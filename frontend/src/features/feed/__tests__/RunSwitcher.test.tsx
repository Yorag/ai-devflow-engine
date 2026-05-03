import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  RunSummaryProjection,
  SessionWorkspaceProjection,
  TopLevelFeedEntry,
} from "../../../api/types";
import { renderWithAppProviders } from "../../../app/test-utils";
import { mockFeedEntriesByType, mockSessionWorkspaces } from "../../../mocks/fixtures";
import { ConsolePage } from "../../../pages/ConsolePage";
import { NarrativeFeed } from "../NarrativeFeed";
import { getRunBoundaryId, groupEntriesByRun } from "../RunBoundary";
import { RunSwitcher, scrollToRunBoundary } from "../RunSwitcher";

const originalRunningWorkspace = mockSessionWorkspaces["session-running"];

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  mockSessionWorkspaces["session-running"] = originalRunningWorkspace;
});

const runs: RunSummaryProjection[] = [
  {
    run_id: "run-first",
    attempt_index: 1,
    status: "failed",
    trigger_source: "initial_requirement",
    started_at: "2026-05-01T09:00:00.000Z",
    ended_at: "2026-05-01T09:15:00.000Z",
    current_stage_type: "test_generation_execution",
    is_active: false,
  },
  {
    run_id: "run-second",
    attempt_index: 2,
    status: "running",
    trigger_source: "retry",
    started_at: "2026-05-01T09:20:00.000Z",
    ended_at: null,
    current_stage_type: "solution_design",
    is_active: true,
  },
];

const firstRunMessage: TopLevelFeedEntry = {
  ...mockFeedEntriesByType.user_message,
  entry_id: "entry-first-message",
  run_id: "run-first",
  occurred_at: "2026-05-01T09:01:00.000Z",
  content: "Build the first attempt.",
};

const firstRunStatus: TopLevelFeedEntry = {
  ...mockFeedEntriesByType.system_status,
  entry_id: "entry-first-failed",
  run_id: "run-first",
  occurred_at: "2026-05-01T09:15:00.000Z",
  title: "First attempt failed",
};

const secondRunMessage: TopLevelFeedEntry = {
  ...mockFeedEntriesByType.user_message,
  entry_id: "entry-second-message",
  run_id: "run-second",
  occurred_at: "2026-05-01T09:21:00.000Z",
  content: "Retry with a smaller implementation.",
};

const secondRunStage: TopLevelFeedEntry = {
  ...mockFeedEntriesByType.stage_node,
  entry_id: "entry-second-stage",
  run_id: "run-second",
  occurred_at: "2026-05-01T09:22:00.000Z",
  summary: "Designing the smaller retry path.",
};

describe("RunBoundary grouping", () => {
  it("groups feed entries by run while preserving run order and entry order", () => {
    const groups = groupEntriesByRun(
      [firstRunMessage, firstRunStatus, secondRunMessage, secondRunStage],
      runs,
    );

    expect(groups.map((group) => group.runId)).toEqual(["run-first", "run-second"]);
    expect(groups[0].entries.map((entry) => entry.entry_id)).toEqual([
      "entry-first-message",
      "entry-first-failed",
    ]);
    expect(groups[1].entries.map((entry) => entry.entry_id)).toEqual([
      "entry-second-message",
      "entry-second-stage",
    ]);
  });

  it("keeps entries visible with a neutral boundary when run metadata is missing", () => {
    const orphanEntry: TopLevelFeedEntry = {
      ...mockFeedEntriesByType.control_item,
      entry_id: "entry-orphan",
      run_id: "run-orphan",
    };

    const groups = groupEntriesByRun([orphanEntry], []);

    expect(groups).toHaveLength(1);
    expect(groups[0].runId).toBe("run-orphan");
    expect(groups[0].run).toBeUndefined();
    expect(groups[0].entries).toEqual([orphanEntry]);

    render(<NarrativeFeed entries={[firstRunMessage, orphanEntry]} runs={[runs[0]]} />);

    expect(screen.queryByRole("navigation", { name: "Run Switcher" })).toBeNull();
    const fallbackBoundary = screen.getByRole("region", {
      name: "Run metadata unavailable boundary",
    });
    expect(within(fallbackBoundary).getByText("Run metadata unavailable")).toBeTruthy();
    expect(within(fallbackBoundary).getByText("run-orphan")).toBeTruthy();
    expect(within(fallbackBoundary).getByText("1 entry")).toBeTruthy();
    expect(within(fallbackBoundary).queryByText("Running")).toBeNull();
    expect(within(fallbackBoundary).queryByText("Initial Requirement")).toBeNull();
    expect(within(fallbackBoundary).queryByText("Historical run")).toBeNull();
    expect(within(fallbackBoundary).queryByText("Current run")).toBeNull();
  });

  it("renders switcher items only for backend-known runs", () => {
    const orphanEntry: TopLevelFeedEntry = {
      ...mockFeedEntriesByType.control_item,
      entry_id: "entry-orphan",
      run_id: "run-orphan-with-a-very-long-id-that-stays-out-of-switcher",
    };

    render(
      <NarrativeFeed
        entries={[firstRunMessage, secondRunMessage, orphanEntry]}
        runs={runs}
        currentRunId="run-second"
      />,
    );

    const switcher = screen.getByRole("navigation", { name: "Run Switcher" });
    expect(within(switcher).getByRole("button", { name: "Run 1 Failed" })).toBeTruthy();
    expect(
      within(switcher).getByRole("button", {
        name: "Run 2 Running Current run",
      }),
    ).toBeTruthy();
    expect(within(switcher).queryByText("Run metadata unavailable")).toBeNull();
    expect(within(switcher).queryByText(orphanEntry.run_id)).toBeNull();
    expect(
      screen.getByRole("region", { name: "Run metadata unavailable boundary" }),
    ).toBeTruthy();
  });
});

