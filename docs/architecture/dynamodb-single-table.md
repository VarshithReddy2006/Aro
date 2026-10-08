# DynamoDB Single-Table Design — Aro Architecture

## 1. Overview and Core Principles

Aro uses a single-table DynamoDB design to store cases, raw/normalized physical events, context, briefs, proposals, approvals, actions, audit records, and idempotency locks.

Core storage principles:
1. **Multi-tenant Organization Isolation**: Every case, policy, location, device, and delivery belongs to a specific tenant `organization_id`. Repositories strictly enforce tenant isolation so that tenant A cannot read, query, or mutate tenant B's records, even if a foreign ID is known.
2. **Deterministic State Invariants**: Consequential transitions (e.g. `APPROVAL_PENDING → APPROVED`, `APPROVED → EXECUTING`, case version updates) are guarded using atomic DynamoDB `ConditionExpression`s.
3. **Optimistic Concurrency**: The `Case` entity maintains an integer `version`. Updates require `attribute_exists(PK) AND version = :expected_version` and atomically increment `version`.
4. **Append-Only Auditing**: Audit timeline records are strictly append-only with SHA-256 hash chaining. Repositories prohibit updates or deletions to existing audit items.
5. **Atomic Execution Locking**: The action execution workflow requires acquiring an atomic execution lock (`status = 'APPROVED' AND attribute_not_exists(execution_lock)`) ensuring exactly-one execution.
6. **No Unnecessary Scans**: Every application access pattern is satisfied via deterministic `GetItem`, `Query` on the primary partition key, or sparse `Query` on targeted Global Secondary Indexes.

---

## 2. Table and Key Patterns

**Table Name**: `aro-core-table` (configurable via environment variable `ARO_TABLE_NAME`).

### Primary Keys
- **Partition Key (`PK`)**: `String`
- **Sort Key (`SK`)**: `String`

### Global Secondary Indexes
- **`GSI1`**:
  - `GSI1PK`: `String`
  - `GSI1SK`: `String`
  - Purpose: Organization-wide case listings and tracking lookups.
- **`GSI2`**:
  - `GSI2PK`: `String`
  - `GSI2SK`: `String`
  - Purpose: Filtered case queries by status or monitored location within an organization.

---

## 3. Entity Partition & Sort Key Layout

| Entity | PK | SK | GSI1PK | GSI1SK | GSI2PK | GSI2SK | TTL Attribute |
|---|---|---|---|---|---|---|---|
| **Organization** | `ORG#<org_id>` | `METADATA` | — | — | — | — | — |
| **Location** | `ORG#<org_id>` | `LOCATION#<location_id>` | — | — | — | — | — |
| **Ring Device** | `ORG#<org_id>` | `DEVICE#<device_id>` | — | — | — | — | — |
| **User** | `ORG#<org_id>` | `USER#<user_id>` | — | — | — | — | — |
| **Policy** | `ORG#<org_id>` | `POLICY` | — | — | — | — | — |
| **Case (Header)** | `CASE#<case_id>` | `CASE` | `ORG#<org_id>` | `CASE#<updated_at>` | `ORG#<org_id>#STATUS#<status>` | `<updated_at>#<case_id>` | — |
| **Ring Event (Raw)** | `EVENT#<event_id>` | `RAW` | `CASE#<case_id>` (post-correlation) | `EVENT#<occurred_at>` | — | — | — |
| **Normalized Event** | `CASE#<case_id>` | `NORM_EVENT#<norm_id>` | — | — | — | — | — |
| **Case Context** | `CASE#<case_id>` | `CONTEXT` | — | — | — | — | — |
| **Case Brief** | `CASE#<case_id>` | `BRIEF#<brief_id>` | — | — | — | — | — |
| **Proposal** | `CASE#<case_id>` | `PROPOSAL#<proposal_id>` | — | — | — | — | — |
| **Approval** | `CASE#<case_id>` | `APPROVAL#<approval_id>` | — | — | — | — | — |
| **Action** | `CASE#<case_id>` | `ACTION#<action_id>` | — | — | — | — | — |
| **Audit Event** | `CASE#<case_id>` | `AUDIT#<timestamp>#<event_id>` | — | — | — | — | — |
| **Evidence Bundle** | `CASE#<case_id>` | `EVIDENCE#<bundle_id>` | — | — | — | — | — |
| **Expected Delivery** | `LOC#<location_id>` | `DELIVERY#<window_start>#<id>` | `ORG#<org_id>` | `TRACKING#<tracking_number>` | — | — | — |
| **Idempotency Record** | `IDEMP#<idempotency_key>` | `RECORD` | — | — | — | — | `expires_at_epoch` |
| **Ring Webhook Dedup** | `DEDUP#RING#<request_id>` | `RECORD` | — | — | — | — | `expires_at_epoch` |

