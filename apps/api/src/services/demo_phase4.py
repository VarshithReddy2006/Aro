"""Deterministic DEMO scenarios for Phase 4: Case Context, Bounded Briefs, and Proposals.

Demonstrates offline, deterministic resilience across all 8 required scenarios:
1. after-hours activity + expected delivery
2. after-hours activity + no expected delivery
3. normal-hours activity
4. multiple correlated events
5. unknown expected delivery
6. AI unavailable (triggers fallback)
7. invalid AI output (triggers fallback)
8. prohibited proposal (e.g. UNLOCK_DOOR, triggers fallback)

Every demo scenario exposes:
- FACTS
- KNOWNS
- UNKNOWNS
- AI BRIEF
- PROPOSAL
- FALLBACK STATUS
"""

from dataclasses import dataclass
from typing import Any

from packages.contracts.enums import (
    ActionType,
    CaseStatus,
    ExpectedDeliveryStatus,
    Provenance,
)
from packages.contracts.models import (
    Case,
    ExpectedDelivery,
    Location,
    NormalizedEvent,
    Policy,
    RingDevice,
    RingEvent,
)

from ..repositories.in_memory import (
    InMemoryCaseRepository,
    InMemoryDeviceRepository,
    InMemoryEventRepository,
    InMemoryExpectedDeliveryRepository,
    InMemoryLocationRepository,
    InMemoryPolicyRepository,
)
from .bedrock_adapter import FallbackBriefGenerator
from .brief_service import BriefGenerationResult, BriefService
from .case_context_builder import CaseContextBuilder


@dataclass(frozen=True)
class Phase4DemoScenarioResult:
    """Complete output of a Phase 4 demo execution."""

    scenario_name: str
    description: str
    facts: list[str]
    knowns: list[str]
    unknowns: list[str]
    brief_summary: str
    proposal_action: str
    proposal_reason: str
    proposal_hash: str
    is_fallback: bool
    context_match: str


class MockBedrockGenerator:
    """Mock generator simulating specific AI behaviors (success, failure, invalid, prohibited)."""

    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode

    def generate_raw_brief(self, ai_input: Any) -> str:
        if self.mode == "error":
            raise RuntimeError("Bedrock connection timed out after 10000ms")

        if self.mode == "invalid_json":
            return "This is not valid JSON at all!"

        if self.mode == "prohibited_action":
            return """{
              "summary": "Motion observed at front door after hours.",
              "facts": ["Motion observed at entrance."],
              "unknowns": ["Identity of visitor."],
              "context_match": "After-hours activity observed.",
              "proposals": [
                {
                  "action_type": "UNLOCK_DOOR",
                  "reason": "Unlock entrance for incoming courier",
                  "parameters": {}
                }
              ]
            }"""

        if self.mode == "prohibited_claims":
            return """{
              "summary": "Ring detected a package delivered by FedEx courier.",
              "facts": ["Package was delivered to door."],
              "unknowns": ["Recipient presence."],
              "context_match": "Delivery confirmed.",
              "proposals": [
                {
                  "action_type": "NOTIFY_OPERATOR",
                  "reason": "Package arrived",
                  "parameters": {"message": "Package delivered", "urgency": "normal", "recipient_role": "OPERATOR"}
                }
              ]
            }"""

        # Valid AI generation
        return """{
          "summary": "Possible after-hours delivery activity observed at designated entrance.",
          "facts": [
            "Physical event activity observed at Front Doorbell.",
            "Activity occurred outside standard business hours.",
            "Expected delivery context status: TRUE."
          ],
          "unknowns": [
            "Whether a parcel or physical item was actually deposited.",
            "Personal identity of observed individual."
          ],
          "context_match": "Activity aligns with scheduled courier window.",
          "proposals": [
            {
              "action_type": "NOTIFY_OPERATOR",
              "reason": "Correlates with expected delivery outside business hours.",
              "parameters": {
                "message": "Activity observed matching scheduled delivery window.",
                "urgency": "normal",
                "recipient_role": "OPERATOR"
              }
            }
          ]
        }"""


