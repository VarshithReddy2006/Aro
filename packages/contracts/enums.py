"""Canonical domain enums for Aro."""

from enum import StrEnum


class Provenance(StrEnum):
    """Origin and authenticity classification of an ingested event."""

    RING_SIGNED = "ring_signed"
    RING_HISTORY = "ring_history"
    DEMO_SYNTHETIC = "demo_synthetic"


class CaseStatus(StrEnum):
    """Lifecycle states of an Aro operational case."""

    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    CASE_CREATED = "CASE_CREATED"
    CONTEXT_READY = "CONTEXT_READY"
    PROPOSAL_READY = "PROPOSAL_READY"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    UNRESOLVED = "UNRESOLVED"


class Role(StrEnum):
    """Operator role-based authorization tiers."""

    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class ActionType(StrEnum):
    """Strict allowlist of consequential operations that can be proposed or approved."""

    NOTIFY_OPERATOR = "NOTIFY_OPERATOR"
    MARK_FOR_REVIEW = "MARK_FOR_REVIEW"
    REQUEST_OPERATOR_CONFIRMATION = "REQUEST_OPERATOR_CONFIRMATION"
    RECORD_NO_ACTION = "RECORD_NO_ACTION"


class ExpectedDeliveryStatus(StrEnum):
    """Status indicating whether a parcel or courier was anticipated at the time of the event."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class AuditEventType(StrEnum):
    """Structured audit event taxonomy."""

    WEBHOOK_RECEIVED = "WEBHOOK_RECEIVED"
    EVENT_VALIDATED = "EVENT_VALIDATED"
    CASE_CREATED = "CASE_CREATED"
    CONTEXT_ASSEMBLED = "CONTEXT_ASSEMBLED"
    BRIEF_GENERATED = "BRIEF_GENERATED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    APPROVAL_RECORDED = "APPROVAL_RECORDED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    CASE_CLOSED = "CASE_CLOSED"
    CASE_UNRESOLVED = "CASE_UNRESOLVED"


class ActionStatus(StrEnum):
    """Execution status of an approved operational action."""

    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
