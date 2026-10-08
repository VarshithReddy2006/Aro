/**
 * Canonical TypeScript contracts for Aro.
 * Directly mirrors packages/contracts domain models and enums.
 */

export type Provenance = "ring_signed" | "ring_history" | "demo_synthetic";

export const CaseStatus = {
  RECEIVED: "RECEIVED",
  VALIDATED: "VALIDATED",
  CASE_CREATED: "CASE_CREATED",
  CONTEXT_READY: "CONTEXT_READY",
  PROPOSAL_READY: "PROPOSAL_READY",
  APPROVAL_PENDING: "APPROVAL_PENDING",
  APPROVED: "APPROVED",
  EXECUTING: "EXECUTING",
  COMPLETED: "COMPLETED",
  CLOSED: "CLOSED",
  FAILED: "FAILED",
  RETRYING: "RETRYING",
  UNRESOLVED: "UNRESOLVED",
  OPEN: "OPEN",
  REJECTED: "REJECTED",
  EXPIRED: "EXPIRED",
} as const;
export type CaseStatus = (typeof CaseStatus)[keyof typeof CaseStatus];

export const Role = {
  ADMIN: "ADMIN",
  OPERATOR: "OPERATOR",
  VIEWER: "VIEWER",
} as const;
export type Role = (typeof Role)[keyof typeof Role];

export const ActionType = {
  NOTIFY_OPERATOR: "NOTIFY_OPERATOR",
  MARK_FOR_REVIEW: "MARK_FOR_REVIEW",
  REQUEST_OPERATOR_CONFIRMATION: "REQUEST_OPERATOR_CONFIRMATION",
  RECORD_NO_ACTION: "RECORD_NO_ACTION",
  REQUEST_INFO: "REQUEST_INFO",
  LOG_EXCEPTION: "LOG_EXCEPTION",
  NO_ACTION: "NO_ACTION",
} as const;
export type ActionType = (typeof ActionType)[keyof typeof ActionType];

export const ExpectedDeliveryStatus = {
  TRUE: "TRUE",
  FALSE: "FALSE",
  UNKNOWN: "UNKNOWN",
} as const;
export type ExpectedDeliveryStatus =
  (typeof ExpectedDeliveryStatus)[keyof typeof ExpectedDeliveryStatus];

export const AuditEventType = {
  WEBHOOK_RECEIVED: "WEBHOOK_RECEIVED",
  EVENT_VALIDATED: "EVENT_VALIDATED",
  CASE_CREATED: "CASE_CREATED",
  CONTEXT_ASSEMBLED: "CONTEXT_ASSEMBLED",
  BRIEF_GENERATED: "BRIEF_GENERATED",
  PROPOSAL_CREATED: "PROPOSAL_CREATED",
  APPROVAL_RECORDED: "APPROVAL_RECORDED",
  APPROVAL_REJECTED: "APPROVAL_REJECTED",
  APPROVAL_EXPIRED: "APPROVAL_EXPIRED",
  ACTION_STARTED: "ACTION_STARTED",
  ACTION_COMPLETED: "ACTION_COMPLETED",
  ACTION_FAILED: "ACTION_FAILED",
  CASE_CLOSED: "CASE_CLOSED",
  CASE_UNRESOLVED: "CASE_UNRESOLVED",
} as const;
export type AuditEventType = (typeof AuditEventType)[keyof typeof AuditEventType];

export const ActionStatus = {
  PENDING: "PENDING",
  EXECUTING: "EXECUTING",
  SUCCEEDED: "SUCCEEDED",
  FAILED: "FAILED",
  COMPLETED: "COMPLETED",
} as const;
export type ActionStatus = (typeof ActionStatus)[keyof typeof ActionStatus];

export const ApprovalDecision = {
  APPROVED: "APPROVED",
  REJECTED: "REJECTED",
} as const;
export type ApprovalDecision =
  (typeof ApprovalDecision)[keyof typeof ApprovalDecision];

export interface User {
  user_id: string;
  organization_id: string;
  email: string;
  name: string;
  role: Role;
}

export interface Organization {
  org_id: string;
  name: string;
  created_at: string;
}

export interface Location {
  location_id: string;
  organization_id: string;
  name: string;
  timezone: string;
  business_hours_start: string;
  business_hours_end: string;
  business_days: number[];
}

