"""Bedrock AI adapter and deterministic fallback generator.

Isolates all AWS Bedrock calls behind a clean protocol:
- One bounded AI call for the MVP.
- Strictly no autonomous agent loops, tool executions, or multi-agent swarms.
- Configurable model ID, region, timeout, and token bounds.
- Deterministic FallbackBriefGenerator guarantees offline resilience and auditability.
"""

import json
import logging
import os
from typing import Any, Protocol

from packages.contracts.enums import ActionType
from packages.contracts.models import AIBriefInput

logger = logging.getLogger("aro.bedrock_adapter")

SYSTEM_PROMPT_V1 = """You are Aro's bounded operational brief generator.
Your task is to transform structured physical event context into a factual, concise operational brief and allowlisted action proposal.

CRITICAL SECURITY AND FACTUAL INVARIANTS:
1. Rely ONLY on the provided context. Never invent facts, courier identities, or events.
2. Ring observes motion and doorbell activity ONLY. NEVER claim or assert that a package was detected, a delivery was confirmed, or an individual was identified.
3. Explicitly distinguish KNOWN facts from UNKNOWNS.
4. Propose actions ONLY from the allowed_actions list provided in the input. Never invent action types (e.g., do NOT propose UNLOCK_DOOR).
5. For parameters, include only validated fields:
   - For NOTIFY_OPERATOR: message, urgency ("low"|"normal"|"high"|"urgent"), recipient_role ("OPERATOR"|"ADMIN")
   - For MARK_FOR_REVIEW: review_reason, priority ("low"|"medium"|"high")
   - For REQUEST_OPERATOR_CONFIRMATION: confirmation_type, target_role ("OPERATOR")
   - For RECORD_NO_ACTION: rationale
6. Return STRICT valid JSON conforming exactly to the schema:
{
  "summary": "...",
  "facts": ["..."],
  "unknowns": ["..."],
  "context_match": "...",
  "proposals": [
    {
      "action_type": "...",
      "reason": "...",
      "parameters": {}
    }
  ]
}
No conversational prose or markdown formatting outside the JSON object.
"""


class BriefGenerator(Protocol):
    """Protocol for generating brief text from structured context."""

    def generate_raw_brief(self, ai_input: AIBriefInput) -> str:
        """Transform structured context into JSON brief response."""
        ...


class FallbackBriefGenerator:
    """Deterministic, offline brief generator used as fallback or baseline."""

    def generate_raw_brief(self, ai_input: AIBriefInput) -> str:
        """Produce deterministic, factual brief matching AIBriefOutput schema."""
        event_count = len(ai_input.events)
        door_info = (
            "designated entrance"
            if ai_input.business_context.get("designated_entrance")
            else "monitored door"
        )
        hours_info = (
            "outside standard business hours"
            if ai_input.business_context.get("is_after_hours")
            else "during standard operating hours"
        )
        deliv_status = ai_input.expected_delivery.get("status", "UNKNOWN")

        summary = (
            f"Physical event activity observed at {door_info} {hours_info} "
            f"across {event_count} recorded event(s). Expected delivery status: {deliv_status}."
        )

        # Select allowlisted proposal based on deterministic context
        allowed = ai_input.allowed_actions
        if (
            ActionType.NOTIFY_OPERATOR in allowed
            and ai_input.business_context.get("is_after_hours")
            and deliv_status != "TRUE"
        ):
            proposals = [
                {
                    "action_type": ActionType.NOTIFY_OPERATOR.value,
                    "reason": "After-hours activity observed at entrance with no confirmed matching delivery.",
                    "parameters": {
                        "message": "After-hours activity observed at entrance requiring operator review",
                        "urgency": "normal",
                        "recipient_role": "OPERATOR",
                    },
                }
            ]
        elif ActionType.MARK_FOR_REVIEW in allowed:
            proposals = [
                {
                    "action_type": ActionType.MARK_FOR_REVIEW.value,
                    "reason": "Operational review recommended based on facility schedule.",
                    "parameters": {
                        "review_reason": "Logged activity flagged for routine operator review",
                        "priority": "medium",
                    },
                }
            ]
        elif ActionType.RECORD_NO_ACTION in allowed:
            proposals = [
                {
                    "action_type": ActionType.RECORD_NO_ACTION.value,
                    "reason": "Event within expected parameters; no intervention required.",
                    "parameters": {
                        "rationale": "Activity recorded during regular schedule",
                    },
                }
            ]
        else:
            proposals = [
                {
                    "action_type": allowed[0].value
                    if allowed
                    else ActionType.RECORD_NO_ACTION.value,
                    "reason": "Default policy action.",
                    "parameters": {"rationale": "Fallback policy default"},
                }
            ]

        fallback_payload = {
            "summary": summary,
            "facts": ai_input.known_facts,
            "unknowns": ai_input.unknowns,
            "context_match": f"Deterministic schedule match: after_hours={ai_input.business_context.get('is_after_hours')}, delivery={deliv_status}",
            "proposals": proposals,
        }

        return json.dumps(fallback_payload, indent=2)


class BedrockBriefGenerator:
    """Bounded AWS Bedrock client adapter."""

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
        timeout_seconds: int = 10,
        max_tokens: int = 1024,
        client: Any = None,
    ) -> None:
        self.model_id = model_id or os.environ.get(
            "BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
        )
        self.region = region or os.environ.get("BEDROCK_REGION", "us-east-1")
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3
        from botocore.config import Config

        config = Config(
            region_name=self.region,
            connect_timeout=self.timeout_seconds,
            read_timeout=self.timeout_seconds,
            retries={"max_attempts": 2},
        )
        self._client = boto3.client("bedrock-runtime", config=config)
        return self._client

    def generate_raw_brief(self, ai_input: AIBriefInput) -> str:
        """Invoke bounded Bedrock model and retrieve raw JSON string response.

        Args:
            ai_input: Sanitized structured context.

        Returns:
            Raw response text from model.

        Raises:
            Exception: On Bedrock invocation or communication failure.
        """
        client = self._get_client()

        # Format input payload for Claude 3 Messages format
        input_json_str = ai_input.model_dump_json(indent=2)
        messages = [
            {
                "role": "user",
                "content": (
                    f"Operational Case Context:\n{input_json_str}\n\n"
                    "Generate the JSON brief and proposals strictly adhering to the schema."
                ),
            }
        ]

        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self.max_tokens,
                "system": SYSTEM_PROMPT_V1,
                "messages": messages,
                "temperature": 0.0,  # Zero temperature for deterministic adherence
            }
        )

        logger.info(
            "Invoking Bedrock model %s for case %s (timeout=%ds)",
            self.model_id,
            ai_input.case_id,
            self.timeout_seconds,
        )

        response = client.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )

        response_body = json.loads(response["body"].read().decode("utf-8"))
        # Extract content text from Anthropic response structure
        content_blocks = response_body.get("content", [])
        if content_blocks and isinstance(content_blocks, list):
            text = content_blocks[0].get("text", "")
            return text.strip()

        raise RuntimeError("Bedrock response did not contain expected text content block")
