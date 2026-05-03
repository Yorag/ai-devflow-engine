import type {
  ApprovalRequestFeedEntry,
  ApprovalResultFeedEntry,
  ComposerStateProjection,
  ControlItemFeedEntry,
  DeliveryResultFeedEntry,
  ExecutionNodeProjection,
  MessageFeedEntry,
  RunStatus,
  RunSummaryProjection,
  SessionEvent,
  SessionRead,
  SessionStatus,
  StageType,
  SystemStatusFeedEntry,
  ToolConfirmationFeedEntry,
  TopLevelFeedEntry,
} from "../../api/types";
import type { WorkspaceStoreState } from "./workspace-store";

type FeedIdentity = string;

export function applySessionEvent(
  state: WorkspaceStoreState,
  event: SessionEvent,
): WorkspaceStoreState {
  switch (event.event_type) {
    case "session_created": {
      const session = readPayload<SessionRead>(event, "session");
      if (!session) {
        return state;
      }

      return refreshSnapshot({
        ...state,
        session,
        currentRunId: session.current_run_id,
        currentStageType: session.latest_stage_type,
        composerState: updateComposerStateFromSessionStatus(
          session.status,
          session.current_run_id,
        ),
      });
    }

    case "session_message_appended":
    case "clarification_answered": {
      const message = readPayload<MessageFeedEntry>(event, "message_item");
      return message ? updateFeed(state, message) : state;
    }

    case "pipeline_run_created": {
      const run = readPayload<RunSummaryProjection>(event, "run");
      if (!run) {
        return state;
      }

      const runs = upsertRun(state.runs, run);
      const currentRunId = run.is_active
        ? run.run_id
        : state.currentRunId;
      const currentStageType = run.is_active
        ? run.current_stage_type
        : state.currentStageType;
      const session =
        run.is_active && state.session
          ? {
              ...state.session,
              status: run.status,
              current_run_id: run.run_id,
              latest_stage_type: run.current_stage_type,
              updated_at: event.occurred_at,
            }
          : state.session;
      const composerState = run.is_active
        ? updateComposerStateFromSessionStatus(run.status, run.run_id)
        : state.composerState;
      return refreshSnapshot({
        ...state,
        session,
        runs,
        currentRunId,
        currentStageType,
        composerState,
        focusedRunId: resolveFocusedRunId(runs, currentRunId, state.focusedRunId),
      });
    }

    case "stage_started":
    case "stage_updated": {
      const stageNode = readPayload<ExecutionNodeProjection>(
        event,
        "stage_node",
      );
      if (!stageNode) {
        return state;
      }

      return refreshSnapshot({
        ...state,
        narrativeFeed: mergeStageNodeUpdate(state.narrativeFeed, stageNode),
      });
    }

    case "clarification_requested":
    case "control_item_created": {
      const controlItem = readPayload<ControlItemFeedEntry>(
        event,
        "control_item",
      );
      return controlItem ? updateFeed(state, controlItem) : state;
    }

    case "approval_requested": {
      const approvalRequest = readPayload<ApprovalRequestFeedEntry>(
        event,
        "approval_request",
      );
      return approvalRequest ? updateFeed(state, approvalRequest) : state;
    }

    case "approval_result": {
      const approvalResult = readPayload<ApprovalResultFeedEntry>(
        event,
        "approval_result",
      );
      if (!approvalResult) {
        return state;
      }

      const narrativeFeed = upsertFeedEntry(
        updateApprovalRequestFromResult(state.narrativeFeed, approvalResult),
        approvalResult,
      );
      return refreshSnapshot({ ...state, narrativeFeed });
    }

    case "tool_confirmation_requested":
    case "tool_confirmation_result": {
      const toolConfirmation = readPayload<ToolConfirmationFeedEntry>(
        event,
        "tool_confirmation",
      );
      return toolConfirmation ? updateFeed(state, toolConfirmation) : state;
    }

    case "delivery_result": {
      const deliveryResult = readPayload<DeliveryResultFeedEntry>(
        event,
        "delivery_result",
      );
      return deliveryResult ? updateFeed(state, deliveryResult) : state;
    }

    case "system_status": {
      const systemStatus = readPayload<SystemStatusFeedEntry>(
        event,
        "system_status",
      );
      if (!systemStatus) {
        return state;
      }

      return applyTerminalSystemStatus(updateFeed(state, systemStatus), systemStatus);
    }

    case "session_status_changed":
      return applySessionStatusChanged(state, event);

    default:
      return state;
  }
}

