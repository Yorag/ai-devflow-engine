import type { ExecutionNodeProjection, StageType } from "../../api/types";
import { StageNodeItems } from "./StageNodeItems";

export type StageNodeProps = {
  entry: ExecutionNodeProjection;
  onOpenInspectorTarget?: (entry: ExecutionNodeProjection) => void;
};

const stageLabels: Record<StageType, string> = {
  requirement_analysis: "Requirement Analysis",
  solution_design: "Solution Design",
  code_generation: "Code Generation",
  test_generation_execution: "Test Generation & Execution",
  code_review: "Code Review",
  delivery_integration: "Delivery Integration",
};

const metricPriority = [
  "duration_ms",
  "clarification_rounds",
  "total_tokens",
  "tool_call_count",
  "changed_file_count",
  "passed_test_count",
  "failed_test_count",
];

export function StageNode({
  entry,
  onOpenInspectorTarget,
}: StageNodeProps): JSX.Element {
  const metrics = selectStageMetrics(entry.metrics);

  return (
    <article
      className={`feed-entry feed-entry--stage-node stage-node stage-node--${entry.status}`}
      aria-label="Stage feed entry"
    >
      <header className="stage-node__header">
        <div className="stage-node__identity">
          <span className="stage-node__eyebrow">Stage</span>
          <h2>{stageLabels[entry.stage_type]}</h2>
        </div>
        <div className="stage-node__header-actions">
          <span className="stage-node__status">{formatLabel(entry.status)}</span>
          {onOpenInspectorTarget ? (
            <button
              type="button"
              className="inspector-trigger"
              onClick={() => onOpenInspectorTarget(entry)}
              aria-label={`Open ${stageLabels[entry.stage_type]} details`}
            >
              Details
            </button>
          ) : null}
        </div>
      </header>

      <p className="stage-node__summary">{entry.summary}</p>

      <div className="stage-node__meta-grid" aria-label="Stage metadata">
        <StageDatum label="Attempt" value={String(entry.attempt_index)} />
        <StageDatum label="Started" value={formatTimestamp(entry.started_at)} />
        {entry.ended_at ? (
          <StageDatum label="Ended" value={formatTimestamp(entry.ended_at)} />
        ) : null}
        <StageDatum
          label="Items"
          value={`${entry.items.length} ${entry.items.length === 1 ? "item" : "items"}`}
        />
        {metrics.map(([key, value]) => (
          <StageDatum
            key={key}
            label={formatMetricLabel(key)}
            value={formatMetricValue(key, value)}
          />
        ))}
      </div>

      <StageNodeItems
        items={entry.items}
        stageType={entry.stage_type}
        stageMetrics={entry.metrics}
      />
    </article>
  );
}

function StageDatum({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <span className="stage-node__datum">
      <strong>{label}</strong>
      <span>{value}</span>
    </span>
  );
}

function selectStageMetrics(metrics: Record<string, unknown>): Array<[string, unknown]> {
  const selected: Array<[string, unknown]> = [];
  for (const key of metricPriority) {
    if (Object.prototype.hasOwnProperty.call(metrics, key)) {
      selected.push([key, metrics[key]]);
    }
    if (selected.length === 3) {
      return selected;
    }
  }

  for (const entry of Object.entries(metrics)) {
    if (!selected.some(([key]) => key === entry[0])) {
      selected.push(entry);
    }
    if (selected.length === 3) {
      break;
    }
  }

  return selected;
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

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
