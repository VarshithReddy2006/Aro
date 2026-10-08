import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Case, CaseStatus, AuditEvent } from "../types/contracts";
import { StatusBadge } from "../components/StatusBadge";
import { apiClient } from "../api/client";

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const [cases, setCases] = useState<Case[]>([]);
  const [recentAudit, setRecentAudit] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const casesList = await apiClient.listCases();
      setCases(casesList);

      // Collect recent audit records from cases
      const auditList: AuditEvent[] = [];
      for (const c of casesList.slice(0, 4)) {
        try {
          const detail = await apiClient.getCase(c.case_id);
          auditList.push(...detail.timeline);
        } catch {
          // ignore individual fetch errors
        }
      }
      setRecentAudit(
        auditList
          .sort((a, b) => {
            const timeA = new Date(a.occurred_at || a.timestamp).getTime();
            const timeB = new Date(b.occurred_at || b.timestamp).getTime();
            return timeB - timeA;
          })
          .slice(0, 6)
      );
    } catch (err: any) {
      setError(err?.message || "Failed to load operational dashboard.");
    } finally {
      setLoading(false);
    }
  };

  // Metrics computation from real cases data
  const openCasesCount = cases.filter(
    (c) => c.status === CaseStatus.OPEN || c.status === CaseStatus.APPROVAL_PENDING || c.status === CaseStatus.EXECUTING
  ).length;

  const awaitingApprovalCount = cases.filter(
    (c) => c.status === CaseStatus.APPROVAL_PENDING
  ).length;

  const executingCount = cases.filter(
    (c) => c.status === CaseStatus.EXECUTING
  ).length;

  const completedCount = cases.filter(
    (c) => c.status === CaseStatus.COMPLETED
  ).length;

  const unresolvedCount = cases.filter(
    (c) => c.status === CaseStatus.UNRESOLVED
  ).length;

  // Attention queue: prioritized by APPROVAL_PENDING, then UNRESOLVED, then EXECUTING
  const attentionQueue = [...cases].sort((a, b) => {
    const priorityOrder: Record<string, number> = {
      [CaseStatus.APPROVAL_PENDING]: 1,
      [CaseStatus.UNRESOLVED]: 2,
      [CaseStatus.EXECUTING]: 3,
      [CaseStatus.OPEN]: 4,
      [CaseStatus.REJECTED]: 5,
      [CaseStatus.COMPLETED]: 6,
    };
    return (priorityOrder[a.status] || 99) - (priorityOrder[b.status] || 99);
  });

  if (loading) {
    return (
      <div>
        <div style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
          Loading operational dashboard telemetry...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card" style={{ borderColor: "#ef4444" }}>
        <h2 style={{ color: "#f87171", fontSize: "1rem", marginBottom: "8px" }}>
          Dashboard Telemetry Error
        </h2>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginBottom: "16px" }}>
          {error}
        </p>
        <button type="button" className="btn btn-secondary" onClick={loadData}>
          Retry Connection
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Operational Summary Cards */}
      <section aria-labelledby="section-summary">
        <h2 id="section-summary" style={{ fontSize: "0.875rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-secondary)", marginBottom: "12px" }}>
          Operational Summary
        </h2>
        <div className="metrics-grid">
          <div className="metric-card">
            <div className="metric-label">Open Cases</div>
            <div className="metric-value">{openCasesCount}</div>
            <div className="metric-sub">Active workflow items</div>
          </div>

          <div className="metric-card" style={{ borderLeft: "3px solid #fbbf24" }}>
            <div className="metric-label" style={{ color: "#fbbf24" }}>Awaiting Approval</div>
            <div className="metric-value" style={{ color: "#fbbf24" }}>{awaitingApprovalCount}</div>
            <div className="metric-sub">Human decision required</div>
          </div>

          <div className="metric-card">
            <div className="metric-label">Executing / In-Flight</div>
            <div className="metric-value">{executingCount}</div>
            <div className="metric-sub">Deterministic dispatch</div>
          </div>

          <div className="metric-card">
            <div className="metric-label">Completed Today</div>
            <div className="metric-value" style={{ color: "#34d399" }}>{completedCount}</div>
            <div className="metric-sub">Successfully closed</div>
          </div>

          <div className="metric-card">
            <div className="metric-label">Unresolved</div>
            <div className="metric-value" style={{ color: "#cbd5e1" }}>{unresolvedCount}</div>
            <div className="metric-sub">Exceptions & reviews</div>
          </div>
        </div>
      </section>

      {/* Attention Queue */}
      <section aria-labelledby="section-attention" style={{ marginBottom: "32px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <h2 id="section-attention" style={{ fontSize: "0.875rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-secondary)" }}>
            Attention Queue (Action Required)
          </h2>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            Showing {attentionQueue.length} operational cases
          </span>
        </div>

        <div className="table-container">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Location</th>
                <th>Event Type</th>
                <th>Occurred</th>
                <th>Status</th>
                <th>Action Required</th>
              </tr>
            </thead>
            <tbody>
              {attentionQueue.map((c) => {
                const actionReq =
                  c.status === CaseStatus.APPROVAL_PENDING
                    ? "Human Approval Required"
                    : c.status === CaseStatus.UNRESOLVED
                    ? "Investigate Ambiguity"
                    : c.status === CaseStatus.EXECUTING
                    ? "Awaiting Dispatch Receipt"
                    : "None (Closed)";

                return (
                  <tr
                    key={c.case_id}
                    onClick={() => navigate(`/cases/${c.case_id}`)}
                    tabIndex={0}
                    role="link"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate(`/cases/${c.case_id}`);
                      }
                    }}
                    aria-label={`Case ${c.case_id}, Status ${c.status}`}
                  >
                    <td>
                      <span className="hash-pill">{c.case_id}</span>
                    </td>
                    <td>
                      <strong>{c.location || c.location_id}</strong>
                    </td>
                    <td>Doorbell observation</td>
                    <td style={{ fontFamily: "var(--font-family-mono)", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
                      {new Date(c.occurred_at || c.created_at).toUTCString().slice(17, 22)} UTC
                    </td>
                    <td>
                      <StatusBadge status={c.status} size="sm" />
                    </td>
                    <td style={{ fontSize: "0.8125rem", fontWeight: c.status === CaseStatus.APPROVAL_PENDING ? 600 : 400, color: c.status === CaseStatus.APPROVAL_PENDING ? "#fbbf24" : "var(--text-muted)" }}>
                      {actionReq}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Recent Activity Feed */}
      <section aria-labelledby="section-activity">
        <h2 id="section-activity" style={{ fontSize: "0.875rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-secondary)", marginBottom: "12px" }}>
          Recent Operational Activity (Tamper-Evident Audit Feed)
        </h2>
        <div className="card">
          {recentAudit.length === 0 ? (
            <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
              No recent audit transitions recorded today.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {recentAudit.map((a, idx) => (
                <div
                  key={a.event_id || idx}
                  style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "8px", fontSize: "0.8125rem" }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <span style={{ fontFamily: "var(--font-family-mono)", color: "var(--text-muted)", fontSize: "0.75rem" }}>
                      {new Date(a.occurred_at || a.timestamp).toUTCString().slice(17, 22)} UTC
                    </span>
                    <strong style={{ color: "var(--text-primary)" }}>
                      {String(a.event_type || a.action).replace(/_/g, " ")}
                    </strong>
                    <span style={{ color: "var(--text-secondary)" }}>
                      on Case {a.case_id}
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>
                      by {a.actor_id}
                    </span>
                    <span className="hash-pill" style={{ fontSize: "0.6875rem" }}>
                      {a.event_hash ? `${a.event_hash.slice(0, 6)}...` : "hashed"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
};
