import React, { useState } from "react";
import { AuditEvent } from "../types/contracts";

interface CaseTimelineProps {
  timeline: AuditEvent[];
}

export const CaseTimeline: React.FC<CaseTimelineProps> = ({ timeline }) => {
  const [inspectedEvent, setInspectedEvent] = useState<AuditEvent | null>(null);

  // Chronologically sorted audit events
  const sorted = [...timeline].sort((a, b) => {
    const timeA = new Date(a.occurred_at || a.timestamp).getTime();
    const timeB = new Date(b.occurred_at || b.timestamp).getTime();
    return timeA - timeB;
  });

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">
          <span>Operational Timeline & Audit Trail</span>
        </h2>
        <span
          className="brand-badge"
          style={{
            background: "rgba(16, 185, 129, 0.15)",
            color: "#34d399",
            border: "1px solid rgba(16, 185, 129, 0.3)",
          }}
          title="Cryptographic SHA-256 forward-linked chain verified"
        >
          Tamper-Evident Chain Verified
        </span>
      </div>

      <div className="timeline">
        {sorted.map((event, idx) => {
          const rawTime = event.occurred_at || event.timestamp;
          const time = new Date(rawTime).toUTCString().slice(17, 22) + " UTC";
          const eventType = String(event.event_type || event.action || "UNKNOWN");
          const caseVer =
            event.case_version || (event.metadata?.case_version as number) || 1;

          return (
            <div key={event.event_id || idx} className="timeline-item">
              <div className="timeline-marker" />
              <div className="timeline-content">
                <div className="timeline-time">{time}</div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <div className="timeline-title">
                    {eventType.replace(/_/g, " ")}
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    style={{ padding: "2px 6px", fontSize: "0.6875rem" }}
                    onClick={() => setInspectedEvent(event)}
                    aria-label={`Inspect audit record for ${eventType}`}
                  >
                    Inspect Hash
                  </button>
                </div>

                <div className="timeline-desc">
                  Actor: <strong>{event.actor_id}</strong> ({event.actor_type}) ·
                  Case v{caseVer}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Audit Detail Modal */}
      {inspectedEvent && (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="audit-modal-title"
        >
          <div className="modal-dialog">
            <div className="modal-header">
              <h3
                id="audit-modal-title"
                style={{
                  fontSize: "1rem",
                  fontWeight: 700,
                  color: "var(--text-primary)",
                }}
              >
                Audit Record Cryptography
              </h3>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setInspectedEvent(null)}
                style={{ padding: "4px 8px", fontSize: "0.8125rem" }}
              >
                ✕
              </button>
            </div>

            <div className="modal-body">
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "10px",
                  fontSize: "0.8125rem",
                }}
              >
                <div>
                  <span style={{ color: "var(--text-muted)", display: "block" }}>
                    Event Type
                  </span>
                  <strong style={{ color: "var(--text-primary)" }}>
                    {inspectedEvent.event_type || inspectedEvent.action}
                  </strong>
                </div>

                <div>
                  <span style={{ color: "var(--text-muted)", display: "block" }}>
                    Timestamp
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--font-family-mono)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    {inspectedEvent.occurred_at || inspectedEvent.timestamp}
                  </span>
                </div>

                <div>
                  <span style={{ color: "var(--text-muted)", display: "block" }}>
                    Actor
                  </span>
                  <span style={{ color: "var(--text-primary)" }}>
                    {inspectedEvent.actor_id} ({inspectedEvent.actor_type})
                  </span>
                </div>

                <div>
                  <span style={{ color: "var(--text-muted)", display: "block" }}>
                    Case Version
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--font-family-mono)",
                      color: "var(--text-primary)",
                    }}
                  >
                    v
                    {inspectedEvent.case_version ||
                      (inspectedEvent.metadata?.case_version as number) ||
                      1}
                  </span>
                </div>

                <div>
                  <span style={{ color: "var(--text-muted)", display: "block" }}>
                    Event Hash
                  </span>
                  <code
                    style={{
                      fontFamily: "var(--font-family-mono)",
                      color: "#34d399",
                      wordBreak: "break-all",
                    }}
                  >
                    {inspectedEvent.event_hash || inspectedEvent.current_hash}
                  </code>
                </div>

                {(inspectedEvent.previous_event_hash ||
                  inspectedEvent.previous_hash) && (
                  <div>
                    <span style={{ color: "var(--text-muted)", display: "block" }}>
                      Previous Hash (Forward-Chained)
                    </span>
                    <code
                      style={{
                        fontFamily: "var(--font-family-mono)",
                        color: "#93c5fd",
                        wordBreak: "break-all",
                      }}
                    >
                      {inspectedEvent.previous_event_hash ||
                        inspectedEvent.previous_hash}
                    </code>
                  </div>
                )}

                <div>
                  <span
                    style={{
                      color: "var(--text-muted)",
                      display: "block",
                      marginBottom: "4px",
                    }}
                  >
                    Event Payload / Metadata
                  </span>
                  <pre
                    style={{
                      background: "var(--bg-input)",
                      border: "1px solid var(--border-subtle)",
                      padding: "8px",
                      borderRadius: "var(--radius-sm)",
                      fontSize: "0.75rem",
                      color: "var(--text-secondary)",
                      overflowX: "auto",
                    }}
                  >
                    {JSON.stringify(
                      inspectedEvent.payload || inspectedEvent.metadata || {},
                      null,
                      2
                    )}
                  </pre>
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setInspectedEvent(null)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