def run_phase4_demo_scenario(scenario_index: int) -> Phase4DemoScenarioResult:
    """Execute one of the 8 deterministic demo scenarios."""
    org_id = f"org_demo_{scenario_index}"
    loc_id = f"loc_demo_{scenario_index}"
    dev_id = f"dev_demo_{scenario_index}"
    case_id = f"case_demo_{scenario_index}"
    evt_id = f"evt_demo_{scenario_index}"

    # Setup repositories
    case_repo = InMemoryCaseRepository()
    event_repo = InMemoryEventRepository()
    loc_repo = InMemoryLocationRepository()
    dev_repo = InMemoryDeviceRepository()
    deliv_repo = InMemoryExpectedDeliveryRepository()
    pol_repo = InMemoryPolicyRepository()

    # Location
    loc = Location(
        location_id=loc_id,
        organization_id=org_id,
        name="TechHub Coworking",
        timezone="America/New_York",
        business_hours_start="08:00",
        business_hours_end="20:00",
        business_days=[0, 1, 2, 3, 4],
    )
    loc_repo.save_location(loc)

    # Device
    is_designated = scenario_index != 3  # Non-designated for scenario 3
    dev = RingDevice(
        device_id=dev_id,
        location_id=loc_id,
        name="Front Entrance Doorbell",
        kind="doorbell",
        is_designated_door=is_designated,
    )
    dev_repo.save_device(dev)

    # Policy
    pol = Policy(
        policy_id=f"pol_{org_id}",
        organization_id=org_id,
        allowed_actions=[
            ActionType.NOTIFY_OPERATOR,
            ActionType.MARK_FOR_REVIEW,
            ActionType.REQUEST_OPERATOR_CONFIRMATION,
            ActionType.RECORD_NO_ACTION,
        ],
    )
    pol_repo.save_policy(pol)

    # Timestamps
    # 2026-10-07T22:30:00Z = 18:30 EDT (after-hours since NY time closes at 20:00? wait, 22:30 EDT is 02:30 UTC next day)
    # 02:30 UTC on 2026-10-08 = 22:30 EDT on 2026-10-07 (outside 08:00-20:00, after hours!)
    after_hours_ts = "2026-10-08T02:30:00Z"
    # Normal hours: 18:00 UTC = 14:00 EDT (normal hours)
    normal_hours_ts = "2026-10-07T18:00:00Z"

    event_ts = normal_hours_ts if scenario_index == 3 else after_hours_ts

    # Expected Deliveries
    if scenario_index == 1:
        # After-hours activity + expected delivery
        d = ExpectedDelivery(
            delivery_id="deliv_01",
            organization_id=org_id,
            location_id=loc_id,
            carrier="FedEx Express",
            tracking_number="789123456789",
            recipient_name="Suite 400 Office Mgr",
            status=ExpectedDeliveryStatus.TRUE,
            expected_window_start="2026-10-08T01:00:00Z",
            expected_window_end="2026-10-08T04:00:00Z",
        )
        deliv_repo.save_expected_delivery(d)

    # Case & Event
    raw_event = RingEvent(
        event_id=evt_id,
        request_id=f"req_{evt_id}",
        device_id=dev_id,
        event_type="button_press",
        occurred_at=event_ts,
        provenance=Provenance.DEMO_SYNTHETIC,
        case_id=case_id,
    )
    event_repo.save_ring_event(raw_event)

    case = Case(
        case_id=case_id,
        organization_id=org_id,
        location_id=loc_id,
        device_id=dev_id,
        event_id=evt_id,
        title="Demo Operational Case",
        status=CaseStatus.RECEIVED,
    )
    case_repo.create_case(case)

    # Correlated events
    norm_event_1 = NormalizedEvent(
        normalized_event_id=f"norm_{evt_id}_1",
        source_event_id=evt_id,
        device_id=dev_id,
        location_id=loc_id,
        event_type="button_press",
        occurred_at=event_ts,
        provenance=Provenance.DEMO_SYNTHETIC,
        is_after_hours=scenario_index != 3,
        is_designated_door=is_designated,
        description="Doorbell activity observed at designated entrance",
    )
    event_repo.save_normalized_event(norm_event_1, case_id=case_id)

    if scenario_index == 4:
        # Scenario 4: Multiple correlated events
        for i in range(2, 4):
            norm_event_i = NormalizedEvent(
                normalized_event_id=f"norm_{evt_id}_{i}",
                source_event_id=f"{evt_id}_{i}",
                device_id=dev_id,
                location_id=loc_id,
                event_type="motion_detected",
                occurred_at=after_hours_ts,
                provenance=Provenance.DEMO_SYNTHETIC,
                is_after_hours=True,
                is_designated_door=True,
                description="Motion activity observed at designated entrance",
            )
            event_repo.save_normalized_event(norm_event_i, case_id=case_id)

    # Builder & Service
    builder = CaseContextBuilder(
        case_repository=case_repo,
        event_repository=event_repo,
        location_repository=loc_repo,
        device_repository=dev_repo,
        delivery_repository=deliv_repo,
        policy_repository=pol_repo,
    )

    # Generator setup
    if scenario_index == 6:
        generator = MockBedrockGenerator(mode="error")
    elif scenario_index == 7:
        generator = MockBedrockGenerator(mode="invalid_json")
    elif scenario_index == 8:
        generator = MockBedrockGenerator(mode="prohibited_action")
    else:
        generator = MockBedrockGenerator(mode="valid")

    service = BriefService(
        context_builder=builder,
        case_repository=case_repo,
        primary_generator=generator,
        fallback_generator=FallbackBriefGenerator(),
    )

    res: BriefGenerationResult = service.generate_brief_for_case(
        case_id=case_id,
        organization_id=org_id,
    )

    names = {
        1: (
            "after_hours_expected_delivery",
            "After-hours activity with matching expected delivery",
        ),
        2: (
            "after_hours_no_expected_delivery",
            "After-hours activity without matching expected delivery",
        ),
        3: ("normal_hours_activity", "Activity during normal business hours"),
        4: ("multiple_correlated_events", "Multiple sequential events grouped into single case"),
        5: (
            "unknown_expected_delivery",
            "Activity with unconfigured / indeterminate delivery data",
        ),
        6: (
            "ai_unavailable_fallback",
            "Bedrock service unavailable; triggers deterministic fallback",
        ),
        7: (
            "invalid_ai_output_fallback",
            "Invalid model JSON output; triggers deterministic fallback",
        ),
        8: ("prohibited_proposal_fallback", "Model attempted prohibited action; triggers fallback"),
    }
    s_name, s_desc = names.get(scenario_index, ("scenario", "Operational scenario"))

    first_prop = res.proposals[0] if res.proposals else None

    return Phase4DemoScenarioResult(
        scenario_name=s_name,
        description=s_desc,
        facts=res.brief.facts,
        knowns=res.context_bundle.known_facts,
        unknowns=res.context_bundle.unknowns,
        brief_summary=res.brief.summary,
        proposal_action=first_prop.action_type.value if first_prop else "NONE",
        proposal_reason=first_prop.reason if first_prop else "",
        proposal_hash=first_prop.proposal_hash if first_prop else "",
        is_fallback=res.is_fallback,
        context_match=res.brief.context_match,
    )
