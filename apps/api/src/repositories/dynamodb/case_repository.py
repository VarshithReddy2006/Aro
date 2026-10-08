"""DynamoDB single-table implementation of CaseRepository."""

from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from packages.contracts.enums import CaseStatus
from packages.contracts.models import Case

from ..errors import (
    ConflictError,
    NotFoundError,
    OrganizationAccessDeniedError,
    VersionMismatchError,
)
from .base import (
    clean_dynamodb_dict,
    format_case_pk,
    format_case_sk,
    format_gsi1_case_sk,
    format_gsi2_status_pk,
    format_gsi2_status_sk,
    format_org_pk,
    map_client_error,
)


class DynamoDBCaseRepository:
    """Production DynamoDB adapter for Case entities with optimistic locking and tenant isolation."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def create_case(self, case: Case) -> Case:
        pk = format_case_pk(case.case_id)
        sk = format_case_sk()
        now_iso = datetime.now(UTC).isoformat()

        item = clean_dynamodb_dict(case.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "GSI1PK": format_org_pk(case.organization_id),
                "GSI1SK": format_gsi1_case_sk(case.updated_at or now_iso),
                "GSI2PK": format_gsi2_status_pk(case.organization_id, case.status.value),
                "GSI2SK": format_gsi2_status_sk(case.updated_at or now_iso, case.case_id),
                "entity_type": "CASE",
            }
        )

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
            )
            return case
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConflictError(f"Case with ID '{case.case_id}' already exists.") from e
            raise map_client_error(e, "Case", case.case_id) from e

    def get_case(self, case_id: str, organization_id: str) -> Case:
        pk = format_case_pk(case_id)
        sk = format_case_sk()

        try:
            resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        except ClientError as e:
            raise map_client_error(e, "Case", case_id) from e

        item = resp.get("Item")
        if not item:
            raise NotFoundError("Case", case_id)

        if item.get("organization_id") != organization_id:
            raise OrganizationAccessDeniedError(
                target_resource=f"Case/{case_id}",
                expected_org_id=organization_id,
                actual_org_id=str(item.get("organization_id")),
            )

        # Remove DynamoDB internal partition attributes before schema parsing
        data = {
            k: v
            for k, v in item.items()
            if k not in {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "entity_type"}
        }
        return Case.model_validate(data)

    def update_case(self, case: Case, organization_id: str, expected_version: int) -> Case:
        pk = format_case_pk(case.case_id)
        sk = format_case_sk()
        now_iso = datetime.now(UTC).isoformat()
        new_version = expected_version + 1

        update_expr = (
            "SET #st = :status, #v = :new_version, updated_at = :updated_at, "
            "title = :title, summary = :summary, brief_id = :brief_id, "
            "active_proposal_id = :prop_id, active_approval_id = :appr_id, "
            "closed_at = :closed_at, closure_reason = :closure_reason, "
            "GSI1SK = :gsi1sk, GSI2PK = :gsi2pk, GSI2SK = :gsi2sk"
        )

        expr_names = {
            "#st": "status",
            "#v": "version",
        }

        expr_values = {
            ":status": case.status.value,
            ":new_version": new_version,
            ":updated_at": now_iso,
            ":title": case.title,
            ":summary": case.summary,
            ":brief_id": case.brief_id,
            ":prop_id": case.active_proposal_id,
            ":appr_id": case.active_approval_id,
            ":closed_at": case.closed_at,
            ":closure_reason": case.closure_reason,
            ":gsi1sk": format_gsi1_case_sk(now_iso),
            ":gsi2pk": format_gsi2_status_pk(organization_id, case.status.value),
            ":gsi2sk": format_gsi2_status_sk(now_iso, case.case_id),
            ":expected_version": expected_version,
            ":org_id": organization_id,
        }

        # Filter out None values in ExpressionAttributeValues
        expr_values = {k: v for k, v in expr_values.items() if v is not None}
        # If any values were None, adjust update_expr
        for field, key in [
            ("summary", ":summary"),
            ("brief_id", ":brief_id"),
            ("active_proposal_id", ":prop_id"),
            ("active_approval_id", ":appr_id"),
            ("closed_at", ":closed_at"),
            ("closure_reason", ":closure_reason"),
        ]:
            if key not in expr_values:
                update_expr = update_expr.replace(f"{field} = {key}, ", "")
                update_expr = update_expr.replace(f", {field} = {key}", "")

        cond_expr = "attribute_exists(PK) AND organization_id = :org_id AND #v = :expected_version"

        try:
            self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression=update_expr,
                ConditionExpression=cond_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
            return case.model_copy(
                update={
                    "version": new_version,
                    "updated_at": now_iso,
                }
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                # Determine precise conflict reason
                existing = self._table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
                if not existing:
                    raise NotFoundError("Case", case.case_id) from e
                if existing.get("organization_id") != organization_id:
                    raise OrganizationAccessDeniedError(
                        target_resource=f"Case/{case.case_id}",
                        expected_org_id=organization_id,
                        actual_org_id=str(existing.get("organization_id")),
                    ) from e
                raise VersionMismatchError(
                    case_id=case.case_id,
                    expected_version=expected_version,
                    actual_version=int(existing.get("version", 0)),
                ) from e
            raise map_client_error(e, "Case", case.case_id) from e

    def list_cases(
        self,
        organization_id: str,
        status: CaseStatus | None = None,
        location_id: str | None = None,
        limit: int = 50,
    ) -> list[Case]:
        kwargs: dict[str, Any] = {
            "ScanIndexForward": False,
            "Limit": limit,
        }

        if status is not None:
            kwargs["IndexName"] = "GSI2"
            kwargs["KeyConditionExpression"] = Key("GSI2PK").eq(
                format_gsi2_status_pk(organization_id, status.value)
            )
        else:
            kwargs["IndexName"] = "GSI1"
            kwargs["KeyConditionExpression"] = Key("GSI1PK").eq(
                format_org_pk(organization_id)
            ) & Key("GSI1SK").begins_with("CASE#")

        if location_id is not None:
            kwargs["FilterExpression"] = Key("location_id").eq(location_id)

        try:
            resp = self._table.query(**kwargs)
        except ClientError as e:
            raise map_client_error(e, "CaseList", organization_id) from e

        cases: list[Case] = []
        for item in resp.get("Items", []):
            data = {
                k: v
                for k, v in item.items()
                if k not in {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "entity_type"}
            }
            cases.append(Case.model_validate(data))
        return cases
