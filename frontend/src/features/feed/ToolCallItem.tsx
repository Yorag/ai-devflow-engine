import { useState } from "react";

import type { StageItemProjection } from "../../api/types";
import { parseDiffPreviewContent } from "./DiffPreview";
import { stageItemLabels } from "./display-labels";

type ToolCallParseResult = {
  commandExcerpt: string | null;
  outputSummary: string | null;
  detailText: string | null;
  detailVariant: "plain" | "pre";
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
  const [isExpanded, setIsExpanded] = useState(false);
  const parsed = parseToolCallContent(item.content);
  const diff = diffItem ? parseDiffPreviewContent(diffItem.content) : null;
  const displayTitle = parsed.commandExcerpt ?? item.title;
  const detailSummary = dedupeToolDetailSummary(
    parsed.outputSummary ?? item.summary,
    parsed.detailText,
    parsed.detailVariant,
  );
  const hasExpandableContent = Boolean(
    detailSummary ||
      parsed.detailText ||
      (diff && (diff.files.length > 0 || diff.previewLines.length > 0 || diff.remainder)),
  );
  const detailsId = `tool-call-details-${item.item_id}`;

  return (
    <li className="stage-node-item stage-node-item--tool-call" aria-label="工具调用">
      <header className="stage-node-item__header stage-node-item__header--tool">
        <span className="stage-node-item__step sr-only">{formatStepNumber(stepIndex)}</span>
        <span className="stage-node-item__icon" aria-hidden="true">
          $
        </span>
        <span className="stage-node-item__kind">{stageItemLabels.tool_call}</span>
        {hasExpandableContent ? (
          <button
            type="button"
            className="stage-node-item__tool-trigger"
            aria-expanded={isExpanded}
            aria-controls={detailsId}
            onClick={() => setIsExpanded((current) => !current)}
          >
            <span className="stage-node-item__tool-title">{displayTitle}</span>
            <span className="stage-node-item__tool-toggle" aria-hidden="true">
              {"›"}
            </span>
          </button>
        ) : (
          <strong>{displayTitle}</strong>
        )}
      </header>
      {hasExpandableContent && isExpanded ? (
        <div
          className="stage-node-item__tool-details"
          id={detailsId}
        >
          {detailSummary ? <p className="stage-node-item__detail-copy">{detailSummary}</p> : null}
          {parsed.detailText ? (
            parsed.detailVariant === "plain" ? (
              <div className="stage-node-item__tool-plain-output">
                {parsed.detailText.split(/\n+/u).map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
            ) : (
              <pre>{parsed.detailText}</pre>
            )
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
          {diff?.remainder ? <pre>{diff.remainder}</pre> : null}
        </div>
      ) : null}
    </li>
  );
}

function parseToolCallContent(content: string | null): ToolCallParseResult {
  const lines = content?.split("\n").map((line) => line.replace(/\r$/u, "")) ?? [];
  const visibleLines = lines.filter((line) => line.trim().length > 0);
  const commandExcerpt = visibleLines[0]?.trim() ?? null;
  const outputSummary =
    visibleLines
      .map((line) => line.trim())
      .find((line) => line.startsWith("Output summary:"))
      ?.replace("Output summary:", "")
      .trim() ?? null;
  const detailText = readableDetailText(lines, commandExcerpt);
  const detailVariant = detectDetailVariant(commandExcerpt, detailText);

  return {
    commandExcerpt,
    outputSummary:
      outputSummary && !isBlockedPlaceholder(outputSummary) ? outputSummary : null,
    detailText,
    detailVariant,
  };
}

function readableDetailText(
  lines: string[],
  commandExcerpt: string | null,
): string | null {
  const visibleLines = lines.filter(
    (line) =>
      line.trim().length > 0 &&
      !isInternalTraceLine(line.trim()) &&
      !isBlockedPlaceholder(line.trim()),
  );
  const contentLines =
    commandExcerpt && visibleLines[0]?.trim() === commandExcerpt
      ? visibleLines.slice(1)
      : visibleLines;
  const detailText = contentLines.join("\n").trim();
  return detailText ? detailText : null;
}

function dedupeToolDetailSummary(
  summary: string | null,
  detailText: string | null,
  detailVariant: "plain" | "pre",
): string | null {
  const normalizedSummary = normalizeWhitespace(summary);
  if (!normalizedSummary) {
    return null;
  }

  if (detailVariant === "plain" && detailText) {
    return null;
  }

  const normalizedDetails = normalizeWhitespace(detailText);
  if (
    normalizedDetails &&
    (normalizedDetails === normalizedSummary ||
      normalizedDetails.startsWith(normalizedSummary) ||
      normalizedDetails.includes(normalizedSummary))
  ) {
    return null;
  }

  return summary;
}

function detectDetailVariant(
  commandExcerpt: string | null,
  detailText: string | null,
): "plain" | "pre" {
  const command = commandExcerpt?.toLowerCase() ?? "";
  if (
    command.startsWith("grep ") ||
    command.startsWith("glob ") ||
    command.startsWith("read_file ") ||
    command.startsWith("read_workspace ")
  ) {
    return "plain";
  }
  void detailText;
  return "pre";
}

function normalizeWhitespace(value: string | null): string | null {
  const normalized = value?.replace(/\s+/gu, " ").trim() ?? "";
  return normalized || null;
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
