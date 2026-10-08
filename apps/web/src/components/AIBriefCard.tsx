import React from "react";
import { CaseBrief } from "../types/contracts";

interface AIBriefCardProps {
  brief?: CaseBrief;
}

export const AIBriefCard: React.FC<AIBriefCardProps> = ({ brief }) => {
  if (!brief) {
    return (
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Bounded AI Brief</h2>
        </div>
        <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
          AI operational brief has not been generated for this case.
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">
          <span>Bounded Operational AI Brief</span>
        </h2>
        <span className="brand-badge" style={{ background: "rgba(59, 130, 246, 0.15)", color: "#93c5fd" }}>
          Model: Claude 3.5 Sonnet (Deterministic Bounds)
        </span>
      </div>

      {/* Advisory Guardrail Banner */}
      <div
        style={{
          background: "rgba(30, 41, 59, 0.7)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          padding: "10px 14px",
          marginBottom: "16px",
          fontSize: "0.8125rem",
          color: "var(--text-secondary)",
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}
      >
        <span style={{ color: "#60a5fa", fontWeight: 700 }}>AI BOUNDARY:</span>
        <span>
          AI operational briefing is strictly descriptive and validated against verified deterministic context.
          The AI engine cannot execute actions, dispatch notifications, or modify case state autonomously.
        </span>
      </div>

      <div style={{ marginBottom: "16px" }}>
        <h3 style={{ fontSize: "0.8125rem", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "6px" }}>
          Operational Summary
        </h3>
        <p style={{ fontSize: "0.9375rem", color: "var(--text-primary)", lineHeight: 1.6 }}>
          {brief.summary}
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
        {/* Identified Facts in Brief */}
        <div style={{ background: "var(--bg-surface)", padding: "12px", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#34d399", textTransform: "uppercase", marginBottom: "8px" }}>
            Validated Facts
          </div>
          <ul style={{ listStyle: "none", fontSize: "0.8125rem", color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: "4px" }}>
            {brief.facts.map((fact, index) => (
              <li key={index} style={{ display: "flex", gap: "6px" }}>
                <span>•</span>
                <span>{fact}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Highlighted Unknowns in Brief */}
        <div style={{ background: "var(--bg-surface)", padding: "12px", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#fbbf24", textTransform: "uppercase", marginBottom: "8px" }}>
            Operational Ambiguities
          </div>
          <ul style={{ listStyle: "none", fontSize: "0.8125rem", color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: "4px" }}>
            {brief.unknowns.map((unknown, index) => (
              <li key={index} style={{ display: "flex", gap: "6px" }}>
                <span>•</span>
                <span>{unknown}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {brief.recommended_action && (
        <div style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
          <span>Recommended Proposal Type: </span>
          <strong style={{ color: "var(--text-primary)" }}>{brief.recommended_action}</strong>
          {brief.urgency && <span> · Urgency: <strong style={{ color: "var(--text-primary)" }}>{brief.urgency.toUpperCase()}</strong></span>}
        </div>
      )}
    </div>
  );
};
