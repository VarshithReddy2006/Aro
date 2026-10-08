# Aro — Operator Experience & Case Workflow Architecture

## 1. Overview & Core Product Principle

Aro is an AI-assisted operational intelligence and human decision-support console for physical-world events.

The authoritative workflow sequence is:

```text
Physical-world event
      ↓
Validated Ring event
      ↓
Operational case
      ↓
Deterministic context
      ↓
Bounded AI brief
      ↓
Allowlisted proposal
      ↓
HUMAN OPERATOR APPROVAL
      ↓
Deterministic execution
      ↓
Idempotency replay cache
      ↓
Tamper-evident audit trail
      ↓
Case closure
```

**Core Principle:**
> The frontend is an interface for operational decision support, **not** an autonomous security system or security boundary.
>
> The UI explains.
> The AI proposes.
> The human decides.
> The backend enforces.

---

## 2. Frontend Security & Trust Boundaries

The frontend is strictly a consumer of the backend security model:

1. **Authoritative Enforcement Server-Side:**
   - Authorization, approval state, case version, cryptographic proposal hash, action permissions, execution permissions, and tenant organization identity are strictly verified and enforced by the backend.
   - Hiding UI controls or disabling buttons on the client is an ergonomics feature, **never** a security boundary.

2. **Immutable Approval Binding:**
   - Approvals must send `{ proposal_id, proposal_hash, case_version }`.
   - The frontend never calculates authorization independently and never submits a naked `{ "approved": true }` payload.
   - Any mismatch between the operator's reviewed proposal hash and the server's case state returns `409 PROPOSAL_HASH_MISMATCH` or `409 STATE_VERSION_MISMATCH`.

3. **Zero Autonomous Dispatch:**
   - The frontend never triggers action dispatch without explicit operator review and confirmation.
   - The frontend never generates arbitrary tool calls or calls arbitrary unvetted endpoints.

4. **Credential Isolation:**
   - No AWS credentials, Ring OAuth secrets, or AI model keys are ever stored or accessible on the client.

---

## 3. Frontend Architecture & Technology Stack

The operator web application is structured under `apps/web`:

- **Framework:** React 19 + TypeScript (strict mode)
- **Tooling:** Vite 6 (fast ESM dev server and optimized production bundles)
- **Routing:** React Router DOM (client-side SPA navigation)
- **Styling:** Vanilla CSS design tokens (`index.css`) emphasizing a calm, high-contrast, professional operations console palette
- **Testing:** Vitest + React Testing Library + JSDOM

### Directory Structure

```text
apps/web/
├── src/
│   ├── api/
│   │   ├── client.ts         # Typed API client with demo mode & error mapping
│   │   └── mockData.ts       # Deterministic demo fixtures (provenance: demo_synthetic)
│   ├── components/
│   │   ├── AppShell.tsx      # Global app shell with role switcher & demo indicator
│   │   ├── StatusBadge.tsx   # Accessible textual status badges
│   │   ├── EventCard.tsx     # Physical observation display & Ring boundaries
│   │   ├── CaseContextCard.tsx # Deterministic Known vs Unknown facts
│   │   ├── AIBriefCard.tsx   # Bounded AI brief with operational notice
│   │   ├── ProposalReviewCard.tsx # Human approval boundary container
│   │   ├── ApprovalModal.tsx # Confirmation modal binding exact hash & version
│   │   ├── RejectionModal.tsx # Rejection modal requiring audit rationale
│   │   ├── ActionReceiptCard.tsx # Execution receipt & idempotency replay notice
│   │   └── CaseTimeline.tsx  # Chronological audit feed & hash inspector
│   ├── pages/
│   │   ├── DashboardPage.tsx # Operational overview, metrics & attention queue
│   │   ├── CasesPage.tsx     # Operational case list with status filters
│   │   ├── CaseDetailPage.tsx # Core golden-path decision workflow
│   │   ├── EvidencePage.tsx  # Verified physical sensor evidence registry
│   │   ├── PoliciesPage.tsx  # Allowlisted action types & security invariants
│   │   └── SettingsPage.tsx  # Facility schedule & designated hardware devices
│   ├── types/
│   │   ├── contracts.ts      # Canonical contract mirror of packages/contracts
│   │   └── api.ts            # Typed request/response and error payloads
│   ├── App.tsx               # Main routing & state setup
│   ├── index.css             # Operations design system tokens
│   └── main.tsx              # Application entrypoint
└── dist/                     # Optimized production bundle
```

---

## 4. Routing Table

