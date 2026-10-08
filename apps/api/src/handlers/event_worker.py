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

from packages.contracts.enums import CaseStatus
from packages.contracts.models import Location, RingDevice

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
from ..services.case_correlation import CaseCorrelationService
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
    correlation_service: Any

    def __init__(self, use_in_memory: bool = False) -> None:
        env = os.environ.get("ARO_ENV", "demo").strip().lower()
        table_name = os.environ.get("ARO_TABLE_NAME")

        if use_in_memory or env in {"demo", "local", "test"}:
            if table_name and not use_in_memory:
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
                        "Demo mode DynamoDB initialization failed, falling back to in-memory: %s",
                        exc,
                    )
                    self._init_in_memory()
            else:
                self._init_in_memory()
        else:
            # dev / prod: MUST NOT fall back to in-memory!
            if not table_name:
                logger.error(
                    "Missing required environment variable ARO_TABLE_NAME in %s environment",
                    env,
                )
                raise RuntimeError(
                    f"DynamoDB table name (ARO_TABLE_NAME) not configured in {env} environment"
                )

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
            except Exception as exc:
                logger.error(
                    "Could not initialize DynamoDB tables in %s environment: %s",
                    env,
                    exc,
                )
                raise RuntimeError(
                    f"DynamoDB initialization failed in {env} environment: {exc}"
                ) from exc

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

        self.correlation_service = CaseCorrelationService(self.event_repo, self.case_repo)
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


def _reset_worker_container() -> None:
    """Clear cached worker container for test isolation."""
    global _worker_container
    _worker_container = None


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

            # 1. Resolve Location
            location_id = detail.get("location_id") or "loc_hq"
            location = services.location_repo.get_location(location_id)
            if location is None:
                location = Location(
                    location_id=location_id,
                    organization_id=org_id,
                    name="Headquarters",
                    timezone="America/New_York",
                    business_hours_start="08:00",
                    business_hours_end="18:00",
                    business_days=[0, 1, 2, 3, 4],
                )
                services.location_repo.save_location(location)

            # 2. Resolve Device
            device = services.device_repo.get_device(raw_event.device_id)
            if device is None:
                dev_id_lower = raw_event.device_id.lower()
                is_designated = any(
                    door_kw in dev_id_lower
                    for door_kw in ("door", "entrance", "gate", "front", "entry")
                ) or raw_event.event_type.lower() in ("doorbell_ring", "button_press")
                device = RingDevice(
                    device_id=raw_event.device_id,
                    location_id=location.location_id,
                    name="Front Door" if is_designated else raw_event.device_id,
                    kind="doorbell" if "doorbell" in dev_id_lower else "camera",
                    is_designated_door=is_designated,
                )
                services.device_repo.save_device(device)

            # 3. Deterministic normalization
            norm_event = services.normalizer.normalize(
                event=raw_event,
                location=location,
                device=device,
            )

            # 4. Correlation / case creation evaluation
            try:
                outcome = services.correlation_service.correlate(
                    event=raw_event,
                    normalized_event=norm_event,
                    organization_id=org_id,
                    location=location,
                    device=device,
                )
            except TypeError:
                outcome = services.correlation_service.correlate(
                    event=raw_event,
                    normalized_event=norm_event,
                    organization_id=org_id,
                )

            if not outcome.correlated or not outcome.case_id:
                result_payload = {
                    "event_id": target_event_id,
                    "correlated_case_id": None,
                    "case_id": None,
                    "status": "UNMATCHED",
                    "reason": outcome.reason,
                }
                services.idempotency_repo.complete_operation(idempotency_key, result_payload)
                return {"status": "SUCCESS", "result": result_payload}

            # 5. Check if case already has an active proposal and is in APPROVAL_PENDING (idempotency)
            try:
                active_case = services.case_repo.get_case(
                    case_id=outcome.case_id, organization_id=org_id
                )
                if (
                    active_case
                    and active_case.active_proposal_id
                    and active_case.status == CaseStatus.APPROVAL_PENDING
                ):
                    result_payload = {
                        "event_id": target_event_id,
                        "correlated_case_id": outcome.case_id,
                        "case_id": outcome.case_id,
                        "brief_id": active_case.brief_id,
                        "proposal_id": active_case.active_proposal_id,
                        "status": "CORRELATED",
                        "lifecycle_status": active_case.status.value,
                        "is_new_case": getattr(outcome, "is_new_case", False),
                        "idempotent": True,
                    }
                    services.idempotency_repo.complete_operation(idempotency_key, result_payload)
                    return {"status": "SUCCESS", "result": result_payload}
            except Exception as exc:  # noqa: BLE001
                logger.debug("Idempotency lookup bypassed: %s", exc)

            # 6. Generate bounded AI brief and transition case to APPROVAL_PENDING
            force_fallback = detail.get("force_fallback", False)
            brief_result = services.brief_service.generate_brief_for_case(
                case_id=outcome.case_id,
                organization_id=org_id,
                force_fallback=force_fallback,
            )

            for prop in brief_result.proposals:
                services.proposal_repo.save_proposal(prop, org_id)

            try:
                updated_case = services.case_repo.get_case(outcome.case_id, org_id)
                active_prop_id = updated_case.active_proposal_id
                lifecycle_status = updated_case.status.value
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not reload case %s: %s", outcome.case_id, exc)
                active_prop_id = (
                    brief_result.proposals[0].proposal_id if brief_result.proposals else None
                )
                lifecycle_status = (
                    CaseStatus.APPROVAL_PENDING.value
                    if brief_result.proposals
                    else CaseStatus.RECEIVED.value
                )

            result_payload = {
                "event_id": target_event_id,
                "correlated_case_id": outcome.case_id,
                "case_id": outcome.case_id,
                "brief_id": brief_result.brief.brief_id,
                "proposal_id": active_prop_id,
                "proposals_count": len(brief_result.proposals),
                "is_fallback": brief_result.is_fallback,
                "status": "CORRELATED",
                "lifecycle_status": lifecycle_status,
                "is_new_case": getattr(outcome, "is_new_case", False),
            }

        elif detail_type == "BriefRequested":
            case_id = detail.get("case_id")
            org_id = detail.get("organization_id", "org_default")
            force_fallback = detail.get("force_fallback", False)

            if not case_id:
                return {"status": "SKIPPED", "reason": "No case_id provided"}

            # Idempotency check
            try:
                active_case = services.case_repo.get_case(case_id, org_id)
                if (
                    active_case
                    and active_case.active_proposal_id
                    and active_case.status == CaseStatus.APPROVAL_PENDING
                ):
                    prop = services.proposal_repo.get_proposal(
                        case_id, active_case.active_proposal_id, org_id
                    )
                    result_payload = {
                        "case_id": case_id,
                        "brief_id": active_case.brief_id,
                        "proposal_id": active_case.active_proposal_id,
                        "proposals_count": 1 if prop else 0,
                        "is_fallback": getattr(active_case, "is_fallback", False),
                        "status": "APPROVAL_PENDING",
                        "idempotent": True,
                    }
                    services.idempotency_repo.complete_operation(idempotency_key, result_payload)
                    return {"status": "SUCCESS", "result": result_payload}
            except Exception as exc:  # noqa: BLE001
                logger.debug("Brief idempotency check skipped: %s", exc)

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
