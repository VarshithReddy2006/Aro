"""DynamoDB single-table implementation of ActionRepository with atomic execution locking."""

from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from packages.contracts.enums import ActionStatus, CaseStatus
from packages.contracts.models import Action

from ..errors import (
    AlreadyCompletedError,
    AlreadyExecutingError,
    ConflictError,
    NotFoundError,
    OrganizationAccessDeniedError,
    VersionMismatchError,
)
from .base import (
    clean_dynamodb_dict,
    format_action_sk,
    format_case_pk,
    format_case_sk,
    map_client_error,
)


class DynamoDBActionRepository:
    """Production DynamoDB adapter for operational actions and atomic execution locks."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def save_action(self, action: Action, organization_id: str) -> Action:
        pk = format_case_pk(action.case_id)
        sk = format_action_sk(action.action_id)

        item = clean_dynamodb_dict(action.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "organization_id": organization_id,
                "entity_type": "ACTION",
            }
        )

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            return action
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConflictError(f"Action '{action.action_id}' already exists.") from e
            raise map_client_error(e, "Action", action.action_id) from e

    def get_action(self, case_id: str, action_id: str, organization_id: str) -> Action:
        pk = format_case_pk(case_id)
        sk = format_action_sk(action_id)

        try:
            resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        except ClientError as e:
            raise map_client_error(e, "Action", action_id) from e

        item = resp.get("Item")
        if not item:
            raise NotFoundError("Action", action_id)

        if item.get("organization_id") != organization_id:
            raise OrganizationAccessDeniedError(
                target_resource=f"Action/{action_id}",
                expected_org_id=organization_id,
                actual_org_id=str(item.get("organization_id")),
            )

        data = {
            k: v for k, v in item.items() if k not in {"PK", "SK", "organization_id", "entity_type"}
        }
        return Action.model_validate(data)

    def acquire_execution_lock(
        self, case_id: str, action_id: str, organization_id: str, expected_case_version: int
    ) -> None:
        """Atomically transition Case from APPROVED to EXECUTING with an execution lock.

        Guarantees:
        - Only one caller can acquire the lock.
        - Fails if case is not APPROVED.
        - Fails if execution_lock attribute already exists.
        - Fails on concurrent race conditions or stale version.
        """
        pk = format_case_pk(case_id)
        sk = format_case_sk()
        now_iso = datetime.now(UTC).isoformat()
        new_version = expected_case_version + 1

        update_expr = (
            "SET #st = :executing_status, execution_lock = :action_id, "
            "executing_at = :now, #v = :new_version"
        )
        cond_expr = (
            "organization_id = :org_id AND #st = :approved_status AND "
            "attribute_not_exists(execution_lock) AND #v = :expected_version"
        )

        expr_names = {
            "#st": "status",
            "#v": "version",
        }
        expr_values = {
            ":approved_status": CaseStatus.APPROVED.value,
            ":executing_status": CaseStatus.EXECUTING.value,
            ":action_id": action_id,
            ":now": now_iso,
            ":expected_version": expected_case_version,
            ":new_version": new_version,
            ":org_id": organization_id,
        }

        try:
            self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression=update_expr,
                ConditionExpression=cond_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                # Inspect existing item to provide precise typed failure
                current_item = self._table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
                if not current_item:
                    raise NotFoundError("Case", case_id) from e

                actual_org = current_item.get("organization_id")
                if actual_org != organization_id:
                    raise OrganizationAccessDeniedError(
                        target_resource=f"Case/{case_id}",
                        expected_org_id=organization_id,
                        actual_org_id=str(actual_org),
                    ) from e

                current_status = current_item.get("status")
                if (
                    current_item.get("execution_lock")
                    or current_status == CaseStatus.EXECUTING.value
                ):
                    raise AlreadyExecutingError(action_id) from e

                if current_status in {CaseStatus.COMPLETED.value, CaseStatus.CLOSED.value}:
                    raise AlreadyCompletedError(action_id) from e

                current_ver = int(current_item.get("version", 0))
                if current_ver != expected_case_version:
                    raise VersionMismatchError(
                        case_id=case_id,
                        expected_version=expected_case_version,
                        actual_version=current_ver,
                    ) from e

                raise ConflictError(
                    f"Cannot acquire execution lock on case '{case_id}' in state '{current_status}'."
                ) from e
            raise map_client_error(e, "ActionLock", action_id) from e

    def complete_action(
        self, case_id: str, action_id: str, organization_id: str, result_summary: str
    ) -> Action:
        pk = format_case_pk(case_id)
        sk = format_action_sk(action_id)
        now_iso = datetime.now(UTC).isoformat()

        update_expr = "SET #st = :status, result_summary = :summary, executed_at = :now"
        cond_expr = "attribute_exists(PK) AND organization_id = :org_id"

        try:
            resp = self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression=update_expr,
                ConditionExpression=cond_expr,
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":status": ActionStatus.SUCCEEDED.value,
                    ":summary": result_summary,
                    ":now": now_iso,
                    ":org_id": organization_id,
                },
                ReturnValues="ALL_NEW",
            )
            item = resp.get("Attributes", {})
            data = {
                k: v
                for k, v in item.items()
                if k not in {"PK", "SK", "organization_id", "entity_type"}
            }
            return Action.model_validate(data)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise NotFoundError("Action", action_id) from e
            raise map_client_error(e, "Action", action_id) from e
