import { useEffect, useMemo, useState } from "react";

import {
  usePipelineTemplatesQuery,
  useProjectSessionsQuery,
  useProvidersQuery,
  useSessionWorkspaceQuery,
} from "../../api/hooks";
import type { ApiRequestOptions } from "../../api/client";
import type {
  PipelineTemplateRead,
  PipelineTemplateWriteRequest,
  ProjectRead,
  SessionEvent,
  SseEventType,
} from "../../api/types";
import { updateSessionTemplate } from "../../api/sessions";
import {
  deletePipelineTemplate,
  patchPipelineTemplate,
  saveAsPipelineTemplate,
} from "../../api/templates";
import { ErrorState } from "../errors/ErrorState";
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
  const [isSessionSelectionCleared, setSessionSelectionCleared] = useState(false);
  const [templateSelections, setTemplateSelections] = useState<Record<string, string>>(
    {},
  );
  const [configuredDraftSessionIds, setConfiguredDraftSessionIds] = useState<
    string[]
  >([]);
  const [templateChangeError, setTemplateChangeError] = useState<unknown | null>(
    null,
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
  const shouldAutoSelectSession =
    currentSessionId === "" &&
    !isSessionSelectionCleared &&
    sessions.length > 0 &&
    Boolean(projectId) &&
    sessionsQuery.isSuccess;
  const selectedSession = shouldAutoSelectSession
    ? sessions[0]
    : (sessions.find((session) => session.session_id === currentSessionId) ?? null);
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
  const templateIds = useMemo(
    () => new Set((templatesQuery.data ?? []).map((template) => template.template_id)),
    [templatesQuery.data],
  );
  const isInspectorVisible = inspector.isOpen && inspector.target !== null;
  const shellClassName = isInspectorVisible
    ? "workspace-shell workspace-shell--inspector-open"
    : "workspace-shell workspace-shell--inspector-closed";

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
    setSessionSelectionCleared(false);
    setConfiguredDraftSessionIds([]);
    inspector.close();
  }

  function handleSessionChange(sessionId: string) {
    setCurrentSessionId(sessionId);
    setSessionSelectionCleared(sessionId === "");
    setTemplateChangeError(null);
    inspector.close();
  }

  async function handleTemplateChange(templateId: string) {
    if (!selectedSession) {
      return;
    }

    setTemplateSelections((current) => ({
      ...current,
      [selectedSession.session_id]: templateId,
    }));
    setTemplateChangeError(null);

    if (
      selectedSession.status !== "draft" ||
      !templateIds.has(templateId) ||
      selectedSession.selected_template_id === templateId
    ) {
      return;
    }

    setWorkspaceActionBusy(true);
    try {
      const updatedSession = await updateSessionTemplate(
        selectedSession.session_id,
        { template_id: templateId },
        request ?? {},
      );
      setTemplateSelections((current) => ({
        ...current,
        [updatedSession.session_id]: updatedSession.selected_template_id,
      }));
      setConfiguredDraftSessionIds((current) =>
        current.filter((sessionId) => sessionId !== updatedSession.session_id),
      );
      await sessionsQuery.refetch();
      await sessionWorkspaceQuery.refetch();
    } catch (error) {
      setTemplateChangeError(error);
      setTemplateSelections((current) => ({
        ...current,
        [selectedSession.session_id]: selectedSession.selected_template_id,
      }));
    } finally {
      setWorkspaceActionBusy(false);
    }
  }

  async function handleTemplateSaveAs(
    _template: PipelineTemplateRead,
    sourceTemplate: PipelineTemplateRead,
    draft: PipelineTemplateWriteRequest,
  ): Promise<PipelineTemplateRead> {
    if (!selectedSession) {
      return _template;
    }

    setWorkspaceActionBusy(true);
    setTemplateChangeError(null);
    try {
      const savedTemplate = await saveAsPipelineTemplate(
        sourceTemplate.template_id,
        createTemplateWriteRequest(draft),
        request ?? {},
      );
      const updatedSession = await updateSessionTemplate(
        selectedSession.session_id,
        { template_id: savedTemplate.template_id },
        request ?? {},
      );
      setTemplateSelections((current) => ({
        ...current,
        [updatedSession.session_id]: updatedSession.selected_template_id,
      }));
      setConfiguredDraftSessionIds((current) =>
        current.includes(updatedSession.session_id)
          ? current
          : [...current, updatedSession.session_id],
      );
      await templatesQuery.refetch();
      await sessionsQuery.refetch();
      await sessionWorkspaceQuery.refetch();
      return savedTemplate;
    } catch (error) {
      setTemplateChangeError(error);
      throw error;
    } finally {
      setWorkspaceActionBusy(false);
    }
  }

  async function handleTemplateOverwrite(
    _template: PipelineTemplateRead,
    sourceTemplate: PipelineTemplateRead,
    draft: PipelineTemplateWriteRequest,
  ): Promise<PipelineTemplateRead> {
    if (!selectedSession) {
      return _template;
    }

    setWorkspaceActionBusy(true);
    setTemplateChangeError(null);
    try {
      const patchedTemplate = await patchPipelineTemplate(
        sourceTemplate.template_id,
        createTemplateWriteRequest(draft),
        request ?? {},
      );
      const updatedSession = await updateSessionTemplate(
        selectedSession.session_id,
        { template_id: patchedTemplate.template_id },
        request ?? {},
      );
      setTemplateSelections((current) => ({
        ...current,
        [updatedSession.session_id]: updatedSession.selected_template_id,
      }));
      setConfiguredDraftSessionIds((current) =>
        current.includes(updatedSession.session_id)
          ? current
          : [...current, updatedSession.session_id],
      );
      await templatesQuery.refetch();
      await sessionsQuery.refetch();
      await sessionWorkspaceQuery.refetch();
      return patchedTemplate;
    } catch (error) {
      setTemplateChangeError(error);
      throw error;
    } finally {
      setWorkspaceActionBusy(false);
    }
  }

  async function handleTemplateDelete(templateId: string): Promise<void> {
    if (!selectedSession) {
      return;
    }

    setWorkspaceActionBusy(true);
    setTemplateChangeError(null);
    try {
      await deletePipelineTemplate(templateId, request ?? {});
      setConfiguredDraftSessionIds((current) =>
        current.filter((sessionId) => sessionId !== selectedSession.session_id),
      );
      await templatesQuery.refetch();
      await sessionsQuery.refetch();
      await sessionWorkspaceQuery.refetch();
    } catch (error) {
      setTemplateChangeError(error);
      throw error;
    } finally {
      setWorkspaceActionBusy(false);
    }
  }

  return (
    <section
      className={shellClassName}
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
        <div className="workspace-main__scroll">
          <div className="workspace-main__content">
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
            {workspace?.session.status === "draft" &&
            !configuredDraftSessionIds.includes(workspace.session.session_id) ? (
              <div className="workspace-main__panel workspace-main__panel--template">
                <div className="narrative-feed" aria-label="Narrative Feed">
                  {templateChangeError ? (
                    <ErrorState error={templateChangeError} />
                  ) : null}
                  <TemplateEmptyState
                    session={workspace.session}
                    templates={templatesQuery.data ?? []}
                    providers={providersQuery.data ?? []}
                    selectedTemplateId={selectedTemplateId}
                    onTemplateChange={handleTemplateChange}
                    isTemplateChangeBusy={isWorkspaceActionBusy}
                    onTemplateSaveAs={handleTemplateSaveAs}
                    onTemplateOverwrite={handleTemplateOverwrite}
                    onTemplateDelete={handleTemplateDelete}
                  />
                </div>
              </div>
            ) : workspace?.session.status === "draft" ? (
              <div className="workspace-main__panel workspace-main__panel--feed">
                <div className="narrative-feed" aria-label="Narrative Feed" />
              </div>
            ) : workspace ? (
              <div className="workspace-main__panel workspace-main__panel--feed">
                <div className="narrative-feed" aria-label="Narrative Feed">
                  <NarrativeFeed
                    entries={workspace.narrative_feed}
                    runs={workspace.runs}
                    currentRunId={workspace.current_run_id}
                    currentSessionStatus={workspace.session.status}
                    sessionId={workspace.session.session_id}
                    projectId={workspace.project.project_id}
                    request={request}
                    onOpenInspectorTarget={inspector.openEntry}
                    onOpenSettings={() => setSettingsOpen(true)}
                  />
                </div>
              </div>
            ) : (
              <div className="workspace-main__panel workspace-main__panel--empty">
                <div className="workspace-main__empty">
                  <p className="workspace-eyebrow">Narrative Workspace</p>
                  <h1>
                    {selectedSession ? selectedSession.display_name : "Workspace"}
                  </h1>
                  <p>
                    {selectedSession
                      ? "Run history and execution feed will appear here."
                      : "Create or select a session to review its execution feed."}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
        {workspace ? (
          <div className="workspace-main__composer-dock">
            <div className="workspace-main__composer-inner">
              <Composer
                session={workspace.session}
                composerState={workspace.composer_state}
                currentStageType={workspace.current_stage_type}
                isBusy={isWorkspaceActionBusy}
                onBusyChange={setWorkspaceActionBusy}
                request={request}
              />
            </div>
          </div>
        ) : null}
      </section>
      <InspectorPanel
        isOpen={isInspectorVisible}
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

function createTemplateWriteRequest(
  draft: PipelineTemplateWriteRequest,
): PipelineTemplateWriteRequest {
  return {
    name: draft.name.trim(),
    description: draft.description,
    stage_role_bindings: draft.stage_role_bindings,
    auto_regression_enabled: draft.auto_regression_enabled,
    max_auto_regression_retries: draft.max_auto_regression_retries,
  };
}
