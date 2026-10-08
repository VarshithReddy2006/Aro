import React from "react";
import { ActionType } from "../types/contracts";

export const PoliciesPage: React.FC = () => {
  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }}>
          Operational Policies & Action Whitelist
        </h2>
        <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", marginTop: "2px" }}>
          Active security invariants and deterministic execution boundaries
        </p>
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Allowlisted Action Catalog</h3>
          <span className="brand-badge" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#34d399" }}>
            Strict Whitelist Enforced
          </span>
        </div>
        <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginBottom: "16px" }}>
          The backend will reject any action request whose type is not explicitly defined in the allowlist. AI models cannot define or invent new action types.
        </p>

        <div className="table-container">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Action Type</th>
                <th>Approval Requirement</th>
                <th>Allowed Roles</th>
                <th>Idempotency Key</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <strong>{ActionType.NOTIFY_OPERATOR}</strong>
                </td>
                <td><span style={{ color: "#fbbf24", fontWeight: 600 }}>Human Approval Required</span></td>
                <td>OPERATOR, ADMIN</td>
                <td><code>HASH(case_id, proposal_hash)</code></td>
              </tr>
              <tr>
                <td>
                  <strong>{ActionType.REQUEST_INFO}</strong>
                </td>
                <td><span style={{ color: "#fbbf24", fontWeight: 600 }}>Human Approval Required</span></td>
                <td>OPERATOR, ADMIN</td>
                <td><code>HASH(case_id, proposal_hash)</code></td>
              </tr>
              <tr>
                <td>
                  <strong>{ActionType.LOG_EXCEPTION}</strong>
                </td>
                <td><span style={{ color: "#34d399", fontWeight: 600 }}>Internal / Non-Consequential</span></td>
                <td>SYSTEM, OPERATOR</td>
                <td><code>HASH(case_id, proposal_hash)</code></td>
              </tr>
              <tr>
                <td>
                  <strong>{ActionType.NO_ACTION}</strong>
                </td>
                <td><span style={{ color: "#34d399", fontWeight: 600 }}>Automatic Case Resolution</span></td>
                <td>OPERATOR, ADMIN</td>
                <td><code>HASH(case_id, proposal_hash)</code></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Core Security Invariants</h3>
        </div>
        <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: "12px", fontSize: "0.875rem", color: "var(--text-secondary)" }}>
          <li style={{ display: "flex", gap: "10px" }}>
            <span style={{ color: "#3b82f6", fontWeight: 700 }}>1.</span>
            <div>
              <strong style={{ color: "var(--text-primary)" }}>Zero Autonomous Action:</strong> Under no circumstance does Bedrock AI or any backend worker execute consequential actions without explicit human approval.
            </div>
          </li>
          <li style={{ display: "flex", gap: "10px" }}>
            <span style={{ color: "#3b82f6", fontWeight: 700 }}>2.</span>
            <div>
              <strong style={{ color: "var(--text-primary)" }}>Cryptographic Proposal Binding:</strong> Approvals authorize only the exact SHA-256 hash of the proposal. Any parameter change invalidates the approval token.
            </div>
          </li>
          <li style={{ display: "flex", gap: "10px" }}>
            <span style={{ color: "#3b82f6", fontWeight: 700 }}>3.</span>
            <div>
              <strong style={{ color: "var(--text-primary)" }}>State Version Concurrency:</strong> Approvals are bound to a specific case version (e.g. v2). If case state advances before approval occurs, a 409 STALE_PROPOSAL error prevents execution.
            </div>
          </li>
          <li style={{ display: "flex", gap: "10px" }}>
            <span style={{ color: "#3b82f6", fontWeight: 700 }}>4.</span>
            <div>
              <strong style={{ color: "var(--text-primary)" }}>Tamper-Evident Audit Chaining:</strong> Every audit transition records the hash of the preceding event, creating an immutable SHA-256 forward-linked chain.
            </div>
          </li>
        </ul>
      </div>
    </div>
  );
};
