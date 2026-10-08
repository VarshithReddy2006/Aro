"""Deterministic DEMO scenarios for Phase 5: Human Approval + Action Execution Engine.

Demonstrates offline, deterministic resilience across core security scenarios:
1. Valid approval & deterministic execution (NOTIFY_OPERATOR) with verified audit hash chain.
2. Security Invariant: Direct execution without human approval blocked.
3. Security Invariant: Stale/tampered proposal hash blocked.
4. Concurrency Guard: Optimistic case version mismatch blocked.
5. RBAC Guard: Role.VIEWER blocked from approving or executing.
6. Multi-Tenant Guard: Cross-tenant approval blocked.
7. Expiry Guard: Expired approval rejected.
8. Idempotency Guard: Duplicate action execution safely replayed with cached outcome.
9. Tamper-evident Audit Chain: Cryptographic verification and tamper detection.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from packages.contracts.enums import (
    ActionType,
    ApprovalDecision,
    CaseStatus,
    Role,
)
from packages.contracts.models import (
    Case,
    Proposal,
    User,
)
from packages.contracts.state_machine import (
    ApprovalExpiredError,
    DirectExecutionWithoutApprovalError,
    ProposalHashMismatchError,
    StateMachineError,
    StateVersionMismatchError,
    UnauthorizedApproverError,
)

from ..repositories.errors import (
    OrganizationAccessDeniedError,
)
from ..repositories.in_memory import (
    InMemoryActionRepository,
    InMemoryApprovalRepository,
    InMemoryAuditRepository,
    InMemoryCaseRepository,
    InMemoryIdempotencyRepository,
    InMemoryProposalRepository,
)
from ..utils.audit_hasher import verify_audit_chain
from ..utils.proposal_hash import calculate_proposal_hash
from .action_executor import ActionExecutor
from .approval_service import ApprovalService


@dataclass(frozen=True)
class Phase5DemoScenarioResult:
    """Structured report of a Phase 5 demo scenario outcome."""

    scenario_name: str
    description: str
    success: bool
    security_invariant_enforced: str
    details: dict[str, Any]


class Phase5DemoHarness:
    """Offline demo harness for Phase 5 Human Approval & Action Execution."""

    def __init__(self, organization_id: str = "org_demo") -> None:
        self.org_id = organization_id
        self.case_repo = InMemoryCaseRepository()
        self.approval_repo = InMemoryApprovalRepository()
        self.action_repo = InMemoryActionRepository(case_repo=self.case_repo)
        self.audit_repo = InMemoryAuditRepository()
        self.proposal_repo = InMemoryProposalRepository()
        self.idempotency_repo = InMemoryIdempotencyRepository()

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

    def _setup_case_with_proposal(
        self,
        case_id: str = "case_demo_01",
        action_type: ActionType = ActionType.NOTIFY_OPERATOR,
        reason: str = "Motion observed at designated entrance during after-hours window",
        params: dict[str, Any] | None = None,
    ) -> tuple[Case, Proposal]:
        action_params = params or {"message": "Courier activity observed", "urgency": "high"}
        proposal_hash = calculate_proposal_hash(
            case_id=case_id,
            action_type=action_type,
            reason=reason,
            parameters=action_params,
        )

        proposal = Proposal(
            proposal_id=f"prop_{case_id}",
            case_id=case_id,
            action_type=action_type,
            reason=reason,
            parameters=action_params,
            proposal_hash=proposal_hash,
        )
        self.proposal_repo.save_proposal(proposal, organization_id=self.org_id)

        case = Case(
            case_id=case_id,
            organization_id=self.org_id,
            location_id="loc_demo",
            device_id="dev_front_door",
            event_id="evt_demo_ring",
            title="After-Hours Entrance Activity",
            status=CaseStatus.APPROVAL_PENDING,
            version=1,
            active_proposal_id=proposal.proposal_id,
        )
        self.case_repo.create_case(case)
        return case, proposal

    def run_all_scenarios(self) -> list[Phase5DemoScenarioResult]:
        """Execute all 9 offline demo scenarios."""
        return [
            self.scenario_1_happy_path_approval_and_execution(),
            self.scenario_2_direct_execution_blocked(),
            self.scenario_3_tampered_proposal_hash_blocked(),
            self.scenario_4_stale_case_version_blocked(),
            self.scenario_5_rbac_viewer_blocked(),
            self.scenario_6_tenant_isolation_blocked(),
            self.scenario_7_expired_approval_blocked(),
            self.scenario_8_duplicate_execution_idempotency(),
            self.scenario_9_audit_chain_verification(),
        ]

    def scenario_1_happy_path_approval_and_execution(self) -> Phase5DemoScenarioResult:
        """Scenario 1: Happy path human approval followed by deterministic action execution."""
        case_id = "case_scn_1"
        _case, proposal = self._setup_case_with_proposal(case_id=case_id)

        operator = User(
            user_id="usr_ops_alice",
            organization_id=self.org_id,
            email="alice@company.com",
            name="Alice Operator",
            role=Role.OPERATOR,
        )

        # 1. Human Operator explicitly approves the exact proposal hash
        approval = self.approval_service.approve_case(
            case_id=case_id,
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.proposal_hash,
            user=operator,
            expected_case_version=1,
        )

        # 2. Consequential action execution by authorized operator
        exec_result = self.action_executor.execute_action(
            case_id=case_id,
            approval_id=approval.approval_id,
            user=operator,
            expected_case_version=2,
            proposal=proposal,
        )

        # 3. Verify audit timeline
        timeline = self.audit_repo.get_case_timeline(case_id, self.org_id)
        chain_valid = verify_audit_chain(timeline)

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 1: Happy Path Approval & Deterministic Execution",
            description="Human explicitly approves exact proposal hash; action executes deterministically.",
            success=(
                approval.decision == ApprovalDecision.APPROVED
                and exec_result.case.status in (CaseStatus.COMPLETED, CaseStatus.CLOSED)
                and chain_valid
            ),
            security_invariant_enforced="NO consequential action executes without human approval of exact proposal hash.",
            details={
                "case_id": case_id,
                "proposal_hash": proposal.proposal_hash,
                "approval_id": approval.approval_id,
                "action_id": exec_result.action.action_id,
                "final_case_status": exec_result.case.status.value,
                "audit_events_count": len(timeline),
                "audit_chain_valid": chain_valid,
            },
        )

    def scenario_2_direct_execution_blocked(self) -> Phase5DemoScenarioResult:
        """Scenario 2: Direct execution attempted without prior approval is blocked."""
        case_id = "case_scn_2"
        _case, proposal = self._setup_case_with_proposal(case_id=case_id)

        operator = User(
            user_id="usr_ops_bob",
            organization_id=self.org_id,
            email="bob@company.com",
            name="Bob Operator",
            role=Role.OPERATOR,
        )

        blocked = False
        error_name = ""
        try:
            self.action_executor.execute_action(
                case_id=case_id,
                approval_id="appr_non_existent",
                user=operator,
                expected_case_version=1,
                proposal=proposal,
            )
        except (DirectExecutionWithoutApprovalError, StateMachineError) as exc:
            blocked = True
            error_name = exc.__class__.__name__

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 2: Direct Execution Without Approval Blocked",
            description="Attempting to trigger execution directly from APPROVAL_PENDING is rejected server-side.",
            success=blocked,
            security_invariant_enforced="Direct execution without approval is strictly prohibited.",
            details={
                "case_id": case_id,
                "blocked": blocked,
                "error_raised": error_name,
            },
        )

    def scenario_3_tampered_proposal_hash_blocked(self) -> Phase5DemoScenarioResult:
        """Scenario 3: Approval with a tampered proposal hash is rejected."""
        case_id = "case_scn_3"
        _case, proposal = self._setup_case_with_proposal(case_id=case_id)

        operator = User(
            user_id="usr_ops_alice",
            organization_id=self.org_id,
            email="alice@company.com",
            name="Alice Operator",
            role=Role.OPERATOR,
        )

        tampered_hash = "deadbeef" * 8
        blocked = False
        error_name = ""
        try:
            self.approval_service.approve_case(
                case_id=case_id,
                proposal_id=proposal.proposal_id,
                proposal_hash=tampered_hash,
                user=operator,
                expected_case_version=1,
            )
        except ProposalHashMismatchError as exc:
            blocked = True
            error_name = exc.__class__.__name__

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 3: Tampered Proposal Hash Blocked",
            description="Approval request submitting an altered proposal hash is rejected.",
            success=blocked,
            security_invariant_enforced="Cryptographic binding: approved hash must match proposal hash.",
            details={
                "case_id": case_id,
                "expected_hash": proposal.proposal_hash,
                "attempted_hash": tampered_hash,
                "error_raised": error_name,
            },
        )

    def scenario_4_stale_case_version_blocked(self) -> Phase5DemoScenarioResult:
        """Scenario 4: Approval against stale case version fails with optimistic locking guard."""
        case_id = "case_scn_4"
        case, proposal = self._setup_case_with_proposal(case_id=case_id)

        # Simulate concurrent update that incremented version to 2
        updated_case = case.model_copy(update={"version": 2, "summary": "Updated concurrently"})
        self.case_repo.update_case(updated_case, self.org_id, expected_version=1)

        operator = User(
            user_id="usr_ops_alice",
            organization_id=self.org_id,
            email="alice@company.com",
            name="Alice Operator",
            role=Role.OPERATOR,
        )

        blocked = False
        error_name = ""
        try:
            # Client attempts approval specifying stale version 1
            self.approval_service.approve_case(
                case_id=case_id,
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal.proposal_hash,
                user=operator,
                expected_case_version=1,
            )
        except StateVersionMismatchError as exc:
            blocked = True
            error_name = exc.__class__.__name__

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 4: Stale Case Version Blocked (Optimistic Concurrency)",
            description="Client approving an outdated case version is rejected to prevent race conditions.",
            success=blocked,
            security_invariant_enforced="Optimistic concurrency: case.version == expected_case_version.",
            details={
                "case_id": case_id,
                "expected_version": 1,
                "actual_version": 2,
                "error_raised": error_name,
            },
        )

    def scenario_5_rbac_viewer_blocked(self) -> Phase5DemoScenarioResult:
        """Scenario 5: VIEWER role cannot approve or execute actions."""
        case_id = "case_scn_5"
        _case, proposal = self._setup_case_with_proposal(case_id=case_id)

        viewer = User(
            user_id="usr_viewer_dave",
            organization_id=self.org_id,
            email="dave@company.com",
            name="Dave Readonly",
            role=Role.VIEWER,
        )

        blocked = False
        error_name = ""
        try:
            self.approval_service.approve_case(
                case_id=case_id,
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal.proposal_hash,
                user=viewer,
                expected_case_version=1,
            )
        except UnauthorizedApproverError as exc:
            blocked = True
            error_name = exc.__class__.__name__

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 5: RBAC Authorization Guard (VIEWER Blocked)",
            description="Users with VIEWER role cannot grant approvals.",
            success=blocked,
            security_invariant_enforced="RBAC: Only ADMIN and OPERATOR roles may approve operational cases.",
            details={
                "case_id": case_id,
                "user_role": viewer.role.value,
                "error_raised": error_name,
            },
        )

    def scenario_6_tenant_isolation_blocked(self) -> Phase5DemoScenarioResult:
        """Scenario 6: Cross-tenant approval attempt blocked."""
        case_id = "case_scn_6"
        _case, proposal = self._setup_case_with_proposal(case_id=case_id)

        alien_user = User(
            user_id="usr_alien_eve",
            organization_id="org_other_tenant",
            email="eve@competitor.com",
            name="Eve External",
            role=Role.ADMIN,
        )

        blocked = False
        error_name = ""
        try:
            self.approval_service.approve_case(
                case_id=case_id,
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal.proposal_hash,
                user=alien_user,
                expected_case_version=1,
            )
        except OrganizationAccessDeniedError as exc:
            blocked = True
            error_name = exc.__class__.__name__

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 6: Multi-Tenant Boundary Guard",
            description="Users from other tenant organizations cannot access or approve foreign cases.",
            success=blocked,
            security_invariant_enforced="Multi-tenant isolation: target_org == user.organization_id.",
            details={
                "case_id": case_id,
                "case_org": self.org_id,
                "user_org": alien_user.organization_id,
                "error_raised": error_name,
            },
        )

    def scenario_7_expired_approval_blocked(self) -> Phase5DemoScenarioResult:
        """Scenario 7: Approval requested after expiry window is rejected."""
        case_id = "case_scn_7"
        _case, proposal = self._setup_case_with_proposal(case_id=case_id)

        operator = User(
            user_id="usr_ops_alice",
            organization_id=self.org_id,
            email="alice@company.com",
            name="Alice Operator",
            role=Role.OPERATOR,
        )

        # Past expiry timestamp
        past_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        blocked = False
        error_name = ""
        try:
            self.approval_service.approve_case(
                case_id=case_id,
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal.proposal_hash,
                user=operator,
                expected_case_version=1,
                expires_at=past_time,
            )
        except ApprovalExpiredError as exc:
            blocked = True
            error_name = exc.__class__.__name__

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 7: Approval Expiry Window Guard",
            description="Expired approval requests are strictly rejected.",
            success=blocked,
            security_invariant_enforced="Approval expiry: current_time <= expires_at.",
            details={
                "case_id": case_id,
                "expires_at": past_time,
                "error_raised": error_name,
            },
        )

    def scenario_8_duplicate_execution_idempotency(self) -> Phase5DemoScenarioResult:
        """Scenario 8: Duplicate execution request returns cached result idempotently."""
        case_id = "case_scn_8"
        _case, proposal = self._setup_case_with_proposal(case_id=case_id)

        operator = User(
            user_id="usr_ops_alice",
            organization_id=self.org_id,
            email="alice@company.com",
            name="Alice Operator",
            role=Role.OPERATOR,
        )

        # Approve case first
        approval = self.approval_service.approve_case(
            case_id=case_id,
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.proposal_hash,
            user=operator,
            expected_case_version=1,
        )

        idempotency_key = f"idemp_scn_8_{case_id}"

        # First execution: executes action
        first_result = self.action_executor.execute_action(
            case_id=case_id,
            approval_id=approval.approval_id,
            user=operator,
            expected_case_version=2,
            idempotency_key=idempotency_key,
            proposal=proposal,
        )

        # Second execution: replayed with same idempotency key
        second_result = self.action_executor.execute_action(
            case_id=case_id,
            approval_id=approval.approval_id,
            user=operator,
            expected_case_version=2,
            idempotency_key=idempotency_key,
            proposal=proposal,
        )

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 8: Execution Idempotency & Replay Protection",
            description="Submitting identical execution request returns cached outcome without re-executing.",
            success=(
                first_result.was_idempotent is False
                and second_result.was_idempotent is True
                and first_result.action.action_id == second_result.action.action_id
            ),
            security_invariant_enforced="Idempotency: Consequential actions execute exactly once per approval key.",
            details={
                "case_id": case_id,
                "first_was_idempotent": first_result.was_idempotent,
                "second_was_idempotent": second_result.was_idempotent,
                "action_id": first_result.action.action_id,
            },
        )

    def scenario_9_audit_chain_verification(self) -> Phase5DemoScenarioResult:
        """Scenario 9: Tamper-evident audit timeline hash chaining and corruption detection."""
        case_id = "case_scn_9"
        _case, proposal = self._setup_case_with_proposal(case_id=case_id)

        operator = User(
            user_id="usr_ops_alice",
            organization_id=self.org_id,
            email="alice@company.com",
            name="Alice Operator",
            role=Role.OPERATOR,
        )

        approval = self.approval_service.approve_case(
            case_id=case_id,
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.proposal_hash,
            user=operator,
            expected_case_version=1,
        )

        self.action_executor.execute_action(
            case_id=case_id,
            approval_id=approval.approval_id,
            user=operator,
            expected_case_version=2,
            proposal=proposal,
        )

        timeline = self.audit_repo.get_case_timeline(case_id, self.org_id)
        original_valid = verify_audit_chain(timeline)

        # Simulate tampering with one audit event in the middle of chain
        tampered_timeline = list(timeline)
        tampered_event = tampered_timeline[0].model_copy(update={"metadata": {"tampered": True}})
        tampered_timeline[0] = tampered_event
        tamper_detected = not verify_audit_chain(tampered_timeline)

        return Phase5DemoScenarioResult(
            scenario_name="Scenario 9: Tamper-Evident Audit Hash Chain Verification",
            description="Complete audit timeline is cryptographically verified; modification breaks chain.",
            success=original_valid and tamper_detected,
            security_invariant_enforced="Audit integrity: Every operational step is chained via SHA-256 digests.",
            details={
                "case_id": case_id,
                "original_chain_valid": original_valid,
                "tamper_detected": tamper_detected,
                "timeline_events_count": len(timeline),
            },
        )
