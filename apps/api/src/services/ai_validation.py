"""Multi-stage AI validation pipeline.

Strictly validates untrusted model outputs through three progressive stages:
1. Schema Validation: Strict JSON and Pydantic validation (AIBriefOutput).
2. Factual & Terminology Guardrails: Enforces zero-fabrication and Ring terminology invariants.
3. Policy & Proposal Validation: Enforces allowlisted actions, strict parameter schemas,
   and organization policy constraints.
"""

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from packages.contracts.enums import ActionType
from packages.contracts.models import (
    AIBriefInput,
    AIBriefOutput,
    MarkForReviewParameters,
    NotifyOperatorParameters,
    Policy,
    Proposal,
    RecordNoActionParameters,
    RequestConfirmationParameters,
)

from ..utils.proposal_hash import calculate_proposal_hash

# Prohibited factual phrases that violate Ring observability boundaries
PROHIBITED_TERMS: list[str] = [
    "package detected",
    "package was delivered",
    "package delivered",
    "delivery confirmed",
    "courier identified",
    "person identified",
    "threat detected",
    "threat level",
    "intruder",
    "unlocked the door",
    "unlock door",
    "entered the facility",
    "gained entry",
    "verified delivery",
    "confirmed delivery",
]

# Injection phrases that must never pass validation
INJECTION_MARKERS: list[str] = [
    "ignore previous instructions",
    "system prompt",
    "disregard all previous",
    "dan mode",
]


@dataclass(frozen=True)
class AIValidationResult:
    """Outcome of multi-stage AI validation."""

    is_valid: bool
    brief_output: AIBriefOutput | None = None
    validated_proposals: list[Proposal] | None = None
    error_stage: str | None = None
    error_message: str | None = None


class AIValidationPipeline:
    """Deterministic validation pipeline for untrusted model responses."""

    @classmethod
    def validate(
        cls,
        raw_output_text: str,
        ai_input: AIBriefInput,
        policy: Policy,
    ) -> AIValidationResult:
        """Validate raw model text through all three security gates.

        Args:
            raw_output_text: Raw string emitted by Bedrock model.
            ai_input: Bounded context that was provided to the model.
            policy: Tenant organization policy.

        Returns:
            AIValidationResult with validated data structures or explicit failure reasons.
        """
        # ==========================================
        # STAGE 1: Schema Validation
        # ==========================================
        if not raw_output_text or not raw_output_text.strip():
            return AIValidationResult(
                is_valid=False,
                error_stage="SCHEMA_VALIDATION",
                error_message="Model returned empty or whitespace-only response",
            )

        # Extract JSON substring if wrapped in markdown code fence
        cleaned_text = raw_output_text.strip()
        if cleaned_text.startswith("```"):
            lines = cleaned_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned_text = "\n".join(lines).strip()

        try:
            parsed_json = json.loads(cleaned_text)
        except json.JSONDecodeError as exc:
            return AIValidationResult(
                is_valid=False,
                error_stage="SCHEMA_VALIDATION",
                error_message=f"Model output is not valid JSON: {exc}",
            )

        if not isinstance(parsed_json, dict):
            return AIValidationResult(
                is_valid=False,
                error_stage="SCHEMA_VALIDATION",
                error_message="Model output root must be a JSON object",
            )

        try:
            brief_output = AIBriefOutput.model_validate(parsed_json)
        except ValidationError as exc:
            return AIValidationResult(
                is_valid=False,
                error_stage="SCHEMA_VALIDATION",
                error_message=f"Schema validation failed: {exc}",
            )

        # ==========================================
        # STAGE 2: Factual & Terminology Guardrails
        # ==========================================
        full_text_to_check = (
            f"{brief_output.summary} "
            f"{' '.join(brief_output.facts)} "
            f"{' '.join(brief_output.unknowns)} "
            f"{brief_output.context_match}"
        ).lower()

        # Check prohibited Ring claims
        for term in PROHIBITED_TERMS:
            if term in full_text_to_check:
                return AIValidationResult(
                    is_valid=False,
                    error_stage="FACTUAL_VALIDATION",
                    error_message=(
                        f"Prohibited claim detected: '{term}'. "
                        "Ring data only observes motion/doorbell activity; "
                        "package/delivery/identity claims are prohibited."
                    ),
                )

        # Check prompt injection markers
        for injection in INJECTION_MARKERS:
            if injection in full_text_to_check:
                return AIValidationResult(
                    is_valid=False,
                    error_stage="FACTUAL_VALIDATION",
                    error_message=f"Prompt injection artifact detected: '{injection}'",
                )

        # Check delivery contradiction: if context says no expected delivery,
        # model must not claim an expected delivery match
        exp_status = ai_input.expected_delivery.get("status")
        if exp_status in ("FALSE", "UNKNOWN"):
            for fact in brief_output.facts:
                if re.search(r"\b(expected delivery found|delivery was expected)\b", fact.lower()):
                    return AIValidationResult(
                        is_valid=False,
                        error_stage="FACTUAL_VALIDATION",
                        error_message=(
                            f"Contradictory delivery claim: context status is {exp_status}, "
                            f"but model asserted '{fact}'."
                        ),
                    )

        # ==========================================
        # STAGE 3: Policy & Proposal Validation
        # ==========================================
        validated_proposals: list[Proposal] = []

        for proposed in brief_output.proposals:
            action_type = proposed.action_type

            # Check 1: Allowed actions per policy
            if action_type not in policy.allowed_actions:
                return AIValidationResult(
                    is_valid=False,
                    error_stage="POLICY_VALIDATION",
                    error_message=(
                        f"Action type '{action_type.value}' is prohibited by tenant organization policy."
                    ),
                )

            # Check 2: Validate parameters per ActionType schema
            param_validation_err = cls._validate_parameters(action_type, proposed.parameters)
            if param_validation_err is not None:
                return AIValidationResult(
                    is_valid=False,
                    error_stage="POLICY_VALIDATION",
                    error_message=param_validation_err,
                )

            # Check 3: Calculate deterministic canonical proposal hash
            proposal_hash = calculate_proposal_hash(
                case_id=ai_input.case_id,
                action_type=action_type,
                reason=proposed.reason,
                parameters=proposed.parameters,
            )

            proposal = Proposal(
                proposal_id=f"prop_{uuid4().hex[:12]}",
                case_id=ai_input.case_id,
                action_type=action_type,
                reason=proposed.reason,
                parameters=proposed.parameters,
                proposal_hash=proposal_hash,
            )
            validated_proposals.append(proposal)

        return AIValidationResult(
            is_valid=True,
            brief_output=brief_output,
            validated_proposals=validated_proposals,
        )

    @staticmethod
    def _validate_parameters(action_type: ActionType, params: dict[str, Any]) -> str | None:
        """Validate proposal parameter dictionary against strict Pydantic parameter schema."""
        try:
            if action_type == ActionType.NOTIFY_OPERATOR:
                NotifyOperatorParameters.model_validate(params)
            elif action_type == ActionType.MARK_FOR_REVIEW:
                MarkForReviewParameters.model_validate(params)
            elif action_type == ActionType.REQUEST_OPERATOR_CONFIRMATION:
                RequestConfirmationParameters.model_validate(params)
            elif action_type == ActionType.RECORD_NO_ACTION:
                RecordNoActionParameters.model_validate(params)
            return None
        except ValidationError as exc:
            return f"Invalid parameters for action '{action_type.value}': {exc}"
