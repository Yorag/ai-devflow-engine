import { useLayoutEffect, useState } from "react";

import type {
  PipelineTemplateRead,
  PipelineTemplateWriteRequest,
  ProviderRead,
  StageRoleBinding,
} from "../../api/types";

export type TemplateDraftState = Pick<
  PipelineTemplateWriteRequest,
  | "stage_role_bindings"
  | "auto_regression_enabled"
  | "max_auto_regression_retries"
>;
export type TemplateGuardAction = "overwrite" | "save_as" | "discard";

export type TemplateStartGuard = {
  canStart: boolean;
  reason: string | null;
  actions: TemplateGuardAction[];
};

type TemplateDraftRecord = {
  draft: TemplateDraftState | null;
  baselineDraft: TemplateDraftState | null;
  templateId: string | null;
  scopeId: string;
};

export function createTemplateDraft(
  template: PipelineTemplateRead,
): TemplateDraftState {
  return {
    stage_role_bindings: cloneStageRoleBindings(template.stage_role_bindings),
    auto_regression_enabled: template.auto_regression_enabled,
    max_auto_regression_retries: template.max_auto_regression_retries,
  };
}

export function useTemplateDraftState(
  template: PipelineTemplateRead | null,
  scopeId = "",
): {
  draft: TemplateDraftState | null;
  setDraft: (draft: TemplateDraftState) => void;
  resetDraft: () => void;
  dirty: boolean;
} {
  const templateId = template?.template_id ?? null;
  const templateDraftSignature = template
    ? serializeDraft(createTemplateDraft(template))
    : null;
  const [state, setState] = useState<TemplateDraftRecord>(() =>
    createDraftRecord(template, scopeId),
  );

  useLayoutEffect(() => {
    setState((current) => {
      const nextRecord = createDraftRecord(template, scopeId);
      const identityChanged =
        current.scopeId !== scopeId || current.templateId !== templateId;

      if (identityChanged || !current.draft || !current.baselineDraft) {
        return nextRecord;
      }

      if (serializeDraft(current.draft) === serializeDraft(current.baselineDraft)) {
        return nextRecord;
      }

      return {
        ...current,
        baselineDraft: nextRecord.baselineDraft,
        templateId,
        scopeId,
      };
    });
  }, [scopeId, template, templateDraftSignature, templateId]);

  function setDraft(draft: TemplateDraftState) {
    setState((current) => ({ ...current, draft }));
  }

  function resetDraft() {
    setState(createDraftRecord(template, scopeId));
  }

  return {
    draft: state.draft,
    setDraft,
    resetDraft,
    dirty: Boolean(template && state.draft && isTemplateDirty(template, state.draft)),
  };
}

export function isTemplateDirty(
  template: PipelineTemplateRead,
  draft: TemplateDraftState,
): boolean {
  return serializeDraft(createTemplateDraft(template)) !== serializeDraft(draft);
}

export function resolveTemplateStartGuard(
  template: PipelineTemplateRead,
  dirty: boolean,
  unavailableProviderIds: string[] = [],
): TemplateStartGuard {
  if (unavailableProviderIds.length > 0) {
    return {
      canStart: false,
      reason: unavailableProviderMessage(unavailableProviderIds),
      actions: [],
    };
  }

  if (!dirty) {
    return { canStart: true, reason: null, actions: [] };
  }

  if (template.template_source === "system_template") {
    return {
      canStart: false,
      reason:
        "Save this edited system template as a user template or discard changes before starting a run.",
      actions: ["save_as", "discard"],
    };
  }

  return {
    canStart: false,
    reason:
      "Overwrite this user template, save it as a new template, or discard changes before starting a run.",
    actions: ["overwrite", "save_as", "discard"],
  };
}

export function cloneStageRoleBindings(
  bindings: StageRoleBinding[],
): StageRoleBinding[] {
  return bindings.map((binding) => ({ ...binding }));
}

export function availableTemplateProviders(providers: ProviderRead[]): ProviderRead[] {
  return providers.filter((provider) => provider.is_enabled);
}

export function resolveTemplateProviderBindings(
  template: PipelineTemplateRead,
  providers: ProviderRead[],
): PipelineTemplateRead {
  void providers;
  return template;
}

export function resolveTemplateDraftProviders(
  draft: TemplateDraftState,
  providers: ProviderRead[],
): TemplateDraftState {
  void providers;
  return draft;
}

export function unavailableTemplateProviderIds(
  draft: TemplateDraftState,
  providers: ProviderRead[],
): string[] {
  const availableProviderIds = new Set(
    availableTemplateProviders(providers).map((provider) => provider.provider_id),
  );
  return Array.from(
    new Set(
      draft.stage_role_bindings
        .map((binding) => binding.provider_id)
        .filter((providerId) => !availableProviderIds.has(providerId)),
    ),
  );
}

export function unavailableProviderMessage(providerIds: string[]): string {
  return `This template references unavailable providers: ${providerIds.join(", ")}.`;
}

function createDraftRecord(
  template: PipelineTemplateRead | null,
  scopeId: string,
): TemplateDraftRecord {
  const draft = template ? createTemplateDraft(template) : null;

  return {
    draft,
    baselineDraft: draft,
    templateId: template?.template_id ?? null,
    scopeId,
  };
}

function serializeDraft(draft: TemplateDraftState): string {
  return JSON.stringify({
    stage_role_bindings: draft.stage_role_bindings.map((binding) => ({
      stage_type: binding.stage_type,
      role_id: binding.role_id,
      system_prompt: binding.system_prompt,
      provider_id: binding.provider_id,
    })),
    auto_regression_enabled: draft.auto_regression_enabled,
    max_auto_regression_retries: draft.max_auto_regression_retries,
  });
}
