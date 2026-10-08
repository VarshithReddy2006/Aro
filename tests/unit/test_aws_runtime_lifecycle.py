"""Comprehensive unit tests for the complete AWS runtime lifecycle and blocker fixes.

Scenarios verified:
A. New relevant Ring event with no active case -> case created, brief generated, proposal persisted, case APPROVAL_PENDING
B. Relevant Ring event matching existing case -> existing case reused, brief generated, no duplicate case
C. Duplicate RingEventReceived -> no duplicate case, no duplicate proposal, idempotent result
D. Irrelevant/in-hours event -> no operational case created
E. AI failure -> deterministic fallback generator engages, case still reaches APPROVAL_PENDING safely
F. Invalid AI proposal -> AIValidationPipeline rejects it, unauthorized proposal not persisted
G. DynamoDB unavailable in demo -> in-memory allowed
H. DynamoDB unavailable in dev -> fails closed (RuntimeError)
I. DynamoDB unavailable in prod -> fails closed (RuntimeError)
J. SSM unavailable in demo -> falls back to demo secret
K. SSM unavailable in dev -> fails closed (RuntimeError)
L. SSM unavailable in prod -> fails closed (RuntimeError)
L2. Empty SSM secret in prod -> fails closed (RuntimeError)
L3. Valid SSM secret in prod -> succeeds
M. Case reaches APPROVAL_PENDING -> ApprovalService accepts valid human approval
N. APPROVAL_PENDING -> direct execution without approval is strictly impossible
O. Approved proposal -> exact proposal hash + version required, ActionExecutor executes (APPROVED -> EXECUTING -> COMPLETED)
P. EventBridge failure -> PutEvents FailedEntryCount > 0 logs structured error without breaking raw durability contract
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from apps.api.src.handlers.api_gateway_adapter import (
    ApiServiceContainer,
)
from apps.api.src.handlers.event_worker import (
    WorkerContainer,
    handle_event_bridge_event,
)
from apps.api.src.handlers.ring_webhook import (
    _emit_eventbridge_notification,
    _get_default_service,
    _reset_cached_secret,
    _resolve_webhook_secret,
)
from apps.api.src.repositories.in_memory import (
    InMemoryActionRepository,
    InMemoryApprovalRepository,
    InMemoryAuditRepository,
    InMemoryCaseRepository,
    InMemoryIdempotencyRepository,
    InMemoryProposalRepository,
)
from apps.api.src.services.action_executor import ActionExecutor
from apps.api.src.services.approval_service import ApprovalService
from apps.api.src.services.bedrock_adapter import FallbackBriefGenerator
from apps.api.src.services.brief_service import BriefService
from apps.api.src.utils.proposal_hash import calculate_proposal_hash
from packages.contracts.enums import (
    ActionStatus,
    ActionType,
    CaseStatus,
    EventProcessingStatus,
    Provenance,
    Role,
)
from packages.contracts.models import (
    Case,
    Location,
    Policy,
    RingDevice,
    RingEvent,
    User,
)
from packages.contracts.state_machine import (
    DirectExecutionWithoutApprovalError,
    transition_case,
)


def _build_test_worker_container() -> WorkerContainer:
    """Build a clean, isolated in-memory WorkerContainer for lifecycle testing."""
    container = WorkerContainer(use_in_memory=True)
    return container


# -----------------------------------------------------------------------------
# PART 1, 2, 3, 4: COMPLETE RUNTIME LIFECYCLE (Scenarios A - F)
# -----------------------------------------------------------------------------


def test_scenario_a_new_relevant_ring_event_creates_case_and_reaches_approval_pending():
    """A. New relevant Ring event with no active case:
    RingEventReceived -> case created -> deterministic context -> brief generated
    -> proposal persisted -> case transitioned to APPROVAL_PENDING.
    """
    container = _build_test_worker_container()
    org_id = "org_alpha"
    device_id = "door_front_main"
    event_id = "evt_lifecycle_01"

    # Seed after-hours location (08:00 - 18:00, event at 02:00)
    container.location_repo.save_location(
        Location(
            location_id="loc_hq",
            organization_id=org_id,
            name="HQ Building",
            timezone="America/New_York",
            business_hours_start="08:00",
            business_hours_end="18:00",
            business_days=[0, 1, 2, 3, 4],
        )
    )
    container.device_repo.save_device(
        RingDevice(
            device_id=device_id,
            location_id="loc_hq",
            name="Front Entrance Doorbell",
            kind="doorbell",
            is_designated_door=True,
        )
    )

    # After-hours physical event
    raw_event = RingEvent(
        event_id=event_id,
        request_id="req_001",
        device_id=device_id,
        event_type="doorbell_ring",
        occurred_at="2026-10-08T02:30:00Z",
        provenance=Provenance.RING_SIGNED,
        signature_verified=True,
        processing_status=EventProcessingStatus.RECEIVED,
        payload={"raw": "ring_data"},
    )
    container.event_repo.save_ring_event(raw_event)

    eb_event = {
        "id": "eb_msg_101",
        "source": "aro.events",
        "detail-type": "RingEventReceived",
        "detail": {
            "event_id": event_id,
            "organization_id": org_id,
            "force_fallback": True,  # Deterministic fallback brief
        },
    }

    resp = handle_event_bridge_event(eb_event, container=container)
    assert resp["status"] == "SUCCESS"
    res = resp["result"]
    assert res["status"] == "CORRELATED"
    assert res["lifecycle_status"] == "APPROVAL_PENDING"
    assert res["is_new_case"] is True
    assert res["case_id"] == f"case_{event_id}"
    assert res["brief_id"] is not None
    assert res["proposal_id"] is not None
    assert res["proposals_count"] >= 1

    # Verify authoritative database state
    stored_case = container.case_repo.get_case(res["case_id"], org_id)
    assert stored_case.status == CaseStatus.APPROVAL_PENDING
    assert stored_case.brief_id == res["brief_id"]
    assert stored_case.active_proposal_id == res["proposal_id"]
    assert stored_case.version >= 2

    # Verify proposal persistence
    stored_prop = container.proposal_repo.get_proposal(
        case_id=res["case_id"],
        proposal_id=res["proposal_id"],
        organization_id=org_id,
    )
    assert stored_prop is not None
    assert stored_prop.proposal_hash is not None


def test_scenario_b_relevant_ring_event_matching_existing_case_reuses_case():
    """B. Relevant Ring event matching existing active case:
    Correlates to existing case without creating a duplicate operational case.
    """
    container = _build_test_worker_container()
    org_id = "org_alpha"
    device_id = "door_front_main"

    now = datetime.now(UTC)
    time1 = (now - timedelta(minutes=3)).isoformat()
    time2 = now.isoformat()

    container.location_repo.save_location(
        Location(
            location_id="loc_hq",
            organization_id=org_id,
            name="HQ Building",
            timezone="UTC",
            business_hours_start="09:00",
            business_hours_end="10:00",
            business_days=[0, 1, 2, 3, 4],
        )
    )
    container.device_repo.save_device(
        RingDevice(
            device_id=device_id,
            location_id="loc_hq",
            name="Front Doorbell",
            kind="doorbell",
            is_designated_door=True,
        )
    )

    # First event creates case_evt_first
    raw1 = RingEvent(
        event_id="evt_first",
        request_id="req_001",
        device_id=device_id,
        event_type="doorbell_ring",
        occurred_at=time1,
        provenance=Provenance.RING_SIGNED,
    )
    container.event_repo.save_ring_event(raw1)

    eb1 = {
        "id": "eb_1",
        "detail-type": "RingEventReceived",
        "detail": {"event_id": "evt_first", "organization_id": org_id, "force_fallback": True},
    }
    r1 = handle_event_bridge_event(eb1, container=container)
    case_id = r1["result"]["case_id"]

    # Second event occurs 3 minutes later on same door
    raw2 = RingEvent(
        event_id="evt_second",
        request_id="req_002",
        device_id=device_id,
        event_type="motion_detected",
        occurred_at=time2,
        provenance=Provenance.RING_SIGNED,
    )
    container.event_repo.save_ring_event(raw2)

    eb2 = {
        "id": "eb_2",
        "detail-type": "RingEventReceived",
        "detail": {"event_id": "evt_second", "organization_id": org_id, "force_fallback": True},
    }
    r2 = handle_event_bridge_event(eb2, container=container)
    assert r2["status"] == "SUCCESS"
    assert r2["result"]["case_id"] == case_id
    assert r2["result"]["is_new_case"] is False

    # Confirm only 1 case was created
    cases = container.case_repo.list_cases(org_id)
    assert len(cases) == 1


def test_scenario_c_duplicate_ring_event_is_idempotent():
    """C. Duplicate RingEventReceived:
    Repeated delivery of the same event returns idempotent result without duplicate
    proposals or version corruptions.
    """
    container = _build_test_worker_container()
    org_id = "org_alpha"
    device_id = "door_front_main"
    event_id = "evt_dup_01"

    container.location_repo.save_location(
        Location(
            location_id="loc_hq",
            organization_id=org_id,
            name="HQ Building",
            timezone="America/New_York",
            business_hours_start="08:00",
            business_hours_end="18:00",
        )
    )
    container.device_repo.save_device(
        RingDevice(
            device_id=device_id,
            location_id="loc_hq",
            name="Front Door",
            kind="doorbell",
            is_designated_door=True,
        )
    )

    raw = RingEvent(
        event_id=event_id,
        request_id="req_dup_01",
        device_id=device_id,
        event_type="doorbell_ring",
        occurred_at="2026-10-08T02:00:00Z",
        provenance=Provenance.RING_SIGNED,
    )
    container.event_repo.save_ring_event(raw)

    eb_event = {
        "id": "eb_msg_dup_1",
        "detail-type": "RingEventReceived",
        "detail": {"event_id": event_id, "organization_id": org_id, "force_fallback": True},
    }

    # First attempt
    res1 = handle_event_bridge_event(eb_event, container=container)
    assert res1["status"] == "SUCCESS"
    case_record1 = container.case_repo.get_case(f"case_{event_id}", org_id)
    version1 = case_record1.version
    proposal_id1 = case_record1.active_proposal_id

    # Second delivery with new EventBridge ID (simulating duplicate/redelivery where lock wasn't identical)
    eb_event2 = {
        "id": "eb_msg_dup_2",
        "detail-type": "RingEventReceived",
        "detail": {"event_id": event_id, "organization_id": org_id, "force_fallback": True},
    }
    res2 = handle_event_bridge_event(eb_event2, container=container)
    assert res2["status"] == "SUCCESS"
    assert res2["result"]["idempotent"] is True
    assert res2["result"]["proposal_id"] == proposal_id1

    case_record2 = container.case_repo.get_case(f"case_{event_id}", org_id)
    assert case_record2.version == version1
    assert case_record2.active_proposal_id == proposal_id1


def test_scenario_d_in_hours_event_creates_no_case():
    """D. Irrelevant/in-hours event:
    Activity during business hours does not create an operational case.
    """
    container = _build_test_worker_container()
    org_id = "org_alpha"
    device_id = "door_front_main"
    event_id = "evt_inhours_01"

    # Business hours: 08:00 - 18:00. Event at 14:00 (in-hours)
    container.location_repo.save_location(
        Location(
            location_id="loc_hq",
            organization_id=org_id,
            name="HQ",
            timezone="UTC",
            business_hours_start="08:00",
            business_hours_end="18:00",
            business_days=[0, 1, 2, 3, 4],  # Thu is 3
        )
    )
    container.device_repo.save_device(
        RingDevice(
            device_id=device_id,
            location_id="loc_hq",
            name="Front Door",
            kind="doorbell",
            is_designated_door=True,
        )
    )

    raw = RingEvent(
        event_id=event_id,
        request_id="req_in_01",
        device_id=device_id,
        event_type="doorbell_ring",
        occurred_at="2026-10-08T14:00:00Z",  # In business hours
        provenance=Provenance.RING_SIGNED,
    )
    container.event_repo.save_ring_event(raw)

    eb_event = {
        "id": "eb_msg_in_01",
        "detail-type": "RingEventReceived",
        "detail": {"event_id": event_id, "organization_id": org_id},
    }
    res = handle_event_bridge_event(eb_event, container=container)
    assert res["status"] == "SUCCESS"
    assert res["result"]["status"] == "UNMATCHED"
    assert res["result"]["case_id"] is None

    # Verify no cases exist
    assert len(container.case_repo.list_cases(org_id)) == 0


def test_scenario_e_ai_failure_engages_deterministic_fallback():
    """E. AI failure:
    Bedrock invocation failure automatically triggers deterministic fallback generator,
    case still safely reaches APPROVAL_PENDING.
    """
    container = _build_test_worker_container()
    org_id = "org_alpha"
    case_id = "case_ai_fail_01"

    case = Case(
        case_id=case_id,
        organization_id=org_id,
        location_id="loc_hq",
        device_id="door_front",
        event_id="evt_fail",
        title="Incident",
        status=CaseStatus.RECEIVED,
    )
    container.case_repo.create_case(case)

    # Primary generator fails with simulated network/API error
    mock_primary = MagicMock()
    mock_primary.generate_raw_brief.side_effect = RuntimeError("Bedrock connection timeout")

    service = BriefService(
        context_builder=container.context_builder,
        case_repository=container.case_repo,
        primary_generator=mock_primary,
        fallback_generator=FallbackBriefGenerator(),
    )

    result = service.generate_brief_for_case(case_id=case_id, organization_id=org_id)
    assert result.is_fallback is True
    assert len(result.proposals) >= 1

    updated_case = container.case_repo.get_case(case_id, org_id)
    assert updated_case.status == CaseStatus.APPROVAL_PENDING
    assert updated_case.active_proposal_id is not None


def test_scenario_f_invalid_ai_proposal_rejected_and_no_unauthorized_action():
    """F. Invalid AI proposal:
    AI validation pipeline rejects unauthorized/hallucinated proposal (e.g. UNLOCK_DOOR).
    BriefService rejects the invalid brief, falls back to deterministic fallback,
    and no unauthorized action is proposed or persisted.
    """
    from apps.api.src.services.ai_validation import AIValidationPipeline

    container = _build_test_worker_container()
    org_id = "org_alpha"
    case_id = "case_invalid_ai_01"

    case = Case(
        case_id=case_id,
        organization_id=org_id,
        location_id="loc_hq",
        device_id="door_front",
        event_id="evt_invalid_ai",
        title="Incident",
        status=CaseStatus.RECEIVED,
    )
    container.case_repo.create_case(case)

    # 1. Direct validation rejects unauthorized action
    context = container.context_builder.build_context(case_id=case_id, organization_id=org_id)
    policy = container.policy_repo.get_policy(org_id) or Policy(
        policy_id=f"pol_{org_id}", organization_id=org_id
    )

    unauthorized_json = """{
      "summary": "Suspicious activity detected at entrance.",
      "facts": ["Motion detected"],
      "unknowns": ["Identity"],
      "context_match": "Unmatched",
      "proposals": [
        {
          "action_type": "UNLOCK_DOOR",
          "reason": "Unlock door to inspect area",
          "parameters": {}
        }
      ]
    }"""
    val_result = AIValidationPipeline.validate(unauthorized_json, context.ai_input, policy)
    assert val_result.is_valid is False

    # 2. In BriefService, returning unauthorized output triggers fallback
    mock_primary = MagicMock()
    mock_primary.generate_raw_brief.return_value = unauthorized_json

    service = BriefService(
        context_builder=container.context_builder,
        case_repository=container.case_repo,
        primary_generator=mock_primary,
        fallback_generator=FallbackBriefGenerator(),
    )

    result = service.generate_brief_for_case(case_id=case_id, organization_id=org_id)
    # BriefService caught invalid proposal and switched to fallback generator
    assert result.is_fallback is True
    for p in result.proposals:
        assert p.action_type in [
            ActionType.NOTIFY_OPERATOR,
            ActionType.MARK_FOR_REVIEW,
            ActionType.REQUEST_OPERATOR_CONFIRMATION,
            ActionType.RECORD_NO_ACTION,
        ]
        assert p.action_type != "UNLOCK_DOOR"

    updated_case = container.case_repo.get_case(case_id, org_id)
    assert updated_case.status == CaseStatus.APPROVAL_PENDING


# -----------------------------------------------------------------------------
# PART 6: FAIL CLOSED ON DYNAMODB (Scenarios G, H, I)
# -----------------------------------------------------------------------------


def test_scenario_g_dynamodb_unavailable_in_demo_allows_in_memory(monkeypatch):
    """G. DynamoDB unavailable in demo environment: In-memory fallback is allowed."""
    monkeypatch.setenv("ARO_ENV", "demo")
    monkeypatch.setenv("ARO_TABLE_NAME", "non_existent_table")

    # In demo mode, table connection error falls back to in-memory without raising
    service = _get_default_service()
    assert service is not None

    worker = WorkerContainer()
    assert worker is not None

    api = ApiServiceContainer()
    assert api is not None


def test_scenario_h_dynamodb_unavailable_in_dev_fails_closed(monkeypatch):
    """H. DynamoDB unavailable in dev environment: MUST fail closed with fatal RuntimeError."""
    monkeypatch.setenv("ARO_ENV", "dev")
    monkeypatch.setenv("RING_SECRET_PARAM", "/aro/dev/ring/webhook-secret")

    # 1. Missing table name raises RuntimeError
    monkeypatch.delenv("ARO_TABLE_NAME", raising=False)
    with patch("boto3.client") as mock_ssm:
        mock_ssm.return_value.get_parameter.return_value = {"Parameter": {"Value": "dev_secret"}}
        with pytest.raises(RuntimeError, match="ARO_TABLE_NAME"):
            _get_default_service()

        with pytest.raises(RuntimeError, match="ARO_TABLE_NAME"):
            WorkerContainer()

        with pytest.raises(RuntimeError, match="ARO_TABLE_NAME"):
            ApiServiceContainer()

    # 2. Connection failure raises RuntimeError
    monkeypatch.setenv("ARO_TABLE_NAME", "dev-table")
    with (
        patch("boto3.resource", side_effect=Exception("DynamoDB unreachable")),
        patch("boto3.client") as mock_ssm,
    ):
        mock_ssm.return_value.get_parameter.return_value = {"Parameter": {"Value": "dev_secret"}}
        with pytest.raises(RuntimeError, match="DynamoDB"):
            _get_default_service()

        with pytest.raises(RuntimeError, match="DynamoDB"):
            WorkerContainer()

        with pytest.raises(RuntimeError, match="DynamoDB"):
            ApiServiceContainer()


def test_scenario_i_dynamodb_unavailable_in_prod_fails_closed(monkeypatch):
    """I. DynamoDB unavailable in prod environment: MUST fail closed with fatal RuntimeError."""
    monkeypatch.setenv("ARO_ENV", "prod")
    monkeypatch.setenv("RING_SECRET_PARAM", "/aro/prod/ring/webhook-secret")

    # 1. Missing table name raises RuntimeError
    monkeypatch.delenv("ARO_TABLE_NAME", raising=False)
    with patch("boto3.client") as mock_ssm:
        mock_ssm.return_value.get_parameter.return_value = {"Parameter": {"Value": "prod_secret"}}
        with pytest.raises(RuntimeError, match="ARO_TABLE_NAME"):
            _get_default_service()

        with pytest.raises(RuntimeError, match="ARO_TABLE_NAME"):
            WorkerContainer()

        with pytest.raises(RuntimeError, match="ARO_TABLE_NAME"):
            ApiServiceContainer()

    # 2. Connection failure raises RuntimeError
    monkeypatch.setenv("ARO_TABLE_NAME", "prod-table")
    with (
        patch("boto3.resource", side_effect=Exception("DynamoDB unreachable")),
        patch("boto3.client") as mock_ssm,
    ):
        mock_ssm.return_value.get_parameter.return_value = {"Parameter": {"Value": "prod_secret"}}
        with pytest.raises(RuntimeError, match="DynamoDB"):
            _get_default_service()

        with pytest.raises(RuntimeError, match="DynamoDB"):
            WorkerContainer()

        with pytest.raises(RuntimeError, match="DynamoDB"):
            ApiServiceContainer()


# -----------------------------------------------------------------------------
# PART 7: FAIL CLOSED ON RING WEBHOOK SECRET (Scenarios J, K, L, L2, L3)
# -----------------------------------------------------------------------------


def test_scenario_j_ssm_unavailable_in_demo_falls_back_to_demo_secret(monkeypatch):
    """J. SSM unavailable in demo: Safe demo fallback is allowed."""
    monkeypatch.setenv("ARO_ENV", "demo")
    monkeypatch.delenv("RING_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("RING_SECRET_PARAM", "/aro/demo/ring/webhook-secret")
    _reset_cached_secret()

    with patch("boto3.client", side_effect=Exception("SSM offline")):
        secret = _resolve_webhook_secret()
        assert secret == "default_insecure_test_secret"


def test_scenario_k_ssm_unavailable_in_dev_fails_closed(monkeypatch):
    """K. SSM unavailable in dev: Fails closed, never uses default insecure secret."""
    monkeypatch.setenv("ARO_ENV", "dev")
    monkeypatch.delenv("RING_WEBHOOK_SECRET", raising=False)
    _reset_cached_secret()

    with (
        patch("boto3.client", side_effect=Exception("SSM Parameter not found")),
        pytest.raises(RuntimeError, match="Ring secret from SSM"),
    ):
        _resolve_webhook_secret()


def test_scenario_l_ssm_unavailable_in_prod_fails_closed(monkeypatch):
    """L. SSM unavailable in prod: Fails closed, never uses default insecure secret."""
    monkeypatch.setenv("ARO_ENV", "prod")
    monkeypatch.delenv("RING_WEBHOOK_SECRET", raising=False)
    _reset_cached_secret()

    with (
        patch("boto3.client", side_effect=Exception("Access Denied to SSM")),
        pytest.raises(RuntimeError, match="Ring secret from SSM"),
    ):
        _resolve_webhook_secret()


def test_scenario_l2_empty_ssm_secret_in_prod_fails_closed(monkeypatch):
    """L2. Empty secret in SSM parameter in prod: Fails closed."""
    monkeypatch.setenv("ARO_ENV", "prod")
    _reset_cached_secret()

    mock_client = MagicMock()
    mock_client.get_parameter.return_value = {"Parameter": {"Value": "   "}}
    with (
        patch("boto3.client", return_value=mock_client),
        pytest.raises(RuntimeError, match="empty in prod"),
    ):
        _resolve_webhook_secret()


def test_scenario_l3_valid_ssm_secret_in_prod_succeeds(monkeypatch):
    """L3. Valid SSM secret in prod: Resolves successfully."""
    monkeypatch.setenv("ARO_ENV", "prod")
    _reset_cached_secret()

    mock_client = MagicMock()
    mock_client.get_parameter.return_value = {
        "Parameter": {"Value": "super_secure_prod_webhook_secret_999"}
    }
    with patch("boto3.client", return_value=mock_client):
        secret = _resolve_webhook_secret()
        assert secret == "super_secure_prod_webhook_secret_999"


# -----------------------------------------------------------------------------
# PART 4, 10: APPROVAL AND EXECUTION LIFECYCLE (Scenarios M, N, O)
# -----------------------------------------------------------------------------


def test_scenario_m_n_o_approval_and_execution_lifecycle():
    """M, N, O. Complete approval and execution flow:
    - Case in APPROVAL_PENDING accepts human approval from authorized operator
    - Direct execution from APPROVAL_PENDING is rejected
    - Approved proposal with exact proposal hash and version executes deterministically.
    """
    case_repo = InMemoryCaseRepository()
    approval_repo = InMemoryApprovalRepository()
    action_repo = InMemoryActionRepository(case_repo=case_repo)
    audit_repo = InMemoryAuditRepository()
    idempotency_repo = InMemoryIdempotencyRepository()
    proposal_repo = InMemoryProposalRepository()

    org_id = "org_ops_01"
    case_id = "case_lifecycle_01"
    proposal_id = "prop_01"

    # 1. Create proposal and case in APPROVAL_PENDING
    p_hash = calculate_proposal_hash(
        case_id=case_id,
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed at designated entrance",
        parameters={"urgency": "normal"},
    )
    from packages.contracts.models import Proposal

    proposal = Proposal(
        proposal_id=proposal_id,
        case_id=case_id,
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed at designated entrance",
        parameters={"urgency": "normal"},
        proposal_hash=p_hash,
    )
    proposal_repo.save_proposal(proposal, org_id)

    case = Case(
        case_id=case_id,
        organization_id=org_id,
        location_id="loc_01",
        device_id="door_01",
        event_id="evt_01",
        title="Operational Incident",
        status=CaseStatus.APPROVAL_PENDING,
        version=2,
        active_proposal_id=proposal_id,
    )
    case_repo.create_case(case)

    approval_service = ApprovalService(
        case_repo=case_repo,
        approval_repo=approval_repo,
        audit_repo=audit_repo,
        proposal_repo=proposal_repo,
    )
    action_executor = ActionExecutor(
        case_repo=case_repo,
        approval_repo=approval_repo,
        action_repo=action_repo,
        audit_repo=audit_repo,
        proposal_repo=proposal_repo,
        idempotency_repo=idempotency_repo,
    )

    # Scenario N: Attempt direct execution from APPROVAL_PENDING (Security Invariant)
    with pytest.raises(DirectExecutionWithoutApprovalError):
        transition_case(case, CaseStatus.EXECUTING)

    with pytest.raises(DirectExecutionWithoutApprovalError):
        # Attempting executor before approval fails
        action_executor.execute_action(
            case_id=case_id,
            approval_id="non_existent",
            user=User(
                user_id="usr_op",
                organization_id=org_id,
                name="Operator",
                email="op@aro.internal",
                role=Role.OPERATOR,
            ),
            expected_case_version=2,
            organization_id=org_id,
        )

    # Scenario M: Human operator approves with exact hash and expected version
    operator = User(
        user_id="usr_op_1",
        organization_id=org_id,
        name="Operator 1",
        email="op1@aro.internal",
        role=Role.OPERATOR,
    )
    approval = approval_service.approve_case(
        case_id=case_id,
        proposal_id=proposal_id,
        proposal_hash=p_hash,
        user=operator,
        expected_case_version=2,
        organization_id=org_id,
    )
    assert approval is not None

    # Verify case is now APPROVED
    approved_case = case_repo.get_case(case_id, org_id)
    assert approved_case.status == CaseStatus.APPROVED
    assert approved_case.version == 3

    # Scenario O: ActionExecutor executes deterministically (APPROVED -> EXECUTING -> COMPLETED)
    exec_result = action_executor.execute_action(
        case_id=case_id,
        approval_id=approval.approval_id,
        user=operator,
        expected_case_version=3,
        organization_id=org_id,
    )
    assert exec_result.action.status == ActionStatus.SUCCEEDED

    # Verify case transitioned to COMPLETED
    completed_case = case_repo.get_case(case_id, org_id)
    assert completed_case.status == CaseStatus.COMPLETED


# -----------------------------------------------------------------------------
# PART 8: EVENTBRIDGE FAILURE MONITORING (Scenario P)
# -----------------------------------------------------------------------------


def test_scenario_p_eventbridge_put_events_failure_logged_without_raising(monkeypatch):
    """P. EventBridge failure: PutEvents FailedEntryCount > 0 logs error without breaking webhook acknowledgment."""
    monkeypatch.setenv("ARO_EVENT_BUS_NAME", "aro-events-bus")

    mock_client = MagicMock()
    mock_client.put_events.return_value = {
        "FailedEntryCount": 1,
        "Entries": [
            {
                "ErrorCode": "InternalFailure",
                "ErrorMessage": "EventBridge throttling limit reached",
            }
        ],
    }

    with patch("boto3.client", return_value=mock_client):
        # Must not raise an exception, preserving raw persistence acknowledgment
        _emit_eventbridge_notification("evt_test_eb", "req_test_eb")
        mock_client.put_events.assert_called_once()
