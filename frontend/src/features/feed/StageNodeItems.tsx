import type {
  ProviderCallStageItem,
  StageItemProjection,
  StageType,
} from "../../api/types";
import { DiffPreview } from "./DiffPreview";
import {
  formatMetricLabel,
  formatStatusLabel,
  formatLabel,
  stageItemLabels,
} from "./display-labels";
import { TestResultSummary } from "./TestResultSummary";
import { ToolCallItem } from "./ToolCallItem";

type StageNodeItem = StageItemProjection | ProviderCallStageItem;
type HiddenStageItemType =
  | "provider_call"
  | "tool_confirmation"
  | "decision"
  | "model_call";
type ToolExecutionDisplayItem = {
  item_id: string;
  type: "tool_execution";
  toolItem: StageItemProjection;
  diffItem: StageItemProjection | null;
};
type DisplayStageItem = StageNodeItem | ToolExecutionDisplayItem;

const hiddenMainFlowTypes: ReadonlySet<HiddenStageItemType> = new Set([
  "provider_call",
  "tool_confirmation",
  "decision",
  "model_call",
]);

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
  const displayItems = stageNodeItemsForDisplay(items);

  if (displayItems.length === 0) {
    return (
      <p className="stage-node__empty" aria-label="Stage has no internal items">
        暂无执行步骤。
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
      <ol className="stage-node-items" aria-label="阶段执行步骤">
        {displayItems.map((item, index) => renderStageItemByType(item, index))}
      </ol>
    </>
  );
}

export function stageNodeItemsForDisplay(items: StageNodeItem[]): DisplayStageItem[] {
  const visibleItems = items.filter(
    (item) => !hiddenMainFlowTypes.has(item.type as HiddenStageItemType),
  );
  const displayItems: DisplayStageItem[] = [];

  for (let index = 0; index < visibleItems.length; index += 1) {
    const item = visibleItems[index];
    if (item.type === "tool_call") {
      const nextItem = visibleItems[index + 1];
      if (nextItem?.type === "diff_preview") {
        displayItems.push({
          item_id: `${item.item_id}::tool-execution`,
          type: "tool_execution",
          toolItem: item,
          diffItem: nextItem,
        });
        index += 1;
        continue;
      }
    }

    displayItems.push(item);
  }

  return displayItems;
}

export function renderStageItemByType(
  item: DisplayStageItem,
  index = 0,
): JSX.Element {
  if (item.type === "provider_call") {
    return <ProviderCallItem item={item} stepIndex={index} key={item.item_id} />;
  }

  if (item.type === "tool_execution") {
    return (
      <ToolCallItem
        item={item.toolItem}
        diffItem={item.diffItem}
        stepIndex={index}
        key={item.item_id}
      />
    );
  }

  switch (item.type) {
    case "dialogue":
      return <DialogueItem item={item} stepIndex={index} key={item.item_id} />;
    case "result":
      return <ProminentItem item={item} stepIndex={index} key={item.item_id} />;
    case "decision":
    case "context":
    case "reasoning":
    case "model_call":
    case "tool_confirmation":
      return <CompactItem item={item} stepIndex={index} key={item.item_id} />;
    case "tool_call":
      return <ToolCallItem item={item} stepIndex={index} key={item.item_id} />;
    case "diff_preview":
      return <DiffPreview item={item} stepIndex={index} key={item.item_id} />;
  }
}

function DialogueItem({
  item,
  stepIndex,
}: {
  item: StageItemProjection;
  stepIndex: number;
}): JSX.Element {
  const roleLabel = item.title.toLowerCase().includes("user")
    ? "用户回复"
    : "助手提问";
  const readableContent = readReadableContent(item.content);

  return (
    <li className="stage-node-item stage-node-item--dialogue" aria-label="澄清对话">
      <StageItemHeader item={item} labelOverride={roleLabel} stepIndex={stepIndex} />
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {readableContent ? (
        <p className="stage-node-item__content">{readableContent.text}</p>
      ) : null}
    </li>
  );
}