export interface RingDevice {
  device_id: string;
  location_id: string;
  name: string;
  kind: string;
  is_designated_door: boolean;
}

export interface RingEvent {
  event_id: string;
  request_id: string;
  device_id: string;
  event_type: string;
  occurred_at: string;
  provenance: Provenance;
  payload?: Record<string, unknown>;
  received_at: string;
  signature_verified: boolean;
  processing_status: string;
  case_id?: string | null;
}

export interface NormalizedEvent {
  normalized_event_id: string;
  source_event_id: string;
  device_id: string;
  location_id: string;
  event_type: string;
  occurred_at: string;
  provenance: Provenance;
  is_after_hours: boolean;
  is_designated_door: boolean;
  description: string;
  raw_metadata?: Record<string, unknown>;
}

export interface ExpectedDelivery {
  delivery_id: string;
  organization_id: string;
  location_id: string;
  carrier: string;
  tracking_number?: string | null;
  recipient_name?: string | null;
  status: ExpectedDeliveryStatus;
  expected_window_start?: string | null;
  expected_window_end?: string | null;
}

export interface CaseContext {
  case_id: string;
  organization_id: string;
  location_id: string;
  device_id: string;
  is_after_hours: boolean;
  designated_entrance: boolean;
  expected_delivery_status: ExpectedDeliveryStatus;
  expected_deliveries: ExpectedDelivery[];
  correlated_events: NormalizedEvent[];
  context_assembled_at: string;
  // UI and helper facets:
  known_facts?: {
    is_after_hours?: boolean;
    is_designated_entrance?: boolean;
    has_expected_delivery?: boolean;
    recent_event_count?: number;
    device_type?: string;
  };
  unknown_facts?: string[];
  recent_events?: NormalizedEvent[];
}

export interface CaseBrief {
  brief_id: string;
  case_id: string;
  summary: string;
  facts: string[];
  unknowns: string[];
  context_match: string;
  is_fallback: boolean;
  generated_at: string;
  recommended_action?: string;
  urgency?: string;
}

export interface Proposal {
  proposal_id: string;
  case_id: string;
  action_type: ActionType;
  reason: string;
  parameters: Record<string, unknown>;
  proposal_hash: string;
  created_at: string;
  expires_at?: string | null;
}

export interface Approval {
  approval_id: string;
  organization_id: string;
  case_id: string;
  proposal_id: string;
  proposal_hash: string;
  approved_by: string;
  approved_at: string;
  expires_at: string;
  decision: ApprovalDecision;
  case_version: number;
  created_at: string;
  updated_at: string;
  approver_role?: Role;
}

export interface Action {
  action_id: string;
  case_id: string;
  approval_id: string;
  action_type: ActionType;
  parameters: Record<string, unknown>;
  status: ActionStatus;
  executed_at?: string | null;
  result_summary?: string | null;
  error_message?: string | null;
  idempotency_key: string;
  // UI convenient aliases:
  result?: Record<string, unknown>;
  error?: string;
}

export interface AuditEvent {
  event_id: string;
  case_id: string;
  actor_id: string;
  actor_type: string;
  action: AuditEventType | string;
  timestamp: string;
  previous_hash: string;
  current_hash: string;
  metadata: Record<string, unknown>;
  // UI & backend compatibility aliases:
  event_type?: string;
  occurred_at?: string;
  event_hash?: string;
  previous_event_hash?: string;
  case_version?: number;
  payload?: Record<string, unknown>;
}

export interface Policy {
  policy_id: string;
  organization_id: string;
  allowed_actions: ActionType[];
  approval_timeout_seconds: number;
  auto_resolve_no_action: boolean;
  require_admin_above_priority: boolean;
}

export interface Case {
  case_id: string;
  organization_id: string;
  location_id: string;
  device_id: string;
  event_id: string;
  title: string;
  status: CaseStatus;
  version: number;
  summary?: string | null;
  brief_id?: string | null;
  active_proposal_id?: string | null;
  active_approval_id?: string | null;
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
  closure_reason?: string | null;
  // UI convenient display aliases:
  location?: string;
  occurred_at?: string;
  context?: CaseContext;
}

export type { CaseDetailBundle } from "./api";
