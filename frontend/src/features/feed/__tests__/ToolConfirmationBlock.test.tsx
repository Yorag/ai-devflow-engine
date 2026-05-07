import { QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/query-client";
import type { ToolConfirmationFeedEntry } from "../../../api/types";
import { ToolConfirmationBlock } from "../ToolConfirmationBlock";
import * as toolConfirmationActions from "../../tool-confirmations/tool-confirmation-actions";

vi.mock("../../tool-confirmations/tool-confirmation-actions", async () => {
  const actual = await vi.importActual<
    typeof import("../../tool-confirmations/tool-confirmation-actions")
  >("../../tool-confirmations/tool-confirmation-actions");
  return {
    ...actual,
    submitToolConfirmationDecision: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function buildEntry(
  overrides: Partial<ToolConfirmationFeedEntry> = {},
): ToolConfirmationFeedEntry {
  return {
    entry_id: "entry-tool-confirmation",
    run_id: "run-running",
    type: "tool_confirmation",
    occurred_at: "2026-05-01T09:20:00.000Z",
    stage_run_id: "stage-code-generation-running",
    tool_confirmation_id: "tool-confirmation-1",
    status: "pending",
    title: "Confirm bash tool action",
    tool_name: "bash",
    command_preview: "npm install",
    target_summary: "frontend/package-lock.json",
    risk_level: "high_risk",
    risk_categories: ["dependency_change", "network_download"],
    reason: "Installing dependencies changes lock files and downloads packages.",
    expected_side_effects: ["package-lock update"],
    allow_action: "allow:tool-confirmation-1",
    deny_action: "deny:tool-confirmation-1",
    is_actionable: true,
    requested_at: "2026-05-01T09:20:00.000Z",
    responded_at: null,
    decision: null,
    deny_followup_action: null,
    deny_followup_summary: null,
    disabled_reason: null,
    ...overrides,
  };
}

function renderBlock(
  entry: ToolConfirmationFeedEntry,
  options: {
    currentRunId?: string | null;
    sessionId?: string;
    projectId?: string;
    onOpenInspectorTarget?: () => void;
  } = {},
) {
  const queryClient = createQueryClient();
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ToolConfirmationBlock
          entry={entry}
          currentRunId={options.currentRunId ?? "run-running"}
          sessionId={options.sessionId ?? "session-running"}
          projectId={options.projectId ?? "project-default"}
          onOpenInspectorTarget={options.onOpenInspectorTarget}
        />
      </QueryClientProvider>,
    ),
  };
}

describe("ToolConfirmationBlock", () => {
  it("submits allow for the current active run and invalidates workspace queries", async () => {
    vi.mocked(
      toolConfirmationActions.submitToolConfirmationDecision,
    ).mockResolvedValue({
      tool_confirmation: buildEntry({
        status: "allowed",
        decision: "allowed",
        responded_at: "2026-05-01T09:21:00.000Z",
      }),
    });
    const { queryClient } = renderBlock(buildEntry());
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: "允许本次执行" }));

    await waitFor(() => {
      expect(
        toolConfirmationActions.submitToolConfirmationDecision,
      ).toHaveBeenCalledWith(
        expect.objectContaining({ tool_confirmation_id: "tool-confirmation-1" }),
        "allow",
        expect.anything(),
      );
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["sessions", "session-running", "workspace"],
        refetchType: "all",
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["projects", "project-default", "sessions"],
        refetchType: "all",
      });
    });
  });

  it("submits deny and renders denied follow-up summary from the projection contract", async () => {
    vi.mocked(
      toolConfirmationActions.submitToolConfirmationDecision,
    ).mockResolvedValue({
      tool_confirmation: buildEntry({
        status: "denied",
        decision: "denied",
        responded_at: "2026-05-01T09:21:00.000Z",
        deny_followup_action: "run_failed",
        deny_followup_summary:
          "The current run will fail because no low-risk alternative path exists.",
        is_actionable: false,
      }),
    });
    renderBlock(buildEntry());

    fireEvent.click(screen.getByRole("button", { name: "拒绝本次执行" }));

    expect(
      await screen.findByText(
        "The current run will fail because no low-risk alternative path exists.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("拒绝后当前运行将失败")).toBeTruthy();
    expect(screen.queryByText("批准")).toBeNull();
    expect(screen.queryByText("退回")).toBeNull();
  });

  it("renders read-only disabled states for paused, history, and terminal confirmations", () => {
    const { rerender } = renderBlock(
      buildEntry({
        is_actionable: false,
        disabled_reason:
          "Current run is paused; resume it to continue tool confirmation.",
      }),
    );

    expect(screen.getByRole("button", { name: "允许本次执行" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.getByRole("button", { name: "拒绝本次执行" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(
      screen.getByText(
        "Current run is paused; resume it to continue tool confirmation.",
      ),
    ).toBeTruthy();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        <ToolConfirmationBlock entry={buildEntry()} currentRunId="run-latest-other" />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: "允许本次执行" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(
      screen.getByText("该工具确认属于历史运行。"),
    ).toBeTruthy();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        <ToolConfirmationBlock
          entry={buildEntry({
            status: "denied",
            decision: "denied",
            is_actionable: false,
            disabled_reason: "This tool confirmation is read-only because the run has failed.",
          })}
          currentRunId="run-running"
        />
      </QueryClientProvider>,
    );
    expect(
      screen.getByText(
        "This tool confirmation is read-only because the run has failed.",
      ),
    ).toBeTruthy();
  });

  it("renders API error messages without clearing the current block state", async () => {
    vi.mocked(
      toolConfirmationActions.submitToolConfirmationDecision,
    ).mockRejectedValue(
      new Error("Current run is paused; resume it to continue tool confirmation."),
    );
    renderBlock(buildEntry());

    fireEvent.click(screen.getByRole("button", { name: "允许本次执行" }));

    expect(
      await screen.findByText(
        "Current run is paused; resume it to continue tool confirmation.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "允许本次执行" })).toBeTruthy();
  });

  it("drops temporary submitted state after parent props refresh with newer projection data", async () => {
    vi.mocked(
      toolConfirmationActions.submitToolConfirmationDecision,
    ).mockResolvedValue({
      tool_confirmation: buildEntry({
        status: "denied",
        decision: "denied",
        responded_at: "2026-05-01T09:21:00.000Z",
        deny_followup_action: "run_failed",
        deny_followup_summary: "Local mutation summary.",
        is_actionable: false,
      }),
    });
    const { rerender } = renderBlock(buildEntry());

    fireEvent.click(screen.getByRole("button", { name: "拒绝本次执行" }));

    expect(await screen.findByText("Local mutation summary.")).toBeTruthy();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        <ToolConfirmationBlock
          entry={buildEntry({
            status: "denied",
            decision: "denied",
            responded_at: "2026-05-01T09:21:02.000Z",
            deny_followup_action: "awaiting_run_control",
            deny_followup_summary: "Refetched projection summary.",
            is_actionable: false,
            disabled_reason:
              "Current run is waiting for explicit pause or terminate control.",
          })}
          currentRunId="run-running"
          sessionId="session-running"
          projectId="project-default"
        />
      </QueryClientProvider>,
    );

    expect(screen.queryByText("Local mutation summary.")).toBeNull();
    expect(screen.getByText("Refetched projection summary.")).toBeTruthy();
    expect(screen.getByText("拒绝后等待运行控制")).toBeTruthy();
  });

  it("keeps the Inspector trigger in the header instead of the primary action row", () => {
    const onOpenInspectorTarget = vi.fn();
    renderBlock(buildEntry(), { onOpenInspectorTarget });

    const actionRow = screen.getByLabelText("Tool confirmation actions");
    expect(
      within(actionRow).queryByRole("button", {
        name: "查看Confirm bash tool action详情",
      }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", {
        name: "查看Confirm bash tool action详情",
      }),
    );

    expect(onOpenInspectorTarget).toHaveBeenCalledTimes(1);
  });
});
