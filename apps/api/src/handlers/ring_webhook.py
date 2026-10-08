"""Ring webhook endpoint handler.

Thin adapter between AWS API Gateway / Lambda / HTTP runtime and EventIngestionService:
- Preserves exact raw request bytes required for HMAC-SHA256 signature verification.
- Decodes base64 payload when API Gateway passes binary/encoded content.
- Never exposes internal exceptions, secrets, or stack traces to clients.
- Returns fast acknowledgment without synchronous Bedrock AI calls.
"""

import base64
import binascii
import json
import logging
import os
from typing import Any

from ..repositories.in_memory import InMemoryEventRepository
from ..services.event_ingestion import EventIngestionService

logger = logging.getLogger("aro.ring_webhook_handler")


def _get_default_service() -> EventIngestionService:
    """Build a default ingestion service if none injected."""
    secret = os.environ.get("RING_WEBHOOK_SECRET", "default_insecure_test_secret")
    repo = InMemoryEventRepository()
    return EventIngestionService(event_repository=repo, webhook_secret=secret)


def handle_ring_webhook(
    event: dict[str, Any],
    context: Any = None,
    service: EventIngestionService | None = None,
) -> dict[str, Any]:
    """Handle incoming Ring webhook from AWS API Gateway Lambda proxy event.

    Args:
        event: API Gateway Lambda proxy event dictionary.
        context: Lambda execution context.
        service: Optional injected EventIngestionService instance.

    Returns:
        API Gateway proxy response with statusCode, headers, and body.
    """
    active_service = service or _get_default_service()

    try:
        # Extract headers (case-insensitive dictionary)
        raw_headers = event.get("headers") or {}

        # Extract raw body bytes
        raw_body_content = event.get("body", "")
        is_b64 = event.get("isBase64Encoded", False)

        if isinstance(raw_body_content, bytes):
            raw_bytes = raw_body_content
        elif is_b64:
            try:
                raw_bytes = base64.b64decode(raw_body_content)
            except (binascii.Error, ValueError):
                return {
                    "statusCode": 400,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(
                        {
                            "error": "INVALID_ENCODING",
                            "message": "Failed to decode base64 body",
                        }
                    ),
                }
        else:
            raw_bytes = str(raw_body_content).encode("utf-8")

        # Ingest through domain service pipeline
        client_ip = event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        result = active_service.ingest(
            raw_body=raw_bytes,
            headers=raw_headers,
            client_ip=client_ip,
        )

        return {
            "statusCode": result.status_code,
            "headers": {
                "Content-Type": "application/json",
                "X-Content-Type-Options": "nosniff",
            },
            "body": json.dumps(result.response_data),
        }

    except Exception as exc:
        logger.exception("Unexpected error processing Ring webhook: %s", type(exc).__name__)
        # Sanitize output: never return internal traceback or secret info
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "X-Content-Type-Options": "nosniff",
            },
            "body": json.dumps(
                {
                    "error": "INTERNAL_SERVER_ERROR",
                    "message": "A transient internal error occurred while processing the webhook",
                }
            ),
        }


# Optional FastAPI / ASGI Router integration
try:
    from fastapi import APIRouter, Request, Response

    router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

    @router.post("/ring")
    async def post_ring_webhook(request: Request) -> Response:
        """FastAPI route adapter for Ring webhook."""
        body_bytes = await request.body()
        headers = dict(request.headers)
        client_ip = request.client.host if request.client else None

        active_service = _get_default_service()
        result = active_service.ingest(
            raw_body=body_bytes,
            headers=headers,
            client_ip=client_ip,
        )

        return Response(
            content=json.dumps(result.response_data),
            status_code=result.status_code,
            media_type="application/json",
            headers={"X-Content-Type-Options": "nosniff"},
        )

except ImportError:
    pass
