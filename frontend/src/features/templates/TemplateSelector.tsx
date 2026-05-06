import type { PipelineTemplateRead } from "../../api/types";

type TemplateSelectorProps = {
  templates: PipelineTemplateRead[];
  selectedTemplateId: string;
  onTemplateChange: (templateId: string) => void;
  disabledTemplateIds?: string[];
  disabled?: boolean;
};

export function TemplateSelector({
  templates,
  selectedTemplateId,
  onTemplateChange,
  disabledTemplateIds = [],
  disabled = false,
}: TemplateSelectorProps): JSX.Element {
  const disabledIds = new Set(disabledTemplateIds);

  return (
    <fieldset
      className="template-selector template-selector--compact"
      aria-label="Pipeline templates"
    >
      <legend>Templates</legend>
      <div className="template-selector__options">
        {templates.map((template) => (
          <label className="template-option" key={template.template_id}>
            <input
              type="radio"
              name="pipeline-template"
              value={template.template_id}
              checked={template.template_id === selectedTemplateId}
              disabled={disabled || disabledIds.has(template.template_id)}
              onChange={() => onTemplateChange(template.template_id)}
            />
            <span>
              <strong>{template.name}</strong>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
