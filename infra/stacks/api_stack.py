"""API Gateway and Cognito authorization stack."""

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_apigateway as apigw,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_lambda as _lambda,
)
from constructs import Construct

from ..config import AroConfig


class ApiStack(Stack):
    """API Gateway and Cognito authentication/authorization resources."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: AroConfig,
        ingest_lambda: _lambda.IFunction,
        api_lambda: _lambda.IFunction,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        removal_policy = RemovalPolicy.RETAIN if config.retain_on_delete else RemovalPolicy.DESTROY

        # -------------------------------------------------------------
        # 1. Cognito User Pool & App Client
        # -------------------------------------------------------------
        self.user_pool = cognito.UserPool(
            self,
            "AroUserPool",
            user_pool_name=config.user_pool_name,
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            custom_attributes={
                "organization_id": cognito.StringAttribute(mutable=True),
            },
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            removal_policy=removal_policy,
        )

        self.user_pool_client = cognito.UserPoolClient(
            self,
            "AroWebClient",
            user_pool=self.user_pool,
            user_pool_client_name=f"aro-web-client-{config.env_name}",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(
                user_srp=True,
                user_password=True,
            ),
        )

        # RBAC Groups
        self.admin_group = cognito.CfnUserPoolGroup(
            self,
            "AdminGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="ADMIN",
            description="Aro Administrators with full configuration and operational rights",
        )

        self.operator_group = cognito.CfnUserPoolGroup(
            self,
            "OperatorGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="OPERATOR",
            description="On-duty Operators authorized to review, approve, reject, and execute cases",
        )

        self.viewer_group = cognito.CfnUserPoolGroup(
            self,
            "ViewerGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="VIEWER",
            description="Read-only Viewers with audit trail and case visibility",
        )

        # -------------------------------------------------------------
        # 2. API Gateway REST API & Authorizer
        # -------------------------------------------------------------
        self.api = apigw.RestApi(
            self,
            "AroRestApi",
            rest_api_name=f"aro-api-{config.env_name}",
            description="Aro Operational Serverless REST API",
            deploy_options=apigw.StageOptions(
                stage_name=config.env_name,
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=not config.is_prod,
                metrics_enabled=True,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=config.cors_allowed_origins,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "X-User-Id",
                    "X-Organization-Id",
                    "X-User-Role",
                    "X-Signature",
                ],
                allow_credentials=True,
            ),
        )

        self.authorizer = apigw.CognitoUserPoolsAuthorizer(
            self,
            "AroCognitoAuthorizer",
            cognito_user_pools=[self.user_pool],
            identity_source="method.request.header.Authorization",
        )

        ingest_integration = apigw.LambdaIntegration(
            ingest_lambda,
            proxy=True,
        )

        api_integration = apigw.LambdaIntegration(
            api_lambda,
            proxy=True,
        )

        # -------------------------------------------------------------
        # 3. Routes & Endpoints
        # -------------------------------------------------------------
        # Public: GET /health
        health_resource = self.api.root.add_resource("health")
        health_resource.add_method("GET", api_integration)

        # Public (HMAC-guarded): POST /webhooks/ring
        webhooks_resource = self.api.root.add_resource("webhooks")
        ring_webhook_resource = webhooks_resource.add_resource("ring")
        ring_webhook_resource.add_method("POST", ingest_integration)

        # Authenticated: /api/*
        api_resource = self.api.root.add_resource("api")
        cases_resource = api_resource.add_resource("cases")

        # GET /api/cases
        cases_resource.add_method(
            "GET",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /api/cases/{id}
        case_item = cases_resource.add_resource("{id}")

        # GET /api/cases/{id}
        case_item.add_method(
            "GET",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /api/cases/{id}/brief
        brief_resource = case_item.add_resource("brief")
        brief_resource.add_method(
            "POST",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /api/cases/{id}/approve
        approve_resource = case_item.add_resource("approve")
        approve_resource.add_method(
            "POST",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /api/cases/{id}/reject
        reject_resource = case_item.add_resource("reject")
        reject_resource.add_method(
            "POST",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /api/cases/{id}/execute
        execute_resource = case_item.add_resource("execute")
        execute_resource.add_method(
            "POST",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /api/cases/{id}/timeline
        timeline_resource = case_item.add_resource("timeline")
        timeline_resource.add_method(
            "GET",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /api/cases/{id}/evidence
        evidence_resource = case_item.add_resource("evidence")
        evidence_resource.add_method(
            "GET",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /api/cases/{id}/close
        close_resource = case_item.add_resource("close")
        close_resource.add_method(
            "POST",
            api_integration,
            authorizer=self.authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # -------------------------------------------------------------
        # 4. Outputs
        # -------------------------------------------------------------
        CfnOutput(self, "ApiUrl", value=self.api.url, description="API Gateway base URL")
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
        )
        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito User Pool Client ID",
        )
