import type { StageItemProjection } from "../../api/types";
import { formatStatusLabel, stageItemLabels } from "./display-labels";

type ToolCallParseResult = {
  toolName: string;
  targetSummary: string;
  statusLabel: string;
  commandExcerpt: string;
  outputSummary: string;
};

export function ToolCallItem({ item }: { item: StageItemProjection }): JSX.Element {
  const parsed = parseToolCallContent(item.content);

  return (
    <li className="stage-node-item stage-node-item--tool-call" aria-label="工具调用">
      <header className="stage-node-item__header">
        <span>{stageItemLabels.tool_call}</span>
        <strong>{item.title}</strong>
        <time dateTime={item.occurred_at}>{formatTimestamp(item.occurred_at)}</time>
      </header>
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      <div className="stage-node-item__tool-grid" aria-label="Tool call metadata">
        <ToolDatum label="工具" value={parsed.toolName} />
        <ToolDatum label="目标" value={parsed.targetSummary} />
        <ToolDatum label="状态" value={parsed.statusLabel} />
        <ToolDatum label="耗时" value={readDuration(item.metrics)} />
      </div>
      {parsed.commandExcerpt !== item.title ? (
        <p className="stage-node-item__command">{parsed.commandExcerpt}</p>
      ) : null}
      {item.content ? (
        <details className="stage-node-item__details">
          <summary>{parsed.outputSummary}</summary>
          <pre>{item.content}</pre>
        </details>
      ) : null}
      <ReferenceList refs={item.artifact_refs} />
    </li>
  );
}

function ToolDatum({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <span className="stage-node-item__datum">
      <strong>{label}</strong>
      <span>{value}</span>
    </span>
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

function parseToolCallContent(content: string | null): ToolCallParseResult {
  const lines = content?.split("\n") ?? [];
  const commandExcerpt = lines[0] ?? "Tool call";
  const toolName = commandExcerpt.split(" ")[0] ?? "tool";
  const targetSummary =
    lines.find((line) => line.startsWith("Target:"))?.replace("Target:", "").trim() ??
    "未记录";
  const statusValue =
    lines.find((line) => line.startsWith("Status:"))?.replace("Status:", "").trim() ??
    "unknown";
  const outputSummary =
    lines
      .find((line) => line.startsWith("Output summary:"))
      ?.replace("Output summary:", "")
      .trim() ?? "Command output";

  return {
    toolName,
    targetSummary,
    statusLabel: formatStatusLabel(statusValue.toLowerCase()),
    commandExcerpt,
    outputSummary,
  };
}

function readDuration(metrics: Record<string, unknown>): string {
  const value = metrics.duration_ms;
  if (typeof value !== "number") {
    return "未记录";
  }
  if (value >= 1000) {
    return `${Number((value / 1000).toFixed(1))}s`;
  }
  return `${value}ms`;
}

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
