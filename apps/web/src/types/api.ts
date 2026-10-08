/**
 * API Request/Response and Error types for Aro frontend.
 */

import {
  Action,
  Approval,
  AuditEvent,
  Case,
  CaseBrief,
  CaseContext,
  CaseStatus,
  Location,
  Proposal,
  RingDevice,
  RingEvent,
} from "./contracts";

export interface ApproveCaseRequest {
  proposal_id: string;
  proposal_hash: string;
  case_version: number;
  expires_at?: string;
}

export interface ApproveCaseResponse {
  status: "APPROVED";
  approval: Approval;
}

export interface RejectCaseRequest {
  proposal_id: string;
  proposal_hash: string;
  case_version: number;
  reason: string;
}

export interface RejectCaseResponse {
  status: "REJECTED";
  rejection: Approval;
}

export interface ExecuteCaseRequest {
  approval_id: string;
  case_version?: number;
  action_type?: string;
  parameters?: Record<string, unknown>;
  idempotency_key?: string;
}

export interface ExecuteCaseResponse {
  status: "EXECUTED";
  action: Action;
  case_status: CaseStatus;
  was_idempotent: boolean;
  receipt?: Record<string, unknown>;
}

export interface CaseDetailBundle {
  case: Case;
  event?: RingEvent;
  location?: Location;
  device?: RingDevice;
  context?: CaseContext;
  brief?: CaseBrief;
  proposal?: Proposal;
  approval?: Approval;
  action?: Action;
  timeline: AuditEvent[];
  audit_chain_verified?: boolean;
}

export interface ApiError {
  status: number;
  code: string;
  message: string;
  details?: string;
}
