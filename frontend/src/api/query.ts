import { apiRequest, type ApiRequestOptions } from "./client";
import type {
  ControlItemInspectorProjection,
  DeliveryResultDetailProjection,
  LogQueryResponse,
  RunTimelineProjection,
  SessionWorkspaceProjection,
  StageInspectorProjection,
  ToolConfirmationInspectorProjection,
} from "./types";

export type LogQueryParams = {
  level?: string;
  category?: string;
  source?: string;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
};

export function getSessionWorkspace(
  sessionId: string,
  options?: ApiRequestOptions,
): Promise<SessionWorkspaceProjection> {
  return apiRequest(`/api/sessions/${sessionId}/workspace`, options);
}

export function getRunTimeline(
  runId: string,
  options?: ApiRequestOptions,
): Promise<RunTimelineProjection> {
  return apiRequest(`/api/runs/${runId}/timeline`, options);
}

export function getStageInspector(
  stageRunId: string,
  options?: ApiRequestOptions,
): Promise<StageInspectorProjection> {
  return apiRequest(`/api/stages/${stageRunId}/inspector`, options);
}

export function getControlRecord(
  controlRecordId: string,
  options?: ApiRequestOptions,
): Promise<ControlItemInspectorProjection> {
  return apiRequest(`/api/control-records/${controlRecordId}`, options);
}

export function getToolConfirmation(
  toolConfirmationId: string,
  options?: ApiRequestOptions,
): Promise<ToolConfirmationInspectorProjection> {
  return apiRequest(`/api/tool-confirmations/${toolConfirmationId}`, options);
}

export function getDeliveryRecord(
  deliveryRecordId: string,
  options?: ApiRequestOptions,
): Promise<DeliveryResultDetailProjection> {
  return apiRequest(`/api/delivery-records/${deliveryRecordId}`, options);
}

export function getRunLogs(
  runId: string,
  params: LogQueryParams = {},
  options?: ApiRequestOptions,
): Promise<LogQueryResponse> {
  return apiRequest(`/api/runs/${runId}/logs${toQueryString(params)}`, options);
}

function toQueryString(params: LogQueryParams): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      query.set(key, String(value));
    }
  }

  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}
