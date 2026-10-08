# ParcelProof Infrastructure

AWS CDK in Python.

Target: API Gateway → Ingest Lambda → DynamoDB → EventBridge → Case/Brief/Action Lambdas → S3/evidence + notification adapter.

Supporting services: Cognito, SSM Parameter Store, CloudWatch, Bedrock.

Do not add Step Functions, AgentCore, Cedar, Kafka/Kinesis, Redis, Kubernetes, vector databases, or other infrastructure without an explicit architecture decision.
