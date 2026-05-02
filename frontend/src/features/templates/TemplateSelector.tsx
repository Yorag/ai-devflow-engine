import type { PipelineTemplateRead } from "../../api/types";

type TemplateSelectorProps = {
  templates: PipelineTemplateRead[];
  selectedTemplateId: string;
  onTemplateChange: (templateId: string) => void;
  disabled?: boolean;
};

export function TemplateSelector({
  templates,
  selectedTemplateId,
  onTemplateChange,
  disabled = false,
}: TemplateSelectorProps): JSX.Element {
  return (
    <fieldset className="template-selector" aria-label="Pipeline templates">
      <legend>Templates</legend>
      <div className="template-selector__options">
        {templates.map((template) => {
          const description = template.description ?? "No description";

          return (
            <label className="template-option" key={template.template_id}>
              <input
                type="radio"
                name="pipeline-template"
                value={template.template_id}
                checked={template.template_id === selectedTemplateId}
                disabled={disabled}
                onChange={() => onTemplateChange(template.template_id)}
              />
              <span>
                <strong>{template.name}</strong>
                <small>{description}</small>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
