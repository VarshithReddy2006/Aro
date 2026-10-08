"""Unit tests for AIValidationPipeline."""

from apps.api.src.services.ai_validation import AIValidationPipeline
from packages.contracts.enums import ActionType
from packages.contracts.models import AIBriefInput, Policy


def _setup_input_and_policy():
    policy = Policy(
        policy_id="pol_test",
        organization_id="org_test",
        allowed_actions=[
            ActionType.NOTIFY_OPERATOR,
            ActionType.MARK_FOR_REVIEW,
            ActionType.REQUEST_OPERATOR_CONFIRMATION,
            ActionType.RECORD_NO_ACTION,
        ],
    )
    ai_input = AIBriefInput(
        case_id="case_101",
        organization_id="org_test",
        location={"name": "HQ"},
        device={"device_id": "doorbell_front"},
        business_context={"is_after_hours": True, "designated_entrance": True},
        expected_delivery={"status": "UNEXPECTED"},
        known_facts=["Motion activity observed at designated entrance."],
        unknowns=["Whether a package was delivered."],
        allowed_actions=policy.allowed_actions,
    )
    return ai_input, policy


def test_t_ai_valid_structured_response():
    ai_input, policy = _setup_input_and_policy()
    valid_json = """{
      "summary": "Motion activity observed at entrance outside business hours.",
      "facts": ["Motion observed at designated entrance."],
      "unknowns": ["Whether a parcel was delivered."],
      "context_match": "Activity observed outside scheduled operating window.",
      "proposals": [
        {
          "action_type": "NOTIFY_OPERATOR",
          "reason": "After-hours activity observed at entrance.",
          "parameters": {
            "message": "Entrance motion requires operator review",
            "urgency": "normal",
            "recipient_role": "OPERATOR"
          }
        }
      ]
    }"""

    res = AIValidationPipeline.validate(valid_json, ai_input, policy)
    assert res.is_valid is True
    assert res.brief_output is not None
    assert res.brief_output.summary.startswith("Motion activity")
    assert len(res.validated_proposals or []) == 1
    assert res.validated_proposals[0].proposal_hash is not None


def test_t_ai_json_invalid_json_rejected():
    ai_input, policy = _setup_input_and_policy()
    invalid_json = "I am a language model and here is what happened: {broken"

    res = AIValidationPipeline.validate(invalid_json, ai_input, policy)
    assert res.is_valid is False
    assert res.error_stage == "SCHEMA_VALIDATION"
    assert "not valid JSON" in str(res.error_message)


def test_t_ai_missing_required_field_rejected():
    ai_input, policy = _setup_input_and_policy()
    # Missing 'summary' and 'unknowns'
    missing_fields_json = """{
      "facts": ["Motion observed."],
      "context_match": "Match found.",
      "proposals": []
    }"""

    res = AIValidationPipeline.validate(missing_fields_json, ai_input, policy)
    assert res.is_valid is False
    assert res.error_stage == "SCHEMA_VALIDATION"


def test_t_ai_factual_unsupported_claim_rejected():
    ai_input, policy = _setup_input_and_policy()
    # Claims "package was delivered" - strictly prohibited!
    hallucinated_json = """{
      "summary": "Package was delivered by courier at front door.",
      "facts": ["A package was delivered."],
      "unknowns": ["None"],
      "context_match": "Delivery completed.",
      "proposals": [
        {
          "action_type": "NOTIFY_OPERATOR",
          "reason": "Package arrived",
          "parameters": {"message": "Package delivered", "urgency": "normal"}
        }
      ]
    }"""

    res = AIValidationPipeline.validate(hallucinated_json, ai_input, policy)
    assert res.is_valid is False
    assert res.error_stage == "FACTUAL_VALIDATION"
    assert "Prohibited claim detected" in str(res.error_message)


def test_t_ai_forbidden_action_rejected():
    ai_input, policy = _setup_input_and_policy()
    # UNLOCK_DOOR is not in ActionType allowlist
    unlock_json = """{
      "summary": "Motion observed at front door after hours.",
      "facts": ["Motion observed at entrance."],
      "unknowns": ["Visitor identity."],
      "context_match": "Activity observed.",
      "proposals": [
        {
          "action_type": "UNLOCK_DOOR",
          "reason": "Unlock entrance for visitor",
          "parameters": {}
        }
      ]
    }"""

    res = AIValidationPipeline.validate(unlock_json, ai_input, policy)
    assert res.is_valid is False
    # Pydantic enum validation catches unknown ActionType at Schema stage
    assert res.error_stage == "SCHEMA_VALIDATION"


def test_t_ai_unknown_action_invented_rejected():
    ai_input, policy = _setup_input_and_policy()
    invented_json = """{
      "summary": "Motion observed at front door after hours.",
      "facts": ["Motion observed at entrance."],
      "unknowns": ["Visitor identity."],
      "context_match": "Activity observed.",
      "proposals": [
        {
          "action_type": "CALL_POLICE_DIRECTLY",
          "reason": "Call 911 immediately",
          "parameters": {}
        }
      ]
    }"""

    res = AIValidationPipeline.validate(invented_json, ai_input, policy)
    assert res.is_valid is False
    assert res.error_stage == "SCHEMA_VALIDATION"


def test_t_ai_parameters_invalid_rejected():
    ai_input, policy = _setup_input_and_policy()
    # NOTIFY_OPERATOR requires message; also extra forbidden parameter added
    bad_params_json = """{
      "summary": "Motion observed at entrance.",
      "facts": ["Motion observed."],
      "unknowns": ["Unknown identity."],
      "context_match": "Match found.",
      "proposals": [
        {
          "action_type": "NOTIFY_OPERATOR",
          "reason": "Notify operator",
          "parameters": {
            "urgency": "super_mega_critical",
            "forbidden_extra_field": "exploit"
          }
        }
      ]
    }"""

    res = AIValidationPipeline.validate(bad_params_json, ai_input, policy)
    assert res.is_valid is False
    assert res.error_stage == "POLICY_VALIDATION"
    assert "Invalid parameters" in str(res.error_message)


def test_t_ai_policy_prohibited_action_rejected():
    ai_input, _ = _setup_input_and_policy()
    # Restrict policy to ONLY NOTIFY_OPERATOR
    restricted_policy = Policy(
        policy_id="pol_strict",
        organization_id="org_test",
        allowed_actions=[ActionType.NOTIFY_OPERATOR],  # MARK_FOR_REVIEW is not allowed
    )

    mark_review_json = """{
      "summary": "Motion observed at entrance.",
      "facts": ["Motion observed."],
      "unknowns": ["Unknown identity."],
      "context_match": "Match found.",
      "proposals": [
        {
          "action_type": "MARK_FOR_REVIEW",
          "reason": "Flag for routine review",
          "parameters": {
            "review_reason": "Routine activity check",
            "priority": "low"
          }
        }
      ]
    }"""

    res = AIValidationPipeline.validate(mark_review_json, ai_input, restricted_policy)
    assert res.is_valid is False
    assert res.error_stage == "POLICY_VALIDATION"
    assert "prohibited by tenant organization policy" in str(res.error_message)
