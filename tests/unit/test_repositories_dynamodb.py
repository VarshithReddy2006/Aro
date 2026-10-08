"""Unit tests for production DynamoDB single-table adapters.

Validates DynamoDB item generation, key formatting, conditional writes,
optimistic concurrency translation, and botocore ClientError mapping
without requiring live AWS infrastructure.
"""

from typing import Any

import pytest
from botocore.exceptions import ClientError

from apps.api.src.repositories import (
    AlreadyExecutingError,
    ConflictError,
    NotFoundError,
    OrganizationAccessDeniedError,
    VersionMismatchError,
)
from apps.api.src.repositories.dynamodb import (
    DynamoDBActionRepository,
    DynamoDBAuditRepository,
    DynamoDBCaseRepository,
    DynamoDBEventRepository,
    DynamoDBIdempotencyRepository,
    DynamoDBPolicyRepository,
)
from apps.api.src.repositories.dynamodb.base import (
    map_client_error,
)
from packages.contracts.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseStatus,
    Provenance,
)
from packages.contracts.models import (
    Action,
    AuditEvent,
    Case,
    Policy,
    RingEvent,
)


class MockDynamoDBTable:
    """Mock DynamoDB table simulating single-table operations and conditional checks."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def put_item(
        self, Item: dict[str, Any], ConditionExpression: str | None = None
    ) -> dict[str, Any]:
        key = (Item["PK"], Item["SK"])
        if ConditionExpression == "attribute_not_exists(PK)" and any(
            k[0] == Item["PK"] for k in self.items
        ):
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Item exists"}},
                "PutItem",
            )
        elif (
            ConditionExpression == "attribute_not_exists(PK) AND attribute_not_exists(SK)"
            and key in self.items
        ):
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Key exists"}},
                "PutItem",
            )

        self.items[key] = dict(Item)
        return {}

    def get_item(self, Key: dict[str, Any]) -> dict[str, Any]:
        key = (Key["PK"], Key["SK"])
        item = self.items.get(key)
        return {"Item": dict(item)} if item else {}

    def update_item(
        self,
        Key: dict[str, Any],
        UpdateExpression: str,
        ConditionExpression: str | None = None,
        ExpressionAttributeNames: dict[str, str] | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
        ReturnValues: str = "NONE",
    ) -> dict[str, Any]:
        key = (Key["PK"], Key["SK"])
        item = self.items.get(key)
        values = ExpressionAttributeValues or {}

        if ConditionExpression:
            if "attribute_exists(PK)" in ConditionExpression and not item:
                raise ClientError(
                    {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Not found"}},
                    "UpdateItem",
                )
            if (
                ":org_id" in ConditionExpression
                and item
                and item.get("organization_id") != values.get(":org_id")
            ):
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ConditionalCheckFailedException",
                            "Message": "Org mismatch",
                        }
                    },
                    "UpdateItem",
                )
            if (
                ":expected_version" in ConditionExpression
                and item
                and int(item.get("version", 0)) != int(values.get(":expected_version", -1))
            ):
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ConditionalCheckFailedException",
                            "Message": "Version mismatch",
                        }
                    },
                    "UpdateItem",
                )
            if (
                "attribute_not_exists(execution_lock)" in ConditionExpression
                and item
                and "execution_lock" in item
            ):
                raise ClientError(
                    {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Locked"}},
                    "UpdateItem",
                )
            if (
                ":approved_status" in ConditionExpression
                and item
                and item.get("status") != values.get(":approved_status")
            ):
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ConditionalCheckFailedException",
                            "Message": "Status mismatch",
                        }
                    },
                    "UpdateItem",
                )

        if not item:
            item = {"PK": Key["PK"], "SK": Key["SK"]}
            self.items[key] = item

        # Apply simple mock updates
        if ":executing_status" in values:
            item["status"] = values[":executing_status"]
        elif ":status" in values:
            item["status"] = values[":status"]
        if ":new_version" in values:
            item["version"] = values[":new_version"]
        if ":updated_at" in values:
            item["updated_at"] = values[":updated_at"]
        if ":action_id" in values:
            item["execution_lock"] = values[":action_id"]
        if ":summary" in values:
            item["result_summary"] = values[":summary"]
        if ":result" in values:
            item["result"] = values[":result"]

        return {"Attributes": dict(item)}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        # Return all items matching basic entity or index filters
        matched: list[dict[str, Any]] = []
        index_name = kwargs.get("IndexName")

        for item in self.items.values():
            if index_name == "GSI1":
                if "GSI1PK" in item:
                    matched.append(dict(item))
            elif index_name == "GSI2":
                if "GSI2PK" in item:
                    matched.append(dict(item))
            else:
                matched.append(dict(item))

        return {"Items": matched}


# Tests
def test_dynamodb_case_crud_and_optimistic_locking():
    mock_table = MockDynamoDBTable()
    repo = DynamoDBCaseRepository(mock_table)

    case = Case(
        case_id="c_ddb_01",
        organization_id="org_alpha",
        location_id="loc_1",
        device_id="dev_1",
        event_id="evt_1",
        title="Possible after-hours delivery activity",
        status=CaseStatus.RECEIVED,
        version=1,
    )
    repo.create_case(case)

    # Read case
    fetched = repo.get_case("c_ddb_01", "org_alpha")
    assert fetched.case_id == "c_ddb_01"
    assert fetched.version == 1

    # Cross org access blocked
    with pytest.raises(OrganizationAccessDeniedError):
        repo.get_case("c_ddb_01", "org_beta")

    # Optimistic update
    updated_case = case.model_copy(update={"status": CaseStatus.VALIDATED})
    result = repo.update_case(updated_case, "org_alpha", expected_version=1)
    assert result.version == 2

    # Stale version update rejected
    with pytest.raises(VersionMismatchError):
        repo.update_case(result, "org_alpha", expected_version=1)


def test_dynamodb_event_and_dedup():
    mock_table = MockDynamoDBTable()
    repo = DynamoDBEventRepository(mock_table)

    event = RingEvent(
        event_id="evt_ddb_1",
        request_id="req_ddb_1",
        device_id="dev_1",
        event_type="motion",
        occurred_at="2026-10-08T22:00:00Z",
        provenance=Provenance.RING_SIGNED,
        payload={},
    )
    repo.save_ring_event(event, case_id="c_ddb_01")

    assert repo.record_webhook_dedup("req_ddb_1", "evt_ddb_1") is True
    # Duplicate returns False
    assert repo.record_webhook_dedup("req_ddb_1", "evt_ddb_1") is False


def test_dynamodb_action_lock_and_completion():
    mock_table = MockDynamoDBTable()
    case_repo = DynamoDBCaseRepository(mock_table)
    action_repo = DynamoDBActionRepository(mock_table)

    case = Case(
        case_id="c_act_01",
        organization_id="org_alpha",
        location_id="loc_1",
        device_id="dev_1",
        event_id="evt_1",
        title="Possible after-hours delivery activity",
        status=CaseStatus.APPROVED,
        version=2,
    )
    case_repo.create_case(case)

    action = Action(
        action_id="act_ddb_01",
        case_id="c_act_01",
        approval_id="appr_01",
        action_type=ActionType.NOTIFY_OPERATOR,
        parameters={},
        status=ActionStatus.PENDING,
        idempotency_key="idemp_ddb_1",
    )
    action_repo.save_action(action, "org_alpha")

    # Acquire lock
    action_repo.acquire_execution_lock(
        "c_act_01", "act_ddb_01", "org_alpha", expected_case_version=2
    )
    locked_case = case_repo.get_case("c_act_01", "org_alpha")
    assert locked_case.status == CaseStatus.EXECUTING

    # Second acquisition fails
    with pytest.raises(AlreadyExecutingError):
        action_repo.acquire_execution_lock(
            "c_act_01", "act_ddb_02", "org_alpha", expected_case_version=3
        )

    # Complete action
    completed = action_repo.complete_action("c_act_01", "act_ddb_01", "org_alpha", "Done")
    assert completed.status == ActionStatus.SUCCEEDED


def test_dynamodb_audit_immutability():
    mock_table = MockDynamoDBTable()
    repo = DynamoDBAuditRepository(mock_table)

    event = AuditEvent(
        event_id="aud_ddb_1",
        case_id="c_aud_01",
        actor_id="sys",
        actor_type="SYSTEM",
        action=AuditEventType.CASE_CREATED,
        previous_hash="0" * 64,
        current_hash="hash_1",
    )
    repo.append_audit_event(event, "org_alpha")

    # Duplicate / overwrite raises ConflictError
    with pytest.raises(ConflictError):
        repo.append_audit_event(event, "org_alpha")


def test_dynamodb_idempotency_and_policy():
    mock_table = MockDynamoDBTable()
    idemp_repo = DynamoDBIdempotencyRepository(mock_table)
    pol_repo = DynamoDBPolicyRepository(mock_table)

    assert idemp_repo.acquire_lock("key_123", "action") is True
    assert idemp_repo.acquire_lock("key_123", "action") is False

    idemp_repo.complete_operation("key_123", {"status": "ok"})
    rec = idemp_repo.get_record("key_123")
    assert rec is not None
    assert rec["status"] == "COMPLETED"

    policy = Policy(
        policy_id="pol_alpha",
        organization_id="org_alpha",
        allowed_actions=[ActionType.NOTIFY_OPERATOR],
    )
    pol_repo.save_policy(policy)
    fetched_pol = pol_repo.get_policy("org_alpha")
    assert fetched_pol is not None
    assert fetched_pol.policy_id == "pol_alpha"


def test_dynamodb_client_error_mapping():
    ce_cond = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Cond failed"}},
        "PutItem",
    )
    mapped = map_client_error(ce_cond, "Case", "c1")
    assert "Conditional write check failed" in str(mapped)

    ce_nf = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}},
        "GetItem",
    )
    mapped_nf = map_client_error(ce_nf, "Case", "c1")
    assert isinstance(mapped_nf, NotFoundError)
