import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ExecutionNodeProjection, StageItemProjection } from "../../../api/types";
import { mockFeedEntriesByType } from "../../../mocks/fixtures";
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
  it("renders a stage frame with summary, status, attempt, item count, and high-signal metrics", () => {
    render(<StageNode entry={requirementAnalysisStage} />);

    const article = screen.getByRole("article", { name: "Stage feed entry" });
    expect(
      within(article).getByRole("heading", { name: "Requirement Analysis" }),
    ).toBeTruthy();
    expect(within(article).getByText("Waiting Clarification")).toBeTruthy();
    expect(within(article).getByText("Attempt")).toBeTruthy();
    const attemptDatum = within(article).getByText("Attempt").closest(".stage-node__datum");
    expect(attemptDatum?.textContent).toContain("2");
    expect(within(article).getByText("8 items")).toBeTruthy();
    expect(
      within(article).getByText(
        "Clarifying the provider retry behavior before design starts.",
      ),
    ).toBeTruthy();
    expect(within(article).getAllByText("Duration").length).toBeGreaterThan(0);
    expect(within(article).getByText("2m 5s")).toBeTruthy();
    expect(within(article).getByText("Clarification Rounds")).toBeTruthy();
    expect(within(article).getByText("1,420")).toBeTruthy();
  });

  it("renders Requirement Analysis clarification as continuous stage-internal dialogue", () => {
    render(<StageNode entry={requirementAnalysisStage} />);

    const dialogueItems = screen.getAllByRole("listitem", {
      name: /Dialogue stage item/,
    });
    expect(dialogueItems).toHaveLength(2);
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

    expect(screen.getByRole("listitem", { name: "Reasoning stage item" })).toBeTruthy();
    expect(screen.getByText("The active run snapshot is immutable.")).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "Decision stage item" })).toBeTruthy();
    expect(screen.getByText("Freeze the provider binding per run.")).toBeTruthy();
    const toolItem = screen.getByRole("listitem", { name: "Tool Call stage item" });
    expect(toolItem).toBeTruthy();
    expect(within(toolItem).getAllByText("read_file frontend/src/api/types.ts")).toHaveLength(2);
    expect(screen.getByRole("listitem", { name: "Diff Preview stage item" })).toBeTruthy();
    expect(
      screen.getByText("frontend/src/features/feed/StageNode.tsx", { exact: false }),
    ).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "Result stage item" })).toBeTruthy();
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
      "Reasoning stage item",
      "Context stage item",
      "Model Call stage item",
      "Tool Call stage item",
      "Tool Confirmation stage item",
    ];

    for (const label of closedCompactLabels) {
      const item = screen.getByRole("listitem", { name: label });
      const details = item.querySelector("details");
      expect(details).toBeTruthy();
      expect(details?.hasAttribute("open")).toBe(false);
      expect(within(item).getByText(/remains visible/)).toBeTruthy();
    }

    const diffItem = screen.getByRole("listitem", { name: "Diff Preview stage item" });
    expect(diffItem.querySelector("details")).toBeTruthy();
  });

  it("renders provider calls with model binding, status, duration, retry, backoff, circuit, and details reference", () => {
    render(<StageNodeItems items={requirementAnalysisStage.items} />);

    const providerItem = screen.getByRole("listitem", {
      name: "Provider Call stage item",
    });
    expect(within(providerItem).getByText("provider-deepseek / deepseek-chat")).toBeTruthy();
    expect(within(providerItem).getByText("Retrying")).toBeTruthy();
    expect(within(providerItem).getByText("3.4s")).toBeTruthy();
    expect(within(providerItem).getByText("1 / 3")).toBeTruthy();
    expect(within(providerItem).getByText("Wait 2s")).toBeTruthy();
    expect(within(providerItem).getByText("Closed")).toBeTruthy();
    expect(within(providerItem).getByText("rate_limit")).toBeTruthy();
    expect(within(providerItem).getByText("provider-trace-1")).toBeTruthy();
  });

  it("uses StageNode for stage_node entries without changing other top-level feed semantics", () => {
    render(<FeedEntryRenderer entry={requirementAnalysisStage} />);

    expect(screen.getByRole("article", { name: "Stage feed entry" })).toBeTruthy();
    expect(screen.getByText("Requirement Analysis")).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "Provider Call stage item" })).toBeTruthy();

    cleanup();
    render(<FeedEntryRenderer entry={mockFeedEntriesByType.tool_confirmation} />);

    expect(
      screen.getByRole("article", { name: "Tool confirmation feed entry" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Allow this execution" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
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

    expect(screen.getByRole("listitem", { name: "Result stage item" })).toBeTruthy();
    expect(screen.getByText("Rendered without the list wrapper.")).toBeTruthy();
  });
});
