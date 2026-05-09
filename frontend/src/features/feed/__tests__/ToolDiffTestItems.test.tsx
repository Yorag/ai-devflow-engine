import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ExecutionNodeProjection, StageItemProjection } from "../../../api/types";
import {
  backendContractCodeGenerationStageNode,
  backendContractTestGenerationExecutionStageNode,
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
  it("renders the tool command as the fold header with raw output inside", () => {
    const item = findStageItem(mockCodeGenerationStageNode, "tool_call");

    render(<ToolCallItem item={item} />);

    const article = screen.getByRole("listitem", { name: "工具调用" });
    const toggle = within(article).getByRole("button", {
      name: /bash pytest frontend/,
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const details = article.querySelector(`#tool-call-details-${item.item_id}`);
    expect(details?.hasAttribute("hidden")).toBe(false);
    expect(within(details as HTMLElement).getByText("stdout 4 lines, stderr 0 lines")).toBeTruthy();
    expect(
      within(details as HTMLElement).getByText((_, element) =>
        element?.tagName.toLowerCase() === "pre" &&
        element.textContent?.includes("> collected 4 items") === true,
      ),
    ).toBeTruthy();
    expect(article.textContent).not.toContain("成功，耗时");
    expect(article.textContent).not.toContain("Target:");
    expect(article.textContent).not.toContain("Status:");
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

    const article = screen.getByRole("listitem", { name: "工具调用" });
    const toggle = within(article).getByRole("button", {
      name: /Read redacted tool trace/,
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const details = article.querySelector(`#tool-call-details-${item.item_id}`);
    expect(details?.hasAttribute("hidden")).toBe(false);
    expect(within(article).getByText("Read redacted tool trace")).toBeTruthy();
    expect(within(details as HTMLElement).getByText("Tool detail is unavailable in the feed projection.")).toBeTruthy();
    expect(article.textContent).not.toContain("Command output");
    expect(article.textContent).not.toContain("未记录");
    expect(article.querySelector("details")).toBeNull();
  });

  it("renders grep-style tool output as one consistent text block instead of mixing summary and monospace output", () => {
    const item: StageItemProjection = {
      item_id: "tool-call-grep",
      type: "tool_call",
      occurred_at: "2026-05-04T09:20:00.000Z",
      title: 'grep pattern="Make delivery work traceable" path=frontend',
      summary: null,
      content:
        'grep pattern="Make delivery work traceable" path=frontend\nfrontend/src/pages/HomePage.tsx:87: <h1>Make delivery work traceable.</h1>\nfrontend/src/pages/__tests__/ConsolePage.test.tsx:88: name: "Make delivery work traceable.",',
      artifact_refs: [],
      metrics: {},
    };

    render(<ToolCallItem item={item} />);

    const article = screen.getByRole("listitem", { name: "工具调用" });
    const toggle = within(article).getByRole("button", {
      name: /grep pattern="Make delivery work traceable" path=frontend/,
    });
    fireEvent.click(toggle);

    const details = article.querySelector(`#tool-call-details-${item.item_id}`);
    expect(details).toBeTruthy();
    expect(
      Array.from((details as HTMLElement).querySelectorAll(".stage-node-item__tool-plain-output p")),
    ).toHaveLength(2);
    expect(within(details as HTMLElement).queryByText((_, element) => element?.tagName.toLowerCase() === "pre")).toBeNull();
  });
});

describe("DiffPreview", () => {
  it("renders affected files, representative diff snippet, and a folded extended preview", () => {
    const item = findStageItem(mockCodeGenerationStageNode, "diff_preview");

    render(<DiffPreview item={item} />);

    const article = screen.getByRole("listitem", { name: "变更预览" });
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

    const article = screen.getByRole("listitem", { name: "变更预览" });
    expect(
      within(article).getByText("frontend/src/features/feed/DiffPreview.tsx"),
    ).toBeTruthy();
    expect(within(article).getByText("@@ fallbackHunk")).toBeTruthy();
    expect(within(article).queryByText("查看更多变更上下文")).toBeNull();
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
    expect(within(article).getByText("生成测试")).toBeTruthy();
    expect(within(article).getByText("执行测试")).toBeTruthy();
    expect(within(article).getByText("通过测试")).toBeTruthy();
    expect(within(article).getByText("失败测试")).toBeTruthy();
    expect(within(article).getByText("跳过测试")).toBeTruthy();
    expect(within(article).getByText("测试缺口")).toBeTruthy();
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
    expect(within(article).getByText("通过测试")).toBeTruthy();
    expect(within(article).getByText("3")).toBeTruthy();
    expect(within(article).queryByText("生成测试")).toBeNull();
    expect(within(article).queryByText("0")).toBeNull();
  });

  it("does not render a summary region when no metrics or result content exist", () => {
    render(<TestResultSummary metrics={{}} resultItem={null} />);

    expect(screen.queryByRole("region", { name: "Test result summary" })).toBeNull();
  });
});

describe("real backend code and test generation payload contract", () => {
  it("renders backend StageItemProjection payloads for code_generation without a mock-only field shape", () => {
    render(
      <StageNodeItems
        items={backendContractCodeGenerationStageNode.items}
        stageType={backendContractCodeGenerationStageNode.stage_type}
        stageMetrics={backendContractCodeGenerationStageNode.metrics}
      />,
    );

    const toolItem = screen.getByRole("listitem", { name: "工具调用" });
    expect(toolItem.textContent).not.toContain("成功，耗时");
    expect(toolItem.textContent).not.toContain("tool-call-ref-codegen");
    const toggle = within(toolItem).getByRole("button", {
      name: /edit_file apply implementation patch/,
    });
    fireEvent.click(toggle);
    const details = toolItem.querySelector(
      `#tool-call-details-${findStageItem(backendContractCodeGenerationStageNode, "tool_call").item_id}`,
    );
    expect(details?.hasAttribute("hidden")).toBe(false);
    expect(within(details as HTMLElement).getByText("patch applied, 1 file changed")).toBeTruthy();
    expect(within(details as HTMLElement).getByText("backend/app/schemas/feed.py")).toBeTruthy();
    expect(within(details as HTMLElement).getByText("@@ StageItemProjection")).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "变更预览" })).toBeNull();
  });

  it("renders backend MetricSet-style test_generation_execution payloads and hides omitted metrics", () => {
    render(
      <StageNodeItems
        items={backendContractTestGenerationExecutionStageNode.items}
        stageType={backendContractTestGenerationExecutionStageNode.stage_type}
        stageMetrics={backendContractTestGenerationExecutionStageNode.metrics}
      />,
    );

    const summary = screen.getByRole("region", { name: "Test result summary" });
    expect(within(summary).getByText("生成测试")).toBeTruthy();
    expect(within(summary).getByText("执行测试")).toBeTruthy();
    expect(within(summary).getByText("失败测试")).toBeTruthy();
    expect(within(summary).getByText("Contract payload passed schema validation.")).toBeTruthy();
    expect(within(summary).queryByText("跳过测试")).toBeNull();
  });
});
