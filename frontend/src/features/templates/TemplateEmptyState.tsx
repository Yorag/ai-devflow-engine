import { useEffect, useMemo, useState } from "react";

import type {
  PipelineTemplateRead,
  ProviderRead,
  SessionRead,
} from "../../api/types";
import { TemplateEditor } from "./TemplateEditor";
import { TemplateSelector } from "./TemplateSelector";
import {
  createTemplateDraft,
  resolveTemplateProviderBindings,
  resolveTemplateDraftProviders,
  useTemplateDraftState,
  type TemplateDraftState,
} from "./template-state";

type TemplateEmptyStateProps = {
  session: SessionRead;
  templates: PipelineTemplateRead[];
  providers?: ProviderRead[];
  selectedTemplateId: string;
  onTemplateChange: (templateId: string) => void;
  isTemplateChangeBusy?: boolean;
  onTemplateSaveAs?: (
    template: PipelineTemplateRead,
    sourceTemplate: PipelineTemplateRead,
    draft: TemplateDraftState,
  ) => unknown | Promise<unknown>;
  onTemplateUse?: (template: PipelineTemplateRead) => unknown | Promise<unknown>;
  onTemplateOverwrite?: (
    template: PipelineTemplateRead,
    sourceTemplate: PipelineTemplateRead,
    draft: TemplateDraftState,
  ) => unknown | Promise<unknown>;
  onTemplateDelete?: (templateId: string) => void | Promise<void>;
};

export function TemplateEmptyState({
  session,
  templates,
  providers = [],
  selectedTemplateId,
  onTemplateChange,
  isTemplateChangeBusy = false,
  onTemplateSaveAs,
  onTemplateUse,
  onTemplateOverwrite,
  onTemplateDelete,
}: TemplateEmptyStateProps): JSX.Element {
  const [localTemplates, setLocalTemplates] = useState(templates);
  const [localCreatedTemplateIds, setLocalCreatedTemplateIds] = useState<string[]>([]);
  const [templateSaveError, setTemplateSaveError] = useState<unknown | null>(null);
  const [isTemplateSaveBusy, setTemplateSaveBusy] = useState(false);
  const selectedTemplate =
    localTemplates.find((template) => template.template_id === selectedTemplateId) ??
    localTemplates[0] ??
    null;
  const selectedTemplateDraftSource = useMemo(
    () =>
      selectedTemplate
        ? resolveTemplateProviderBindings(selectedTemplate, providers)
        : null,
    [selectedTemplate, providers],
  );
  const isDraft = session.status === "draft";
  const { draft, setDraft, resetDraft } = useTemplateDraftState(
    selectedTemplateDraftSource,
    session.session_id,
  );

  useEffect(() => {
    setLocalTemplates((current) =>
      mergeIncomingTemplates(templates, current, localCreatedTemplateIds),
    );
  }, [templates, localCreatedTemplateIds]);

  useEffect(() => {
    if (!draft) {
      return;
    }

    const resolvedDraft = resolveTemplateDraftProviders(draft, providers);
    if (resolvedDraft !== draft) {
      setDraft(resolvedDraft);
    }
  }, [draft, providers, setDraft]);

  async function handleSaveAs() {
    if (!selectedTemplate || !draft) {
      return;
    }

    setTemplateSaveBusy(true);
    setTemplateSaveError(null);
    try {
      const localTemplate = buildUserTemplate(
        selectedTemplate,
        draft,
        localTemplates,
      );
      const saveResult = await onTemplateSaveAs?.(
        localTemplate,
        selectedTemplate,
        draft,
      );
      const savedTemplate = isPipelineTemplateRead(saveResult)
        ? saveResult
        : localTemplate;
      setLocalTemplates((current) => upsertTemplate(current, savedTemplate));
      if (!templates.some((template) => template.template_id === savedTemplate.template_id)) {
        setLocalCreatedTemplateIds((current) =>
          current.includes(savedTemplate.template_id)
            ? current
            : [...current, savedTemplate.template_id],
        );
      }
      setDraft(createTemplateDraft(savedTemplate));
    } catch (error) {
      setTemplateSaveError(error);
    } finally {
      setTemplateSaveBusy(false);
    }
  }

  async function handleUse() {
    if (!selectedTemplate) {
      return;
    }

    setTemplateSaveBusy(true);
    setTemplateSaveError(null);
    try {
      await onTemplateUse?.(selectedTemplate);
    } catch (error) {
      setTemplateSaveError(error);
    } finally {
      setTemplateSaveBusy(false);
    }
  }

  async function handleOverwrite() {
    if (
      !selectedTemplate ||
      !draft ||
      selectedTemplate.template_source !== "user_template"
    ) {
      return;
    }

    setTemplateSaveBusy(true);
    setTemplateSaveError(null);
    try {
      const localTemplate = {
        ...selectedTemplate,
        ...draft,
        name: draft.name.trim(),
        updated_at: new Date(0).toISOString(),
      };
      const overwriteResult = await onTemplateOverwrite?.(
        localTemplate,
        selectedTemplate,
        draft,
      );
      const overwrittenTemplate = isPipelineTemplateRead(overwriteResult)
        ? overwriteResult
        : localTemplate;
      setLocalTemplates((current) => upsertTemplate(current, overwrittenTemplate));
      setDraft(createTemplateDraft(overwrittenTemplate));
    } catch (error) {
      setTemplateSaveError(error);
    } finally {
      setTemplateSaveBusy(false);
    }
  }

  async function handleDelete() {
    if (!selectedTemplate || selectedTemplate.template_source !== "user_template") {
      return;
    }

    setTemplateSaveBusy(true);
    setTemplateSaveError(null);
    try {
      await onTemplateDelete?.(selectedTemplate.template_id);
      const remainingTemplates = localTemplates.filter(
        (template) => template.template_id !== selectedTemplate.template_id,
      );
      const nextTemplateId = resolveDeleteFallbackTemplateId(
        selectedTemplate,
        remainingTemplates,
      );

      setLocalTemplates(remainingTemplates);
      setLocalCreatedTemplateIds((current) =>
        current.filter((templateId) => templateId !== selectedTemplate.template_id),
      );
      onTemplateChange(nextTemplateId);
    } catch (error) {
      setTemplateSaveError(error);
    } finally {
      setTemplateSaveBusy(false);
    }
  }

  return (
    <article
      className="template-empty-state"
      aria-label="Template empty state"
      role="region"
    >
      <div className="template-empty-state__intro">
        <p className="workspace-eyebrow">Narrative Workspace</p>
        <h1>{selectedTemplate?.name ?? "No template selected"}</h1>
        <p>
          {selectedTemplate?.description ??
            "Select a pipeline template before the first requirement starts."}
        </p>
      </div>

      <TemplateSelector
        templates={localTemplates}
        selectedTemplateId={selectedTemplate?.template_id ?? ""}
        onTemplateChange={onTemplateChange}
        disabledTemplateIds={localCreatedTemplateIds}
        disabled={!isDraft || isTemplateChangeBusy}
      />

      {selectedTemplate && draft && isDraft ? (
        <TemplateEditor
          template={selectedTemplate}
          providers={providers}
          draft={draft}
          onDraftChange={setDraft}
          onUse={handleUse}
          onSaveAs={handleSaveAs}
          onOverwrite={handleOverwrite}
          onDelete={handleDelete}
          onDiscard={resetDraft}
          isSaving={isTemplateSaveBusy}
          error={templateSaveError}
        />
      ) : null}
    </article>
  );
}