export function mergeStageNodeUpdate(
  entries: TopLevelFeedEntry[],
  stageNode: ExecutionNodeProjection,
): TopLevelFeedEntry[] {
  return upsertFeedEntry(entries, stageNode);
}

export function updateComposerStateFromSessionStatus(
  status: SessionStatus,
  currentRunId: string | null,
): ComposerStateProjection {
  const terminal = isTerminalSessionStatus(status);
  const secondaryActions: ComposerStateProjection["secondary_actions"] =
    status === "draft" || terminal
      ? []
      : status === "waiting_clarification"
        ? ["pause", "terminate"]
        : ["terminate"];

  return {
    mode: terminal ? "readonly" : status,
    is_input_enabled: status === "draft" || status === "waiting_clarification",
    primary_action:
      status === "draft" || status === "waiting_clarification"
        ? "send"
        : status === "paused"
          ? "resume"
          : terminal
            ? "disabled"
            : "pause",
    secondary_actions: secondaryActions,
    bound_run_id: currentRunId,
  };
}

function applyTerminalSystemStatus(
  state: WorkspaceStoreState,
  systemStatus: SystemStatusFeedEntry,
): WorkspaceStoreState {
  const runs = updateCurrentRunFromSessionStatus(
    state.runs,
    systemStatus.status,
    systemStatus.run_id,
    state.currentStageType,
    systemStatus.occurred_at,
  );
  const session =
    state.session?.current_run_id === systemStatus.run_id
      ? {
          ...state.session,
          status: systemStatus.status,
          updated_at: systemStatus.occurred_at,
        }
      : state.session;

  return refreshSnapshot({
    ...state,
    session,
    runs,
    composerState:
      state.session?.current_run_id === systemStatus.run_id
        ? updateComposerStateFromSessionStatus(
            systemStatus.status,
            systemStatus.run_id,
          )
        : state.composerState,
  });
}

function applySessionStatusChanged(
  state: WorkspaceStoreState,
  event: SessionEvent,
): WorkspaceStoreState {
  const payload = readSessionStatusChangedPayload(event);
  if (!payload) {
    return state;
  }

  const session = state.session
    ? {
        ...state.session,
        status: payload.status,
        current_run_id: payload.current_run_id,
        latest_stage_type: payload.current_stage_type,
        updated_at: event.occurred_at,
      }
    : state.session;
  const runs = updateCurrentRunFromSessionStatus(
    state.runs,
    payload.status,
    payload.current_run_id,
    payload.current_stage_type,
    event.occurred_at,
  );

  return refreshSnapshot({
    ...state,
    session,
    runs,
    currentRunId: payload.current_run_id,
    currentStageType: payload.current_stage_type,
    focusedRunId: resolveFocusedRunId(
      runs,
      payload.current_run_id,
      state.focusedRunId,
    ),
    composerState: updateComposerStateFromSessionStatus(
      payload.status,
      payload.current_run_id,
    ),
  });
}

function updateFeed(
  state: WorkspaceStoreState,
  entry: TopLevelFeedEntry,
): WorkspaceStoreState {
  return refreshSnapshot({
    ...state,
    narrativeFeed: upsertFeedEntry(state.narrativeFeed, entry),
  });
}

function upsertFeedEntry(
  entries: TopLevelFeedEntry[],
  incoming: TopLevelFeedEntry,
): TopLevelFeedEntry[] {
  const incomingIdentity = getFeedIdentity(incoming);
  const index = entries.findIndex(
    (entry) => getFeedIdentity(entry) === incomingIdentity,
  );

  if (index === -1) {
    return [...entries, incoming];
  }

  return entries.map((entry, entryIndex) =>
    entryIndex === index ? incoming : entry,
  );
}

function updateApprovalRequestFromResult(
  entries: TopLevelFeedEntry[],
  approvalResult: ApprovalResultFeedEntry,
): TopLevelFeedEntry[] {
  return entries.map((entry) => {
    if (
      entry.type !== "approval_request" ||
      entry.approval_id !== approvalResult.approval_id
    ) {
      return entry;
    }

    return {
      ...entry,
      status: approvalResult.decision,
      is_actionable: false,
    };
  });
}

