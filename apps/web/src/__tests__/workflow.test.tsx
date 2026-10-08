import { describe, it, expect, beforeEach } from "vitest";
import { apiClient } from "../api/client";
import { Role, CaseStatus } from "../types/contracts";

describe("Aro Operator Workflow & Security Invariants", () => {
  beforeEach(() => {
    apiClient.resetDemoData();
    apiClient.setCurrentUserRole(Role.OPERATOR);
  });

  it("completes the Golden Path: Approval Pending -> Approved -> Executed -> Completed with Audit Chaining", async () => {
    // 1. Initial State: Retrieve Golden Path Case
    const initialBundle = await apiClient.getCase("case_golden_01");
    expect(initialBundle.case.status).toBe(CaseStatus.APPROVAL_PENDING);
    expect(initialBundle.case.version).toBe(1);
    expect(initialBundle.proposal).toBeDefined();

    const proposal = initialBundle.proposal!;
    expect(proposal.proposal_hash).toBe(
      "a4c8f58e65e4860b29841804e1bc2a946b2b73315a6767ea321d234dbb9b91f2"
    );

    // 2. Human Approval: Submit exact proposal hash and case version
    const approveResult = await apiClient.approveCase("case_golden_01", {
      proposal_id: proposal.proposal_id,
      proposal_hash: proposal.proposal_hash,
      case_version: initialBundle.case.version,
    });

    expect(approveResult.status).toBe("APPROVED");
    expect(approveResult.approval.decision).toBe("APPROVED");
    expect(approveResult.approval.case_version).toBe(1);

    // 3. Execution: Submit execution for the granted approval
    const execResult = await apiClient.executeCase("case_golden_01", {
      approval_id: approveResult.approval.approval_id,
      action_type: proposal.action_type,
      parameters: proposal.parameters,
    });

    expect(execResult.status).toBe("EXECUTED");
    expect(execResult.case_status).toBe(CaseStatus.COMPLETED);
    expect(execResult.was_idempotent).toBe(false);

    // 4. Verification: State transitioned to COMPLETED and version bumped
    const refreshedBundle = await apiClient.getCase("case_golden_01");
    expect(refreshedBundle.case.status).toBe(CaseStatus.COMPLETED);
    expect(refreshedBundle.case.version).toBeGreaterThan(initialBundle.case.version);

    // 5. Audit Chain: Timeline entries are forward-chained
    const timeline = refreshedBundle.timeline;
    expect(timeline.length).toBeGreaterThanOrEqual(6);

    const lastEvent = timeline[timeline.length - 1];
    expect(lastEvent.action).toBe("ACTION_COMPLETED");
    expect(lastEvent.previous_hash).toBeDefined();
    expect(lastEvent.current_hash).toBeDefined();
  });

  it("enforces Stale Proposal rejection when case version mismatches (409 STATE_VERSION_MISMATCH)", async () => {
    const bundle = await apiClient.getCase("case_golden_01");
    const proposal = bundle.proposal!;

    // Attempt approval with stale case version (e.g. version 99 instead of 1)
    await expect(
      apiClient.approveCase("case_golden_01", {
        proposal_id: proposal.proposal_id,
        proposal_hash: proposal.proposal_hash,
        case_version: 99,
      })
    ).rejects.toMatchObject({
      status: 409,
      code: "STATE_VERSION_MISMATCH",
    });
  });

  it("enforces Proposal Hash integrity check (409 PROPOSAL_HASH_MISMATCH)", async () => {
    const bundle = await apiClient.getCase("case_golden_01");
    const proposal = bundle.proposal!;

    // Attempt approval with altered hash
    await expect(
      apiClient.approveCase("case_golden_01", {
        proposal_id: proposal.proposal_id,
        proposal_hash: "tampered_fake_proposal_hash_0000000000000000000000000000000000",
        case_version: bundle.case.version,
      })
    ).rejects.toMatchObject({
      status: 409,
      code: "PROPOSAL_HASH_MISMATCH",
    });
  });

  it("enforces RBAC boundary: VIEWER role cannot approve or execute actions (403 UNAUTHORIZED_APPROVER)", async () => {
    apiClient.setCurrentUserRole(Role.VIEWER);

    const bundle = await apiClient.getCase("case_golden_01");
    const proposal = bundle.proposal!;

    await expect(
      apiClient.approveCase("case_golden_01", {
        proposal_id: proposal.proposal_id,
        proposal_hash: proposal.proposal_hash,
        case_version: bundle.case.version,
      })
    ).rejects.toMatchObject({
      status: 403,
      code: "UNAUTHORIZED_APPROVER",
    });

    await expect(
      apiClient.executeCase("case_golden_01", {
        approval_id: "appr_test",
        action_type: proposal.action_type,
      })
    ).rejects.toMatchObject({
      status: 403,
      code: "UNAUTHORIZED_APPROVER",
    });
  });

  it("demonstrates Idempotency: duplicate execution returns cached outcome without duplicate action execution", async () => {
    const bundle = await apiClient.getCase("case_golden_01");
    const proposal = bundle.proposal!;

    const approveResult = await apiClient.approveCase("case_golden_01", {
      proposal_id: proposal.proposal_id,
      proposal_hash: proposal.proposal_hash,
      case_version: bundle.case.version,
    });

    const execResult1 = await apiClient.executeCase("case_golden_01", {
      approval_id: approveResult.approval.approval_id,
      action_type: proposal.action_type,
      idempotency_key: "fixed_idem_key_101",
    });
    expect(execResult1.was_idempotent).toBe(false);

    // Duplicate execution with identical idempotency key
    const execResult2 = await apiClient.executeCase("case_golden_01", {
      approval_id: approveResult.approval.approval_id,
      action_type: proposal.action_type,
      idempotency_key: "fixed_idem_key_101",
    });
    expect(execResult2.was_idempotent).toBe(true);
    expect(execResult2.action.action_id).toBe(execResult1.action.action_id);
  });
});
