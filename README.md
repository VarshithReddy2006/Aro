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

## Development Modes

- **DEMO / LOCAL**: Zero AWS credentials required. In-memory repositories, deterministic fallback brief generator, simulated authentication, and instant test runs.
- **DEV / PROD**: AWS Serverless architecture deployed via AWS CDK (API Gateway, Lambda, DynamoDB, EventBridge, Bedrock, S3, Cognito, SSM, CloudFront).

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

# Run all backend unit & security integration tests
pytest

# Format & lint check
ruff check .
ruff format --check .
```

### 3. Frontend Setup & Tests

```bash
cd apps/web
npm install

# Run frontend tests
npm test

# Build production bundle
npm run build
```

---

## AWS Deployment (AWS CDK)

See [docs/architecture/aws-deployment.md](docs/architecture/aws-deployment.md) for full architecture details.

### Prerequisites

- Node.js 20+ & AWS CDK CLI (`npm install -g aws-cdk`)
- Python 3.12 with `aws-cdk-lib` and `constructs` (`pip install aws-cdk-lib constructs`)
- Configured AWS credentials (`aws configure`)

### Synthesize Infrastructure

```bash
# Synthesize CloudFormation templates (defaults to demo)
npx aws-cdk synth

# Inspect differences against active AWS deployment
cdk diff -c env=dev
```

### Deploy to AWS

```bash
# Deploy dev environment
cdk deploy --all -c env=dev --require-approval broadening

# Deploy prod environment
cdk deploy --all -c env=prod --require-approval broadening
```

---

## Quality Gates

All changes must pass:

- **Backend tests**: `pytest` (185 tests passing)
- **Frontend tests**: `npm test` in `apps/web` (15 tests passing)
- **Lint**: `ruff check .`
- **Format**: `ruff format --check .`
- **TypeScript**: `tsc --noEmit`
- **CDK Synth**: `npx aws-cdk synth`
