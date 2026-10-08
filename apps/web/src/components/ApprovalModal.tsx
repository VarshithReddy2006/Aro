import React from "react";
import { Proposal } from "../types/contracts";

interface ApprovalModalProps {
  isOpen: boolean;
  proposal: Proposal;
  caseVersion: number;
  caseId: string;
  isSubmitting: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export const ApprovalModal: React.FC<ApprovalModalProps> = ({
  isOpen,
  proposal,
  caseVersion,
  caseId,
  isSubmitting,
  onConfirm,
  onClose,
}) => {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="approval-modal-title">
      <div className="modal-dialog">
        <div className="modal-header">
          <h2 id="approval-modal-title" style={{ fontSize: "1.125rem", fontWeight: 700, color: "var(--text-primary)" }}>
            Confirm Human Approval
          </h2>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            disabled={isSubmitting}
            style={{ padding: "4px 8px", fontSize: "0.8125rem" }}
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>

        <div className="modal-body">
          <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginBottom: "16px" }}>
            You are authorizing an irreversible operational action. Verify the exact cryptographic binding:
          </p>

          <div style={{ background: "var(--bg-surface)", padding: "12px 16px", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)", display: "flex", flexDirection: "column", gap: "10px", fontSize: "0.8125rem" }}>
            <div>
              <span style={{ color: "var(--text-muted)", display: "block" }}>Action</span>
              <strong style={{ color: "var(--text-primary)", fontSize: "0.9375rem" }}>
                {proposal.action_type.replace(/_/g, " ")}
              </strong>
            </div>

            <div>
              <span style={{ color: "var(--text-muted)", display: "block" }}>Reason</span>
              <span style={{ color: "var(--text-secondary)" }}>{proposal.reason}</span>
            </div>

            <div>
              <span style={{ color: "var(--text-muted)", display: "block" }}>Proposal Hash (Authoritative)</span>
              <code style={{ fontFamily: "var(--font-family-mono)", color: "#93c5fd", wordBreak: "break-all" }}>
                {proposal.proposal_hash}
              </code>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div>
                <span style={{ color: "var(--text-muted)", display: "block" }}>Bound Case Version</span>
                <strong style={{ color: "var(--text-primary)", fontFamily: "var(--font-family-mono)" }}>
                  v{caseVersion}
                </strong>
              </div>

              <div>
                <span style={{ color: "var(--text-muted)", display: "block" }}>Case Identifier</span>
                <span className="hash-pill">{caseId}</span>
              </div>
            </div>

            {proposal.expires_at && (
              <div>
                <span style={{ color: "var(--text-muted)", display: "block" }}>Authorization Expiration</span>
                <span style={{ color: "var(--text-secondary)" }}>
                  {new Date(proposal.expires_at).toUTCString()}
                </span>
              </div>
            )}
          </div>

          <div style={{ marginTop: "16px", fontSize: "0.75rem", color: "var(--text-muted)" }}>
            * Note: The backend will cryptographically verify that the hash and case version match current state before dispatching any execution.
          </div>
        </div>

        <div className="modal-footer">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onConfirm}
            disabled={isSubmitting}
          >
            {isSubmitting ? "Authorizing..." : "Authorize Action"}
          </button>
        </div>
      </div>
    </div>
  );
};
