import { apiRequest, type ApiRequestOptions } from "./client";
import type {
  ProjectDeliveryChannelDetailProjection,
  ProjectDeliveryChannelUpdateRequest,
  ProjectDeliveryChannelValidationResult,
} from "./types";

export function getProjectDeliveryChannel(
  projectId: string,
  options?: ApiRequestOptions,
): Promise<ProjectDeliveryChannelDetailProjection> {
  return apiRequest(`/api/projects/${projectId}/delivery-channel`, options);
}

export function updateProjectDeliveryChannel(
  projectId: string,
  body: ProjectDeliveryChannelUpdateRequest,
  options?: ApiRequestOptions,
): Promise<ProjectDeliveryChannelDetailProjection> {
  return apiRequest(`/api/projects/${projectId}/delivery-channel`, {
    ...options,
    method: "PUT",
    body,
  });
}

export function validateProjectDeliveryChannel(
  projectId: string,
  options?: ApiRequestOptions,
): Promise<ProjectDeliveryChannelValidationResult> {
  return apiRequest(`/api/projects/${projectId}/delivery-channel/validate`, {
    ...options,
    method: "POST",
  });
}
