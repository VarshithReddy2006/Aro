"""DynamoDB single-table implementation of IdempotencyRepository."""

import time
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from ..errors import (
    NotFoundError,
)
from .base import (
    format_idemp_pk,
    map_client_error,
)


class DynamoDBIdempotencyRepository:
    """Production DynamoDB adapter for distributed idempotency locking and replay caching."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def acquire_lock(self, key: str, operation: str, ttl_seconds: int = 86400) -> bool:
        pk = format_idemp_pk(key)
        sk = "RECORD"
        now_epoch = int(time.time())
        expires_at = now_epoch + ttl_seconds

        item = {
            "PK": pk,
            "SK": sk,
            "idempotency_key": key,
            "operation": operation,
            "status": "IN_PROGRESS",
            "created_at": datetime.now(UTC).isoformat(),
            "created_at_epoch": now_epoch,
            "expires_at_epoch": expires_at,
            "entity_type": "IDEMPOTENCY_RECORD",
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
            raise map_client_error(e, "IdempotencyLock", key) from e

    def get_record(self, key: str) -> dict[str, Any] | None:
        pk = format_idemp_pk(key)
        sk = "RECORD"

        try:
            resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        except ClientError as e:
            raise map_client_error(e, "IdempotencyRecord", key) from e

        item = resp.get("Item")
        if not item:
            return None

        return {k: v for k, v in item.items() if k not in {"PK", "SK", "entity_type"}}

    def complete_operation(self, key: str, result: dict[str, Any]) -> None:
        pk = format_idemp_pk(key)
        sk = "RECORD"

        try:
            self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET #st = :status, #res = :result",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeNames={"#st": "status", "#res": "result"},
                ExpressionAttributeValues={
                    ":status": "COMPLETED",
                    ":result": result,
                },
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise NotFoundError("IdempotencyRecord", key) from e
            raise map_client_error(e, "IdempotencyRecord", key) from e
