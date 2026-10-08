# Aro Architecture — Trust Boundary

## 1. System Trust Boundary Overview

The Aro platform operates across strictly delineated trust domains to ensure that unauthenticated or adversarial external inputs cannot compromise system state, poison operational audit chains, or trigger consequential physical actions.

```
                  UNTRUSTED INTERNET
                          │
                          │ HTTPS Webhook POST
                          ▼
                  AWS API Gateway
                          │ (Max payload size check)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    RING INGEST HANDLER                      │
│                                                             │
│  [1] Size Check (413 Payload Too Large)                     │
│  [2] HMAC-SHA256 Signature Verification                    │
│      ├── INVALID/FORGED ──► Drop immediately (HTTP 401)    │
│      │                      ZERO DATABASE WRITES            │
│      └── VALID SIGNATURE ──┐                                │
│                            ▼                                │
│  [3] Schema & JSON Validation                               │
│      ├── MALFORMED ──► Quarantine (HTTP 400)                │
│      │                 Persist status = QUARANTINED         │
│      └── VALID ──┐                                          │
│                  ▼                                          │
│  [4] Replay Protection Check                                │
│      ├── STALE/FUTURE ──► Reject (HTTP 400)                 │
│      └── FRESH ──┐                                          │
│                  ▼                                          │
│  [5] Deduplication (Atomic DynamoDB conditional check)      │
│      ├── DUPLICATE ──► Acknowledge (HTTP 200 idempotent)    │
│      └── NEW ──┐                                            │
│                ▼                                            │
│  [6] Raw Event Persistence                                  │
│      PK = EVENT#<event_id>, SK = RAW, status = RECEIVED     │
│                │                                            │
│                ▼                                            │
│  [7] Deterministic Normalization (Business Hours Policy)    │
│      status = VALIDATED                                     │
│                │                                            │
│                ▼                                            │
│  [8] Case Correlation Boundary                              │
│      (Link to active case or queue for operational grouping)│
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              TRUSTED APPLICATION BOUNDARY
        (Case State Machine, Deterministic Policies,
          Human Approvals, Idempotent Action Adapters)
```

## 2. Ingestion Security Invariants

1. **Zero-Write on Forgery**: Any request failing HMAC-SHA256 verification (or lacking a signature) is terminated at the perimeter. No records are written to DynamoDB, no S3 bundles are created, and no downstream events are fired.
2. **Raw Body Integrity**: Signature verification is computed over the exact wire bytes prior to JSON decoding.
3. **No Credential Logging**: Webhook secrets, HMAC signatures, bearer tokens, and credentials are never logged or exported to observability streams.
4. **Quarantine for Authenticated Malformed Payloads**: Payloads with valid HMAC signatures but invalid JSON schemas or prohibited event types are persisted with `status = QUARANTINED` for security forensics, but are never forwarded to case correlation.
5. **No AI at the Webhook Boundary**: The ingestion handler acknowledges within seconds. Bounded LLM processing (Bedrock) is never called synchronously during webhook ingestion.
6. **Strict Terminology & Factual Boundaries**: The ingestion layer preserves physical observations (motion, doorbell rings). It never asserts or fabricates "package detected" or "delivery confirmed" events.
