import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ExecutionNodeProjection, StageItemProjection } from "../../../api/types";
import {
  mockCodeGenerationStageNode,
  mockFeedEntriesByType,
  mockTestGenerationExecutionStageNode,
} from "../../../mocks/fixtures";
import { FeedEntryRenderer } from "../FeedEntryRenderer";
import { StageNode } from "../StageNode";
import { renderStageItemByType, StageNodeItems } from "../StageNodeItems";

afterEach(() => {
  cleanup();
});

const occurredAt = "2026-05-01T09:12:00.000Z";

function stageItem(
  overrides: Partial<StageItemProjection> &
    Pick<StageItemProjection, "item_id" | "type" | "title">,
): StageItemProjection {
  return {
    occurred_at: occurredAt,
    summary: null,
    content: null,
    artifact_refs: [],
    metrics: {},
    ...overrides,
  };
}

const requirementAnalysisStage: ExecutionNodeProjection = {
  entry_id: "entry-requirement-analysis",
  run_id: "run-waiting-clarification",
  type: "stage_node",
  occurred_at: occurredAt,
  stage_run_id: "stage-requirement-analysis",
  stage_type: "requirement_analysis",
  status: "waiting_clarification",
  attempt_index: 2,
  started_at: "2026-05-01T09:12:00.000Z",
  ended_at: null,
  summary: "Clarifying the provider retry behavior before design starts.",
  metrics: {
    duration_ms: 125000,
    clarification_rounds: 2,
    total_tokens: 1420,
  },
  items: [
    stageItem({
      item_id: "dialogue-question",
      type: "dialogue",
      title: "Assistant clarification question",
      summary: "The provider fallback rule is ambiguous.",
      content: "Should the started run keep the original provider binding after a retry?",
    }),
    stageItem({
      item_id: "dialogue-answer",
      type: "dialogue",
      title: "User clarification reply",
      content: "Keep the original provider binding for the active run.",
    }),
    stageItem({
      item_id: "reasoning-1",
      type: "reasoning",
      title: "Reasoning trace",
      summary: "The active run snapshot is immutable.",
      content: "The runtime snapshot must not change provider semantics after the run starts.",
    }),
    stageItem({
      item_id: "decision-1",
      type: "decision",
      title: "Decision",
      summary: "Freeze the provider binding per run.",
      content: "This keeps retries deterministic and leaves provider changes for new runs.",
    }),
    {
      item_id: "provider-call-1",
      type: "provider_call",
      occurred_at: "2026-05-01T09:14:00.000Z",
      title: "Provider call",
      summary: "Provider call is retrying after a rate limit.",
      content: null,
      artifact_refs: ["provider-artifact-1"],
      metrics: { duration_ms: 3400, total_tokens: 1200 },
      provider_id: "provider-deepseek",
      model_id: "deepseek-chat",
      status: "retrying",
      retry_attempt: 1,
      max_retry_attempts: 3,
      backoff_wait_seconds: 2,
      circuit_breaker_status: "closed",
      failure_reason: "rate_limit",
      process_ref: "provider-trace-1",
    },
    stageItem({
      item_id: "tool-call-1",
      type: "tool_call",
      title: "read_file frontend/src/api/types.ts",
      summary: "Read the frozen projection types.",
      content: "read_file frontend/src/api/types.ts",
      metrics: { file_count: 1 },
    }),
    stageItem({
      item_id: "diff-preview-1",
      type: "diff_preview",
      title: "Diff preview",
      summary: "2 files changed.",
      content: "frontend/src/features/feed/StageNode.tsx\n+ StageNode",
      artifact_refs: ["changeset-1"],
      metrics: { changed_file_count: 2 },
    }),
    stageItem({
      item_id: "result-1",
      type: "result",
      title: "Requirement analysis result",
      summary: "Provider binding behavior is now explicit.",
      content: "The stage can continue into Solution Design.",
      artifact_refs: ["requirement-analysis-output"],
    }),
  ],
};