---

### 3.1 Pre-Ingestion Raw Event Lifecycle and Case Correlation

Raw Ring events arrive at the webhook before an operational case exists. The lifecycle separates event arrival from case correlation:

1. **HMAC Verification Guard**:
   - The webhook checks the HMAC signature before persisting anything.
   - Forged or unsigned requests are rejected immediately (HTTP 401) with **zero database writes**.
2. **Replay & Deduplication**:
   - The request ID is recorded in `DEDUP#RING#<request_id>` using a conditional put.
   - Duplicate submissions are acknowledged safely without creating duplicate raw events or duplicate cases.
3. **Pre-Case Raw Event Storage**:
   - Stored at `PK = EVENT#<event_id>`, `SK = RAW`.
   - Preserves: `event_id`, `request_id`, `device_id`, `event_type`, `occurred_at`, `received_at`, `provenance`, `payload`, `signature_verified=True`, `processing_status='RECEIVED'` (or `'VALIDATED'`).
   - If payload is malformed despite valid signature, stored with `processing_status='QUARANTINED'` and `quarantine_reason` for investigation.
4. **Downstream Case Correlation**:
   - When downstream processing associates or correlates the event to a case:
     - `EVENT#<event_id> / RAW` is updated with `case_id = <case_id>`, `processing_status = 'CORRELATED'`, and `GSI1PK = CASE#<case_id>`, `GSI1SK = EVENT#<occurred_at>`.
     - The case partition receives the enriched `NormalizedEvent` at `PK = CASE#<case_id>, SK = NORM_EVENT#<norm_id>` with a back-reference to `source_event_id`.
   - **No Payload Duplication**: The full raw JSON payload resides solely on the `EVENT#<event_id> / RAW` item, while the case partition contains normalized event metadata.

---

## 4. Query Patterns Matrix

| ID | Access Pattern | Target | Key Condition | Filter / Notes |
|---|---|---|---|---|
| **AP-01** | Get Case Header | Table | `PK = CASE#<case_id> AND SK = CASE` | Enforces `organization_id` match. |
| **AP-02** | Get Complete Case Aggregation | Table | `PK = CASE#<case_id>` | Retrieves header, context, brief, proposals, approvals, actions in 1 roundtrip. |
| **AP-03** | List Recent Cases for Org | GSI1 | `GSI1PK = ORG#<org_id> AND GSI1SK begins_with CASE#` | Scans backward (`ScanIndexForward=False`) for chronological recency. |
| **AP-04** | List Cases by Status for Org | GSI2 | `GSI2PK = ORG#<org_id>#STATUS#<status>` | Directly indexed by status for operator queue filtering without table scans. |
| **AP-05** | List Cases for Location | GSI1 | `GSI1PK = ORG#<org_id> AND GSI1SK begins_with CASE#` | Filter: `location_id = :loc_id`. |
| **AP-06** | Get Audit Timeline for Case | Table | `PK = CASE#<case_id> AND SK begins_with AUDIT#` | Chronologically sorted by `SK` (`AUDIT#<timestamp>#<event_id>`). |
| **AP-07** | Get Approval by ID | Table | `PK = CASE#<case_id> AND SK = APPROVAL#<approval_id>` | Constant-time point read. |
| **AP-08** | Get Action by ID | Table | `PK = CASE#<case_id> AND SK = ACTION#<action_id>` | Constant-time point read. |
| **AP-09** | Find Expected Deliveries by Window | Table | `PK = LOC#<location_id> AND SK BETWEEN DELIVERY#<start> AND DELIVERY#<end>` | Range query for deliveries active at event timestamp. |
| **AP-10** | Lookup Delivery by Tracking | GSI1 | `GSI1PK = ORG#<org_id> AND GSI1SK = TRACKING#<tracking_number>` | Exact tracking lookup. |
| **AP-11** | Check/Acquire Idempotency Lock | Table | `PK = IDEMP#<key> AND SK = RECORD` | Atomic conditional write with TTL. |
| **AP-12** | Check Ring Webhook Dedup | Table | `PK = DEDUP#RING#<request_id> AND SK = RECORD` | Atomic conditional write with 24h replay TTL. |

---

## 5. Write Patterns & Conditional Logic

