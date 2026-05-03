import { useEffect, useMemo, useState } from "react";

import {
  usePipelineTemplatesQuery,
  useProjectSessionsQuery,
  useProvidersQuery,
  useSessionWorkspaceQuery,
} from "../../api/hooks";
import type { ApiRequestOptions } from "../../api/client";
import type { ProjectRead, SessionEvent, SseEventType } from "../../api/types";
import { Composer } from "../composer/Composer";
import { NarrativeFeed } from "../feed/NarrativeFeed";
import { InspectorPanel } from "../inspector/InspectorPanel";
import { useInspector } from "../inspector/useInspector";
import { TerminateRunAction } from "../runs/TerminateRunAction";
import { SettingsModal } from "../settings/SettingsModal";
import { TemplateEmptyState } from "../templates/TemplateEmptyState";
import { ProjectSidebar } from "./ProjectSidebar";
import { createSessionEventSource } from "./sse-client";
import { useWorkspaceStore } from "./workspace-store";

type WorkspaceShellProps = {
  request?: ApiRequestOptions;
};

export function WorkspaceShell({ request }: WorkspaceShellProps = {}): JSX.Element {
  const [isWorkspaceActionBusy, setWorkspaceActionBusy] = useState(false);
  const [currentProjectId, setCurrentProjectId] = useState("");
  const [currentProject, setCurrentProject] = useState<ProjectRead | null>(null);
  const [currentSessionId, setCurrentSessionId] = useState("");
  const [templateSelections, setTemplateSelections] = useState<Record<string, string>>(
    {},
  );
  const [isSettingsOpen, setSettingsOpen] = useState(false);
  const inspector = useInspector();
  const projectId = currentProject?.project_id ?? currentProjectId;
  const sessionsQuery = useProjectSessionsQuery(projectId, {
    request,
  });
  const templatesQuery = usePipelineTemplatesQuery({ request });
  const providersQuery = useProvidersQuery({ request });
  const sessions = useMemo(() => sessionsQuery.data ?? [], [sessionsQuery.data]);
  const selectedSession =
    sessions.find((session) => session.session_id === currentSessionId) ??
    sessions[0] ??
    null;
  const sessionWorkspaceQuery = useSessionWorkspaceQuery(
    selectedSession?.session_id ?? "",
    { request },
  );
  const snapshot = sessionWorkspaceQuery.data;
  const workspaceSessionId = useWorkspaceStore((state) => state.session?.session_id);
  const workspaceSessionStatus = useWorkspaceStore((state) => state.session?.status);
  const workspaceRuns = useWorkspaceStore((state) => state.runs);
  const workspaceNarrativeFeed = useWorkspaceStore((state) => state.narrativeFeed);
  const workspaceCurrentRunId = useWorkspaceStore((state) => state.currentRunId);
  const workspaceCurrentStageType = useWorkspaceStore(
    (state) => state.currentStageType,
  );
  const workspaceComposerState = useWorkspaceStore((state) => state.composerState);
  const initializeFromSnapshot = useWorkspaceStore(
    (state) => state.initializeFromSnapshot,
  );
  const applySessionEvent = useWorkspaceStore((state) => state.applySessionEvent);
  const resetWorkspace = useWorkspaceStore((state) => state.resetWorkspace);
  const workspace =
    snapshot && workspaceSessionId === snapshot.session.session_id
      ? {
          ...snapshot,
          session: {
            ...snapshot.session,
            status: workspaceSessionStatus ?? snapshot.session.status,
          },
          runs: workspaceRuns,
          narrative_feed: workspaceNarrativeFeed,
          current_run_id: workspaceCurrentRunId,
          current_stage_type: workspaceCurrentStageType,
          composer_state: workspaceComposerState ?? snapshot.composer_state,
        }
      : snapshot;
  const selectedTemplateId =
    selectedSession && templateSelections[selectedSession.session_id]
      ? templateSelections[selectedSession.session_id]
      : (workspace?.session.selected_template_id ??
        selectedSession?.selected_template_id ??
        "");

  useEffect(() => {
    if (!selectedSession) {
      setCurrentSessionId("");
      resetWorkspace();
      return;
    }

    setCurrentSessionId(selectedSession.session_id);
  }, [resetWorkspace, selectedSession]);

  useEffect(() => {
    if (!snapshot) {
      return;
    }

    initializeFromSnapshot(snapshot);
  }, [initializeFromSnapshot, snapshot]);

  useEffect(() => {
    const sessionId = snapshot?.session.session_id;
    if (!sessionId || typeof EventSource === "undefined") {
      return;
    }

    const source = createSessionEventSource(sessionId, { baseUrl: request?.baseUrl });
    const handleSessionEvent = (message: MessageEvent<string>) => {
      try {
        applySessionEvent(JSON.parse(message.data) as SessionEvent);
      } catch {
        // Ignore malformed stream frames; the snapshot query remains the recovery path.
      }
    };
    for (const eventType of SSE_EVENT_TYPES) {
      source.addEventListener(eventType, handleSessionEvent as EventListener);
    }
    return () => {
      for (const eventType of SSE_EVENT_TYPES) {
        source.removeEventListener(eventType, handleSessionEvent as EventListener);
      }
      source.close();
    };
  }, [applySessionEvent, request?.baseUrl, snapshot?.session.session_id]);

  function handleProjectChange(projectId: string) {
    setCurrentProjectId(projectId);
    setCurrentSessionId("");
    inspector.close();
  }

  function handleSessionChange(sessionId: string) {
    setCurrentSessionId(sessionId);
    inspector.close();
  }

  function handleTemplateChange(templateId: string) {
    if (!selectedSession) {
      return;
    }

    setTemplateSelections((current) => ({
      ...current,
      [selectedSession.session_id]: templateId,
    }));
  }

  return (
    <section
      className={`workspace-shell${
        inspector.isOpen ? " workspace-shell--inspector-open" : ""
      }`}
      aria-label="Workspace shell"
    >
      <ProjectSidebar
        request={request}
        currentProjectId={currentProjectId}
        currentSessionId={selectedSession?.session_id ?? ""}
        onProjectChange={handleProjectChange}
        onSessionChange={handleSessionChange}
        onCurrentProjectChange={setCurrentProject}
      />
      <section className="workspace-main" aria-label="Narrative workspace">
        <div className="workspace-toolbar" aria-label="Global tools">
          {workspace ? (
            <TerminateRunAction
              projectId={workspace.project.project_id}
              sessionId={workspace.session.session_id}
              runId={workspace.current_run_id}
              sessionStatus={workspace.session.status}
              secondaryActions={workspace.composer_state.secondary_actions}
              isBusy={isWorkspaceActionBusy}
              onBusyChange={setWorkspaceActionBusy}
              request={request}
            />
          ) : null}
          <button
            className="workspace-button workspace-button--secondary workspace-button--compact"
            type="button"
            onClick={() => setSettingsOpen(true)}
            aria-label="Open settings"
          >
            Settings
          </button>
        </div>
        <div className="narrative-feed" aria-label="Narrative Feed">
          {workspace?.session.status === "draft" ? (
            <TemplateEmptyState
              session={workspace.session}
              templates={templatesQuery.data ?? []}
              providers={providersQuery.data ?? []}
              selectedTemplateId={selectedTemplateId}
              onTemplateChange={handleTemplateChange}
            />
          ) : workspace ? (
            <NarrativeFeed
              entries={workspace.narrative_feed}
              runs={workspace.runs}
              currentRunId={workspace.current_run_id}
              onOpenInspectorTarget={inspector.openEntry}
            />
          ) : (
            <div className="workspace-main__empty">
              <p className="workspace-eyebrow">Narrative Workspace</p>
              <h1>{selectedSession ? selectedSession.display_name : "Workspace"}</h1>
              <p>
                {selectedSession
                  ? "Run history and execution feed will appear here."
                  : "Create or select a session to review its execution feed."}
              </p>
            </div>
          )}
        </div>
        {workspace ? (
          <Composer
            session={workspace.session}
            composerState={workspace.composer_state}
            currentStageType={workspace.current_stage_type}
            isBusy={isWorkspaceActionBusy}
            onBusyChange={setWorkspaceActionBusy}
            request={request}
          />
        ) : null}
      </section>
      <InspectorPanel
        isOpen={inspector.isOpen}
        target={inspector.target}
        onClose={inspector.close}
        request={request}
      />
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setSettingsOpen(false)}
        project={currentProject}
        request={request}
      />
    </section>
  );
}

const SSE_EVENT_TYPES: readonly SseEventType[] = [
  "session_created",
  "session_message_appended",
  "pipeline_run_created",
  "stage_started",
  "stage_updated",
  "clarification_requested",
  "clarification_answered",
  "approval_requested",
  "approval_result",
  "tool_confirmation_requested",
  "tool_confirmation_result",
  "control_item_created",
  "delivery_result",
  "system_status",
  "session_status_changed",
];
