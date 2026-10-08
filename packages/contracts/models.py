"""Canonical domain models for Aro.

Adheres strictly to Ring terminology:
- Never claim Ring detected or confirmed a delivery or package.
- Ring observes motion/doorbell activity associated with a designated entrance.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseStatus,
    EventProcessingStatus,
    ExpectedDeliveryStatus,
    Provenance,
    Role,
)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp formatted as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


class User(BaseModel):
    """Authenticated user within an organization."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(..., min_length=1, description="Unique user identifier")
    organization_id: str = Field(..., min_length=1, description="Organization identifier")
    email: str = Field(..., min_length=3, description="User email address")
    name: str = Field(..., min_length=1, description="Display name of the user")
    role: Role = Field(..., description="Role-based access tier")


class Organization(BaseModel):
    """Tenant organization."""

    model_config = ConfigDict(frozen=True)

    org_id: str = Field(..., min_length=1, description="Unique organization identifier")
    name: str = Field(..., min_length=1, description="Organization name")
    created_at: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 creation timestamp",
    )


class Location(BaseModel):
    """Physical office or facility location monitored by Aro."""

    model_config = ConfigDict(frozen=True)

    location_id: str = Field(..., min_length=1, description="Unique location identifier")
    organization_id: str = Field(
        ..., min_length=1, description="Associated organization identifier"
    )
    name: str = Field(..., min_length=1, description="Facility or office name")
    timezone: str = Field(default="UTC", description="IANA timezone name, e.g. America/New_York")
    business_hours_start: str = Field(
        default="08:00", description="HH:MM formatted start of business hours"
    )
    business_hours_end: str = Field(
        default="20:00", description="HH:MM formatted end of business hours"
    )
    business_days: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4],
        description="List of business days (0=Monday through 6=Sunday)",
    )


class RingDevice(BaseModel):
    """Designated Ring device installed at a facility location."""

    model_config = ConfigDict(frozen=True)

    device_id: str = Field(..., min_length=1, description="Ring device identifier")
    location_id: str = Field(..., min_length=1, description="Associated location identifier")
    name: str = Field(..., min_length=1, description="Device label, e.g. Front Doorbell")
    kind: str = Field(default="doorbell", description="Device category: doorbell or camera")
    is_designated_door: bool = Field(
        default=True,
        description="Whether this device monitors an operational designated entrance",
    )


class ExpectedDelivery(BaseModel):
    """Operational record of expected incoming shipment or courier arrival."""

    model_config = ConfigDict(frozen=True)

    delivery_id: str = Field(..., min_length=1, description="Unique delivery record identifier")
    organization_id: str = Field(
        ..., min_length=1, description="Associated organization identifier"
    )
    location_id: str = Field(..., min_length=1, description="Associated location identifier")
    carrier: str = Field(..., min_length=1, description="Carrier name, e.g. FedEx, UPS, Courier")
    tracking_number: str | None = Field(default=None, description="Tracking identifier if known")
    recipient_name: str | None = Field(default=None, description="Intended recipient or department")
    status: ExpectedDeliveryStatus = Field(
        default=ExpectedDeliveryStatus.UNKNOWN,
        description="Expectation status at time of event evaluation",
    )
    expected_window_start: str | None = Field(
        default=None, description="ISO 8601 start of expected delivery window"
    )
    expected_window_end: str | None = Field(
        default=None, description="ISO 8601 end of expected delivery window"
    )


