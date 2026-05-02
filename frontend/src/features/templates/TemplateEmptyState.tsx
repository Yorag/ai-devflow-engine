import type { PipelineTemplateRead, SessionRead, StageType } from "../../api/types";
import { TemplateSelector } from "./TemplateSelector";

type TemplateEmptyStateProps = {
  session: SessionRead;
  templates: PipelineTemplateRead[];
  selectedTemplateId: string;
  onTemplateChange: (templateId: string) => void;
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
  selectedTemplateId,
  onTemplateChange,
}: TemplateEmptyStateProps): JSX.Element {
  const selectedTemplate =
    templates.find((template) => template.template_id === selectedTemplateId) ??
    templates[0] ??
    null;
  const isDraft = session.status === "draft";

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
        templates={templates}
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
    </article>
  );
}
