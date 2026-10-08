"""Unit tests for Phase 4 DEMO scenarios."""

from apps.api.src.services.demo_phase4 import run_phase4_demo_scenario


def test_phase4_demo_scenario_1_after_hours_expected_delivery():
    res = run_phase4_demo_scenario(1)
    assert res.is_fallback is False
    assert "TRUE" in str(res.knowns)
    assert res.proposal_action == "NOTIFY_OPERATOR"
    assert len(res.proposal_hash) == 64


def test_phase4_demo_scenario_2_after_hours_no_expected_delivery():
    res = run_phase4_demo_scenario(2)
    assert res.is_fallback is False
    assert "FALSE" in str(res.knowns)
    assert res.proposal_action == "NOTIFY_OPERATOR"


def test_phase4_demo_scenario_3_normal_hours_activity():
    res = run_phase4_demo_scenario(3)
    assert res.is_fallback is False
    assert any("normal business hours" in k for k in res.knowns)


def test_phase4_demo_scenario_4_multiple_correlated_events():
    res = run_phase4_demo_scenario(4)
    assert res.is_fallback is False
    assert any("3" in k for k in res.knowns)  # 3 correlated events


def test_phase4_demo_scenario_5_unknown_expected_delivery():
    res = run_phase4_demo_scenario(5)
    assert res.is_fallback is False
    assert "FALSE" in str(res.knowns) or "UNKNOWN" in str(res.knowns)


def test_phase4_demo_scenario_6_ai_unavailable_fallback():
    # Bedrock timeout/offline simulates automatic fallback
    res = run_phase4_demo_scenario(6)
    assert res.is_fallback is True
    assert len(res.facts) > 0
    assert len(res.unknowns) > 0
    assert res.proposal_action in ("NOTIFY_OPERATOR", "MARK_FOR_REVIEW")


def test_phase4_demo_scenario_7_invalid_ai_output_fallback():
    # Broken JSON from model triggers fallback
    res = run_phase4_demo_scenario(7)
    assert res.is_fallback is True
    assert res.proposal_action in ("NOTIFY_OPERATOR", "MARK_FOR_REVIEW")


def test_phase4_demo_scenario_8_prohibited_proposal_fallback():
    # Model attempted UNLOCK_DOOR; validation rejected it and safely triggered fallback
    res = run_phase4_demo_scenario(8)
    assert res.is_fallback is True
    assert res.proposal_action != "UNLOCK_DOOR"
    assert res.proposal_action in ("NOTIFY_OPERATOR", "MARK_FOR_REVIEW")
