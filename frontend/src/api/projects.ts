import { apiRequest, type ApiRequestOptions } from "./client";
import type { ProjectCreateRequest, ProjectRead, ProjectRemoveResult } from "./types";

export function listProjects(options?: ApiRequestOptions): Promise<ProjectRead[]> {
  return apiRequest("/api/projects", options);
}

export function createProject(
  body: ProjectCreateRequest,
  options?: ApiRequestOptions,
): Promise<ProjectRead> {
  return apiRequest("/api/projects", { ...options, method: "POST", body });
}

export function removeProject(
  projectId: string,
  options?: ApiRequestOptions,
): Promise<ProjectRemoveResult> {
  return apiRequest(`/api/projects/${projectId}`, {
    ...options,
    method: "DELETE",
  });
}