describe("RunSwitcher", () => {
  it("renders no switcher for a single run", () => {
    render(
      <RunSwitcher
        groups={groupEntriesByRun([firstRunMessage], [runs[0]])}
        currentRunId="run-first"
      />,
    );

    expect(screen.queryByRole("navigation", { name: "Run Switcher" })).toBeNull();
  });

  it("renders a low-weight navigation control and marks the active run", () => {
    render(
      <RunSwitcher
        groups={groupEntriesByRun([firstRunMessage, secondRunMessage], runs)}
        currentRunId="run-second"
      />,
    );

    const switcher = screen.getByRole("navigation", { name: "Run Switcher" });
    expect(within(switcher).getByRole("button", { name: "Run 1 Failed" })).toBeTruthy();
    const currentButton = within(switcher).getByRole("button", {
      name: "Run 2 Running Current run",
    });
    expect(currentButton.getAttribute("aria-current")).toBe("true");
    expect(within(switcher).queryByText(/new session/i)).toBeNull();
    expect(within(switcher).queryByText(/template/i)).toBeNull();
  });

  it("scrolls to the selected run boundary without replacing the feed", () => {
    const scrollIntoView = vi.fn();
    render(
      <NarrativeFeed
        entries={[firstRunMessage, firstRunStatus, secondRunMessage, secondRunStage]}
        runs={runs}
        currentRunId="run-second"
      />,
    );
    const target = document.getElementById(getRunBoundaryId("run-first"));
    Object.defineProperty(target, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    fireEvent.click(screen.getByRole("button", { name: "Run 1 Failed" }));

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
    expect(screen.getByText("Build the first attempt.")).toBeTruthy();
    expect(screen.getByText("Retry with a smaller implementation.")).toBeTruthy();
  });

  it("reports whether direct boundary scrolling found a target", () => {
    render(
      <div id={getRunBoundaryId("run-first")}>
        <span>Boundary target</span>
      </div>,
    );
    const target = document.getElementById(getRunBoundaryId("run-first"));
    const scrollIntoView = vi.fn();
    Object.defineProperty(target, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    expect(scrollToRunBoundary("run-first")).toBe(true);
    expect(scrollToRunBoundary("missing-run")).toBe(false);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
  });
});

describe("NarrativeFeed run boundaries", () => {
  it("renders strong run boundaries that correspond to switcher items", () => {
    render(
      <NarrativeFeed
        entries={[firstRunMessage, firstRunStatus, secondRunMessage, secondRunStage]}
        runs={runs}
        currentRunId="run-second"
      />,
    );

    const runSections = screen.getAllByRole("region", { name: /Run [12] boundary/ });
    expect(runSections).toHaveLength(2);
    expect(within(runSections[0]).getByRole("heading", { name: "Run 1" })).toBeTruthy();
    expect(within(runSections[0]).getByText("Historical run")).toBeTruthy();
    expect(within(runSections[0]).getByText("First attempt failed")).toBeTruthy();
    expect(within(runSections[1]).getByRole("heading", { name: "Run 2" })).toBeTruthy();
    expect(within(runSections[1]).getByText("Current run")).toBeTruthy();
    const runTwoSummary = within(runSections[1]).getByRole("group", {
      name: "Run 2 summary",
    });
    expect(within(runTwoSummary).getByText("Retry")).toBeTruthy();
    expect(within(runTwoSummary).getByText("2 entries")).toBeTruthy();
  });

  it("keeps the previous flat feed behavior when run summaries are not provided", () => {
    render(<NarrativeFeed entries={[firstRunMessage, secondRunMessage]} />);

    expect(screen.queryByRole("navigation", { name: "Run Switcher" })).toBeNull();
    expect(screen.queryByRole("region", { name: /Run 1 boundary/ })).toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("renders run boundaries for empty runs without showing the global empty state", () => {
    render(<NarrativeFeed entries={[]} runs={[runs[0]]} currentRunId="run-first" />);

    const runBoundary = screen.getByRole("region", { name: "Run 1 boundary" });
    expect(within(runBoundary).getByRole("heading", { name: "Run 1" })).toBeTruthy();
    expect(within(runBoundary).getByText("Historical run")).toBeTruthy();
    expect(within(runBoundary).getByText("Failed")).toBeTruthy();
    expect(within(runBoundary).getByText("Initial Requirement")).toBeTruthy();
    expect(within(runBoundary).getByText("0 entries")).toBeTruthy();
    expect(
      screen.queryByRole("region", { name: "Narrative Feed empty state" }),
    ).toBeNull();
  });

  it("mounts run boundaries from the selected workspace projection", async () => {
    const multiRunWorkspace: SessionWorkspaceProjection = {
      ...mockSessionWorkspaces["session-running"],
      runs,
      current_run_id: "run-second",
      narrative_feed: [firstRunMessage, firstRunStatus, secondRunMessage, secondRunStage],
    };
    mockSessionWorkspaces["session-running"] = multiRunWorkspace;

    renderWithAppProviders(<ConsolePage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );

    expect(await screen.findByRole("navigation", { name: "Run Switcher" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Run 1 boundary" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Run 2 boundary" })).toBeTruthy();
    expect(screen.getByText("Build the first attempt.")).toBeTruthy();
    expect(screen.getByText("Retry with a smaller implementation.")).toBeTruthy();
  });
});
