/**
 * Deterministic seed fixtures for Aro offline demo mode.
 * All synthetic events are strictly classified with provenance="demo_synthetic".
 */

import {
  Case,
  CaseBrief,
  CaseContext,
  Location,
  Proposal,
  RingDevice,
  RingEvent,
} from "../types/contracts";

export const MOCK_ORGANIZATION = {
  org_id: "org_demo",
  name: "Acme Logistics Facility Ops",
  created_at: "2026-10-01T00:00:00Z",
};

export const MOCK_LOCATIONS: Record<string, Location> = {
  loc_main_facility: {
    location_id: "loc_main_facility",
    organization_id: "org_demo",
    name: "North Logistics Center — Building A",
    timezone: "America/New_York",
    business_hours_start: "08:00",
    business_hours_end: "18:00",
    business_days: [0, 1, 2, 3, 4],
  },
};

export const MOCK_DEVICES: Record<string, RingDevice> = {
  dev_front_doorbell: {
    device_id: "dev_front_doorbell",
    location_id: "loc_main_facility",
    name: "Front Staff Entrance Doorbell",
    kind: "doorbell",
    is_designated_door: true,
  },
  dev_dock_camera: {
    device_id: "dev_dock_camera",
    location_id: "loc_main_facility",
    name: "North Loading Bay Cam 1",
    kind: "camera",
    is_designated_door: true,
  },
};

// 1. GOLDEN PATH CASE: Awaiting Human Approval
export const GOLDEN_CASE_ID = "case_golden_01";

export const MOCK_GOLDEN_EVENT: RingEvent = {
  event_id: "evt_synthetic_01",
  request_id: "req_synthetic_01",
  device_id: "dev_front_doorbell",
  event_type: "doorbell_ring",
  occurred_at: "2026-10-08T02:30:15Z",
  provenance: "demo_synthetic",
  received_at: "2026-10-08T02:30:16Z",
  signature_verified: true,
  processing_status: "CORRELATED",
  case_id: GOLDEN_CASE_ID,
};

export const MOCK_GOLDEN_CONTEXT: CaseContext = {
  case_id: GOLDEN_CASE_ID,
  organization_id: "org_demo",
  location_id: "loc_main_facility",
  device_id: "dev_front_doorbell",
  is_after_hours: true,
  designated_entrance: true,
  expected_delivery_status: "FALSE",
  expected_deliveries: [],
  correlated_events: [
    {
      normalized_event_id: "norm_01",
      source_event_id: "evt_synthetic_01",
      device_id: "dev_front_doorbell",
      location_id: "loc_main_facility",
      event_type: "doorbell_ring",
      occurred_at: "2026-10-08T02:30:15Z",
      provenance: "demo_synthetic",
      is_after_hours: true,
      is_designated_door: true,
      description: "Doorbell activity observed at designated staff entrance outside business hours",
    },
  ],
  context_assembled_at: "2026-10-08T02:30:18Z",
};

export const MOCK_GOLDEN_BRIEF: CaseBrief = {
  brief_id: "brief_01",
  case_id: GOLDEN_CASE_ID,
  summary:
    "Doorbell activity observed at designated facility entrance at 02:30 UTC outside business hours. No deliveries were scheduled or expected for this window.",
  facts: [
    "Activity observed at designated staff entrance (Front Staff Entrance Doorbell)",
    "Observed timestamp 02:30 UTC is outside configured business hours (08:00–18:00 EDT)",
    "Expected delivery status is FALSE; zero scheduled manifests active",
  ],
  unknowns: [
    "Identity, affiliation, or intent of individual at the entrance",
    "Whether physical items or parcels were left at the entryway",
    "Whether facility access or door release was attempted",
  ],
  context_match: "High certainty after-hours unexpected arrival",
  is_fallback: false,
  generated_at: "2026-10-08T02:30:20Z",
};

