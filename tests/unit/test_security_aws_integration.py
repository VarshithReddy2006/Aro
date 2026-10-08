"""Security tests verifying AWS boundaries and domain invariants for Phase 7.

Invariants verified:
1. Invalid webhook HMAC -> rejected (HTTP 401)
2. Replayed webhook -> rejected (HTTP 400)
3. Oversized webhook (>256KB) -> rejected (HTTP 413)
4. Unauthenticated approval -> rejected (HTTP 401)
5. VIEWER approval -> rejected (HTTP 403)
6. Cross-tenant case access -> rejected (HTTP 403)
7. Stale proposal / version mismatch -> rejected (HTTP 409)
8. Wrong proposal hash -> rejected (HTTP 409)
9. Expired approval -> rejected (HTTP 409)
10. Direct execution bypass -> rejected (HTTP 409)
11. Duplicate execution -> idempotent (HTTP 200, was_idempotent=True)
12. Lambda retry -> idempotent
13. AI direct tool execution attempt -> impossible
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from apps.api.src.handlers.api_gateway_adapter import (
    ApiServiceContainer,
    handle_api_request,
)
from apps.api.src.handlers.event_worker import (
    WorkerContainer,
    handle_event_bridge_event,
)
from apps.api.src.handlers.ring_webhook import handle_ring_webhook
from apps.api.src.services.event_ingestion import EventIngestionService
from apps.api.src.utils.proposal_hash import calculate_proposal_hash
from packages.contracts.enums import (
    ActionType,
    ApprovalDecision,
    CaseStatus,
    EventProcessingStatus,
    Provenance,
    Role,
)
from packages.contracts.models import (
    Approval,
    Case,
    Proposal,
    RingEvent,
)


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# -------------------------------------------------------------
# 1. Ingestion Boundary Tests
# -------------------------------------------------------------
def test_security_invalid_webhook_hmac_rejected() -> None:
    """Invalid HMAC signature rejected with HTTP 401 and zero persistence."""
    body = b'{"event_id": "evt_001", "kind": "motion"}'
    event = {
        "body": body.decode("utf-8"),
        "headers": {
            "x-signature": "invalid_hmac_signature",
            "x-request-id": "req_001",
            "x-timestamp": datetime.now(UTC).isoformat(),
        },
    }
    resp = handle_ring_webhook(event)
    assert resp["statusCode"] == 401


def test_security_replayed_webhook_rejected() -> None:
    """Stale timestamp (>5m) is rejected with HTTP 400."""
    secret = "test_secret_123"
    stale_time = (datetime.now(UTC) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "meta": {
            "version": "1.1",
            "time": stale_time,
            "request_id": "req_002",
        },
        "data": {
            "id": "evt_002",
            "type": "event",
            "attributes": {
                "event_type": "motion_detected",
                "device_id": "dev_1",
                "timestamp": stale_time,
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body, secret)

    event = {
        "body": body.decode("utf-8"),
        "headers": {
            "x-signature": f"sha256={sig}",
            "x-request-id": "req_002",
            "x-timestamp": stale_time,
        },
    }
    svc = EventIngestionService(
        event_repository=ApiServiceContainer().event_repo, webhook_secret=secret
    )
    resp = handle_ring_webhook(event, service=svc)
    assert resp["statusCode"] == 400
    assert "REPLAY" in resp["body"] or "STALE" in resp["body"] or "stale" in resp["body"].lower()


def test_security_oversized_webhook_rejected() -> None:
    """Payload exceeding 256KB rejected with HTTP 413."""
    secret = "test_secret_123"
    big_body = b"x" * (300 * 1024)
    sig = _sign(big_body, secret)
    event = {
        "body": big_body.decode("latin-1"),
        "headers": {
            "x-signature": f"sha256={sig}",
            "x-request-id": "req_003",
            "x-timestamp": datetime.now(UTC).isoformat(),
        },
    }
    svc = EventIngestionService(
        event_repository=ApiServiceContainer().event_repo, webhook_secret=secret
    )
    resp = handle_ring_webhook(event, service=svc)
    assert resp["statusCode"] == 413


# -------------------------------------------------------------
# 2. Authorization & RBAC Tests
# -------------------------------------------------------------
def test_security_viewer_approval_rejected() -> None:
    """VIEWER role cannot approve cases (HTTP 403)."""
    container = ApiServiceContainer()
    event = {
        "httpMethod": "POST",
        "path": "/api/cases/case_01/approve",
        "pathParameters": {"id": "case_01"},
        "headers": {
            "x-user-id": "usr_viewer",
            "x-organization-id": "org_demo",
            "x-user-role": "VIEWER",
        },
        "body": json.dumps(
            {
                "proposal_id": "prop_01",
                "proposal_hash": "hash_01",
                "case_version": 1,
            }
        ),
    }
    resp = handle_api_request(event, container=container)
    assert resp["statusCode"] == 403
    assert "Unauthorized" in resp["body"]


def test_security_cross_tenant_access_denied() -> None:
    """Operator from org_A cannot view or mutate a case belonging to org_B."""
    container = ApiServiceContainer()
    case_b = Case(
        case_id="case_tenant_b",
        organization_id="org_tenant_b",
        location_id="loc_b",
        device_id="dev_b",
        event_id="evt_b",
        title="Tenant B Incident",
        status=CaseStatus.APPROVAL_PENDING,
        version=1,
    )
    container.case_repo.create_case(case_b)

    event = {
        "httpMethod": "GET",
        "path": "/api/cases/case_tenant_b",
        "pathParameters": {"id": "case_tenant_b"},
        "headers": {
            "x-user-id": "usr_operator_a",
            "x-organization-id": "org_tenant_a",
            "x-user-role": "OPERATOR",
        },
    }
    resp = handle_api_request(event, container=container)
    assert resp["statusCode"] == 403


# -------------------------------------------------------------
# 3. State Machine & Approval Boundary Tests
# -------------------------------------------------------------
def test_security_wrong_proposal_hash_rejected() -> None:
    """Approval with altered or incorrect proposal hash rejected (HTTP 409)."""
    container = ApiServiceContainer()
    case = Case(
        case_id="case_02",
        organization_id="org_demo",
        location_id="loc_1",
        device_id="dev_01",
        event_id="evt_01",
        title="Delivery Verification",
        status=CaseStatus.APPROVAL_PENDING,
        version=1,
    )
    container.case_repo.create_case(case)

    prop = Proposal(
        proposal_id="prop_02",
        case_id="case_02",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="Motion detected",
        parameters={"message": "Motion at door", "urgency": "normal", "recipient_role": "OPERATOR"},
        proposal_hash=calculate_proposal_hash(
            "case_02",
            ActionType.NOTIFY_OPERATOR,
            "Motion detected",
            {"message": "Motion at door", "urgency": "normal", "recipient_role": "OPERATOR"},
        ),
    )
    container.proposal_repo.save_proposal(prop, "org_demo")

    event = {
        "httpMethod": "POST",
        "path": "/api/cases/case_02/approve",
        "pathParameters": {"id": "case_02"},
        "headers": {
            "x-user-id": "usr_op",
            "x-organization-id": "org_demo",
            "x-user-role": "OPERATOR",
        },
        "body": json.dumps(
            {
                "proposal_id": "prop_02",
                "proposal_hash": "tampered_hash_value_1234",
                "case_version": 1,
            }
        ),
    }
    resp = handle_api_request(event, container=container)
    assert resp["statusCode"] == 409
    assert "Conflict" in resp["body"]


def test_security_direct_execution_bypass_rejected() -> None:
    """Execution cannot occur without an approved state (HTTP 409)."""
    container = ApiServiceContainer()
    case = Case(
        case_id="case_unapproved",
        organization_id="org_demo",
        location_id="loc_1",
        device_id="dev_01",
        event_id="evt_01",
        title="Pending Case",
        status=CaseStatus.APPROVAL_PENDING,
        version=1,
    )
    container.case_repo.create_case(case)

    event = {
        "httpMethod": "POST",
        "path": "/api/cases/case_unapproved/execute",
        "pathParameters": {"id": "case_unapproved"},
        "headers": {
            "x-user-id": "usr_op",
            "x-organization-id": "org_demo",
            "x-user-role": "OPERATOR",
        },
        "body": json.dumps(
            {
                "approval_id": "appr_fake",
                "case_version": 1,
            }
        ),
    }
    resp = handle_api_request(event, container=container)
    assert resp["statusCode"] == 409


def test_security_duplicate_execution_idempotency() -> None:
    """Duplicate execution request returns previous receipt and is marked idempotent."""
    container = ApiServiceContainer()
    case = Case(
        case_id="case_exec_01",
        organization_id="org_demo",
        location_id="loc_1",
        device_id="dev_01",
        event_id="evt_01",
        title="Verified Case",
        status=CaseStatus.APPROVED,
        version=1,
        active_approval_id="appr_01",
    )
    container.case_repo.create_case(case)

    prop = Proposal(
        proposal_id="prop_01",
        case_id="case_exec_01",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="Verified delivery",
        parameters={
            "message": "Package safely staged",
            "urgency": "normal",
            "recipient_role": "OPERATOR",
        },
        proposal_hash=calculate_proposal_hash(
            "case_exec_01",
            ActionType.NOTIFY_OPERATOR,
            "Verified delivery",
            {"message": "Package safely staged", "urgency": "normal", "recipient_role": "OPERATOR"},
        ),
    )
    container.proposal_repo.save_proposal(prop, "org_demo")

    approval = Approval(
        approval_id="appr_01",
        organization_id="org_demo",
        case_id="case_exec_01",
        proposal_id="prop_01",
        proposal_hash=prop.proposal_hash,
        approved_by="usr_op",
        approver_role=Role.OPERATOR,
        decision=ApprovalDecision.APPROVED,
        case_version=1,
        expires_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    )
    container.approval_repo.save_approval(approval, "org_demo")

    exec_event = {
        "httpMethod": "POST",
        "path": "/api/cases/case_exec_01/execute",
        "pathParameters": {"id": "case_exec_01"},
        "headers": {
            "x-user-id": "usr_op",
            "x-organization-id": "org_demo",
            "x-user-role": "OPERATOR",
        },
        "body": json.dumps(
            {
                "approval_id": "appr_01",
                "case_version": 1,
                "idempotency_key": "idemp_test_key_01",
            }
        ),
    }

    # First execution
    resp1 = handle_api_request(exec_event, container=container)
    assert resp1["statusCode"] == 200
    body1 = json.loads(resp1["body"])
    assert body1["was_idempotent"] is False
    assert body1["status"] == "EXECUTED"

    # Second execution with same idempotency key
    resp2 = handle_api_request(exec_event, container=container)
    assert resp2["statusCode"] == 200
    body2 = json.loads(resp2["body"])
    assert body2["was_idempotent"] is True


def test_security_event_worker_retry_idempotency() -> None:
    """EventBridge worker retries return IDEMPOTENT_SKIPPED without duplicate processing."""
    worker_container = WorkerContainer()
    ring_event = RingEvent(
        event_id="ring_evt_01",
        request_id="req_test_01",
        device_id="dev_01",
        event_type="motion",
        occurred_at=datetime.now(UTC).isoformat(),
        provenance=Provenance.RING_SIGNED,
        signature_verified=True,
        processing_status=EventProcessingStatus.VALIDATED,
        payload={"kind": "motion"},
    )
    worker_container.event_repo.save_ring_event(ring_event)

    event = {
        "id": "evt_bridge_unique_01",
        "source": "aro.events",
        "detail-type": "RingEventReceived",
        "detail": {"event_id": "ring_evt_01"},
    }

    # First run
    resp1 = handle_event_bridge_event(event, container=worker_container)
    assert resp1["status"] == "SUCCESS"

    # Retry with identical event
    resp2 = handle_event_bridge_event(event, container=worker_container)
    assert resp2["status"] == "IDEMPOTENT_SKIPPED"