class RingEvent(BaseModel):
    """Raw, verified event originating from a Ring device or synthetic demo harness."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., min_length=1, description="Unique event identifier")
    request_id: str = Field(
        ..., min_length=1, description="Ring webhook request identifier for deduplication"
    )
    device_id: str = Field(..., min_length=1, description="Designated Ring device identifier")
    event_type: str = Field(..., min_length=1, description="Motion or doorbell activity identifier")
    occurred_at: str = Field(..., description="ISO 8601 timestamp of observed physical event")
    provenance: Provenance = Field(..., description="Verified provenance of event data")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Raw event payload parameters"
    )
    received_at: str = Field(
        default_factory=_utc_now_iso, description="ISO 8601 timestamp when webhook was received"
    )
    signature_verified: bool = Field(
        default=True, description="Whether the event passed cryptographic HMAC verification"
    )
    processing_status: EventProcessingStatus = Field(
        default=EventProcessingStatus.RECEIVED, description="Ingestion processing lifecycle status"
    )
    quarantine_reason: str | None = Field(
        default=None,
        description="Reason if event was signed but quarantined due to malformed payload",
    )
    case_id: str | None = Field(
        default=None, description="Associated case identifier once correlated"
    )


class NormalizedEvent(BaseModel):
    """Canonically normalized event enriched with facility and schedule classification."""

    model_config = ConfigDict(frozen=True)

    normalized_event_id: str = Field(..., min_length=1, description="Unique normalized identifier")
    source_event_id: str = Field(..., min_length=1, description="Source Ring event identifier")
    device_id: str = Field(..., min_length=1, description="Ring device identifier")
    location_id: str = Field(..., min_length=1, description="Monitored location identifier")
    event_type: str = Field(..., min_length=1, description="Type of motion/doorbell activity")
    occurred_at: str = Field(..., description="ISO 8601 event timestamp")
    provenance: Provenance = Field(..., description="Data provenance tier")
    is_after_hours: bool = Field(
        ..., description="Whether activity occurred outside configured business hours"
    )
    is_designated_door: bool = Field(
        ..., description="Whether activity was associated with a designated door"
    )
    description: str = Field(
        ...,
        description="Factual description, e.g. motion/doorbell activity observed at designated entrance",
    )
    raw_metadata: dict[str, Any] = Field(
        default_factory=dict, description="Preserved source metadata"
    )


class CaseContext(BaseModel):
    """Aggregated operational context assembled deterministically for brief generation."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(..., min_length=1, description="Target case identifier")
    organization_id: str = Field(..., min_length=1, description="Organization identifier")
    location_id: str = Field(..., min_length=1, description="Location identifier")
    device_id: str = Field(..., min_length=1, description="Ring device identifier")
    is_after_hours: bool = Field(
        ..., description="True if activity occurred outside business hours"
    )
    designated_entrance: bool = Field(..., description="True if activity was at a designated door")
    expected_delivery_status: ExpectedDeliveryStatus = Field(
        ..., description="Delivery expectation classification"
    )
    expected_deliveries: list[ExpectedDelivery] = Field(
        default_factory=list, description="Expected delivery records matching this location/window"
    )
    correlated_events: list[NormalizedEvent] = Field(
        default_factory=list,
        description="Correlated motion/doorbell events within the correlation window",
    )
    context_assembled_at: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 timestamp of context assembly",
    )


class CaseBrief(BaseModel):
    """Structured, bounded AI brief summarizing known facts, unknowns, and context match."""

    model_config = ConfigDict(frozen=True)

    brief_id: str = Field(..., min_length=1, description="Unique brief identifier")
    case_id: str = Field(..., min_length=1, description="Target case identifier")
    summary: str = Field(..., min_length=1, description="Concise factual operational summary")
    facts: list[str] = Field(
        default_factory=list, description="Traceable factual claims from context"
    )
    unknowns: list[str] = Field(default_factory=list, description="Explicit operational unknowns")
    context_match: str = Field(..., min_length=1, description="Classification of context alignment")
    is_fallback: bool = Field(
        default=False,
        description="True if generated by deterministic template because AI was unavailable or invalid",
    )
    generated_at: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 generation timestamp",
    )


class NotifyOperatorParameters(BaseModel):
    """Validated parameters for NOTIFY_OPERATOR proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(..., min_length=1, max_length=500, description="Notification message")
    urgency: str = Field(
        default="normal",
        pattern="^(low|normal|high|urgent)$",
        description="Operational urgency level",
    )
    recipient_role: Role = Field(default=Role.OPERATOR, description="Target recipient role")


class MarkForReviewParameters(BaseModel):
    """Validated parameters for MARK_FOR_REVIEW proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_reason: str = Field(
        ..., min_length=1, max_length=500, description="Rationale for manual review"
    )
    priority: str = Field(
        default="medium",
        pattern="^(low|medium|high)$",
        description="Review queue priority",
    )


