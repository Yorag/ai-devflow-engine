import type {
  ProviderCallStageItem,
  StageItemProjection,
  StageItemType,
} from "../../api/types";

type StageNodeItem = StageItemProjection | ProviderCallStageItem;

export type StageNodeItemsProps = {
  items: StageNodeItem[];
};

const itemLabels: Record<StageItemType, string> = {
  dialogue: "Dialogue",
  context: "Context",
  reasoning: "Reasoning",
  decision: "Decision",
  model_call: "Model Call",
  provider_call: "Provider Call",
  tool_call: "Tool Call",
  tool_confirmation: "Tool Confirmation",
  diff_preview: "Diff Preview",
  result: "Result",
};

export function StageNodeItems({ items }: StageNodeItemsProps): JSX.Element {
  if (items.length === 0) {
    return (
      <p className="stage-node__empty" aria-label="Stage has no internal items">
        No stage activity has been projected yet.
      </p>
    );
  }

  return (
    <ol className="stage-node-items" aria-label="Stage internal items">
      {items.map((item) => renderStageItemByType(item))}
    </ol>
  );
}

export function renderStageItemByType(item: StageNodeItem): JSX.Element {
  if (item.type === "provider_call") {
    return <ProviderCallItem item={item} key={item.item_id} />;
  }

  switch (item.type) {
    case "dialogue":
      return <DialogueItem item={item} key={item.item_id} />;
    case "decision":
    case "result":
      return <ProminentItem item={item} key={item.item_id} />;
    case "context":
    case "reasoning":
    case "model_call":
    case "tool_call":
    case "tool_confirmation":
    case "diff_preview":
      return <CompactItem item={item} key={item.item_id} />;
  }
}

function DialogueItem({ item }: { item: StageItemProjection }): JSX.Element {
  return (
    <li className="stage-node-item stage-node-item--dialogue" aria-label="Dialogue stage item">
      <StageItemHeader item={item} />
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {item.content ? <p className="stage-node-item__content">{item.content}</p> : null}
      <MetricPills metrics={item.metrics} limit={2} />
      <ReferenceList refs={item.artifact_refs} />
    </li>
  );
}

function ProminentItem({ item }: { item: StageItemProjection }): JSX.Element {
  return (
    <li
      className={`stage-node-item stage-node-item--${item.type}`}
      aria-label={`${itemLabels[item.type]} stage item`}
    >
      <StageItemHeader item={item} />
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {item.content ? <p className="stage-node-item__content">{item.content}</p> : null}
      <MetricPills metrics={item.metrics} limit={3} />
      <ReferenceList refs={item.artifact_refs} />
    </li>
  );
}

function CompactItem({ item }: { item: StageItemProjection }): JSX.Element {
  const content = item.content;

  return (
    <li
      className={`stage-node-item stage-node-item--${item.type}`}
      aria-label={`${itemLabels[item.type]} stage item`}
    >
      <StageItemHeader item={item} />
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {content ? (
        <details className="stage-node-item__details" open={item.type === "diff_preview"}>
          <summary>{formatCompactSummary(item.type)}</summary>
          <pre>{content}</pre>
        </details>
      ) : null}
      <MetricPills metrics={item.metrics} limit={3} />
      <ReferenceList refs={item.artifact_refs} />
    </li>
  );
}

function formatCompactSummary(type: StageItemProjection["type"]): string {
  switch (type) {
    case "context":
      return "Context";
    case "reasoning":
      return "Reasoning";
    case "model_call":
      return "Model details";
    case "tool_call":
      return "Command";
    case "tool_confirmation":
      return "Confirmation";
    case "diff_preview":
      return "Preview";
    case "dialogue":
    case "decision":
    case "result":
      return "Details";
  }
}

function ProviderCallItem({ item }: { item: ProviderCallStageItem }): JSX.Element {
  const duration = readDuration(item.metrics);

  return (
    <li
      className={`stage-node-item stage-node-item--provider-${item.status}`}
      aria-label="Provider Call stage item"
    >
      <StageItemHeader item={item} />
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      <div className="provider-call-grid" aria-label="Provider call metadata">
        <ProviderDatum label="Model" value={`${item.provider_id} / ${item.model_id}`} />
        <ProviderDatum label="Status" value={formatLabel(item.status)} />
        <ProviderDatum label="Duration" value={duration} />
        <ProviderDatum
          label="Retry"
          value={`${item.retry_attempt} / ${item.max_retry_attempts}`}
        />
        <ProviderDatum label="Backoff" value={formatBackoff(item.backoff_wait_seconds)} />
        <ProviderDatum label="Circuit" value={formatLabel(item.circuit_breaker_status)} />
        {item.failure_reason ? (
          <ProviderDatum label="Failure" value={item.failure_reason} />
        ) : null}
        {item.process_ref ? <ProviderDatum label="Details" value={item.process_ref} /> : null}
      </div>
      <MetricPills metrics={item.metrics} limit={2} />
      <ReferenceList refs={item.artifact_refs} />
    </li>
  );
}

function StageItemHeader({ item }: { item: StageNodeItem }): JSX.Element {
  return (
    <header className="stage-node-item__header">
      <span>{itemLabels[item.type]}</span>
      <strong>{item.title}</strong>
      <time dateTime={item.occurred_at}>{formatTimestamp(item.occurred_at)}</time>
    </header>
  );
}

function ProviderDatum({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <span className="provider-call-grid__datum">
      <strong>{label}</strong>
      <span>{value}</span>
    </span>
  );
}

function MetricPills({
  metrics,
  limit,
}: {
  metrics: Record<string, unknown>;
  limit: number;
}): JSX.Element | null {
  const entries = Object.entries(metrics).slice(0, limit);
  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="stage-node-item__metric-pills" aria-label="Item metrics">
      {entries.map(([key, value]) => (
        <span key={key}>
          {formatMetricLabel(key)}: {formatMetricValue(key, value)}
        </span>
      ))}
    </div>
  );
}

function ReferenceList({ refs }: { refs: string[] }): JSX.Element | null {
  if (refs.length === 0) {
    return null;
  }

  return (
    <div className="stage-node-item__refs" aria-label="Artifact references">
      {refs.map((ref) => (
        <span key={ref}>{ref}</span>
      ))}
    </div>
  );
}

function readDuration(metrics: Record<string, unknown>): string {
  const value = metrics.duration_ms;
  return typeof value === "number" ? formatDurationMs(value) : "Not recorded";
}

function formatBackoff(value: number | null): string {
  return typeof value === "number" ? `Wait ${formatSeconds(value)}` : "No wait";
}

function formatMetricLabel(value: string): string {
  return value === "duration_ms" ? "Duration" : formatLabel(value);
}

function formatMetricValue(key: string, value: unknown): string {
  if (typeof value === "number") {
    if (key.endsWith("_ms")) {
      return formatDurationMs(value);
    }
    return new Intl.NumberFormat("en-US").format(value);
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  return String(value);
}

function formatDurationMs(value: number): string {
  if (value >= 60000) {
    const totalSeconds = Math.round(value / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
  }
  if (value >= 1000) {
    return `${Number((value / 1000).toFixed(1))}s`;
  }
  return `${value}ms`;
}

function formatSeconds(value: number): string {
  return value >= 60 ? formatDurationMs(value * 1000) : `${value}s`;
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
