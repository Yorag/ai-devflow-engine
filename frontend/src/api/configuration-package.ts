import { apiRequest, type ApiRequestOptions } from "./client";
import type {
  ConfigurationPackageExport,
  ConfigurationPackageImportRequest,
  ConfigurationPackageImportResult,
} from "./types";

export function exportProjectConfigurationPackage(
  projectId: string,
  options?: ApiRequestOptions,
): Promise<ConfigurationPackageExport> {
  return apiRequest(`/api/projects/${projectId}/configuration-package/export`, options);
}

export function importProjectConfigurationPackage(
  projectId: string,
  body: ConfigurationPackageImportRequest,
  options?: ApiRequestOptions,
): Promise<ConfigurationPackageImportResult> {
  return apiRequest(`/api/projects/${projectId}/configuration-package/import`, {
    ...options,
    method: "POST",
    body,
  });
}