### 5.1 Case Creation
- **Condition**: `attribute_not_exists(PK)`
- Prevents accidental overwriting of an existing case with identical ID.

### 5.2 Case State Transition & Optimistic Concurrency
- **Condition**: `attribute_exists(PK) AND organization_id = :org_id AND version = :expected_version`
- **Update**:
  ```text
  SET #status = :new_status,
      #version = :new_version,
      updated_at = :now,
      GSI1SK = :new_gsi1sk,
      GSI2PK = :new_gsi2pk,
      GSI2SK = :new_gsi2sk
  ```
- Guarantees that any competing process attempting to modify the case concurrently will encounter a `ConditionalCheckFailedException`, which maps to `VersionMismatchError`.

### 5.3 Human Approval Recording
- **Condition**: `attribute_not_exists(PK) AND :current_case_status = 'APPROVAL_PENDING' AND :case_version = :approved_case_version`
- Atomic update on Case Header:
  - Transition status: `APPROVAL_PENDING → APPROVED`.
  - Record `active_approval_id = approval_id`.
  - Put new item: `PK = CASE#<case_id>, SK = APPROVAL#<approval_id>`.

### 5.4 Action Execution Lock Acquisition
- **Condition**: Case status must be `APPROVED` and `attribute_not_exists(execution_lock)`.
- Updates Case item:
  - `SET #status = 'EXECUTING', execution_lock = :action_id, executing_at = :now`
- Guarantees that even if two operators trigger execution simultaneously or duplicate HTTP requests arrive, only ONE caller can acquire the lock and transition into `EXECUTING`.

### 5.5 Audit Event Append
- **Condition**: `attribute_not_exists(PK) AND attribute_not_exists(SK)`
- Guarantees audit immutability: existing audit entries can never be modified or overwritten.

---

## 6. Idempotency & Replay Protection

Idempotency items have the structure:
- `PK`: `IDEMP#<idempotency_key>`
- `SK`: `RECORD`
- Attributes:
  - `status`: `IN_PROGRESS` | `COMPLETED` | `FAILED`
  - `operation`: e.g. `ring_webhook` | `action_execution`
  - `result`: cached JSON response or reference ID
  - `created_at`: ISO 8601 string
  - `expires_at_epoch`: Unix epoch timestamp (TTL 86400s / 24 hours)

### Protocol:
1. Caller executes conditional `PutItem` with `attribute_not_exists(PK)`.
2. If successful, lock is acquired (`IN_PROGRESS`). Caller executes work, then updates to `COMPLETED` with result.
3. If `ConditionalCheckFailedException` is raised:
   - Read existing record.
   - If `status == 'COMPLETED'`, return cached response safely without re-executing.
   - If `status == 'IN_PROGRESS'`, reject with `AlreadyExecutingError` (or await/retry depending on operation).

---

## 7. TTL Strategy

TTL is applied **strictly to ephemeral deduplication records**:
- `DEDUP#RING#<request_id>`: `expires_at_epoch` = now + 86400 (24 hours).
- `IDEMP#<key>`: `expires_at_epoch` = now + 86400 (24 hours).

**No TTL is applied to**:
- Cases
- Approvals
- Actions
- Audit records
- Evidence metadata
- Policies or configurations

---

## 8. Multi-Tenant Organization Isolation

1. **Storage Boundary**: All Organization-scoped items store `organization_id` as a top-level indexed attribute.
2. **Access Verification**:
   - `get_case(case_id, organization_id)`: Checks `item["organization_id"] == organization_id`. If mismatched, raises `OrganizationAccessDeniedError`.
   - `update_case(..., organization_id)`: Enforces `organization_id = :org_id` in DynamoDB `ConditionExpression`. Cross-tenant mutations will fail at the database engine level.
3. **Partition Segregation**: GSI partition keys for listing include `ORG#<org_id>` prefixes, preventing any cross-tenant data leakage during index queries.

---

## 9. Hot-Key & Cost Considerations

1. **Partition Distribution**: Cases have uniformly distributed UUIDv4 identifiers as partition keys (`CASE#<uuid>`), preventing write hotspots on the base table.
2. **GSI Sharding**: For large organizations with extreme write volume, `GSI1PK` could optionally be sharded by date partition (`ORG#<org_id>#<YYYY-MM>`), but for MVP coworking office volumes, `ORG#<org_id>` provides optimal sub-millisecond query performance without complex fan-out queries.
3. **Sparse Indexes**: `GSI2` only projects Case Header items (omitting audit events, normalized events, and raw payloads), keeping index storage and replication costs minimal.
