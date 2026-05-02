import { afterEach, describe, expect, it } from "vitest";

import { mockSessionWorkspaces } from "../../../mocks/fixtures";
import {
  initializeWorkspaceFromSnapshot,
  selectComposerState,
  selectCurrentRun,
  useWorkspaceStore,
  type WorkspaceInspectorTarget,
} from "../workspace-store";

afterEach(() => {
  useWorkspaceStore.getState().resetWorkspace();
});

describe("workspace-store snapshot initialization", () => {
  it("initializes workspace state from a SessionWorkspaceProjection snapshot", () => {
    const snapshot = mockSessionWorkspaces["session-running"];

    initializeWorkspaceFromSnapshot(snapshot);

    const state = useWorkspaceStore.getState();
    expect(state.snapshot).toBe(snapshot);
    expect(state.session?.session_id).toBe("session-running");
    expect(state.project?.project_id).toBe(snapshot.project.project_id);
    expect(state.deliveryChannel).toEqual(snapshot.delivery_channel);
    expect(state.currentRunId).toBe("run-running");
    expect(state.focusedRunId).toBe("run-running");
    expect(state.currentStageType).toBe("solution_design");
    expect(state.runs.map((run) => run.run_id)).toEqual(["run-running"]);
    expect(state.narrativeFeed.map((entry) => entry.entry_id)).toEqual(
      snapshot.narrative_feed.map((entry) => entry.entry_id),
    );
    expect(state.inspector).toEqual({ isOpen: false, target: null });
    expect(selectCurrentRun(state)?.run_id).toBe("run-running");
    expect(selectComposerState(state)).toEqual(snapshot.composer_state);
  });

  it("keeps draft sessions focused on no run while preserving composer state", () => {
    const snapshot = mockSessionWorkspaces["session-draft"];

    initializeWorkspaceFromSnapshot(snapshot);

    const state = useWorkspaceStore.getState();
    expect(state.currentRunId).toBeNull();
    expect(state.focusedRunId).toBeNull();
    expect(selectCurrentRun(state)).toBeNull();
    expect(selectComposerState(state)?.mode).toBe("draft");
    expect(selectComposerState(state)?.is_input_enabled).toBe(true);
    expect(state.narrativeFeed).toEqual([]);
  });

  it("stores Inspector open and close state without changing the snapshot", () => {
    const snapshot = mockSessionWorkspaces["session-running"];
    const target: WorkspaceInspectorTarget = {
      type: "stage",
      runId: "run-running",
      stageRunId: "stage-solution-design-running",
    };
    initializeWorkspaceFromSnapshot(snapshot);

    useWorkspaceStore.getState().openInspector(target);

    expect(useWorkspaceStore.getState().inspector).toEqual({
      isOpen: true,
      target,
    });
    expect(useWorkspaceStore.getState().snapshot).toBe(snapshot);

    useWorkspaceStore.getState().closeInspector();

    expect(useWorkspaceStore.getState().inspector).toEqual({
      isOpen: false,
      target: null,
    });
    expect(useWorkspaceStore.getState().snapshot).toBe(snapshot);
  });

  it("keeps current run focus inside the initialized snapshot run list", () => {
    const snapshot = mockSessionWorkspaces["session-running"];
    initializeWorkspaceFromSnapshot(snapshot);

    useWorkspaceStore.getState().focusRun("missing-run");

    expect(useWorkspaceStore.getState().focusedRunId).toBe("run-running");
    expect(selectCurrentRun(useWorkspaceStore.getState())?.run_id).toBe(
      "run-running",
    );
  });

  it("resets workspace state without leaving stale Inspector or Composer state", () => {
    const snapshot = mockSessionWorkspaces["session-running"];
    initializeWorkspaceFromSnapshot(snapshot);
    useWorkspaceStore.getState().openInspector({
      type: "stage",
      runId: "run-running",
      stageRunId: "stage-solution-design-running",
    });

    useWorkspaceStore.getState().resetWorkspace();

    const state = useWorkspaceStore.getState();
    expect(state.snapshot).toBeNull();
    expect(state.session).toBeNull();
    expect(state.focusedRunId).toBeNull();
    expect(state.composerState).toBeNull();
    expect(state.inspector).toEqual({ isOpen: false, target: null });
    expect(selectCurrentRun(state)).toBeNull();
    expect(selectComposerState(state)).toBeNull();
  });
});
