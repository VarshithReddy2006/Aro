#!/usr/bin/env python3
"""Aro CDK application entrypoint."""

import os
import sys

# Ensure project root is in python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from aws_cdk import App, Tags

from infra.config import load_config
from infra.stacks import (
    ApiStack,
    ComputeStack,
    EventsStack,
    FrontendStack,
    StorageStack,
)


def main() -> None:
    app = App()
    config = load_config()

    env_tags = {
        "Project": "Aro",
        "Environment": config.env_name,
        "ManagedBy": "AWS-CDK",
    }

    env_kwargs = {}
    if config.account and config.region:
        env_kwargs["env"] = {"account": config.account, "region": config.region}

    # 1. Storage: DynamoDB Single-Table + S3 Evidence Bucket
    storage_stack = StorageStack(
        app,
        f"AroStorage-{config.env_name}",
        config=config,
        description=f"Aro DynamoDB and S3 evidence storage ({config.env_name})",
        **env_kwargs,
    )

    # 2. Events: EventBridge Custom Bus
    events_stack = EventsStack(
        app,
        f"AroEvents-{config.env_name}",
        config=config,
        description=f"Aro EventBridge asynchronous event bus ({config.env_name})",
        **env_kwargs,
    )

    # 3. Compute: Ingest, API, and Worker Lambdas
    compute_stack = ComputeStack(
        app,
        f"AroCompute-{config.env_name}",
        config=config,
        table=storage_stack.table,
        evidence_bucket=storage_stack.evidence_bucket,
        event_bus=events_stack.event_bus,
        description=f"Aro serverless Lambdas and execution roles ({config.env_name})",
        **env_kwargs,
    )

    # 4. API & Auth: API Gateway RestApi + Cognito User Pool
    api_stack = ApiStack(
        app,
        f"AroApi-{config.env_name}",
        config=config,
        ingest_lambda=compute_stack.ingest_lambda,
        api_lambda=compute_stack.api_lambda,
        description=f"Aro API Gateway and Cognito authorizer ({config.env_name})",
        **env_kwargs,
    )

    # 5. Frontend: Private S3 + CloudFront Distribution
    frontend_stack = FrontendStack(
        app,
        f"AroFrontend-{config.env_name}",
        config=config,
        description=f"Aro React operator UI hosting ({config.env_name})",
        **env_kwargs,
    )

    # Tag all stacks consistently
    for stack in [storage_stack, events_stack, compute_stack, api_stack, frontend_stack]:
        for k, v in env_tags.items():
            Tags.of(stack).add(k, v)

    app.synth()


if __name__ == "__main__":
    main()
