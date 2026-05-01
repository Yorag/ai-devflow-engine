import { apiRequest, type ApiRequestOptions } from "./client";
import type {
  SessionDeleteResult,
  SessionMessageAppendRequest,
  SessionRead,
  SessionRenameRequest,
  SessionTemplateUpdateRequest,
} from "./types";

export function createSession(
  projectId: string,
  options?: ApiRequestOptions,
): Promise<SessionRead> {
  return apiRequest(`/api/projects/${projectId}/sessions`, {
    ...options,
    method: "POST",
  });
}

export function listProjectSessions(
  projectId: string,
  options?: ApiRequestOptions,
): Promise<SessionRead[]> {
  return apiRequest(`/api/projects/${projectId}/sessions`, options);
}

export function getSession(
  sessionId: string,
  options?: ApiRequestOptions,
): Promise<SessionRead> {
  return apiRequest(`/api/sessions/${sessionId}`, options);
}

export function renameSession(
  sessionId: string,
  body: SessionRenameRequest,
  options?: ApiRequestOptions,
): Promise<SessionRead> {
  return apiRequest(`/api/sessions/${sessionId}`, {
    ...options,
    method: "PATCH",
    body,
  });
}

export function deleteSession(
  sessionId: string,
  options?: ApiRequestOptions,
): Promise<SessionDeleteResult> {
  return apiRequest(`/api/sessions/${sessionId}`, {
    ...options,
    method: "DELETE",
  });
}

export function updateSessionTemplate(
  sessionId: string,
  body: SessionTemplateUpdateRequest,
  options?: ApiRequestOptions,
): Promise<SessionRead> {
  return apiRequest(`/api/sessions/${sessionId}/template`, {
    ...options,
    method: "PUT",
    body,
  });
}

export function appendSessionMessage(
  sessionId: string,
  body: SessionMessageAppendRequest,
  options?: ApiRequestOptions,
): Promise<SessionRead> {
  return apiRequest(`/api/sessions/${sessionId}/messages`, {
    ...options,
    method: "POST",
    body,
  });
}
