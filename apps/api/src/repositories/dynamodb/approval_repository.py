"""DynamoDB single-table implementation of ApprovalRepository."""

from typing import Any

from botocore.exceptions import ClientError

from packages.contracts.models import Approval

from ..errors import (
    ConflictError,
    NotFoundError,
    OrganizationAccessDeniedError,
)
from .base import (
    clean_dynamodb_dict,
    format_approval_sk,
    format_case_pk,
    map_client_error,
)


class DynamoDBApprovalRepository:
    """Production DynamoDB adapter for human approvals."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def save_approval(self, approval: Approval, organization_id: str) -> Approval:
        pk = format_case_pk(approval.case_id)
        sk = format_approval_sk(approval.approval_id)

        item = clean_dynamodb_dict(approval.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "organization_id": organization_id,
                "entity_type": "APPROVAL",
            }
        )

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            return approval
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConflictError(f"Approval '{approval.approval_id}' already exists.") from e
            raise map_client_error(e, "Approval", approval.approval_id) from e

    def get_approval(self, case_id: str, approval_id: str, organization_id: str) -> Approval:
        pk = format_case_pk(case_id)
        sk = format_approval_sk(approval_id)

        try:
            resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        except ClientError as e:
            raise map_client_error(e, "Approval", approval_id) from e

        item = resp.get("Item")
        if not item:
            raise NotFoundError("Approval", approval_id)

        if item.get("organization_id") != organization_id:
            raise OrganizationAccessDeniedError(
                target_resource=f"Approval/{approval_id}",
                expected_org_id=organization_id,
                actual_org_id=str(item.get("organization_id")),
            )

        data = {
            k: v for k, v in item.items() if k not in {"PK", "SK", "organization_id", "entity_type"}
        }
        return Approval.model_validate(data)

    def list_approvals_for_case(self, case_id: str, organization_id: str) -> list[Approval]:
        pk = format_case_pk(case_id)
        from boto3.dynamodb.conditions import Key

        try:
            resp = self._table.query(
                KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("APPROVAL#")
            )
        except ClientError as e:
            raise map_client_error(e, "Approval", case_id) from e

        results: list[Approval] = []
        for item in resp.get("Items", []):
            if item.get("organization_id") == organization_id:
                data = {
                    k: v
                    for k, v in item.items()
                    if k not in {"PK", "SK", "organization_id", "entity_type"}
                }
                results.append(Approval.model_validate(data))
        return results
