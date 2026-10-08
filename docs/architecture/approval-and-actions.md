# Human Approval and Deterministic Action Engine

## 1. Architectural Philosophy & Core Security Invariant

Aro separates contextual reasoning from consequential execution:

> **Core Security Invariant:**
> **NO consequential action may execute unless an authenticated human explicitly approves the exact proposal hash associated with the current case version.**

```text
Physical-world event (Ring)
        ↓
    validated event
        ↓
    operational case
        ↓
contextual understanding
        ↓
  bounded AI brief
        ↓
allowlisted action proposal (SHA-256 hash bound)
        ↓
  HUMAN APPROVAL (Explicit cryptographically bound decision)
        ↓
deterministic execution (Strict allowlist + atomic idempotency lock)
        ↓
evidence + tamper-evident audit trail (SHA-256 hash-chain)
        ↓
    case closure
```

AI explains and proposes.
Deterministic backend code strictly validates and enforces.
Authenticated human operators authorize consequential actions.

---

## 2. Human Approval Boundary & Domain Model

### 2.1 The `Approval` Contract

An approval is an immutable record binding an authorized human decision to a specific proposal hash and case state:

```python
class Approval(BaseModel):
    approval_id: str  # Unique approval identifier (appr_...)
    organization_id: str  # Tenant isolation boundary
    case_id: str  # Bound operational case
    proposal_id: str  # Bound proposal identifier
    proposal_hash: str  # SHA-256 digest of canonical proposal
    approved_by: str  # Authenticated approver user ID
    approved_at: str  # ISO 8601 approval timestamp
    expires_at: str  # ISO 8601 expiration threshold
    decision: ApprovalDecision  # APPROVED or REJECTED
    case_version: int  # Expected case version at approval time
    created_at: str  # Creation timestamp
    updated_at: str  # Last update timestamp
```

### 2.2 Security Preconditions for Approval

When an operator submits `POST /api/cases/{id}/approve`, `ApprovalService` verifies:
1. **Tenant Isolation**: `user.organization_id == case.organization_id`. Cross-tenant access is rejected with `OrganizationAccessDeniedError`.
2. **Role Authorization (RBAC)**: Approver must possess `Role.ADMIN` or `Role.OPERATOR`. `Role.VIEWER` is rejected with `UnauthorizedApproverError`.
3. **Optimistic Locking**: `case.version == expected_case_version`. Outdated client views are rejected with `StateVersionMismatchError`.
4. **State Machine Compliance**: `case.status == CaseStatus.APPROVAL_PENDING`. Direct execution from pending or terminal transitions from closed states are blocked.
5. **Proposal Binding**: `case.active_proposal_id == proposal_id`.
6. **Proposal Hash Verification**: The provided hash must match `proposal.proposal_hash`, recomputed deterministically via `calculate_proposal_hash`. Mismatches raise `ProposalHashMismatchError`.
7. **Expiry Enforcement**: `now <= expires_at`. Expired approvals raise `ApprovalExpiredError`.

---

## 3. Rejection & Expiry Workflows

Human operators can explicitly reject proposals (`POST /api/cases/{id}/reject`).
- A rejection record is created with `decision = ApprovalDecision.REJECTED`.
- The case moves deterministically from `APPROVAL_PENDING` to `UNRESOLVED` with the operator's justification.
- An `APPROVAL_REJECTED` audit event is appended to the tamper-evident hash chain.

If an approval window elapses without human intervention:
- The case transitions to `UNRESOLVED` with closure reason `"Human approval window expired without action"`.
- An `APPROVAL_EXPIRED` audit event is recorded in the hash chain.

---

## 4. Deterministic Action Execution Engine

Consequential actions are never executed by AI models or external agents. They are dispatched solely by the deterministic `ActionExecutor`.

### 4.1 Strict Allowlist Enforcement

