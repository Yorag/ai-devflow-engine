import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createRerun } from "../../../api/runs";
import type { SystemStatusFeedEntry } from "../../../api/types";
import { createQueryClient } from "../../../app/query-client";
import { getRunBoundaryId } from "../../feed/RunBoundary";
import { RerunAction } from "../RerunAction";

vi.mock("../../../api/runs", async () => {
  const actual = await vi.importActual<typeof import("../../../api/runs")>(
    "../../../api/runs",
  );
  return {
    ...actual,
    createRerun: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

function buildSystemStatusEntry(
  overrides: Partial<SystemStatusFeedEntry> = {},
): SystemStatusFeedEntry {
  return {
    entry_id: "entry-system-status-failed",
    run_id: "run-failed",
    type: "system_status",
    occurred_at: "2026-05-01T10:15:00.000Z",
    status: "failed",
    title: "Run failed",
    reason: "Tests failed after retry limit.",
    retry_action: "retry:run-failed",
    ...overrides,
  };
}

function renderRerunAction(
  entry: SystemStatusFeedEntry,
  options: {
    currentRunId?: string | null;
    sessionId?: string;
    projectId?: string;
  } = {},
) {
  const queryClient = createQueryClient();

  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <RerunAction
          entry={entry}
          currentRunId={options.currentRunId ?? "run-failed"}
          sessionId={options.sessionId ?? "session-failed"}
          projectId={options.projectId ?? "project-default"}
        />
      </QueryClientProvider>,
    ),
  };
}

describe("RerunAction", () => {
  it("submits rerun for the current terminal run, invalidates workspace queries, and focuses the new run boundary", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(createRerun).mockResolvedValue({
      run_id: "run-failed-retry-2",
      attempt_index: 2,
      status: "running",
      trigger_source: "retry",
      started_at: "2026-05-01T10:16:00.000Z",
      ended_at: null,
      current_stage_type: "requirement_analysis",
      is_active: true,
    });

    const target = document.createElement("section");
    target.id = getRunBoundaryId("run-failed-retry-2");
    target.tabIndex = -1;
    const focusSpy = vi.fn();
    const scrollSpy = vi.fn();
    Object.defineProperty(target, "focus", { configurable: true, value: focusSpy });
    Object.defineProperty(target, "scrollIntoView", {
      configurable: true,
      value: scrollSpy,
    });
    document.body.appendChild(target);

    const { queryClient } = renderRerunAction(buildSystemStatusEntry());
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: "Retry run" }));

    await waitFor(() => {
      expect(createRerun).toHaveBeenCalledWith("session-failed", expect.anything());
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["sessions", "session-failed", "workspace"],
        refetchType: "all",
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["projects", "project-default", "sessions"],
        refetchType: "all",
      });
      expect(focusSpy).toHaveBeenCalled();
      expect(scrollSpy).toHaveBeenCalledWith({
        behavior: "smooth",
        block: "start",
      });
    });
  });

  it("does not render rerun for a historical terminal run", () => {
    renderRerunAction(buildSystemStatusEntry(), {
      currentRunId: "run-current-other",
    });

    expect(screen.queryByRole("button", { name: "Retry run" })).toBeNull();
  });

  it.each([
    ["missing retry action", { retry_action: null }],
    ["legacy mock-only marker", { retry_action: ["create", "rerun"].join("_") }],
    ["unknown action", { retry_action: "resume:run-failed" }],
    ["malformed retry action", { retry_action: "retry" }],
    ["mismatched target run", { retry_action: "retry:run-other" }],
  ] satisfies Array<[string, Partial<SystemStatusFeedEntry>]>)(
    "does not render rerun for %s",
    (_label, overrides) => {
      renderRerunAction(buildSystemStatusEntry(overrides));

      expect(screen.queryByRole("button", { name: "Retry run" })).toBeNull();
    },
  );

  it("renders rerun for a terminated current run with a matching retry action", () => {
    renderRerunAction(
      buildSystemStatusEntry({
        status: "terminated",
        title: "Run terminated",
        reason: "The run was terminated by the user.",
        retry_action: "retry:run-failed",
      }),
    );

    expect(screen.getByRole("button", { name: "Retry run" })).toBeTruthy();
  });

  it("shows the rerun warning copy and surfaces API errors inline", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(createRerun).mockRejectedValue(
      new Error("Rerun is not available for completed sessions."),
    );

    renderRerunAction(buildSystemStatusEntry());

    expect(
      screen.getByText(
        "Retry starts a new run from Requirement Analysis. It will not inherit undelivered workspace changes from the previous run.",
      ),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retry run" }));

    expect(
      await screen.findByText("Rerun is not available for completed sessions."),
    ).toBeTruthy();
  });
});
