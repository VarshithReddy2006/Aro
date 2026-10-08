# AWS Serverless Infrastructure & Deployment Integration

This document defines the AWS serverless architecture, AWS CDK implementation, deployment lifecycle, and security controls for Aro Phase 7.

---

## 1. AWS Architecture Overview

Aro's deployed architecture translates the deterministic event-driven operational domain into AWS serverless primitives while strictly maintaining the human approval boundary.

```
                    Ring / Signed Webhook
                              │
                              ▼
                       API Gateway (REST)
                        ├── POST /webhooks/ring (HMAC)
                        └── /api/cases/* (Cognito Authorizer)
                              │
                              ▼
                     Ingest Lambda
                     ├── Exact raw body HMAC verification
                     ├── SSM Parameter Secret lookup
                     ├── Raw Ring persistence (DynamoDB)
                     └── PutEvents to EventBridge
                              │
                              ▼
                     EventBridge Bus (`aro-events-{env}`)
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
        Worker Lambda                CloudWatch Metrics
        ├── Event correlation         └── Operational logs
        ├── Business-hours context
        ├── Bounded Bedrock Brief (Claude 3 Haiku)
        ├── Deterministic Fallback on error
        └── Proposal persistence (DynamoDB)
                │
                ▼
         Operator UI (React / CloudFront + S3)
                │
                ▼
          HUMAN APPROVAL
                │
                ▼
      API Gateway -> API Lambda
      ├── Cognito JWT claims -> ActorContext (ADMIN/OPERATOR/VIEWER)
      ├── RBAC check (rejects VIEWER mutations)
      ├── Cryptographic Proposal Hash validation
      ├── Case version concurrency check
      ├── ActionExecutor deterministic dispatch
      ├── Idempotency enforcement
      ├── Audit hash-chain generation
      └── Evidence bundle sealing (S3 Private Bucket)
```

### Core Invariants Preserved
- **AI Proposes, Humans Approve**: Bedrock is bounded to proposing allowlisted operational actions. It cannot execute actions or call tools.
- **Backend Authoritative**: The frontend is not a security boundary; Cognito claims are extracted and validated on every backend invocation.
- **Cryptographic Bounding**: Approvals are cryptographically bound to `proposal_hash`, `case_version`, and authenticated `actor_id`.
- **Deterministic Execution**: Action execution goes solely through `ActionExecutor` with idempotency and audit chaining.

---

## 2. CDK Structure

The infrastructure is organized under `infra/` using AWS CDK v2 (Python) into 5 focused stacks:

```
infra/
├── app.py                     # CDK app entrypoint with tagging and env resolution
├── config.py                  # Environment dataclass (demo, dev, prod)
├── stacks/
│   ├── storage_stack.py       # AroStorageStack: DynamoDB single-table & S3 Evidence bucket
│   ├── events_stack.py        # AroEventsStack: Custom EventBridge event bus
│   ├── compute_stack.py       # AroComputeStack: Ingest, Worker, and API Lambdas + SSM
│   ├── api_stack.py           # AroApiStack: Cognito User Pool & API Gateway REST API
│   └── frontend_stack.py      # AroFrontendStack: S3 bucket & CloudFront CDN distribution
└── tests/                     # Infrastructure synthesis and assertion tests
```

---

## 3. DynamoDB Single-Table Design

Aro provisions a single-table design (`AroTable-{env}`) compatible with all domain repositories:
- `CaseRepository`
- `EventRepository`
- `ApprovalRepository`
- `ActionRepository`
- `AuditRepository`
- `IdempotencyRepository`
- `ExpectedDeliveryRepository`
- `PolicyRepository`
- `ProposalRepository`

### Key Schema
- **PK**: `String` (Partition key: `CASE#{case_id}`, `ORG#{org_id}`, `RING_EVENT#{event_id}`, etc.)
- **SK**: `String` (Sort key: `METADATA`, `AUDIT#{timestamp}#{event_id}`, `PROPOSAL#{prop_id}`, etc.)
- **GSI1**: `GSI1PK` / `GSI1SK` (Query cases by status or tenant)
- **GSI2**: `GSI2PK` / `GSI2SK` (Query events by location or device)

