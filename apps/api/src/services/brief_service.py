"""Orchestration service for case context assembly and bounded brief generation.

Integrates:
- CaseContextBuilder (Deterministic context assembly)
- BriefGenerator (Bedrock primary or Fallback generator)
- AIValidationPipeline (Multi-stage schema, factual, and policy validation)
- Proposal Hashing (Deterministic SHA-256 proposal binding)
- Observability and Metrics
"""

import logging
from dataclasses import dataclass
from uuid import uuid4

from packages.contracts.models import CaseBrief, Proposal

from ..repositories.interfaces import CaseRepository
from .ai_validation import AIValidationPipeline, AIValidationResult
from .bedrock_adapter import BedrockBriefGenerator, BriefGenerator, FallbackBriefGenerator
from .case_context_builder import CaseContextBuilder, CaseContextBundle
from .metrics import IngestionMetrics

logger = logging.getLogger("aro.brief_service")


@dataclass(frozen=True)
class BriefGenerationResult:
    """Outcome of brief generation and validation."""

    brief: CaseBrief
    proposals: list[Proposal]
    context_bundle: CaseContextBundle
    is_fallback: bool
    validation_result: AIValidationResult


class BriefService:
    """Production service orchestrating bounded brief generation and proposals."""

    def __init__(
        self,
        context_builder: CaseContextBuilder,
        case_repository: CaseRepository,
        primary_generator: BriefGenerator | None = None,
        fallback_generator: BriefGenerator | None = None,
        metrics: IngestionMetrics | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.case_repo = case_repository
        self.primary_generator = primary_generator or BedrockBriefGenerator()
        self.fallback_generator = fallback_generator or FallbackBriefGenerator()
        self.metrics = metrics or IngestionMetrics()

    def generate_brief_for_case(
        self,
        case_id: str,
        organization_id: str,
        force_fallback: bool = False,
    ) -> BriefGenerationResult:
        """Assemble context, execute bounded generation, validate, and store proposal.

        Args:
            case_id: Target operational case identifier.
            organization_id: Authenticated tenant organization identifier.
            force_fallback: When True, bypasses Bedrock and uses deterministic fallback.

        Returns:
            BriefGenerationResult containing validated brief, proposals, and context.
        """
        # Step 1: Assemble deterministic case context
        try:
            bundle = self.context_builder.build_context(
                case_id=case_id,
                organization_id=organization_id,
            )
        except Exception:
            logger.exception("Failed to assemble case context for case %s", case_id)
            raise

        validation_result: AIValidationResult | None = None
        is_fallback = False

        # Step 2: Attempt primary Bedrock generation unless forced to fallback
        if not force_fallback:
            try:
                raw_text = self.primary_generator.generate_raw_brief(bundle.ai_input)
                validation_result = AIValidationPipeline.validate(
                    raw_output_text=raw_text,
                    ai_input=bundle.ai_input,
                    policy=bundle.policy,
                )
                if not validation_result.is_valid:
                    logger.warning(
                        "AI response for case %s failed validation at stage %s: %s. Switching to fallback.",
                        case_id,
                        validation_result.error_stage,
                        validation_result.error_message,
                    )
            except (RuntimeError, TimeoutError, ValueError, ConnectionError, OSError) as exc:
                logger.warning(
                    "Bedrock invocation failed for case %s: %s. Switching to fallback.",
                    case_id,
                    exc,
                )

        # Step 3: Execute deterministic fallback if primary failed or was bypassed
        if validation_result is None or not validation_result.is_valid:
            is_fallback = True
            fallback_text = self.fallback_generator.generate_raw_brief(bundle.ai_input)
            validation_result = AIValidationPipeline.validate(
                raw_output_text=fallback_text,
                ai_input=bundle.ai_input,
                policy=bundle.policy,
            )

        if not validation_result.is_valid or validation_result.brief_output is None:
            # Fatal safety error: even fallback failed validation (should never happen)
            raise RuntimeError(
                f"Validation pipeline completely rejected brief: {validation_result.error_message}"
            )

        brief_data = validation_result.brief_output
        proposals = validation_result.validated_proposals or []

        # Step 4: Construct canonical CaseBrief
        brief = CaseBrief(
            brief_id=f"brief_{uuid4().hex[:12]}",
            case_id=case_id,
            summary=brief_data.summary,
            facts=brief_data.facts,
            unknowns=brief_data.unknowns,
            context_match=brief_data.context_match,
            is_fallback=is_fallback,
        )

        # Step 5: Update Case metadata in repository
        case = self.case_repo.get_case(case_id=case_id, organization_id=organization_id)
        updated_case = case.model_copy(
            update={
                "brief_id": brief.brief_id,
                "active_proposal_id": proposals[0].proposal_id if proposals else None,
            }
        )
        self.case_repo.update_case(
            case=updated_case,
            organization_id=organization_id,
            expected_version=case.version,
        )

        return BriefGenerationResult(
            brief=brief,
            proposals=proposals,
            context_bundle=bundle,
            is_fallback=is_fallback,
            validation_result=validation_result,
        )
