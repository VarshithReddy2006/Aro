"""Compute stack provisioning least-privilege Lambda functions and SSM configuration."""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as _lambda,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_ssm as ssm,
)
from constructs import Construct

from ..config import AroConfig


class ComputeStack(Stack):
    """Serverless compute resources implementing least-privilege operational workflows."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: AroConfig,
        table: dynamodb.Table,
        evidence_bucket: s3.Bucket,
        event_bus: events.EventBus,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        log_retention = (
            logs.RetentionDays.ONE_MONTH if config.is_prod else logs.RetentionDays.ONE_WEEK
        )
        removal_policy = RemovalPolicy.RETAIN if config.retain_on_delete else RemovalPolicy.DESTROY

        # -------------------------------------------------------------
        # 1. SSM Parameter for Ring Webhook Secret
        # -------------------------------------------------------------
        self.ring_secret_param = ssm.StringParameter(
            self,
            "RingWebhookSecretParam",
            parameter_name=config.ring_secret_param_name,
            string_value="aro-ring-webhook-secret-placeholder",
            description="HMAC SHA-256 verification secret for public Ring webhook ingress",
        )

        # Common Lambda bundling / asset directory
        code_asset = _lambda.Code.from_asset(
            ".",
            exclude=[
                "cdk.out",
                ".git",
                ".github",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                "apps/web/node_modules",
                "apps/web/dist",
                "docs",
                "tests",
            ],
        )

        # -------------------------------------------------------------
        # 2. Ingest Lambda (Webhook Ingress & HMAC Guard)
        # -------------------------------------------------------------
        ingest_log_group = logs.LogGroup(
            self,
            "IngestLogGroup",
            log_group_name=f"/aws/lambda/aro-ingest-{config.env_name}",
            retention=log_retention,
            removal_policy=removal_policy,
        )

        self.ingest_lambda = _lambda.Function(
            self,
            "IngestFunction",
            function_name=f"aro-ingest-{config.env_name}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="apps.api.src.handlers.ring_webhook.handle_ring_webhook",
            code=code_asset,
            memory_size=256,
            timeout=Duration.seconds(10),
            log_group=ingest_log_group,
            environment={
                "ARO_ENV": config.env_name,
                "ARO_TABLE_NAME": table.table_name,
                "ARO_EVENT_BUS_NAME": event_bus.event_bus_name,
                "RING_SECRET_PARAM": self.ring_secret_param.parameter_name,
                "LOG_LEVEL": config.log_level,
            },
        )
        table.grant_read_write_data(self.ingest_lambda)
        event_bus.grant_put_events_to(self.ingest_lambda)
        self.ring_secret_param.grant_read(self.ingest_lambda)

        # -------------------------------------------------------------
        # 3. API Lambda (Core Operations & Deterministic Execution)
        # -------------------------------------------------------------
        api_log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            log_group_name=f"/aws/lambda/aro-api-{config.env_name}",
            retention=log_retention,
            removal_policy=removal_policy,
        )

        self.api_lambda = _lambda.Function(
            self,
            "ApiFunction",
            function_name=f"aro-api-{config.env_name}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="apps.api.src.handlers.api_gateway_adapter.handle_api_request",
            code=code_asset,
            memory_size=512,
            timeout=Duration.seconds(15),
            log_group=api_log_group,
            environment={
                "ARO_ENV": config.env_name,
                "ARO_TABLE_NAME": table.table_name,
                "ARO_EVIDENCE_BUCKET": evidence_bucket.bucket_name,
                "ARO_EVENT_BUS_NAME": event_bus.event_bus_name,
                "ARO_CORS_ORIGINS": ",".join(config.cors_allowed_origins),
                "LOG_LEVEL": config.log_level,
            },
        )
        table.grant_read_write_data(self.api_lambda)
        evidence_bucket.grant_read(self.api_lambda)
        event_bus.grant_put_events_to(self.api_lambda)

        # -------------------------------------------------------------
        # 4. Worker Lambda (EventBridge Consumer & Bounded Bedrock AI)
        # -------------------------------------------------------------
        worker_log_group = logs.LogGroup(
            self,
            "WorkerLogGroup",
            log_group_name=f"/aws/lambda/aro-worker-{config.env_name}",
            retention=log_retention,
            removal_policy=removal_policy,
        )

        self.worker_lambda = _lambda.Function(
            self,
            "WorkerFunction",
            function_name=f"aro-worker-{config.env_name}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="apps.api.src.handlers.event_worker.handle_event_bridge_event",
            code=code_asset,
            memory_size=512,
            timeout=Duration.seconds(30),
            log_group=worker_log_group,
            environment={
                "ARO_ENV": config.env_name,
                "ARO_TABLE_NAME": table.table_name,
                "ARO_EVIDENCE_BUCKET": evidence_bucket.bucket_name,
                "ARO_EVENT_BUS_NAME": event_bus.event_bus_name,
                "BEDROCK_MODEL_ID": config.bedrock_model_id,
                "LOG_LEVEL": config.log_level,
            },
        )
        table.grant_read_write_data(self.worker_lambda)
        evidence_bucket.grant_read_write(self.worker_lambda)
        event_bus.grant_put_events_to(self.worker_lambda)

        # Scoped Bedrock Invoke permission: only worker lambda has Bedrock access
        self.worker_lambda.add_to_role_policy(
            iam.PolicyStatement(
                sid="ScopedBedrockInvoke",
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{config.bedrock_model_id}",
                    f"arn:aws:bedrock:{self.region}::foundation-model/*",
                ],
            )
        )

        # -------------------------------------------------------------
        # 5. EventBridge Rule Routing to Worker Lambda
        # -------------------------------------------------------------
        self.worker_rule = events.Rule(
            self,
            "AroWorkerRule",
            event_bus=event_bus,
            event_pattern=events.EventPattern(
                source=["aro.events"],
                detail_type=["RingEventReceived", "CaseCreated", "BriefRequested"],
            ),
        )
        self.worker_rule.add_target(targets.LambdaFunction(self.worker_lambda))
