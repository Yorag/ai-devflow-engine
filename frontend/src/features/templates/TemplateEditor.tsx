import { useEffect, useMemo, useState } from "react";

import type { PipelineTemplateRead, ProviderRead, StageType } from "../../api/types";
import { ErrorState } from "../errors/ErrorState";
import {
  availableTemplateProviders,
  isTemplateDirty,
  resolveTemplateStartGuard,
  unavailableProviderMessage,
  unavailableTemplateProviderIds,
  type TemplateDraftState,
} from "./template-state";

type TemplateEditorProps = {
  template: PipelineTemplateRead;
  providers: ProviderRead[];
  draft: TemplateDraftState;
  onDraftChange: (draft: TemplateDraftState) => void;
  onSaveAs: () => void;
  onOverwrite: () => void;
  onDelete: () => void;
  onDiscard: () => void;
  isSaving?: boolean;
  error?: unknown;
};

const stageLabels: Record<StageType, string> = {
  requirement_analysis: "Requirement Analysis",
  solution_design: "Solution Design",
  code_generation: "Code Generation",
  test_generation_execution: "Test Generation & Execution",
  code_review: "Code Review",
  delivery_integration: "Delivery Integration",
};

export function TemplateEditor({
  template,
  providers,
  draft,
  onDraftChange,
  onSaveAs,
  onOverwrite,
  onDelete,
  onDiscard,
  isSaving = false,
  error = null,
}: TemplateEditorProps): JSX.Element {
  const firstStageType =
    template.fixed_stage_sequence[0] ??
    draft.stage_role_bindings[0]?.stage_type ??
    "requirement_analysis";
  const [activeStageType, setActiveStageType] = useState<StageType>(firstStageType);
  const dirty = isTemplateDirty(template, draft);
  const unavailableProviderIds = unavailableTemplateProviderIds(draft, providers);
  const guard = resolveTemplateStartGuard(template, dirty);
  const retryError = getRetryValidationError(draft.max_auto_regression_retries);
  const nameError = getTemplateNameValidationError(template, draft.name);
  const providerOptions = availableTemplateProviders(providers);
  const noConfiguredProviders = providerOptions.length === 0;
  const activeBinding =
    draft.stage_role_bindings.find(
      (binding) => binding.stage_type === activeStageType,
    ) ??
    draft.stage_role_bindings.find((binding) => binding.stage_type === firstStageType) ??
    draft.stage_role_bindings[0];
  const activeStageLabel = activeBinding
    ? stageLabels[activeBinding.stage_type]
    : "Selected stage";
  const canSave =
    Boolean(activeBinding) &&
    !isSaving &&
    !retryError &&
    !nameError &&
    !noConfiguredProviders &&
    unavailableProviderIds.length === 0;
  const providerStatusReason =
    noConfiguredProviders || unavailableProviderIds.length > 0
      ? unavailableProviderMessage(unavailableProviderIds)
      : null;
  const statusMessages = [
    providerStatusReason,
    guard.reason && guard.reason !== providerStatusReason ? guard.reason : null,
  ].filter((message): message is string => Boolean(message));
  const stageSequence = useMemo(
    () =>
      template.fixed_stage_sequence.filter((stageType) =>
        draft.stage_role_bindings.some((binding) => binding.stage_type === stageType),
      ),
    [draft.stage_role_bindings, template.fixed_stage_sequence],
  );

  useEffect(() => {
    setActiveStageType(firstStageType);
  }, [firstStageType, template.template_id]);

  useEffect(() => {
    if (
      activeBinding ||
      !draft.stage_role_bindings[0] ||
      activeStageType === draft.stage_role_bindings[0].stage_type
    ) {
      return;
    }

    setActiveStageType(draft.stage_role_bindings[0].stage_type);
  }, [activeBinding, activeStageType, draft.stage_role_bindings]);

  function updateDraft(next: Partial<TemplateDraftState>) {
    onDraftChange({ ...draft, ...next });
  }

  function updateBinding(
    stageType: StageType,
    nextBinding: Partial<TemplateDraftState["stage_role_bindings"][number]>,
  ) {
    updateDraft({
      stage_role_bindings: draft.stage_role_bindings.map((binding) =>
        binding.stage_type === stageType ? { ...binding, ...nextBinding } : binding,
      ),
    });
  }

  return (
    <section className="template-editor" role="region" aria-label="Template editor">
      <div className="template-editor__heading">
        <div>
          <p className="workspace-eyebrow">Template editor</p>
          <h2>Run configuration</h2>
        </div>
        <span>{dirty ? "Unsaved" : "Saved"}</span>
      </div>

      {statusMessages.map((message) => (
        <p className="template-editor__guard" role="status" key={message}>
          {message}
        </p>
      ))}

      {template.template_source === "user_template" ? (
        <div className="template-editor__global">
          <label>
            <span>Template name</span>
            <input
              value={draft.name}
              aria-invalid={Boolean(nameError)}
              onChange={(event) => updateDraft({ name: event.target.value })}
            />
          </label>
        </div>
      ) : null}

      <div className="template-editor__policy-row">
        <label className="template-editor__checkbox">
          <input
            type="checkbox"
            checked={draft.auto_regression_enabled}
            onChange={(event) =>
              updateDraft({ auto_regression_enabled: event.target.checked })
            }
          />
          <span>Auto regression</span>
        </label>
        <label className="template-editor__checkbox">
          <input
            type="checkbox"
            checked={draft.skip_high_risk_tool_confirmations}
            onChange={(event) =>
              updateDraft({
                skip_high_risk_tool_confirmations: event.target.checked,
              })
            }
          />
          <span>Skip high-risk confirmations</span>
        </label>
        <label>
          <span>Maximum auto regression retries</span>
          <input
            type="number"
            min="0"
            step="1"
            value={
              Number.isFinite(draft.max_auto_regression_retries)
                ? draft.max_auto_regression_retries
                : ""
            }
            aria-invalid={Boolean(retryError)}
            onChange={(event) =>
              updateDraft({
                max_auto_regression_retries:
                  event.target.value === "" ? Number.NaN : Number(event.target.value),
              })
            }
          />
        </label>
      </div>

      {retryError ? (
        <p className="template-editor__field-error" role="alert">
          {retryError}
        </p>
      ) : null}
      {nameError ? (
        <p className="template-editor__field-error" role="alert">
          {nameError}
        </p>
      ) : null}
      {error ? <ErrorState error={error} /> : null}

      <div
        className="template-stage-tabs"
        role="tablist"
        aria-label="Template stages"
      >
        {stageSequence.map((stageType) => (
          <button
            className="template-stage-tab"
            key={stageType}
            type="button"
            role="tab"
            aria-selected={activeStageType === stageType}
            onClick={() => setActiveStageType(stageType)}
          >
            {stageLabels[stageType]}
          </button>
        ))}
      </div>

      <div className="template-editor__stages">
        {activeBinding ? (
          <section className="template-editor-stage" key={activeBinding.stage_type}>
            <div className="template-editor-stage__title">
              <strong>{activeStageLabel}</strong>
            </div>
            <div className="template-editor-stage__fields">
              <label>
                <span>Provider</span>
                <select
                  aria-label={`${activeStageLabel} provider`}
                  value={providerSelectValue(
                    activeBinding.provider_id,
                    providerOptions,
                  )}
                  disabled={noConfiguredProviders}
                  onChange={(event) =>
                    updateBinding(activeBinding.stage_type, {
                      provider_id: event.target.value,
                    })
                  }
                >
                  {noConfiguredProviders ? (
                    <option value="" disabled>
                      No provider configured
                    </option>
                  ) : null}
                  {!noConfiguredProviders &&
                  !providerOptions.some(
                    (provider) => provider.provider_id === activeBinding.provider_id,
                  ) ? (
                    <option value={activeBinding.provider_id} disabled>
                      Unavailable provider
                    </option>
                  ) : null}
                  {providerOptions.map((provider) => (
                    <option key={provider.provider_id} value={provider.provider_id}>
                      {provider.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="template-editor-stage__prompt">
                <span>System prompt</span>
                <textarea
                  aria-label={`${activeStageLabel} system prompt`}
                  rows={3}
                  value={activeBinding.system_prompt}
                  onChange={(event) =>
                    updateBinding(activeBinding.stage_type, {
                      system_prompt: event.target.value,
                    })
                  }
                />
              </label>
            </div>
          </section>
        ) : null}
      </div>

      <div className="template-editor__actions">
        {template.template_source === "user_template" && dirty ? (
          <p className="template-editor__action-note">
            Save or discard changes before deleting this user template.
          </p>
        ) : null}
        {dirty ? (
          <button
            className="workspace-button workspace-button--secondary"
            type="button"
            onClick={onDiscard}
          >
            Discard changes
          </button>
        ) : null}
        {template.template_source === "user_template" ? (
          <button
            className="workspace-button workspace-button--secondary"
            type="button"
            onClick={onSaveAs}
            disabled={!canSave}
          >
            {isSaving ? "Saving template" : "Save as new template"}
          </button>
        ) : null}
        <button
          className="workspace-button"
          type="button"
          onClick={
            template.template_source === "user_template"
              ? onOverwrite
              : onSaveAs
          }
          disabled={!canSave}
        >
          {isSaving ? "Saving template" : "Save template"}
        </button>
        {template.template_source === "user_template" ? (
          <>
            <button
              className="workspace-button workspace-button--danger"
              type="button"
              onClick={onDelete}
              disabled={dirty || isSaving}
            >
              Delete template
            </button>
          </>
        ) : null}
      </div>
    </section>
  );
}

function providerSelectValue(
  providerId: string,
  providerOptions: ProviderRead[],
): string {
  if (providerOptions.length === 0) {
    return "";
  }

  if (providerOptions.some((provider) => provider.provider_id === providerId)) {
    return providerId;
  }
  return providerId || "";
}

function getRetryValidationError(value: number): string | null {
  if (!Number.isFinite(value) || !Number.isInteger(value) || value < 0) {
    return "Cannot save current field: config_invalid_value. Maximum auto regression retries must be a finite non-negative number.";
  }

  if (value > 3) {
    return "Cannot save current field: config_hard_limit_exceeded. Maximum auto regression retries exceeds the backend save limit.";
  }

  return null;
}

function getTemplateNameValidationError(
  template: PipelineTemplateRead,
  value: string,
): string | null {
  if (template.template_source !== "user_template") {
    return null;
  }

  return value.trim()
    ? null
    : "Cannot save current field: config_invalid_value. Template name is required.";
}
