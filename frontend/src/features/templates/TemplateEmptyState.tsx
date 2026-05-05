import { useEffect, useMemo, useState } from "react";

import type {
  PipelineTemplateRead,
  ProviderRead,
  SessionRead,
  StageType,
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
  onTemplateSaveAs?: (template: PipelineTemplateRead) => void;
  onTemplateOverwrite?: (template: PipelineTemplateRead) => void;
  onTemplateDelete?: (templateId: string) => void;
};

const stageLabels: Record<StageType, string> = {
  requirement_analysis: "Requirement Analysis",
  solution_design: "Solution Design",
  code_generation: "Code Generation",
  test_generation_execution: "Test Generation & Execution",
  code_review: "Code Review",
  delivery_integration: "Delivery Integration",
};

const approvalLabels = {
  solution_design_approval: "Solution Design approval",
  code_review_approval: "Code Review approval",
} as const;

export function TemplateEmptyState({
  session,
  templates,
  providers = [],
  selectedTemplateId,
  onTemplateChange,
  onTemplateSaveAs,
  onTemplateOverwrite,
  onTemplateDelete,
}: TemplateEmptyStateProps): JSX.Element {
  const [localTemplates, setLocalTemplates] = useState(templates);
  const [localCreatedTemplateIds, setLocalCreatedTemplateIds] = useState<string[]>([]);
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

  function handleSaveAs() {
    if (!selectedTemplate || !draft) {
      return;
    }

    const savedTemplate = buildUserTemplate(selectedTemplate, draft, localTemplates);
    setLocalTemplates((current) => [...current, savedTemplate]);
    setLocalCreatedTemplateIds((current) => [...current, savedTemplate.template_id]);
    setDraft(createTemplateDraft(savedTemplate));
    onTemplateSaveAs?.(savedTemplate);
    onTemplateChange(savedTemplate.template_id);
  }

  function handleOverwrite() {
    if (
      !selectedTemplate ||
      !draft ||
      selectedTemplate.template_source !== "user_template"
    ) {
      return;
    }

    const overwrittenTemplate = {
      ...selectedTemplate,
      ...draft,
      updated_at: new Date(0).toISOString(),
    };
    setLocalTemplates((current) =>
      current.map((template) =>
        template.template_id === selectedTemplate.template_id
          ? overwrittenTemplate
          : template,
      ),
    );
    setDraft(createTemplateDraft(overwrittenTemplate));
    onTemplateOverwrite?.(overwrittenTemplate);
  }

  function handleDelete() {
    if (!selectedTemplate || selectedTemplate.template_source !== "user_template") {
      return;
    }

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
    onTemplateDelete?.(selectedTemplate.template_id);
    onTemplateChange(nextTemplateId);
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
        disabled={!isDraft}
      />

      {selectedTemplate ? (
        <section className="template-summary" aria-label="Selected template summary">
          <div className="template-summary__header">
            <span>{selectedTemplate.template_source.replace("_", " ")}</span>
            <strong>
              {selectedTemplate.auto_regression_enabled
                ? `${selectedTemplate.max_auto_regression_retries} auto regression retry`
                : "Auto regression off"}
            </strong>
          </div>
          <ol className="template-stage-list">
            {selectedTemplate.fixed_stage_sequence.map((stageType) => (
              <li key={stageType}>{stageLabels[stageType]}</li>
            ))}
          </ol>
          <div className="template-approvals" aria-label="Approval checkpoints">
            {selectedTemplate.approval_checkpoints.map((approvalType) => (
              <span key={approvalType}>{approvalLabels[approvalType]}</span>
            ))}
          </div>
        </section>
      ) : null}

      {selectedTemplate && draft && isDraft ? (
        <TemplateEditor
          template={selectedTemplateDraftSource ?? selectedTemplate}
          providers={providers}
          draft={draft}
          onDraftChange={setDraft}
          onSaveAs={handleSaveAs}
          onOverwrite={handleOverwrite}
          onDelete={handleDelete}
          onDiscard={resetDraft}
        />
      ) : null}
    </article>
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
    template_id: createSaveAsTemplateId(sourceTemplate.template_id, templates),
    template_source: "user_template",
    base_template_id:
      sourceTemplate.template_source === "system_template"
        ? sourceTemplate.template_id
        : sourceTemplate.base_template_id,
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
