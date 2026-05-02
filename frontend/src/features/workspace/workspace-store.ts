import { create } from "zustand";

import type {
  ComposerStateProjection,
  ProjectDeliveryChannelDetailProjection,
  ProjectRead,
  RunSummaryProjection,
  SessionRead,
  SessionWorkspaceProjection,
  StageType,
  TopLevelFeedEntry,
} from "../../api/types";

export type WorkspaceInspectorTarget =
  | {
      type: "stage";
      runId: string;
      stageRunId: string;
    }
  | {
      type: "control_item";
      runId: string;
      controlRecordId: string;
    }
  | {
      type: "tool_confirmation";
      runId: string;
      toolConfirmationId: string;
    }
  | {
      type: "delivery_result";
      runId: string;
      deliveryRecordId: string;
    };

export type WorkspaceInspectorState = {
  isOpen: boolean;
  target: WorkspaceInspectorTarget | null;
};

type WorkspaceStoreData = {
  snapshot: SessionWorkspaceProjection | null;
  session: SessionRead | null;
  project: ProjectRead | null;
  deliveryChannel: ProjectDeliveryChannelDetailProjection | null;
  runs: RunSummaryProjection[];
  narrativeFeed: TopLevelFeedEntry[];
  currentRunId: string | null;
  focusedRunId: string | null;
  currentStageType: StageType | null;
  composerState: ComposerStateProjection | null;
  inspector: WorkspaceInspectorState;
};

type WorkspaceStoreActions = {
  initializeFromSnapshot: (snapshot: SessionWorkspaceProjection) => void;
  focusRun: (runId: string) => void;
  openInspector: (target: WorkspaceInspectorTarget) => void;
  closeInspector: () => void;
  resetWorkspace: () => void;
};

export type WorkspaceStoreState = WorkspaceStoreData & WorkspaceStoreActions;

export const useWorkspaceStore = create<WorkspaceStoreState>()((set, get) => ({
  ...createEmptyWorkspaceData(),
  initializeFromSnapshot: (snapshot) => {
    set(createWorkspaceDataFromSnapshot(snapshot));
  },
  focusRun: (runId) => {
    if (get().runs.some((run) => run.run_id === runId)) {
      set({ focusedRunId: runId });
    }
  },
  openInspector: (target) => {
    set({ inspector: { isOpen: true, target } });
  },
  closeInspector: () => {
    set({ inspector: createClosedInspectorState() });
  },
  resetWorkspace: () => {
    set(createEmptyWorkspaceData());
  },
}));

export function initializeWorkspaceFromSnapshot(
  snapshot: SessionWorkspaceProjection,
): void {
  useWorkspaceStore.getState().initializeFromSnapshot(snapshot);
}

export function selectCurrentRun(
  state: WorkspaceStoreState,
): RunSummaryProjection | null {
  return (
    state.runs.find((run) => run.run_id === state.focusedRunId) ??
    state.runs.find((run) => run.run_id === state.currentRunId) ??
    null
  );
}

export function selectComposerState(
  state: WorkspaceStoreState,
): ComposerStateProjection | null {
  return state.composerState;
}

function createWorkspaceDataFromSnapshot(
  snapshot: SessionWorkspaceProjection,
): WorkspaceStoreData {
  const runs = [...snapshot.runs];

  return {
    snapshot,
    session: snapshot.session,
    project: snapshot.project,
    deliveryChannel: snapshot.delivery_channel,
    runs,
    narrativeFeed: [...snapshot.narrative_feed],
    currentRunId: snapshot.current_run_id,
    focusedRunId: resolveInitialFocusedRunId(snapshot, runs),
    currentStageType: snapshot.current_stage_type,
    composerState: snapshot.composer_state,
    inspector: createClosedInspectorState(),
  };
}

function createEmptyWorkspaceData(): WorkspaceStoreData {
  return {
    snapshot: null,
    session: null,
    project: null,
    deliveryChannel: null,
    runs: [],
    narrativeFeed: [],
    currentRunId: null,
    focusedRunId: null,
    currentStageType: null,
    composerState: null,
    inspector: createClosedInspectorState(),
  };
}

function createClosedInspectorState(): WorkspaceInspectorState {
  return { isOpen: false, target: null };
}

function resolveInitialFocusedRunId(
  snapshot: SessionWorkspaceProjection,
  runs: RunSummaryProjection[],
): string | null {
  const currentRun = runs.find((run) => run.run_id === snapshot.current_run_id);
  if (currentRun) {
    return currentRun.run_id;
  }

  return runs.find((run) => run.is_active)?.run_id ?? runs[0]?.run_id ?? null;
}
