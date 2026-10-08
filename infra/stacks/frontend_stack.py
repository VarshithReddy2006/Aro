"""Frontend deployment stack provisioning S3 and CloudFront for the Vite React SPA."""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as origins,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import Construct

from ..config import AroConfig


class FrontendStack(Stack):
    """Static web hosting stack for the Aro operator dashboard."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: AroConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        removal_policy = RemovalPolicy.RETAIN if config.retain_on_delete else RemovalPolicy.DESTROY

        # -------------------------------------------------------------
        # 1. Private S3 Bucket for Web Assets
        # -------------------------------------------------------------
        self.site_bucket = s3.Bucket(
            self,
            "AroSiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=config.is_prod,
            removal_policy=removal_policy,
            auto_delete_objects=not config.retain_on_delete,
        )

        # -------------------------------------------------------------
        # 2. CloudFront CDN Distribution with SPA Fallback
        # -------------------------------------------------------------
        self.distribution = cloudfront.Distribution(
            self,
            "AroSiteDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
            ),
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            comment=f"Aro Operator Dashboard CDN ({config.env_name})",
        )

        # -------------------------------------------------------------
        # 3. Outputs
        # -------------------------------------------------------------
        CfnOutput(
            self,
            "SiteDistributionDomain",
            value=self.distribution.distribution_domain_name,
            description="CloudFront CDN domain name for operator UI",
        )
        CfnOutput(
            self,
            "SiteBucketName",
            value=self.site_bucket.bucket_name,
            description="S3 bucket storing frontend build assets",
        )
