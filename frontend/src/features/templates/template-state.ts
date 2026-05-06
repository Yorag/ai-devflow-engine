import { useLayoutEffect, useState } from "react";

import type {
  PipelineTemplateRead,
  PipelineTemplateWriteRequest,
  ProviderRead,
  StageRoleBinding,
} from "../../api/types";

export type TemplateDraftState = Pick<
  PipelineTemplateWriteRequest,
  | "name"
  | "description"
  | "stage_role_bindings"
  | "auto_regression_enabled"
  | "max_auto_regression_retries"
  | "max_react_iterations_per_stage"
  | "max_tool_calls_per_stage"
  | "skip_high_risk_tool_confirmations"
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
    name: template.name,
    description: template.description,
    stage_role_bindings: cloneStageRoleBindings(template.stage_role_bindings),
    auto_regression_enabled: template.auto_regression_enabled,
    max_auto_regression_retries: template.max_auto_regression_retries,
    max_react_iterations_per_stage: Number.isFinite(
      template.max_react_iterations_per_stage,
    )
      ? template.max_react_iterations_per_stage
      : 30,
    max_tool_calls_per_stage: Number.isFinite(template.max_tool_calls_per_stage)
      ? template.max_tool_calls_per_stage
      : 80,
    skip_high_risk_tool_confirmations:
      template.skip_high_risk_tool_confirmations === true,
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
      canStart: true,
      reason:
        "Unsaved edits will not affect this session until you save as a user template.",
      actions: ["save_as", "discard"],
    };
  }

  return {
    canStart: true,
    reason:
      "Unsaved edits will not affect this session until you save the template.",
    actions: ["overwrite", "discard"],
  };
}

export function cloneStageRoleBindings(
  bindings: StageRoleBinding[],
): StageRoleBinding[] {
  return bindings.map((binding) => normalizeStageRoleBinding(binding));
}

export function availableTemplateProviders(providers: ProviderRead[]): ProviderRead[] {
  return providers.filter((provider) => provider.is_enabled);
}

export function resolveTemplateProviderBindings(
  template: PipelineTemplateRead,
  providers: ProviderRead[],
): PipelineTemplateRead {
  const resolvedBindings = resolveStageRoleBindingProviders(
    template.stage_role_bindings,
    providers,
  );

  return resolvedBindings === template.stage_role_bindings
    ? template
    : {
        ...template,
        stage_role_bindings: resolvedBindings,
      };
}

export function resolveTemplateDraftProviders(
  draft: TemplateDraftState,
  providers: ProviderRead[],
): TemplateDraftState {
  const resolvedBindings = resolveStageRoleBindingProviders(
    draft.stage_role_bindings,
    providers,
  );

  return resolvedBindings === draft.stage_role_bindings
    ? draft
    : {
        ...draft,
        stage_role_bindings: resolvedBindings,
      };
}

export function unavailableTemplateProviderIds(
  draft: TemplateDraftState,
  providers: ProviderRead[],
): string[] {
  const availableProviders = availableTemplateProviders(providers);
  if (availableProviders.length === 0) {
    return [];
  }

  const availableProviderIds = new Set(
    availableProviders.map((provider) => provider.provider_id),
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
  return providerIds.length > 0
    ? "This template references unavailable providers."
    : "No provider configured.";
}

function resolveStageRoleBindingProviders(
  bindings: StageRoleBinding[],
  providers: ProviderRead[],
): StageRoleBinding[] {
  const availableProviders = availableTemplateProviders(providers);
  const fallbackProviderId = availableProviders[0]?.provider_id;

  if (!fallbackProviderId) {
    return bindings;
  }

  const availableProviderIds = new Set(
    availableProviders.map((provider) => provider.provider_id),
  );
  let changed = false;
  const resolvedBindings = bindings.map((binding) => {
    if (availableProviderIds.has(binding.provider_id)) {
      return binding;
    }

    changed = true;
    return {
      ...binding,
      provider_id: fallbackProviderId,
    };
  });

  return changed ? resolvedBindings : bindings;
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
    name: draft.name.trim(),
    description: draft.description ?? null,
    stage_role_bindings: draft.stage_role_bindings.map((binding) => ({
      stage_type: binding.stage_type,
      role_id: binding.role_id,
      stage_work_instruction: binding.stage_work_instruction,
      system_prompt: binding.system_prompt,
      provider_id: binding.provider_id,
    })),
    auto_regression_enabled: draft.auto_regression_enabled,
    max_auto_regression_retries: draft.max_auto_regression_retries,
    max_react_iterations_per_stage: draft.max_react_iterations_per_stage,
    max_tool_calls_per_stage: draft.max_tool_calls_per_stage,
    skip_high_risk_tool_confirmations:
      draft.skip_high_risk_tool_confirmations,
  });
}

function normalizeStageRoleBinding(binding: StageRoleBinding): StageRoleBinding {
  const stageWorkInstruction =
    binding.stage_work_instruction || binding.system_prompt;
  return {
    ...binding,
    stage_work_instruction: stageWorkInstruction,
    system_prompt: binding.system_prompt || stageWorkInstruction,
  };
}
