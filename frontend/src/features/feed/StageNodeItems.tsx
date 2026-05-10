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
  const readableContent =
    item.type === "result" ? readResultContent(item.content) : readReadableContent(item.content);
  const resultContent =
    item.type === "result" ? parseResultContent(readableContent?.text ?? "") : null;
  const resultSummary =
    item.type === "result" ? readResultSummary(item.summary, resultContent) : null;

  return (
    <li
      className={`stage-node-item stage-node-item--${item.type}`}
      aria-label={stageItemLabels[item.type]}
    >
      {item.type === "result" ? null : (
        <StageItemHeader item={item} stepIndex={stepIndex} />
      )}
      {item.type === "result" ? (
        <ResultMarkdownPanel summary={resultSummary} sections={resultContent} />
      ) : readableContent && readableContent.text !== item.summary ? (
        <p className="stage-node-item__content">{readableContent.text}</p>
      ) : null}
      {item.type !== "result" && item.summary ? (
        <p className="stage-node-item__summary">{item.summary}</p>
      ) : null}
    </li>
  );
}

type ResultSection = {
  title: string | null;
  paragraphs: string[];
  bullets: ResultBullet[];
};

type ResultBullet = {
  text: string;
  level: number;
};

function ResultMarkdownPanel({
  summary,
  sections,
}: {
  summary: string | null;
  sections: ResultSection[] | null;
}): JSX.Element | null {
  if (!summary && (!sections || sections.length === 0)) {
    return null;
  }

  return (
    <div className="stage-result-panel" aria-label="Stage result content">
      {summary ? <p className="stage-result-panel__summary">{summary}</p> : null}
      {sections?.map((section, index) => (
        <section
          key={`${section.title ?? "result"}-${index}`}
          className="stage-result-panel__section"
        >
          {section.title ? (
            <p className="stage-result-panel__line stage-result-panel__line--heading">
              {`## ${section.title}`}
            </p>
          ) : null}
          {section.paragraphs.map((paragraph) => (
            <p key={paragraph} className="stage-result-panel__line">
              {paragraph}
            </p>
          ))}
          {section.bullets.map((bullet) => (
            <p
              key={`${bullet.level}-${bullet.text}`}
              className={`stage-result-panel__line stage-result-panel__line--bullet stage-result-panel__line--bullet-level-${bullet.level}`}
            >
              {`- ${bullet.text}`}
            </p>
          ))}
        </section>
      ))}
    </div>
  );
}

function readResultSummary(
  value: string | null,
  sections: ResultSection[] | null,
): string | null {
  const trimmed = value?.trim();
  if (!trimmed || isArtifactSummary(trimmed)) {
    return null;
  }
  return resultSectionsContainText(sections, trimmed) ? null : trimmed;
}

function resultSectionsContainText(
  sections: ResultSection[] | null,
  candidate: string,
): boolean {
  if (!sections) {
    return false;
  }

  return sections.some((section) =>
    section.paragraphs.includes(candidate)
    || section.bullets.some((bullet) => bullet.text === candidate),
  );
}

