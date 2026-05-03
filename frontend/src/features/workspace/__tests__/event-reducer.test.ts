import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ApprovalResultFeedEntry,
  ExecutionNodeProjection,
  ProviderCallStageItem,
  SessionEvent,
  ToolConfirmationFeedEntry,
  TopLevelFeedEntry,
} from "../../../api/types";
import { mockFeedEntriesByType, mockSessionWorkspaces } from "../../../mocks/fixtures";
import { createSessionEventSource } from "../sse-client";
import {
  applySessionEvent,
  updateComposerStateFromSessionStatus,
} from "../event-reducer";
import {
  initializeWorkspaceFromSnapshot,
  useWorkspaceStore,
  type WorkspaceStoreState,
} from "../workspace-store";

afterEach(() => {
  vi.restoreAllMocks();
  useWorkspaceStore.getState().resetWorkspace();
});

describe("workspace SSE client", () => {
  it("uses the canonical session events stream path", () => {
    const OriginalEventSource = globalThis.EventSource;
    const eventSourceSpy = vi.fn(function MockEventSource(
      this: EventSource,
      url: string,
    ) {
      Object.defineProperty(this, "url", { value: url });
    });
    vi.stubGlobal("EventSource", eventSourceSpy);

    const source = createSessionEventSource("session-1", {
      baseUrl: "http://localhost:8000/api/",
    });

    expect(eventSourceSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/sessions/session-1/events/stream",
    );
    expect((source as EventSource).url).toBe(
      "http://localhost:8000/api/sessions/session-1/events/stream",
    );

    vi.stubGlobal("EventSource", OriginalEventSource);
  });
});