export const MOCK_GOLDEN_PROPOSAL: Proposal = {
  proposal_id: "prop_golden_01",
  case_id: GOLDEN_CASE_ID,
  action_type: "NOTIFY_OPERATOR",
  reason: "After-hours entrance activity observed without scheduled delivery; requires on-duty staff notification.",
  parameters: {
    message: "Unexpected after-hours doorbell activity observed at Front Staff Entrance. No scheduled delivery.",
    urgency: "normal",
    recipient_role: "OPERATOR",
  },
  // Exact canonical SHA-256 hash matching backend proposal hashing algorithm
  proposal_hash: "a4c8f58e65e4860b29841804e1bc2a946b2b73315a6767ea321d234dbb9b91f2",
  created_at: "2026-10-08T02:30:22Z",
};

export const MOCK_GOLDEN_CASE: Case = {
  case_id: GOLDEN_CASE_ID,
  organization_id: "org_demo",
  location_id: "loc_main_facility",
  device_id: "dev_front_doorbell",
  event_id: "evt_synthetic_01",
  title: "After-Hours Entrance Activity",
  status: "APPROVAL_PENDING",
  version: 1,
  summary: "Doorbell activity observed outside business hours at designated entrance.",
  brief_id: "brief_01",
  active_proposal_id: "prop_golden_01",
  created_at: "2026-10-08T02:30:17Z",
  updated_at: "2026-10-08T02:30:22Z",
};

// Additional seeded cases for comprehensive operational queue
export const MOCK_CASES_SEED: Case[] = [
  MOCK_GOLDEN_CASE,
  {
    case_id: "case_review_02",
    organization_id: "org_demo",
    location_id: "loc_main_facility",
    device_id: "dev_dock_camera",
    event_id: "evt_synthetic_02",
    title: "Loading Dock Motion Sequence",
    status: "APPROVAL_PENDING",
    version: 1,
    summary: "Repeated motion activity observed at North Loading Bay gate.",
    brief_id: "brief_02",
    active_proposal_id: "prop_review_02",
    created_at: "2026-10-08T01:45:00Z",
    updated_at: "2026-10-08T01:45:10Z",
  },
  {
    case_id: "case_executing_03",
    organization_id: "org_demo",
    location_id: "loc_main_facility",
    device_id: "dev_dock_camera",
    event_id: "evt_synthetic_03",
    title: "Overnight Gate Confirmation",
    status: "EXECUTING",
    version: 2,
    summary: "Operator confirmation dispatch in flight for dock barrier inspection.",
    active_proposal_id: "prop_03",
    active_approval_id: "appr_03",
    created_at: "2026-10-08T00:10:00Z",
    updated_at: "2026-10-08T00:12:00Z",
  },
  {
    case_id: "case_completed_04",
    organization_id: "org_demo",
    location_id: "loc_main_facility",
    device_id: "dev_front_doorbell",
    event_id: "evt_synthetic_04",
    title: "Authorized Courier Activity",
    status: "COMPLETED",
    version: 3,
    summary: "After-hours expected courier arrival verified and closed with no action required.",
    active_proposal_id: "prop_04",
    active_approval_id: "appr_04",
    created_at: "2026-10-07T22:15:00Z",
    updated_at: "2026-10-07T22:20:00Z",
    closed_at: "2026-10-07T22:20:00Z",
    closure_reason: "Recorded no action: Activity aligned with authorized overnight delivery window.",
  },
  {
    case_id: "case_unresolved_05",
    organization_id: "org_demo",
    location_id: "loc_main_facility",
    device_id: "dev_front_doorbell",
    event_id: "evt_synthetic_05",
    title: "Weather Wind False Trigger",
    status: "UNRESOLVED",
    version: 2,
    summary: "Operator rejected notification proposal due to known banner wind flutter.",
    created_at: "2026-10-07T19:30:00Z",
    updated_at: "2026-10-07T19:35:00Z",
    closure_reason: "Operator rejected proposal: Exterior entrance banner flutter false motion trigger.",
  },
];
