import React from "react";
import { NavLink } from "react-router-dom";
import { Role } from "../types/contracts";
import { apiClient } from "../api/client";

interface AppShellProps {
  children: React.ReactNode;
  currentRole: Role;
  onRoleChange: (role: Role) => void;
  isDemoMode?: boolean;
  onResetDemo?: () => void;
}

export const AppShell: React.FC<AppShellProps> = ({
  children,
  currentRole,
  onRoleChange,
  isDemoMode = true,
  onResetDemo,
}) => {
  const handleReset = () => {
    if (onResetDemo) {
      onResetDemo();
    } else {
      apiClient.resetDemoData();
      window.location.reload();
    }
  };

  return (
    <div className="app-container">
      {/* Navigation Sidebar */}
      <aside className="app-sidebar" aria-label="Main Navigation">
        <div className="nav-brand">
          <div className="brand-title">Aro</div>
          <span className="brand-badge">Ops</span>
        </div>

        <nav>
          <ul className="nav-links">
            <li>
              <NavLink
                to="/dashboard"
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              >
                Dashboard
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/cases"
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              >
                Cases
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/evidence"
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              >
                Evidence
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/policies"
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              >
                Policies
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/settings"
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              >
                Settings
              </NavLink>
            </li>
          </ul>
        </nav>
      </aside>

      {/* Main Content Area */}
      <div className="app-main">
        <header className="app-header">
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <h1 style={{ fontSize: "1.125rem", fontWeight: 600, color: "var(--text-primary)" }}>
              Operations Console
            </h1>
          </div>

          <div className="header-right">
            {isDemoMode && (
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <div className="demo-pill" title="Running in deterministic demo mode with synthetic events">
                  <span className="demo-indicator" aria-hidden="true" />
                  <span>Demo Mode (demo_synthetic)</span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: "0.75rem", padding: "4px 8px" }}
                  onClick={handleReset}
                  title="Reset all demo cases and state to initial deterministic demo scenario"
                  aria-label="Reset Demo Scenario"
                >
                  Reset Demo Scenario
                </button>
              </div>
            )}

            <div className="role-switcher">
              <label htmlFor="role-select" style={{ fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
                Role:
              </label>
              <select
                id="role-select"
                className="role-select"
                value={currentRole}
                onChange={(e) => onRoleChange(e.target.value as Role)}
                aria-label="Active operator role"
              >
                <option value={Role.OPERATOR}>OPERATOR (Full Approval)</option>
                <option value={Role.ADMIN}>ADMIN (Full Access)</option>
                <option value={Role.VIEWER}>VIEWER (Read-Only)</option>
              </select>
            </div>

            <div style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", borderLeft: "1px solid var(--border-subtle)", paddingLeft: "12px" }}>
              Acme Facility 01 · <strong>Operator 104</strong>
            </div>
          </div>
        </header>

        <main className="app-content">{children}</main>
      </div>
    </div>
  );
};