class RequestConfirmationParameters(BaseModel):
    """Validated parameters for REQUEST_OPERATOR_CONFIRMATION proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmation_type: str = Field(
        ..., min_length=1, max_length=200, description="Specific item or detail to confirm"
    )
    target_role: Role = Field(default=Role.OPERATOR, description="Role requested to confirm")


class RecordNoActionParameters(BaseModel):
    """Validated parameters for RECORD_NO_ACTION proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rationale: str = Field(
        ..., min_length=1, max_length=500, description="Justification for taking no action"
    )


class AIProposedAction(BaseModel):
    """Proposed action emitted by bounded AI model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: ActionType = Field(..., description="Allowlisted action type")
    reason: str = Field(..., min_length=1, max_length=500, description="Factual justification")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action parameters")


class AIBriefOutput(BaseModel):
    """Strict structured schema required from AI model generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(..., min_length=1, max_length=1000, description="Factual brief summary")
    facts: list[str] = Field(..., min_length=1, description="Traceable factual claims from context")
    unknowns: list[str] = Field(..., min_length=1, description="Explicit operational unknowns")
    context_match: str = Field(
        ..., min_length=1, max_length=200, description="Context match assessment"
    )
    proposals: list[AIProposedAction] = Field(
        ..., min_length=1, description="Allowlisted proposals"
    )


class AIBriefInput(BaseModel):
    """Sanitized, bounded input contract provided to AI brief generator."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(..., min_length=1)
    organization_id: str = Field(..., min_length=1)
    location: dict[str, Any] = Field(default_factory=dict)
    device: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    business_context: dict[str, Any] = Field(default_factory=dict)
    expected_delivery: dict[str, Any] = Field(default_factory=dict)
    known_facts: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    allowed_actions: list[ActionType] = Field(default_factory=list)
    prompt_version: str = Field(default="2026-10-v1")


class Proposal(BaseModel):
    """Allowlisted operational action proposal generated for human operator review."""

    model_config = ConfigDict(frozen=True)

    proposal_id: str = Field(..., min_length=1, description="Unique proposal identifier")
    case_id: str = Field(..., min_length=1, description="Target case identifier")
    action_type: ActionType = Field(..., description="Strict allowlisted action type")
    reason: str = Field(..., min_length=1, description="Justification for proposal")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    proposal_hash: str = Field(
        ..., min_length=1, description="SHA-256 hash of canonical proposal representation"
    )
    created_at: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 creation timestamp",
    )


class Approval(BaseModel):
    """Cryptographically and contextually bound human approval record."""

    model_config = ConfigDict(frozen=True)

    approval_id: str = Field(..., min_length=1, description="Unique approval identifier")
    case_id: str = Field(..., min_length=1, description="Target case identifier")
    case_version: int = Field(..., ge=1, description="Case version at time of approval")
    proposal_id: str = Field(..., min_length=1, description="Approved proposal identifier")
    proposal_hash: str = Field(
        ..., min_length=1, description="Proposal SHA-256 hash verified at approval time"
    )
    approver_user_id: str = Field(
        ..., min_length=1, description="Authenticated approver identifier"
    )
    approver_role: Role = Field(..., description="Role tier of approver (ADMIN or OPERATOR)")
    approved_at: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 approval timestamp",
    )
    expires_at: str = Field(..., description="ISO 8601 timestamp after which approval is invalid")


class Action(BaseModel):
    """Deterministic execution record for an approved operational action."""

    model_config = ConfigDict(frozen=True)

    action_id: str = Field(..., min_length=1, description="Unique action identifier")
    case_id: str = Field(..., min_length=1, description="Target case identifier")
    approval_id: str = Field(..., min_length=1, description="Bound approval identifier")
    action_type: ActionType = Field(..., description="Allowlisted action type executed")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Parameters executed")
    status: ActionStatus = Field(
        default=ActionStatus.PENDING, description="Action execution status"
    )
    executed_at: str | None = Field(default=None, description="ISO 8601 timestamp of execution")
    result_summary: str | None = Field(default=None, description="Execution outcome summary")
    error_message: str | None = Field(default=None, description="Failure details if applicable")
    idempotency_key: str = Field(
        ..., min_length=1, description="Unique key guaranteeing idempotent execution"
    )


class AuditEvent(BaseModel):
    """Tamper-evident audit timeline record with SHA-256 hash chaining."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., min_length=1, description="Unique audit event identifier")
    case_id: str = Field(..., min_length=1, description="Associated case identifier")
    actor_id: str = Field(..., min_length=1, description="Actor identifier")
    actor_type: str = Field(
        ..., min_length=1, description="Actor classification: HUMAN, SYSTEM, RING_WEBHOOK"
    )
    action: AuditEventType = Field(..., description="Audited operational transition or event")
    timestamp: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 event timestamp",
    )
    previous_hash: str = Field(
        ..., description="SHA-256 hash of preceding audit event in the chain"
    )
    current_hash: str = Field(
        ..., description="SHA-256 hash of this audit record including previous_hash"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Contextual audit metadata")


class EvidenceBundle(BaseModel):
    """Comprehensive, sealed operational evidence package stored for auditability."""

    model_config = ConfigDict(frozen=True)

    bundle_id: str = Field(..., min_length=1, description="Unique evidence bundle identifier")
    case_id: str = Field(..., min_length=1, description="Associated case identifier")
    created_at: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 package creation timestamp",
    )
    source_events: list[RingEvent] = Field(default_factory=list, description="Raw source events")
    normalized_events: list[NormalizedEvent] = Field(
        default_factory=list, description="Normalized events"
    )
    case_context: CaseContext = Field(..., description="Aggregated operational context")
    brief: CaseBrief = Field(..., description="Bounded brief")
    proposal: Proposal = Field(..., description="Action proposal")
    approval: Approval | None = Field(default=None, description="Human approval record if granted")
    action: Action | None = Field(
        default=None, description="Execution outcome if action was executed"
    )
    audit_timeline: list[AuditEvent] = Field(
        default_factory=list, description="Tamper-evident audit trail"
    )
    closure_decision: str | None = Field(default=None, description="Final case closure summary")
    bundle_hash: str = Field(
        ..., min_length=1, description="SHA-256 manifest hash of the evidence bundle"
    )
    s3_key: str | None = Field(default=None, description="S3 storage key if persisted")


