import { apiRequest, type ApiRequestOptions } from "./client";
import type { RunSummaryProjection, RunTimelineProjection } from "./types";

export function createRerun(
  sessionId: string,
  options?: ApiRequestOptions,
): Promise<RunSummaryProjection> {
  return apiRequest(`/api/sessions/${sessionId}/runs`, {
    ...options,
    method: "POST",
  });
}

export function getRun(
  runId: string,
  options?: ApiRequestOptions,
): Promise<RunSummaryProjection> {
  return apiRequest(`/api/runs/${runId}`, options);
}

export function getRunTimeline(
  runId: string,
  options?: ApiRequestOptions,
): Promise<RunTimelineProjection> {
  return apiRequest(`/api/runs/${runId}/timeline`, options);
}

export function pauseRun(
  runId: string,
  options?: ApiRequestOptions,
): Promise<RunSummaryProjection> {
  return apiRequest(`/api/runs/${runId}/pause`, { ...options, method: "POST" });
}

export function resumeRun(
  runId: string,
  options?: ApiRequestOptions,
): Promise<RunSummaryProjection> {
  return apiRequest(`/api/runs/${runId}/resume`, { ...options, method: "POST" });
}

export function terminateRun(
  runId: string,
  options?: ApiRequestOptions,
): Promise<RunSummaryProjection> {
  return apiRequest(`/api/runs/${runId}/terminate`, {
    ...options,
    method: "POST",
  });
}
