"""Ring webhook endpoint handler.

Thin adapter between AWS API Gateway / Lambda / HTTP runtime and EventIngestionService:
- Preserves exact raw request bytes required for HMAC-SHA256 signature verification.
- Decodes base64 payload when API Gateway passes binary/encoded content.
- Never exposes internal exceptions, secrets, or stack traces to clients.
- Returns fast acknowledgment without synchronous Bedrock AI calls.
- Emits RingEventReceived event to EventBridge upon valid ingestion.
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

_cached_secret: str | None = None


def _reset_cached_secret() -> None:
    """Clear cached secret for test isolation."""
    global _cached_secret
    _cached_secret = None


def _resolve_webhook_secret() -> str:
    """Resolve Ring secret from environment or SSM Parameter Store with strict env fail-closed policy."""
    global _cached_secret
    if _cached_secret:
        return _cached_secret

    env = os.environ.get("ARO_ENV", "demo").strip().lower()
    is_demo = env in {"demo", "local", "test"}

    if is_demo:
        secret = os.environ.get("RING_WEBHOOK_SECRET")
        if secret:
            _cached_secret = secret
            return secret

        param_name = os.environ.get("RING_SECRET_PARAM")
        if param_name:
            try:
                import boto3

                ssm = boto3.client("ssm")
                resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
                param_val = resp.get("Parameter", {}).get("Value")
                if param_val:
                    _cached_secret = param_val
                    return param_val
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not load Ring secret from SSM parameter %s in demo mode: %s",
                    param_name,
                    exc,
                )

        return "default_insecure_test_secret"

    # In dev/prod: SSM parameter resolution is mandatory and fails closed
    param_name = os.environ.get("RING_SECRET_PARAM") or f"/aro/{env}/ring/webhook-secret"
    try:
        import boto3

        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
        param_val = resp.get("Parameter", {}).get("Value")
        if not param_val or not param_val.strip():
            logger.error(
                "Empty secret retrieved from SSM parameter %s in %s environment", param_name, env
            )
            raise RuntimeError(
                f"SSM parameter {param_name} for Ring webhook secret is empty in {env}"
            )
        _cached_secret = param_val
        return param_val
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        logger.error(
            "Failed to load mandatory Ring webhook secret from SSM parameter %s in %s environment: %s",
            param_name,
            env,
            exc,
        )
        raise RuntimeError(
            f"Failed to load mandatory Ring secret from SSM parameter {param_name} in {env}"
        ) from exc


def _emit_eventbridge_notification(event_id: str, request_id: str | None) -> None:
    """Emit asynchronous notification to EventBridge bus if configured."""
    bus_name = os.environ.get("ARO_EVENT_BUS_NAME")
    if not bus_name:
        return
    try:
        import boto3

        events_client = boto3.client("events")
        detail = {
            "event_id": event_id,
            "request_id": request_id,
            "source": "aro.ingest",
        }
        resp = events_client.put_events(
            Entries=[
                {
                    "EventBusName": bus_name,
                    "Source": "aro.events",
                    "DetailType": "RingEventReceived",
                    "Detail": json.dumps(detail),
                }
            ]
        )
        failed_count = resp.get("FailedEntryCount", 0)
        if failed_count > 0:
            entries = resp.get("Entries", [])
            for entry in entries:
                if "ErrorCode" in entry:
                    logger.error(
                        "EventBridge put_events entry failed for event %s: code=%s, message=%s",
                        event_id,
                        entry.get("ErrorCode"),
                        entry.get("ErrorMessage"),
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to emit EventBridge notification for event %s: %s", event_id, exc)


def _get_default_service() -> EventIngestionService:
    """Build a default ingestion service enforcing persistence requirements by environment."""
    secret = _resolve_webhook_secret()
    env = os.environ.get("ARO_ENV", "demo").strip().lower()
    table_name = os.environ.get("ARO_TABLE_NAME")

    if env in {"demo", "local", "test"}:
        if table_name:
            try:
                import boto3

                from ..repositories.dynamodb import DynamoDBEventRepository

                table = boto3.resource("dynamodb").Table(table_name)
                repo = DynamoDBEventRepository(table)  # type: ignore[assignment]
                return EventIngestionService(event_repository=repo, webhook_secret=secret)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not connect to DynamoDB table %s in demo mode: %s", table_name, exc
                )

        repo = InMemoryEventRepository()  # type: ignore[assignment]
        return EventIngestionService(event_repository=repo, webhook_secret=secret)

    # dev / prod: MUST fail closed on DynamoDB
    if not table_name:
        logger.error("Missing required environment variable ARO_TABLE_NAME in %s environment", env)
        raise RuntimeError(
            f"DynamoDB table name (ARO_TABLE_NAME) not configured in {env} environment"
        )

    try:
        import boto3

        from ..repositories.dynamodb import DynamoDBEventRepository

        table = boto3.resource("dynamodb").Table(table_name)
        repo = DynamoDBEventRepository(table)  # type: ignore[assignment]
        return EventIngestionService(event_repository=repo, webhook_secret=secret)
    except Exception as exc:
        logger.error("Could not connect to DynamoDB table in %s environment: %s", env, exc)
        raise RuntimeError(f"DynamoDB initialization failed in {env} environment: {exc}") from exc


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

        # Asynchronously notify downstream processing on successful non-duplicate ingestion
        if result.status_code == 200 and result.event_id and not result.duplicate:
            _emit_eventbridge_notification(result.event_id, result.request_id)

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
