"""Unit tests for audit timeline SHA-256 hash chaining and tamper-evidence."""

from apps.api.src.utils.audit_hasher import (
    GENESIS_HASH,
    create_audit_event,
    verify_audit_chain,
    verify_audit_event,
)
from packages.contracts.enums import AuditEventType


def test_genesis_audit_event():
    evt = create_audit_event(
        case_id="case_chain_01",
        actor_id="usr_admin",
        actor_type="HUMAN",
        action=AuditEventType.CASE_CREATED,
        metadata={"note": "genesis record"},
    )

    assert evt.previous_hash == GENESIS_HASH
    assert len(evt.current_hash) == 64
    assert verify_audit_event(evt) is True


def test_multi_event_hash_chain():
    e1 = create_audit_event(
        case_id="case_chain_02",
        actor_id="sys",
        actor_type="SYSTEM",
        action=AuditEventType.CASE_CREATED,
    )

    e2 = create_audit_event(
        case_id="case_chain_02",
        actor_id="usr_ops",
        actor_type="HUMAN",
        action=AuditEventType.APPROVAL_RECORDED,
        previous_hash=e1.current_hash,
        metadata={"approval_id": "appr_1"},
    )

    e3 = create_audit_event(
        case_id="case_chain_02",
        actor_id="sys",
        actor_type="SYSTEM",
        action=AuditEventType.ACTION_COMPLETED,
        previous_hash=e2.current_hash,
        metadata={"action_id": "act_1"},
    )

    timeline = [e1, e2, e3]
    assert verify_audit_chain(timeline) is True


def test_tamper_detection_metadata_modification():
    e1 = create_audit_event(
        case_id="case_chain_03",
        actor_id="sys",
        actor_type="SYSTEM",
        action=AuditEventType.CASE_CREATED,
    )
    e2 = create_audit_event(
        case_id="case_chain_03",
        actor_id="usr_ops",
        actor_type="HUMAN",
        action=AuditEventType.APPROVAL_RECORDED,
        previous_hash=e1.current_hash,
        metadata={"approval_id": "appr_original"},
    )

    # Attacker tampers with metadata in e2
    tampered_e2 = e2.model_copy(update={"metadata": {"approval_id": "appr_injected"}})

    # Individual check catches corruption
    assert verify_audit_event(tampered_e2) is False

    # Chain check catches corruption
    assert verify_audit_chain([e1, tampered_e2]) is False


def test_tamper_detection_broken_chain_link():
    e1 = create_audit_event(
        case_id="case_chain_04",
        actor_id="sys",
        actor_type="SYSTEM",
        action=AuditEventType.CASE_CREATED,
    )
    e2 = create_audit_event(
        case_id="case_chain_04",
        actor_id="usr_ops",
        actor_type="HUMAN",
        action=AuditEventType.APPROVAL_RECORDED,
        previous_hash="f" * 64,  # Does not match e1.current_hash
    )

    assert verify_audit_chain([e1, e2]) is False


def test_tamper_detection_invalid_genesis():
    e1 = create_audit_event(
        case_id="case_chain_05",
        actor_id="sys",
        actor_type="SYSTEM",
        action=AuditEventType.CASE_CREATED,
        previous_hash="1" * 64,  # Not GENESIS_HASH
    )
    assert verify_audit_chain([e1]) is False
