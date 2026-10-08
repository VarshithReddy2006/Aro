from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field

class Provenance(StrEnum):
    RING_SIGNED = "ring_signed"
    RING_HISTORY = "ring_history"
    DEMO_SYNTHETIC = "demo_synthetic"

class CaseStatus(StrEnum):
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

class RingEvent(BaseModel):
    event_id: str
    request_id: str
    device_id: str
    event_type: str
    occurred_at: str
    provenance: Provenance
    payload: dict[str, Any] = Field(default_factory=dict)

class Case(BaseModel):
    case_id: str
    status: CaseStatus
    event_id: str
    title: str
    summary: str | None = None
    version: int = 1
