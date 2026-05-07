import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithAppProviders } from "../../../app/test-utils";
import { createQueryClient } from "../../../app/query-client";
import type { TopLevelFeedEntry } from "../../../api/types";
import {
  mockFeedEntriesByType,
  mockGitDeliveryResultFeedEntry,
  mockSessionWorkspaces,
} from "../../../mocks/fixtures";
import { mockApiRequestOptions } from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { FeedEntryRenderer, renderFeedEntryByType } from "../FeedEntryRenderer";
import { NarrativeFeed } from "../NarrativeFeed";

afterEach(() => {
  cleanup();
});

describe("FeedEntryRenderer", () => {
  it("renders each supported top-level entry with distinct semantics", () => {
    renderWithAppProviders(
      <NarrativeFeed entries={Object.values(mockFeedEntriesByType)} />,
    );

    expect(
      screen.getByRole("article", { name: "User message feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("Add a workspace shell.")).toBeTruthy();

    const stageEntry = screen.getByRole("article", {
      name: "阶段节点",
    });
    expect(within(stageEntry).getByText("方案设计")).toBeTruthy();
    expect(within(stageEntry).getByText("运行中")).toBeTruthy();
    expect(within(stageEntry).getByText("2 项")).toBeTruthy();

    const approvalEntry = screen.getByRole("article", {
      name: "Approval request feed entry",
    });
    expect(within(approvalEntry).getByText("Review solution design")).toBeTruthy();
    expect(within(approvalEntry).getByRole("button", { name: "批准" })).toBeTruthy();
    expect(within(approvalEntry).getByRole("button", { name: "退回" })).toBeTruthy();

    const toolEntry = screen.getByRole("article", {
      name: "Tool confirmation feed entry",
    });
    expect(within(toolEntry).getByText("Allow dependency install")).toBeTruthy();
    expect(within(toolEntry).getByText("bash")).toBeTruthy();
    expect(
      within(toolEntry).getByRole("button", { name: "允许本次执行" }),
    ).toBeTruthy();
    expect(
      within(toolEntry).getByRole("button", { name: "拒绝本次执行" }),
    ).toBeTruthy();
    expect(within(toolEntry).queryByText("批准")).toBeNull();
    expect(within(toolEntry).queryByText("退回")).toBeNull();

    expect(
      screen.getByRole("article", { name: "Control item feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("Clarification needed")).toBeTruthy();

    expect(
      screen.getByRole("article", { name: "Approval result feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("已批准")).toBeTruthy();

    const deliveryEntry = screen.getByRole("article", {
      name: "Delivery result feed entry",
    });
    expect(within(deliveryEntry).getByText("Demo delivery")).toBeTruthy();
    expect(
      within(deliveryEntry).getByText("Demo delivery completed without Git writes."),
    ).toBeTruthy();
    expect(within(deliveryEntry).getByText("展示分支")).toBeTruthy();
    expect(within(deliveryEntry).getByText("demo/run-completed")).toBeTruthy();
    expect(within(deliveryEntry).getByText("引用")).toBeTruthy();
    expect(
      within(deliveryEntry).getByText("demo-delivery-result:run-completed"),
    ).toBeTruthy();
    expect(deliveryEntry.textContent).not.toMatch(/提交/);
    expect(deliveryEntry.textContent).not.toMatch(/\bCode review\b/i);

    const systemEntry = screen.getByRole("article", {
      name: "System status feed entry",
    });
    expect(within(systemEntry).getByText("Run failed")).toBeTruthy();
  });

  it("preserves the provided top-level feed order", () => {
    const entries: TopLevelFeedEntry[] = [
      mockFeedEntriesByType.user_message,
      mockFeedEntriesByType.approval_request,
      mockFeedEntriesByType.tool_confirmation,
      mockFeedEntriesByType.delivery_result,
    ];

    renderWithAppProviders(<NarrativeFeed entries={entries} />);

    const labels = screen
      .getAllByRole("listitem")
      .map((item) => within(item).getByRole("article").getAttribute("aria-label"));

    expect(labels).toEqual([
      "User message feed entry",
      "Approval request feed entry",
      "Tool confirmation feed entry",
      "Delivery result feed entry",
    ]);
  });

  it("does not fabricate a completed-run system status entry", () => {
    render(
      <NarrativeFeed
        entries={mockSessionWorkspaces["session-completed"].narrative_feed}
      />,
    );

    expect(
      screen.getByRole("article", { name: "Delivery result feed entry" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("article", { name: "System status feed entry" }),
    ).toBeNull();
  });

  it("exposes the direct render helper for focused top-level entry dispatch", () => {
    render(renderFeedEntryByType(mockFeedEntriesByType.control_item));

    expect(
      screen.getByRole("article", { name: "Control item feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("需求分析")).toBeTruthy();
  });

  it("renders the selected non-draft workspace feed instead of placeholder copy", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );

    expect(
      await screen.findByRole("article", { name: "User message feed entry" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("article", { name: "阶段节点" }),
    ).toBeTruthy();
    expect(
      screen.getByText("Designing the workspace shell boundaries."),
    ).toBeTruthy();
    expect(
      screen.queryByText("Run history and execution feed will appear here."),
    ).toBeNull();
  });

  it("renders an empty feed state for non-draft sessions without feed entries", () => {
    render(<NarrativeFeed entries={[]} />);

    expect(
      screen.getByRole("region", { name: "Narrative Feed empty state" }),
    ).toBeTruthy();
    expect(screen.getByText("No run entries yet")).toBeTruthy();
  });

  it("renders approval actions for the current run but not for a historical run", () => {
    const currentApproval = {
      ...mockFeedEntriesByType.approval_request,
      run_id: "run-waiting-approval",
    };

    const { rerender } = renderWithAppProviders(
      renderFeedEntryByType(currentApproval, {
        currentRunId: "run-waiting-approval",
        sessionId: "session-waiting-approval",
        projectId: "project-default",
      }),
    );

    expect(screen.getByRole("button", { name: "批准" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "退回" })).toBeTruthy();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        {renderFeedEntryByType(currentApproval, {
          currentRunId: "run-latest-other",
          sessionId: "session-waiting-approval",
          projectId: "project-default",
        })}
      </QueryClientProvider>,
    );

    expect(screen.queryByRole("button", { name: "批准" })).toBeNull();
    expect(screen.queryByRole("button", { name: "退回" })).toBeNull();
  });

  it("renders denied follow-up semantics on top-level tool confirmation entries", () => {
    const deniedToolConfirmation = {
      ...mockFeedEntriesByType.tool_confirmation,
      status: "denied",
      decision: "denied",
      is_actionable: false,
      responded_at: "2026-05-01T09:21:00.000Z",
      deny_followup_action: "run_failed",
      deny_followup_summary:
        "The current run will fail because no low-risk alternative path exists.",
    } satisfies TopLevelFeedEntry;

    renderWithAppProviders(renderFeedEntryByType(deniedToolConfirmation));

    expect(
      screen.getByText(
        "The current run will fail because no low-risk alternative path exists.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("拒绝后当前运行将失败")).toBeTruthy();
    expect(screen.queryByText("approval rollback")).toBeNull();
  });

  it("keeps the system status fixture aligned to the backend retry contract", () => {
    expect(mockFeedEntriesByType.system_status.retry_action).toBe("retry:run-failed");
  });

  it("renders rerun only for the current terminal run with a matching retry action", () => {
    const currentStatus = {
      ...mockFeedEntriesByType.system_status,
      run_id: "run-failed",
      retry_action: "retry:run-failed",
    };

    const { rerender } = renderWithAppProviders(
      renderFeedEntryByType(currentStatus, {
        currentRunId: "run-failed",
        sessionId: "session-failed",
        projectId: "project-default",
      }),
    );

    expect(screen.getByRole("button", { name: "Retry run" })).toBeTruthy();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        {renderFeedEntryByType(
          { ...currentStatus, retry_action: "retry:run-previous" },
          {
            currentRunId: "run-failed",
            sessionId: "session-failed",
            projectId: "project-default",
          },
        )}
      </QueryClientProvider>,
    );

    expect(screen.queryByRole("button", { name: "Retry run" })).toBeNull();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        {renderFeedEntryByType(currentStatus, {
          currentRunId: "run-retry",
          sessionId: "session-failed",
          projectId: "project-default",
        })}
      </QueryClientProvider>,
    );

    expect(screen.queryByRole("button", { name: "Retry run" })).toBeNull();
  });
});

describe("FeedEntryRenderer guards", () => {
  it("renders single entries without requiring the list wrapper", () => {
    render(<FeedEntryRenderer entry={mockFeedEntriesByType.delivery_result} />);

    expect(
      screen.getByRole("article", { name: "Delivery result feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("Demo delivery")).toBeTruthy();
    expect(screen.getByText("demo/run-completed")).toBeTruthy();
    expect(screen.getByText("demo-delivery-result:run-completed")).toBeTruthy();
  });

  it("renders real backend-shaped git delivery_result payloads", () => {
    renderWithAppProviders(renderFeedEntryByType(mockGitDeliveryResultFeedEntry));

    const deliveryEntry = screen.getByRole("article", {
      name: "Delivery result feed entry",
    });
    expect(within(deliveryEntry).getByText("Git auto delivery")).toBeTruthy();
    expect(within(deliveryEntry).getByText("Delivery completed.")).toBeTruthy();
    expect(within(deliveryEntry).getByText("feature/run-delivery")).toBeTruthy();
    expect(within(deliveryEntry).getByText("abc123def456")).toBeTruthy();
    expect(
      within(deliveryEntry).getByRole("link", {
        name: "代码评审 github.example/pulls/1",
      }),
    ).toBeTruthy();
    expect(
      within(deliveryEntry).getByText("Resolved upstream test summary."),
    ).toBeTruthy();
    expect(
      within(deliveryEntry).getByText("git-delivery-result:run-delivery"),
    ).toBeTruthy();
  });
});