### Operational Settings
- **Billing Mode**: `PAY_PER_REQUEST` (On-demand) for cost efficiency.
- **Encryption**: AWS-managed server-side encryption (`KMS_MANAGED`).
- **TTL**: Configured on attribute `expires_at_epoch` for transient records (e.g., idempotency tokens, temporary webhooks). Never applied to permanent audit trails.
- **Point-In-Time Recovery (PITR)**: Enabled in `prod`; disabled in `demo`/`dev` to minimize cost.
- **Deletion Protection**: Enabled in `prod`; removal policy set to `RETAIN` for production, `DESTROY` for ephemeral environments.

---

## 4. S3 Evidence Storage

Evidence bundles and tamper-evident audit packages are persisted in a dedicated private S3 bucket (`AroEvidenceBucket-{env}`):
- **Access**: `BlockPublicAccess.BLOCK_ALL` enabled. No public bucket policies.
- **Encryption**: `S3_MANAGED` server-side encryption with `enforce_ssl=True`.
- **Versioning**: Enabled in `prod` for tamper-resistance.
- **Lifecycle Rules**: In `demo`/`dev`, noncurrent versions transition/expire after 30 days to control storage costs.
- **Least Privilege**: Only API Lambda has `PutObject` and `GetObject` permissions. No credentials or secrets are stored in S3.

---

## 5. API Gateway

An Amazon API Gateway REST API (`aro-api-{env}`) exposes Aro's backend endpoints:

| Method | Path | Auth / Security | Description |
|---|---|---|---|
| `GET` | `/health` | Public | Health check / uptime monitoring |
| `POST` | `/webhooks/ring` | Public (HMAC verified) | Public Ring doorbell webhook entrypoint |
| `GET` | `/api/cases` | Cognito Authorizer | List operational cases |
| `GET` | `/api/cases/{id}` | Cognito Authorizer | Get single case details |
| `POST` | `/api/cases/{id}/approve` | Cognito Authorizer (RBAC) | Approve case proposal (OPERATOR / ADMIN) |
| `POST` | `/api/cases/{id}/reject` | Cognito Authorizer (RBAC) | Reject case proposal (OPERATOR / ADMIN) |
| `POST` | `/api/cases/{id}/execute` | Cognito Authorizer (RBAC) | Execute approved action (OPERATOR / ADMIN) |
| `GET` | `/api/cases/{id}/timeline` | Cognito Authorizer | Get tamper-evident audit timeline |
| `GET` | `/api/cases/{id}/evidence` | Cognito Authorizer | Assemble & download sealed evidence bundle |
| `POST` | `/api/cases/{id}/close` | Cognito Authorizer (RBAC) | Close case (OPERATOR / ADMIN) |

---

## 6. Lambda Compute Architecture

Rather than creating dozens of trivial Lambdas, Aro uses 3 cohesive functions:

1. **Ingest Lambda** (`AroIngestFunction-{env}`):
   - Fast, lightweight ingestion entrypoint.
   - Computes HMAC-SHA256 signature over exact raw payload body.
   - Enforces 256KB size limit and timestamp replay boundaries (300s window).
   - Records raw event to DynamoDB and emits event notification to EventBridge.
2. **Worker Lambda** (`AroWorkerFunction-{env}`):
   - Triggered by EventBridge events (`source: aro.ring`, `detail-type: RingEventReceived`).
   - Normalizes event, performs windowed event correlation.
   - Assembles deterministic context (business hours, expected delivery, designated entrance).
   - Generates bounded AI operational brief via Amazon Bedrock (with automatic fallback to deterministic brief generator on error/timeout).
   - Saves generated brief and allowlisted proposals to DynamoDB.
3. **API Lambda** (`AroApiFunction-{env}`):
   - Handles authenticated REST API routes.
   - Extracts caller claims from Cognito JWT or demo headers.
   - Enforces RBAC permissions: VIEWER roles are strictly denied mutations (`403 Forbidden`).
   - Coordinates `ApprovalService`, `ActionExecutor`, and `EvidenceService`.

