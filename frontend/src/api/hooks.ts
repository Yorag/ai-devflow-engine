import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";

import type { ApiRequestError, ApiRequestOptions } from "./client";
import { getProjectDeliveryChannel } from "./delivery-channels";
import { listProjects } from "./projects";
import { listProviders } from "./providers";
import {
  getRunTimeline as fetchRunTimeline,
  getSessionWorkspace as fetchSessionWorkspace,
} from "./query";
import { listProjectSessions } from "./sessions";
import { listPipelineTemplates } from "./templates";
import type {
  PipelineTemplateRead,
  ProjectDeliveryChannelDetailProjection,
  ProjectRead,
  ProviderRead,
  RunTimelineProjection,
  SessionRead,
  SessionWorkspaceProjection,
} from "./types";

export { listProjects } from "./projects";
export { getRunTimeline, getSessionWorkspace } from "./query";
export { listProjectSessions } from "./sessions";

type QueryHookOptions<TQueryFnData, TData = TQueryFnData> = {
  request?: ApiRequestOptions;
  query?: Omit<
    UseQueryOptions<TQueryFnData, ApiRequestError, TData, QueryKey>,
    "queryKey" | "queryFn" | "enabled"
  > & {
    enabled?: boolean;
  };
};

export const apiQueryKeys = {
  projects: ["projects"] as const,
  projectSessions: (projectId: string) =>
    ["projects", projectId, "sessions"] as const,
  pipelineTemplates: ["pipeline-templates"] as const,
  providers: ["providers"] as const,
  projectDeliveryChannel: (projectId: string) =>
    ["projects", projectId, "delivery-channel"] as const,
  sessionWorkspace: (sessionId: string) =>
    ["sessions", sessionId, "workspace"] as const,
  runTimeline: (runId: string) => ["runs", runId, "timeline"] as const,
};

export function useProjectsQuery<TData = ProjectRead[]>(
  options: QueryHookOptions<ProjectRead[], TData> = {},
): UseQueryResult<TData, ApiRequestError> {
  return useQuery({
    ...options.query,
    queryKey: apiQueryKeys.projects,
    queryFn: () => listProjects(options.request),
  });
}

export function useProjectSessionsQuery<TData = SessionRead[]>(
  projectId: string,
  options: QueryHookOptions<SessionRead[], TData> = {},
): UseQueryResult<TData, ApiRequestError> {
  return useQuery({
    ...options.query,
    queryKey: apiQueryKeys.projectSessions(projectId),
    queryFn: () => listProjectSessions(projectId, options.request),
    enabled: combineEnabled(Boolean(projectId), options.query?.enabled),
  });
}

export function usePipelineTemplatesQuery<TData = PipelineTemplateRead[]>(
  options: QueryHookOptions<PipelineTemplateRead[], TData> = {},
): UseQueryResult<TData, ApiRequestError> {
  return useQuery({
    ...options.query,
    queryKey: apiQueryKeys.pipelineTemplates,
    queryFn: () => listPipelineTemplates(options.request),
  });
}

export function useProvidersQuery<TData = ProviderRead[]>(
  options: QueryHookOptions<ProviderRead[], TData> = {},
): UseQueryResult<TData, ApiRequestError> {
  return useQuery({
    ...options.query,
    queryKey: apiQueryKeys.providers,
    queryFn: () => listProviders(options.request),
  });
}

export function useProjectDeliveryChannelQuery<
  TData = ProjectDeliveryChannelDetailProjection,
>(
  projectId: string,
  options: QueryHookOptions<ProjectDeliveryChannelDetailProjection, TData> = {},
): UseQueryResult<TData, ApiRequestError> {
  return useQuery({
    ...options.query,
    queryKey: apiQueryKeys.projectDeliveryChannel(projectId),
    queryFn: () => getProjectDeliveryChannel(projectId, options.request),
    enabled: combineEnabled(Boolean(projectId), options.query?.enabled),
  });
}

export function useSessionWorkspaceQuery<TData = SessionWorkspaceProjection>(
  sessionId: string,
  options: QueryHookOptions<SessionWorkspaceProjection, TData> = {},
): UseQueryResult<TData, ApiRequestError> {
  return useQuery({
    ...options.query,
    queryKey: apiQueryKeys.sessionWorkspace(sessionId),
    queryFn: () => fetchSessionWorkspace(sessionId, options.request),
    enabled: combineEnabled(Boolean(sessionId), options.query?.enabled),
  });
}

export function useRunTimelineQuery<TData = RunTimelineProjection>(
  runId: string,
  options: QueryHookOptions<RunTimelineProjection, TData> = {},
): UseQueryResult<TData, ApiRequestError> {
  return useQuery({
    ...options.query,
    queryKey: apiQueryKeys.runTimeline(runId),
    queryFn: () => fetchRunTimeline(runId, options.request),
    enabled: combineEnabled(Boolean(runId), options.query?.enabled),
  });
}

function combineEnabled(required: boolean, configured: boolean | undefined): boolean {
  return required && configured !== false;
}
