# ARO

> Ring-triggered, human-approved operational case system for after-hours delivery activity at coworking and shared offices.

## Product boundary

ARO is **not** a Ring security dashboard, autonomous security agent, or generic ticketing system.

Core flow:

**Ring event → verify → normalize → deduplicate/correlate → classify → case → context → factual AI brief → allowlisted proposal → human approval → action → audit/evidence → closure**

AI explains and proposes. Deterministic code enforces. Humans approve consequential actions.

## Repository layout

```text
ARO/
├── apps/
│   ├── api/              # AWS Lambda/API application layer
│   └── web/              # React + Vite + TypeScript operator UI
├── infra/                # AWS CDK (Python)
├── packages/contracts/   # Shared API/domain contracts
├── docs/
│   ├── architecture/    # C4, sequences, state/data-flow diagrams
│   └── adr/              # Architecture decision records
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── scripts/              # Local/demo/deployment helpers
```

## MVP status

Scaffold only. Implementation follows the approved ARO architecture and MVP scope.

## Engineering principles

- Human approval is mandatory before consequential actions.
- Ring-originated data must retain explicit provenance.
- Demo/synthetic events must never masquerade as real Ring events.
- Webhook ingestion is idempotent and replay-resistant.
- AI output is schema-constrained and cannot execute tools directly.
- Actions are allowlisted, authorized, auditable, and idempotent.
- Audit history is tamper-evident, not tamper-proof.
- Keep the MVP small enough for two developers and the hackathon timeline.

## Development modes

- `DEMO`: deterministic synthetic Ring fixtures; no external network dependency.
- `LIVE`: real Ring/AWS integrations behind explicit configuration.

These modes must remain separate.
