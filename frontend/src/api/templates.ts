import { apiRequest, type ApiRequestOptions } from "./client";
import type { PipelineTemplateRead, PipelineTemplateWriteRequest } from "./types";

export function listPipelineTemplates(
  options?: ApiRequestOptions,
): Promise<PipelineTemplateRead[]> {
  return apiRequest("/api/pipeline-templates", options);
}

export function getPipelineTemplate(
  templateId: string,
  options?: ApiRequestOptions,
): Promise<PipelineTemplateRead> {
  return apiRequest(`/api/pipeline-templates/${templateId}`, options);
}

export function createPipelineTemplate(
  body: PipelineTemplateWriteRequest,
  options?: ApiRequestOptions,
): Promise<PipelineTemplateRead> {
  return apiRequest("/api/pipeline-templates", {
    ...options,
    method: "POST",
    body,
  });
}

export function patchPipelineTemplate(
  templateId: string,
  body: PipelineTemplateWriteRequest,
  options?: ApiRequestOptions,
): Promise<PipelineTemplateRead> {
  return apiRequest(`/api/pipeline-templates/${templateId}`, {
    ...options,
    method: "PATCH",
    body,
  });
}

export function saveAsPipelineTemplate(
  templateId: string,
  body: PipelineTemplateWriteRequest,
  options?: ApiRequestOptions,
): Promise<PipelineTemplateRead> {
  return apiRequest(`/api/pipeline-templates/${templateId}/save-as`, {
    ...options,
    method: "POST",
    body,
  });
}

export function deletePipelineTemplate(
  templateId: string,
  options?: ApiRequestOptions,
): Promise<void> {
  return apiRequest(`/api/pipeline-templates/${templateId}`, {
    ...options,
    method: "DELETE",
  });
}
