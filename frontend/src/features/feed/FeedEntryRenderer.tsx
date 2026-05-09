import type {
  ApprovalResultFeedEntry,
  ControlItemFeedEntry,
  MessageFeedEntry,
  SessionStatus,
  SystemStatusFeedEntry,
  TopLevelFeedEntry,
} from "../../api/types";
import type { ApiRequestOptions } from "../../api/client";
import { ApprovalBlock } from "../approvals/ApprovalBlock";
import { DeliveryResultBlock } from "../delivery/DeliveryResultBlock";
import { RerunAction } from "../runs/RerunAction";
import {
  formatApprovalType,
  formatAuthor,
  formatStatusLabel,
  stageLabels,
} from "./display-labels";
import { StageNode } from "./StageNode";
import { ToolConfirmationBlock } from "./ToolConfirmationBlock";

export type FeedEntryRendererProps = {
  entry: TopLevelFeedEntry;
  currentRunId?: string | null;
  currentSessionStatus?: SessionStatus | null;
  sessionId?: string;
  projectId?: string;
  request?: ApiRequestOptions;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
  onOpenSettings?: () => void;
};

export type FeedEntryRendererOptions = {
  currentRunId?: string | null;
  currentSessionStatus?: SessionStatus | null;
  sessionId?: string;
  projectId?: string;
  request?: ApiRequestOptions;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
  onOpenSettings?: () => void;
};

export function renderFeedEntryByType(
  entry: TopLevelFeedEntry,
  options: FeedEntryRendererOptions = {},
): JSX.Element {
  return (
    <FeedEntryRenderer
      entry={entry}
      currentRunId={options.currentRunId}
      currentSessionStatus={options.currentSessionStatus}
      sessionId={options.sessionId}
      projectId={options.projectId}
      request={options.request}
      onOpenInspectorTarget={options.onOpenInspectorTarget}
      onOpenSettings={options.onOpenSettings}
    />
  );
}

export function FeedEntryRenderer({
  entry,
  currentRunId,
  currentSessionStatus,
  sessionId,
  projectId,
  request,
  onOpenInspectorTarget,
  onOpenSettings,
}: FeedEntryRendererProps): JSX.Element {
  switch (entry.type) {
    case "user_message":
      return <UserMessageEntry entry={entry} />;
    case "stage_node":
      return (
        <StageNode
          entry={entry}
          onOpenInspectorTarget={onOpenInspectorTarget}
        />
      );
    case "approval_request":
      return (
        <ApprovalBlock
          entry={entry}
          sessionId={sessionId}
          projectId={projectId}
          currentRunId={currentRunId}
          currentSessionStatus={currentSessionStatus}
          request={request}
          onOpenSettings={onOpenSettings}
        />
      );
    case "tool_confirmation":
      return (
        <ToolConfirmationBlock
          entry={entry}
          currentRunId={currentRunId}
          sessionId={sessionId}
          projectId={projectId}
          request={request}
          onOpenInspectorTarget={onOpenInspectorTarget}
        />
      );
    case "control_item":
      return (
        <ControlItemEntry
          entry={entry}
          onOpenInspectorTarget={onOpenInspectorTarget}
        />
      );
    case "approval_result":
      return <ApprovalResultEntry entry={entry} />;
    case "delivery_result":
      return (
        <DeliveryResultBlock
          entry={entry}
          onOpenInspectorTarget={onOpenInspectorTarget}
        />
      );
    case "system_status":
      return (
        <SystemStatusEntry
          entry={entry}
          currentRunId={currentRunId}
          sessionId={sessionId}
          projectId={projectId}
          request={request}
        />
      );
  }
}

function UserMessageEntry({ entry }: { entry: MessageFeedEntry }): JSX.Element {
  return (
    <article
      className="feed-entry feed-entry--user-message"
      aria-label="User message feed entry"
    >
      <EntryHeader label={formatAuthor(entry.author)} />
      <p className="feed-entry__body">{entry.content}</p>
    </article>
  );
}

function ControlItemEntry({
  entry,
  onOpenInspectorTarget,
}: {
  entry: ControlItemFeedEntry;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
}): JSX.Element {
  return (
    <article
      className="feed-entry feed-entry--control-item"
      aria-label="Control item feed entry"
    >
      <EntryHeader label={formatStatusLabel(entry.control_type)} />
      <h2>{entry.title}</h2>
      <p className="feed-entry__body">{entry.summary}</p>
      {entry.target_stage_type &&
      entry.target_stage_type !== entry.source_stage_type ? (
        <p className="feed-entry__supporting">
          {stageLabels[entry.source_stage_type]}{" -> "}
          {stageLabels[entry.target_stage_type]}
        </p>
      ) : null}
      {onOpenInspectorTarget ? (
        <div className="feed-entry__actions" aria-label="Control item actions">
          <InspectorTrigger
            label={entry.title}
            onClick={() => onOpenInspectorTarget(entry)}
          />
        </div>
      ) : null}
    </article>
  );
}

function ApprovalResultEntry({
  entry,
}: {
  entry: ApprovalResultFeedEntry;
}): JSX.Element {
  return (
    <article
      className="feed-entry feed-entry--approval-result"
      aria-label="Approval result feed entry"
    >
      <EntryHeader label={formatApprovalType(entry.approval_type)} />
      <h2>{formatStatusLabel(entry.decision)}</h2>
      {entry.reason ? <p className="feed-entry__body">{entry.reason}</p> : null}
      <p className="feed-entry__supporting">
        下一步：{stageLabels[entry.next_stage_type]}
      </p>
    </article>
  );
}

function SystemStatusEntry({
  entry,
  currentRunId,
  sessionId,
  projectId,
  request,
}: {
  entry: SystemStatusFeedEntry;
  currentRunId?: string | null;
  sessionId?: string;
  projectId?: string;
  request?: ApiRequestOptions;
}): JSX.Element {
  return (
    <article
      className="feed-entry feed-entry--system-status"
      aria-label="System status feed entry"
    >
      <EntryHeader label="系统状态" badge={formatStatusLabel(entry.status)} />
      <h2>{entry.title}</h2>
      <p className="feed-entry__body">{entry.reason}</p>
      <RerunAction
        entry={entry}
        currentRunId={currentRunId}
        sessionId={sessionId}
        projectId={projectId}
        request={request}
      />
    </article>
  );
}

function EntryHeader({
  label,
  badge,
}: {
  label: string;
  badge?: string;
}): JSX.Element {
  return (
    <header className="feed-entry__header">
      <span>{label}</span>
      {badge ? <strong>{badge}</strong> : null}
    </header>
  );
}

function InspectorTrigger({
  label,
  className,
  onClick,
}: {
  label: string;
  className?: string;
  onClick: () => void;
}): JSX.Element {
  return (
    <button
      type="button"
      className={["inspector-trigger", className].filter(Boolean).join(" ")}
      onClick={onClick}
      aria-label={`查看${label}详情`}
    >
      查看详情
    </button>
  );
}
