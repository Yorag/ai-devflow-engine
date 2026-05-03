import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { approveApproval, rejectApproval } from "../../api/approvals";
import type { ApiRequestError, ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import type { ApprovalRequestFeedEntry } from "../../api/types";
import { DeliveryReadinessNotice } from "./DeliveryReadinessNotice";
import { RejectReasonForm } from "./RejectReasonForm";

type ApprovalBlockProps = {
  entry: ApprovalRequestFeedEntry;
  sessionId?: string;
  projectId?: string;
  currentRunId?: string | null;
  request?: ApiRequestOptions;
  onOpenSettings?: () => void;
};

type ApprovalActionState = {
  isHistory: boolean;
  showPrimaryActions: boolean;
  canApprove: boolean;
  canReject: boolean;
  isApproveBlockedByReadiness: boolean;
};

export function ApprovalBlock({
  entry,
  sessionId = "",
  projectId = "",
  currentRunId = null,
  request,
  onOpenSettings,
}: ApprovalBlockProps): JSX.Element {
  const queryClient = useQueryClient();
  const [isBusy, setBusy] = useState(false);
  const [isRejectOpen, setRejectOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const actionState = resolveApprovalActionState(entry, currentRunId);

  async function invalidateWorkspaceQueries() {
    await queryClient.invalidateQueries({
      queryKey: apiQueryKeys.sessionWorkspace(sessionId),
      refetchType: "all",
    });
    await queryClient.invalidateQueries({
      queryKey: apiQueryKeys.projectSessions(projectId),
      refetchType: "all",
    });
  }

  async function handleApprove() {
    if (!actionState.canApprove || isBusy) {
      return;
    }

    setBusy(true);
    setErrorMessage(null);
    try {
      await approveApproval(entry.approval_id, request ?? {});
      setRejectOpen(false);
      await invalidateWorkspaceQueries();
    } catch (error) {
      setErrorMessage(readApiErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleReject(reason: string) {
    if (!actionState.canReject || isBusy) {
      return;
    }

    setBusy(true);
    setErrorMessage(null);
    try {
      await rejectApproval(entry.approval_id, { reason }, request ?? {});
      setRejectOpen(false);
      await invalidateWorkspaceQueries();
    } catch (error) {
      setErrorMessage(readApiErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      className="feed-entry feed-entry--approval-request approval-block"
      aria-label="Approval request feed entry"
    >
      <header className="feed-entry__header">
        <span>{formatApprovalType(entry.approval_type)}</span>
        <time dateTime={entry.requested_at}>{formatTimestamp(entry.requested_at)}</time>
        <strong>{formatLabel(entry.status)}</strong>
      </header>
      <h2>{entry.title}</h2>
      <p className="feed-entry__body">{entry.approval_object_excerpt}</p>
      {entry.risk_excerpt ? (
        <p className="feed-entry__supporting">{entry.risk_excerpt}</p>
      ) : null}
      <DeliveryReadinessNotice entry={entry} onOpenSettings={onOpenSettings} />
      {entry.disabled_reason ? (
        <p className="feed-entry__supporting">{entry.disabled_reason}</p>
      ) : null}
      {errorMessage ? <p className="approval-block__error">{errorMessage}</p> : null}
      {actionState.showPrimaryActions ? (
        <div className="feed-entry__actions" aria-label="Approval actions">
          <button
            type="button"
            disabled={!actionState.canApprove || isBusy}
            onClick={handleApprove}
          >
            {isBusy ? "Submitting approval" : "Approve"}
          </button>
          <button
            type="button"
            disabled={!actionState.canReject || isBusy}
            onClick={() => setRejectOpen((current) => !current)}
          >
            Reject
          </button>
        </div>
      ) : null}
      {isRejectOpen ? (
        <RejectReasonForm
          isBusy={isBusy}
          errorMessage={errorMessage}
          onCancel={() => {
            setRejectOpen(false);
            setErrorMessage(null);
          }}
          onSubmit={handleReject}
        />
      ) : null}
    </article>
  );
}

export function resolveApprovalActionState(
  entry: ApprovalRequestFeedEntry,
  currentRunId: string | null,
): ApprovalActionState {
  const isHistory = Boolean(currentRunId) && entry.run_id !== currentRunId;
  const isPending = entry.status === "pending";
  const isApproveBlockedByReadiness =
    entry.approval_type === "code_review_approval" &&
    entry.delivery_readiness_status !== null &&
    entry.delivery_readiness_status !== "ready";

  return {
    isHistory,
    showPrimaryActions: !isHistory && isPending,
    canApprove:
      !isHistory && isPending && entry.is_actionable && !isApproveBlockedByReadiness,
    canReject: !isHistory && isPending && entry.is_actionable,
    isApproveBlockedByReadiness,
  };
}

function readApiErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as ApiRequestError).message);
  }
  return "Approval request failed.";
}

function formatApprovalType(value: ApprovalRequestFeedEntry["approval_type"]): string {
  return value === "solution_design_approval"
    ? "Solution design approval"
    : "Code review approval";
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
