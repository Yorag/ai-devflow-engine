import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ExecutionNodeProjection, StageItemProjection } from "../../../api/types";
import {
  mockCodeGenerationStageNode,
  mockTestGenerationExecutionStageNode,
} from "../../../mocks/fixtures";
import { DiffPreview } from "../DiffPreview";
import { StageNodeItems } from "../StageNodeItems";
import { TestResultSummary } from "../TestResultSummary";
import { ToolCallItem } from "../ToolCallItem";

afterEach(() => {
  cleanup();
});

function findStageItem(
  entry: ExecutionNodeProjection,
  type: StageItemProjection["type"],
): StageItemProjection {
  const match = entry.items.find(
    (item): item is StageItemProjection => item.type === type,
  );
  if (!match) {
    throw new Error(`Missing ${type} item`);
  }
  return match;
}

describe("ToolCallItem", () => {
  it("renders tool name, target, command excerpt, duration, status, and folded output summary", () => {
    const item = findStageItem(mockCodeGenerationStageNode, "tool_call");

    render(<ToolCallItem item={item} />);

    const article = screen.getByRole("listitem", { name: "Tool Call stage item" });
    expect(within(article).getByText("bash pytest frontend")).toBeTruthy();
    expect(within(article).getByText("frontend/src/features/feed")).toBeTruthy();
    expect(within(article).getByText("Succeeded")).toBeTruthy();
    expect(within(article).getByText("2.4s")).toBeTruthy();
    const details = article.querySelector("details");
    expect(details).toBeTruthy();
    expect(details?.hasAttribute("open")).toBe(false);
    expect(within(article).getByText("stdout 4 lines, stderr 0 lines")).toBeTruthy();
  });

  it("keeps the stable item title visible when tool content is missing", () => {
    const item: StageItemProjection = {
      item_id: "tool-call-redacted",
      type: "tool_call",
      occurred_at: "2026-05-04T09:20:00.000Z",
      title: "Read redacted tool trace",
      summary: "Tool detail is unavailable in the feed projection.",
      content: null,
      artifact_refs: [],
      metrics: {},
    };

    render(<ToolCallItem item={item} />);

    const article = screen.getByRole("listitem", { name: "Tool Call stage item" });
    expect(within(article).getByText("Read redacted tool trace")).toBeTruthy();
    expect(within(article).getByText("Not recorded")).toBeTruthy();
  });
});

describe("DiffPreview", () => {
  it("renders affected files, representative diff snippet, and a folded extended preview", () => {
    const item = findStageItem(mockCodeGenerationStageNode, "diff_preview");

    render(<DiffPreview item={item} />);

    const article = screen.getByRole("listitem", { name: "Diff Preview stage item" });
    expect(
      within(article).getByText("frontend/src/features/feed/StageNodeItems.tsx"),
    ).toBeTruthy();
    expect(
      within(article).getByText("frontend/src/features/feed/ToolCallItem.tsx"),
    ).toBeTruthy();
    expect(within(article).getByText("@@ renderStageItemByType")).toBeTruthy();
    const details = article.querySelector("details");
    expect(details).toBeTruthy();
    expect(details?.hasAttribute("open")).toBe(false);
  });

  it("renders hunk snippets from fallback file-list content without an empty expander", () => {
    const item: StageItemProjection = {
      item_id: "diff-preview-fallback",
      type: "diff_preview",
      occurred_at: "2026-05-04T09:21:00.000Z",
      title: "Fallback diff preview",
      summary: "2 files changed.",
      content:
        "frontend/src/features/feed/DiffPreview.tsx\nfrontend/src/features/feed/TestResultSummary.tsx\n\n@@ fallbackHunk\n+ preserve representative hunk",
      artifact_refs: [],
      metrics: {},
    };

    render(<DiffPreview item={item} />);

    const article = screen.getByRole("listitem", { name: "Diff Preview stage item" });
    expect(
      within(article).getByText("frontend/src/features/feed/DiffPreview.tsx"),
    ).toBeTruthy();
    expect(within(article).getByText("@@ fallbackHunk")).toBeTruthy();
    expect(within(article).queryByText("More diff context")).toBeNull();
  });
});

describe("TestResultSummary", () => {
  it("renders generated, executed, passed, failed, skipped, and gap counts for test_generation_execution", () => {
    render(
      <TestResultSummary
        metrics={mockTestGenerationExecutionStageNode.metrics}
        resultItem={findStageItem(mockTestGenerationExecutionStageNode, "result")}
      />,
    );

    const article = screen.getByRole("region", { name: "Test result summary" });
    expect(within(article).getByText("Generated Tests")).toBeTruthy();
    expect(within(article).getByText("Executed Tests")).toBeTruthy();
    expect(within(article).getByText("Passed Tests")).toBeTruthy();
    expect(within(article).getByText("Failed Tests")).toBeTruthy();
    expect(within(article).getByText("Skipped Tests")).toBeTruthy();
    expect(within(article).getByText("Test Gaps")).toBeTruthy();
    expect(
      within(article).getByText(
        "Pytest finished with one failure and one uncovered branch.",
      ),
    ).toBeTruthy();
  });

  it("renders the test summary inline with stage items for test_generation_execution", () => {
    render(
      <StageNodeItems
        items={mockTestGenerationExecutionStageNode.items}
        stageType={mockTestGenerationExecutionStageNode.stage_type}
        stageMetrics={mockTestGenerationExecutionStageNode.metrics}
      />,
    );

    expect(screen.getByRole("region", { name: "Test result summary" })).toBeTruthy();
  });

  it("hides missing test metrics instead of rendering fabricated zeroes", () => {
    render(<TestResultSummary metrics={{ passed_test_count: 3 }} resultItem={null} />);

    const article = screen.getByRole("region", { name: "Test result summary" });
    expect(within(article).getByText("Passed Tests")).toBeTruthy();
    expect(within(article).getByText("3")).toBeTruthy();
    expect(within(article).queryByText("Generated Tests")).toBeNull();
    expect(within(article).queryByText("0")).toBeNull();
  });

  it("does not render a summary region when no metrics or result content exist", () => {
    render(<TestResultSummary metrics={{}} resultItem={null} />);

    expect(screen.queryByRole("region", { name: "Test result summary" })).toBeNull();
  });
});
