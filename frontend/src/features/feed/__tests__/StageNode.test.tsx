import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

function expandToolItem(
  container: HTMLElement,
  itemId: string,
  toggleName?: string | RegExp,
): HTMLElement {
  const toggle = toggleName
    ? within(container).getByRole("button", { name: toggleName })
    : within(container).getByRole("button");
  fireEvent.click(toggle);
  const details = container.querySelector(`#tool-call-details-${itemId}`);
  if (!(details instanceof HTMLElement)) {
    throw new Error(`Missing tool details for ${itemId}`);
  }
  return details;
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
      item_id: "model-call-1",
      type: "model_call",
      title: "Call deepseek-chat",
      summary: "Need to inspect the feed renderer before deciding the next action.",
      content: null,
      metrics: {
        model_call_type: "stage_execution",
        input_tokens: 180,
        output_tokens: 56,
        total_tokens: 236,
      },
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
      summary: "The stage can continue into Solution Design.",
      content: JSON.stringify(
        {
          structured_requirement: {
            summary: "Keep provider binding fixed for the active run.",
          },
          acceptance_criteria: [
            "Retries keep the original provider binding.",
            "New runs can use updated provider configuration.",
          ],
          clarification_summary:
            "The active run snapshot remains immutable once execution starts.",
          analysis_notes:
            "This preserves deterministic retry behavior and keeps provider changes scoped to future runs.",
        },
        null,
        2,
      ),
      artifact_refs: ["requirement-analysis-output"],
    }),
  ],
};

