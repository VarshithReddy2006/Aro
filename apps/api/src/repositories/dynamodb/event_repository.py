"""DynamoDB single-table implementation of EventRepository."""

import time
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from packages.contracts.models import NormalizedEvent, RingEvent

from .base import (
    clean_dynamodb_dict,
    format_case_pk,
    format_dedup_ring_pk,
    format_event_sk,
    format_norm_event_sk,
    map_client_error,
)


class DynamoDBEventRepository:
    """Production DynamoDB adapter for raw and normalized Ring events."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def save_ring_event(self, event: RingEvent, case_id: str | None = None) -> RingEvent:
        pk = format_case_pk(case_id or event.event_id)
        sk = format_event_sk(event.event_id)

        item = clean_dynamodb_dict(event.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "GSI1PK": f"DEVICE#{event.device_id}",
                "GSI1SK": event.occurred_at,
                "entity_type": "RING_EVENT",
            }
        )

        try:
            self._table.put_item(Item=item)
            return event
        except ClientError as e:
            raise map_client_error(e, "RingEvent", event.event_id) from e

    def get_ring_event(self, event_id: str) -> RingEvent | None:
        # Check standard partition with event_id as case_id fallback
        pk = format_case_pk(event_id)
        sk = format_event_sk(event_id)

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
