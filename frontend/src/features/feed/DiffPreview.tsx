import type { StageItemProjection } from "../../api/types";
import { stageItemLabels } from "./display-labels";

type DiffPreviewParseResult = {
  files: string[];
  previewLines: string[];
  remainder: string | null;
};

export function DiffPreview({
  item,
  stepIndex = 0,
}: {
  item: StageItemProjection;
  stepIndex?: number;
}): JSX.Element {
  const parsed = parseDiffPreviewContent(item.content);

  return (
    <li
      className="stage-node-item stage-node-item--diff-preview"
      aria-label="变更预览"
    >
      <header className="stage-node-item__header">
        <span className="stage-node-item__step sr-only">{formatStepNumber(stepIndex)}</span>
        <span className="stage-node-item__icon" aria-hidden="true">
          +
        </span>
        <span className="stage-node-item__kind">{stageItemLabels.diff_preview}</span>
        <strong>{item.title}</strong>
      </header>
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {parsed.files.length > 0 ? (
        <ul className="stage-node-item__file-list" aria-label="变更文件">
          {parsed.files.map((file) => (
            <li key={file}>{file}</li>
          ))}
        </ul>
      ) : null}
      {parsed.previewLines.length > 0 ? (
        <pre className="stage-node-item__diff-snippet">
          {parsed.previewLines.map((line) => (
            <span key={line}>{line}</span>
          ))}
        </pre>
      ) : null}
      {parsed.remainder ? (
        <details className="stage-node-item__details">
          <summary>查看更多变更上下文</summary>
          <pre>{parsed.remainder}</pre>
        </details>
      ) : null}
    </li>
  );
}

function parseDiffPreviewContent(content: string | null): DiffPreviewParseResult {
  const sections = content?.split("\n\n") ?? [];
  const fileSection = sections[0] ?? "";
  const remainder = sections.slice(2).join("\n\n") || null;
  const lines = fileSection.split("\n").map((line) => line.trim()).filter(Boolean);
  const hasFileSection = fileSection.startsWith("Files:");
  const files = hasFileSection
    ? fileSection
        .replace(/^Files:\n?/u, "")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
    : lines.filter((line) => !line.startsWith("+") && !line.startsWith("-"));
  const sectionPreview = (sections[1] ?? "").split("\n").filter(Boolean);
  const previewLines =
    sectionPreview.length > 0
      ? sectionPreview
      : lines.filter(
          (line) => line.startsWith("+") || line.startsWith("-") || line.startsWith("@@"),
        );

  return {
    files,
    previewLines,
    remainder,
  };
}

function formatStepNumber(index: number): string {
  return String(index + 1).padStart(2, "0");
}
