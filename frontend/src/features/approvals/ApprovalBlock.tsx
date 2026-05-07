import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { approveApproval, rejectApproval } from "../../api/approvals";
import type { ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import type { ApprovalRequestFeedEntry, SessionStatus } from "../../api/types";
import { ErrorState } from "../errors/ErrorState";
import { formatApprovalType, formatStatusLabel } from "../feed/display-labels";
import { DeliveryReadinessNotice } from "./DeliveryReadinessNotice";
import { RejectReasonForm } from "./RejectReasonForm";

type ApprovalBlockProps = {
  entry: ApprovalRequestFeedEntry;
  sessionId?: string;
  projectId?: string;
  currentRunId?: string | null;
  currentSessionStatus?: SessionStatus | null;
  request?: ApiRequestOptions;
  onOpenSettings?: () => void;
};

type ApprovalActionState = {
  isHistory: boolean;
  isCurrentRunTerminal: boolean;
  showPrimaryActions: boolean;
  canApprove: boolean;
  canReject: boolean;
  isApproveBlockedByReadiness: boolean;
};

type HistoricalApprovalState = {
  isHistory: boolean;
  isCurrentRunTerminal: boolean;
};

export function ApprovalBlock({
  entry,
  sessionId = "",
  projectId = "",
  currentRunId = null,
  currentSessionStatus = null,
  request,
  onOpenSettings,
}: ApprovalBlockProps): JSX.Element {
  const queryClient = useQueryClient();
  const [isBusy, setBusy] = useState(false);
  const [isRejectOpen, setRejectOpen] = useState(false);
  const [apiError, setApiError] = useState<unknown | null>(null);
  const actionState = resolveApprovalActionState(
    entry,
    currentRunId,
    currentSessionStatus,
  );
  const disabledReason =
    entry.disabled_reason ??
    (actionState.isCurrentRunTerminal
      ? "当前运行已结束。重试会创建新的运行。"
      : null);

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
    setApiError(null);
    try {
      await approveApproval(entry.approval_id, request ?? {});
      setRejectOpen(false);
      await invalidateWorkspaceQueries();
    } catch (error) {
      setApiError(error);
    } finally {
      setBusy(false);
    }
  }

  async function handleReject(reason: string) {
    if (!actionState.canReject || isBusy) {
      return;
    }

    setBusy(true);
    setApiError(null);
    try {
      await rejectApproval(entry.approval_id, { reason }, request ?? {});
      setRejectOpen(false);
      await invalidateWorkspaceQueries();
    } catch (error) {
      setApiError(error);
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
        <strong>{formatStatusLabel(entry.status)}</strong>
      </header>
      <h2>{entry.title}</h2>
      <p className="feed-entry__body">{entry.approval_object_excerpt}</p>
      {entry.risk_excerpt ? (
        <p className="feed-entry__supporting">{entry.risk_excerpt}</p>
      ) : null}
      <DeliveryReadinessNotice entry={entry} onOpenSettings={onOpenSettings} />
      {disabledReason ? (
        <p className="feed-entry__supporting">{disabledReason}</p>
      ) : null}
      {apiError ? (
        <ErrorState
          error={apiError}
          actionLabel={
            onOpenSettings && errorHasCode(apiError, "delivery_snapshot_not_ready")
              ? "Open settings"
              : undefined
          }
          onAction={
            onOpenSettings && errorHasCode(apiError, "delivery_snapshot_not_ready")
              ? onOpenSettings
              : undefined
          }
        />
      ) : null}
      {actionState.showPrimaryActions ? (
        <div className="feed-entry__actions" aria-label="Approval actions">
          <button
            type="button"
            disabled={!actionState.canApprove || isBusy}
            onClick={handleApprove}
          >
            {isBusy ? "正在提交批准" : "批准"}
          </button>
          <button
            type="button"
            disabled={!actionState.canReject || isBusy}
            onClick={() => setRejectOpen((current) => !current)}
          >
            退回
          </button>
        </div>
      ) : null}
      {isRejectOpen && actionState.canReject ? (
        <RejectReasonForm
          isBusy={isBusy}
          errorMessage={null}
          onCancel={() => {
            setRejectOpen(false);
            setApiError(null);
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
  currentSessionStatus: SessionStatus | null = null,
): ApprovalActionState {
  const historyState = resolveHistoricalApprovalState(
    entry,
    currentRunId,
    currentSessionStatus,
  );
  const isPending = entry.status === "pending";
  const isApproveBlockedByReadiness =
    entry.approval_type === "code_review_approval" &&
    entry.delivery_readiness_status !== null &&
    entry.delivery_readiness_status !== "ready";

  return {
    ...historyState,
    showPrimaryActions: !historyState.isHistory && isPending,
    canApprove:
      !historyState.isHistory &&
      !historyState.isCurrentRunTerminal &&
      isPending &&
      entry.is_actionable &&
      !isApproveBlockedByReadiness,
    canReject:
      !historyState.isHistory &&
      !historyState.isCurrentRunTerminal &&
      isPending &&
      entry.is_actionable,
    isApproveBlockedByReadiness,
  };
}

export function resolveHistoricalApprovalState(
  entry: ApprovalRequestFeedEntry,
  currentRunId: string | null,
  currentSessionStatus: SessionStatus | null,
): HistoricalApprovalState {
  const isHistory = Boolean(currentRunId) && entry.run_id !== currentRunId;
  const isCurrentRunTerminal =
    !isHistory &&
    currentRunId === entry.run_id &&
    entry.status === "pending" &&
    currentSessionStatus !== null &&
    ["failed", "terminated", "completed"].includes(currentSessionStatus);

  return {
    isHistory,
    isCurrentRunTerminal,
  };
}

function errorHasCode(error: unknown, code: string): boolean {
  if (!error || typeof error !== "object" || !("code" in error)) {
    return false;
  }
  return (error as { code?: unknown }).code === code;
}

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
