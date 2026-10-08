import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StatusBadge } from "../components/StatusBadge";
import { EventCard } from "../components/EventCard";
import { CaseContextCard } from "../components/CaseContextCard";
import { AIBriefCard } from "../components/AIBriefCard";
import { ProposalReviewCard } from "../components/ProposalReviewCard";
import { ApprovalModal } from "../components/ApprovalModal";
import { RejectionModal } from "../components/RejectionModal";
import { ActionReceiptCard } from "../components/ActionReceiptCard";
import { CaseTimeline } from "../components/CaseTimeline";
import {
  CaseStatus,
  ActionStatus,
  Role,
  ActionType,
  Case,
  CaseContext,
  CaseBrief,
  Proposal,
  Action,
  AuditEvent,
} from "../types/contracts";

describe("StatusBadge Component", () => {
  it("renders textual status labels for accessibility without relying solely on color", () => {
    const { rerender } = render(<StatusBadge status={CaseStatus.APPROVAL_PENDING} />);
    expect(screen.getByText("APPROVAL PENDING")).toBeDefined();

    rerender(<StatusBadge status={CaseStatus.COMPLETED} />);
    expect(screen.getByText("COMPLETED")).toBeDefined();

    rerender(<StatusBadge status={CaseStatus.REJECTED} />);
    expect(screen.getByText("REJECTED")).toBeDefined();

    rerender(<StatusBadge status={CaseStatus.UNRESOLVED} />);
    expect(screen.getByText("UNRESOLVED")).toBeDefined();
  });
});

describe("EventCard Component", () => {
  it("displays observed physical facts and communicates Ring boundary limitations", () => {
    const testCase: Case = {
      case_id: "case_test_01",
      organization_id: "org_01",
      location_id: "loc_01",
      location: "Main Staff Gate",
      device_id: "dev_doorbell",
      event_id: "ev_01",
      title: "After-hours doorbell event",
      status: CaseStatus.APPROVAL_PENDING,
      version: 1,
      created_at: "2026-10-08T02:30:00Z",
      updated_at: "2026-10-08T02:30:00Z",
    };

    const context: CaseContext = {
      case_id: "case_test_01",
      organization_id: "org_01",
      location_id: "loc_01",
      device_id: "dev_doorbell",
      is_after_hours: true,
      designated_entrance: true,
      expected_delivery_status: "FALSE",
      expected_deliveries: [],
      correlated_events: [],
      context_assembled_at: "2026-10-08T02:30:05Z",
      known_facts: {
        is_after_hours: true,
        is_designated_entrance: true,
      },
    };

    render(<EventCard caseData={testCase} context={context} />);

    expect(screen.getByText("Observed Physical Event")).toBeDefined();
    expect(screen.getByText("Doorbell activity observed")).toBeDefined();
    expect(screen.getByText("Main Staff Gate")).toBeDefined();
    expect(screen.getByText(/Ring hardware detects motion\/doorbell press only/)).toBeDefined();
  });
});

describe("CaseContextCard Component", () => {
  it("renders deterministic knowns vs unknowns side-by-side", () => {
    const context: CaseContext = {
      case_id: "case_test_01",
      organization_id: "org_01",
      location_id: "loc_01",
      device_id: "dev_doorbell",
      is_after_hours: true,
      designated_entrance: true,
      expected_delivery_status: "FALSE",
      expected_deliveries: [],
      correlated_events: [],
      context_assembled_at: "2026-10-08T02:30:05Z",
      known_facts: {
        is_after_hours: true,
        is_designated_entrance: true,
        has_expected_delivery: false,
      },
      unknown_facts: [
        "Whether a parcel was delivered",
        "Identity or affiliation of the individual",
      ],
    };

    render(<CaseContextCard context={context} />);

    expect(screen.getByText("Known Facts (Deterministic)")).toBeDefined();
    expect(screen.getByText("Unknowns (Unverified Bounds)")).toBeDefined();
    expect(screen.getByText("Whether a parcel was delivered")).toBeDefined();
    expect(screen.getByText("Identity or affiliation of the individual")).toBeDefined();
  });
});

describe("AIBriefCard Component", () => {
  it("renders bounded operational brief with explicit AI boundary notice", () => {
    const brief: CaseBrief = {
      brief_id: "brief_01",
      case_id: "case_01",
      summary: "After-hours physical doorbell activity observed. No expected delivery recorded.",
      facts: ["Event occurred outside business hours", "Designated entrance"],
      unknowns: ["Identity of individual unverified"],
      context_match: "EXACT_AFTER_HOURS_RULE",
      is_fallback: false,
      generated_at: "2026-10-08T02:31:00Z",
      recommended_action: ActionType.NOTIFY_OPERATOR,
      urgency: "normal",
    };

    render(<AIBriefCard brief={brief} />);

    expect(screen.getByText("Bounded Operational AI Brief")).toBeDefined();
    expect(screen.getByText(/AI operational briefing is strictly descriptive/)).toBeDefined();
    expect(screen.getByText(brief.summary)).toBeDefined();
    expect(screen.getByText("Event occurred outside business hours")).toBeDefined();
  });
});

