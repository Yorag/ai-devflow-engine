import type { StageItemProjection } from "../../api/types";
import { parseDiffPreviewContent } from "./DiffPreview";
import { formatStatusLabel, stageItemLabels } from "./display-labels";

type ToolCallParseResult = {
  toolName: string;
  targetSummary: string;
  statusLabel: string;
  commandExcerpt: string | null;
  outputSummary: string | null;
  detailText: string | null;
  visibleOutput: string | null;
};

export function ToolCallItem({
  item,
  diffItem = null,
  stepIndex = 0,
}: {
  item: StageItemProjection;
  diffItem?: StageItemProjection | null;
  stepIndex?: number;
}): JSX.Element {
  const parsed = parseToolCallContent(item.content);
  const diff = diffItem ? parseDiffPreviewContent(diffItem.content) : null;

  return (
    <li className="stage-node-item stage-node-item--tool-call" aria-label="工具调用">
      <header className="stage-node-item__header">
        <span className="stage-node-item__step sr-only">{formatStepNumber(stepIndex)}</span>
        <span className="stage-node-item__icon" aria-hidden="true">
          $
        </span>
        <span className="stage-node-item__kind">{stageItemLabels.tool_call}</span>
        <strong>{item.title}</strong>
      </header>
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {parsed.visibleOutput ? (
        <p className="stage-node-item__content">{parsed.visibleOutput}</p>
      ) : null}
      {parsed.commandExcerpt && parsed.commandExcerpt !== item.title ? (
        <p className="stage-node-item__command">{parsed.commandExcerpt}</p>
      ) : null}
      {diff && diff.files.length > 0 ? (
        <ul className="stage-node-item__file-list" aria-label="变更文件">
          {diff.files.map((file) => (
            <li key={file}>{file}</li>
          ))}
        </ul>
      ) : null}
      {diff && diff.previewLines.length > 0 ? (
        <pre className="stage-node-item__diff-snippet">
          {diff.previewLines.map((line) => (
            <span key={line}>{line}</span>
          ))}
        </pre>
      ) : null}
      {parsed.detailText ? (
        <details className="stage-node-item__details">
          <summary>查看输出</summary>
          <pre>{parsed.detailText}</pre>
        </details>
      ) : null}
      {diff?.remainder ? (
        <details className="stage-node-item__details">
          <summary>查看更多变更上下文</summary>
          <pre>{diff.remainder}</pre>
        </details>
      ) : null}
    </li>
  );
}

function parseToolCallContent(content: string | null): ToolCallParseResult {
  const lines = content?.split("\n").map((line) => line.trim()).filter(Boolean) ?? [];
  const commandExcerpt = lines[0] ?? null;
  const toolName =
    lines.find((line) => line.startsWith("Tool:"))?.replace("Tool:", "").trim() ??
    commandExcerpt?.split(" ")[0] ??
    "tool";
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
      .trim() ?? null;
  const visibleOutput =
    outputSummary && !isBlockedPlaceholder(outputSummary) ? outputSummary : null;
  const detailText = readableDetailText(lines);

  return {
    toolName,
    targetSummary,
    statusLabel: formatStatusLabel(statusValue.toLowerCase()),
    commandExcerpt,
    outputSummary,
    detailText,
    visibleOutput,
  };
}

function readableDetailText(lines: string[]): string | null {
  const visibleLines = lines.filter(
    (line) => !isInternalTraceLine(line) && !isBlockedPlaceholder(line),
  );
  return visibleLines.length > 1 ? visibleLines.join("\n") : null;
}

function isBlockedPlaceholder(value: string): boolean {
  return value.startsWith("[blocked:");
}

function isInternalTraceLine(line: string): boolean {
  const lowered = line.toLowerCase();
  return (
    lowered.startsWith("call id:") ||
    lowered.startsWith("artifact refs:") ||
    lowered.startsWith("trace ref:") ||
    lowered.startsWith("side effect refs:") ||
    lowered.startsWith("decision trace") ||
    lowered.includes("sha256:") ||
    lowered.includes("evidence_refs") ||
    lowered.startsWith("status:") ||
    lowered.startsWith("tool:") ||
    lowered.startsWith("target:") ||
    lowered.startsWith("output summary:")
  );
}

function formatStepNumber(index: number): string {
  return String(index + 1).padStart(2, "0");
}
