"""DynamoDB single-table implementation of EventRepository supporting pre-case storage and correlation."""

import time
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from packages.contracts.enums import EventProcessingStatus
from packages.contracts.models import NormalizedEvent, RingEvent

from ..errors import (
    ConflictError,
    NotFoundError,
)
from .base import (
    clean_dynamodb_dict,
    format_case_pk,
    format_dedup_ring_pk,
    format_event_pk,
    format_norm_event_sk,
    format_raw_event_sk,
    map_client_error,
)


class DynamoDBEventRepository:
    """Production DynamoDB adapter for raw and normalized Ring events."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def save_ring_event(self, event: RingEvent) -> RingEvent:
        """Persist an authenticated raw Ring event prior to case correlation."""
        pk = format_event_pk(event.event_id)
        sk = format_raw_event_sk()

        item = clean_dynamodb_dict(event.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "GSI1PK": f"CASE#{event.case_id}" if event.case_id else f"DEVICE#{event.device_id}",
                "GSI1SK": f"EVENT#{event.occurred_at}",
                "entity_type": "RING_EVENT_RAW",
            }
        )

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
            )
            return event
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConflictError(f"Raw event '{event.event_id}' already exists.") from e
            raise map_client_error(e, "RingEvent", event.event_id) from e

    def get_ring_event(self, event_id: str) -> RingEvent | None:
        """Retrieve a raw Ring event by event ID."""
        pk = format_event_pk(event_id)
        sk = format_raw_event_sk()

        try:
            resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        except ClientError as e:
            raise map_client_error(e, "RingEvent", event_id) from e

        item = resp.get("Item")
        if not item:
            return None

        data = {
            k: v
            for k, v in item.items()
            if k not in {"PK", "SK", "GSI1PK", "GSI1SK", "entity_type"}
        }
        return RingEvent.model_validate(data)

    def quarantine_event(self, event_id: str, reason: str) -> RingEvent:
        """Mark an authenticated but malformed Ring event as quarantined with rationale."""
        pk = format_event_pk(event_id)
        sk = format_raw_event_sk()

        try:
            resp = self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET processing_status = :status, quarantine_reason = :reason",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={
                    ":status": EventProcessingStatus.QUARANTINED.value,
                    ":reason": reason,
                },
                ReturnValues="ALL_NEW",
            )
            item = resp.get("Attributes", {})
            data = {
                k: v
                for k, v in item.items()
                if k not in {"PK", "SK", "GSI1PK", "GSI1SK", "entity_type"}
            }
            return RingEvent.model_validate(data)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise NotFoundError("RingEvent", event_id) from e
            raise map_client_error(e, "RingEvent", event_id) from e

    def correlate_event_to_case(self, event_id: str, case_id: str) -> RingEvent:
        """Associate a previously ingested raw Ring event with an operational case."""
        pk = format_event_pk(event_id)
        sk = format_raw_event_sk()

        try:
            resp = self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET case_id = :case_id, processing_status = :status, GSI1PK = :gsi1pk",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={
                    ":case_id": case_id,
                    ":status": EventProcessingStatus.CORRELATED.value,
                    ":gsi1pk": f"CASE#{case_id}",
                },
                ReturnValues="ALL_NEW",
            )
            item = resp.get("Attributes", {})
            data = {
                k: v
                for k, v in item.items()
                if k not in {"PK", "SK", "GSI1PK", "GSI1SK", "entity_type"}
            }
            return RingEvent.model_validate(data)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise NotFoundError("RingEvent", event_id) from e
            raise map_client_error(e, "RingEvent", event_id) from e

    def record_webhook_dedup(
        self, request_id: str, event_id: str, ttl_seconds: int = 86400
    ) -> bool:
        pk = format_dedup_ring_pk(request_id)
        sk = "RECORD"
        now_epoch = int(time.time())
        expires_at = now_epoch + ttl_seconds

        item = {
            "PK": pk,
            "SK": sk,
            "request_id": request_id,
            "event_id": event_id,
            "created_at_epoch": now_epoch,
            "expires_at_epoch": expires_at,
            "entity_type": "WEBHOOK_DEDUP",
        }

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
            )
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise map_client_error(e, "WebhookDedup", request_id) from e

    def save_normalized_event(self, event: NormalizedEvent, case_id: str) -> NormalizedEvent:
        pk = format_case_pk(case_id)
        sk = format_norm_event_sk(event.normalized_event_id)

        item = clean_dynamodb_dict(event.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "case_id": case_id,
                "entity_type": "NORM_EVENT",
            }
        )

        try:
            self._table.put_item(Item=item)
            return event
        except ClientError as e:
            raise map_client_error(e, "NormalizedEvent", event.normalized_event_id) from e

    def get_case_events(self, case_id: str) -> list[NormalizedEvent]:
        pk = format_case_pk(case_id)

        try:
            resp = self._table.query(
                KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("NORM_EVENT#"),
            )
        except ClientError as e:
            raise map_client_error(e, "NormalizedEventsList", case_id) from e

        events: list[NormalizedEvent] = []
        for item in resp.get("Items", []):
            data = {
                k: v for k, v in item.items() if k not in {"PK", "SK", "case_id", "entity_type"}
            }
            events.append(NormalizedEvent.model_validate(data))
        return events