| Route | View | Description |
|---|---|---|
| `/` | Redirect | Redirects to `/dashboard` |
| `/dashboard` | `DashboardPage` | Operational summary metrics, priority attention queue, recent audit feed |
| `/cases` | `CasesPage` | Operational cases table with filtering by status |
| `/cases/:caseId` | `CaseDetailPage` | End-to-end case detail, context evaluation, AI brief, and human approval workflow |
| `/evidence` | `EvidencePage` | Ingested sensor evidence registry (no simulated video/media) |
| `/policies` | `PoliciesPage` | Whitelisted action catalog and active security invariants |
| `/settings` | `SettingsPage` | Facility hours, timezone, and designated entrance hardware configuration |

---

## 5. Case Workflow & Human Approval Boundary

The case detail screen is organized into a disciplined, chronological hierarchy:

```text
CASE HEADER (Case ID, Location, Status, Case Version)
    ↓
EVENT CARD (Doorbell activity observed, timestamp, designated door)
    ↓
CONTEXT CARD (Known vs Unknown facts evaluated deterministically)
    ↓
AI BRIEF CARD (Bounded summary, facts, unknowns with advisory guardrail)
    ↓
PROPOSAL REVIEW CARD (Proposed action, reason, urgency, parameters)
    ↓
HUMAN APPROVAL BOUNDARY (Clear boundary container; modal confirmation)
    ↓
EXECUTION STATUS & ACTION RECEIPT (Execution ID, outcome, idempotency status)
    ↓
TIMELINE & AUDIT TRAIL (Chronological audit records with SHA-256 chain inspection)
```

### Stale Proposal UX (Concurrency Handling)

If the case version advances on the server or an altered proposal hash is detected before approval:
1. The server returns HTTP 409 (`STATE_VERSION_MISMATCH` or `PROPOSAL_HASH_MISMATCH`).
2. The UI intercepts this error and presents a dedicated operational banner:
   > **Proposal is no longer current**
   > The case changed after this proposal was generated. For safety, the previous proposal cannot be approved or executed.
   > [Refresh case to review latest state]
3. Approval is **never** retried automatically.

### Role-Based Access Control (RBAC) UX

- **OPERATOR & ADMIN:** May approve or reject proposals, and dispatch approved actions.
- **VIEWER:** A read-only observer. The UI replaces the Approve/Reject buttons with an informative role notification (*"Active role is VIEWER. Approval and rejection require OPERATOR or ADMIN permissions"*). If an API call is attempted directly, the backend/client returns `403 UNAUTHORIZED_APPROVER`.

---

## 6. Deterministic Action Execution & Idempotency

When an action executes:
1. The backend issues a deterministic action receipt with `action_id`, `status: SUCCEEDED`, and `idempotency_key`.
2. If the operator or network triggers a duplicate execution for the same approval/case, the backend returns the cached receipt with `was_idempotent: true`.
3. The UI presents an explicit notification:
   > **Action already executed:** This request returned the existing execution result from DynamoDB idempotency cache. No duplicate action was performed.

---

## 7. Tamper-Evident Audit Trail

Every state transition produces a cryptographic audit record:
- Preceding event hash (`previous_hash`) is concatenated with the new event payload to calculate `current_hash` via SHA-256.
- The UI displays a **Tamper-Evident Chain Verified** badge.
- Operators can click **Inspect Hash** on any timeline entry to review the raw SHA-256 event hash, parent hash, actor, and payload metadata.

---

## 8. Offline Demo Mode (`demo_synthetic`)

Aro provides a full offline demo mode without requiring AWS, Bedrock, or Ring credentials:
- Ingestion fixtures and cases carry `provenance: "demo_synthetic"`.
- The top navigation bar presents a persistent `Demo Mode (demo_synthetic)` status pill.
- The client maintains an in-memory persistence store, cryptographic hash chaining, version counters, and idempotency store mirroring DynamoDB behaviors.

---

## 9. Accessibility & UX Integrity

1. **No Color-Only State Communication:**
   - Statuses always include explicit text labels (e.g. `APPROVAL PENDING`, `APPROVED`, `EXECUTING`, `COMPLETED`, `REJECTED`, `UNRESOLVED`).
2. **Accessible Dialogs:**
   - Modals use `role="dialog"`, `aria-modal="true"`, and proper header labeling (`aria-labelledby`).
3. **Contrast & Typography:**
   - High-contrast slate/navy palette meets WCAG AA standards.
   - Mono-spaced fonts are used for cryptographic hashes, versions, and ISO timestamps.
4. **Factual Integrity Guardrails:**
   - The UI never asserts unsupported claims such as "Package detected", "Courier identified", or "Threat detected".
   - It strictly displays verified physical facts: *"Doorbell activity observed"*, *"After-hours entrance activity"*, *"Expected delivery context"*.
