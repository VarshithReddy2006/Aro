"""DynamoDB single-table implementation of PolicyRepository."""

from typing import Any

from botocore.exceptions import ClientError

from packages.contracts.models import Policy

from .base import (
    clean_dynamodb_dict,
    format_org_pk,
    map_client_error,
)


class DynamoDBPolicyRepository:
    """Production DynamoDB adapter for tenant operational policy."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def save_policy(self, policy: Policy) -> Policy:
        pk = format_org_pk(policy.organization_id)
        sk = "POLICY"

        item = clean_dynamodb_dict(policy.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "entity_type": "POLICY",
            }
        )

        try:
            self._table.put_item(Item=item)
            return policy
        except ClientError as e:
            raise map_client_error(e, "Policy", policy.policy_id) from e

    def get_policy(self, organization_id: str) -> Policy | None:
        pk = format_org_pk(organization_id)
        sk = "POLICY"

        try:
            resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        except ClientError as e:
            raise map_client_error(e, "Policy", organization_id) from e

        item = resp.get("Item")
        if not item:
            return None

        data = {k: v for k, v in item.items() if k not in {"PK", "SK", "entity_type"}}
        return Policy.model_validate(data)
