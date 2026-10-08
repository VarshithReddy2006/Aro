"""Environment-aware configuration for Aro AWS infrastructure."""

import os
from dataclasses import dataclass, field
from typing import Literal

EnvironmentType = Literal["demo", "dev", "prod"]


@dataclass(frozen=True)
class AroConfig:
    """Infrastructure configuration settings scoped per deployment target."""

    env_name: EnvironmentType = "demo"
    region: str = "us-east-1"
    account: str | None = None
    table_name: str = "aro-core-table"
    evidence_bucket_name: str | None = None
    event_bus_name: str = "aro-events-bus"
    user_pool_name: str = "aro-users-pool"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    ring_secret_param_name: str = "/aro/demo/ring/webhook-secret"
    cors_allowed_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )
    deletion_protection: bool = False
    point_in_time_recovery: bool = False
    retain_on_delete: bool = False
    log_retention_days: int = 7
    log_level: str = "INFO"

    @property
    def is_prod(self) -> bool:
        return self.env_name == "prod"


def load_config(env_override: str | None = None) -> AroConfig:
    """Load and validate infrastructure configuration from environment variables."""
    raw_env = (env_override or os.environ.get("ARO_ENV", "demo")).strip().lower()
    if raw_env not in {"demo", "dev", "prod"}:
        raw_env = "demo"

    env_name: EnvironmentType = raw_env  # type: ignore[assignment]
    region = os.environ.get("AWS_REGION", os.environ.get("CDK_DEFAULT_REGION", "us-east-1"))
    account = os.environ.get("AWS_ACCOUNT_ID", os.environ.get("CDK_DEFAULT_ACCOUNT"))

    if env_name == "prod":
        # Production defaults strictly enforce retention and protection
        table_name = os.environ.get("ARO_TABLE_NAME", "aro-core-table-prod")
        bucket_name = os.environ.get("ARO_EVIDENCE_BUCKET")
        event_bus = os.environ.get("ARO_EVENT_BUS_NAME", "aro-events-prod")
        user_pool = os.environ.get("ARO_USER_POOL_NAME", "aro-users-prod")
        secret_param = os.environ.get("ARO_RING_SECRET_PARAM", "/aro/prod/ring/webhook-secret")
        cors_origins_env = os.environ.get("ARO_CORS_ORIGINS")
        cors_origins = (
            [o.strip() for o in cors_origins_env.split(",") if o.strip()]
            if cors_origins_env
            else ["https://aro.acme-facility.com"]
        )

        return AroConfig(
            env_name="prod",
            region=region,
            account=account,
            table_name=table_name,
            evidence_bucket_name=bucket_name,
            event_bus_name=event_bus,
            user_pool_name=user_pool,
            bedrock_model_id=os.environ.get(
                "ARO_BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
            ),
            ring_secret_param_name=secret_param,
            cors_allowed_origins=cors_origins,
            deletion_protection=True,
            point_in_time_recovery=True,
            retain_on_delete=True,
            log_retention_days=30,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )

    # Dev / Demo environment configuration
    prefix = f"aro-{env_name}"
    table_name = os.environ.get("ARO_TABLE_NAME", f"{prefix}-table")
    bucket_name = os.environ.get("ARO_EVIDENCE_BUCKET")
    event_bus = os.environ.get("ARO_EVENT_BUS_NAME", f"{prefix}-bus")
    user_pool = os.environ.get("ARO_USER_POOL_NAME", f"{prefix}-users")
    secret_param = os.environ.get("ARO_RING_SECRET_PARAM", f"/aro/{env_name}/ring/webhook-secret")
    cors_origins_env = os.environ.get("ARO_CORS_ORIGINS")
    cors_origins = (
        [o.strip() for o in cors_origins_env.split(",") if o.strip()]
        if cors_origins_env
        else ["http://localhost:5173", "http://localhost:3000"]
    )

    return AroConfig(
        env_name=env_name,
        region=region,
        account=account,
        table_name=table_name,
        evidence_bucket_name=bucket_name,
        event_bus_name=event_bus,
        user_pool_name=user_pool,
        bedrock_model_id=os.environ.get(
            "ARO_BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
        ),
        ring_secret_param_name=secret_param,
        cors_allowed_origins=cors_origins,
        deletion_protection=False,
        point_in_time_recovery=False,
        retain_on_delete=False,
        log_retention_days=7,
        log_level=os.environ.get("LOG_LEVEL", "DEBUG" if env_name == "demo" else "INFO"),
    )
