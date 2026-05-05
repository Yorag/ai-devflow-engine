import { apiRequest, type ApiRequestOptions } from "./client";
import type { ProviderRead, ProviderWriteRequest } from "./types";

export function listProviders(options?: ApiRequestOptions): Promise<ProviderRead[]> {
  return apiRequest("/api/providers", options);
}

export function getProvider(
  providerId: string,
  options?: ApiRequestOptions,
): Promise<ProviderRead> {
  return apiRequest(`/api/providers/${providerId}`, options);
}

export function createProvider(
  body: ProviderWriteRequest,
  options?: ApiRequestOptions,
): Promise<ProviderRead> {
  return apiRequest("/api/providers", { ...options, method: "POST", body });
}

export function patchProvider(
  providerId: string,
  body: ProviderWriteRequest,
  options?: ApiRequestOptions,
): Promise<ProviderRead> {
  return apiRequest(`/api/providers/${providerId}`, {
    ...options,
    method: "PATCH",
    body,
  });
}

export function deleteProvider(
  providerId: string,
  options?: ApiRequestOptions,
): Promise<void> {
  return apiRequest(`/api/providers/${providerId}`, {
    ...options,
    method: "DELETE",
  });
}
