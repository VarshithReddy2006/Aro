"""Human approval orchestration service.

Enforces server-side security invariants:
- NO consequential action may execute unless a human explicitly approves the exact
  proposal hash associated with the current case version.
- Strict RBAC authorization: Only ADMIN and OPERATOR roles may approve/reject. VIEWER cannot.
- Tenant isolation: Multi-tenant organization boundaries enforced.
- Optimistic concurrency: Stale case version requests are rejected.
- Cryptographic proposal hash binding and validation.
- Expiry window validation.
- State-machine compliance: APPROVAL_PENDING -> APPROVED or UNRESOLVED.
- Tamper-evident hash-chained audit logging for every decision.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from packages.contracts.enums import (
    ApprovalDecision,
    AuditEventType,
    CaseStatus,
    Role,
)
from packages.contracts.models import (
    Approval,
    Case,
    User,
)
from packages.contracts.state_machine import (
    ApprovalExpiredError,
    InvalidStateTransitionError,
    ProposalHashMismatchError,
    StateVersionMismatchError,
    TerminalStateError,
    UnauthorizedApproverError,
    transition_case,
)

from ..repositories.errors import (
    OrganizationAccessDeniedError,
)
from ..repositories.interfaces import (
    ApprovalRepository,
    AuditRepository,
    CaseRepository,
    PolicyRepository,
    ProposalRepository,
)
from ..utils.audit_hasher import create_audit_event
from ..utils.proposal_hash import calculate_proposal_hash

DEFAULT_APPROVAL_TIMEOUT_SECONDS = 1800  # 30 minutes


class ApprovalService:
    """Service governing human approval workflows for operational cases."""

    def __init__(
        self,
        case_repo: CaseRepository,
        approval_repo: ApprovalRepository,
        audit_repo: AuditRepository,
        proposal_repo: ProposalRepository | None = None,
        policy_repo: PolicyRepository | None = None,
    ) -> None:
        self.case_repo = case_repo
        self.approval_repo = approval_repo
        self.audit_repo = audit_repo
        self.proposal_repo = proposal_repo
        self.policy_repo = policy_repo

    def _get_timeout_seconds(self, organization_id: str) -> int:
        if self.policy_repo:
            policy = self.policy_repo.get_policy(organization_id)
            if policy:
                return policy.approval_timeout_seconds
        return DEFAULT_APPROVAL_TIMEOUT_SECONDS

    def approve_case(
        self,
        case_id: str,
        proposal_id: str,
        proposal_hash: str,
        user: User,
        expected_case_version: int,
        organization_id: str | None = None,
        expires_at: str | None = None,
    ) -> Approval:
        """Approve an operational proposal for a case.

        Security Invariants Enforced:
        1. Tenant isolation: user's org must match case's org.
        2. Role-based access control: user must have ADMIN or OPERATOR role.
        3. Optimistic concurrency: case.version must exactly match expected_case_version.
        4. State machine: case must be in APPROVAL_PENDING state.
        5. Proposal binding: case.active_proposal_id must match proposal_id.
        6. Cryptographic proposal hash binding: proposal_hash must match stored proposal hash.
        7. Non-expiry: approval must not be expired.

        Args:
            case_id: Target case identifier.
            proposal_id: Active proposal identifier.
            proposal_hash: Canonical SHA-256 hash of the proposal.
            user: Authenticated human user attempting approval.
            expected_case_version: Optimistic locking version guard.
            organization_id: Optional organization override (must match user org).
            expires_at: Optional custom expiration timestamp.

        Returns:
            Sealed Approval model.
        """
        target_org = organization_id or user.organization_id

        # 1. Tenant boundary enforcement
        if user.organization_id != target_org:
            raise OrganizationAccessDeniedError(
                target_resource=f"Case/{case_id}",
                expected_org_id=user.organization_id,
                actual_org_id=target_org,
            )

        # 2. RBAC check: Only ADMIN and OPERATOR may approve
        if user.role not in (Role.ADMIN, Role.OPERATOR):
            raise UnauthorizedApproverError(user_id=user.user_id, role=user.role.value)

        # 3. Fetch Case
        case = self.case_repo.get_case(case_id, organization_id=target_org)

        # 4. Optimistic concurrency check
        if case.version != expected_case_version:
            raise StateVersionMismatchError(expected=expected_case_version, actual=case.version)

        # 5. State machine validation
        if case.status == CaseStatus.CLOSED:
            raise TerminalStateError(case.status, CaseStatus.APPROVED)
        if case.status != CaseStatus.APPROVAL_PENDING:
            raise InvalidStateTransitionError(
                case.status,
                CaseStatus.APPROVED,
                f"Cannot approve case in '{case.status}' state. Case must be APPROVAL_PENDING.",
            )

        # 6. Active proposal binding verification
        if not case.active_proposal_id or case.active_proposal_id != proposal_id:
            raise ProposalHashMismatchError(
                expected_hash=case.active_proposal_id or "NO_ACTIVE_PROPOSAL",
                provided_hash=proposal_id,
            )

        # 7. Cryptographic proposal hash verification
        if self.proposal_repo:
            stored_prop = self.proposal_repo.get_proposal(
                case_id=case_id, proposal_id=proposal_id, organization_id=target_org
            )
            if stored_prop:
                if stored_prop.proposal_hash != proposal_hash:
                    raise ProposalHashMismatchError(
                        expected_hash=stored_prop.proposal_hash,
                        provided_hash=proposal_hash,
                    )
                # Recompute hash to ensure no in-memory mutation
                recomputed = calculate_proposal_hash(
                    case_id=stored_prop.case_id,
                    action_type=stored_prop.action_type,
                    reason=stored_prop.reason,
                    parameters=stored_prop.parameters,
                )
                if recomputed != proposal_hash:
                    raise ProposalHashMismatchError(
                        expected_hash=recomputed,
                        provided_hash=proposal_hash,
                    )

        # 8. Expiry calculation & check
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        if expires_at is None:
            timeout_sec = self._get_timeout_seconds(target_org)
            exp_dt = now + timedelta(seconds=timeout_sec)
            actual_expires_at = exp_dt.isoformat()
        else:
            actual_expires_at = expires_at

        if now_iso > actual_expires_at:
            raise ApprovalExpiredError(expires_at=actual_expires_at, current_time=now_iso)

        # 9. Create sealed Approval model
        approval_id = f"appr_{uuid4().hex[:12]}"
        approval = Approval(
            approval_id=approval_id,
            organization_id=target_org,
            case_id=case_id,
            proposal_id=proposal_id,
            proposal_hash=proposal_hash,
            approved_by=user.user_id,
            approved_at=now_iso,
            expires_at=actual_expires_at,
            decision=ApprovalDecision.APPROVED,
            case_version=expected_case_version,
            created_at=now_iso,
            updated_at=now_iso,
            approver_role=user.role,
        )

        # 10. Persist Approval
        self.approval_repo.save_approval(approval, organization_id=target_org)

        # 11. State transition: APPROVAL_PENDING -> APPROVED
        transitioned = transition_case(
            case, CaseStatus.APPROVED, expected_version=expected_case_version
        )
        updated_case = transitioned.model_copy(update={"active_approval_id": approval_id})
        self.case_repo.update_case(
            updated_case, organization_id=target_org, expected_version=case.version
        )

        # 12. Hash-chained audit logging
        latest_audit = self.audit_repo.get_latest_audit_event(case_id, organization_id=target_org)
        audit_event = create_audit_event(
            case_id=case_id,
            actor_id=user.user_id,
            actor_type="HUMAN",
            action=AuditEventType.APPROVAL_RECORDED,
            previous_hash=latest_audit.current_hash if latest_audit else None,
            metadata={
                "approval_id": approval_id,
                "proposal_id": proposal_id,
                "proposal_hash": proposal_hash,
                "case_version": expected_case_version,
                "decision": ApprovalDecision.APPROVED.value,
                "approver_role": user.role.value,
            },
        )
        self.audit_repo.append_audit_event(audit_event, organization_id=target_org)

        return approval

    def reject_case(
        self,
        case_id: str,
        proposal_id: str,
        proposal_hash: str,
        user: User,
        reason: str,
        expected_case_version: int,
        organization_id: str | None = None,
    ) -> Approval:
        """Reject an operational proposal, moving case to UNRESOLVED.

        Args:
            case_id: Target case identifier.
            proposal_id: Active proposal identifier.
            proposal_hash: Proposal hash being rejected.
            user: Authenticated human user rejecting the proposal.
            reason: Explicit human rationale for rejection.
            expected_case_version: Optimistic locking version guard.
            organization_id: Optional organization override.

        Returns:
            Sealed Approval model reflecting REJECTED decision.
        """
        target_org = organization_id or user.organization_id

        # 1. Tenant boundary
        if user.organization_id != target_org:
            raise OrganizationAccessDeniedError(
                target_resource=f"Case/{case_id}",
                expected_org_id=user.organization_id,
                actual_org_id=target_org,
            )

        # 2. RBAC: Only ADMIN and OPERATOR may reject
        if user.role not in (Role.ADMIN, Role.OPERATOR):
            raise UnauthorizedApproverError(user_id=user.user_id, role=user.role.value)

        # 3. Fetch Case
        case = self.case_repo.get_case(case_id, organization_id=target_org)

        # 4. Version check
        if case.version != expected_case_version:
            raise StateVersionMismatchError(expected=expected_case_version, actual=case.version)

        # 5. State machine check
        if case.status == CaseStatus.CLOSED:
            raise TerminalStateError(case.status, CaseStatus.UNRESOLVED)
        if case.status != CaseStatus.APPROVAL_PENDING:
            raise InvalidStateTransitionError(
                case.status,
                CaseStatus.UNRESOLVED,
                f"Cannot reject case in '{case.status}' state. Case must be APPROVAL_PENDING.",
            )

        # 6. Proposal binding
        if not case.active_proposal_id or case.active_proposal_id != proposal_id:
            raise ProposalHashMismatchError(
                expected_hash=case.active_proposal_id or "NO_ACTIVE_PROPOSAL",
                provided_hash=proposal_id,
            )

        # 7. Proposal hash check if stored
        if self.proposal_repo:
            stored_prop = self.proposal_repo.get_proposal(
                case_id=case_id, proposal_id=proposal_id, organization_id=target_org
            )
            if stored_prop and stored_prop.proposal_hash != proposal_hash:
                raise ProposalHashMismatchError(
                    expected_hash=stored_prop.proposal_hash,
                    provided_hash=proposal_hash,
                )

        now_iso = datetime.now(UTC).isoformat()
        approval_id = f"appr_{uuid4().hex[:12]}"
        approval = Approval(
            approval_id=approval_id,
            organization_id=target_org,
            case_id=case_id,
            proposal_id=proposal_id,
            proposal_hash=proposal_hash,
            approved_by=user.user_id,
            approved_at=now_iso,
            expires_at=now_iso,
            decision=ApprovalDecision.REJECTED,
            case_version=expected_case_version,
            created_at=now_iso,
            updated_at=now_iso,
            approver_role=user.role,
        )

        # Persist Rejection record
        self.approval_repo.save_approval(approval, organization_id=target_org)

        # Transition state: APPROVAL_PENDING -> UNRESOLVED
        updated_case = transition_case(
            case,
            CaseStatus.UNRESOLVED,
            expected_version=expected_case_version,
            closure_reason=f"Operator rejected proposal: {reason.strip()}",
        )
        self.case_repo.update_case(
            updated_case, organization_id=target_org, expected_version=case.version
        )

        # Audit logging
        latest_audit = self.audit_repo.get_latest_audit_event(case_id, organization_id=target_org)
        audit_event = create_audit_event(
            case_id=case_id,
            actor_id=user.user_id,
            actor_type="HUMAN",
            action=AuditEventType.APPROVAL_REJECTED,
            previous_hash=latest_audit.current_hash if latest_audit else None,
            metadata={
                "approval_id": approval_id,
                "proposal_id": proposal_id,
                "proposal_hash": proposal_hash,
                "reason": reason.strip(),
                "case_version": expected_case_version,
                "decision": ApprovalDecision.REJECTED.value,
                "approver_role": user.role.value,
            },
        )
        self.audit_repo.append_audit_event(audit_event, organization_id=target_org)

        return approval

    def expire_case_approval(
        self,
        case_id: str,
        expected_case_version: int,
        organization_id: str,
    ) -> Case:
        """Process an expired approval window, transitioning case to UNRESOLVED.

        Args:
            case_id: Target case identifier.
            expected_case_version: Optimistic locking version guard.
            organization_id: Tenant organization identifier.

        Returns:
            Updated Case model in UNRESOLVED state.
        """
        case = self.case_repo.get_case(case_id, organization_id=organization_id)

        if case.version != expected_case_version:
            raise StateVersionMismatchError(expected=expected_case_version, actual=case.version)

        if case.status != CaseStatus.APPROVAL_PENDING:
            raise InvalidStateTransitionError(
                case.status,
                CaseStatus.UNRESOLVED,
                f"Cannot expire approval for case in '{case.status}' state.",
            )

        updated_case = transition_case(
            case,
            CaseStatus.UNRESOLVED,
            expected_version=expected_case_version,
            closure_reason="Human approval window expired without action",
        )
        self.case_repo.update_case(
            updated_case, organization_id=organization_id, expected_version=case.version
        )

        latest_audit = self.audit_repo.get_latest_audit_event(
            case_id, organization_id=organization_id
        )
        audit_event = create_audit_event(
            case_id=case_id,
            actor_id="system",
            actor_type="SYSTEM",
            action=AuditEventType.APPROVAL_EXPIRED,
            previous_hash=latest_audit.current_hash if latest_audit else None,
            metadata={
                "case_id": case_id,
                "case_version": expected_case_version,
            },
        )
        self.audit_repo.append_audit_event(audit_event, organization_id=organization_id)

        return updated_case
