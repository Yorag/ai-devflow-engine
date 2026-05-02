import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { ApiRequestOptions } from "../../api/client";
import {
  exportProjectConfigurationPackage,
  importProjectConfigurationPackage,
} from "../../api/configuration-package";
import { apiQueryKeys } from "../../api/hooks";
import type {
  ConfigurationPackageExport,
  ConfigurationPackageImportResult,
  ProjectRead,
} from "../../api/types";

type ConfigurationPackageSettingsProps = {
  project: ProjectRead | null;
  request: ApiRequestOptions;
};

export function ConfigurationPackageSettings({
  project,
  request,
}: ConfigurationPackageSettingsProps): JSX.Element {
  const queryClient = useQueryClient();
  const [exportResult, setExportResult] =
    useState<ConfigurationPackageExport | null>(null);
  const [importResult, setImportResult] =
    useState<ConfigurationPackageImportResult | null>(null);

  async function handleExport() {
    if (!project) {
      return;
    }

    setExportResult(
      await exportProjectConfigurationPackage(project.project_id, request),
    );
  }

  async function handleImport() {
    if (!project) {
      return;
    }

    const result = await importProjectConfigurationPackage(
      project.project_id,
      {
        package_schema_version: "function-one-config-v1",
        scope: { scope_type: "project", project_id: project.project_id },
        providers: [],
        delivery_channels: [],
        pipeline_templates: [],
      },
      request,
    );
    setImportResult(result);
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projectDeliveryChannel(project.project_id),
        refetchType: "all",
      }),
      queryClient.invalidateQueries({
        queryKey: apiQueryKeys.providers,
        refetchType: "all",
      }),
      queryClient.invalidateQueries({
        queryKey: apiQueryKeys.pipelineTemplates,
        refetchType: "all",
      }),
    ]);
  }

  return (
    <div className="settings-section">
      <div className="settings-section__heading">
        <h3>导入导出</h3>
        <p>{project ? `Project: ${project.name}` : "No project loaded"}</p>
      </div>
      <div className="settings-actions settings-actions--start">
        <button
          type="button"
          className="workspace-button workspace-button--secondary"
          onClick={handleExport}
        >
          Export configuration package
        </button>
        <button type="button" className="workspace-button" onClick={handleImport}>
          Import configuration package
        </button>
      </div>
      {exportResult ? (
        <section className="settings-result" aria-label="Configuration export summary">
          <h4>{exportResult.package_schema_version}</h4>
          <p>{exportResult.scope.project_id}</p>
          <p>
            Providers {exportResult.providers.length}; delivery channels{" "}
            {exportResult.delivery_channels.length}; templates{" "}
            {exportResult.pipeline_templates.length}
          </p>
        </section>
      ) : null}
      {importResult ? (
        <section className="settings-result" aria-label="Configuration import summary">
          <h4>{importResult.summary ?? "Import result"}</h4>
          {importResult.changed_objects?.map((changedObject) => (
            <p key={`${changedObject.object_type}-${changedObject.object_id}`}>
              {changedObject.object_type}: {changedObject.object_id} /{" "}
              {changedObject.action}
            </p>
          ))}
          {importResult.field_errors?.map((fieldError) => (
            <p className="settings-inline-error" key={fieldError.field}>
              {fieldError.field}: {fieldError.message}
            </p>
          ))}
        </section>
      ) : null}
    </div>
  );
}
