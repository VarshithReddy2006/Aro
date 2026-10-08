# Ring Ingestion & Webhook Security Architecture

## 1. Executive Summary

This document specifies the ingestion architecture and security boundaries for incoming Ring device events in Aro. Ring webhooks are the primary external stimulus for physical-world event observation outside business hours.

Because webhooks originate on the public internet, they represent an untrusted external boundary. The pipeline strictly validates authenticity, integrity, freshness, and structural schema before persisting events or handing them off to internal case workflows.

---

## 2. Verified Ring Capabilities vs. Prohibited Claims

### Official Ring Partner API Verified Capabilities (v1.1)
Based on official Ring Developer and Partner documentation:
- **Authentication**: HMAC-SHA256 signature passed in the `X-Signature` header (calculated over the raw HTTP body).
- **Transport**: HTTPS POST to partner-registered webhook URL.
- **Payload Format**: JSON:API compliant structure (`meta` object with `version`, `time`, `request_id`, and `data` object with `id`, `attributes.event_type`, `attributes.device_id`, `attributes.timestamp`).
- **Verified Physical Event Types**:
  - `motion_detected` / `motion` (PIR or computer vision motion alert)
  - `button_press` / `doorbell_ring` (Physical ring button pushed on doorbell)
  - `device_online` / `device_offline` (Device connectivity status)

### Critical Terminology Rule & Known Ring Limitations
1. **No Native Package / Delivery Detection**: Ring does **NOT** provide a native `package_detected`, `package_delivered`, or `delivery_detected` event type in its Partner webhook protocol.
2. **Strict Terminology Invariant**:
   - **NEVER** claim:
     - *"Ring detected a package"*
     - *"Ring detected a delivery"*
     - *"Ring confirmed a delivery"*
   - **ALWAYS** use:
     - *"Ring activity associated with a designated door"*
     - *"possible after-hours delivery activity"*
     - *"motion/doorbell activity observed at designated entrance"*
3. Fabricated event types claiming package detection are explicitly rejected and quarantined by the validation schema.

---

## 3. Ingestion Pipeline & Trust Boundary

```
Ring Webhook Request
        │
        ▼
[1] Payload Size Guard (Default 256 KB)
    └── If exceeded: HTTP 413 Payload Too Large (Zero DB writes)
        │
        ▼
[2] HMAC-SHA256 Signature Verification (RingSignatureVerifier)
    ├── Reads exact raw HTTP request bytes
    ├── Extracts `X-Signature` header
    ├── Compares computed HMAC using constant-time `hmac.compare_digest`
    └── If invalid/missing: HTTP 401 Unauthorized (Zero DB writes)
        │
        ▼
[3] Schema & JSON Validation (RingPayloadValidator)
    ├── Parses JSON from verified raw bytes
    ├── Validates required fields: request_id, event_id, device_id, event_type, occurred_at
    └── If malformed or prohibited type:
        └── QUARANTINE: Persist to PK=EVENT#<id>, SK=RAW with status=QUARANTINED (HTTP 400)
        │
        ▼
[4] Replay Protection (ReplayProtectionService)
    ├── Evaluates `meta.time` (or `X-Signature-Timestamp`) against UTC reference clock
    ├── Enforces freshness window (300 seconds) & future clock skew tolerance (60 seconds)
    └── If stale/future: HTTP 400 Bad Request
        │
        ▼
[5] Atomic Deduplication (DynamoDB / EventRepository)
    ├── Records `DEDUP#RING#<request_id>` with atomic conditional put (`attribute_not_exists`)
    └── If duplicate: HTTP 200 Idempotent Acknowledgment
        │
        ▼
[6] Raw Event Persistence (Pre-Case Partition)
    └── Writes `PK = EVENT#<event_id>, SK = RAW` with status = RECEIVED
        │
        ▼
[7] Deterministic Normalization (RingNormalizer)
    ├── Resolves `Location` and `RingDevice` records
    ├── Evaluates deterministic business hours policy via `BusinessHoursService`
    ├── Derives designated entrance flag and factual description
    └── Updates status = VALIDATED
        │
        ▼
[8] Case Correlation Handoff (DefaultCaseCorrelationService)
    ├── Checks for active open cases matching location and device
    ├── If active case found: correlates event (`event_repo.correlate_event_to_case`) -> status = CORRELATED
    └── If no active case found: remains VALIDATED in pre-case partition awaiting grouping
```

---

## 4. Replay Protection & Clock Assumptions

- **Timestamp Source**: Ring sends an ISO 8601 UTC timestamp in `meta.time`. If an HTTP header such as `X-Signature-Timestamp` is present, it is also validated.
- **Freshness Window**: 300 seconds (5 minutes). Requests older than 300 seconds are rejected with HTTP 400.
- **Clock Skew Tolerance**: Up to 60 seconds of future drift is tolerated to accommodate NTP variations across distributed systems. Beyond 60 seconds into the future, requests are rejected.
- **Idempotency Token Expiration**: Deduplication records (`DEDUP#RING#<request_id>`) persist with a 24-hour DynamoDB TTL (`expires_at_epoch`), ensuring that replayed requests with the same `request_id` are caught even within the freshness window.

---

## 5. Deduplication Invariants

- Deduplication uses atomic conditional writes on `PK = ORG#<org_id>, SK = DEDUP#RING#<request_id>`.
- Concurrent identical requests result in exactly **one** accepted raw event persistence.
- The duplicate request receives an HTTP 200 acknowledgment with `{"status": "duplicate", "message": "Duplicate event already processed"}` to ensure upstream webhook retries do not trigger duplicate processing cascades.

---

## 6. Business Hours Engine (Deterministic)

The business hours evaluation engine (`BusinessHoursService`) is purely deterministic and executes without AI:
- **Inputs**: Facility IANA timezone (e.g. `America/New_York`, `Europe/London`), business days list (`[0, 1, 2, 3, 4]` for Mon–Fri), opening time (`08:00`), closing time (`20:00`), and UTC event timestamp.
- **Calculation**: Converts timestamp to local facility time (handling DST automatically via standard library `zoneinfo`). If outside configured open interval or on a non-business day (weekend), returns `is_after_hours = True`.

---

## 7. DEMO vs. LIVE Integration Modes

### DEMO Mode
- Provides 7 deterministic synthetic fixtures covering:
  1. Valid motion event
  2. Duplicate request
  3. Forged signature
  4. Authenticated malformed payload
  5. Stale / replayed timestamp
  6. After-hours event
  7. Normal-hours event
- **Provenance Invariant**: Every synthetic fixture is explicitly tagged `provenance = demo_synthetic`. Synthetic data is never represented as real Ring hardware data.

### LIVE Mode
- Implements the official Ring Partner API v1.1 protocol.
- Production environment injects `RING_WEBHOOK_SECRET` securely from AWS SSM Parameter Store / Secrets Manager.
- Never logs credentials, secrets, or HMAC keys.
