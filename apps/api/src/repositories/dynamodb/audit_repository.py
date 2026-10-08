"""DynamoDB single-table implementation of AuditRepository with immutable append semantics."""

from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from packages.contracts.models import AuditEvent

from ..errors import (
    ConflictError,
    OrganizationAccessDeniedError,
)
from .base import (
    clean_dynamodb_dict,
    format_audit_sk,
    format_case_pk,
    map_client_error,
)


class DynamoDBAuditRepository:
    """Production DynamoDB adapter for append-only tamper-evident audit timeline records."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def append_audit_event(self, event: AuditEvent, organization_id: str) -> AuditEvent:
        pk = format_case_pk(event.case_id)
        sk = format_audit_sk(event.timestamp, event.event_id)

        item = clean_dynamodb_dict(event.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "organization_id": organization_id,
                "entity_type": "AUDIT_EVENT",
            }
        )

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            return event
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConflictError(
                    f"Audit record immutability violation: Audit event '{event.event_id}' "
                    f"for case '{event.case_id}' already exists and cannot be modified."
                ) from e
            raise map_client_error(e, "AuditEvent", event.event_id) from e

    def get_case_timeline(self, case_id: str, organization_id: str) -> list[AuditEvent]:
        pk = format_case_pk(case_id)

        try:
            resp = self._table.query(
                KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("AUDIT#"),
                ScanIndexForward=True,  # Chronological order
            )
        except ClientError as e:
            raise map_client_error(e, "AuditTimeline", case_id) from e

        events: list[AuditEvent] = []
        for item in resp.get("Items", []):
            if item.get("organization_id") and item.get("organization_id") != organization_id:
                raise OrganizationAccessDeniedError(
                    target_resource=f"Audit/Case/{case_id}",
                    expected_org_id=organization_id,
                    actual_org_id=str(item.get("organization_id")),
                )
            data = {
                k: v
                for k, v in item.items()
                if k not in {"PK", "SK", "organization_id", "entity_type"}
            }
            events.append(AuditEvent.model_validate(data))
        return events

    def get_latest_audit_event(self, case_id: str, organization_id: str) -> AuditEvent | None:
        pk = format_case_pk(case_id)

        try:
            resp = self._table.query(
                KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("AUDIT#"),
                ScanIndexForward=False,  # Latest first
                Limit=1,
            )
        except ClientError as e:
            raise map_client_error(e, "AuditLatest", case_id) from e

        items = resp.get("Items", [])
        if not items:
            return None

        item = items[0]
        if item.get("organization_id") and item.get("organization_id") != organization_id:
            raise OrganizationAccessDeniedError(
                target_resource=f"Audit/Case/{case_id}",
                expected_org_id=organization_id,
                actual_org_id=str(item.get("organization_id")),
            )

        data = {
            k: v for k, v in item.items() if k not in {"PK", "SK", "organization_id", "entity_type"}
        }
        return AuditEvent.model_validate(data)
