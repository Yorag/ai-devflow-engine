import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiRequestOptions } from "../../../api/client";
import type { SessionWorkspaceProjection, TopLevelFeedEntry } from "../../../api/types";
import { renderWithAppProviders } from "../../../app/test-utils";
import { mockFeedEntriesByType, mockSessionWorkspaces } from "../../../mocks/fixtures";
import { createMockApiFetcher, mockApiRequestOptions } from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { useWorkspaceStore } from "../workspace-store";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useWorkspaceStore.getState().resetWorkspace();
});

describe("Project session history regression", () => {
  it("keeps historical runs in the same session surface without making them current controls", async () => {
    const workspace = buildWorkspaceWithHistoricalRun();

    renderWithAppProviders(<ConsolePage request={requestWithWorkspace(workspace)} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );

    const historicalRun = await screen.findByRole("region", {
      name: "Run 1 boundary",
    });
    const currentRun = await screen.findByRole("region", {
      name: "Run 2 boundary",
    });

    expect(within(historicalRun).getByText("Historical run")).toBeTruthy();
    expect(within(currentRun).getByText("Current run")).toBeTruthy();
    expect(within(historicalRun).getByText("Review earlier solution")).toBeTruthy();
    expect(within(currentRun).getByText("Continue current implementation.")).toBeTruthy();

    expect(
      within(historicalRun).queryByRole("button", { name: "暂停当前运行" }),
    ).toBeNull();
    expect(within(historicalRun).queryByRole("button", { name: "暂停" })).toBeNull();
    expect(within(historicalRun).queryByRole("button", { name: "恢复" })).toBeNull();
    expect(
      within(historicalRun).queryByRole("button", { name: "终止当前运行" }),
    ).toBeNull();
    expect(within(historicalRun).queryByRole("button", { name: "Approve" })).toBeNull();
    expect(within(historicalRun).queryByRole("button", { name: "Reject" })).toBeNull();

    expect(
      within(historicalRun).getByRole("button", { name: "允许本次执行" }),
    ).toHaveProperty("disabled", true);
    expect(
      within(historicalRun).getByRole("button", { name: "拒绝本次执行" }),
    ).toHaveProperty("disabled", true);
    expect(
      within(historicalRun).getByText(
        "This tool confirmation belongs to a historical run.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "终止当前运行" })).toBeTruthy();
  });

  it("does not present historical sessions as automatic memory for new sessions", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    await screen.findByRole("region", {
      name: "Template empty state",
    });
    const draftCopy = document.body.textContent ?? "";
    const memoryVerbs = "(?:automatic|auto|inherit|inherits|inherited|reuse|reuses|reused|carry|carries|carried|remember|remembers|remembered|load|loads|loaded)";
    const historyQualifiers = "(?:historical|previous|prior|past|old)";
    const historyObjects = [
      "sessions?",
      "runs?",
      "artifacts?",
      "approvals?",
      "tool confirmations?",
      "provider process records?",
      "provider processes?",
      "process records?",
    ];

    expect(draftCopy).not.toMatch(/automatic memory/i);
    expect(draftCopy).not.toMatch(/long[- ]term memory/i);
    for (const object of historyObjects) {
      expect(draftCopy).not.toMatch(
        new RegExp(`${memoryVerbs}[^.\\n]{0,80}${historyQualifiers}\\s+${object}`, "i"),
      );
      expect(draftCopy).not.toMatch(
        new RegExp(`${historyQualifiers}\\s+${object}[^.\\n]{0,80}${memoryVerbs}`, "i"),
      );
    }
  });

  it("keeps session and project destructive actions blocked for active or default boundaries", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("button", {
        name: "Delete Add workspace shell blocked by active run",
      }),
    ).toHaveProperty("disabled", true);
    expect(
      screen.getByRole("button", { name: "Default project cannot be removed" }),
    ).toHaveProperty("disabled", true);

    fireEvent.change(await screen.findByLabelText("Switch project"), {
      target: { value: "project-loaded" },
    });

    expect(
      await screen.findByRole("button", {
        name: "Remove Checkout Service unavailable",
      }),
    ).toHaveProperty("disabled", true);
  });
});

function requestWithWorkspace(workspace: SessionWorkspaceProjection): ApiRequestOptions {
  const baseFetcher = createMockApiFetcher();

  return {
    fetcher: async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/sessions/session-running/workspace")) {
        return new Response(JSON.stringify(workspace), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }

      return baseFetcher(input, init);
    },
  };
}

function buildWorkspaceWithHistoricalRun(): SessionWorkspaceProjection {
  const baseWorkspace = mockSessionWorkspaces["session-running"];
  const historicalRunId = "run-history";
  const currentRunId = "run-current";

  const historicalApproval: TopLevelFeedEntry = {
    ...mockFeedEntriesByType.approval_request,
    entry_id: "entry-history-approval",
    run_id: historicalRunId,
    approval_id: "approval-history",
    requested_at: "2026-05-01T09:03:00.000Z",
    occurred_at: "2026-05-01T09:03:00.000Z",
    title: "Review earlier solution",
  };
  const historicalToolConfirmation: TopLevelFeedEntry = {
    ...mockFeedEntriesByType.tool_confirmation,
    entry_id: "entry-history-tool-confirmation",
    run_id: historicalRunId,
    tool_confirmation_id: "tool-confirmation-history",
    requested_at: "2026-05-01T09:04:00.000Z",
    occurred_at: "2026-05-01T09:04:00.000Z",
  };
  const currentMessage: TopLevelFeedEntry = {
    ...mockFeedEntriesByType.user_message,
    entry_id: "entry-current-message",
    run_id: currentRunId,
    message_id: "message-current",
    occurred_at: "2026-05-01T09:21:00.000Z",
    content: "Continue current implementation.",
  };

  return {
    ...baseWorkspace,
    session: {
      ...baseWorkspace.session,
      current_run_id: currentRunId,
      latest_stage_type: "solution_design",
      status: "running",
    },
    runs: [
      {
        run_id: historicalRunId,
        attempt_index: 1,
        status: "failed",
        trigger_source: "initial_requirement",
        started_at: "2026-05-01T09:00:00.000Z",
        ended_at: "2026-05-01T09:10:00.000Z",
        current_stage_type: "solution_design",
        is_active: false,
      },
      {
        run_id: currentRunId,
        attempt_index: 2,
        status: "running",
        trigger_source: "retry",
        started_at: "2026-05-01T09:20:00.000Z",
        ended_at: null,
        current_stage_type: "solution_design",
        is_active: true,
      },
    ],
    narrative_feed: [historicalApproval, historicalToolConfirmation, currentMessage],
    current_run_id: currentRunId,
    current_stage_type: "solution_design",
    composer_state: {
      mode: "running",
      is_input_enabled: false,
      primary_action: "pause",
      secondary_actions: ["terminate"],
      bound_run_id: currentRunId,
    },
  };
}