function isArtifactSummary(value: string): boolean {
  return value.toLowerCase().replace(/[\s_-]+/gu, "").endsWith("artifact");
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

function readResultContent(
  content: string | null,
): { text: string; source: "plain" | "structured" } | null {
  const trimmed = content?.trim();
  if (!trimmed) {
    return null;
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

  const structuredSections = parseStructuredResultContent(trimmed);
  if (structuredSections) {
    return structuredSections;
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
    const contentLines = firstLineLooksLikeHeading ? remainder : lines;
    const bulletLines = contentLines
      .map(stripBulletPrefix)
      .filter(Boolean);
    const allBulletLines = bulletLines.length > 0 && contentLines.every(isBulletLine);
    const textLines = allBulletLines ? [] : contentLines;

    sections.push({
      title: firstLineLooksLikeHeading ? firstLine : null,
      paragraphs: textLines.length > 0 ? [textLines.join("\n")] : [],
      bullets: allBulletLines
        ? bulletLines.map((bullet) => ({ text: bullet, level: 0 }))
        : [],
    });
  }

  return sections.length > 0 ? sections : null;
}

function parseStructuredResultContent(text: string): ResultSection[] | null {
  if (!text.startsWith("{") && !text.startsWith("[")) {
    return null;
  }

  try {
    const parsed = JSON.parse(text) as unknown;
    const sections = resultSectionsFromStructuredValue(parsed);
    return sections.length > 0 ? sections : null;
  } catch {
    return null;
  }
}

function resultSectionsFromStructuredValue(value: unknown): ResultSection[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return [];
  }

  const record = value as Record<string, unknown>;
  const sections: ResultSection[] = [];

  for (const [key, raw] of Object.entries(record)) {
    const title = formatResultKey(key);
    const section = resultSectionFromValue(title, raw);
    if (section) {
      sections.push(section);
    }
  }

  return sections;
}

function resultSectionFromValue(
  title: string,
  value: unknown,
): ResultSection | null {
  if (title === "实施计划" && value && typeof value === "object" && !Array.isArray(value)) {
    const section = formatImplementationPlanSection(value as Record<string, unknown>);
    if (section) {
      return {
        title,
        ...section,
      };
    }
  }

  if (typeof value === "string") {
    const text = value.trim();
    return text
      ? {
          title,
          paragraphs: [text],
          bullets: [],
        }
      : null;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return {
      title,
      paragraphs: [String(value)],
      bullets: [],
    };
  }

  if (Array.isArray(value)) {
    const items = value
      .flatMap((item) => formatStructuredListItem(item))
      .filter(Boolean);
    return items.length > 0
      ? {
          title,
          paragraphs: [],
          bullets: items.map((item) => ({ text: item, level: 0 })),
        }
      : null;
  }

  if (value && typeof value === "object") {
    const nestedObject = value as Record<string, unknown>;
    const summary = readStructuredSectionSummary(nestedObject);
    const nestedItems = formatStructuredObjectItems(nestedObject);
    if (!summary && nestedItems.length === 0) {
      return null;
    }
    return {
      title,
      paragraphs: summary ? [summary] : [],
      bullets: nestedItems.map((item) => ({ text: item, level: 0 })),
    };
  }

  return null;
}

function formatStructuredListItem(value: unknown): string[] {
  if (typeof value === "string") {
    const text = value.trim();
    return text ? [text] : [];
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return [String(value)];
  }
  if (value && typeof value === "object") {
    return formatStructuredObjectItems(value as Record<string, unknown>);
  }
  return [];
}

function formatImplementationPlanSection(
  value: Record<string, unknown>,
): Omit<ResultSection, "title"> | null {
  const paragraphs = readStructuredSectionSummary(value)
    ? [readStructuredSectionSummary(value) as string]
    : [];
  const bullets: ResultBullet[] = [];

  for (const [key, nestedValue] of Object.entries(value)) {
    if (
      key === "summary" ||
      key === "plan_id" ||
      key === "downstream_refs"
    ) {
      continue;
    }

    if (key === "tasks" && Array.isArray(nestedValue)) {
      bullets.push(...formatImplementationTasks(nestedValue));
      continue;
    }

    const label = formatResultKey(key);
    bullets.push(
      ...formatStructuredNamedItems(label, nestedValue).map((item) => ({
        text: item,
        level: 0,
      })),
    );
  }

  if (paragraphs.length === 0 && bullets.length === 0) {
    return null;
  }

  return {
    paragraphs,
    bullets,
  };
}

function formatImplementationTasks(value: unknown[]): ResultBullet[] {
  const bullets: ResultBullet[] = [];

  value.forEach((task, index) => {
    if (!task || typeof task !== "object" || Array.isArray(task)) {
      return;
    }

    const taskRecord = task as Record<string, unknown>;
    bullets.push({
      text: formatImplementationTaskTitle(taskRecord, index),
      level: 0,
    });

    bullets.push(
      ...formatImplementationTaskDetails(taskRecord).map((detail) => ({
        text: detail,
        level: 1,
      })),
    );
  });

  return bullets;
}

function formatImplementationTaskTitle(
  value: Record<string, unknown>,
  index: number,
): string {
  const order =
    typeof value.order_index === "number" && Number.isFinite(value.order_index)
      ? value.order_index
      : index + 1;
  const workDescription =
    typeof value.work_description === "string" && value.work_description.trim()
      ? value.work_description.trim()
      : null;

  return workDescription ? `任务 ${order}: ${workDescription}` : `任务 ${order}`;
}

function formatImplementationTaskDetails(
  value: Record<string, unknown>,
): string[] {
  const orderedKeys = [
    "target_files",
    "verification_commands",
    "dependency_assumptions",
    "risk_handling",
  ];
  const consumed = new Set([
    "task_id",
    "order_index",
    "work_description",
    "summary",
  ]);
  const lines: string[] = [];

  for (const key of orderedKeys) {
    if (!(key in value)) {
      continue;
    }
    consumed.add(key);
    lines.push(...formatStructuredNamedItems(formatResultKey(key), value[key]));
  }

  for (const [key, nestedValue] of Object.entries(value)) {
    if (consumed.has(key)) {
      continue;
    }
    lines.push(...formatStructuredNamedItems(formatResultKey(key), nestedValue));
  }

  return lines;
}

function formatStructuredObjectItems(
  value: Record<string, unknown>,
): string[] {
  return Object.entries(value).flatMap(([nestedKey, nestedValue]) =>
    formatStructuredNamedItems(formatResultKey(nestedKey), nestedValue),
  );
}

function formatStructuredNamedItems(
  label: string,
  value: unknown,
): string[] {
  if (shouldHideStructuredResultKey(label) || label === "摘要") {
    return [];
  }

  if (typeof value === "string") {
    const text = value.trim();
    return text ? [`${label}: ${text}`] : [];
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return [`${label}: ${String(value)}`];
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return [];
    }

    if (value.every((item) => typeof item !== "object" || item === null)) {
      return value
        .map((item) => formatStructuredInlineValue(item))
        .filter((item): item is string => Boolean(item))
        .map((item) => `${label}: ${item}`);
    }

    return value.flatMap((item) => {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        return formatStructuredObjectItems(item as Record<string, unknown>);
      }
      const formatted = formatStructuredInlineValue(item);
      return formatted ? [`${label}: ${formatted}`] : [];
    });
  }

  if (value && typeof value === "object") {
    return formatStructuredObjectItems(value as Record<string, unknown>);
  }

  return [];
}

