import type {
  ApprovalRequestFeedEntry,
  ApprovalResultFeedEntry,
  ControlItemFeedEntry,
  DeliveryResultFeedEntry,
  MessageFeedEntry,
  StageType,
  SystemStatusFeedEntry,
  ToolConfirmationFeedEntry,
  TopLevelFeedEntry,
} from "../../api/types";
import { StageNode } from "./StageNode";

export type FeedEntryRendererProps = {
  entry: TopLevelFeedEntry;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
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
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
};

export function renderFeedEntryByType(
  entry: TopLevelFeedEntry,
  options: FeedEntryRendererOptions = {},
): JSX.Element {
  return (
    <FeedEntryRenderer
      entry={entry}
      onOpenInspectorTarget={options.onOpenInspectorTarget}
    />
  );
}

export function FeedEntryRenderer({
  entry,
  onOpenInspectorTarget,
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
      return <ApprovalRequestEntry entry={entry} />;
    case "tool_confirmation":
      return (
        <ToolConfirmationEntry
          entry={entry}
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
        <DeliveryResultEntry
          entry={entry}
          onOpenInspectorTarget={onOpenInspectorTarget}
        />
      );
    case "system_status":
      return <SystemStatusEntry entry={entry} />;
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

function ApprovalRequestEntry({
  entry,
}: {
  entry: ApprovalRequestFeedEntry;
}): JSX.Element {
  return (
    <article
      className="feed-entry feed-entry--approval-request"
      aria-label="Approval request feed entry"
    >
      <EntryHeader
        label={formatApprovalType(entry.approval_type)}
        timestamp={entry.requested_at}
        badge={formatLabel(entry.status)}
      />
      <h2>{entry.title}</h2>
      <p className="feed-entry__body">{entry.approval_object_excerpt}</p>
      {entry.risk_excerpt ? (
        <p className="feed-entry__supporting">{entry.risk_excerpt}</p>
      ) : null}
      <div className="feed-entry__meta-grid" aria-label="Approval metadata">
        {entry.delivery_readiness_status ? (
          <Metadata
            label="Delivery readiness"
            value={formatLabel(entry.delivery_readiness_status)}
          />
        ) : null}
        {entry.delivery_readiness_message ? (
          <Metadata label="Readiness note" value={entry.delivery_readiness_message} />
        ) : null}
        {entry.disabled_reason ? (
          <Metadata label="Disabled" value={entry.disabled_reason} />
        ) : null}
      </div>
      <div className="feed-entry__actions" aria-label="Approval actions">
        <button type="button" disabled={!entry.is_actionable}>
          Approve
        </button>
        <button type="button" disabled={!entry.is_actionable}>
          Reject
        </button>
      </div>
    </article>
  );
}

function ToolConfirmationEntry({
  entry,
  onOpenInspectorTarget,
}: {
  entry: ToolConfirmationFeedEntry;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
}): JSX.Element {
  return (
    <article
      className="feed-entry feed-entry--tool-confirmation"
      aria-label="Tool confirmation feed entry"
    >
      <EntryHeader
        label="High-risk tool confirmation"
        timestamp={entry.requested_at}
        badge={formatLabel(entry.status)}
      />
      <h2>{entry.title}</h2>
      <div className="feed-entry__meta-grid" aria-label="Tool confirmation metadata">
        <Metadata label="Tool" value={entry.tool_name} />
        {entry.command_preview ? (
          <Metadata label="Command" value={entry.command_preview} />
        ) : null}
        <Metadata label="Target" value={entry.target_summary} />
        <Metadata label="Risk" value={formatLabel(entry.risk_level)} />
      </div>
      <p className="feed-entry__body">{entry.reason}</p>
      {entry.risk_categories.length > 0 ? (
        <ChipList
          label="Risk categories"
          values={entry.risk_categories.map(formatLabel)}
        />
      ) : null}
      {entry.expected_side_effects.length > 0 ? (
        <ChipList label="Expected side effects" values={entry.expected_side_effects} />
      ) : null}
      {entry.disabled_reason ? (
        <p className="feed-entry__supporting">{entry.disabled_reason}</p>
      ) : null}
      <div className="feed-entry__actions" aria-label="Tool confirmation actions">
        <button type="button" disabled={!entry.is_actionable}>
          Allow this execution
        </button>
        <button type="button" disabled={!entry.is_actionable}>
          Deny this execution
        </button>
        {onOpenInspectorTarget ? (
          <InspectorTrigger
            label={entry.title}
            className="inspector-trigger--quiet"
            onClick={() => onOpenInspectorTarget(entry)}
          />
        ) : null}
      </div>
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

function DeliveryResultEntry({
  entry,
  onOpenInspectorTarget,
}: {
  entry: DeliveryResultFeedEntry;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
}): JSX.Element {
  return (
    <article
      className="feed-entry feed-entry--delivery-result"
      aria-label="Delivery result feed entry"
    >
      <EntryHeader
        label="Delivery result"
        timestamp={entry.occurred_at}
        badge={formatLabel(entry.status)}
      />
      <h2>{formatLabel(entry.delivery_mode)}</h2>
      <p className="feed-entry__body">{entry.summary}</p>
      <div className="feed-entry__meta-grid" aria-label="Delivery result metadata">
        <Metadata label="Mode" value={entry.delivery_mode} />
        {entry.branch_name ? <Metadata label="Branch" value={entry.branch_name} /> : null}
        {entry.commit_sha ? <Metadata label="Commit" value={entry.commit_sha} /> : null}
        {entry.code_review_url ? (
          <Metadata label="Code review" value={entry.code_review_url} />
        ) : null}
        {entry.test_summary ? (
          <Metadata label="Tests" value={entry.test_summary} />
        ) : null}
      </div>
      {onOpenInspectorTarget ? (
        <div className="feed-entry__actions" aria-label="Delivery result actions">
          <InspectorTrigger
            label={entry.delivery_mode}
            onClick={() => onOpenInspectorTarget(entry)}
          />
        </div>
      ) : null}
    </article>
  );
}

function SystemStatusEntry({
  entry,
}: {
  entry: SystemStatusFeedEntry;
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
      {entry.retry_action ? (
        <div className="feed-entry__actions" aria-label="System status actions">
          <button type="button">Retry run</button>
        </div>
      ) : null}
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