function isPipelineTemplateRead(value: unknown): value is PipelineTemplateRead {
  return (
    Boolean(value) &&
    typeof value === "object" &&
    typeof (value as Partial<PipelineTemplateRead>).template_id === "string" &&
    Array.isArray((value as Partial<PipelineTemplateRead>).stage_role_bindings)
  );
}

function buildUserTemplate(
  sourceTemplate: PipelineTemplateRead,
  draft: TemplateDraftState,
  templates: PipelineTemplateRead[],
): PipelineTemplateRead {
  return {
    ...sourceTemplate,
    ...draft,
    name: draft.name.trim(),
    template_id: createSaveAsTemplateId(sourceTemplate.template_id, templates),
    template_source: "user_template",
    base_template_id: sourceTemplate.template_id,
    created_at: new Date(0).toISOString(),
    updated_at: new Date(0).toISOString(),
  };
}

function createSaveAsTemplateId(
  sourceTemplateId: string,
  templates: PipelineTemplateRead[],
): string {
  const existingIds = new Set(templates.map((template) => template.template_id));
  let nextIndex = 1;
  let nextId = `template-user-${sourceTemplateId}-${nextIndex}`;

  while (existingIds.has(nextId)) {
    nextIndex += 1;
    nextId = `template-user-${sourceTemplateId}-${nextIndex}`;
  }

  return nextId;
}

function mergeIncomingTemplates(
  incomingTemplates: PipelineTemplateRead[],
  currentTemplates: PipelineTemplateRead[],
  localCreatedTemplateIds: string[],
): PipelineTemplateRead[] {
  const incomingIds = new Set(incomingTemplates.map((template) => template.template_id));
  const localTemplates = currentTemplates.filter(
    (template) =>
      localCreatedTemplateIds.includes(template.template_id) &&
      !incomingIds.has(template.template_id),
  );

  return [...incomingTemplates, ...localTemplates];
}

function upsertTemplate(
  templates: PipelineTemplateRead[],
  savedTemplate: PipelineTemplateRead,
): PipelineTemplateRead[] {
  return templates.some((template) => template.template_id === savedTemplate.template_id)
    ? templates.map((template) =>
        template.template_id === savedTemplate.template_id ? savedTemplate : template,
      )
    : [...templates, savedTemplate];
}

function resolveDeleteFallbackTemplateId(
  deletedTemplate: PipelineTemplateRead,
  remainingTemplates: PipelineTemplateRead[],
): string {
  return (
    remainingTemplates.find(
      (template) => template.template_id === deletedTemplate.base_template_id,
    )?.template_id ??
    remainingTemplates.find((template) => template.template_id === "template-feature")
      ?.template_id ??
    remainingTemplates[0]?.template_id ??
    ""
  );
}