describe("StageNode", () => {
  it("renders a stripped stage header with status and summary but without timing and metric noise", () => {
    render(<StageNode entry={requirementAnalysisStage} />);

    const article = screen.getByRole("article", { name: "阶段执行流" });
    expect(
      within(article).getByRole("heading", { name: "需求分析" }),
    ).toBeTruthy();
    expect(within(article).getByText("等待澄清")).toBeTruthy();
    expect(
      within(article).getByText(
        "Clarifying the provider retry behavior before design starts.",
      ),
    ).toBeTruthy();
    expect(within(article).queryByText("阶段执行")).toBeNull();
    expect(within(article).queryByText("尝试")).toBeNull();
    expect(within(article).queryByText("执行步骤")).toBeNull();
    expect(within(article).queryByText("耗时")).toBeNull();
    expect(within(article).queryByText("澄清轮次")).toBeNull();
    expect(article.textContent).not.toContain("2026-05-01");
  });

  it("renders a readable execution flow without exposing machine refs or low-signal internal decisions", () => {
    render(<StageNode entry={requirementAnalysisStage} />);

    const article = screen.getByRole("article", { name: "阶段执行流" });

    const flow = article.querySelector(".stage-node-items");
    const steps = Array.from(flow?.children ?? []) as HTMLElement[];
    expect(steps).toHaveLength(5);
    expect(within(steps[0]).getByText("助手提问")).toBeTruthy();
    expect(within(steps[0]).getByText("Should the started run keep the original provider binding after a retry?")).toBeTruthy();
    expect(within(steps[2]).getByText("思考")).toBeTruthy();
    expect(within(steps[2]).getByText("The active run snapshot is immutable.")).toBeTruthy();
    expect(within(steps[3]).getByText("工具调用")).toBeTruthy();
    expect(
      within(steps[3]).getByRole("button", {
        name: /read_file frontend\/src\/api\/types\.ts/,
      }),
    ).toBeTruthy();
    const toolDetails = expandToolItem(
      steps[3],
      "tool-call-1",
      /read_file frontend\/src\/api\/types\.ts/,
    );
    expect(
      within(toolDetails).getByText(
        "Read the frozen projection types.",
      ),
    ).toBeTruthy();
    expect(
      within(toolDetails).getByText(
        "frontend/src/features/feed/StageNode.tsx",
        { exact: false },
      ),
    ).toBeTruthy();
    expect(within(steps[4]).getByText("阶段结果")).toBeTruthy();
    expect(within(steps[4]).getByText("The stage can continue into Solution Design.")).toBeTruthy();
    expect(within(steps[4]).getByText("需求")).toBeTruthy();
    expect(
      within(steps[4]).getByText(
        "摘要: Keep provider binding fixed for the active run.",
      ),
    ).toBeTruthy();
    expect(within(steps[4]).getByText("验收条件")).toBeTruthy();
    expect(within(steps[4]).getByText("Retries keep the original provider binding.")).toBeTruthy();

    expect(article.textContent).not.toContain("provider-trace-1");
    expect(article.textContent).not.toContain("provider-artifact-1");
    expect(article.textContent).not.toContain("provider-deepseek");
    expect(article.textContent).not.toContain("Command output");
    expect(article.textContent).not.toContain("requirement-analysis-output");
    expect(article.textContent).not.toContain("evidence_refs");
    expect(article.textContent).not.toContain("message-4944117081b84a85acefe870fa998f3e");
    expect(article.textContent).not.toContain("Freeze the provider binding per run.");
    expect(article.textContent).not.toContain("决策");
    expect(article.textContent).not.toContain("模型记录");
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

  it("renders only user-facing stage item types with distinct content", () => {
    render(<StageNodeItems items={requirementAnalysisStage.items} />);

    expect(screen.getByRole("listitem", { name: "思考" })).toBeTruthy();
    expect(screen.getByText("The active run snapshot is immutable.")).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "决策" })).toBeNull();
    expect(screen.queryByRole("listitem", { name: "模型记录" })).toBeNull();
    const toolItem = screen.getByRole("listitem", { name: "工具调用" });
    expect(toolItem).toBeTruthy();
    expect(
      within(toolItem).getByRole("button", {
        name: /read_file frontend\/src\/api\/types\.ts/,
      }),
    ).toBeTruthy();
    const toolDetails = expandToolItem(
      toolItem,
      "tool-call-1",
      /read_file frontend\/src\/api\/types\.ts/,
    );
    expect(
      within(toolDetails).getByText(
        "Read the frozen projection types.",
      ),
    ).toBeTruthy();
    expect(
      within(toolDetails).getByText(
        "frontend/src/features/feed/StageNode.tsx",
        { exact: false },
      ),
    ).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "阶段结果" })).toBeTruthy();
    expect(screen.getByText("The stage can continue into Solution Design.")).toBeTruthy();
    expect(
      screen.getByText("摘要: Keep provider binding fixed for the active run."),
    ).toBeTruthy();
    expect(screen.getByText("The active run snapshot remains immutable once execution starts.")).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "模型服务调用" })).toBeNull();
    expect(screen.queryByRole("listitem", { name: "变更预览" })).toBeNull();
  });

  it("renders expandable details for visible compact item types while suppressing hidden internal trace items", () => {
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
            item_id: "compact-decision",
            type: "decision",
            title: "Decision",
            summary: "Decision remains visible.",
            content: "Decision details should be expandable.",
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

    const closedCompactLabels = ["思考", "上下文"];

    for (const label of closedCompactLabels) {
      const item = screen.getByRole("listitem", { name: label });
      const details = item.querySelector("details");
      expect(details).toBeTruthy();
      expect(details?.hasAttribute("open")).toBe(false);
      expect(within(item).getByText(/remains visible/)).toBeTruthy();
    }

    const toolItem = screen.getByRole("listitem", { name: "工具调用" });
    const toolDetails = expandToolItem(toolItem, "compact-tool-call");
    expect(
      within(toolDetails).getByText("Tool call remains visible."),
    ).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "模型记录" })).toBeNull();
    expect(screen.queryByRole("listitem", { name: "变更预览" })).toBeNull();
    expect(screen.queryByRole("listitem", { name: "工具确认" })).toBeNull();
    expect(screen.queryByRole("listitem", { name: "决策" })).toBeNull();
  });

  it("hides provider telemetry from the main execution flow", () => {
    render(<StageNodeItems items={requirementAnalysisStage.items} />);

    expect(screen.queryByRole("listitem", { name: "模型服务调用" })).toBeNull();
    expect(screen.queryByText("provider-deepseek")).toBeNull();
    expect(screen.queryByText("rate_limit")).toBeNull();
  });

  it("uses StageNode for stage_node entries without changing other top-level feed semantics", () => {
    render(<FeedEntryRenderer entry={requirementAnalysisStage} />);

    expect(screen.getByRole("article", { name: "阶段执行流" })).toBeTruthy();
    expect(screen.getByText("需求分析")).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "模型服务调用" })).toBeNull();

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

  it("renders merged tool execution content instead of splitting command and diff into separate main-flow blocks", () => {
    render(<StageNode entry={mockCodeGenerationStageNode} />);

    const toolItem = screen.getByRole("listitem", { name: "工具调用" });
    expect(toolItem.textContent).not.toContain("成功，耗时");
    expect(toolItem.textContent).not.toContain("tool-call-ref");
    expect(toolItem.textContent).not.toContain("sha256:");
    expect(
      within(toolItem).getByRole("button", { name: /bash pytest frontend/ }),
    ).toBeTruthy();
    const details = expandToolItem(
      toolItem,
      "tool-call-codegen-1",
      /bash pytest frontend/,
    );
    expect(within(details).getByText("stdout 4 lines, stderr 0 lines")).toBeTruthy();
    expect(
      within(details).getByText(
        "frontend/src/features/feed/ToolCallItem.tsx",
      ),
    ).toBeTruthy();
    expect(
      within(details).getByText("@@ renderStageItemByType"),
    ).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "变更预览" })).toBeNull();
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