function ProminentItem({
  item,
  stepIndex,
}: {
  item: StageItemProjection;
  stepIndex: number;
}): JSX.Element {
  const readableContent = readReadableContent(item.content);
  const resultContent =
    item.type === "result" ? parseResultContent(readableContent?.text ?? "") : null;

  return (
    <li
      className={`stage-node-item stage-node-item--${item.type}`}
      aria-label={stageItemLabels[item.type]}
    >
      <StageItemHeader item={item} stepIndex={stepIndex} />
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {readableContent && readableContent.text !== item.summary ? (
        item.type === "result" ? (
          <ResultContent text={readableContent.text} parsed={resultContent} />
        ) : (
          <p className="stage-node-item__content">{readableContent.text}</p>
        )
      ) : null}
    </li>
  );
}

type ResultSection =
  | { type: "paragraph"; title: string | null; text: string }
  | { type: "list"; title: string | null; items: string[] };

function ResultContent({
  text,
  parsed,
}: {
  text: string;
  parsed: ResultSection[] | null;
}): JSX.Element {
  if (parsed && parsed.length > 0) {
    return (
      <div className="stage-node-item__result-sections">
        {parsed.map((section, index) => {
          if (section.type === "paragraph") {
            return (
              <div
                key={`${section.type}-${index}-${section.text}`}
                className="stage-node-item__result-section"
              >
                {section.title ? (
                  <strong className="stage-node-item__result-heading">
                    {section.title}
                  </strong>
                ) : null}
                <p className="stage-node-item__content">{section.text}</p>
              </div>
            );
          }

          return (
            <section
              key={`${section.type}-${index}-${section.title ?? "items"}`}
              className="stage-node-item__result-section"
            >
              {section.title ? (
                <strong className="stage-node-item__result-heading">
                  {section.title}
                </strong>
              ) : null}
              <ul className="stage-node-item__result-list">
                {section.items.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    );
  }

  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length <= 1) {
    return <p className="stage-node-item__content">{text}</p>;
  }
  return (
    <ul className="stage-node-item__result-list">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

function CompactItem({
  item,
  stepIndex,
}: {
  item: StageItemProjection;
  stepIndex: number;
}): JSX.Element {
  const readableContent = readReadableContent(item.content);
  const detailsContent =
    readableContent?.source === "plain" && readableContent.text !== item.summary
      ? readableContent.text
      : fallbackCompactDetails(item);
  const detailsVariant = compactDetailsVariant(item, readableContent, detailsContent);

  return (
    <li
      className={`stage-node-item stage-node-item--${item.type}`}
      aria-label={stageItemLabels[item.type]}
    >
      <StageItemHeader item={item} stepIndex={stepIndex} />
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {!item.summary && readableContent ? (
        <p className="stage-node-item__content">{readableContent.text}</p>
      ) : null}
      {detailsContent ? (
        <details className="stage-node-item__details">
          <summary>{formatCompactSummary(item.type)}</summary>
          {detailsVariant === "transcript" ? (
            <TranscriptDetails text={detailsContent} />
          ) : (
            <pre>{detailsContent}</pre>
          )}
        </details>
      ) : null}
    </li>
  );
}

function compactDetailsVariant(
  item: StageItemProjection,
  readableContent: { text: string; source: "plain" | "structured" } | null,
  detailsContent: string | null,
): "transcript" | "pre" {
  if (
    item.type === "model_call" &&
    readableContent?.source === "plain" &&
    detailsContent === readableContent.text
  ) {
    return "transcript";
  }
  return "pre";
}

function TranscriptDetails({ text }: { text: string }): JSX.Element {
  const paragraphs = text
    .split(/\n{2,}/u)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  if (paragraphs.length === 0) {
    return <div className="stage-node-item__details-body">{text}</div>;
  }

  return (
    <div className="stage-node-item__details-body">
      {paragraphs.map((paragraph) => (
        <p key={paragraph}>{paragraph}</p>
      ))}
    </div>
  );
}

function formatCompactSummary(type: StageItemProjection["type"]): string {
  switch (type) {
    case "context":
      return "查看上下文";
    case "reasoning":
      return "查看思考";
    case "model_call":
      return "查看模型记录";
    case "decision":
      return "查看决策详情";
    case "tool_call":
      return "查看命令";
    case "tool_confirmation":
      return "查看确认详情";
    case "diff_preview":
      return "查看预览";
    case "dialogue":
    case "result":
      return "查看详情";
  }
}

function ProviderCallItem({
  item,
  stepIndex,
}: {
  item: ProviderCallStageItem;
  stepIndex: number;
}): JSX.Element {
  const duration = readDuration(item.metrics);
  const retry =
    item.retry_attempt > 0 ? `，第 ${item.retry_attempt}/${item.max_retry_attempts} 次重试` : "";
  const callSummary = `${item.provider_id} 调用 ${item.model_id}，${formatProviderStatusPhrase(
    item.status,
  )}${retry}，耗时 ${duration}。`;

  return (
    <li
      className={`stage-node-item stage-node-item--provider-${item.status}`}
      aria-label="模型服务调用"
    >
      <StageItemHeader
        item={item}
        labelOverride="模型调用"
        titleOverride={`调用 ${item.model_id}`}
        stepIndex={stepIndex}
      />
      <p className="stage-node-item__content">{callSummary}</p>
      {item.summary ? <p className="stage-node-item__summary">{item.summary}</p> : null}
      {item.failure_reason ? (
        <p className="stage-node-item__supporting">失败原因：{item.failure_reason}</p>
      ) : null}
    </li>
  );
}

function StageItemHeader({
  item,
  labelOverride,
  titleOverride,
  stepIndex,
}: {
  item: StageNodeItem;
  labelOverride?: string;
  titleOverride?: string;
  stepIndex: number;
}): JSX.Element {
  return (
    <header className="stage-node-item__header">
      <span className="stage-node-item__step sr-only">{formatStepNumber(stepIndex)}</span>
      <span className="stage-node-item__icon" aria-hidden="true">
        {stageItemIcon(item.type)}
      </span>
      <span className="stage-node-item__kind">{labelOverride ?? stageItemLabels[item.type]}</span>
      <strong>{titleOverride ?? item.title}</strong>
    </header>
  );
}

function readDuration(metrics: Record<string, unknown>): string {
  const value = metrics.duration_ms;
  return typeof value === "number" ? formatDurationMs(value) : "未记录";
}

function formatProviderStatusPhrase(status: ProviderCallStageItem["status"]): string {
  switch (status) {
    case "queued":
      return "等待执行";
    case "running":
      return "正在执行";
    case "retrying":
      return "正在重试";
    case "succeeded":
      return "已完成";
    case "failed":
      return "失败";
    case "circuit_open":
      return "熔断打开";
  }
}

function stageItemIcon(type: DisplayStageItem["type"]): string {
  switch (type) {
    case "dialogue":
      return "?";
    case "context":
      return "#";
    case "reasoning":
      return "~";
    case "decision":
      return ">";
    case "model_call":
    case "provider_call":
      return "@";
    case "tool_call":
    case "tool_execution":
      return "$";
    case "tool_confirmation":
      return "!";
    case "diff_preview":
      return "+";
    case "result":
      return "=";
  }
}

function fallbackCompactDetails(item: StageItemProjection): string | null {
  switch (item.type) {
    case "model_call":
      return modelCallDetails(item);
    case "decision":
      return decisionDetails(item);
    default:
      return null;
  }
}

function modelCallDetails(item: StageItemProjection): string | null {
  if (readReadableContent(item.content)?.source === "plain") {
    return null;
  }

  const lines: string[] = [];
  const callType = readStringMetric(item.metrics, "model_call_type");
  if (callType) {
    lines.push(`调用类型: ${formatLabel(callType)}`);
  }

  const tokenLine = formatTokenMetrics(item.metrics);
  if (tokenLine) {
    lines.push(tokenLine);
  }

  return lines.length > 0 ? lines.join("\n") : null;
}

function decisionDetails(item: StageItemProjection): string | null {
  const lines: string[] = [];
  const decisionType = readStringMetric(item.metrics, "decision_type");
  if (decisionType) {
    lines.push(`决策类型: ${formatLabel(decisionType)}`);
  } else if (item.title && item.title !== "Decision") {
    lines.push(`动作: ${item.title}`);
  }

  const status = readStringMetric(item.metrics, "status");
  if (status) {
    lines.push(`状态: ${formatStatusLabel(status)}`);
  }

  return lines.length > 0 ? lines.join("\n") : null;
}

function readStringMetric(
  metrics: Record<string, unknown>,
  key: string,
): string | null {
  const value = metrics[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function formatTokenMetrics(metrics: Record<string, unknown>): string | null {
  const tokenKeys = ["input_tokens", "output_tokens", "total_tokens"] as const;
  const parts = tokenKeys
    .map((key) => {
      const value = metrics[key];
      if (typeof value !== "number") {
        return null;
      }
      return `${formatMetricLabel(key)} ${value}`;
    })
    .filter((value): value is string => value !== null);
  return parts.length > 0 ? parts.join("，") : null;
}

function readReadableContent(
  content: string | null,
): { text: string; source: "plain" | "structured" } | null {
  const trimmed = content?.trim();
  if (!trimmed) {
    return null;
  }

  const structuredSummary = readStructuredSummary(trimmed);
  if (structuredSummary) {
    return { text: structuredSummary, source: "structured" };
  }

  return { text: trimmed, source: "plain" };
}

function readStructuredSummary(value: string): string | null {
  if (!value.startsWith("{") && !value.startsWith("[")) {
    return null;
  }

  try {
    const parsed = JSON.parse(value) as unknown;
    return extractStructuredSummary(parsed);
  } catch {
    return null;
  }
}

function extractStructuredSummary(value: unknown): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const record = value as Record<string, unknown>;
  const summaryKeys = [
    "summary",
    "design_summary",
    "implementation_summary",
    "review_summary",
    "delivery_summary",
    "message",
    "title",
  ];
  for (const key of summaryKeys) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }

  const artifactType = record.artifact_type;
  return typeof artifactType === "string" ? `${formatLabel(artifactType)} 已生成。` : null;
}

function parseResultContent(text: string): ResultSection[] | null {
  const trimmed = text.trim();
  if (!trimmed) {
    return null;
  }

  const blocks = trimmed
    .split(/\n{2,}/u)
    .map((block) => block.trim())
    .filter(Boolean);
  const sections: ResultSection[] = [];

  for (const block of blocks) {
    const lines = block
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length === 0) {
      continue;
    }

    const firstLine = lines[0];
    const remainder = lines.slice(1);
    const firstLineLooksLikeHeading = remainder.length > 0 && !isBulletLine(firstLine);
    const bulletLines = (firstLineLooksLikeHeading ? remainder : lines)
      .map(stripBulletPrefix)
      .filter(Boolean);
    const allBulletLines = bulletLines.length > 0 && (
      firstLineLooksLikeHeading
        ? remainder.every(isBulletLine)
        : lines.every(isBulletLine)
    );

    if (allBulletLines) {
      sections.push({
        type: "list",
        title: firstLineLooksLikeHeading ? firstLine : null,
        items: bulletLines,
      });
      continue;
    }

    sections.push({
      type: "paragraph",
      title: firstLineLooksLikeHeading ? firstLine : null,
      text: (firstLineLooksLikeHeading ? remainder : lines).join("\n"),
    });
  }

  return sections.length > 0 ? sections : null;
}

function isBulletLine(line: string): boolean {
  return /^[-*]\s+/u.test(line);
}

function stripBulletPrefix(line: string): string {
  return line.replace(/^[-*]\s+/u, "").trim();
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

function formatStepNumber(index: number): string {
  return String(index + 1).padStart(2, "0");
}