describe("applySessionEvent", () => {
  it("merges stage updates in place and preserves provider_call semantics", () => {
    const snapshot = mockSessionWorkspaces["session-running"];
    initializeWorkspaceFromSnapshot(snapshot);
    const stageNode = findEntry(snapshot.narrative_feed, "stage_node");
    const updatedStageNode: ExecutionNodeProjection = {
      ...stageNode,
      status: "waiting_tool_confirmation",
      summary: "Code Generation is blocked on a high-risk tool confirmation.",
      items: stageNode.items.map((item) =>
        item.type === "provider_call"
          ? {
              ...item,
              status: "circuit_open",
              retry_attempt: 3,
              backoff_wait_seconds: null,
              circuit_breaker_status: "open",
              failure_reason: "quota_exhausted",
            }
          : item,
      ),
    };

    let state = reduce(
      useWorkspaceStore.getState(),
      sessionEvent("stage_updated", { stage_node: updatedStageNode }),
    );
    state = reduce(
      state,
      sessionEvent("stage_updated", { stage_node: updatedStageNode }),
    );

    expect(state.narrativeFeed.map((entry) => entry.entry_id)).toEqual(
      snapshot.narrative_feed.map((entry) => entry.entry_id),
    );
    expect(
      state.narrativeFeed.filter((entry) => entry.type === "stage_node"),
    ).toHaveLength(1);
    const mergedStage = findEntry(state.narrativeFeed, "stage_node");
    const providerCall = mergedStage.items.find(
      (item): item is ProviderCallStageItem => item.type === "provider_call",
    );
    expect(mergedStage.status).toBe("waiting_tool_confirmation");
    expect(providerCall).toMatchObject({
      type: "provider_call",
      status: "circuit_open",
      retry_attempt: 3,
      backoff_wait_seconds: null,
      circuit_breaker_status: "open",
      failure_reason: "quota_exhausted",
    });
  });

  it("adds and updates tool_confirmation top-level blocks without duplicates", () => {
    initializeWorkspaceFromSnapshot(mockSessionWorkspaces["session-running"]);
    const requested = mockFeedEntriesByType.tool_confirmation;
    const decided: ToolConfirmationFeedEntry = {
      ...requested,
      status: "denied",
      is_actionable: false,
      responded_at: "2026-05-01T09:23:00.000Z",
      decision: "denied",
      deny_followup_action: "run_failed",
      deny_followup_summary:
        "The current run will fail because no low-risk alternative path exists.",
      disabled_reason: "The tool action was denied.",
    };

    let state = reduce(
      useWorkspaceStore.getState(),
      sessionEvent("tool_confirmation_requested", {
        tool_confirmation: requested,
      }),
    );
    state = reduce(
      state,
      sessionEvent("tool_confirmation_result", { tool_confirmation: decided }),
    );
    state = reduce(
      state,
      sessionEvent("tool_confirmation_result", { tool_confirmation: decided }),
    );

    const confirmations = state.narrativeFeed.filter(
      (entry): entry is ToolConfirmationFeedEntry =>
        entry.type === "tool_confirmation",
    );
    expect(confirmations).toHaveLength(1);
    expect(confirmations[0]).toMatchObject({
      tool_confirmation_id: "tool-confirmation-1",
      status: "denied",
      decision: "denied",
      is_actionable: false,
      deny_followup_action: "run_failed",
      deny_followup_summary:
        "The current run will fail because no low-risk alternative path exists.",
    });
  });

  it("updates matching approval blocks when approval_result is appended", () => {
    initializeWorkspaceFromSnapshot(
      mockSessionWorkspaces["session-waiting-approval"],
    );
    const approvalResult: ApprovalResultFeedEntry = {
      entry_id: "entry-approval-result-solution-design",
      run_id: "run-waiting-approval",
      type: "approval_result",
      occurred_at: "2026-05-01T09:56:00.000Z",
      approval_id: "approval-solution-design",
      approval_type: "solution_design_approval",
      decision: "approved",
      reason: null,
      created_at: "2026-05-01T09:56:00.000Z",
      next_stage_type: "code_generation",
    };

    let state = reduce(
      useWorkspaceStore.getState(),
      sessionEvent("approval_result", { approval_result: approvalResult }),
    );
    state = reduce(
      state,
      sessionEvent("approval_result", { approval_result: approvalResult }),
    );

    const approvalRequest = state.narrativeFeed.find(
      (entry) =>
        entry.type === "approval_request" &&
        entry.approval_id === "approval-solution-design",
    );
    expect(approvalRequest).toMatchObject({
      status: "approved",
      is_actionable: false,
    });
    expect(
      state.narrativeFeed.filter((entry) => entry.type === "approval_result"),
    ).toHaveLength(1);
  });

  it("updates session, run, snapshot, and composer state from session_status_changed", () => {
    initializeWorkspaceFromSnapshot(mockSessionWorkspaces["session-running"]);

    let state = reduce(
      useWorkspaceStore.getState(),
      sessionEvent("session_status_changed", {
        session_id: "session-running",
        status: "waiting_tool_confirmation",
        current_run_id: "run-running",
        current_stage_type: "code_generation",
      }),
    );

    expect(state.session).toMatchObject({
      status: "waiting_tool_confirmation",
      current_run_id: "run-running",
      latest_stage_type: "code_generation",
    });
    expect(state.currentRunId).toBe("run-running");
    expect(state.currentStageType).toBe("code_generation");
    expect(state.focusedRunId).toBe("run-running");
    expect(state.runs[0]).toMatchObject({
      run_id: "run-running",
      status: "waiting_tool_confirmation",
      current_stage_type: "code_generation",
      is_active: true,
      ended_at: null,
    });
    expect(state.composerState).toEqual(
      updateComposerStateFromSessionStatus(
        "waiting_tool_confirmation",
        "run-running",
      ),
    );
    expect(state.snapshot?.composer_state).toEqual(state.composerState);

    state = reduce(
      state,
      sessionEvent("session_status_changed", {
        session_id: "session-running",
        status: "failed",
        current_run_id: "run-running",
        current_stage_type: "code_generation",
      }),
    );

    expect(state.runs[0]).toMatchObject({
      status: "failed",
      is_active: false,
      ended_at: "2026-05-01T09:30:00.000Z",
    });
    expect(state.composerState).toEqual({
      mode: "readonly",
      is_input_enabled: false,
      primary_action: "disabled",
      secondary_actions: [],
      bound_run_id: "run-running",
    });
  });

  it("keeps waiting clarification composer actions aligned with backend projection", () => {
    expect(updateComposerStateFromSessionStatus("waiting_clarification", "run-1")).toEqual({
      mode: "waiting_clarification",
      is_input_enabled: true,
      primary_action: "send",
      secondary_actions: ["pause", "terminate"],
      bound_run_id: "run-1",
    });
  });

  it("updates terminal run and composer state from system_status events", () => {
    initializeWorkspaceFromSnapshot(mockSessionWorkspaces["session-running"]);
    const systemStatus = {
      ...mockFeedEntriesByType.system_status,
      run_id: "run-running",
      status: "failed",
      occurred_at: "2026-05-01T10:00:00.000Z",
      title: "Run failed",
      reason: "Tests failed after retry limit.",
    } satisfies Extract<TopLevelFeedEntry, { type: "system_status" }>;

    const state = reduce(
      useWorkspaceStore.getState(),
      sessionEvent("system_status", { system_status: systemStatus }),
    );

    expect(state.session).toMatchObject({
      status: "failed",
      current_run_id: "run-running",
      updated_at: "2026-05-01T10:00:00.000Z",
    });
    expect(state.runs[0]).toMatchObject({
      run_id: "run-running",
      status: "failed",
      is_active: false,
      ended_at: "2026-05-01T10:00:00.000Z",
    });
    expect(state.composerState).toEqual({
      mode: "readonly",
      is_input_enabled: false,
      primary_action: "disabled",
      secondary_actions: [],
      bound_run_id: "run-running",
    });
    expect(state.narrativeFeed).toContainEqual(systemStatus);
  });

  it("promotes an active pipeline_run_created event over a terminal current run", () => {
    initializeWorkspaceFromSnapshot(mockSessionWorkspaces["session-failed"]);
    const retryRun = {
      run_id: "run-retry",
      attempt_index: 2,
      status: "running",
      trigger_source: "retry",
      started_at: "2026-05-01T10:20:00.000Z",
      ended_at: null,
      current_stage_type: "requirement_analysis",
      is_active: true,
    } satisfies WorkspaceStoreState["runs"][number];

    const state = reduce(
      useWorkspaceStore.getState(),
      sessionEvent("pipeline_run_created", { run: retryRun }, "run-retry"),
    );

    expect(state.currentRunId).toBe("run-retry");
    expect(state.currentStageType).toBe("requirement_analysis");
    expect(state.focusedRunId).toBe("run-retry");
    expect(state.session).toMatchObject({
      status: "running",
      current_run_id: "run-retry",
      latest_stage_type: "requirement_analysis",
    });
    expect(state.composerState).toEqual(
      updateComposerStateFromSessionStatus("running", "run-retry"),
    );
    expect(state.snapshot).toMatchObject({
      current_run_id: "run-retry",
      current_stage_type: "requirement_analysis",
      composer_state: state.composerState,
    });
    expect(state.snapshot?.session).toMatchObject({
      status: "running",
      current_run_id: "run-retry",
      latest_stage_type: "requirement_analysis",
    });
  });

  it("adds run and feed projection payloads using existing SessionEvent keys", () => {
    initializeWorkspaceFromSnapshot(mockSessionWorkspaces["session-running"]);
    const run = {
      run_id: "run-retry",
      attempt_index: 2,
      status: "running",
      trigger_source: "retry",
      started_at: "2026-05-01T10:00:00.000Z",
      ended_at: null,
      current_stage_type: "requirement_analysis",
      is_active: true,
    } satisfies WorkspaceStoreState["runs"][number];
    const message = {
      ...mockFeedEntriesByType.user_message,
      entry_id: "entry-user-message-retry",
      run_id: "run-retry",
      message_id: "message-retry",
      content: "Retry with a smaller scope.",
    };

    let state = reduce(
      useWorkspaceStore.getState(),
      sessionEvent("pipeline_run_created", { run }, "run-retry"),
    );
    state = reduce(
      state,
      sessionEvent(
        "session_message_appended",
        { message_item: message },
        "run-retry",
      ),
    );
    state = reduce(
      state,
      sessionEvent(
        "session_message_appended",
        { message_item: message },
        "run-retry",
      ),
    );

    expect(state.runs.some((candidate) => candidate.run_id === "run-retry")).toBe(
      true,
    );
    expect(
      state.narrativeFeed.filter(
        (entry) => entry.type === "user_message" && entry.run_id === "run-retry",
      ),
    ).toHaveLength(1);
  });
});

function reduce(
  state: WorkspaceStoreState,
  event: SessionEvent,
): WorkspaceStoreState {
  return applySessionEvent(state, event);
}

function sessionEvent(
  eventType: SessionEvent["event_type"],
  payload: SessionEvent["payload"],
  runId = "run-running",
): SessionEvent {
  return {
    event_id: `event-${eventType}`,
    session_id: "session-running",
    run_id: runId,
    event_type: eventType,
    occurred_at: "2026-05-01T09:30:00.000Z",
    payload,
  };
}

function findEntry<TType extends TopLevelFeedEntry["type"]>(
  entries: TopLevelFeedEntry[],
  type: TType,
): Extract<TopLevelFeedEntry, { type: TType }> {
  const entry = entries.find((candidate) => candidate.type === type);
  if (!entry) {
    throw new Error(`Missing ${type} entry`);
  }
  return entry as Extract<TopLevelFeedEntry, { type: TType }>;
}
