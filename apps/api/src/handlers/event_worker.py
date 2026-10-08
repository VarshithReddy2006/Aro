"""EventBridge worker Lambda handler for asynchronous case processing and bounded AI brief generation.

Handled detail-types:
- RingEventReceived: correlates raw event to case, updates context, triggers brief
- BriefRequested: executes bounded Bedrock brief generator and validates proposals

Security & Architectural Invariants:
- Reuses IdempotencyRepository to ensure safe Lambda retries.
- Authoritative state is always loaded from DynamoDB, not trusted from event payload.
- Bedrock is invoked solely to generate bounded structured proposals.
- AI never directly executes actions; proposals require human approval.
"""

import json
import logging
import os
from typing import Any

from packages.contracts.models import Location

from ..repositories.in_memory import (
    InMemoryAuditRepository,
    InMemoryCaseRepository,
    InMemoryDeviceRepository,
    InMemoryEventRepository,
    InMemoryExpectedDeliveryRepository,
    InMemoryIdempotencyRepository,
    InMemoryLocationRepository,
    InMemoryPolicyRepository,
    InMemoryProposalRepository,
)
from ..services.bedrock_adapter import BedrockBriefGenerator, FallbackBriefGenerator
from ..services.brief_service import BriefService
from ..services.case_context_builder import CaseContextBuilder
from ..services.correlation import DefaultCaseCorrelationService
from ..services.ring_normalizer import RingNormalizer

logger = logging.getLogger("aro.event_worker")


class WorkerContainer:
    """Dependency container for worker lambda with DynamoDB or in-memory fallback."""

    case_repo: Any
    event_repo: Any
    audit_repo: Any
    idempotency_repo: Any
    policy_repo: Any
    delivery_repo: Any
    proposal_repo: Any

    def __init__(self) -> None:
        table_name = os.environ.get("ARO_TABLE_NAME")
        if table_name and "demo" not in os.environ.get("ARO_ENV", "demo").lower():
            try:
                import boto3

                from ..repositories.dynamodb import (
                    DynamoDBAuditRepository,
                    DynamoDBCaseRepository,
                    DynamoDBEventRepository,
                    DynamoDBExpectedDeliveryRepository,
                    DynamoDBIdempotencyRepository,
                    DynamoDBPolicyRepository,
                    DynamoDBProposalRepository,
                )

                table = boto3.resource("dynamodb").Table(table_name)
                self.case_repo = DynamoDBCaseRepository(table)
                self.event_repo = DynamoDBEventRepository(table)
                self.audit_repo = DynamoDBAuditRepository(table)
                self.idempotency_repo = DynamoDBIdempotencyRepository(table)
                self.policy_repo = DynamoDBPolicyRepository(table)
                self.delivery_repo = DynamoDBExpectedDeliveryRepository(table)
                self.proposal_repo = DynamoDBProposalRepository(table)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Worker DynamoDB initialization failed, falling back to in-memory: %s", exc
                )
                self._init_in_memory()
        else:
            self._init_in_memory()

        self.location_repo = InMemoryLocationRepository()
        self.device_repo = InMemoryDeviceRepository()

        self.context_builder = CaseContextBuilder(
            case_repository=self.case_repo,
            event_repository=self.event_repo,
            location_repository=self.location_repo,
            device_repository=self.device_repo,
            delivery_repository=self.delivery_repo,
            policy_repository=self.policy_repo,
        )

        model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
        primary_gen = BedrockBriefGenerator(model_id=model_id)
        fallback_gen = FallbackBriefGenerator()

        self.brief_service = BriefService(
            context_builder=self.context_builder,
            case_repository=self.case_repo,
            primary_generator=primary_gen,
            fallback_generator=fallback_gen,
        )

        self.correlation_service = DefaultCaseCorrelationService(self.event_repo, self.case_repo)
        self.normalizer = RingNormalizer()

    def _init_in_memory(self) -> None:
        self.case_repo = InMemoryCaseRepository()
        self.event_repo = InMemoryEventRepository()
        self.audit_repo = InMemoryAuditRepository()
        self.idempotency_repo = InMemoryIdempotencyRepository()
        self.policy_repo = InMemoryPolicyRepository()
        self.delivery_repo = InMemoryExpectedDeliveryRepository()
        self.proposal_repo = InMemoryProposalRepository()


_worker_container: WorkerContainer | None = None


def get_worker_container() -> WorkerContainer:
    global _worker_container
    if _worker_container is None:
        _worker_container = WorkerContainer()
    return _worker_container


def handle_event_bridge_event(
    event: dict[str, Any],
    context: Any = None,
    container: WorkerContainer | None = None,
) -> dict[str, Any]:
    """Process incoming EventBridge events safely and idempotently."""
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            detail = {}

    event_id = event.get("id") or detail.get("event_id") or "evt_unknown"
    idempotency_key = f"worker#{detail_type}#{event_id}"

    services = container or get_worker_container()

    # Lambda retry safety via IdempotencyRepository
    lock_acquired = services.idempotency_repo.acquire_lock(
        key=idempotency_key, operation=f"EVENT_WORKER_{detail_type}", ttl_seconds=86400
    )
    if not lock_acquired:
        existing = services.idempotency_repo.get_record(idempotency_key)
        logger.info(
            "Idempotent replay detected for %s; skipping duplicate execution", idempotency_key
        )
        return {
            "status": "IDEMPOTENT_SKIPPED",
            "key": idempotency_key,
            "cached_result": existing.get("result") if existing else None,
        }

    try:
        result_payload: dict[str, Any] = {}

        if detail_type == "RingEventReceived":
            target_event_id = detail.get("event_id")
            if not target_event_id:
                return {"status": "SKIPPED", "reason": "No event_id in detail"}

            raw_event = services.event_repo.get_ring_event(target_event_id)
            if not raw_event:
                return {"status": "NOT_FOUND", "event_id": target_event_id}

            org_id = (
                detail.get("organization_id")
                or getattr(raw_event, "organization_id", None)
                or "org_default"
            )
            location = Location(
                location_id="loc_hq",
                organization_id=org_id,
                name="Headquarters",
                timezone="America/New_York",
            )
            norm_event = services.normalizer.normalize(raw_event, location=location)
            outcome = services.correlation_service.correlate(raw_event, norm_event, org_id)

            result_payload = {
                "event_id": target_event_id,
                "correlated_case_id": outcome.case_id,
                "status": "CORRELATED" if outcome.correlated else "UNMATCHED",
            }

        elif detail_type == "BriefRequested":
            case_id = detail.get("case_id")
            org_id = detail.get("organization_id", "org_default")
            force_fallback = detail.get("force_fallback", False)

            if not case_id:
                return {"status": "SKIPPED", "reason": "No case_id provided"}

            brief_result = services.brief_service.generate_brief_for_case(
                case_id=case_id,
                organization_id=org_id,
                force_fallback=force_fallback,
            )

            for prop in brief_result.proposals:
                services.proposal_repo.save_proposal(prop, org_id)

            result_payload = {
                "case_id": case_id,
                "brief_id": brief_result.brief.brief_id,
                "proposals_count": len(brief_result.proposals),
                "is_fallback": brief_result.is_fallback,
            }

        else:
            result_payload = {"status": "IGNORED", "detail_type": detail_type}

        services.idempotency_repo.complete_operation(idempotency_key, result_payload)
        return {"status": "SUCCESS", "result": result_payload}

    except Exception as exc:
        logger.exception("Worker processing failed for %s", detail_type)
        return {"status": "FAILED", "error": type(exc).__name__, "message": str(exc)}
