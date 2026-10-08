import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Case, CaseStatus } from "../types/contracts";
import { StatusBadge } from "../components/StatusBadge";
import { apiClient } from "../api/client";

type FilterType = "ALL" | "NEEDS_APPROVAL" | "OPEN" | "EXECUTING" | "COMPLETED" | "UNRESOLVED";

export const CasesPage: React.FC = () => {
  const navigate = useNavigate();
  const [cases, setCases] = useState<Case[]>([]);
  const [filter, setFilter] = useState<FilterType>("ALL");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadCases();
  }, []);

  const loadCases = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await apiClient.listCases();
      setCases(res);
    } catch (err: any) {
      setError(err?.message || "Failed to load operational cases.");
    } finally {
      setLoading(false);
    }
  };

  const filteredCases = cases.filter((c) => {
    if (filter === "ALL") return true;
    if (filter === "NEEDS_APPROVAL") return c.status === CaseStatus.APPROVAL_PENDING;
    if (filter === "OPEN") return c.status === CaseStatus.OPEN;
    if (filter === "EXECUTING") return c.status === CaseStatus.EXECUTING;
    if (filter === "COMPLETED") return c.status === CaseStatus.COMPLETED;
    if (filter === "UNRESOLVED") return c.status === CaseStatus.UNRESOLVED;
    return true;
  });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }}>
            Operational Cases
          </h2>
          <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", marginTop: "2px" }}>
            Authoritative physical-world event cases under operational management
          </p>
        </div>

        <button
          type="button"
          className="btn btn-secondary"
          onClick={loadCases}
          disabled={loading}
          aria-label="Refresh operational cases"
        >
          {loading ? "Refreshing..." : "Refresh Cases"}
        </button>
      </div>

      {/* Filter Tabs */}
      <div style={{ display: "flex", gap: "8px", marginBottom: "16px", flexWrap: "wrap" }}>
        {(
          [
            { id: "ALL", label: "All" },
            { id: "NEEDS_APPROVAL", label: "Needs Approval" },
            { id: "OPEN", label: "Open" },
            { id: "EXECUTING", label: "Executing" },
            { id: "COMPLETED", label: "Completed" },
            { id: "UNRESOLVED", label: "Unresolved" },
          ] as { id: FilterType; label: string }[]
        ).map((item) => (
          <button
            key={item.id}
            type="button"
            className={`btn ${filter === item.id ? "btn-primary" : "btn-secondary"}`}
            style={{ fontSize: "0.8125rem", padding: "6px 12px" }}
            onClick={() => setFilter(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* States */}
      {loading ? (
        <div className="card" style={{ textAlign: "center", padding: "48px" }}>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
            Loading operational cases...
          </p>
        </div>
      ) : error ? (
        <div className="card" style={{ borderColor: "#ef4444", textAlign: "center", padding: "32px" }}>
          <p style={{ color: "#f87171", fontSize: "0.9375rem", marginBottom: "12px" }}>
            Unable to load cases: {error}
          </p>
          <button type="button" className="btn btn-secondary" onClick={loadCases}>
            Retry
          </button>
        </div>
      ) : filteredCases.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: "48px" }}>
          <p style={{ color: "var(--text-muted)", fontSize: "0.9375rem" }}>
            No operational cases found matching current filter.
          </p>
        </div>
      ) : (
        <div className="table-container">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Location</th>
                <th>Event</th>
                <th>Occurred</th>
                <th>Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.map((c) => {
                const occurredDate = new Date(c.occurred_at || c.created_at).toUTCString().slice(5, 22) + " UTC";
                const updatedDate = new Date(c.updated_at).toUTCString().slice(5, 22) + " UTC";

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
                    aria-label={`Case ${c.case_id}`}
                  >
                    <td>
                      <span className="hash-pill" style={{ color: "var(--text-primary)", fontWeight: 600 }}>
                        {c.case_id}
                      </span>
                    </td>
                    <td>
                      <strong>{c.location || c.location_id}</strong>
                    </td>
                    <td>
                      <span>Doorbell activity observed</span>
                    </td>
                    <td style={{ fontFamily: "var(--font-family-mono)", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
                      {occurredDate}
                    </td>
                    <td>
                      <StatusBadge status={c.status} size="sm" />
                    </td>
                    <td style={{ fontFamily: "var(--font-family-mono)", fontSize: "0.8125rem", color: "var(--text-muted)" }}>
                      {updatedDate}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
