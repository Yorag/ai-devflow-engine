import type { PipelineTemplateRead, ProviderRead, StageType } from "../../api/types";
import {
  availableTemplateProviders,
  isTemplateDirty,
  resolveTemplateStartGuard,
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
}: TemplateEditorProps): JSX.Element {
  const dirty = isTemplateDirty(template, draft);
  const unavailableProviderIds = unavailableTemplateProviderIds(draft, providers);
  const guard = resolveTemplateStartGuard(template, dirty, unavailableProviderIds);
  const retryError = getRetryValidationError(draft.max_auto_regression_retries);
  const canSave = !retryError && unavailableProviderIds.length === 0;
  const roleOptions = Array.from(
    new Set(template.stage_role_bindings.map((binding) => binding.role_id)),
  );
  const providerOptions = availableTemplateProviders(providers);

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

      {!guard.canStart && guard.reason ? (
        <p className="template-editor__guard" role="status">
          {guard.reason}
        </p>
      ) : null}

      <div className="template-editor__global">
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
        <label>
          <span>Maximum auto regression retries</span>
          <input
            type="number"
            min="0"
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

      <div className="template-editor__stages">
        {draft.stage_role_bindings.map((binding) => (
          <section className="template-editor-stage" key={binding.stage_type}>
            <div className="template-editor-stage__title">
              <strong>Stage slot</strong>
              <span>{binding.stage_type}</span>
            </div>
            <div className="template-editor-stage__fields">
              <label>
                <span>Role</span>
                <select
                  aria-label={`${binding.stage_type} role`}
                  value={binding.role_id}
                  onChange={(event) =>
                    updateBinding(binding.stage_type, { role_id: event.target.value })
                  }
                >
                  {roleOptions.map((roleId) => (
                    <option key={roleId} value={roleId}>
                      {roleId}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Provider</span>
                <select
                  aria-label={`${binding.stage_type} provider`}
                  value={providerSelectValue(binding.provider_id, providerOptions)}
                  onChange={(event) =>
                    updateBinding(binding.stage_type, {
                      provider_id: event.target.value,
                    })
                  }
                >
                  {providerOptions.length === 0 ? (
                    <option value="" disabled>
                      No provider configured
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
                  aria-label={`${binding.stage_type} system prompt`}
                  rows={3}
                  value={binding.system_prompt}
                  onChange={(event) =>
                    updateBinding(binding.stage_type, {
                      system_prompt: event.target.value,
                    })
                  }
                />
              </label>
            </div>
          </section>
        ))}
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
        <button
          className="workspace-button"
          type="button"
          onClick={onSaveAs}
          disabled={!canSave}
        >
          Save as user template
        </button>
        {template.template_source === "user_template" ? (
          <>
            <button
              className="workspace-button workspace-button--secondary"
              type="button"
              onClick={onOverwrite}
              disabled={!dirty || !canSave}
            >
              Overwrite template
            </button>
            <button
              className="workspace-button workspace-button--danger"
              type="button"
              onClick={onDelete}
              disabled={dirty}
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
  if (providerOptions.some((provider) => provider.provider_id === providerId)) {
    return providerId;
  }
  return providerOptions[0]?.provider_id ?? "";
}

function getRetryValidationError(value: number): string | null {
  if (!Number.isFinite(value) || value < 0) {
    return "Cannot save current field: config_invalid_value. Maximum auto regression retries must be a finite non-negative number.";
  }

  if (value > 3) {
    return "Cannot save current field: config_hard_limit_exceeded. Maximum auto regression retries exceeds the backend save limit.";
  }

  return null;
}
