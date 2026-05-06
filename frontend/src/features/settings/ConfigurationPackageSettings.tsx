import { type ChangeEvent, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { ApiRequestOptions } from "../../api/client";
import {
  exportProjectConfigurationPackage,
  importProjectConfigurationPackage,
} from "../../api/configuration-package";
import { apiQueryKeys } from "../../api/hooks";
import type {
  ConfigurationPackageExport,
  ConfigurationPackageImportRequest,
  ConfigurationPackageImportResult,
  ProjectRead,
} from "../../api/types";

type ConfigurationPackageSettingsProps = {
  project: ProjectRead | null;
  request?: ApiRequestOptions;
};

export function ConfigurationPackageSettings({
  project,
  request,
}: ConfigurationPackageSettingsProps): JSX.Element {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [exportResult, setExportResult] =
    useState<ConfigurationPackageExport | null>(null);
  const [importResult, setImportResult] =
    useState<ConfigurationPackageImportResult | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  async function handleExport() {
    if (!project) {
      setErrorMessage("Select a project before downloading JSON.");
      setStatusMessage(null);
      return;
    }

    setIsExporting(true);
    setErrorMessage(null);
    setStatusMessage(null);

    try {
      const result = await exportProjectConfigurationPackage(
        project.project_id,
        request,
      );
      const fileName = buildConfigurationPackageFileName(project);

      downloadJsonFile(fileName, result);
      setExportResult(result);
      setStatusMessage(`Downloaded ${fileName}.`);
    } catch (error) {
      setErrorMessage(readErrorMessage(error, "Download JSON failed."));
    } finally {
      setIsExporting(false);
    }
  }

  function handleUploadClick() {
    if (!project) {
      setErrorMessage("Select a project before uploading JSON.");
      setStatusMessage(null);
      setImportResult(null);
      return;
    }

    fileInputRef.current?.click();
  }

  async function handleImportFileChange(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0] ?? null;

    if (!project) {
      setErrorMessage("Select a project before uploading JSON.");
      setStatusMessage(null);
      setImportResult(null);
      input.value = "";
      return;
    }

    if (!file) {
      setErrorMessage("Choose a JSON file before uploading.");
      setStatusMessage(null);
      setImportResult(null);
      input.value = "";
      return;
    }

    if (!isJsonPackageFile(file)) {
      setErrorMessage("Choose a .json configuration package file.");
      setStatusMessage(null);
      setImportResult(null);
      input.value = "";
      return;
    }

    setIsImporting(true);
    setErrorMessage(null);
    setStatusMessage(null);
    setImportResult(null);

    try {
      const parsed = JSON.parse(
        await file.text(),
      ) as ConfigurationPackageImportRequest;
      const result = await importProjectConfigurationPackage(
        project.project_id,
        parsed,
        request,
      );

      setImportResult(result);

      if (result.field_errors?.length) {
        setStatusMessage(null);
      } else {
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
        setStatusMessage(`Uploaded ${file.name}.`);
      }
    } catch (error) {
      setStatusMessage(null);
      if (error instanceof SyntaxError) {
        setErrorMessage(`JSON parse failed: ${error.message}`);
      } else {
        setImportResult(null);
        setErrorMessage(readErrorMessage(error, "Upload JSON failed."));
      }
    } finally {
      setIsImporting(false);
      input.value = "";
    }
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
          disabled={isExporting}
        >
          {isExporting ? "Downloading JSON" : "Download JSON"}
        </button>
        <button
          type="button"
          className="workspace-button"
          onClick={handleUploadClick}
          disabled={isImporting}
        >
          {isImporting ? "Uploading JSON" : "Upload JSON"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          aria-label="Configuration package JSON file"
          className="settings-file-input"
          tabIndex={-1}
          onChange={handleImportFileChange}
        />
      </div>
      {statusMessage ? (
        <p className="settings-inline-status" aria-live="polite">
          {statusMessage}
        </p>
      ) : null}
      {errorMessage ? (
        <p className="settings-inline-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
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
          {importResult.changed_objects?.length ? (
            <ul className="settings-result__list" aria-label="Changed objects">
              {importResult.changed_objects.map((changedObject) => (
                <li
                  key={`${changedObject.object_type}-${changedObject.object_id}`}
                >
                  {changedObject.object_type}: {changedObject.object_id} /{" "}
                  {changedObject.action}
                </li>
              ))}
            </ul>
          ) : (
            <p>No configuration objects changed.</p>
          )}
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

function buildConfigurationPackageFileName(project: ProjectRead): string {
  const projectName = sanitizeFileNameSegment(project.name);
  const projectId = sanitizeFileNameSegment(project.project_id);
  const projectSegment = projectName || projectId || "project";

  return `function-one-config-${projectSegment}-${formatTimestamp(new Date())}.json`;
}

function sanitizeFileNameSegment(value: string): string {
  return value
    .trim()
    .replace(/[^A-Za-z0-9._-]+/gu, "-")
    .replace(/-+/gu, "-")
    .replace(/^-|-$/gu, "");
}

function formatTimestamp(date: Date): string {
  const pad = (value: number) => value.toString().padStart(2, "0");

  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(
    date.getDate(),
  )}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(
    date.getSeconds(),
  )}`;
}

function downloadJsonFile(fileName: string, data: unknown) {
  const blob = new Blob([`${JSON.stringify(data, null, 2)}\n`], {
    type: "application/json",
  });
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = objectUrl;
  link.download = fileName;
  link.rel = "noopener";
  document.body.appendChild(link);

  try {
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }
}

function isJsonPackageFile(file: File): boolean {
  const fileName = file.name.toLowerCase();

  return fileName.endsWith(".json");
}

function readErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}
