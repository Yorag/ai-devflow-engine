import { useEffect, useState } from "react";

import type {
  PipelineTemplateRead,
  PipelineTemplateWriteRequest,
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

export function createTemplateDraft(
  template: PipelineTemplateRead,
): TemplateDraftState {
  return {
    stage_role_bindings: cloneStageRoleBindings(template.stage_role_bindings),
    auto_regression_enabled: template.auto_regression_enabled,
    max_auto_regression_retries: template.max_auto_regression_retries,
  };
}

export function useTemplateDraftState(template: PipelineTemplateRead | null): {
  draft: TemplateDraftState | null;
  setDraft: (draft: TemplateDraftState) => void;
  resetDraft: () => void;
  dirty: boolean;
} {
  const [draft, setDraft] = useState<TemplateDraftState | null>(
    template ? createTemplateDraft(template) : null,
  );

  useEffect(() => {
    setDraft(template ? createTemplateDraft(template) : null);
  }, [template?.template_id]);

  return {
    draft,
    setDraft,
    resetDraft: () => setDraft(template ? createTemplateDraft(template) : null),
    dirty: Boolean(template && draft && isTemplateDirty(template, draft)),
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
): TemplateStartGuard {
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
