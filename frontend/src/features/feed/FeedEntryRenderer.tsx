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
      <EntryHeader label={formatAuthor(entry.author)} timestamp={entry.occurred_at} />
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
      <EntryHeader
        label={formatStatusLabel(entry.control_type)}
        timestamp={entry.occurred_at}
      />
      <h2>{entry.title}</h2>
      <p className="feed-entry__body">{entry.summary}</p>
      <div className="feed-entry__meta-grid" aria-label="Control metadata">
        <Metadata label="来源阶段" value={stageLabels[entry.source_stage_type]} />
        {entry.target_stage_type &&
        entry.target_stage_type !== entry.source_stage_type ? (
          <Metadata label="目标阶段" value={stageLabels[entry.target_stage_type]} />
        ) : null}
      </div>
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
      <EntryHeader
        label={formatApprovalType(entry.approval_type)}
        timestamp={entry.created_at}
      />
      <h2>{formatStatusLabel(entry.decision)}</h2>
      {entry.reason ? <p className="feed-entry__body">{entry.reason}</p> : null}
      <div className="feed-entry__meta-grid" aria-label="Approval result metadata">
        <Metadata label="下一阶段" value={stageLabels[entry.next_stage_type]} />
      </div>
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
      <EntryHeader
        label="系统状态"
        timestamp={entry.occurred_at}
        badge={formatStatusLabel(entry.status)}
      />
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

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
