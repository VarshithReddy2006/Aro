"""Base utilities and error mapping for DynamoDB single-table repositories."""

import os
from typing import Any

from botocore.exceptions import ClientError

from ..errors import (
    ConditionalWriteFailedError,
    ConflictError,
    NotFoundError,
    PersistenceError,
)

DEFAULT_TABLE_NAME = "aro-core-table"


def get_table_name() -> str:
    """Resolve active DynamoDB table name from environment configuration."""
    return os.environ.get("ARO_TABLE_NAME", DEFAULT_TABLE_NAME)


def map_client_error(error: ClientError, resource_type: str, identifier: str) -> PersistenceError:
    """Map raw botocore ClientError into strongly typed application domain errors."""
    code = error.response.get("Error", {}).get("Code", "Unknown")
    msg = error.response.get("Error", {}).get("Message", str(error))

    if code == "ConditionalCheckFailedException":
        return ConditionalWriteFailedError(
            f"Conditional write check failed for {resource_type} '{identifier}': {msg}"
        )
    if code == "ResourceNotFoundException":
        return NotFoundError(resource_type, identifier)
    if code in {"TransactionConflictException", "TransactionCanceledException"}:
        return ConflictError(f"Transaction conflict for {resource_type} '{identifier}': {msg}")

    return PersistenceError(f"DynamoDB error ({code}) on {resource_type} '{identifier}': {msg}")


def format_case_pk(case_id: str) -> str:
    return f"CASE#{case_id}"


def format_case_sk() -> str:
    return "CASE"


def format_org_pk(org_id: str) -> str:
    return f"ORG#{org_id}"


def format_gsi1_case_sk(updated_at: str) -> str:
    return f"CASE#{updated_at}"


def format_gsi2_status_pk(org_id: str, status: str) -> str:
    return f"ORG#{org_id}#STATUS#{status}"


def format_gsi2_status_sk(updated_at: str, case_id: str) -> str:
    return f"{updated_at}#{case_id}"


def format_audit_sk(timestamp: str, event_id: str) -> str:
    return f"AUDIT#{timestamp}#{event_id}"


def format_approval_sk(approval_id: str) -> str:
    return f"APPROVAL#{approval_id}"


def format_action_sk(action_id: str) -> str:
    return f"ACTION#{action_id}"


def format_event_sk(event_id: str) -> str:
    return f"EVENT#{event_id}"


def format_norm_event_sk(norm_id: str) -> str:
    return f"NORM_EVENT#{norm_id}"


def format_idemp_pk(key: str) -> str:
    return f"IDEMP#{key}"


def format_dedup_ring_pk(request_id: str) -> str:
    return f"DEDUP#RING#{request_id}"


def format_loc_pk(location_id: str) -> str:
    return f"LOC#{location_id}"


def format_delivery_sk(window_start: str, delivery_id: str) -> str:
    return f"DELIVERY#{window_start}#{delivery_id}"


def format_gsi1_tracking_sk(tracking_number: str) -> str:
    return f"TRACKING#{tracking_number}"


def clean_dynamodb_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively clean dict to ensure DynamoDB compatibility (removes empty strings/nones where necessary)."""
    cleaned: dict[str, Any] = {}
    for k, v in data.items():
        if v is not None:
            if isinstance(v, dict):
                cleaned[k] = clean_dynamodb_dict(v)
            else:
                cleaned[k] = v
    return cleaned
