# Case Context, Bounded AI Brief, and Allowlisted Proposal Architecture

## 1. Executive Summary

Phase 4 establishes the AI boundary in Aro. The core product principle remains:
**AI explains and proposes. Deterministic application code enforces. Humans approve consequential actions.**

Under this architecture, model output is treated as untrusted input. The system enforces:
1. Deterministic case context assembly strictly from validated records.
2. Explicit conceptual separation between verified KNOWN facts and operational UNKNOWNS.
3. A single, bounded Bedrock invocation for the MVP (strictly no autonomous tool loops, multi-agent swarms, or direct execution).
4. A multi-stage validation pipeline: Schema Validation → Factual & Terminology Guardrail Validation → Policy & Parameter Validation.
5. Strict proposal allowlisting (`NOTIFY_OPERATOR`, `MARK_FOR_REVIEW`, `REQUEST_OPERATOR_CONFIRMATION`, `RECORD_NO_ACTION`).
6. Deterministic canonical SHA-256 proposal hashing.
7. Resilient fallback brief generation guaranteeing offline execution and audit continuity.

---

## 2. Context Sources & Deterministic Assembly

The `CaseContextBuilder` deterministically aggregates operational facts from trusted repositories without AI inference:

| Context Element | Trusted Source | Deterministic Logic / Enforced Invariant |
|---|---|---|
| **Case Metadata** | `CaseRepository` | Enforces `organization_id` tenant isolation on retrieval. |
| **Monitored Facility** | `LocationRepository` | Timezone, operating hours (`HH:MM`), business days. Cross-tenant access forbidden. |
| **Device Configuration**| `DeviceRepository` | Device category and `is_designated_door` entrance classification. |
| **Physical Events** | `EventRepository` | Correlated normalized events and triggering raw event timestamp. |
| **Schedule Policy** | `BusinessHoursService` | Deterministic IANA timezone evaluation (handles DST). Computes `is_after_hours`. |
| **Expected Deliveries**| `ExpectedDeliveryRepository` | Queries scheduled arrivals within operational window (`±120 min`). Categorized as `EXPECTED`, `UNEXPECTED`, or `UNKNOWN`. |
| **Tenant Policy** | `PolicyRepository` | Dictates `allowed_actions` for the organization. |

---

## 3. The Known vs. Unknown Epistemic Model

The context layer and prompt enforce an explicit distinction between facts and operational unknowns:

### Verified KNOWN Facts
- A physical Ring motion or doorbell press occurred at an authenticated hardware sensor.
- The exact UTC timestamp and local facility time.
- Monitored door designation (`is_designated_door = True/False`).
- Operating schedule classification (`is_after_hours = True/False`).
- Expected delivery schedule match status (`EXPECTED` / `UNEXPECTED` / `UNKNOWN`).
- Total count and chronology of correlated event observations.

### Operational UNKNOWNS (Never converted to Fact without direct physical evidence)
- Whether a parcel or physical package was actually deposited or delivered.
- The personal identity, name, employer, or credentials of the individual observed.
- Whether any person gained unauthorized entry or unlocked a facility door.
- The subjective intent or legitimacy of the observed visitor.

---

## 4. AI Input & Output Contracts

### Sanitized AI Input Contract (`AIBriefInput`)
The model receives only the minimal structured fields necessary to synthesize the operational brief:
```json
{
  "case_id": "case_12345",
  "organization_id": "org_alpha",
  "location": { "name": "Main Office", "timezone": "America/New_York", "business_hours_start": "08:00", "business_hours_end": "20:00" },
  "device": { "device_id": "doorbell_front", "is_designated_door": true },
  "events": [ { "event_type": "button_press", "occurred_at": "...", "description": "..." } ],
  "business_context": { "is_after_hours": true, "designated_entrance": true },
  "expected_delivery": { "status": "EXPECTED", "deliveries": [ ... ] },
  "known_facts": [ ... ],
  "unknowns": [ ... ],
  "allowed_actions": [ "NOTIFY_OPERATOR", "MARK_FOR_REVIEW", "REQUEST_OPERATOR_CONFIRMATION", "RECORD_NO_ACTION" ],
  "prompt_version": "2026-10-v1"
}
```
**Excluded**: Internal database credentials, bearer tokens, raw payloads, and cross-tenant records.

