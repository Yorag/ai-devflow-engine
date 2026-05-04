import type {
  ApprovalResultFeedEntry,
  ControlItemFeedEntry,
  MessageFeedEntry,
  SessionStatus,
  StageType,
  SystemStatusFeedEntry,
  TopLevelFeedEntry,
} from "../../api/types";
import type { ApiRequestOptions } from "../../api/client";
import { ApprovalBlock } from "../approvals/ApprovalBlock";
import { DeliveryResultBlock } from "../delivery/DeliveryResultBlock";
import { RerunAction } from "../runs/RerunAction";
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

const stageLabels: Record<StageType, string> = {
  requirement_analysis: "Requirement Analysis",
  solution_design: "Solution Design",
  code_generation: "Code Generation",
  test_generation_execution: "Test Generation & Execution",
  code_review: "Code Review",
  delivery_integration: "Delivery Integration",
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
        label={formatLabel(entry.control_type)}
        timestamp={entry.occurred_at}
      />
      <h2>{entry.title}</h2>
      <p className="feed-entry__body">{entry.summary}</p>
      <div className="feed-entry__meta-grid" aria-label="Control metadata">
        <Metadata label="Source" value={stageLabels[entry.source_stage_type]} />
        {entry.target_stage_type &&
        entry.target_stage_type !== entry.source_stage_type ? (
          <Metadata label="Target" value={stageLabels[entry.target_stage_type]} />
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
      <h2>{formatLabel(entry.decision)}</h2>
      {entry.reason ? <p className="feed-entry__body">{entry.reason}</p> : null}
      <div className="feed-entry__meta-grid" aria-label="Approval result metadata">
        <Metadata label="Next stage" value={stageLabels[entry.next_stage_type]} />
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
        label="System status"
        timestamp={entry.occurred_at}
        badge={formatLabel(entry.status)}
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
      aria-label={`Open ${label} details`}
    >
      Details
    </button>
  );
}

function formatAuthor(author: MessageFeedEntry["author"]): string {
  return author === "user" ? "User" : formatLabel(author);
}

function formatApprovalType(value: ApprovalResultFeedEntry["approval_type"]): string {
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