---

## 7. EventBridge

Asynchronous decoupling is provided by a custom event bus (`aro-events-{env}`):
- **Source**: `aro.ring`
- **Detail Type**: `RingEventReceived`
- **Payload Shape**: Contains event identifiers (`event_id`, `device_id`, `organization_id`, `event_type`) rather than huge raw payloads. Workers query authoritative state from DynamoDB.
- **Tenant Validation**: The worker verifies tenant ownership and event existence before processing.

---

## 8. Amazon Bedrock Integration

- **Model ID**: `anthropic.claude-3-haiku-20240307-v1:0` (configurable via `ARO_BEDROCK_MODEL_ID`).
- **Least-Privilege IAM**: Only `AroWorkerFunction` has IAM permission `bedrock:InvokeModel` scoped to the specific model ARN. No other Lambda has Bedrock permissions.
- **Safety Boundary**: Bedrock is strictly used to synthesize facts, unknowns, context match, and allowlisted action proposals (`AIProposedAction`). It has zero tool-calling, autonomous execution, or external network capabilities.

---

## 9. Amazon Cognito Authentication & RBAC

- **User Pool**: `aro-users-{env}` with email-based sign-in and password policies.
- **User Groups**:
  - `ADMIN`: Full operational and administrative capabilities.
  - `OPERATOR`: Permitted to approve, reject, execute, and close cases.
  - `VIEWER`: Read-only access to cases, timelines, and evidence bundles.
- **API Authorization**:
  - API Gateway validates incoming Cognito JWTs via `CognitoUserPoolsAuthorizer`.
  - API Lambda extracts `cognito:groups` from the request context and derives the authoritative `Role` (`Role.ADMIN`, `Role.OPERATOR`, `Role.VIEWER`).
  - All mutating endpoints (`approve`, `reject`, `execute`, `close`) reject `VIEWER` users with HTTP 403.

---

## 10. Secrets Management (AWS SSM Parameter Store)

- The Ring webhook shared secret is stored in AWS Systems Manager Parameter Store at:
  `/aro/{environment}/ring/webhook-secret`
- **Access Control**: Only the `AroIngestFunction` role is granted `ssm:GetParameter` on this exact parameter ARN.
- The secret is never logged, never returned in API responses, and never bundled into frontend assets.

---

## 11. IAM Least Privilege Review

Every IAM role in Aro adheres to strict least-privilege principles:
- **No Wildcard Admin Roles**: Zero instances of `AdministratorAccess`, `PowerUserAccess`, `AmazonDynamoDBFullAccess`, `AmazonS3FullAccess`, or `AmazonBedrockFullAccess`.
- **Resource Scoping**:
  - DynamoDB permissions (`GetItem`, `PutItem`, `UpdateItem`, `Query`) scoped to the specific table ARN and its GSIs.
  - S3 permissions (`PutObject`, `GetObject`) scoped to the specific bucket ARN and `/*`.
  - Bedrock permission (`bedrock:InvokeModel`) scoped to the exact foundation model ARN.
  - SSM permission (`ssm:GetParameter`) scoped to the exact webhook secret parameter ARN.
  - EventBridge permission (`events:PutEvents`) scoped to the specific custom event bus ARN.

---

## 12. CloudWatch Observability

CloudWatch provides operational monitoring without replacing the application's cryptographically linked `AuditEvent` log chain:
- **Metrics & Alarms**:
  - Lambda invocations, errors, durations, and throttles.
  - API Gateway 4xx/5xx error rates and latency.
- **Structured JSON Logging**:
  - Operational logs emit structured keys: `request_id`, `case_id`, `event_id`, `execution_id`, `organization_id`.
  - Explicit omission of Ring secrets, auth tokens, and raw personally identifiable payloads.

---

## 13. Frontend Deployment

