import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { CaseDetailBundle, CaseStatus, Role } from "../types/contracts";
import { apiClient } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { EventCard } from "../components/EventCard";
import { CaseContextCard } from "../components/CaseContextCard";
import { AIBriefCard } from "../components/AIBriefCard";
import { ProposalReviewCard } from "../components/ProposalReviewCard";
import { ApprovalModal } from "../components/ApprovalModal";
import { RejectionModal } from "../components/RejectionModal";
import { ActionReceiptCard } from "../components/ActionReceiptCard";
import { CaseTimeline } from "../components/CaseTimeline";

interface CaseDetailPageProps {
  currentRole: Role;
}

export const CaseDetailPage: React.FC<CaseDetailPageProps> = ({ currentRole }) => {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();

  const [bundle, setBundle] = useState<CaseDetailBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modals & Submissions
  const [isApproveOpen, setIsApproveOpen] = useState(false);
  const [isRejectOpen, setIsRejectOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Dedicated Stale / Concurrency error state
  const [staleError, setStaleError] = useState<string | null>(null);
  const [generalActionError, setGeneralActionError] = useState<string | null>(null);

  useEffect(() => {
    if (caseId) {
      loadCaseData(caseId);
    }
  }, [caseId]);

  const loadCaseData = async (id: string) => {
    try {
      setLoading(true);
      setError(null);
      setStaleError(null);
      setGeneralActionError(null);
      const data = await apiClient.getCase(id);
      setBundle(data);
    } catch (err: any) {
      if (err.status === 404) {
        setError("Case not found in operations registry.");
      } else {
        setError(err?.message || "Failed to retrieve case details.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!bundle || !bundle.proposal || !caseId) return;

    try {
      setIsSubmitting(true);
      setGeneralActionError(null);
      setStaleError(null);

      // Explicit human confirmation sending exact proposal binding
      const approveRes = await apiClient.approveCase(caseId, {
        proposal_id: bundle.proposal.proposal_id,
        proposal_hash: bundle.proposal.proposal_hash,
        case_version: bundle.case.version,
      });

      setIsApproveOpen(false);

      // Now dispatch execution (server-enforced deterministic execution)
      const execRes = await apiClient.executeCase(caseId, {
        approval_id: approveRes.approval.approval_id,
        action_type: bundle.proposal.action_type,
        parameters: bundle.proposal.parameters,
      });

      // Reload fresh case state
      await loadCaseData(caseId);
    } catch (err: any) {
      setIsApproveOpen(false);
      if (err.status === 409 || err.code === "STALE_PROPOSAL" || err.code === "VERSION_MISMATCH") {
        setStaleError(
          "Proposal is no longer current. The case changed after this proposal was generated. For safety, the previous proposal cannot be approved or executed."
        );
      } else if (err.status === 403) {
        setGeneralActionError("You are not authorized to perform this action. Active role lacks OPERATOR approval permission.");
      } else {
        setGeneralActionError(err?.message || "Approval authorization rejected by server.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async (reason: string) => {
    if (!bundle || !bundle.proposal || !caseId) return;

    try {
      setIsSubmitting(true);
      setGeneralActionError(null);
      setStaleError(null);

      await apiClient.rejectCase(caseId, {
        proposal_id: bundle.proposal.proposal_id,
        proposal_hash: bundle.proposal.proposal_hash,
        case_version: bundle.case.version,
        reason,
      });

      setIsRejectOpen(false);
      // Reload fresh case state
      await loadCaseData(caseId);
    } catch (err: any) {
      setIsRejectOpen(false);
      if (err.status === 409) {
        setStaleError(
          "Proposal is no longer current. The case changed after this proposal was generated."
        );
      } else if (err.status === 403) {
        setGeneralActionError("You are not authorized to perform this action. Active role lacks OPERATOR permission.");
      } else {
        setGeneralActionError(err?.message || "Rejection could not be recorded.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "48px" }}>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
          Loading case {caseId} context & audit trail...
        </p>
      </div>
    );
  }

  if (error || !bundle) {
    return (
      <div className="card" style={{ borderColor: "#ef4444", textAlign: "center", padding: "32px" }}>
        <h2 style={{ color: "#f87171", fontSize: "1.125rem", marginBottom: "8px" }}>
          {error || "Unable to load case."}
        </h2>
        <div style={{ display: "flex", gap: "12px", justifyContent: "center", marginTop: "16px" }}>
          <button type="button" className="btn btn-secondary" onClick={() => navigate("/cases")}>
            Return to Cases
          </button>
          <button type="button" className="btn btn-primary" onClick={() => caseId && loadCaseData(caseId)}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const { case: caseData, context, brief, proposal, action, timeline } = bundle;

  return (
    <div>
      {/* CASE HEADER */}
      <div className="card" style={{ marginBottom: "24px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
              <span className="hash-pill" style={{ fontSize: "0.875rem", fontWeight: 700 }}>
                {caseData.case_id}
              </span>
              <StatusBadge status={caseData.status} />
              <span className="hash-pill" title="Deterministic state machine version">
                v{caseData.version}
              </span>
            </div>
            <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--text-primary)" }}>
              After-hours entrance activity
            </h1>
            <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginTop: "2px" }}>
              {caseData.location} · Device: Front Entrance Doorbell
            </p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: "0.75rem", padding: "4px 10px" }}
              onClick={() => caseId && loadCaseData(caseId)}
              aria-label="Refresh case state"
            >
              Refresh Case State
            </button>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontFamily: "var(--font-family-mono)" }}>
              Occurred: {new Date(caseData.occurred_at || caseData.created_at).toUTCString().slice(5, 22)} UTC
            </div>
          </div>
        </div>
      </div>

      {/* STALE PROPOSAL / CONCURRENCY BANNER */}
      {staleError && (
        <div className="stale-proposal-alert" role="alert">
          <div className="stale-proposal-title">Proposal is no longer current</div>
          <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginBottom: "12px" }}>
            {staleError}
          </p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => caseId && loadCaseData(caseId)}
          >
            Refresh case to review latest state
          </button>
        </div>
      )}

      {/* GENERAL ACTION ERROR BANNER */}
      {generalActionError && (
        <div className="card" style={{ borderColor: "#ef4444", background: "rgba(239, 68, 68, 0.08)", marginBottom: "20px" }} role="alert">
          <div style={{ color: "#f87171", fontWeight: 700, fontSize: "0.9375rem", marginBottom: "4px" }}>
            Authorization or Execution Denied
          </div>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
            {generalActionError}
          </p>
        </div>
      )}

      {/* REJECTION REASON BANNER (IF REJECTED) */}
      {caseData.status === CaseStatus.REJECTED && (
        <div className="card" style={{ borderColor: "#ef4444", background: "rgba(239, 68, 68, 0.08)" }}>
          <div style={{ color: "#f87171", fontWeight: 700, fontSize: "0.9375rem", marginBottom: "4px" }}>
            Case Rejected by Operator
          </div>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
            Proposal dismissed. No physical action authorized.
          </p>
        </div>
      )}

      {/* SECTION 1: PHYSICAL EVENT FACTS */}
      <EventCard caseData={caseData} />

      {/* SECTION 2: DETERMINISTIC CONTEXT (KNOWN VS UNKNOWN) */}
      <CaseContextCard context={context} />

      {/* SECTION 3: BOUNDED AI BRIEF */}
      <AIBriefCard brief={brief} />

      {/* SECTION 4: PROPOSAL REVIEW & HUMAN APPROVAL BOUNDARY */}
      {proposal && (
        <ProposalReviewCard
          proposal={proposal}
          caseVersion={caseData.version}
          caseStatus={caseData.status}
          currentRole={currentRole}
          onApproveClick={() => setIsApproveOpen(true)}
          onRejectClick={() => setIsRejectOpen(true)}
        />
      )}

      {/* SECTION 5: ACTION EXECUTION RECEIPT */}
      {action && <ActionReceiptCard action={action} />}

      {/* SECTION 6: CHRONOLOGICAL TIMELINE & AUDIT TRAIL */}
      <CaseTimeline timeline={timeline} />

      {/* APPROVAL CONFIRMATION MODAL */}
      {proposal && (
        <ApprovalModal
          isOpen={isApproveOpen}
          proposal={proposal}
          caseVersion={caseData.version}
          caseId={caseData.case_id}
          isSubmitting={isSubmitting}
          onConfirm={handleApprove}
          onClose={() => setIsApproveOpen(false)}
        />
      )}

      {/* REJECTION CONFIRMATION MODAL */}
      {proposal && (
        <RejectionModal
          isOpen={isRejectOpen}
          proposal={proposal}
          caseVersion={caseData.version}
          caseId={caseData.case_id}
          isSubmitting={isSubmitting}
          onConfirm={handleReject}
          onClose={() => setIsRejectOpen(false)}
        />
      )}
    </div>
  );
};