describe("StageNode", () => {
  it("renders a localized stage frame with summary, status, attempt, item count, and high-signal metrics", () => {
    render(<StageNode entry={requirementAnalysisStage} />);

    const article = screen.getByRole("article", { name: "阶段节点" });
    expect(
      within(article).getByRole("heading", { name: "需求分析" }),
    ).toBeTruthy();
    expect(within(article).getByText("等待澄清")).toBeTruthy();
    expect(within(article).getByText("阶段")).toBeTruthy();
    expect(within(article).getByText("尝试次数")).toBeTruthy();
    const attemptDatum = within(article).getByText("尝试次数").closest(".stage-node__datum");
    expect(attemptDatum?.textContent).toContain("2");
    expect(within(article).getByText("8 项")).toBeTruthy();
    expect(
      within(article).getByText(
        "Clarifying the provider retry behavior before design starts.",
      ),
    ).toBeTruthy();
    expect(within(article).getAllByText("耗时").length).toBeGreaterThan(0);
    expect(within(article).getByText("2m 5s")).toBeTruthy();
    expect(within(article).getByText("澄清轮次")).toBeTruthy();
    expect(within(article).getByText("1,420")).toBeTruthy();
  });

  it("renders Requirement Analysis clarification as localized continuous dialogue rows", () => {
    render(<StageNode entry={requirementAnalysisStage} />);

    const dialogueItems = screen.getAllByRole("listitem", {
      name: /澄清对话/,
    });
    expect(dialogueItems).toHaveLength(2);
    expect(within(dialogueItems[0]).getByText("助手提问")).toBeTruthy();
    expect(within(dialogueItems[1]).getByText("用户回复")).toBeTruthy();
    expect(
      within(dialogueItems[0]).getByText(
        "Should the started run keep the original provider binding after a retry?",
      ),
    ).toBeTruthy();
    expect(
      within(dialogueItems[1]).getByText(
        "Keep the original provider binding for the active run.",
      ),
    ).toBeTruthy();
  });

  it("renders all required stage-internal item types with distinct content", () => {
    render(<StageNodeItems items={requirementAnalysisStage.items} />);

    expect(screen.getByRole("listitem", { name: "推理记录" })).toBeTruthy();
    expect(screen.getByText("The active run snapshot is immutable.")).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "决策" })).toBeTruthy();
    expect(screen.getByText("Freeze the provider binding per run.")).toBeTruthy();
    const toolItem = screen.getByRole("listitem", { name: "工具调用" });
    expect(toolItem).toBeTruthy();
    expect(within(toolItem).getAllByText("read_file frontend/src/api/types.ts")).toHaveLength(2);
    expect(screen.getByRole("listitem", { name: "变更预览" })).toBeTruthy();
    expect(
      screen.getByText("frontend/src/features/feed/StageNode.tsx", { exact: false }),
    ).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "阶段结果" })).toBeTruthy();
    expect(screen.getByText("The stage can continue into Solution Design.")).toBeTruthy();
  });

  it("renders expandable details for compact long-content item types and folds tool calls by default", () => {
    render(
      <StageNodeItems
        items={[
          stageItem({
            item_id: "compact-reasoning",
            type: "reasoning",
            title: "Reasoning trace",
            summary: "Reasoning remains visible.",
            content: "Detailed reasoning content should be expandable.",
          }),
          stageItem({
            item_id: "compact-context",
            type: "context",
            title: "Context bundle",
            summary: "Context remains visible.",
            content: "Long context content should be expandable.",
          }),
          stageItem({
            item_id: "compact-model-call",
            type: "model_call",
            title: "Model call",
            summary: "Model call remains visible.",
            content: "Model request and response content should be expandable.",
          }),
          stageItem({
            item_id: "compact-tool-call",
            type: "tool_call",
            title: "Tool call",
            summary: "Tool call remains visible.",
            content: "Long tool command output should start folded.",
          }),
          stageItem({
            item_id: "compact-tool-confirmation",
            type: "tool_confirmation",
            title: "Internal tool confirmation trace",
            summary: "Tool confirmation remains visible.",
            content: "Internal tool confirmation details should be expandable.",
          }),
          stageItem({
            item_id: "compact-diff-preview",
            type: "diff_preview",
            title: "Diff preview",
            summary: "Diff preview remains visible.",
            content: "Diff preview content may remain open.",
          }),
        ]}
      />,
    );

    const closedCompactLabels = [
      "推理记录",
      "上下文",
      "模型调用",
      "工具调用",
      "工具确认",
    ];

    for (const label of closedCompactLabels) {
      const item = screen.getByRole("listitem", { name: label });
      const details = item.querySelector("details");
      expect(details).toBeTruthy();
      expect(details?.hasAttribute("open")).toBe(false);
      expect(within(item).getByText(/remains visible/)).toBeTruthy();
    }

    const diffItem = screen.getByRole("listitem", { name: "变更预览" });
    expect(diffItem.querySelector("details")).toBeNull();
  });

  it("renders provider calls with model binding, status, duration, retry, backoff, circuit, and details reference", () => {
    render(<StageNodeItems items={requirementAnalysisStage.items} />);

    const providerItem = screen.getByRole("listitem", {
      name: "模型服务调用",
    });
    expect(within(providerItem).getByText("provider-deepseek / deepseek-chat")).toBeTruthy();
    expect(within(providerItem).getByText("重试中")).toBeTruthy();
    expect(within(providerItem).getByText("3.4s")).toBeTruthy();
    expect(within(providerItem).getByText("1 / 3")).toBeTruthy();
    expect(within(providerItem).getByText("等待 2s")).toBeTruthy();
    expect(within(providerItem).getByText("关闭")).toBeTruthy();
    expect(within(providerItem).getByText("rate_limit")).toBeTruthy();
    expect(within(providerItem).getByText("provider-trace-1")).toBeTruthy();
  });

  it("uses StageNode for stage_node entries without changing other top-level feed semantics", () => {
    render(<FeedEntryRenderer entry={requirementAnalysisStage} />);

    expect(screen.getByRole("article", { name: "阶段节点" })).toBeTruthy();
    expect(screen.getByText("需求分析")).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "模型服务调用" })).toBeTruthy();

    cleanup();
    render(<FeedEntryRenderer entry={mockFeedEntriesByType.tool_confirmation} />);

    expect(
      screen.getByRole("article", { name: "Tool confirmation feed entry" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "允许本次执行" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "批准" })).toBeNull();
  });

  it("exposes the direct stage item render helper", () => {
    render(
      renderStageItemByType(
        stageItem({
          item_id: "direct-result",
          type: "result",
          title: "Direct result",
          content: "Rendered without the list wrapper.",
        }),
      ),
    );

    expect(screen.getByRole("listitem", { name: "阶段结果" })).toBeTruthy();
    expect(screen.getByText("Rendered without the list wrapper.")).toBeTruthy();
  });

  it("renders specialized tool-call and diff-preview content instead of the generic compact block", () => {
    render(<StageNode entry={mockCodeGenerationStageNode} />);

    const toolItem = screen.getByRole("listitem", { name: "工具调用" });
    expect(within(toolItem).getByText("目标")).toBeTruthy();
    expect(within(toolItem).getByText("成功")).toBeTruthy();
    expect(within(toolItem).getByText("stdout 4 lines, stderr 0 lines")).toBeTruthy();

    const diffItem = screen.getByRole("listitem", { name: "变更预览" });
    expect(
      within(diffItem).getByText("frontend/src/features/feed/ToolCallItem.tsx"),
    ).toBeTruthy();
    expect(within(diffItem).getByText("@@ renderStageItemByType")).toBeTruthy();
  });

  it("renders test-result summary above test_generation_execution internal items", () => {
    render(<StageNode entry={mockTestGenerationExecutionStageNode} />);

    const summary = screen.getByRole("region", { name: "Test result summary" });
    expect(within(summary).getByText("生成测试")).toBeTruthy();
    expect(within(summary).getByText("1")).toBeTruthy();
    expect(within(summary).getByText("7")).toBeTruthy();
    expect(
      within(summary).getByText(
        "Pytest finished with one failure and one uncovered branch.",
      ),
    ).toBeTruthy();
  });
});
