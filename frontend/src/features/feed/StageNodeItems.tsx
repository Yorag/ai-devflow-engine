import type {
  ProviderCallStageItem,
  StageItemProjection,
  StageType,
} from "../../api/types";
import { DiffPreview } from "./DiffPreview";
import {
  formatBoolean,
  formatMetricLabel,
  formatStatusLabel,
  stageItemLabels,
} from "./display-labels";
import { TestResultSummary } from "./TestResultSummary";
import { ToolCallItem } from "./ToolCallItem";

type StageNodeItem = StageItemProjection | ProviderCallStageItem;

export type StageNodeItemsProps = {
  items: StageNodeItem[];
  stageType?: StageType;
  stageMetrics?: Record<string, unknown>;
};

export function StageNodeItems({
  items,
  stageType,
  stageMetrics = {},
}: StageNodeItemsProps): JSX.Element {
  if (items.length === 0) {
    return (
      <p className="stage-node__empty" aria-label="Stage has no internal items">
        暂无阶段内部活动。
      </p>
    );
  }

  const resultItem =
    items.find(
      (item): item is StageItemProjection => item.type === "result",
    ) ?? null;

  return (
    <>
      {stageType === "test_generation_execution" ? (
        <TestResultSummary metrics={stageMetrics} resultItem={resultItem} />
      ) : null}
      <ol className="stage-node-items" aria-label="Stage internal items">
        {items.map((item) => renderStageItemByType(item))}
      </ol>
    </>
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
    case "tool_confirmation":
      return <CompactItem item={item} key={item.item_id} />;
    case "tool_call":
      return <ToolCallItem item={item} key={item.item_id} />;
    case "diff_preview":
      return <DiffPreview item={item} key={item.item_id} />;
  }
}

function DialogueItem({ item }: { item: StageItemProjection }): JSX.Element {
  const roleLabel = item.title.toLowerCase().includes("user")
    ? "用户回复"
    : "助手提问";

  return (
    <li className="stage-node-item stage-node-item--dialogue" aria-label="澄清对话">
      <StageItemHeader item={item} labelOverride={roleLabel} />
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
      aria-label={stageItemLabels[item.type]}
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
      aria-label={stageItemLabels[item.type]}
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
      return "查看上下文";
    case "reasoning":
      return "查看推理";
    case "model_call":
      return "查看模型详情";
    case "tool_call":
      return "查看命令";
    case "tool_confirmation":
      return "查看确认详情";
    case "diff_preview":
      return "查看预览";
    case "dialogue":
    case "decision":
    case "result":
      return "查看详情";
  }
}

function ProviderCallItem({ item }: { item: ProviderCallStageItem }): JSX.Element {
  const duration = readDuration(item.metrics);

  return (
    <li
      className={`stage-node-item stage-node-item--provider-${item.status}`}
      aria-label="模型服务调用"
    >
      <StageItemHeader item={item} />
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      <div className="provider-call-grid" aria-label="Provider call metadata">
        <ProviderDatum label="模型" value={`${item.provider_id} / ${item.model_id}`} />
        <ProviderDatum label="状态" value={formatStatusLabel(item.status)} />
        <ProviderDatum label="耗时" value={duration} />
        <ProviderDatum
          label="重试"
          value={`${item.retry_attempt} / ${item.max_retry_attempts}`}
        />
        <ProviderDatum label="退避" value={formatBackoff(item.backoff_wait_seconds)} />
        <ProviderDatum label="熔断器" value={formatStatusLabel(item.circuit_breaker_status)} />
        {item.failure_reason ? (
          <ProviderDatum label="失败原因" value={item.failure_reason} />
        ) : null}
        {item.process_ref ? <ProviderDatum label="详情引用" value={item.process_ref} /> : null}
      </div>
      <MetricPills metrics={item.metrics} limit={2} />
      <ReferenceList refs={item.artifact_refs} />
    </li>
  );
}

function StageItemHeader({
  item,
  labelOverride,
}: {
  item: StageNodeItem;
  labelOverride?: string;
}): JSX.Element {
  return (
    <header className="stage-node-item__header">
      <span>{labelOverride ?? stageItemLabels[item.type]}</span>
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
  return typeof value === "number" ? formatDurationMs(value) : "未记录";
}

function formatBackoff(value: number | null): string {
  return typeof value === "number" ? `等待 ${formatSeconds(value)}` : "无需等待";
}

function formatMetricValue(key: string, value: unknown): string {
  if (typeof value === "number") {
    if (key.endsWith("_ms")) {
      return formatDurationMs(value);
    }
    return new Intl.NumberFormat("en-US").format(value);
  }
  if (typeof value === "boolean") {
    return formatBoolean(value);
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

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
