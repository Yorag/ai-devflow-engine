import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { approveApproval, rejectApproval } from "../../api/approvals";
import type { ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import type {
  ApprovalRequestFeedEntry,
  ApprovalResultFeedEntry,
  SessionStatus,
} from "../../api/types";
import { ErrorState } from "../errors/ErrorState";
import {
  formatApprovalType,
  formatStatusLabel,
  stageLabels,
} from "../feed/display-labels";
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

type LocalHandledState = {
  decision: ApprovalResultFeedEntry["decision"];
  nextStageType: ApprovalResultFeedEntry["next_stage_type"];
  reason: string | null;
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
  const [localHandledState, setLocalHandledState] =
    useState<LocalHandledState | null>(null);
  const actionState = resolveApprovalActionState(
    entry,
    currentRunId,
    currentSessionStatus,
  );
  const handledState =
    localHandledState ??
    (entry.status === "approved" || entry.status === "rejected"
      ? {
          decision: entry.status,
          nextStageType:
            entry.approval_type === "solution_design_approval"
              ? entry.status === "approved"
                ? "code_generation"
                : "solution_design"
              : entry.status === "approved"
                ? "delivery_integration"
                : "code_generation",
          reason: null,
        }
      : null);
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
      const response = await approveApproval(entry.approval_id, request ?? {});
      setLocalHandledState({
        decision: response.approval_result.decision,
        nextStageType: response.approval_result.next_stage_type,
        reason: response.approval_result.reason,
      });
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
      const response = await rejectApproval(
        entry.approval_id,
        { reason },
        request ?? {},
      );
      setLocalHandledState({
        decision: response.approval_result.decision,
        nextStageType: response.approval_result.next_stage_type,
        reason: response.approval_result.reason,
      });
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
      className={[
        "feed-entry",
        "feed-entry--approval-request",
        "approval-block",
        handledState ? "approval-block--handled" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label="Approval request feed entry"
    >
      <header className="feed-entry__header">
        <span>审批请求</span>
        <strong>{formatStatusLabel(handledState?.decision ?? entry.status)}</strong>
      </header>
      {handledState ? (
        <>
          <h2>{`${formatApprovalType(entry.approval_type)}${formatDecisionSuffix(handledState.decision)}`}</h2>
          <p className="feed-entry__supporting">
            下一步：{stageLabels[handledState.nextStageType]}
          </p>
          {handledState.reason ? (
            <p className="feed-entry__supporting">{handledState.reason}</p>
          ) : null}
        </>
      ) : (
        <>
          <h2>{`等待${formatApprovalType(entry.approval_type)}`}</h2>
          <p className="feed-entry__summary">{entry.title}</p>
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
                onOpenSettings &&
                errorHasCode(apiError, "delivery_snapshot_not_ready")
                  ? "Open settings"
                  : undefined
              }
              onAction={
                onOpenSettings &&
                errorHasCode(apiError, "delivery_snapshot_not_ready")
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
        </>
      )}
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

function formatDecisionSuffix(
  decision: ApprovalResultFeedEntry["decision"],
): string {
  return decision === "approved" ? "已批准" : "已退回";
}
