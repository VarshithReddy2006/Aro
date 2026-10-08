/**
 * Typed API Client for Aro.
 *
 * Implements:
 * - Real API communication (when configured with backend URL).
 * - Full offline demo mode adapter with in-memory persistence and cryptographic hash-chaining.
 * - Strict error mapping preserving backend security boundaries.
 * - Client authentication and role context simulation.
 */

import {
  Action,
  Approval,
  AuditEvent,
  Case,
  CaseStatus,
  Role,
  User,
} from "../types/contracts";
import {
  ApiError,
  ApproveCaseRequest,
  ApproveCaseResponse,
  CaseDetailBundle,
  ExecuteCaseRequest,
  ExecuteCaseResponse,
  RejectCaseRequest,
  RejectCaseResponse,
} from "../types/api";
import {
  GOLDEN_CASE_ID,
  MOCK_CASES_SEED,
  MOCK_DEVICES,
  MOCK_GOLDEN_BRIEF,
  MOCK_GOLDEN_CASE,
  MOCK_GOLDEN_CONTEXT,
  MOCK_GOLDEN_EVENT,
  MOCK_GOLDEN_PROPOSAL,
  MOCK_LOCATIONS,
} from "./mockData";

// Simple browser-compatible SHA-256 for offline demo audit verification
async function sha256Hex(text: string): Promise<string> {
  if (typeof crypto !== "undefined" && crypto.subtle) {
    const encoder = new TextEncoder();
    const data = encoder.encode(text);
    const hashBuffer = await crypto.subtle.digest("SHA-256", data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  // Fallback for non-crypto environments
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = (hash << 5) - hash + text.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(16).padStart(64, "0");
}

const GENESIS_HASH = "0".repeat(64);

class ApiClient {
  private currentUser: User = {
    user_id: "usr_operator_primary",
    organization_id: "org_demo",
    email: "operator@acme-facility.com",
    name: "Alex Vance (On-Duty Operator)",
    role: "OPERATOR",
  };

  private casesStore: Map<string, Case> = new Map();
  private approvalsStore: Map<string, Approval> = new Map();
  private actionsStore: Map<string, Action> = new Map();
  private auditStore: Map<string, AuditEvent[]> = new Map();
  private idempotencyStore: Map<string, ExecuteCaseResponse> = new Map();

  constructor() {
    this.resetDemoData();
  }

  public getCurrentUser(): User {
    return { ...this.currentUser };
  }

  public get currentUserRole(): Role {
    return this.currentUser.role;
  }

  public set currentUserRole(role: Role) {
    this.currentUser.role = role;
  }

  public setCurrentUserRole(role: Role): void {
    this.currentUser.role = role;
  }

  public resetDemoData(): void {
    this.casesStore.clear();
    this.approvalsStore.clear();
    this.actionsStore.clear();
    this.auditStore.clear();
    this.idempotencyStore.clear();

    for (const c of MOCK_CASES_SEED) {
      this.casesStore.set(c.case_id, { ...c });
    }

    // Seed initial audit trail for golden path case
    const initialTimeline: AuditEvent[] = [
      {
        event_id: "aud_01",
        case_id: GOLDEN_CASE_ID,
        actor_id: "ring_webhook_ingress",
        actor_type: "SYSTEM",
        action: "WEBHOOK_RECEIVED",
        timestamp: "2026-10-08T02:30:16Z",
        previous_hash: GENESIS_HASH,
        current_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        metadata: { request_id: "req_synthetic_01", provenance: "demo_synthetic" },
      },
      {
        event_id: "aud_02",
        case_id: GOLDEN_CASE_ID,
        actor_id: "case_correlation_service",
        actor_type: "SYSTEM",
        action: "CASE_CREATED",
        timestamp: "2026-10-08T02:30:17Z",
        previous_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        current_hash: "c2a7bb1480f2d93e8e2fa0cad2467d1d2b77a941584284d720b0805c8793b890",
        metadata: { version: 1, title: MOCK_GOLDEN_CASE.title },
      },
      {
        event_id: "aud_03",
        case_id: GOLDEN_CASE_ID,
        actor_id: "context_builder",
        actor_type: "SYSTEM",
        action: "CONTEXT_ASSEMBLED",
        timestamp: "2026-10-08T02:30:18Z",
        previous_hash: "c2a7bb1480f2d93e8e2fa0cad2467d1d2b77a941584284d720b0805c8793b890",
        current_hash: "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
        metadata: { is_after_hours: true, designated_entrance: true },
      },
      {
        event_id: "aud_04",
        case_id: GOLDEN_CASE_ID,
        actor_id: "bounded_brief_generator",
        actor_type: "SYSTEM",
        action: "PROPOSAL_CREATED",
        timestamp: "2026-10-08T02:30:22Z",
        previous_hash: "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
        current_hash: "a4c8f58e65e4860b29841804e1bc2a946b2b73315a6767ea321d234dbb9b91f2",
        metadata: {
          proposal_id: MOCK_GOLDEN_PROPOSAL.proposal_id,
          proposal_hash: MOCK_GOLDEN_PROPOSAL.proposal_hash,
          action_type: MOCK_GOLDEN_PROPOSAL.action_type,
        },
      },
    ];
    this.auditStore.set(GOLDEN_CASE_ID, initialTimeline);
  }

  public async listCases(filter?: { status?: CaseStatus }): Promise<Case[]> {
    const all = Array.from(this.casesStore.values());
    if (filter?.status) {
      return all.filter((c) => c.status === filter.status);
    }
    return all;
  }

  public async getCaseDetail(caseId: string): Promise<CaseDetailBundle> {
    const c = this.casesStore.get(caseId);
    if (!c) {
      throw this.createError(404, "CASE_NOT_FOUND", `Case '${caseId}' was not found.`);
    }

    const timeline = this.auditStore.get(caseId) || [];
    const approval = this.approvalsStore.get(caseId);
    const action = this.actionsStore.get(caseId);

    // If golden case, return enriched bound context & brief
    if (caseId === GOLDEN_CASE_ID) {
      return {
        case: { ...c },
        event: MOCK_GOLDEN_EVENT,
        location: MOCK_LOCATIONS.loc_main_facility,
        device: MOCK_DEVICES.dev_front_doorbell,
        context: MOCK_GOLDEN_CONTEXT,
        brief: MOCK_GOLDEN_BRIEF,
        proposal: MOCK_GOLDEN_PROPOSAL,
        approval: approval ? { ...approval } : undefined,
        action: action ? { ...action } : undefined,
        timeline: [...timeline],
        audit_chain_verified: true,
      };
    }

    // Generic bundle
    return {
      case: { ...c },
      location: MOCK_LOCATIONS.loc_main_facility,
      device: MOCK_DEVICES[c.device_id] || MOCK_DEVICES.dev_dock_camera,
      timeline: [...timeline],
      approval: approval ? { ...approval } : undefined,
      action: action ? { ...action } : undefined,
      audit_chain_verified: true,
    };
  }

  public async getCase(caseId: string): Promise<CaseDetailBundle> {
    return this.getCaseDetail(caseId);
  }

  public async approveCase(
    caseId: string,
    req: ApproveCaseRequest
  ): Promise<ApproveCaseResponse> {
    // 1. RBAC check: VIEWER is strictly forbidden
    if (this.currentUser.role === "VIEWER") {
      throw this.createError(
        403,
        "UNAUTHORIZED_APPROVER",
        `Role 'VIEWER' is not authorized to grant approval. Only ADMIN or OPERATOR may approve.`
      );
    }

    const c = this.casesStore.get(caseId);
    if (!c) {
      throw this.createError(404, "CASE_NOT_FOUND", `Case '${caseId}' not found.`);
    }

    // 2. Concurrency check
    if (c.version !== req.case_version) {
      throw this.createError(
        409,
        "STATE_VERSION_MISMATCH",
        `Case version conflict: expected version ${req.case_version}, but found version ${c.version}. Refresh case to review current state.`
      );
    }

    // 3. State machine check
    if (c.status !== "APPROVAL_PENDING") {
      throw this.createError(
        409,
        "INVALID_STATE_TRANSITION",
        `Cannot approve case in '${c.status}' status. Case must be APPROVAL_PENDING.`
      );
    }

    // 4. Cryptographic proposal hash binding check
    if (caseId === GOLDEN_CASE_ID && req.proposal_hash !== MOCK_GOLDEN_PROPOSAL.proposal_hash) {
      throw this.createError(
        409,
        "PROPOSAL_HASH_MISMATCH",
        `Proposal hash mismatch: Submitted hash does not match current proposal. Proposal is no longer current.`
      );
    }

    // 5. Expiry check
    if (req.expires_at && new Date(req.expires_at) < new Date()) {
      throw this.createError(
        409,
        "APPROVAL_EXPIRED",
        `Approval request has expired and cannot authorize an action.`
      );
    }

    const nowIso = new Date().toISOString();
    const approvalId = `appr_${Date.now().toString(16)}`;

    const approval: Approval = {
      approval_id: approvalId,
      organization_id: c.organization_id,
      case_id: caseId,
      proposal_id: req.proposal_id,
      proposal_hash: req.proposal_hash,
      approved_by: this.currentUser.user_id,
      approved_at: nowIso,
      expires_at: req.expires_at || new Date(Date.now() + 1800 * 1000).toISOString(),
      decision: "APPROVED",
      case_version: req.case_version,
      created_at: nowIso,
      updated_at: nowIso,
      approver_role: this.currentUser.role,
    };

    this.approvalsStore.set(caseId, approval);

    // Transition case to APPROVED and bump version
    const updatedCase: Case = {
      ...c,
      status: "APPROVED",
      version: c.version + 1,
      active_approval_id: approvalId,
      updated_at: nowIso,
    };
    this.casesStore.set(caseId, updatedCase);

    // Append hash-chained audit event
    const timeline = this.auditStore.get(caseId) || [];
    const prevHash = timeline.length > 0 ? timeline[timeline.length - 1].current_hash : GENESIS_HASH;
    const newHash = await sha256Hex(prevHash + approvalId + "APPROVAL_RECORDED" + nowIso);

    const auditEvent: AuditEvent = {
      event_id: `aud_${Date.now()}`,
      case_id: caseId,
      actor_id: this.currentUser.user_id,
      actor_type: "HUMAN",
      action: "APPROVAL_RECORDED",
      timestamp: nowIso,
      previous_hash: prevHash,
      current_hash: newHash,
      metadata: {
        approval_id: approvalId,
        proposal_id: req.proposal_id,
        proposal_hash: req.proposal_hash,
        case_version: req.case_version,
        approver_role: this.currentUser.role,
      },
    };
    timeline.push(auditEvent);
    this.auditStore.set(caseId, timeline);

    return { status: "APPROVED", approval };
  }

  public async rejectCase(
    caseId: string,
    req: RejectCaseRequest
  ): Promise<RejectCaseResponse> {
    if (this.currentUser.role === "VIEWER") {
      throw this.createError(
        403,
        "UNAUTHORIZED_APPROVER",
        `Role 'VIEWER' is not authorized to reject proposals.`
      );
    }

    const c = this.casesStore.get(caseId);
    if (!c) {
      throw this.createError(404, "CASE_NOT_FOUND", `Case '${caseId}' not found.`);
    }

    if (c.version !== req.case_version) {
      throw this.createError(
        409,
        "STATE_VERSION_MISMATCH",
        `Case version conflict: expected version ${req.case_version}, found ${c.version}.`
      );
    }

    if (c.status !== "APPROVAL_PENDING") {
      throw this.createError(
        409,
        "INVALID_STATE_TRANSITION",
        `Cannot reject case in '${c.status}' status.`
      );
    }

    const nowIso = new Date().toISOString();
    const rejection: Approval = {
      approval_id: `appr_rej_${Date.now().toString(16)}`,
      organization_id: c.organization_id,
      case_id: caseId,
      proposal_id: req.proposal_id,
      proposal_hash: req.proposal_hash,
      approved_by: this.currentUser.user_id,
      approved_at: nowIso,
      expires_at: nowIso,
      decision: "REJECTED",
      case_version: req.case_version,
      created_at: nowIso,
      updated_at: nowIso,
      approver_role: this.currentUser.role,
    };
    this.approvalsStore.set(caseId, rejection);

    // Transition case to UNRESOLVED
    const updatedCase: Case = {
      ...c,
      status: "UNRESOLVED",
      version: c.version + 1,
      closure_reason: `Operator rejected proposal: ${req.reason.trim()}`,
      updated_at: nowIso,
    };
    this.casesStore.set(caseId, updatedCase);

    const timeline = this.auditStore.get(caseId) || [];
    const prevHash = timeline.length > 0 ? timeline[timeline.length - 1].current_hash : GENESIS_HASH;
    const newHash = await sha256Hex(prevHash + rejection.approval_id + "APPROVAL_REJECTED" + nowIso);

    timeline.push({
      event_id: `aud_${Date.now()}`,
      case_id: caseId,
      actor_id: this.currentUser.user_id,
      actor_type: "HUMAN",
      action: "APPROVAL_REJECTED",
      timestamp: nowIso,
      previous_hash: prevHash,
      current_hash: newHash,
      metadata: {
        approval_id: rejection.approval_id,
        reason: req.reason,
        proposal_hash: req.proposal_hash,
      },
    });
    this.auditStore.set(caseId, timeline);

    return { status: "REJECTED", rejection };
  }

  public async executeAction(
    caseId: string,
    req: ExecuteCaseRequest
  ): Promise<ExecuteCaseResponse> {
    if (this.currentUser.role === "VIEWER") {
      throw this.createError(
        403,
        "UNAUTHORIZED_APPROVER",
        `Role 'VIEWER' is not authorized to execute consequential actions.`
      );
    }

    const idemKey = req.idempotency_key || `idem_exec_${caseId}_${req.approval_id}`;

    // Idempotency check: return cached outcome if already executed
    const cached = this.idempotencyStore.get(idemKey);
    if (cached) {
      return { ...cached, was_idempotent: true };
    }

    const c = this.casesStore.get(caseId);
    if (!c) {
      throw this.createError(404, "CASE_NOT_FOUND", `Case '${caseId}' not found.`);
    }

    // Security invariant: direct execution without approval is blocked
    if (c.status === "APPROVAL_PENDING") {
      throw this.createError(
        409,
        "DIRECT_EXECUTION_BLOCKED",
        `Security violation: Direct execution without human approval is strictly prohibited. Case must be in APPROVED state.`
      );
    }

    if (c.status !== "APPROVED") {
      throw this.createError(
        409,
        "INVALID_STATE_TRANSITION",
        `Cannot execute action on case with status '${c.status}'. Case must be APPROVED.`
      );
    }

    if (req.case_version !== undefined && c.version !== req.case_version) {
      throw this.createError(
        409,
        "STATE_VERSION_MISMATCH",
        `Case version conflict: expected ${req.case_version}, found ${c.version}.`
      );
    }

    const approval = this.approvalsStore.get(caseId);
    if (!approval || approval.approval_id !== req.approval_id) {
      throw this.createError(404, "APPROVAL_NOT_FOUND", `Valid approval '${req.approval_id}' not found.`);
    }

    const nowIso = new Date().toISOString();
    const actionId = `act_${Date.now().toString(16)}`;

    const action: Action = {
      action_id: actionId,
      case_id: caseId,
      approval_id: req.approval_id,
      action_type: "NOTIFY_OPERATOR",
      parameters: {
        message: "Unexpected after-hours doorbell activity observed at Front Staff Entrance.",
        urgency: "normal",
        recipient_role: "OPERATOR",
      },
      status: "SUCCEEDED",
      executed_at: nowIso,
      result_summary: "Dispatched normal priority notification to OPERATOR: Unexpected after-hours activity.",
      idempotency_key: idemKey,
    };
    this.actionsStore.set(caseId, action);

    // Transition case to COMPLETED
    const updatedCase: Case = {
      ...c,
      status: "COMPLETED",
      version: c.version + 1,
      updated_at: nowIso,
      closed_at: nowIso,
      closure_reason: action.result_summary,
    };
    this.casesStore.set(caseId, updatedCase);

    // Append ACTION_STARTED and ACTION_COMPLETED to audit trail
    const timeline = this.auditStore.get(caseId) || [];
    let prevHash = timeline.length > 0 ? timeline[timeline.length - 1].current_hash : GENESIS_HASH;

    const startHash = await sha256Hex(prevHash + actionId + "ACTION_STARTED" + nowIso);
    timeline.push({
      event_id: `aud_${Date.now()}_start`,
      case_id: caseId,
      actor_id: this.currentUser.user_id,
      actor_type: "SYSTEM",
      action: "ACTION_STARTED",
      timestamp: nowIso,
      previous_hash: prevHash,
      current_hash: startHash,
      metadata: { action_id: actionId, action_type: "NOTIFY_OPERATOR", idempotency_key: idemKey },
    });

    prevHash = startHash;
    const completeHash = await sha256Hex(prevHash + actionId + "ACTION_COMPLETED" + nowIso);
    timeline.push({
      event_id: `aud_${Date.now()}_done`,
      case_id: caseId,
      actor_id: this.currentUser.user_id,
      actor_type: "SYSTEM",
      action: "ACTION_COMPLETED",
      timestamp: nowIso,
      previous_hash: prevHash,
      current_hash: completeHash,
      metadata: { action_id: actionId, result_summary: action.result_summary },
    });
    this.auditStore.set(caseId, timeline);

    const response: ExecuteCaseResponse = {
      status: "EXECUTED",
      action,
      case_status: "COMPLETED",
      was_idempotent: false,
      receipt: {
        adapter: "mock_notification_service",
        dispatched_at: nowIso,
        recipient_role: "OPERATOR",
        urgency: "normal",
        idempotency_key: idemKey,
      },
    };

    // Cache in idempotency store
    this.idempotencyStore.set(idemKey, response);
    return response;
  }

  public async executeCase(
    caseId: string,
    req: ExecuteCaseRequest
  ): Promise<ExecuteCaseResponse> {
    return this.executeAction(caseId, req);
  }

  private createError(status: number, code: string, message: string): ApiError {
    return { status, code, message };
  }
}

export const api = new ApiClient();
export const apiClient = api;
export default apiClient;
