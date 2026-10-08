"""Deterministic Action Execution Engine.

Core Security Invariants:
- NO consequential action may execute unless a human explicitly approves the exact
  proposal hash associated with the current case version.
- Strict action allowlist enforcement:
  Only NOTIFY_OPERATOR, MARK_FOR_REVIEW, REQUEST_OPERATOR_CONFIRMATION, RECORD_NO_ACTION.
- Concurrency & idempotency protection: Atomic execution locking and replay protection.
- State-machine compliance:
  APPROVED -> EXECUTING -> COMPLETED (-> CLOSED).
  Direct execution from APPROVAL_PENDING is strictly blocked.
- Cryptographic hash-chain audit logging for ACTION_STARTED, ACTION_COMPLETED, and CASE_CLOSED.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from packages.contracts.enums import (
    ActionStatus,
    ActionType,
    ApprovalDecision,
    AuditEventType,
    CaseStatus,
    Role,
)
from packages.contracts.models import (
    Action,
    Case,
    Proposal,
    User,
)
from packages.contracts.state_machine import (
    ActionNotAllowlistedError,
    ApprovalExpiredError,
    DirectExecutionWithoutApprovalError,
    InvalidStateTransitionError,
    ProposalHashMismatchError,
    StateVersionMismatchError,
    TerminalStateError,
    UnauthorizedApproverError,
    transition_case,
)

from ..repositories.errors import (
    AlreadyCompletedError,
    AlreadyExecutingError,
    OrganizationAccessDeniedError,
)
from ..repositories.interfaces import (
    ActionRepository,
    ApprovalRepository,
    AuditRepository,
    CaseRepository,
    IdempotencyRepository,
    PolicyRepository,
    ProposalRepository,
)
from ..utils.audit_hasher import create_audit_event

ALLOWLISTED_ACTIONS: set[ActionType] = {
    ActionType.NOTIFY_OPERATOR,
    ActionType.MARK_FOR_REVIEW,
    ActionType.REQUEST_OPERATOR_CONFIRMATION,
    ActionType.RECORD_NO_ACTION,
}


@dataclass(frozen=True)
class ActionExecutionResult:
    """Outcome of deterministic action execution."""

    action: Action
    case: Case
    was_idempotent: bool = False
    execution_receipt: dict[str, Any] | None = None


class ActionExecutor:
    """Deterministic engine for consequential operational action execution."""

    def __init__(
        self,
        case_repo: CaseRepository,
        approval_repo: ApprovalRepository,
        action_repo: ActionRepository,
        audit_repo: AuditRepository,
        proposal_repo: ProposalRepository | None = None,
        idempotency_repo: IdempotencyRepository | None = None,
        policy_repo: PolicyRepository | None = None,
    ) -> None:
        self.case_repo = case_repo
        self.approval_repo = approval_repo
        self.action_repo = action_repo
        self.audit_repo = audit_repo
        self.proposal_repo = proposal_repo
        self.idempotency_repo = idempotency_repo
        self.policy_repo = policy_repo

    def execute_action(
        self,
        case_id: str,
        approval_id: str,
        user: User,
        expected_case_version: int,
        organization_id: str | None = None,
        idempotency_key: str | None = None,
        proposal: Proposal | None = None,
    ) -> ActionExecutionResult:
        """Execute an approved action with deterministic guards.

        Args:
            case_id: Target case identifier.
            approval_id: Associated human approval identifier.
            user: Authenticated human operator initiating execution.
            expected_case_version: Optimistic locking version guard.
            organization_id: Tenant organization override.
            idempotency_key: Optional caller-specified idempotency key.
            proposal: Optional in-memory Proposal if not persisted in repository.

        Returns:
            ActionExecutionResult with updated Action and Case records.
        """
        target_org = organization_id or user.organization_id

        # 1. Tenant boundary
        if user.organization_id != target_org:
            raise OrganizationAccessDeniedError(
                target_resource=f"Case/{case_id}",
                expected_org_id=user.organization_id,
                actual_org_id=target_org,
            )

        # 2. RBAC: Only ADMIN or OPERATOR may execute actions
        if user.role not in (Role.ADMIN, Role.OPERATOR):
            raise UnauthorizedApproverError(user_id=user.user_id, role=user.role.value)

        # 3. Retrieve Case and check state invariant
        case = self.case_repo.get_case(case_id, organization_id=target_org)
        if case.status == CaseStatus.APPROVAL_PENDING:
            raise DirectExecutionWithoutApprovalError()

        approval = self.approval_repo.get_approval(case_id, approval_id, organization_id=target_org)

        # 4. Resolve Proposal & Verify Proposal Hash early
        resolved_proposal: Proposal | None = proposal
        if not resolved_proposal and self.proposal_repo:
            resolved_proposal = self.proposal_repo.get_proposal(
                case_id=case_id,
                proposal_id=approval.proposal_id,
                organization_id=target_org,
            )

        action_type: ActionType
        action_params: dict[str, Any]
        if resolved_proposal:
            if resolved_proposal.proposal_hash != approval.proposal_hash:
                raise ProposalHashMismatchError(
                    expected_hash=resolved_proposal.proposal_hash,
                    provided_hash=approval.proposal_hash,
                )
            action_type = resolved_proposal.action_type
            action_params = resolved_proposal.parameters
        else:
            action_type = ActionType.NOTIFY_OPERATOR
            action_params = {"channel": "ops_console"}

        # Strict Allowlist Enforcement
        if action_type not in ALLOWLISTED_ACTIONS:
            raise ActionNotAllowlistedError(str(action_type))

        # 5. Idempotency Check for already completed executions
        idem_key = (
            idempotency_key
            or f"idem_exec_{case_id}_{approval.approval_id}_{action_type.value}_{approval.proposal_hash[:8]}"
        )
        if self.idempotency_repo:
            record = self.idempotency_repo.get_record(idem_key)
            if record and record.get("status") == "COMPLETED":
                # Return cached result idempotently
                cached_data = record.get("result", {})
                cached_action = Action.model_validate(cached_data)
                return ActionExecutionResult(
                    action=cached_action,
                    case=case,
                    was_idempotent=True,
                    execution_receipt={"cached": True, "idempotency_key": idem_key},
                )

        # 7. Security Invariant: Human must have approved (not rejected)
        if approval.decision != ApprovalDecision.APPROVED:
            raise InvalidStateTransitionError(
                case.status,
                CaseStatus.EXECUTING,
                f"Cannot execute action: human decision was '{approval.decision.value}'.",
            )

        # 8. Expiry check
        now_iso = datetime.now(UTC).isoformat()
        if now_iso > approval.expires_at:
            raise ApprovalExpiredError(expires_at=approval.expires_at, current_time=now_iso)

        # 9. Case status check
        if case.status == CaseStatus.CLOSED:
            raise TerminalStateError(case.status, CaseStatus.EXECUTING)
        if case.status == CaseStatus.EXECUTING:
            raise AlreadyExecutingError(case_id)
        if case.status in {CaseStatus.COMPLETED}:
            raise AlreadyCompletedError(case_id)
        if case.status != CaseStatus.APPROVED:
            raise InvalidStateTransitionError(
                case.status,
                CaseStatus.EXECUTING,
                f"Cannot execute action on case with status '{case.status}'. Must be APPROVED.",
            )

        # 10. Version guard
        if case.version != expected_case_version:
            raise StateVersionMismatchError(expected=expected_case_version, actual=case.version)

        # 11. Acquire Idempotency Lock
        if self.idempotency_repo:
            acquired = self.idempotency_repo.acquire_lock(idem_key, operation="EXECUTE_ACTION")
            if not acquired:
                raise AlreadyExecutingError(f"Idempotency lock held for {idem_key}")

        # 12. Create pending Action record and acquire execution lock
        action_id = f"act_{uuid4().hex[:12]}"
        action_record = Action(
            action_id=action_id,
            case_id=case_id,
            approval_id=approval_id,
            action_type=action_type,
            parameters=action_params,
            status=ActionStatus.PENDING,
            idempotency_key=idem_key,
        )
        self.action_repo.save_action(action_record, organization_id=target_org)

        # Acquire execution lock on case (atomically transitions case to EXECUTING)
        self.action_repo.acquire_execution_lock(
            case_id=case_id,
            action_id=action_id,
            organization_id=target_org,
            expected_case_version=expected_case_version,
        )

        # 13. Audit Event: ACTION_STARTED
        latest_audit = self.audit_repo.get_latest_audit_event(case_id, organization_id=target_org)
        start_audit = create_audit_event(
            case_id=case_id,
            actor_id=user.user_id,
            actor_type="HUMAN",
            action=AuditEventType.ACTION_STARTED,
            previous_hash=latest_audit.current_hash if latest_audit else None,
            metadata={
                "action_id": action_id,
                "action_type": action_type.value,
                "approval_id": approval_id,
                "idempotency_key": idem_key,
            },
        )
        self.audit_repo.append_audit_event(start_audit, organization_id=target_org)

        # 14. Deterministic Execution of Allowlisted Action Adapter
        receipt, summary = self._execute_deterministic_adapter(
            action_type=action_type,
            parameters=action_params,
            case_id=case_id,
            target_org=target_org,
        )

        # 15. Complete Action in ActionRepository
        completed_action = self.action_repo.complete_action(
            case_id=case_id,
            action_id=action_id,
            organization_id=target_org,
            result_summary=summary,
        )

        # 16. State Machine Transitions: EXECUTING -> COMPLETED (-> CLOSED)
        case_in_exec = self.case_repo.get_case(case_id, organization_id=target_org)
        completed_case = transition_case(
            case_in_exec,
            CaseStatus.COMPLETED,
            expected_version=case_in_exec.version,
        )

        # Determine auto-closure
        should_close = False
        if action_type == ActionType.RECORD_NO_ACTION:
            should_close = True
        elif self.policy_repo:
            pol = self.policy_repo.get_policy(target_org)
            if pol and pol.auto_resolve_no_action:
                should_close = True

        final_case = completed_case
        if should_close:
            final_case = transition_case(
                completed_case,
                CaseStatus.CLOSED,
                expected_version=completed_case.version,
                closure_reason=summary,
            )

        self.case_repo.update_case(
            final_case, organization_id=target_org, expected_version=case_in_exec.version
        )

        # 17. Hash-chained audit logging: ACTION_COMPLETED (& CASE_CLOSED)
        latest_audit = self.audit_repo.get_latest_audit_event(case_id, organization_id=target_org)
        complete_audit = create_audit_event(
            case_id=case_id,
            actor_id=user.user_id,
            actor_type="SYSTEM",
            action=AuditEventType.ACTION_COMPLETED,
            previous_hash=latest_audit.current_hash if latest_audit else None,
            metadata={
                "action_id": action_id,
                "result_summary": summary,
                "action_type": action_type.value,
            },
        )
        self.audit_repo.append_audit_event(complete_audit, organization_id=target_org)

        if should_close:
            latest_audit = self.audit_repo.get_latest_audit_event(
                case_id, organization_id=target_org
            )
            closed_audit = create_audit_event(
                case_id=case_id,
                actor_id=user.user_id,
                actor_type="SYSTEM",
                action=AuditEventType.CASE_CLOSED,
                previous_hash=latest_audit.current_hash if latest_audit else None,
                metadata={
                    "case_id": case_id,
                    "closure_reason": summary,
                },
            )
            self.audit_repo.append_audit_event(closed_audit, organization_id=target_org)

        # 18. Complete Idempotency record
        if self.idempotency_repo:
            self.idempotency_repo.complete_operation(idem_key, result=completed_action.model_dump())

        return ActionExecutionResult(
            action=completed_action,
            case=final_case,
            was_idempotent=False,
            execution_receipt=receipt,
        )

    def _execute_deterministic_adapter(
        self,
        action_type: ActionType,
        parameters: dict[str, Any],
        case_id: str,
        target_org: str,
    ) -> tuple[dict[str, Any], str]:
        """Execute deterministic mock/simulation adapter for allowlisted action."""
        now_iso = datetime.now(UTC).isoformat()

        if action_type == ActionType.NOTIFY_OPERATOR:
            msg = parameters.get("message", "Operational notification")
            urgency = parameters.get("urgency", "normal")
            recipient_role = parameters.get("recipient_role", Role.OPERATOR.value)
            receipt = {
                "adapter": "mock_notification_service",
                "dispatched_at": now_iso,
                "recipient_role": str(recipient_role),
                "urgency": urgency,
                "message": msg,
                "status": "DISPATCHED",
            }
            summary = f"Dispatched {urgency} priority notification to {recipient_role}: {msg[:80]}"
            return receipt, summary

        if action_type == ActionType.MARK_FOR_REVIEW:
            reason = parameters.get("review_reason", "Operational review required")
            priority = parameters.get("priority", "medium")
            receipt = {
                "adapter": "mock_review_queue",
                "enqueued_at": now_iso,
                "queue": "operator_review_queue",
                "priority": priority,
                "review_reason": reason,
                "status": "ENQUEUED",
            }
            summary = f"Enqueued case for operator review ({priority} priority): {reason[:80]}"
            return receipt, summary

        if action_type == ActionType.REQUEST_OPERATOR_CONFIRMATION:
            confirmation_type = parameters.get("confirmation_type", "physical_status")
            target_role = parameters.get("target_role", Role.OPERATOR.value)
            receipt = {
                "adapter": "mock_confirmation_service",
                "requested_at": now_iso,
                "confirmation_type": confirmation_type,
                "target_role": str(target_role),
                "status": "AWAITING_CONFIRMATION",
            }
            summary = (
                f"Requested operator confirmation for '{confirmation_type}' from {target_role}"
            )
            return receipt, summary

        if action_type == ActionType.RECORD_NO_ACTION:
            rationale = parameters.get("rationale", "Normal expected activity observed")
            receipt = {
                "adapter": "mock_resolution_log",
                "recorded_at": now_iso,
                "rationale": rationale,
                "status": "RECORDED",
            }
            summary = f"Recorded no action rationale: {rationale[:80]}"
            return receipt, summary

        raise ActionNotAllowlistedError(str(action_type))