The system strictly executes allowlisted action types:
- `NOTIFY_OPERATOR`: Formats and dispatches operational notification to on-duty staff.
- `MARK_FOR_REVIEW`: Enqueues the case in the operator manual triage queue.
- `REQUEST_OPERATOR_CONFIRMATION`: Generates structured confirmation requests for physical security checks.
- `RECORD_NO_ACTION`: Records justification for benign after-hours activity.

Any action type outside this allowlist raises `ActionNotAllowlistedError`.

### 4.2 Idempotency and Concurrency Protection

To guarantee **exactly-once execution**:
1. **Idempotency Key**: Derived deterministically as `idem_exec_{case_id}_{approval_id}_{action_type}_{proposal_hash[:8]}`.
2. **Idempotency Lock**: `IdempotencyRepository.acquire_lock` guarantees single-flight execution. Replayed requests return cached execution receipts with `was_idempotent = True`.
3. **Atomic Execution Lock**: `ActionRepository.acquire_execution_lock` verifies that `case.status == CaseStatus.APPROVED` and atomically transitions the case to `EXECUTING`. Concurrent execution requests raise `AlreadyExecutingError`.

---

## 5. Tamper-Evident Audit Timeline & Hash Chaining

Every lifecycle state change and authorization event is sealed in an append-only timeline using SHA-256 hash chaining.

### 5.1 Chain Structure

```text
Genesis Event (e.g. CASE_CREATED)
  previous_hash = "0000...0000" (64 zeros)
  current_hash  = SHA-256(canonical JSON)
        ↓
Approval Event (APPROVAL_RECORDED)
  previous_hash = <current_hash of Genesis Event>
  current_hash  = SHA-256(canonical JSON)
        ↓
Action Started (ACTION_STARTED)
  previous_hash = <current_hash of Approval Event>
  current_hash  = SHA-256(canonical JSON)
        ↓
Action Completed (ACTION_COMPLETED)
  previous_hash = <current_hash of Action Started>
  current_hash  = SHA-256(canonical JSON)
```

### 5.2 Verification Utility

`verify_audit_chain(timeline: list[AuditEvent]) -> bool`:
- Verifies that every event's `current_hash` matches its recomputed canonical digest.
- Verifies that the first event links to `GENESIS_HASH`.
- Verifies that each subsequent event's `previous_hash` matches its predecessor's `current_hash`.
- Any modification to metadata, timestamps, or action types invalidates the cryptographic verification.

---

## 6. HTTP API Specification

### 6.1 `POST /api/cases/{id}/approve`
**Headers**: `x-user-id`, `x-user-role`, `x-organization-id`  
**Request Body**:
```json
{
  "proposal_id": "prop_12345",
  "proposal_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
  "case_version": 1,
  "expires_at": "2026-10-08T23:00:00Z"
}
```
**Response**: `200 OK`
```json
{
  "status": "APPROVED",
  "approval": {
    "approval_id": "appr_98765",
    "case_id": "case_12345",
    "decision": "APPROVED",
    "case_version": 1
  }
}
```

### 6.2 `POST /api/cases/{id}/reject`
**Headers**: `x-user-id`, `x-user-role`, `x-organization-id`  
**Request Body**:
```json
{
  "proposal_id": "prop_12345",
  "proposal_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
  "reason": "Authorized security guard inspection",
  "case_version": 1
}
```
**Response**: `200 OK`

### 6.3 `POST /api/cases/{id}/execute`
**Headers**: `x-user-id`, `x-user-role`, `x-organization-id`  
**Request Body**:
```json
{
  "approval_id": "appr_98765",
  "case_version": 2,
  "idempotency_key": "idemp_custom_key_1"
}
```
**Response**: `200 OK`
```json
{
  "status": "EXECUTED",
  "action": {
    "action_id": "act_45678",
    "status": "SUCCEEDED",
    "action_type": "NOTIFY_OPERATOR"
  },
  "case_status": "COMPLETED",
  "was_idempotent": false
}
```
