"""HTTP handlers for case approval, rejection, and deterministic action execution.

Follows AWS API Gateway Lambda Proxy integration standards:
- POST /api/cases/{id}/approve -> handle_approve_case
- POST /api/cases/{id}/reject  -> handle_reject_case
- POST /api/cases/{id}/execute -> handle_execute_case
"""

import json
import logging
import os
from typing import Any

from packages.contracts.enums import Role
from packages.contracts.models import User
from packages.contracts.state_machine import (
    ApprovalExpiredError,
    DirectExecutionWithoutApprovalError,
    InvalidStateTransitionError,
    ProposalHashMismatchError,
    StateMachineError,
    StateVersionMismatchError,
    TerminalStateError,
    UnauthorizedApproverError,
)

from ..repositories.errors import (
    AlreadyCompletedError,
    AlreadyExecutingError,
    ConflictError,
    NotFoundError,
    OrganizationAccessDeniedError,
)
from ..services.action_executor import ActionExecutor
from ..services.approval_service import ApprovalService

logger = logging.getLogger("aro.case_action_handlers")


def _json_response(status_code: int, body_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body_dict),
    }


def _extract_user_and_case(
    event: dict[str, Any], user: User | None = None
) -> tuple[User, str, dict[str, Any]]:
    # Extract case_id from path parameters
    path_params = event.get("pathParameters") or {}
    case_id = path_params.get("id") or path_params.get("case_id") or ""
    if not case_id:
        raise ValueError("Missing 'case_id' in path parameters")

    if user is None:
        req_context = event.get("requestContext") or {}
        auth_ctx = req_context.get("authorizer") or {}
        claims = auth_ctx.get("claims") or {}
        is_demo_mode = os.environ.get("ARO_ENV", "demo").strip().lower() in {
            "demo",
            "local",
            "test",
        }

        if claims and (claims.get("sub") or claims.get("cognito:username")):
            user_id = str(claims.get("sub") or claims.get("cognito:username"))
            org_id = claims.get("custom:tenant_id") or claims.get("custom:organization_id")
            if not org_id:
                raise ValueError("Cognito authorizer claims missing tenant identity")
            email = str(claims.get("email", f"{user_id}@aro.internal"))
            role_claim = claims.get("custom:role")
            groups_claim = claims.get("cognito:groups", [])
            if isinstance(groups_claim, str):
                groups = [
                    g.strip().upper()
                    for g in groups_claim.replace("[", "").replace("]", "").split(",")
                    if g.strip()
                ]
            elif isinstance(groups_claim, list):
                groups = [str(g).upper() for g in groups_claim]
            else:
                groups = []

            if role_claim:
                try:
                    role = Role(str(role_claim).upper())
                except ValueError:
                    role = Role.VIEWER
            elif "ADMIN" in groups:
                role = Role.ADMIN
            elif "OPERATOR" in groups:
                role = Role.OPERATOR
            else:
                role = Role.VIEWER

            user = User(
                user_id=user_id,
                organization_id=str(org_id),
                email=email,
                name="Aro Authenticated User",
                role=role,
            )
        elif not is_demo_mode:
            raise ValueError(
                "Production authentication required: Request lacks valid Cognito authorizer claims."
            )
        else:
            # Extract headers for isolated local/demo execution
            raw_headers = event.get("headers") or {}
            headers = {k.lower(): str(v) for k, v in raw_headers.items()}

            user_id = headers.get("x-user-id") or headers.get("x-actor-id") or "usr_ops_default"
            org_id = headers.get("x-tenant-id") or headers.get("x-organization-id") or "org_default"
            role_str = (
                headers.get("x-user-role") or headers.get("x-actor-role") or Role.OPERATOR.value
            ).upper()
            try:
                role = Role(role_str)
            except ValueError:
                role = Role.OPERATOR

            user = User(
                user_id=user_id,
                organization_id=org_id,
                email=f"{user_id}@aro.internal",
                name="Operator",
                role=role,
            )

    # Parse body
    raw_body = event.get("body") or "{}"
    if isinstance(raw_body, str):
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON body: {exc}") from exc
    elif isinstance(raw_body, dict):
        body = raw_body
    else:
        body = {}

    return user, case_id, body


