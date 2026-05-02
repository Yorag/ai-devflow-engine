import { useEffect, useMemo, useState } from "react";

import {
  usePipelineTemplatesQuery,
  useProjectSessionsQuery,
  useProvidersQuery,
  useSessionWorkspaceQuery,
} from "../../api/hooks";
import type { ProjectRead } from "../../api/types";
import { mockApiRequestOptions } from "../../mocks/handlers";
import { SettingsModal } from "../settings/SettingsModal";
import { TemplateEmptyState } from "../templates/TemplateEmptyState";
import { ProjectSidebar } from "./ProjectSidebar";

export function WorkspaceShell(): JSX.Element {
  const [currentProjectId, setCurrentProjectId] = useState("");
  const [currentProject, setCurrentProject] = useState<ProjectRead | null>(null);
  const [currentSessionId, setCurrentSessionId] = useState("");
  const [templateSelections, setTemplateSelections] = useState<Record<string, string>>(
    {},
  );
  const [isSettingsOpen, setSettingsOpen] = useState(false);
  const projectId = currentProject?.project_id ?? currentProjectId;
  const sessionsQuery = useProjectSessionsQuery(projectId, {
    request: mockApiRequestOptions,
  });
  const templatesQuery = usePipelineTemplatesQuery({ request: mockApiRequestOptions });
  const providersQuery = useProvidersQuery({ request: mockApiRequestOptions });
  const sessions = useMemo(() => sessionsQuery.data ?? [], [sessionsQuery.data]);
  const selectedSession =
    sessions.find((session) => session.session_id === currentSessionId) ??
    sessions[0] ??
    null;
  const sessionWorkspaceQuery = useSessionWorkspaceQuery(
    selectedSession?.session_id ?? "",
    { request: mockApiRequestOptions },
  );
  const workspace = sessionWorkspaceQuery.data;
  const selectedTemplateId =
    selectedSession && templateSelections[selectedSession.session_id]
      ? templateSelections[selectedSession.session_id]
      : (workspace?.session.selected_template_id ??
        selectedSession?.selected_template_id ??
        "");

  useEffect(() => {
    if (!selectedSession) {
      setCurrentSessionId("");
      return;
    }

    setCurrentSessionId(selectedSession.session_id);
  }, [selectedSession]);

  function handleProjectChange(projectId: string) {
    setCurrentProjectId(projectId);
    setCurrentSessionId("");
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
    <section className="workspace-shell" aria-label="Workspace shell">
      <ProjectSidebar
        request={mockApiRequestOptions}
        currentProjectId={currentProjectId}
        currentSessionId={selectedSession?.session_id ?? ""}
        onProjectChange={handleProjectChange}
        onSessionChange={setCurrentSessionId}
        onCurrentProjectChange={setCurrentProject}
      />
      <section className="workspace-main" aria-label="Narrative workspace">
        <div className="workspace-toolbar" aria-label="Global tools">
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
      </section>
      <aside className="workspace-inspector" aria-label="Inspector">
        <p>Inspector closed</p>
      </aside>
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setSettingsOpen(false)}
        project={currentProject}
        request={mockApiRequestOptions}
      />
    </section>
  );
}
