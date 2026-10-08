import React from "react";

export const SettingsPage: React.FC = () => {
  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }}>
          Facility Configuration & Operations Settings
        </h2>
        <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", marginTop: "2px" }}>
          Physical environment parameters for deterministic context evaluation
        </p>
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Facility Profile</h3>
          <span className="hash-pill">facility_01</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "16px", fontSize: "0.875rem" }}>
          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
              Facility Identifier
            </div>
            <strong style={{ color: "var(--text-primary)" }}>facility_01</strong>
          </div>

          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
              Facility Name
            </div>
            <strong style={{ color: "var(--text-primary)" }}>Acme Operations Center #1</strong>
          </div>

          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
              Timezone
            </div>
            <strong style={{ color: "var(--text-primary)" }}>UTC (Universal Coordinated Time)</strong>
          </div>

          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
              Standard Business Hours
            </div>
            <strong style={{ color: "var(--text-primary)" }}>08:00 - 18:00 UTC (Mon - Fri)</strong>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Designated Entrance Hardware</h3>
        </div>
        <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginBottom: "16px" }}>
          Sensors mapped to official entrance gates. Activity on secondary devices triggers elevated attention queues.
        </p>

        <div className="table-container">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Device ID</th>
                <th>Device Name</th>
                <th>Classification</th>
                <th>Ingestion HMAC Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>front_entrance_doorbell</code></td>
                <td>Front Entrance Doorbell</td>
                <td><span style={{ color: "#34d399", fontWeight: 600 }}>Designated Primary Entrance</span></td>
                <td><span className="brand-badge" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#34d399" }}>Active / Validated</span></td>
              </tr>
              <tr>
                <td><code>rear_loading_dock_doorbell</code></td>
                <td>Rear Loading Dock Doorbell</td>
                <td><span style={{ color: "#fbbf24", fontWeight: 600 }}>Secondary Access Point</span></td>
                <td><span className="brand-badge" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#34d399" }}>Active / Validated</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Execution Mode & Environment</h3>
        </div>
        <div style={{ fontSize: "0.875rem", color: "var(--text-secondary)", lineHeight: 1.6 }}>
          <p>
            Current client connection is operating in <strong>Deterministic Offline Demo Mode</strong> (<code>demo_synthetic</code>).
          </p>
          <p style={{ marginTop: "8px" }}>
            Synthetic events and mock persistence preserve exact domain model validation, state transitions, version checks, and SHA-256 forward-linked audit chains without requiring live AWS or Ring credentials.
          </p>
        </div>
      </div>
    </div>
  );
};
