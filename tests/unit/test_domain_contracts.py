"""Unit tests for Aro canonical domain models and enums."""

import pytest
from pydantic import ValidationError

from packages.contracts.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseStatus,
    ExpectedDeliveryStatus,
    Provenance,
    Role,
)
from packages.contracts.models import (
    Action,
    Approval,
    AuditEvent,
    Case,
    CaseBrief,
    CaseContext,
    EvidenceBundle,
    ExpectedDelivery,
    Location,
    NormalizedEvent,
    Organization,
    Policy,
    Proposal,
    RingDevice,
    RingEvent,
    User,
)


def test_user_model_instantiation_and_validation():
    """Verify User model creation with role-based attributes."""
    user = User(
        user_id="usr_001",
        organization_id="org_001",
        email="ops@cowork.example",
        name="Jane Operator",
        role=Role.OPERATOR,
    )
    assert user.role == Role.OPERATOR
    assert user.email == "ops@cowork.example"

    # Must reject invalid email or empty user_id
    with pytest.raises(ValidationError):
        User(
            user_id="",
            organization_id="org_001",
            email="invalid",
            name="Test",
            role=Role.OPERATOR,
        )


def test_organization_and_location():
    """Verify Organization and Location schedule models."""
    org = Organization(org_id="org_001", name="Alpha Coworking")
    assert org.name == "Alpha Coworking"

    loc = Location(
        location_id="loc_001",
        organization_id=org.org_id,
        name="Downtown Hub",
        timezone="America/New_York",
        business_hours_start="08:00",
        business_hours_end="20:00",
        business_days=[0, 1, 2, 3, 4],
    )
    assert loc.business_hours_start == "08:00"
    assert loc.business_hours_end == "20:00"


def test_ring_device_and_expected_delivery():
    """Verify RingDevice and ExpectedDelivery models."""
    device = RingDevice(
        device_id="ring_dev_front",
        location_id="loc_001",
        name="Front Doorbell Pro",
        kind="doorbell",
        is_designated_door=True,
    )
    assert device.is_designated_door is True

    delivery = ExpectedDelivery(
        delivery_id="deliv_001",
        organization_id="org_001",
        location_id="loc_001",
        carrier="FedEx",
        tracking_number="1234567890",
        recipient_name="Suite 400",
        status=ExpectedDeliveryStatus.TRUE,
    )
    assert delivery.status == ExpectedDeliveryStatus.TRUE
    assert delivery.carrier == "FedEx"


def test_ring_event_and_normalized_event():
    """Verify RingEvent and NormalizedEvent models with proper terminology."""
    event = RingEvent(
        event_id="evt_001",
        request_id="req_001",
        device_id="ring_dev_front",
        event_type="motion",
        occurred_at="2026-10-08T22:30:00Z",
        provenance=Provenance.RING_SIGNED,
        payload={"door_id": "front_door"},
    )
    assert event.provenance == Provenance.RING_SIGNED

    normalized = NormalizedEvent(
        normalized_event_id="norm_001",
        source_event_id=event.event_id,
        device_id=event.device_id,
        location_id="loc_001",
        event_type="motion",
        occurred_at=event.occurred_at,
        provenance=event.provenance,
        is_after_hours=True,
        is_designated_door=True,
        description="Possible after-hours delivery activity observed at designated entrance",
        raw_metadata={},
    )
    assert normalized.is_after_hours is True
    assert normalized.is_designated_door is True


def test_proposal_and_approval_binding():
    """Verify Proposal, hash binding, and Approval models."""
    proposal = Proposal(
        proposal_id="prop_001",
        case_id="case_001",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed while delivery was expected",
        parameters={"channel": "sms", "recipient": "ops-duty"},
        proposal_hash="a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
    )
    assert proposal.action_type == ActionType.NOTIFY_OPERATOR

    approval = Approval(
        approval_id="appr_001",
        case_id="case_001",
        case_version=2,
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal.proposal_hash,
        approver_user_id="usr_admin",
        approver_role=Role.ADMIN,
        expires_at="2026-10-08T23:30:00Z",
    )
    assert approval.case_version == 2
    assert approval.proposal_hash == proposal.proposal_hash


def test_action_and_audit_event():
    """Verify Action and AuditEvent models."""
    action = Action(
        action_id="act_001",
        case_id="case_001",
        approval_id="appr_001",
        action_type=ActionType.NOTIFY_OPERATOR,
        parameters={"channel": "sms"},
        status=ActionStatus.PENDING,
        idempotency_key="idemp_act_001",
    )
    assert action.status == ActionStatus.PENDING

    audit = AuditEvent(
        event_id="audit_001",
        case_id="case_001",
        actor_id="usr_admin",
        actor_type="HUMAN",
        action=AuditEventType.APPROVAL_RECORDED,
        previous_hash="0" * 64,
        current_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        metadata={"approval_id": "appr_001"},
    )
    assert audit.action == AuditEventType.APPROVAL_RECORDED


def test_policy_and_case():
    """Verify Policy and core Case model."""
    policy = Policy(
        policy_id="pol_default",
        organization_id="org_001",
        allowed_actions=[
            ActionType.NOTIFY_OPERATOR,
            ActionType.MARK_FOR_REVIEW,
            ActionType.RECORD_NO_ACTION,
        ],
        approval_timeout_seconds=1200,
    )
    assert ActionType.NOTIFY_OPERATOR in policy.allowed_actions

    case = Case(
        case_id="case_001",
        organization_id="org_001",
        location_id="loc_001",
        device_id="ring_dev_front",
        event_id="evt_001",
        title="Possible after-hours delivery activity at designated entrance",
        status=CaseStatus.RECEIVED,
        version=1,
    )
    assert case.version == 1
    assert case.status == CaseStatus.RECEIVED


def test_case_context_brief_and_evidence_bundle():
    """Verify CaseContext, CaseBrief, and comprehensive EvidenceBundle packaging."""
    context = CaseContext(
        case_id="case_001",
        organization_id="org_001",
        location_id="loc_001",
        device_id="ring_dev_front",
        is_after_hours=True,
        designated_entrance=True,
        expected_delivery_status=ExpectedDeliveryStatus.TRUE,
    )
    assert context.designated_entrance is True

    brief = CaseBrief(
        brief_id="brf_001",
        case_id="case_001",
        summary="Possible delivery-related motion observed at front entrance after operating hours.",
        facts=["Activity at front door at 22:30", "Delivery expected by carrier FedEx"],
        unknowns=["Carrier driver identity not known"],
        context_match="High alignment with scheduled courier delivery",
        is_fallback=False,
    )
    assert brief.is_fallback is False

    proposal = Proposal(
        proposal_id="prop_001",
        case_id="case_001",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed while delivery was expected",
        proposal_hash="a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
    )

    bundle = EvidenceBundle(
        bundle_id="bndl_001",
        case_id="case_001",
        case_context=context,
        brief=brief,
        proposal=proposal,
        bundle_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    assert bundle.bundle_id == "bndl_001"
    assert bundle.case_context.is_after_hours is True
