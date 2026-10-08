"""Unit tests verifying Phase 5 offline demo scenarios."""

import pytest

from apps.api.src.services.demo_phase5 import Phase5DemoHarness


@pytest.fixture
def harness():
    return Phase5DemoHarness()


def test_demo_scenario_1_happy_path(harness):
    result = harness.scenario_1_happy_path_approval_and_execution()
    assert result.success is True
    assert result.details["audit_chain_valid"] is True


def test_demo_scenario_2_direct_execution_blocked(harness):
    result = harness.scenario_2_direct_execution_blocked()
    assert result.success is True
    assert result.details["blocked"] is True


def test_demo_scenario_3_tampered_proposal_hash_blocked(harness):
    result = harness.scenario_3_tampered_proposal_hash_blocked()
    assert result.success is True
    assert result.details["error_raised"] == "ProposalHashMismatchError"


def test_demo_scenario_4_stale_case_version_blocked(harness):
    result = harness.scenario_4_stale_case_version_blocked()
    assert result.success is True
    assert result.details["error_raised"] == "StateVersionMismatchError"


def test_demo_scenario_5_rbac_viewer_blocked(harness):
    result = harness.scenario_5_rbac_viewer_blocked()
    assert result.success is True
    assert result.details["error_raised"] == "UnauthorizedApproverError"


def test_demo_scenario_6_tenant_isolation_blocked(harness):
    result = harness.scenario_6_tenant_isolation_blocked()
    assert result.success is True
    assert result.details["error_raised"] == "OrganizationAccessDeniedError"


def test_demo_scenario_7_expired_approval_blocked(harness):
    result = harness.scenario_7_expired_approval_blocked()
    assert result.success is True
    assert result.details["error_raised"] == "ApprovalExpiredError"


def test_demo_scenario_8_duplicate_execution_idempotency(harness):
    result = harness.scenario_8_duplicate_execution_idempotency()
    assert result.success is True
    assert result.details["first_was_idempotent"] is False
    assert result.details["second_was_idempotent"] is True


def test_demo_scenario_9_audit_chain_verification(harness):
    result = harness.scenario_9_audit_chain_verification()
    assert result.success is True
    assert result.details["original_chain_valid"] is True
    assert result.details["tamper_detected"] is True


def test_run_all_demo_scenarios(harness):
    results = harness.run_all_scenarios()
    assert len(results) == 9
    assert all(r.success for r in results)