The React/Vite operator console can be deployed to AWS using static hosting:
- **Storage**: Private S3 bucket (`AroFrontendBucket-{env}`) with public access blocked.
- **CDN**: CloudFront Distribution with Origin Access Control (OAC) or Origin Access Identity (OAI).
- **HTTPS & Routing**: Redirect to HTTPS enforced, with SPA fallback (`403` and `404` errors redirect to `/index.html` with HTTP 200).
- **Environment API Endpoint**: Configured at build time via `VITE_API_BASE_URL`.

---

## 14. Environment Configurations

Aro supports three explicit environments configured in `infra/config.py`:

| Environment | DynamoDB PITR | Table Deletion Protection | S3 Versioning | S3 Removal Policy | CORS Origins |
|---|---|---|---|---|---|
| `demo` | Disabled | Disabled | Disabled | `DESTROY` | `*` (Local dev) |
| `dev` | Disabled | Disabled | Disabled | `DESTROY` | Configured Dev URL |
| `prod` | Enabled | Enabled | Enabled | `RETAIN` | Strict Prod URL |

---

## 15. Local / Demo Workflow (Zero AWS Dependency)

The local demo workflow runs completely without AWS credentials or network access:
- **Repositories**: `InMemoryCaseRepository`, `InMemoryEventRepository`, `InMemoryApprovalRepository`, `InMemoryActionRepository`, `InMemoryAuditRepository`, `InMemoryIdempotencyRepository`, `InMemoryProposalRepository`.
- **Bedrock**: Deterministic `FallbackBriefGenerator` executes when AWS credentials are absent.
- **Auth**: Headers `x-actor-id`, `x-organization-id`, and `x-actor-role` simulate Cognito claims for test scenarios.
- **Tests**: All 185 unit and integration tests run entirely in-memory in under 30 seconds.

---

## 16. Deployment Commands

### Prerequisites
- Node.js 20+ and AWS CDK CLI (`npm install -g aws-cdk`)
- Python 3.12 with dependencies: `pip install -e ".[dev]" aws-cdk-lib constructs`
- Configured AWS credentials with appropriate deployment permissions.

### Synthesis & Review
```bash
# Synthesize CloudFormation templates for demo environment
npx aws-cdk synth

# Inspect changes against an active environment
cdk diff -c env=dev
```

### Deployment (Targeted Environment)
```bash
# Deploy dev environment
cdk deploy --all -c env=dev --require-approval broadening

# Deploy production environment (requires explicit stack review)
cdk deploy --all -c env=prod --require-approval broadening
```

---

## 17. Rollback Considerations

- **Serverless Immutability**: Lambda functions and API Gateway stages deploy revisioned code artifacts without modifying stored data.
- **DynamoDB Safeguards**: In `prod`, the table has `deletion_protection=True` and `removal_policy=RETAIN`, preventing catastrophic data loss during stack tear-down or rollback.
- **S3 Versioning**: The evidence bucket preserves object versions in `prod` to prevent accidental overwrites or purges.

---

## 18. Security Boundaries Summary

1. **Ring Webhook Boundary**: Raw body HMAC-SHA256 verification + 300s replay prevention window + 256KB max size limit.
2. **Cognito / API Gateway Boundary**: Authenticated JWT token validation with server-authoritative role extraction.
3. **Operator Approval Boundary**: Human approval strictly required before any operational action can be executed.
4. **Cryptographic Binding**: Execution verifies proposal hash matching SHA-256 canonical digest and case version.
5. **Deterministic Executor**: Only allowlisted actions (`NOTIFY_OPERATOR`, `MARK_FOR_REVIEW`, `RECORD_NO_ACTION`) can be processed; arbitrary tool execution is structurally impossible.

---

## 19. Cost Control Analysis

Aro is optimized for ultra-low base cost:
- **Serverless Baseline**: Zero hourly compute or cluster charges (no NAT Gateway, VPC, EC2, ECS, EKS, or RDS).
- **DynamoDB**: On-demand billing (`PAY_PER_REQUEST`), zero cost when idle.
- **Lambda**: Pay per millisecond of execution; generous free-tier allocation.
- **S3 & EventBridge**: Pay per event/request, negligible for test and hackathon scale.
- **Bedrock**: Incurred only upon processing motion/doorbell events; prompt is strictly bounded to minimal context tokens.
