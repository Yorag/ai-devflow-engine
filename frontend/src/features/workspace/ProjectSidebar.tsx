import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { ApiRequestOptions } from "../../api/client";
import {
  apiQueryKeys,
  useProjectDeliveryChannelQuery,
  useProjectSessionsQuery,
  useProjectsQuery,
} from "../../api/hooks";
import { createSession } from "../../api/sessions";
import type { ProjectRead, SessionRead } from "../../api/types";
import { ErrorState } from "../errors/ErrorState";
import { SessionList } from "./SessionList";

type ProjectSidebarProps = {
  request?: ApiRequestOptions;
  currentProjectId: string;
  currentSessionId: string;
  onProjectChange: (projectId: string) => void;
  onSessionChange: (sessionId: string) => void;
  onCurrentProjectChange: (project: ProjectRead | null) => void;
};

export function ProjectSidebar({
  request,
  currentProjectId,
  currentSessionId,
  onProjectChange,
  onSessionChange,
  onCurrentProjectChange,
}: ProjectSidebarProps): JSX.Element {
  const queryClient = useQueryClient();
  const [isCreatingSession, setCreatingSession] = useState(false);
  const [createSessionError, setCreateSessionError] = useState<unknown | null>(
    null,
  );
  const projectsQuery = useProjectsQuery({ request });
  const projects = projectsQuery.data ?? [];
  const currentProject =
    projects.find((project) => project.project_id === currentProjectId) ??
    projects[0] ??
    null;
  const projectId = currentProject?.project_id ?? "";
  const sessionsQuery = useProjectSessionsQuery(projectId, { request });
  const deliveryQuery = useProjectDeliveryChannelQuery(projectId, { request });
  const sessions = sessionsQuery.data ?? [];
  const sessionCount = sessions.length;
  const deliveryMode = deliveryQuery.data?.delivery_mode ?? "unknown";
  const latestSession = sessions.reduce<ProjectSidebarLatestSession | null>(
    (latest, session) =>
      latest && latest.updated_at >= session.updated_at ? latest : session,
    null,
  );

  useEffect(() => {
    onCurrentProjectChange(currentProject);
  }, [currentProject, onCurrentProjectChange]);

  function handleProjectChange(projectId: string) {
    setCreateSessionError(null);
    onProjectChange(projectId);
    onCurrentProjectChange(
      projects.find((project) => project.project_id === projectId) ?? null,
    );
  }

  async function handleCreateSession() {
    if (!projectId || isCreatingSession) {
      return;
    }

    setCreatingSession(true);
    setCreateSessionError(null);
    try {
      const session = await createSession(projectId, request ?? {});
      queryClient.setQueryData<SessionRead[]>(
        apiQueryKeys.projectSessions(projectId),
        (current) => upsertCreatedSession(current ?? [], session),
      );
      onSessionChange(session.session_id);
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projectSessions(projectId),
        refetchType: "all",
      });
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.sessionWorkspace(session.session_id),
        refetchType: "all",
      });
    } catch (error) {
      setCreateSessionError(error);
    } finally {
      setCreatingSession(false);
    }
  }

  return (
    <aside className="workspace-sidebar" aria-label="Project and session sidebar">
      <ProjectSwitcher
        projects={projects}
        currentProject={currentProject}
        onProjectChange={handleProjectChange}
      />

      <div className="workspace-sidebar__actions">
        <button className="workspace-button workspace-button--secondary" type="button">
          Load project
        </button>
        <button
          className="workspace-button"
          type="button"
          disabled={!projectId || isCreatingSession}
          onClick={handleCreateSession}
        >
          {isCreatingSession ? "Creating session" : "New session"}
        </button>
      </div>

      {createSessionError ? <ErrorState error={createSessionError} /> : null}

      {currentProject ? (
        <section className="project-summary" aria-label="Current project summary">
          <div>
            <span>Sessions</span>
            <strong>{sessionCount}</strong>
          </div>
          <div>
            <span>Default delivery</span>
            <strong>{deliveryMode}</strong>
          </div>
          <div>
            <span>Latest activity</span>
            <strong>
              {latestSession ? formatTimestamp(latestSession.updated_at) : "None"}
            </strong>
          </div>
        </section>
      ) : null}

      <button
        className="workspace-button workspace-button--danger"
        type="button"
        disabled
        aria-label={
          currentProject?.is_default
            ? "Default project cannot be removed"
            : `Remove ${currentProject?.name} unavailable`
        }
      >
        Remove project
      </button>

      <SessionList
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSessionChange={onSessionChange}
      />
    </aside>
  );
}

function upsertCreatedSession(
  sessions: SessionRead[],
  createdSession: SessionRead,
): SessionRead[] {
  return [
    createdSession,
    ...sessions.filter(
      (session) => session.session_id !== createdSession.session_id,
    ),
  ];
}

type ProjectSidebarLatestSession = {
  updated_at: string;
};

function ProjectSwitcher({
  projects,
  currentProject,
  onProjectChange,
}: {
  projects: ProjectRead[];
  currentProject: ProjectRead | null;
  onProjectChange: (projectId: string) => void;
}): JSX.Element {
  return (
    <section className="project-switcher" aria-label="Project switcher">
      <p className="workspace-eyebrow">Project</p>
      <h2>{currentProject?.name ?? "No project loaded"}</h2>
      <p>{currentProject?.root_path ?? "Load a local project to begin."}</p>
      {projects.length > 0 ? (
        <label>
          <span>Switch project</span>
          <select
            value={currentProject?.project_id ?? ""}
            onChange={(event) => onProjectChange(event.target.value)}
          >
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </section>
  );
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(
    date.getUTCDate(),
  )} ${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}`;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}
