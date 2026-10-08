import React, { useState } from "react";
import { Proposal } from "../types/contracts";

interface RejectionModalProps {
  isOpen: boolean;
  proposal: Proposal;
  caseVersion: number;
  caseId: string;
  isSubmitting: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}

export const RejectionModal: React.FC<RejectionModalProps> = ({
  isOpen,
  proposal,
  caseVersion,
  caseId,
  isSubmitting,
  onConfirm,
  onClose,
}) => {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) {
      setError("An explicit rejection reason is required for audit compliance.");
      return;
    }
    setError(null);
    onConfirm(reason.trim());
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="reject-modal-title">
      <div className="modal-dialog">
        <form onSubmit={handleSubmit}>
          <div className="modal-header">
            <h2 id="reject-modal-title" style={{ fontSize: "1.125rem", fontWeight: 700, color: "var(--text-primary)" }}>
              Reject Proposal
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
              Rejection will dismiss this proposed action and record an immutable audit entry against case version v{caseVersion}.
            </p>

            <div style={{ marginBottom: "16px" }}>
              <label htmlFor="rejection-reason" style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "var(--text-primary)", marginBottom: "6px" }}>
                Rejection Reason *
              </label>
              <textarea
                id="rejection-reason"
                rows={3}
                style={{
                  width: "100%",
                  backgroundColor: "var(--bg-input)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-md)",
                  padding: "8px 12px",
                  color: "var(--text-primary)",
                  fontSize: "0.875rem",
                  fontFamily: "inherit",
                }}
                placeholder="State why this proposed action is rejected..."
                value={reason}
                onChange={(e) => {
                  setReason(e.target.value);
                  if (error) setError(null);
                }}
                disabled={isSubmitting}
              />
              {error && (
                <div style={{ color: "#f87171", fontSize: "0.75rem", marginTop: "4px" }}>
                  {error}
                </div>
              )}
            </div>

            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Bound Proposal ID: <span className="hash-pill">{proposal.proposal_id}</span>
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
              type="submit"
              className="btn btn-danger"
              disabled={isSubmitting}
            >
              {isSubmitting ? "Rejecting..." : "Confirm Rejection"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
