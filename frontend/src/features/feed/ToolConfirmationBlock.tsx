import { QueryClientContext } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";

import type { ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import type {
  ToolConfirmationFeedEntry,
  TopLevelFeedEntry,
} from "../../api/types";
import { ErrorState } from "../errors/ErrorState";
import {
  submitToolConfirmationDecision,
  type ToolConfirmationDecision,
} from "../tool-confirmations/tool-confirmation-actions";

type ToolConfirmationBlockProps = {
  entry: ToolConfirmationFeedEntry;
  currentRunId?: string | null;
  sessionId?: string;
  projectId?: string;
  request?: ApiRequestOptions;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
};

type SubmittedToolConfirmationState = {
  sourceSignature: string;
  entry: ToolConfirmationFeedEntry;
};

export function ToolConfirmationBlock({
  entry,
  currentRunId,
  sessionId,
  projectId,
  request,
  onOpenInspectorTarget,
}: ToolConfirmationBlockProps): JSX.Element {
  const queryClient = useContext(QueryClientContext);
  const entrySignature = getToolConfirmationSignature(entry);
  const [submittedState, setSubmittedState] =
    useState<SubmittedToolConfirmationState | null>(null);
  const [pendingDecision, setPendingDecision] =
    useState<ToolConfirmationDecision | null>(null);
  const [apiError, setApiError] = useState<unknown | null>(null);
  const displayEntry =
    submittedState?.sourceSignature === entrySignature
      ? submittedState.entry
      : entry;
  const isHistorical =
    Boolean(currentRunId) && displayEntry.run_id !== currentRunId;
  const disabledReason = isHistorical
    ? "This tool confirmation belongs to a historical run."
    : displayEntry.disabled_reason;
  const isActionable =
    !isHistorical && displayEntry.is_actionable && pendingDecision === null;

  useEffect(() => {
    if (submittedState && submittedState.sourceSignature !== entrySignature) {
      setSubmittedState(null);
    }
  }, [entrySignature, submittedState]);

  async function submitDecision(decision: ToolConfirmationDecision): Promise<void> {
    if (!isActionable) {
      return;
    }

    setPendingDecision(decision);
    setApiError(null);
    try {
      const result = await submitToolConfirmationDecision(
        displayEntry,
        decision,
        request ?? {},
      );
      setSubmittedState({
        sourceSignature: entrySignature,
        entry: result.tool_confirmation,
      });
      if (queryClient && sessionId) {
        await queryClient.invalidateQueries({
          queryKey: apiQueryKeys.sessionWorkspace(sessionId),
          refetchType: "all",
        });
      }
      if (queryClient && projectId) {
        await queryClient.invalidateQueries({
          queryKey: apiQueryKeys.projectSessions(projectId),
          refetchType: "all",
        });
      }
    } catch (error) {
      setApiError(error);
    } finally {
      setPendingDecision(null);
    }
  }

  return (
    <article
      className="feed-entry feed-entry--tool-confirmation tool-confirmation-block"
      aria-label="Tool confirmation feed entry"
    >
      <EntryHeader
        label="High-risk tool confirmation"
        timestamp={displayEntry.requested_at}
        badge={formatLabel(displayEntry.status)}
      />
      <h2>{displayEntry.title}</h2>
      <div
        className="feed-entry__meta-grid"
        aria-label="Tool confirmation metadata"
      >
        <Metadata label="Tool" value={displayEntry.tool_name} />
        {displayEntry.command_preview ? (
          <Metadata label="Command" value={displayEntry.command_preview} />
        ) : null}
        <Metadata label="Target" value={displayEntry.target_summary} />
        <Metadata label="Risk" value={formatLabel(displayEntry.risk_level)} />
      </div>
      <p className="feed-entry__body">{displayEntry.reason}</p>
      {displayEntry.risk_categories.length > 0 ? (
        <ChipList
          label="Risk categories"
          values={displayEntry.risk_categories.map(formatLabel)}
        />
      ) : null}
      {displayEntry.expected_side_effects.length > 0 ? (
        <ChipList
          label="Expected side effects"
          values={displayEntry.expected_side_effects}
        />
      ) : null}
      {displayEntry.decision === "denied" && displayEntry.deny_followup_summary ? (
        <div className="tool-confirmation-block__follow-up">
          <strong>
            {formatDenyFollowupAction(displayEntry.deny_followup_action)}
          </strong>
          <p>{displayEntry.deny_followup_summary}</p>
        </div>
      ) : null}
      {disabledReason ? (
        <p className="feed-entry__supporting">{disabledReason}</p>
      ) : null}
      {apiError ? <ErrorState error={apiError} /> : null}
      <div className="feed-entry__actions" aria-label="Tool confirmation actions">
        <button
          type="button"
          className="tool-confirmation-block__allow"
          disabled={!isActionable}
          onClick={() => void submitDecision("allow")}
        >
          {pendingDecision === "allow" ? "正在允许..." : "允许本次执行"}
        </button>
        <button
          type="button"
          className="tool-confirmation-block__deny"
          disabled={!isActionable}
          onClick={() => void submitDecision("deny")}
        >
          {pendingDecision === "deny" ? "正在拒绝..." : "拒绝本次执行"}
        </button>
        {onOpenInspectorTarget ? (
          <button
            type="button"
            className="inspector-trigger inspector-trigger--quiet"
            onClick={() => onOpenInspectorTarget(displayEntry)}
            aria-label={`Open ${displayEntry.title} details`}
          >
            Details
          </button>
        ) : null}
      </div>
    </article>
  );
}

function formatDenyFollowupAction(
  value: ToolConfirmationFeedEntry["deny_followup_action"],
): string {
  switch (value) {
    case "continue_current_stage":
      return "拒绝后将继续当前阶段";
    case "run_failed":
      return "拒绝后当前运行将失败";
    case "awaiting_run_control":
      return "拒绝后等待运行控制";
    default:
      return "拒绝后的运行语义";
  }
}

function getToolConfirmationSignature(entry: ToolConfirmationFeedEntry): string {
  return JSON.stringify({
    run_id: entry.run_id,
    status: entry.status,
    is_actionable: entry.is_actionable,
    responded_at: entry.responded_at,
    decision: entry.decision,
    deny_followup_action: entry.deny_followup_action,
    deny_followup_summary: entry.deny_followup_summary,
    disabled_reason: entry.disabled_reason,
  });
}

function EntryHeader({
  label,
  timestamp,
  badge,
}: {
  label: string;
  timestamp: string;
  badge?: string;
}): JSX.Element {
  return (
    <header className="feed-entry__header">
      <span>{label}</span>
      <time dateTime={timestamp}>{formatTimestamp(timestamp)}</time>
      {badge ? <strong>{badge}</strong> : null}
    </header>
  );
}

function Metadata({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <span className="feed-entry__metadata">
      <strong>{label}</strong>
      <span>{value}</span>
    </span>
  );
}

function ChipList({
  label,
  values,
}: {
  label: string;
  values: string[];
}): JSX.Element {
  return (
    <div className="feed-entry__chip-group" aria-label={label}>
      {values.map((value) => (
        <span key={value}>{value}</span>
      ))}
    </div>
  );
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