### Strict AI Output Schema (`AIBriefOutput`)
The model must emit valid JSON matching this schema:
```json
{
  "summary": "Factual operational summary...",
  "facts": ["Grounded fact 1", "Grounded fact 2"],
  "unknowns": ["Explicit operational unknown 1"],
  "context_match": "Contextual alignment assessment...",
  "proposals": [
    {
      "action_type": "NOTIFY_OPERATOR",
      "reason": "Operational justification...",
      "parameters": {
        "message": "After-hours activity observed at entrance",
        "urgency": "normal",
        "recipient_role": "OPERATOR"
      }
    }
  ]
}
```

---

## 5. Multi-Stage Validation Pipeline

Every raw string emitted by Bedrock passes through three deterministic gates:

```
Raw Model Response
        │
        ▼
[Stage 1: Schema Validation]
    ├── JSON parsing (rejects malformed syntax)
    └── Pydantic model validation (`AIBriefOutput.model_validate`)
        │
        ▼
[Stage 2: Factual & Terminology Guardrail Validation]
    ├── Strictly rejects prohibited terminology:
    │   "package detected", "package delivered", "delivery confirmed",
    │   "courier identified", "person identified", "threat detected", "unlocked"
    ├── Strictly rejects prompt injection artifacts ("ignore previous instructions")
    └── Validates consistency with context (e.g. no claiming expected delivery when status is UNEXPECTED)
        │
        ▼
[Stage 3: Policy & Parameter Validation]
    ├── Verifies action_type is within `Policy.allowed_actions` (rejects invented actions like `UNLOCK_DOOR`)
    ├── Validates parameters against action-specific schemas (`NotifyOperatorParameters`, etc.) with `extra="forbid"`
    └── Computes deterministic SHA-256 `proposal_hash`
        │
        ▼
[Validated CaseBrief & Proposal Entities]
```
If any stage fails, `BriefService` automatically engages `FallbackBriefGenerator`.

---

## 6. Action Allowlist & Parameter Schemas

The model is strictly prohibited from executing or proposing arbitrary actions:

| ActionType | Permitted Parameter Schema | Invariant Enforced |
|---|---|---|
| `NOTIFY_OPERATOR` | `NotifyOperatorParameters(message, urgency, recipient_role)` | Rejects arbitrary webhook calls or unauthorized recipients. |
| `MARK_FOR_REVIEW` | `MarkForReviewParameters(review_reason, priority)` | Enforces structured review queues. |
| `REQUEST_OPERATOR_CONFIRMATION` | `RequestConfirmationParameters(confirmation_type, target_role)` | Prompts human operator for explicit confirmation. |
| `RECORD_NO_ACTION`| `RecordNoActionParameters(rationale)` | Closes review cycle with audited justification. |

Any other action (e.g. `UNLOCK_DOOR`, `CALL_POLICE`, `TRIGGER_ALARM`) is immediately rejected at validation.

---

## 7. Deterministic Proposal Hashing

To ensure that the human operator later approves the exact proposal and parameters generated by the system without mid-flight tampering:
$$\text{proposal\_hash} = \text{SHA-256}\Big(\text{JSON}_{\text{canonical}}\big(\{\text{action\_type}, \text{case\_id}, \text{parameters}, \text{reason}\}\big)\Big)$$
- Dictionary keys are recursively sorted.
- JSON serialization uses compact separators (`separators=(',', ':')`).
- Proven property: identical proposal payload produces identical hash; any parameter mutation changes the hash.

---

## 8. Fallback Brief Generation

If AWS Bedrock:
- is unreachable or times out,
- throws client exceptions or throttling errors,
- returns invalid JSON,
- generates prohibited terminology (e.g. claims a package was detected), or
- proposes an unauthorized action,

the system invokes `FallbackBriefGenerator`:
1. Synthesizes a factual brief directly from the trusted context facts.
2. Selects an allowlisted default action (`NOTIFY_OPERATOR` if after-hours and unexpected delivery; otherwise `MARK_FOR_REVIEW`).
3. Explicitly flags the brief with `is_fallback = True`.
4. Guarantees that cases are never blocked or left unrecorded due to downstream AI failure.
