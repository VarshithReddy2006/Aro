import React from "react";
import { CaseContext } from "../types/contracts";

interface CaseContextCardProps {
  context?: CaseContext;
}

export const CaseContextCard: React.FC<CaseContextCardProps> = ({ context }) => {
  if (!context) {
    return (
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Deterministic Context</h2>
        </div>
        <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
          Context computation in progress or unavailable.
        </p>
      </div>
    );
  }

  const known = context.known_facts || {};
  const unknowns = context.unknown_facts || [];

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">Deterministic Context Evaluation</h2>
        <span className="card-subtitle">
          Evaluated against active facility configuration rules
        </span>
      </div>

      <div className="fact-grid">
        {/* Known Facts Column */}
        <div className="fact-column">
          <div className="fact-title known">Known Facts (Deterministic)</div>
          <ul className="fact-list">
            <li>
              <span>✓</span>
              <span>
                Schedule window:{" "}
                <strong>{known.is_after_hours ? "Outside business hours (After hours)" : "During business hours"}</strong>
              </span>
            </li>
            <li>
              <span>✓</span>
              <span>
                Entrance type:{" "}
                <strong>{known.is_designated_entrance ? "Designated access point" : "Non-designated access point"}</strong>
              </span>
            </li>
            <li>
              <span>✓</span>
              <span>
                Expected delivery registered:{" "}
                <strong>{known.has_expected_delivery ? "TRUE" : "FALSE"}</strong>
              </span>
            </li>
            {known.recent_event_count !== undefined && (
              <li>
                <span>✓</span>
                <span>
                  Recent events in window: <strong>{known.recent_event_count}</strong>
                </span>
              </li>
            )}
            {known.device_type && (
              <li>
                <span>✓</span>
                <span>
                  Hardware device: <strong>{known.device_type}</strong>
                </span>
              </li>
            )}
          </ul>
        </div>

        {/* Unknown Facts Column */}
        <div className="fact-column">
          <div className="fact-title unknown">Unknowns (Unverified Bounds)</div>
          <ul className="fact-list">
            {unknowns.length > 0 ? (
              unknowns.map((fact, index) => (
                <li key={index}>
                  <span>?</span>
                  <span>{fact}</span>
                </li>
              ))
            ) : (
              <>
                <li>
                  <span>?</span>
                  <span>Whether a physical parcel was placed or delivered</span>
                </li>
                <li>
                  <span>?</span>
                  <span>Identity or organizational affiliation of the individual</span>
                </li>
                <li>
                  <span>?</span>
                  <span>Whether physical building breach occurred</span>
                </li>
              </>
            )}
          </ul>
        </div>
      </div>
    </div>
  );
};
