import React from "react";
import { Proposal, CaseStatus, Role } from "../types/contracts";

interface ProposalReviewCardProps {
  proposal: Proposal;
  caseVersion: number;
  caseStatus: CaseStatus;
  currentRole: Role;
  onApproveClick: () => void;
  onRejectClick: () => void;
}

export const ProposalReviewCard: React.FC<ProposalReviewCardProps> = ({
  proposal,
  caseVersion,
  caseStatus,
  currentRole,
  onApproveClick,
  onRejectClick,
}) => {
  const isPending = caseStatus === CaseStatus.APPROVAL_PENDING;
  const isViewer = currentRole === Role.VIEWER;
  const expiresAtFormatted = proposal.expires_at
    ? new Date(proposal.expires_at).toUTCString()
    : "No expiry specified";

  const isExpired = proposal.expires_at
    ? new Date(proposal.expires_at).getTime() < Date.now()
    : false;

  return (
    <div className="card" style={{ borderColor: isPending ? "var(--boundary-accent)" : "var(--border-subtle)" }}>
      <div className="card-header">
        <h2 className="card-title">
          <span style={{ color: "#60a5fa", marginRight: "8px", fontSize: "0.75rem", padding: "2px 6px", background: "rgba(59, 130, 246, 0.15)", borderRadius: "4px", border: "1px solid rgba(59, 130, 246, 0.3)" }}>
            AI PROPOSAL
          </span>
          <span>Allowlisted Action Proposal</span>
        </h2>
        <span className="hash-pill" title="Canonical SHA-256 hash of this proposal payload">
          Hash: {proposal.proposal_hash ? `${proposal.proposal_hash.slice(0, 8)}...${proposal.proposal_hash.slice(-8)}` : "None"}
        </span>
      </div>

      <div style={{ marginBottom: "16px" }}>
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
          Proposed Action
        </div>
        <div style={{ fontSize: "1.125rem", fontWeight: 700, color: "var(--text-primary)", marginTop: "2px" }}>
          {proposal.action_type.replace(/_/g, " ")}
        </div>
      </div>

      <div style={{ marginBottom: "16px" }}>
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
          Operational Rationale
        </div>
        <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginTop: "2px", lineHeight: 1.5 }}>
          {proposal.reason}
        </p>
      </div>

      {/* Action Parameters Table */}
      <div style={{ background: "var(--bg-surface)", padding: "12px 16px", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)", marginBottom: "16px" }}>
        <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", marginBottom: "8px" }}>
          Execution Parameters
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px", fontSize: "0.8125rem" }}>
          {Object.entries(proposal.parameters || {}).map(([key, val]) => (
            <div key={key}>
              <span style={{ color: "var(--text-muted)", textTransform: "capitalize" }}>{key.replace(/_/g, " ")}: </span>
              <strong style={{ color: "var(--text-primary)" }}>{String(val)}</strong>
            </div>
          ))}
        </div>
      </div>

      {/* Cryptographic & Version Bindings */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", fontSize: "0.8125rem", marginBottom: "20px" }}>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Target Case Version: </span>
          <strong style={{ color: "var(--text-primary)", fontFamily: "var(--font-family-mono)" }}>
            v{caseVersion}
          </strong>
        </div>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Proposal ID: </span>
          <span className="hash-pill">{proposal.proposal_id}</span>
        </div>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Expires At: </span>
          <span style={{ color: isExpired ? "#f87171" : "var(--text-secondary)" }}>
            {expiresAtFormatted}
          </span>
        </div>
      </div>

      {/* Human Approval Required Boundary */}
      {isPending && !isExpired && (
        <div className="approval-boundary-card">
          <div className="boundary-banner">
            <span style={{ color: "#fbbf24", marginRight: "8px", fontSize: "0.75rem", padding: "2px 6px", background: "rgba(245, 158, 11, 0.15)", borderRadius: "4px", border: "1px solid rgba(245, 158, 11, 0.3)", fontWeight: 700 }}>
              HUMAN DECISION
            </span>
            <span className="boundary-title">Human Approval Required</span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
              Boundary Rule: Human Operator In The Loop
            </span>
          </div>

          <div className="boundary-body">
            Review this proposal before approving. Approval authorizes <strong>only</strong> this exact proposal hash (
            <code style={{ fontFamily: "var(--font-family-mono)", color: "#93c5fd" }}>
              {proposal.proposal_hash?.slice(0, 10)}...
            </code>
            ) bound strictly to Case Version <strong>v{caseVersion}</strong>.
          </div>

          {isViewer ? (
            <div style={{ fontSize: "0.8125rem", color: "#fbbf24", background: "rgba(245, 158, 11, 0.1)", padding: "8px 12px", borderRadius: "var(--radius-sm)" }}>
              Active role is <strong>VIEWER</strong>. Approval and rejection actions require <strong>OPERATOR</strong> or <strong>ADMIN</strong> permissions.
            </div>
          ) : (
            <div className="boundary-actions">
              <button
                type="button"
                className="btn btn-danger"
                onClick={onRejectClick}
                aria-label="Reject proposal"
              >
                Reject Proposal
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={onApproveClick}
                aria-label="Approve proposal"
              >
                Approve Proposal
              </button>
            </div>
          )}
        </div>
      )}

      {isExpired && isPending && (
        <div className="stale-proposal-alert">
          <div className="stale-proposal-title">Approval Expired</div>
          <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
            This approval window has expired ({expiresAtFormatted}). It can no longer authorize action execution.
            Please regenerate or review updated case state.
          </p>
        </div>
      )}
    </div>
  );
};
