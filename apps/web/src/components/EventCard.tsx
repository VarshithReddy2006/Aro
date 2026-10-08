import React from "react";
import { Case, CaseContext } from "../types/contracts";

interface EventCardProps {
  caseData: Case;
  context?: CaseContext;
}

export const EventCard: React.FC<EventCardProps> = ({ caseData, context }) => {
  const effectiveContext = context || caseData.context;
  const isAfterHours = effectiveContext?.is_after_hours ?? effectiveContext?.known_facts?.is_after_hours ?? true;
  const isDesignated = effectiveContext?.designated_entrance ?? effectiveContext?.known_facts?.is_designated_entrance ?? true;
  const rawOccurred = caseData.occurred_at || caseData.created_at;
  const occurredAtFormatted = rawOccurred ? new Date(rawOccurred).toUTCString() : "Observed recently";
  const displayLocation = caseData.location || caseData.location_id;

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">
          <span>Observed Physical Event</span>
        </h2>
        <span className="hash-pill">Source: Ring Event Ingestion</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "16px" }}>
        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Event Nature
          </div>
          <div style={{ fontWeight: 600, fontSize: "0.9375rem", color: "var(--text-primary)" }}>
            Doorbell activity observed
          </div>
        </div>

        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Device Location
          </div>
          <div style={{ fontWeight: 600, fontSize: "0.9375rem", color: "var(--text-primary)" }}>
            {displayLocation}
          </div>
        </div>

        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Observed Timestamp
          </div>
          <div style={{ fontFamily: "var(--font-family-mono)", fontSize: "0.875rem", color: "var(--text-primary)" }}>
            {occurredAtFormatted}
          </div>
        </div>

        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Entrance Classification
          </div>
          <div style={{ fontWeight: 600, fontSize: "0.9375rem", color: isDesignated ? "#34d399" : "#fbbf24" }}>
            {isDesignated ? "Designated primary entrance" : "Secondary entrance"}
          </div>
        </div>
      </div>

      <div style={{ background: "var(--bg-surface)", padding: "12px 16px", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <span style={{ fontSize: "0.75rem", fontWeight: 700, color: isAfterHours ? "#fbbf24" : "#34d399", textTransform: "uppercase" }}>
            {isAfterHours ? "After-Hours Window" : "Standard Hours Window"}
          </span>
          <span style={{ fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
            — Physical sensor motion detected during operational schedule.
          </span>
        </div>
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "6px" }}>
          <strong>Boundary Note:</strong> Ring hardware detects motion/doorbell press only. It does not provide certified package detection or courier identification.
        </div>
      </div>
    </div>
  );
};
