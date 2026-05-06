import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import type { ApiRequestOptions } from "../../api/client";
import {
  apiQueryKeys,
  useProjectSessionsQuery,
  useProjectsQuery,
} from "../../api/hooks";
import { createProject } from "../../api/projects";
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
  const [isLoadProjectOpen, setLoadProjectOpen] = useState(false);
  const [projectRootPath, setProjectRootPath] = useState("");
  const [isLoadingProject, setLoadingProject] = useState(false);
  const [loadProjectError, setLoadProjectError] = useState<unknown | null>(null);
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
  const sessions = sessionsQuery.data ?? [];

  useEffect(() => {
    onCurrentProjectChange(currentProject);
  }, [currentProject, onCurrentProjectChange]);

  function handleProjectChange(projectId: string) {
    setCreateSessionError(null);
    setLoadProjectError(null);
    onProjectChange(projectId);
    onCurrentProjectChange(
      projects.find((project) => project.project_id === projectId) ?? null,
    );
  }

  async function handleLoadProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const rootPath = projectRootPath.trim();
    if (!rootPath || isLoadingProject) {
      return;
    }

    setLoadingProject(true);
    setLoadProjectError(null);
    try {
      const project = await createProject(
        { root_path: rootPath },
        request ?? {},
      );
      queryClient.setQueryData<ProjectRead[]>(
        apiQueryKeys.projects,
        (current) => upsertLoadedProject(current ?? [], project),
      );
      onProjectChange(project.project_id);
      onCurrentProjectChange(project);
      setProjectRootPath("");
      setLoadProjectOpen(false);
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projects,
        refetchType: "all",
      });
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projectSessions(project.project_id),
        refetchType: "all",
      });
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projectDeliveryChannel(project.project_id),
        refetchType: "all",
      });
    } catch (error) {
      setLoadProjectError(error);
    } finally {
      setLoadingProject(false);
    }
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
        <button
          className="workspace-button workspace-button--secondary"
          type="button"
          disabled={isLoadingProject}
          onClick={() => {
            setLoadProjectOpen((current) => !current);
            setLoadProjectError(null);
          }}
        >
          {isLoadingProject ? "Loading" : "Load"}
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

      {isLoadProjectOpen ? (
        <form
          className="project-load-form"
          aria-label="Load local project"
          onSubmit={handleLoadProject}
        >
          <label>
            <span>Project root path</span>
            <input
              type="text"
              value={projectRootPath}
              onChange={(event) => setProjectRootPath(event.target.value)}
              disabled={isLoadingProject}
              placeholder="C:/work/project"
            />
          </label>
          <div className="project-load-form__actions">
            <button
              className="workspace-button"
              type="submit"
              disabled={!projectRootPath.trim() || isLoadingProject}
            >
              {isLoadingProject ? "Loading" : "Load"}
            </button>
            <button
              className="workspace-button workspace-button--secondary"
              type="button"
              disabled={isLoadingProject}
              onClick={() => {
                setLoadProjectOpen(false);
                setProjectRootPath("");
                setLoadProjectError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}

      {loadProjectError ? <ErrorState error={loadProjectError} /> : null}
      {createSessionError ? <ErrorState error={createSessionError} /> : null}

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
        onSessionRename={(session) => {
          queryClient.setQueryData<SessionRead[]>(
            apiQueryKeys.projectSessions(projectId),
            (current) => updateRenamedSession(current ?? [], session),
          );
          void queryClient.invalidateQueries({
            queryKey: apiQueryKeys.projectSessions(projectId),
            refetchType: "all",
          });
          void queryClient.invalidateQueries({
            queryKey: apiQueryKeys.sessionWorkspace(session.session_id),
            refetchType: "all",
          });
        }}
        onSessionDelete={(session, result) => {
          if (!result.visibility_removed) {
            return;
          }

          const nextSessions = removeDeletedSession(sessions, session.session_id);
          queryClient.setQueryData<SessionRead[]>(
            apiQueryKeys.projectSessions(projectId),
            nextSessions,
          );
          queryClient.removeQueries({
            queryKey: apiQueryKeys.sessionWorkspace(session.session_id),
          });
          if (currentSessionId === session.session_id) {
            onSessionChange("");
          }
          void queryClient.invalidateQueries({
            queryKey: apiQueryKeys.projectSessions(projectId),
            refetchType: "all",
          });
        }}
        request={request}
      />
    </aside>
  );
}

function upsertLoadedProject(
  projects: ProjectRead[],
  loadedProject: ProjectRead,
): ProjectRead[] {
  return [
    loadedProject,
    ...projects.filter((project) => project.project_id !== loadedProject.project_id),
  ];
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

function updateRenamedSession(
  sessions: SessionRead[],
  renamedSession: SessionRead,
): SessionRead[] {
  return sessions.map((session) =>
    session.session_id === renamedSession.session_id ? renamedSession : session,
  );
}

function removeDeletedSession(
  sessions: SessionRead[],
  sessionId: string,
): SessionRead[] {
  return sessions.filter((session) => session.session_id !== sessionId);
}

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
      {projects.length > 0 ? (
        <label>
          <span className="sr-only">Switch project</span>
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
      <p className="project-switcher__path" title={currentProject?.root_path}>
        {currentProject
          ? formatCompactPath(currentProject.root_path)
          : "Load a local project to begin."}
      </p>
    </section>
  );
}

function formatCompactPath(value: string): string {
  const normalized = value.replace(/\\/gu, "/");
  const segments = normalized.split("/").filter(Boolean);

  if (segments.length <= 3) {
    return value;
  }

  const hasDriveRoot = /^[A-Za-z]:$/u.test(segments[0] ?? "");
  const prefix = hasDriveRoot
    ? `${segments[0]}/${segments[1]}`
    : `${normalized.startsWith("/") ? "/" : ""}${segments[0]}/${segments[1]}`;
  const leaf = segments[segments.length - 1];

  return `${prefix}/.../${leaf}`;
}