function shouldHideStructuredResultKey(label: string): boolean {
  return label === "Plan Id" || label === "Task Id" || label === "Downstream Refs";
}

function formatStructuredInlineValue(value: unknown): string | null {
  if (typeof value === "string") {
    const text = value.trim();
    return text || null;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => formatStructuredInlineValue(item))
      .filter((item): item is string => Boolean(item));
    return parts.length > 0 ? parts.join(", ") : null;
  }
  if (value && typeof value === "object") {
    const parts = Object.entries(value as Record<string, unknown>)
      .map(([key, nestedValue]) => {
        const formatted = formatStructuredInlineValue(nestedValue);
        return formatted ? `${formatResultKey(key)}: ${formatted}` : null;
      })
      .filter((item): item is string => Boolean(item));
    return parts.length > 0 ? parts.join("；") : null;
  }
  return null;
}

function formatResultKey(value: string): string {
  const labels: Record<string, string> = {
    structured_requirement: "需求",
    acceptance_criteria: "验收条件",
    clarification_summary: "澄清结论",
    assumptions: "关键假设",
    non_goals: "非目标",
    open_questions: "待确认问题",
    analysis_notes: "分析说明",
    technical_plan: "方案",
    implementation_plan: "实施计划",
    impacted_files: "影响范围",
    api_design: "接口设计",
    data_flow_design: "数据流设计",
    risks: "风险",
    test_strategy: "验证策略",
    validation_report: "校验结论",
    changed_files: "修改文件",
    implementation_notes: "实现说明",
    completed_steps: "已完成内容",
    remaining_steps: "剩余工作",
    generated_tests: "新增测试",
    executed_tests: "执行内容",
    test_execution_result: "测试结果",
    test_gap_report: "测试缺口",
    failed_test_refs: "失败项",
    review_report: "评审结论",
    issue_list: "问题列表",
    risk_assessment: "风险评估",
    fix_requirements: "修复要求",
    regression_decision: "回归建议",
    summary: "摘要",
    change_type: "变更类型",
    scope_note: "范围说明",
    plan_id: "Plan Id",
    task_id: "Task Id",
    order_index: "顺序",
    title: "标题",
    target_files: "目标文件",
    work_description: "工作内容",
    verification_commands: "验证命令",
    dependency_assumptions: "依赖假设",
    risk_handling: "风险处理",
    downstream_refs: "Downstream Refs",
  };
  return labels[value] ?? formatLabel(value);
}

function readStructuredSectionSummary(
  value: Record<string, unknown>,
): string | null {
  const summary = value.summary;
  return typeof summary === "string" && summary.trim() ? summary.trim() : null;
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
