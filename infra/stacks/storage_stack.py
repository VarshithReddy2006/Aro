"""Storage stack provisioning DynamoDB single-table and private S3 evidence bucket."""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import Construct

from ..config import AroConfig


class StorageStack(Stack):
    """Storage resources for operational data persistence and evidence archiving."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: AroConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        # -------------------------------------------------------------
        # 1. DynamoDB Single-Table Design
        # -------------------------------------------------------------
        removal_policy = RemovalPolicy.RETAIN if config.retain_on_delete else RemovalPolicy.DESTROY

        self.table = dynamodb.Table(
            self,
            "AroCoreTable",
            table_name=config.table_name,
            partition_key=dynamodb.Attribute(
                name="PK",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="SK",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            time_to_live_attribute="expires_at_epoch",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=config.point_in_time_recovery
            ),
            deletion_protection=config.deletion_protection,
            removal_policy=removal_policy,
        )

        # GSI1: Organization-wide case listings and tracking lookups
        self.table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI2: Status and location filtered case queries
        self.table.add_global_secondary_index(
            index_name="GSI2",
            partition_key=dynamodb.Attribute(
                name="GSI2PK",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="GSI2SK",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # -------------------------------------------------------------
        # 2. Private S3 Evidence Bucket
        # -------------------------------------------------------------
        bucket_props: dict[str, object] = {
            "block_public_access": s3.BlockPublicAccess.BLOCK_ALL,
            "encryption": s3.BucketEncryption.S3_MANAGED,
            "enforce_ssl": True,
            "versioned": True,
            "removal_policy": removal_policy,
            "auto_delete_objects": not config.retain_on_delete,
            "lifecycle_rules": [
                s3.LifecycleRule(
                    id="TransitionAndExpireNoncurrentVersions",
                    enabled=True,
                    noncurrent_version_transitions=[
                        s3.NoncurrentVersionTransition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        )
                    ],
                    noncurrent_version_expiration=Duration.days(90),
                )
            ],
        }

        if config.evidence_bucket_name:
            bucket_props["bucket_name"] = config.evidence_bucket_name

        self.evidence_bucket = s3.Bucket(
            self,
            "AroEvidenceBucket",
            **bucket_props,
        )
