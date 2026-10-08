import React from "react";
import { CaseStatus, ActionStatus } from "../types/contracts";

interface StatusBadgeProps {
  status: CaseStatus | ActionStatus | string;
  size?: "sm" | "md";
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = "md" }) => {
  const normalized = status.toUpperCase().replace(/\s+/g, "_");

  let statusClass = "status-unresolved";
  let label = status;

  switch (normalized) {
    case CaseStatus.APPROVAL_PENDING:
    case "APPROVAL_PENDING":
      statusClass = "status-approval-pending";
      label = "APPROVAL PENDING";
      break;
    case CaseStatus.APPROVED:
    case "APPROVED":
      statusClass = "status-approved";
      label = "APPROVED";
      break;
    case CaseStatus.EXECUTING:
    case "EXECUTING":
      statusClass = "status-executing";
      label = "EXECUTING";
      break;
    case CaseStatus.COMPLETED:
    case ActionStatus.COMPLETED:
    case "COMPLETED":
      statusClass = "status-completed";
      label = "COMPLETED";
      break;
    case CaseStatus.REJECTED:
    case ActionStatus.FAILED:
    case "REJECTED":
    case "FAILED":
      statusClass = "status-rejected";
      label = normalized === "FAILED" ? "FAILED" : "REJECTED";
      break;
    case CaseStatus.EXPIRED:
    case "EXPIRED":
      statusClass = "status-rejected";
      label = "EXPIRED";
      break;
    case CaseStatus.UNRESOLVED:
    case "UNRESOLVED":
      statusClass = "status-unresolved";
      label = "UNRESOLVED";
      break;
    case CaseStatus.OPEN:
    case "OPEN":
      statusClass = "status-approved";
      label = "OPEN";
      break;
    default:
      label = status;
  }

  return (
    <span
      className={`status-badge ${statusClass}`}
      style={{ fontSize: size === "sm" ? "0.6875rem" : "0.75rem" }}
      aria-label={`Status: ${label}`}
    >
      {label}
    </span>
  );
};