function upsertRun(
  runs: RunSummaryProjection[],
  incoming: RunSummaryProjection,
): RunSummaryProjection[] {
  const index = runs.findIndex((run) => run.run_id === incoming.run_id);
  if (index === -1) {
    return [...runs, incoming];
  }

  return runs.map((run, runIndex) => (runIndex === index ? incoming : run));
}

function updateCurrentRunFromSessionStatus(
  runs: RunSummaryProjection[],
  status: SessionStatus,
  currentRunId: string | null,
  currentStageType: StageType | null,
  occurredAt: string,
): RunSummaryProjection[] {
  if (!currentRunId || !isRunStatus(status)) {
    return runs;
  }

  const terminal = isTerminalSessionStatus(status);
  return runs.map((run) =>
    run.run_id === currentRunId
      ? {
          ...run,
          status,
          current_stage_type: currentStageType,
          is_active: !terminal,
          ended_at: terminal ? (run.ended_at ?? occurredAt) : null,
        }
      : run,
  );
}

function resolveFocusedRunId(
  runs: RunSummaryProjection[],
  currentRunId: string | null,
  previousFocusedRunId: string | null,
): string | null {
  if (currentRunId && runs.some((run) => run.run_id === currentRunId)) {
    return currentRunId;
  }
  if (
    previousFocusedRunId &&
    runs.some((run) => run.run_id === previousFocusedRunId)
  ) {
    return previousFocusedRunId;
  }

  return runs.find((run) => run.is_active)?.run_id ?? runs[0]?.run_id ?? null;
}

function refreshSnapshot(state: WorkspaceStoreState): WorkspaceStoreState {
  if (!state.snapshot || !state.session || !state.project || !state.composerState) {
    return state;
  }

  return {
    ...state,
    snapshot: {
      ...state.snapshot,
      session: state.session,
      project: state.project,
      delivery_channel: state.deliveryChannel,
      runs: state.runs,
      narrative_feed: state.narrativeFeed,
      current_run_id: state.currentRunId,
      current_stage_type: state.currentStageType,
      composer_state: state.composerState,
    },
  };
}

function getFeedIdentity(entry: TopLevelFeedEntry): FeedIdentity {
  switch (entry.type) {
    case "user_message":
      return `${entry.type}:${entry.message_id}`;
    case "stage_node":
      return `${entry.type}:${entry.stage_run_id}`;
    case "approval_request":
      return `${entry.type}:${entry.approval_id}`;
    case "tool_confirmation":
      return `${entry.type}:${entry.tool_confirmation_id}`;
    case "control_item":
      return `${entry.type}:${entry.control_record_id}`;
    case "approval_result":
      return `${entry.type}:${entry.approval_id}`;
    case "delivery_result":
      return `${entry.type}:${entry.delivery_record_id}`;
    case "system_status":
      return `${entry.type}:${entry.run_id}:${entry.status}`;
  }
}

function readPayload<TPayload>(
  event: SessionEvent,
  key: string,
): TPayload | null {
  const value = event.payload[key];
  return isRecord(value) ? (value as TPayload) : null;
}

type SessionStatusChangedPayload = {
  session_id: string;
  status: SessionStatus;
  current_run_id: string | null;
  current_stage_type: StageType | null;
};

function readSessionStatusChangedPayload(
  event: SessionEvent,
): SessionStatusChangedPayload | null {
  const { session_id, status, current_run_id, current_stage_type } =
    event.payload;
  if (typeof session_id !== "string" || typeof status !== "string") {
    return null;
  }

  return {
    session_id,
    status: status as SessionStatus,
    current_run_id: typeof current_run_id === "string" ? current_run_id : null,
    current_stage_type:
      typeof current_stage_type === "string"
        ? (current_stage_type as StageType)
        : null,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isRunStatus(status: SessionStatus): status is RunStatus {
  return status !== "draft";
}

function isTerminalSessionStatus(
  status: SessionStatus,
): status is Extract<SessionStatus, "completed" | "failed" | "terminated"> {
  return status === "completed" || status === "failed" || status === "terminated";
}
