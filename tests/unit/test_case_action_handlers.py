"""Unit tests for case action HTTP handlers (approve, reject, execute)."""

import json

import pytest

from apps.api.src.handlers.case_actions import (
    handle_approve_case,
    handle_execute_case,
    handle_reject_case,
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
from apps.api.src.utils.proposal_hash import calculate_proposal_hash
from packages.contracts.enums import (
    ActionType,
    CaseStatus,
)
from packages.contracts.models import (
    Case,
    Proposal,
)


@pytest.fixture
def handler_context():
    case_repo = InMemoryCaseRepository()
    approval_repo = InMemoryApprovalRepository()
    action_repo = InMemoryActionRepository(case_repo=case_repo)
    audit_repo = InMemoryAuditRepository()
    proposal_repo = InMemoryProposalRepository()
    idempotency_repo = InMemoryIdempotencyRepository()

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

    case_id = "case_hdl_01"
    org_id = "org_test"
    h = calculate_proposal_hash(
        case_id=case_id,
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours entrance motion",
        parameters={"message": "Duty alert", "urgency": "normal"},
    )
    prop = Proposal(
        proposal_id="prop_hdl_01",
        case_id=case_id,
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours entrance motion",
        parameters={"message": "Duty alert", "urgency": "normal"},
        proposal_hash=h,
    )
    proposal_repo.save_proposal(prop, org_id)

    case = Case(
        case_id=case_id,
        organization_id=org_id,
        location_id="loc_1",
        device_id="dev_1",
        event_id="evt_1",
        title="Handler Test Case",
        status=CaseStatus.APPROVAL_PENDING,
        version=1,
        active_proposal_id=prop.proposal_id,
    )
    case_repo.create_case(case)

    return {
        "approval_service": approval_service,
        "action_executor": action_executor,
        "case": case,
        "proposal": prop,
    }


def test_handle_approve_case_success(handler_context):
    case = handler_context["case"]
    prop = handler_context["proposal"]
    service = handler_context["approval_service"]

    event = {
        "pathParameters": {"id": case.case_id},
        "headers": {
            "x-user-id": "usr_op_1",
            "x-user-role": "OPERATOR",
            "x-organization-id": "org_test",
        },
        "body": json.dumps(
            {
                "proposal_id": prop.proposal_id,
                "proposal_hash": prop.proposal_hash,
                "case_version": 1,
            }
        ),
    }

    resp = handle_approve_case(event, service=service)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "APPROVED"
    assert body["approval"]["proposal_hash"] == prop.proposal_hash


def test_handle_approve_case_bad_request_missing_fields(handler_context):
    case = handler_context["case"]
    service = handler_context["approval_service"]

    event = {
        "pathParameters": {"id": case.case_id},
        "headers": {"x-user-role": "OPERATOR"},
        "body": json.dumps({"proposal_id": "prop_1"}),  # Missing proposal_hash & version
    }

    resp = handle_approve_case(event, service=service)
    assert resp["statusCode"] == 400


def test_handle_approve_case_unauthorized_viewer(handler_context):
    case = handler_context["case"]
    prop = handler_context["proposal"]
    service = handler_context["approval_service"]

    event = {
        "pathParameters": {"id": case.case_id},
        "headers": {
            "x-user-id": "usr_view_1",
            "x-user-role": "VIEWER",
            "x-organization-id": "org_test",
        },
        "body": json.dumps(
            {
                "proposal_id": prop.proposal_id,
                "proposal_hash": prop.proposal_hash,
                "case_version": 1,
            }
        ),
    }

    resp = handle_approve_case(event, service=service)
    assert resp["statusCode"] == 403


def test_handle_reject_case_success(handler_context):
    case = handler_context["case"]
    prop = handler_context["proposal"]
    service = handler_context["approval_service"]

    event = {
        "pathParameters": {"id": case.case_id},
        "headers": {
            "x-user-id": "usr_op_1",
            "x-user-role": "OPERATOR",
            "x-organization-id": "org_test",
        },
        "body": json.dumps(
            {
                "proposal_id": prop.proposal_id,
                "proposal_hash": prop.proposal_hash,
                "reason": "False alarm caused by facility wind banner",
                "case_version": 1,
            }
        ),
    }

    resp = handle_reject_case(event, service=service)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "REJECTED"


def test_handle_execute_case_full_flow(handler_context):
    case = handler_context["case"]
    prop = handler_context["proposal"]
    approval_service = handler_context["approval_service"]
    executor = handler_context["action_executor"]

    # 1. Approve case first
    approve_event = {
        "pathParameters": {"id": case.case_id},
        "headers": {
            "x-user-id": "usr_op_1",
            "x-user-role": "OPERATOR",
            "x-organization-id": "org_test",
        },
        "body": json.dumps(
            {
                "proposal_id": prop.proposal_id,
                "proposal_hash": prop.proposal_hash,
                "case_version": 1,
            }
        ),
    }
    approve_resp = handle_approve_case(approve_event, service=approval_service)
    assert approve_resp["statusCode"] == 200
    approval_data = json.loads(approve_resp["body"])["approval"]
    approval_id = approval_data["approval_id"]

    # 2. Execute case
    execute_event = {
        "pathParameters": {"id": case.case_id},
        "headers": {
            "x-user-id": "usr_op_1",
            "x-user-role": "OPERATOR",
            "x-organization-id": "org_test",
        },
        "body": json.dumps(
            {
                "approval_id": approval_id,
                "case_version": 2,  # Advanced after approval
            }
        ),
    }
    exec_resp = handle_execute_case(execute_event, executor=executor)
    assert exec_resp["statusCode"] == 200
    body = json.loads(exec_resp["body"])
    assert body["status"] == "EXECUTED"
    assert body["action"]["status"] == "SUCCEEDED"