def handle_approve_case(
    event: dict[str, Any],
    context: Any = None,
    service: ApprovalService | None = None,
    user: User | None = None,
) -> dict[str, Any]:
    """HTTP handler for POST /api/cases/{id}/approve."""
    if service is None:
        return _json_response(500, {"error": "ApprovalService not configured"})

    try:
        resolved_user, case_id, body = _extract_user_and_case(event, user=user)
    except ValueError as exc:
        return _json_response(400, {"error": str(exc)})

    proposal_id = body.get("proposal_id")
    proposal_hash = body.get("proposal_hash")
    case_version = body.get("case_version")
    expires_at = body.get("expires_at")

    if not proposal_id or not proposal_hash or case_version is None:
        return _json_response(
            400,
            {
                "error": "Missing required fields: proposal_id, proposal_hash, and case_version are required"
            },
        )

    try:
        approval = service.approve_case(
            case_id=case_id,
            proposal_id=str(proposal_id),
            proposal_hash=str(proposal_hash),
            user=resolved_user,
            expected_case_version=int(case_version),
            expires_at=str(expires_at) if expires_at else None,
        )
        return _json_response(200, {"status": "APPROVED", "approval": approval.model_dump()})

    except UnauthorizedApproverError as exc:
        return _json_response(403, {"error": "Unauthorized", "details": str(exc)})
    except OrganizationAccessDeniedError as exc:
        return _json_response(403, {"error": "Access Denied", "details": str(exc)})
    except NotFoundError as exc:
        return _json_response(404, {"error": "Not Found", "details": str(exc)})
    except (
        StateVersionMismatchError,
        ProposalHashMismatchError,
        ApprovalExpiredError,
        DirectExecutionWithoutApprovalError,
        TerminalStateError,
        InvalidStateTransitionError,
        ConflictError,
    ) as exc:
        return _json_response(409, {"error": "Conflict", "details": str(exc)})
    except Exception:
        logger.exception("Unexpected error in handle_approve_case for case %s", case_id)
        return _json_response(500, {"error": "Internal server error"})


def handle_reject_case(
    event: dict[str, Any],
    context: Any = None,
    service: ApprovalService | None = None,
    user: User | None = None,
) -> dict[str, Any]:
    """HTTP handler for POST /api/cases/{id}/reject."""
    if service is None:
        return _json_response(500, {"error": "ApprovalService not configured"})

    try:
        resolved_user, case_id, body = _extract_user_and_case(event, user=user)
    except ValueError as exc:
        return _json_response(400, {"error": str(exc)})

    proposal_id = body.get("proposal_id")
    proposal_hash = body.get("proposal_hash")
    reason = body.get("reason", "Operator rejected proposal")
    case_version = body.get("case_version")

    if not proposal_id or not proposal_hash or case_version is None:
        return _json_response(
            400,
            {
                "error": "Missing required fields: proposal_id, proposal_hash, and case_version are required"
            },
        )

    try:
        rejection = service.reject_case(
            case_id=case_id,
            proposal_id=str(proposal_id),
            proposal_hash=str(proposal_hash),
            user=resolved_user,
            reason=str(reason),
            expected_case_version=int(case_version),
        )
        return _json_response(200, {"status": "REJECTED", "rejection": rejection.model_dump()})

    except UnauthorizedApproverError as exc:
        return _json_response(403, {"error": "Unauthorized", "details": str(exc)})
    except OrganizationAccessDeniedError as exc:
        return _json_response(403, {"error": "Access Denied", "details": str(exc)})
    except NotFoundError as exc:
        return _json_response(404, {"error": "Not Found", "details": str(exc)})
    except (
        StateVersionMismatchError,
        ProposalHashMismatchError,
        TerminalStateError,
        InvalidStateTransitionError,
        ConflictError,
    ) as exc:
        return _json_response(409, {"error": "Conflict", "details": str(exc)})
    except Exception:
        logger.exception("Unexpected error in handle_reject_case for case %s", case_id)
        return _json_response(500, {"error": "Internal server error"})


def handle_execute_case(
    event: dict[str, Any],
    context: Any = None,
    executor: ActionExecutor | None = None,
    user: User | None = None,
) -> dict[str, Any]:
    """HTTP handler for POST /api/cases/{id}/execute."""
    if executor is None:
        return _json_response(500, {"error": "ActionExecutor not configured"})

    try:
        resolved_user, case_id, body = _extract_user_and_case(event, user=user)
    except ValueError as exc:
        return _json_response(400, {"error": str(exc)})

    approval_id = body.get("approval_id")
    case_version = body.get("case_version")
    idempotency_key = body.get("idempotency_key")

    if not approval_id or case_version is None:
        return _json_response(
            400,
            {"error": "Missing required fields: approval_id and case_version are required"},
        )

    try:
        result = executor.execute_action(
            case_id=case_id,
            approval_id=str(approval_id),
            user=resolved_user,
            expected_case_version=int(case_version),
            idempotency_key=str(idempotency_key) if idempotency_key else None,
        )
        return _json_response(
            200,
            {
                "status": "EXECUTED",
                "action": result.action.model_dump(),
                "case_status": result.case.status.value,
                "was_idempotent": result.was_idempotent,
                "receipt": result.execution_receipt,
            },
        )

    except UnauthorizedApproverError as exc:
        return _json_response(403, {"error": "Unauthorized", "details": str(exc)})
    except OrganizationAccessDeniedError as exc:
        return _json_response(403, {"error": "Access Denied", "details": str(exc)})
    except NotFoundError as exc:
        return _json_response(404, {"error": "Not Found", "details": str(exc)})
    except (
        AlreadyExecutingError,
        AlreadyCompletedError,
        StateVersionMismatchError,
        ProposalHashMismatchError,
        ApprovalExpiredError,
        DirectExecutionWithoutApprovalError,
        TerminalStateError,
        InvalidStateTransitionError,
        StateMachineError,
        ConflictError,
    ) as exc:
        return _json_response(409, {"error": "Conflict", "details": str(exc)})
    except Exception:
        logger.exception("Unexpected error in handle_execute_case for case %s", case_id)
        return _json_response(500, {"error": "Internal server error"})
