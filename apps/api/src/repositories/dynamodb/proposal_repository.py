"""DynamoDB single-table implementation of ProposalRepository."""

from typing import Any

from botocore.exceptions import ClientError

from packages.contracts.models import Proposal

from ..errors import (
    ConflictError,
    OrganizationAccessDeniedError,
)
from .base import (
    clean_dynamodb_dict,
    format_case_pk,
    map_client_error,
)


def format_proposal_sk(proposal_id: str) -> str:
    return f"PROPOSAL#{proposal_id}"


class DynamoDBProposalRepository:
    """Production DynamoDB adapter for Proposal entities."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def save_proposal(self, proposal: Proposal, organization_id: str) -> Proposal:
        pk = format_case_pk(proposal.case_id)
        sk = format_proposal_sk(proposal.proposal_id)

        item = clean_dynamodb_dict(proposal.model_dump())
        item.update(
            {
                "PK": pk,
                "SK": sk,
                "organization_id": organization_id,
                "entity_type": "PROPOSAL",
            }
        )

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            return proposal
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConflictError(f"Proposal '{proposal.proposal_id}' already exists.") from e
            raise map_client_error(e, "Proposal", proposal.proposal_id) from e

    def get_proposal(self, case_id: str, proposal_id: str, organization_id: str) -> Proposal | None:
        pk = format_case_pk(case_id)
        sk = format_proposal_sk(proposal_id)

        try:
            resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        except ClientError as e:
            raise map_client_error(e, "Proposal", proposal_id) from e

        item = resp.get("Item")
        if not item:
            return None

        if item.get("organization_id") != organization_id:
            raise OrganizationAccessDeniedError(
                target_resource=f"Proposal/{proposal_id}",
                expected_org_id=organization_id,
                actual_org_id=str(item.get("organization_id")),
            )

        data = {
            k: v
            for k, v in item.items()
            if k not in {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "entity_type"}
        }
        return Proposal.model_validate(data)
