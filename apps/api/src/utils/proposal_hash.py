"""Deterministic canonical SHA-256 hashing for operational proposals.

Guarantees tamper-evident binding between an allowlisted proposal,
its structured parameters, and future human approval records:
- Normalizes dictionary keys recursively in strict alphabetical order.
- Generates compact, canonical JSON bytes without extraneous whitespace.
- Computes cryptographic SHA-256 digest.
"""

import hashlib
import json
from typing import Any

from packages.contracts.enums import ActionType


def canonicalize_obj(obj: Any) -> Any:
    """Recursively convert objects to deterministic dictionary/list representations."""
    if isinstance(obj, dict):
        return {k: canonicalize_obj(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [canonicalize_obj(item) for item in obj]
    if isinstance(obj, ActionType):
        return obj.value
    return obj


def calculate_proposal_hash(
    case_id: str,
    action_type: ActionType,
    reason: str,
    parameters: dict[str, Any],
) -> str:
    """Calculate canonical SHA-256 hash of a proposal.

    Args:
        case_id: Bound operational case identifier.
        action_type: Strictly allowlisted ActionType.
        reason: Factual operational justification.
        parameters: Validated parameter dictionary.

    Returns:
        Hexadecimal SHA-256 hash string.
    """
    canonical_payload = {
        "action_type": action_type.value,
        "case_id": case_id,
        "parameters": canonicalize_obj(parameters),
        "reason": reason.strip(),
    }

    # Compact JSON encoding with sorted keys
    canonical_bytes = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")

    return hashlib.sha256(canonical_bytes).hexdigest()
