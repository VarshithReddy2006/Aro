# ARO

> Ring-triggered, human-approved operational case system for after-hours delivery activity at coworking and shared offices.

## Product Boundary

ARO is **not** a Ring security dashboard, autonomous security agent, or generic ticketing system.

Core flow:

**Physical event → Ring webhook → HMAC verify → normalize → correlate → case → context → factual AI brief → allowlisted proposal → HUMAN APPROVAL → deterministic action → audit/evidence → closure**

AI proposes. Humans approve. Backend authorization enforces. Deterministic code executes.

---

## Repository Layout

```text
ARO/
├── apps/
│   ├── api/              # AWS Lambda/API application layer & domain services
│   └── web/              # React + Vite + TypeScript operator UI
├── infra/                # AWS CDK v2 (Python) serverless infrastructure stacks
├── packages/contracts/   # Shared API/domain schemas & Pydantic contracts
├── docs/
│   ├── architecture/     # Architecture documents, state machines, AWS deployment
│   └── adr/              # Architecture decision records
├── tests/
│   ├── unit/             # Unit, security, and CDK assertion tests
│   └── fixtures/         # Deterministic demo events and payloads
└── scripts/              # Local/demo/deployment helpers
```

---

Scaffold only. Implementation follows the approved ARO architecture and MVP scope.

## Development & Demo Modes

- **DEMO / LOCAL**: Zero AWS credentials required. In-memory repositories, deterministic fallback brief generator, simulated authentication, and instant test runs. Synthetic events are stamped with `provenance=demo_synthetic`.
- **DEV / PROD**: AWS Serverless architecture deployed via AWS CDK (API Gateway, Lambda, DynamoDB, EventBridge, Bedrock, S3, Cognito, SSM, CloudFront).

### Ring Hardware Terminology Boundary

- Ring devices detect physical motion and doorbell ring events only.
- Ring does **not** provide native package or parcel delivery detection.
- All references in Aro are strictly formulated as *"Ring activity associated with a designated door"* or *"possible after-hours delivery activity"*.
- AI output claiming native courier or parcel detection without physical verification is rejected at validation stage.

---

## Canonical 3-Minute Hackathon Demo Path

The complete local demo executes without AWS credentials in under 3 minutes:

1. **Launch Local Application**:
   - Operator opens `http://localhost:5173` with Demo Mode banner active (`demo_synthetic`).
2. **Synthetic Event Ingest**:
   - Deterministic synthetic event (`evt_synthetic_01`) arrives representing after-hours doorbell activity.
3. **Deterministic Correlation & Context**:
   - Aro evaluates business hours (outside 08:00–18:00), matches entrance rules (designated door), and notes no active parcel manifest is registered.
4. **Bounded AI Briefing**:
   - AI generates factual summary strictly bounded to verified context facts. Known facts vs unknown ambiguities are separated.
5. **Allowlisted Proposal**:
   - System formulates an allowlisted proposal (`NOTIFY_OPERATOR`) with canonical SHA-256 hash digest.
6. **Human Approval Gate**:
   - Case enters `APPROVAL_PENDING`. Operator inspects proposal hash and case version, then clicks **Approve Proposal**. Case advances to `APPROVED`.
7. **Deterministic Execution**:
   - Operator triggers action execution. Backend validates approval ID, case version, and idempotency key before dispatching deterministic adapter. Case advances to `COMPLETED`.
8. **Evidence & Audit Sealing**:
   - Cryptographic tamper-evident hash chain logs all state transitions. Sealed evidence bundle is available for review.
9. **Case Closure**:
   - Operator enters resolution notes and closes the case (`CLOSED`).
10. **Scenario Reset**:
    - Operator clicks **Reset Demo Scenario** in the header to re-arm the deterministic golden path at any time.

---

## Authentication & Authorization Boundaries

- **PRODUCTION (AWS Deployed)**:
  - API Gateway validates Cognito User Pool JWT bearer tokens via Cognito authorizer.
  - Server-authoritative claims (`sub`, `custom:tenant_id`, `custom:role`) populate the verified `ActorContext`.
  - Client headers (`x-actor-role`, `x-actor-id`, `x-tenant-id`, `x-organization-id`) are **never** trusted or consulted in production.
  - Role-based access control enforces `VIEWER` read-only access and prevents role elevation.
- **LOCAL / DEMO**:
  - In explicitly isolated local/demo mode (`ARO_ENV=demo`), simulated actor headers (`x-actor-role`, `x-actor-id`, `x-tenant-id`) are accepted for offline UI simulation and integration testing without AWS credentials.

## Infrastructure & Messaging Primitives

- **Secret Storage (SSM)**: Webhook HMAC secret is canonicalized to `/aro/{env}/ring/webhook-secret` across all environments.
- **Event Transport**: Asynchronous ingestion and worker notifications route exclusively through **Amazon EventBridge** (`aro-events-{env}`). SQS is not used.
- **Database**: Single-table Amazon DynamoDB (`aro-core-table-{env}`) with conditional writes, composite tenant partition keys, and TTL.

---

## Quick Start — Local Demo

The local demo and test suite run entirely offline without AWS credentials:

### 1. Environment Setup

```bash
cp .env.example .env
```

### 2. Backend Setup & Tests

```bash
# Install Python dependencies
pip install -e ".[dev]"

# Run all 210 backend tests (193 unit + 17 integration)
pytest

# Format & lint check
ruff check .
ruff format --check .

# Static type check
mypy packages apps/api tests/integration/test_end_to_end_workflow.py tests/unit/test_security_aws_integration.py
```

### 3. Frontend Setup & Tests

```bash
cd apps/web
npm install

# Run 15 frontend tests
npm test

# Typecheck and build production bundle
npm run build
```

---

## AWS Deployment Readiness

See [docs/architecture/aws-deployment.md](docs/architecture/aws-deployment.md) for full architecture details and readiness runbook.

> [!IMPORTANT]
> **Deployment Status**: Infrastructure code has been synthesized, diffed, and validated against contract tests. Actual AWS deployment has **NOT** been performed (**NOT DEPLOYED**).

### Synthesize Infrastructure

```bash
# Synthesize CloudFormation templates (defaults to demo)
npx aws-cdk synth

# Inspect differences against active AWS deployment
cdk diff -c env=dev
```

### Deployment Commands (When Authorized)

```bash
# Deploy dev environment
cdk deploy --all -c env=dev --require-approval broadening

# Deploy prod environment
cdk deploy --all -c env=prod --require-approval broadening
```

---

## Quality Gates

All checks pass locally and in CI:

- **Backend tests**: `pytest` (210 passed: 193 unit + 17 integration)
- **Frontend tests**: `vitest` in `apps/web` (15 passed)
- **Frontend build**: `vite build` (Production bundle generated)
- **Lint**: `ruff check .` (0 errors)
- **Format**: `ruff format --check .` (0 errors)
- **Type Checking**: `mypy` (0 errors in 55 files), `tsc --noEmit` (0 errors)
- **CDK Synth**: `npx aws-cdk synth` (All 5 stacks synthesized cleanly)
