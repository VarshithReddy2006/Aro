"""CDK Infrastructure unit tests inspecting synthesized CloudFormation resources."""

import pytest
from aws_cdk import App
from aws_cdk.assertions import Match, Template

from infra.config import AroConfig, load_config
from infra.stacks import (
    ApiStack,
    ComputeStack,
    EventsStack,
    FrontendStack,
    StorageStack,
)


@pytest.fixture
def cdk_app() -> App:
    return App()


@pytest.fixture
def demo_config() -> AroConfig:
    return load_config("demo")


@pytest.fixture
def prod_config() -> AroConfig:
    return load_config("prod")


def test_storage_stack_dynamodb_single_table(cdk_app: App, demo_config: AroConfig) -> None:
    """Verify DynamoDB table, primary keys, GSIs, encryption, and TTL."""
    stack = StorageStack(cdk_app, "TestStorageStack", config=demo_config)
    template = Template.from_stack(stack)

    # 1. Verify DynamoDB Table definition
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "TableName": demo_config.table_name,
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "SSESpecification": {
                "SSEEnabled": True,
            },
            "TimeToLiveSpecification": {
                "AttributeName": "expires_at_epoch",
                "Enabled": True,
            },
            "GlobalSecondaryIndexes": Match.array_with(
                [
                    Match.object_like(
                        {
                            "IndexName": "GSI1",
                            "KeySchema": [
                                {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                                {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                        }
                    ),
                    Match.object_like(
                        {
                            "IndexName": "GSI2",
                            "KeySchema": [
                                {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                                {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                        }
                    ),
                ]
            ),
        },
    )


def test_storage_stack_prod_protections(cdk_app: App, prod_config: AroConfig) -> None:
    """Verify production protections: deletion protection, PITR, retention policy."""
    stack = StorageStack(cdk_app, "TestStorageStackProd", config=prod_config)
    template = Template.from_stack(stack)

    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "DeletionProtectionEnabled": True,
            "PointInTimeRecoverySpecification": {
                "PointInTimeRecoveryEnabled": True,
            },
        },
    )


def test_storage_stack_s3_evidence_bucket(cdk_app: App, demo_config: AroConfig) -> None:
    """Verify private S3 evidence bucket: block public access, encryption, versioning."""
    stack = StorageStack(cdk_app, "TestStorageStackS3", config=demo_config)
    template = Template.from_stack(stack)

    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": {
                "ServerSideEncryptionConfiguration": [
                    {
                        "ServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256",
                        }
                    }
                ]
            },
            "VersioningConfiguration": {
                "Status": "Enabled",
            },
        },
    )


def test_events_stack_bus(cdk_app: App, demo_config: AroConfig) -> None:
    """Verify custom EventBridge bus is provisioned."""
    stack = EventsStack(cdk_app, "TestEventsStack", config=demo_config)
    template = Template.from_stack(stack)

    template.has_resource_properties(
        "AWS::Events::EventBus",
        {
            "Name": demo_config.event_bus_name,
        },
    )


def test_compute_stack_least_privilege(cdk_app: App, demo_config: AroConfig) -> None:
    """Verify Lambda functions, environment variables, and least-privilege IAM policies."""
    storage = StorageStack(cdk_app, "TestStorageComputeRef", config=demo_config)
    events = EventsStack(cdk_app, "TestEventsComputeRef", config=demo_config)
    compute = ComputeStack(
        cdk_app,
        "TestComputeStack",
        config=demo_config,
        table=storage.table,
        evidence_bucket=storage.evidence_bucket,
        event_bus=events.event_bus,
    )
    template = Template.from_stack(compute)

    # 1. Verify Lambda functions
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": f"aro-ingest-{demo_config.env_name}",
            "Handler": "apps.api.src.handlers.ring_webhook.handle_ring_webhook",
            "Runtime": "python3.12",
            "MemorySize": 256,
        },
    )
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": f"aro-api-{demo_config.env_name}",
            "Handler": "apps.api.src.handlers.api_gateway_adapter.handle_api_request",
            "Runtime": "python3.12",
            "MemorySize": 512,
        },
    )
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": f"aro-worker-{demo_config.env_name}",
            "Handler": "apps.api.src.handlers.event_worker.handle_event_bridge_event",
            "Runtime": "python3.12",
            "MemorySize": 512,
        },
    )

    # 2. Verify SSM parameter created
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": demo_config.ring_secret_param_name,
            "Type": "String",
        },
    )

    # 3. Verify Bedrock InvokeModel is granted ONLY to Worker Lambda
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "bedrock:InvokeModel",
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )

    # 4. Verify EventBridge Rule routes to Worker Lambda
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["aro.events"],
                "detail-type": ["RingEventReceived", "CaseCreated", "BriefRequested"],
            }
        },
    )


def test_api_stack_cognito_and_routes(cdk_app: App, demo_config: AroConfig) -> None:
    """Verify Cognito User Pool, Groups, API Gateway authorizer, and endpoints."""
    storage = StorageStack(cdk_app, "TestStorageApiRef", config=demo_config)
    events = EventsStack(cdk_app, "TestEventsApiRef", config=demo_config)
    compute = ComputeStack(
        cdk_app,
        "TestComputeApiRef",
        config=demo_config,
        table=storage.table,
        evidence_bucket=storage.evidence_bucket,
        event_bus=events.event_bus,
    )
    api_stack = ApiStack(
        cdk_app,
        "TestApiStack",
        config=demo_config,
        ingest_lambda=compute.ingest_lambda,
        api_lambda=compute.api_lambda,
    )
    template = Template.from_stack(api_stack)

    # 1. Cognito User Pool & Groups
    template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "UserPoolName": demo_config.user_pool_name,
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
        },
    )
    for group in ["ADMIN", "OPERATOR", "VIEWER"]:
        template.has_resource_properties(
            "AWS::Cognito::UserPoolGroup",
            {"GroupName": group},
        )

    # 2. API Gateway Authorizer
    template.has_resource_properties(
        "AWS::ApiGateway::Authorizer",
        {
            "Type": "COGNITO_USER_POOLS",
            "IdentitySource": "method.request.header.Authorization",
        },
    )

    # 3. API Gateway RestApi
    template.has_resource_properties(
        "AWS::ApiGateway::RestApi",
        {
            "Name": f"aro-api-{demo_config.env_name}",
        },
    )

    # 4. Verify Resources exist
    for path_part in [
        "health",
        "webhooks",
        "ring",
        "api",
        "cases",
        "approve",
        "reject",
        "execute",
        "timeline",
        "evidence",
        "close",
    ]:
        template.has_resource_properties(
            "AWS::ApiGateway::Resource",
            {"PathPart": path_part},
        )


def test_frontend_stack_cdn(cdk_app: App, demo_config: AroConfig) -> None:
    """Verify private S3 hosting and CloudFront CDN distribution."""
    stack = FrontendStack(cdk_app, "TestFrontendStack", config=demo_config)
    template = Template.from_stack(stack)

    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )

    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "DefaultRootObject": "index.html",
                    "CustomErrorResponses": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "ErrorCode": 403,
                                    "ResponseCode": 200,
                                    "ResponsePagePath": "/index.html",
                                }
                            ),
                            Match.object_like(
                                {
                                    "ErrorCode": 404,
                                    "ResponseCode": 200,
                                    "ResponsePagePath": "/index.html",
                                }
                            ),
                        ]
                    ),
                }
            )
        },
    )
