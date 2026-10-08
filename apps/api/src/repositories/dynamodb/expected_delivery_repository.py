"""DynamoDB single-table implementation of ExpectedDeliveryRepository."""

from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from packages.contracts.models import ExpectedDelivery

from .base import (
    clean_dynamodb_dict,
    format_delivery_sk,
    format_gsi1_tracking_sk,
    format_loc_pk,
    format_org_pk,
    map_client_error,
)


class DynamoDBExpectedDeliveryRepository:
    """Production DynamoDB adapter for anticipated delivery context."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def save_expected_delivery(self, delivery: ExpectedDelivery) -> ExpectedDelivery:
        pk = format_loc_pk(delivery.location_id)
        sk = format_delivery_sk(delivery.expected_window_start or "0000", delivery.delivery_id)

        item = clean_dynamodb_dict(delivery.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "entity_type": "EXPECTED_DELIVERY",
            }
        )

        if delivery.tracking_number:
            item["GSI1PK"] = format_org_pk(delivery.organization_id)
            item["GSI1SK"] = format_gsi1_tracking_sk(delivery.tracking_number)

        try:
            self._table.put_item(Item=item)
            return delivery
        except ClientError as e:
            raise map_client_error(e, "ExpectedDelivery", delivery.delivery_id) from e

    def find_deliveries_for_window(
        self,
        location_id: str,
        organization_id: str,
        window_start: str,
        window_end: str,
    ) -> list[ExpectedDelivery]:
        pk = format_loc_pk(location_id)

        try:
            resp = self._table.query(
                KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("DELIVERY#"),
            )
        except ClientError as e:
            raise map_client_error(e, "ExpectedDeliveryList", location_id) from e

        matches: list[ExpectedDelivery] = []
        for item in resp.get("Items", []):
            if item.get("organization_id") != organization_id:
                continue

            data = {
                k: v
                for k, v in item.items()
                if k not in {"PK", "SK", "GSI1PK", "GSI1SK", "entity_type"}
            }
            delivery = ExpectedDelivery.model_validate(data)

            # Window overlap
            if delivery.expected_window_start and delivery.expected_window_end:
                if (
                    delivery.expected_window_start <= window_end
                    and delivery.expected_window_end >= window_start
                ):
                    matches.append(delivery)
            else:
                matches.append(delivery)

        return matches

    def get_by_tracking(
        self, organization_id: str, tracking_number: str
    ) -> ExpectedDelivery | None:
        try:
            resp = self._table.query(
                IndexName="GSI1",
                KeyConditionExpression=Key("GSI1PK").eq(format_org_pk(organization_id))
                & Key("GSI1SK").eq(format_gsi1_tracking_sk(tracking_number)),
            )
        except ClientError as e:
            raise map_client_error(e, "ExpectedDeliveryTracking", tracking_number) from e

        items = resp.get("Items", [])
        if not items:
            return None

        data = {
            k: v
            for k, v in items[0].items()
            if k not in {"PK", "SK", "GSI1PK", "GSI1SK", "entity_type"}
        }
        return ExpectedDelivery.model_validate(data)
