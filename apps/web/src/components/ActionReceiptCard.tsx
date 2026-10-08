import React from "react";
import { Action, ActionStatus } from "../types/contracts";
import { StatusBadge } from "./StatusBadge";

interface ActionReceiptCardProps {
  action?: Action;
}

export const ActionReceiptCard: React.FC<ActionReceiptCardProps> = ({ action }) => {
  if (!action) {
    return null;
  }

  const isCompleted = action.status === ActionStatus.COMPLETED;
  const wasIdempotent = (action as any).was_idempotent === true;
  const executedAtFormatted = action.executed_at
    ? new Date(action.executed_at).toUTCString()
    : "In progress";

  return (
    <div className="card" style={{ borderColor: isCompleted ? "var(--status-completed-border)" : "var(--border-subtle)" }}>
      <div className="card-header">
        <h2 className="card-title">
          <span style={{ color: "#34d399", marginRight: "8px", fontSize: "0.75rem", padding: "2px 6px", background: "rgba(52, 211, 153, 0.15)", borderRadius: "4px", border: "1px solid rgba(52, 211, 153, 0.3)" }}>
            EXECUTION RESULT
          </span>
          <span>Deterministic Action Receipt</span>
        </h2>
        <StatusBadge status={action.status} />
      </div>

      {wasIdempotent && (
        <div style={{ background: "rgba(59, 130, 246, 0.1)", border: "1px solid rgba(59, 130, 246, 0.3)", borderRadius: "var(--radius-md)", padding: "10px 14px", marginBottom: "16px", fontSize: "0.8125rem", color: "#93c5fd" }}>
          <strong>Action already executed:</strong> This request returned the existing execution result from DynamoDB idempotency cache. No duplicate action was performed.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px", marginBottom: "16px" }}>
        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Action Executed
          </div>
          <div style={{ fontSize: "0.9375rem", fontWeight: 700, color: "var(--text-primary)" }}>
            {action.action_type.replace(/_/g, " ")}
          </div>
        </div>

        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Execution ID
          </div>
          <div className="hash-pill" style={{ display: "inline-block", marginTop: "2px" }}>
            {action.action_id}
          </div>
        </div>

        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Executed At
          </div>
          <div style={{ fontFamily: "var(--font-family-mono)", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
            {executedAtFormatted}
          </div>
        </div>

        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Idempotency Status
          </div>
          <div style={{ fontSize: "0.875rem", fontWeight: 600, color: wasIdempotent ? "#60a5fa" : "var(--text-primary)" }}>
            {wasIdempotent ? "Replay Cached Result" : "Initial Execution"}
          </div>
        </div>
      </div>

      {/* Execution Result Payload */}
      {action.result && (
        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "6px" }}>
            Execution Output / Response
          </div>
          <pre
            style={{
              backgroundColor: "var(--bg-input)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-md)",
              padding: "10px 14px",
              fontFamily: "var(--font-family-mono)",
              fontSize: "0.75rem",
              color: "#34d399",
              overflowX: "auto",
            }}
          >
            {JSON.stringify(action.result, null, 2)}
          </pre>
        </div>
      )}

      {action.error && (
        <div style={{ marginTop: "12px", color: "#f87171", fontSize: "0.8125rem" }}>
          <strong>Execution Failure:</strong> {action.error}
        </div>
      )}
    </div>
  );
};