class Policy(BaseModel):
    """Deterministic organization policy governing proposals, actions, and approvals."""

    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(..., min_length=1, description="Unique policy identifier")
    organization_id: str = Field(..., min_length=1, description="Target organization identifier")
    allowed_actions: list[ActionType] = Field(
        default_factory=lambda: [
            ActionType.NOTIFY_OPERATOR,
            ActionType.MARK_FOR_REVIEW,
            ActionType.REQUEST_OPERATOR_CONFIRMATION,
            ActionType.RECORD_NO_ACTION,
        ],
        description="Allowlisted action types permitted under this policy",
    )
    approval_timeout_seconds: int = Field(
        default=1800, ge=60, description="Window in seconds before approval request expires"
    )
    auto_resolve_no_action: bool = Field(
        default=False, description="Whether record_no_action can close case automatically"
    )
    require_admin_above_priority: bool = Field(
        default=False, description="Whether elevated priority actions require ADMIN role"
    )


class Case(BaseModel):
    """Core operational case representing an after-hours physical event workflow."""

    case_id: str = Field(..., min_length=1, description="Unique case identifier")
    organization_id: str = Field(..., min_length=1, description="Tenant organization identifier")
    location_id: str = Field(..., min_length=1, description="Facility location identifier")
    device_id: str = Field(
        ..., min_length=1, description="Associated designated Ring device identifier"
    )
    event_id: str = Field(..., min_length=1, description="Triggering Ring event identifier")
    title: str = Field(..., min_length=1, description="Operational case title")
    status: CaseStatus = Field(default=CaseStatus.RECEIVED, description="Current lifecycle state")
    version: int = Field(
        default=1,
        ge=1,
        description="Monotonically increasing version counter for optimistic locking",
    )
    summary: str | None = Field(default=None, description="Brief summary of physical activity")
    brief_id: str | None = Field(default=None, description="Linked brief identifier")
    active_proposal_id: str | None = Field(default=None, description="Linked proposal identifier")
    active_approval_id: str | None = Field(default=None, description="Linked approval identifier")
    created_at: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 case creation timestamp",
    )
    updated_at: str = Field(
        default_factory=_utc_now_iso,
        description="ISO 8601 last update timestamp",
    )
    closed_at: str | None = Field(default=None, description="ISO 8601 case closure timestamp")
    closure_reason: str | None = Field(
        default=None, description="Closure rationale or final decision"
    )
