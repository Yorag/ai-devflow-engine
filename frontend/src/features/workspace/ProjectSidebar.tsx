import { useEffect } from "react";

import type { ApiRequestOptions } from "../../api/client";
import {
  useProjectDeliveryChannelQuery,
  useProjectSessionsQuery,
  useProjectsQuery,
} from "../../api/hooks";
import type { ProjectRead } from "../../api/types";
import { SessionList } from "./SessionList";

type ProjectSidebarProps = {
  request: ApiRequestOptions;
  currentProjectId: string;
  onProjectChange: (projectId: string) => void;
  onCurrentProjectChange: (project: ProjectRead | null) => void;
};

export function ProjectSidebar({
  request,
  currentProjectId,
  onProjectChange,
  onCurrentProjectChange,
}: ProjectSidebarProps): JSX.Element {
  const projectsQuery = useProjectsQuery({ request });
  const projects = projectsQuery.data ?? [];
  const currentProject =
    projects.find((project) => project.project_id === currentProjectId) ??
    projects[0] ??
    null;
  const projectId = currentProject?.project_id ?? "";
  const sessionsQuery = useProjectSessionsQuery(projectId, { request });
  const deliveryQuery = useProjectDeliveryChannelQuery(projectId, { request });
  const sessionCount = sessionsQuery.data?.length ?? 0;
  const deliveryMode = deliveryQuery.data?.delivery_mode ?? "unknown";

  useEffect(() => {
    onCurrentProjectChange(currentProject);
  }, [currentProject, onCurrentProjectChange]);

  function handleProjectChange(projectId: string) {
    onProjectChange(projectId);
    onCurrentProjectChange(
      projects.find((project) => project.project_id === projectId) ?? null,
    );
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
        <button className="workspace-button" type="button">
          New session
        </button>
      </div>

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

      <SessionList sessions={sessionsQuery.data ?? []} />
    </aside>
  );
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
