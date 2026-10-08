"""API Gateway router and Lambda proxy adapter for Aro core operations.

Routes:
- GET  /health
- GET  /api/cases
- GET  /api/cases/{id}
- POST /api/cases/{id}/brief
- POST /api/cases/{id}/approve
- POST /api/cases/{id}/reject
- POST /api/cases/{id}/execute
- GET  /api/cases/{id}/timeline
- GET  /api/cases/{id}/evidence
- POST /api/cases/{id}/close

Security & Trust Boundary:
- Authenticates actor context from Cognito authorizer claims or headers (demo mode).
- Derives user_id, organization_id, and role from trusted auth context.
- Enforces RBAC: VIEWER cannot approve, reject, execute, or close cases (HTTP 403).
- Strictly sanitizes errors: never exposes stack traces or secrets to clients.
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from packages.contracts.enums import CaseStatus, Role
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
    PersistenceError,
)
from ..repositories.in_memory import (
    InMemoryActionRepository,
    InMemoryApprovalRepository,
    InMemoryAuditRepository,
    InMemoryCaseRepository,
    InMemoryEventRepository,
    InMemoryIdempotencyRepository,
    InMemoryProposalRepository,
)
from ..services.action_executor import ActionExecutor
from ..services.approval_service import ApprovalService
from ..services.evidence_service import EvidenceService
from .case_actions import handle_approve_case, handle_execute_case, handle_reject_case

logger = logging.getLogger("aro.api_gateway_adapter")


def _cors_headers() -> dict[str, str]:
    cors_origins = os.environ.get("ARO_CORS_ORIGINS", "*")
    # If comma-separated, take first or reflect
    origin = cors_origins.split(",")[0].strip() if cors_origins else "*"
    return {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-User-Id,X-Organization-Id,X-User-Role",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "X-Content-Type-Options": "nosniff",
    }


def _response(status_code: int, body_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": _cors_headers(),
        "body": json.dumps(body_dict),
    }


def _extract_authenticated_user(event: dict[str, Any]) -> User:
    """Extract authenticated actor identity with strict production / local isolation.

    PRODUCTION PATH:
      Requires verified Cognito Authorizer claims in requestContext.authorizer.claims.
      Cognito claims are authoritative for user_id, organization_id, and role.
      Client headers (x-actor-role, x-actor-id, x-user-role, x-user-id, x-tenant-id,
      x-organization-id) are NEVER trusted or consulted in production.

    LOCAL/DEMO PATH:
      Permitted ONLY when ARO_ENV is in {"demo", "local", "test"}.
      If Cognito claims are absent, simulated headers are used for offline test/demo execution.
      If Cognito claims ARE present in demo mode, they remain strictly authoritative.
    """
    req_context = event.get("requestContext") or {}
    auth_ctx = req_context.get("authorizer") or {}
    claims = auth_ctx.get("claims") or {}

    is_demo_mode = os.environ.get("ARO_ENV", "demo").strip().lower() in {"demo", "local", "test"}

    # 1. Authoritative Cognito Authorizer Claims
    if claims and (claims.get("sub") or claims.get("cognito:username")):
        user_id = str(claims.get("sub") or claims.get("cognito:username"))
        org_id = claims.get("custom:tenant_id") or claims.get("custom:organization_id")
        if not org_id:
            raise ValueError("Cognito authorizer claims missing tenant identity (custom:tenant_id)")

        email = str(claims.get("email", f"{user_id}@aro.internal"))

        # Role derivation strictly from Cognito claims (never headers)
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

        return User(
            user_id=user_id,
            organization_id=str(org_id),
            email=email,
            name="Aro Authenticated User",
            role=role,
        )

    # 2. Production Rejection: Production requests MUST have valid Cognito claims
    if not is_demo_mode:
        raise ValueError(
            "Production authentication required: Request lacks valid Cognito authorizer claims."
        )

    # 3. Local/Demo Simulated Adapter Path (Isolated to local/demo/test environment)
    raw_headers = event.get("headers") or {}
    headers = {k.lower(): str(v) for k, v in raw_headers.items()}

    user_id = headers.get("x-user-id") or headers.get("x-actor-id") or "usr_demo_operator"
    org_id = headers.get("x-tenant-id") or headers.get("x-organization-id") or "org_demo"
    role_header = (
        headers.get("x-user-role") or headers.get("x-actor-role") or Role.OPERATOR.value
    ).upper()
    try:
        role = Role(role_header)
    except ValueError:
        role = Role.OPERATOR

    email = f"{user_id}@aro.internal"

    return User(
        user_id=user_id,
        organization_id=org_id,
        email=email,
        name="Aro Demo Operator",
        role=role,
    )


class ApiServiceContainer:
    """Lazy container for API dependencies with DynamoDB or in-memory fallback."""

    case_repo: Any
    approval_repo: Any
    action_repo: Any
    audit_repo: Any
    event_repo: Any
    idempotency_repo: Any
    proposal_repo: Any

    def __init__(self) -> None:
        table_name = os.environ.get("ARO_TABLE_NAME")
        if table_name and "demo" not in os.environ.get("ARO_ENV", "demo").lower():
            try:
                import boto3

                from ..repositories.dynamodb import (
                    DynamoDBActionRepository,
                    DynamoDBApprovalRepository,
                    DynamoDBAuditRepository,
                    DynamoDBCaseRepository,
                    DynamoDBEventRepository,
                    DynamoDBIdempotencyRepository,
                    DynamoDBProposalRepository,
                )

                table = boto3.resource("dynamodb").Table(table_name)
                self.case_repo = DynamoDBCaseRepository(table)
                self.approval_repo = DynamoDBApprovalRepository(table)
                self.action_repo = DynamoDBActionRepository(table)
                self.audit_repo = DynamoDBAuditRepository(table)
                self.event_repo = DynamoDBEventRepository(table)
                self.idempotency_repo = DynamoDBIdempotencyRepository(table)
                self.proposal_repo = DynamoDBProposalRepository(table)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not initialize DynamoDB tables, falling back to in-memory: %s", exc
                )
                self._init_in_memory()
        else:
            self._init_in_memory()

        self.approval_service = ApprovalService(
            case_repo=self.case_repo,
            approval_repo=self.approval_repo,
            audit_repo=self.audit_repo,
            proposal_repo=self.proposal_repo,
        )

        self.action_executor = ActionExecutor(
            case_repo=self.case_repo,
            approval_repo=self.approval_repo,
            action_repo=self.action_repo,
            audit_repo=self.audit_repo,
            proposal_repo=self.proposal_repo,
            idempotency_repo=self.idempotency_repo,
        )

        self.evidence_service = EvidenceService(
            case_repo=self.case_repo,
            audit_repo=self.audit_repo,
            event_repo=self.event_repo,
            approval_repo=self.approval_repo,
            action_repo=self.action_repo,
            proposal_repo=self.proposal_repo,
        )

    def _init_in_memory(self) -> None:
        self.case_repo = InMemoryCaseRepository()
        self.approval_repo = InMemoryApprovalRepository()
        self.action_repo = InMemoryActionRepository(case_repo=self.case_repo)
        self.audit_repo = InMemoryAuditRepository()
        self.event_repo = InMemoryEventRepository()
        self.idempotency_repo = InMemoryIdempotencyRepository()
        self.proposal_repo = InMemoryProposalRepository()


_container: ApiServiceContainer | None = None


def get_container() -> ApiServiceContainer:
    global _container
    if _container is None:
        _container = ApiServiceContainer()
    return _container


def handle_api_request(
    event: dict[str, Any],
    context: Any = None,
    container: ApiServiceContainer | None = None,
) -> dict[str, Any]:
    """Main API Gateway Lambda router."""
    http_method = event.get("httpMethod", "GET").upper()
    path = event.get("path", "/")

    # Preflight CORS support
    if http_method == "OPTIONS":
        return _response(200, {"message": "OK"})

    # Health check endpoint (Public)
    if path == "/health" and http_method == "GET":
        return _response(
            200,
            {
                "status": "HEALTHY",
                "service": "aro-api",
                "environment": os.environ.get("ARO_ENV", "demo"),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    services = container or get_container()

    try:
        user = _extract_authenticated_user(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Authentication failed: %s", exc)
        return _response(401, {"error": "Unauthenticated", "message": "Valid identity required"})

    path_params = event.get("pathParameters") or {}
    case_id = path_params.get("id") or path_params.get("case_id")

    try:
        # 1. GET /api/cases
        if path == "/api/cases" and http_method == "GET":
            q_params = event.get("queryStringParameters") or {}
            status_param = q_params.get("status")
            status = CaseStatus(status_param) if status_param else None
            loc_param = q_params.get("location_id")
            cases = services.case_repo.list_cases(
                organization_id=user.organization_id,
                status=status,
                location_id=loc_param,
            )
            return _response(200, {"cases": [c.model_dump() for c in cases], "count": len(cases)})

        # 2. GET /api/cases/{id}
        if case_id and path == f"/api/cases/{case_id}" and http_method == "GET":
            case = services.case_repo.get_case(case_id, user.organization_id)
            return _response(200, {"case": case.model_dump()})

        # 3. POST /api/cases/{id}/approve
        if case_id and path.endswith("/approve") and http_method == "POST":
            _check_operator_or_admin(user)
            return handle_approve_case(event, context, service=services.approval_service, user=user)

        # 4. POST /api/cases/{id}/reject
        if case_id and path.endswith("/reject") and http_method == "POST":
            _check_operator_or_admin(user)
            return handle_reject_case(event, context, service=services.approval_service, user=user)

        # 5. POST /api/cases/{id}/execute
        if case_id and path.endswith("/execute") and http_method == "POST":
            _check_operator_or_admin(user)
            return handle_execute_case(event, context, executor=services.action_executor, user=user)

        # 6. GET /api/cases/{id}/timeline
        if case_id and path.endswith("/timeline") and http_method == "GET":
            timeline = services.audit_repo.get_case_timeline(case_id, user.organization_id)
            return _response(
                200, {"case_id": case_id, "timeline": [e.model_dump() for e in timeline]}
            )

        # 7. GET /api/cases/{id}/evidence
        if case_id and path.endswith("/evidence") and http_method == "GET":
            bundle = services.evidence_service.build_evidence_bundle(case_id, user.organization_id)
            return _response(200, {"evidence": bundle.model_dump()})

        # 8. POST /api/cases/{id}/close
        if case_id and path.endswith("/close") and http_method == "POST":
            _check_operator_or_admin(user)
            raw_body = event.get("body") or "{}"
            body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
            reason = body.get("reason", "Operator closed case manually")
            case = services.case_repo.get_case(case_id, user.organization_id)
            updated = case.model_copy(
                update={
                    "status": CaseStatus.CLOSED,
                    "closed_at": datetime.now(UTC).isoformat(),
                    "closure_reason": reason,
                }
            )
            saved = services.case_repo.update_case(
                updated, organization_id=user.organization_id, expected_version=case.version
            )
            return _response(200, {"status": "CLOSED", "case": saved.model_dump()})

        return _response(
            404, {"error": "NotFound", "message": f"Route not found: {http_method} {path}"}
        )

    except UnauthorizedApproverError as exc:
        return _response(403, {"error": "Unauthorized", "details": str(exc)})
    except OrganizationAccessDeniedError as exc:
        return _response(403, {"error": "AccessDenied", "details": str(exc)})
    except NotFoundError as exc:
        return _response(404, {"error": "NotFound", "details": str(exc)})
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
        return _response(409, {"error": "Conflict", "details": str(exc)})
    except PersistenceError:
        logger.exception("Persistence error occurred")
        return _response(500, {"error": "DatabaseError", "message": "Storage operation failed"})
    except Exception as exc:
        logger.exception(
            "Unhandled error processing %s %s: %s", http_method, path, type(exc).__name__
        )
        return _response(
            500, {"error": "InternalServerError", "message": "An unexpected error occurred"}
        )


def _check_operator_or_admin(user: User) -> None:
    if user.role not in {Role.OPERATOR, Role.ADMIN}:
        raise UnauthorizedApproverError(user_id=user.user_id, role=user.role.value)
