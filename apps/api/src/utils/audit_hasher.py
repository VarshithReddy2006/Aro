"""Deterministic tamper-evident audit timeline hash chaining.

Provides cryptographic verification for immutable operational audit timelines:
- SHA-256 hash chaining linking each event to its preceding event.
- Canonical JSON serialization of payload fields.
- Genesis hash constant for chain root.
- Chain integrity verification utility.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from packages.contracts.enums import AuditEventType
from packages.contracts.models import AuditEvent

from .proposal_hash import canonicalize_obj

GENESIS_HASH = "0" * 64


def calculate_audit_hash(
    event_id: str,
    case_id: str,
    actor_id: str,
    actor_type: str,
    action: AuditEventType | str,
    timestamp: str,
    previous_hash: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Calculate canonical SHA-256 hash of an audit event.

    Args:
        event_id: Unique event identifier.
        case_id: Target case identifier.
        actor_id: Actor identifier.
        actor_type: Classification (HUMAN, SYSTEM, RING_WEBHOOK).
        action: AuditEventType or action string.
        timestamp: ISO 8601 event timestamp.
        previous_hash: SHA-256 hash of previous event in chain.
        metadata: Contextual metadata dictionary.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    action_str = action.value if isinstance(action, AuditEventType) else str(action)
    payload = {
        "action": action_str,
        "actor_id": str(actor_id),
        "actor_type": str(actor_type),
        "case_id": str(case_id),
        "event_id": str(event_id),
        "metadata": canonicalize_obj(metadata or {}),
        "previous_hash": str(previous_hash),
        "timestamp": str(timestamp),
    }

    canonical_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")

    return hashlib.sha256(canonical_bytes).hexdigest()


def create_audit_event(
    case_id: str,
    actor_id: str,
    actor_type: str,
    action: AuditEventType,
    previous_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> AuditEvent:
    """Construct and cryptographically seal an AuditEvent.

    Args:
        case_id: Target case identifier.
        actor_id: Actor identifier.
        actor_type: HUMAN, SYSTEM, etc.
        action: AuditEventType.
        previous_hash: Previous event hash or None for genesis.
        metadata: Contextual metadata dictionary.
        event_id: Optional ID; auto-generated if omitted.
        timestamp: Optional ISO 8601 timestamp; now() if omitted.

    Returns:
        Sealed AuditEvent instance with current_hash set.
    """
    eid = event_id or f"aud_{uuid.uuid4().hex[:12]}"
    ts = timestamp or datetime.now(UTC).isoformat()
    prev_h = previous_hash or GENESIS_HASH
    meta = metadata or {}

    current_h = calculate_audit_hash(
        event_id=eid,
        case_id=case_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        timestamp=ts,
        previous_hash=prev_h,
        metadata=meta,
    )

    return AuditEvent(
        event_id=eid,
        case_id=case_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        timestamp=ts,
        previous_hash=prev_h,
        current_hash=current_h,
        metadata=meta,
    )


def verify_audit_event(event: AuditEvent) -> bool:
    """Verify that an AuditEvent's current_hash matches its recomputed digest."""
    recomputed = calculate_audit_hash(
        event_id=event.event_id,
        case_id=event.case_id,
        actor_id=event.actor_id,
        actor_type=event.actor_type,
        action=event.action,
        timestamp=event.timestamp,
        previous_hash=event.previous_hash,
        metadata=event.metadata,
    )
    return recomputed == event.current_hash


def verify_audit_chain(timeline: list[AuditEvent]) -> bool:
    """Verify complete chronological audit timeline integrity.

    Verifies:
    1. Every event's current_hash matches its canonical recomputation.
    2. The first event links to GENESIS_HASH.
    3. Each subsequent event links its previous_hash to preceding event's current_hash.

    Args:
        timeline: Chronological list of AuditEvent instances.

    Returns:
        True if the entire hash chain is valid and untampered, False otherwise.
    """
    if not timeline:
        return True

    for i, event in enumerate(timeline):
        if not verify_audit_event(event):
            return False

        if i == 0:
            if event.previous_hash != GENESIS_HASH:
                return False
        else:
            prev_event = timeline[i - 1]
            if event.previous_hash != prev_event.current_hash:
                return False

    return True