describe("ProposalReviewCard Component", () => {
  const proposal: Proposal = {
    proposal_id: "prop_01",
    case_id: "case_01",
    action_type: ActionType.NOTIFY_OPERATOR,
    reason: "After-hours activity requires operator review.",
    parameters: {
      urgency: "normal",
      recipient: "Operator",
    },
    proposal_hash: "a4c8f58e65e4860b29841804e1bc2a946b2b73315a6767ea321d234dbb9b91f2",
    created_at: new Date(Date.now() - 60000).toISOString(),
    expires_at: new Date(Date.now() + 3600000).toISOString(),
  };

  it("renders human approval required boundary for OPERATOR", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();

    render(
      <ProposalReviewCard
        proposal={proposal}
        caseVersion={1}
        caseStatus={CaseStatus.APPROVAL_PENDING}
        currentRole={Role.OPERATOR}
        onApproveClick={onApprove}
        onRejectClick={onReject}
      />
    );

    expect(screen.getByText("Human Approval Required")).toBeDefined();
    expect(screen.getByText("Approve Proposal")).toBeDefined();
    expect(screen.getByText("Reject Proposal")).toBeDefined();

    fireEvent.click(screen.getByText("Approve Proposal"));
    expect(onApprove).toHaveBeenCalledOnce();
  });

  it("hides approval action buttons for VIEWER role", () => {
    render(
      <ProposalReviewCard
        proposal={proposal}
        caseVersion={1}
        caseStatus={CaseStatus.APPROVAL_PENDING}
        currentRole={Role.VIEWER}
        onApproveClick={vi.fn()}
        onRejectClick={vi.fn()}
      />
    );

    expect(screen.queryByText("Approve Proposal")).toBeNull();
    expect(screen.queryByText("Reject Proposal")).toBeNull();
    expect(screen.getByText(/Active role is/)).toBeDefined();
  });
});

describe("ApprovalModal & RejectionModal Components", () => {
  const proposal: Proposal = {
    proposal_id: "prop_01",
    case_id: "case_01",
    action_type: ActionType.NOTIFY_OPERATOR,
    reason: "After-hours activity requires operator review.",
    parameters: {},
    proposal_hash: "a4c8f58e65e4860b29841804e1bc2a946b2b73315a6767ea321d234dbb9b91f2",
    created_at: "2026-10-08T02:31:10Z",
    expires_at: "2026-10-08T03:31:10Z",
  };

  it("ApprovalModal displays exact proposal hash and case version for explicit review", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();

    render(
      <ApprovalModal
        isOpen={true}
        proposal={proposal}
        caseVersion={3}
        caseId="case_01"
        isSubmitting={false}
        onConfirm={onConfirm}
        onClose={onClose}
      />
    );

    expect(screen.getByText("Confirm Human Approval")).toBeDefined();
    expect(screen.getByText(proposal.proposal_hash)).toBeDefined();
    expect(screen.getByText("v3")).toBeDefined();

    fireEvent.click(screen.getByText("Authorize Action"));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("RejectionModal requires an explicit rejection reason before confirming", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();

    render(
      <RejectionModal
        isOpen={true}
        proposal={proposal}
        caseVersion={3}
        caseId="case_01"
        isSubmitting={false}
        onConfirm={onConfirm}
        onClose={onClose}
      />
    );

    fireEvent.click(screen.getByText("Confirm Rejection"));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText(/rejection reason is required/)).toBeDefined();

    const textarea = screen.getByLabelText(/Rejection Reason/);
    fireEvent.change(textarea, { target: { value: "Authorized maintenance crew" } });

    fireEvent.click(screen.getByText("Confirm Rejection"));
    expect(onConfirm).toHaveBeenCalledWith("Authorized maintenance crew");
  });
});

describe("ActionReceiptCard Component", () => {
  it("renders execution receipt with status and displays idempotency replay cache notice", () => {
    const action: Action = {
      action_id: "act_01",
      case_id: "case_01",
      approval_id: "appr_01",
      action_type: ActionType.NOTIFY_OPERATOR,
      parameters: { urgency: "normal" },
      status: ActionStatus.COMPLETED,
      executed_at: "2026-10-08T02:33:00Z",
      result: { message: "Notification delivered" },
      idempotency_key: "idem_01",
    };
    (action as any).was_idempotent = true;

    render(<ActionReceiptCard action={action} />);

    expect(screen.getByText("Deterministic Action Receipt")).toBeDefined();
    expect(screen.getByText(/Action already executed/)).toBeDefined();
    expect(screen.getByText("Replay Cached Result")).toBeDefined();
    expect(screen.getByText("act_01")).toBeDefined();
  });
});

describe("CaseTimeline Component", () => {
  it("renders chronological audit events and displays tamper-evident badge", () => {
    const timeline: AuditEvent[] = [
      {
        event_id: "aud_01",
        case_id: "case_01",
        actor_id: "ring_webhook",
        actor_type: "SYSTEM",
        action: "WEBHOOK_RECEIVED",
        timestamp: "2026-10-08T02:30:00Z",
        previous_hash: "0000000000000000000000000000000000000000000000000000000000000000",
        current_hash: "hash_01",
        metadata: { case_version: 1 },
      },
      {
        event_id: "aud_02",
        case_id: "case_01",
        actor_id: "operator_01",
        actor_type: "HUMAN",
        action: "APPROVAL_RECORDED",
        timestamp: "2026-10-08T02:32:00Z",
        previous_hash: "hash_01",
        current_hash: "hash_02",
        metadata: { case_version: 2 },
      },
    ];

    render(<CaseTimeline timeline={timeline} />);

    expect(screen.getByText("Operational Timeline & Audit Trail")).toBeDefined();
    expect(screen.getByText("Tamper-Evident Chain Verified")).toBeDefined();
    expect(screen.getByText("WEBHOOK RECEIVED")).toBeDefined();
    expect(screen.getByText("APPROVAL RECORDED")).toBeDefined();
  });
});
