import type {
  ControlItemInspectorProjection,
  DeliveryResultDetailProjection,
  InspectorSection,
  JsonObject,
  SolutionImplementationPlanRead,
  StageInspectorProjection,
  ToolConfirmationInspectorProjection,
} from "../../api/types";
import { MetricGrid, getVisibleMetricEntries } from "./MetricGrid";

export type InspectorDetail =
  | StageInspectorProjection
  | ControlItemInspectorProjection
  | ToolConfirmationInspectorProjection
  | DeliveryResultDetailProjection;

type SectionConfig = {
  key: "identity" | "input" | "process" | "output" | "artifacts";
  title: string;
  section: InspectorSection;
};

export function InspectorSections({
  detail,
}: {
  detail: InspectorDetail;
}): JSX.Element {
  const stageExtras = getStageExtras(detail);
  const sections: SectionConfig[] = [
    { key: "identity", title: "Identity", section: detail.identity },
    { key: "input", title: "Input", section: detail.input },
    { key: "process", title: "Process", section: detail.process },
    { key: "output", title: "Output", section: detail.output },
    { key: "artifacts", title: "Artifacts", section: detail.artifacts },
  ];
  const hasMetrics = getVisibleMetricEntries(detail.metrics).length > 0;

  return (
    <>
      {sections.map(({ key, title, section }) =>
        shouldRenderSection(key, section, stageExtras) ? (
          <section className="inspector-panel__section" aria-label={title} key={key}>
            <h3>{title}</h3>
            <div className="inspector-section__records">
              {renderSectionRecords(section.records)}
              {renderRefList("Stable refs", section.stable_refs)}
              {renderRefList("Log refs", section.log_refs)}
              {section.truncated ? (
                <p className="inspector-section__meta">Content truncated</p>
              ) : null}
              {section.redaction_status !== "none" ? (
                <p className="inspector-section__meta">
                  Redaction: {section.redaction_status}
                </p>
              ) : null}
              {key === "output" && stageExtras.implementationPlan ? (
                <ImplementationPlanBlock plan={stageExtras.implementationPlan} />
              ) : null}
              {key === "process"
                ? renderRefList(
                    "Tool confirmation traces",
                    stageExtras.toolConfirmationTraceRefs,
                  )
                : null}
              {key === "process"
                ? renderRefList(
                    "Provider retry traces",
                    stageExtras.providerRetryTraceRefs,
                  )
                : null}
              {key === "process"
                ? renderRefList(
                    "Provider circuit-breaker traces",
                    stageExtras.providerCircuitBreakerTraceRefs,
                  )
                : null}
              {key === "artifacts"
                ? renderRefList("Approval result refs", stageExtras.approvalResultRefs)
                : null}
            </div>
          </section>
        ) : null,
      )}
      {hasMetrics ? (
        <section className="inspector-panel__section" aria-label="Metrics">
          <h3>Metrics</h3>
          <MetricGrid metrics={detail.metrics} />
        </section>
      ) : null}
    </>
  );
}

function renderSectionRecords(records: JsonObject): JSX.Element[] {
  return Object.entries(records).map(([key, value]) => (
    <div className="inspector-record" key={key}>
      <strong>{formatLabel(key)}</strong>
      {renderValue(value)}
    </div>
  ));
}

function renderValue(value: unknown): JSX.Element {
  if (typeof value === "string") {
    if (value.includes("\n") || value.length > 120) {
      return (
        <pre className="inspector-record__code">
          <code>{value}</code>
        </pre>
      );
    }

    return <span className="inspector-record__text">{value}</span>;
  }

  if (Array.isArray(value)) {
    if (value.every((item) => typeof item !== "object" || item === null)) {
      return (
        <ul className="inspector-ref-list">
          {value.map((item, index) => (
            <li key={`${String(item)}-${index}`}>{String(item)}</li>
          ))}
        </ul>
      );
    }

    return (
      <pre className="inspector-record__code">
        <code>{JSON.stringify(value, null, 2)}</code>
      </pre>
    );
  }

  if (value && typeof value === "object") {
    return (
      <pre className="inspector-record__code">
        <code>{JSON.stringify(value, null, 2)}</code>
      </pre>
    );
  }

  return <span className="inspector-record__text">{String(value)}</span>;
}

function renderRefList(title: string, refs: string[]): JSX.Element | null {
  if (refs.length === 0) {
    return null;
  }

  return (
    <div className="inspector-record">
      <strong>{title}</strong>
      <ul className="inspector-ref-list">
        {refs.map((ref) => (
          <li key={ref}>{ref}</li>
        ))}
      </ul>
    </div>
  );
}

function shouldRenderSection(
  key: SectionConfig["key"],
  section: InspectorSection,
  extras: ReturnType<typeof getStageExtras>,
): boolean {
  if (hasSectionContent(section)) {
    return true;
  }

  if (key === "output" && extras.implementationPlan) {
    return true;
  }

  if (
    key === "process" &&
    (extras.toolConfirmationTraceRefs.length > 0 ||
      extras.providerRetryTraceRefs.length > 0 ||
      extras.providerCircuitBreakerTraceRefs.length > 0)
  ) {
    return true;
  }

  if (key === "artifacts" && extras.approvalResultRefs.length > 0) {
    return true;
  }

  return false;
}

function hasSectionContent(section: InspectorSection): boolean {
  return (
    Object.keys(section.records).length > 0 ||
    section.stable_refs.length > 0 ||
    section.log_refs.length > 0 ||
    section.truncated ||
    section.redaction_status !== "none"
  );
}

function getStageExtras(detail: InspectorDetail) {
  if (!("implementation_plan" in detail)) {
    return {
      implementationPlan: null,
      toolConfirmationTraceRefs: [],
      providerRetryTraceRefs: [],
      providerCircuitBreakerTraceRefs: [],
      approvalResultRefs: [],
    };
  }

  return {
    implementationPlan: detail.implementation_plan,
    toolConfirmationTraceRefs: detail.tool_confirmation_trace_refs,
    providerRetryTraceRefs: detail.provider_retry_trace_refs,
    providerCircuitBreakerTraceRefs: detail.provider_circuit_breaker_trace_refs,
    approvalResultRefs: detail.approval_result_refs,
  };
}

function ImplementationPlanBlock({
  plan,
}: {
  plan: SolutionImplementationPlanRead;
}): JSX.Element {
  return (
    <div className="inspector-record">
      <strong>Implementation plan</strong>
      <div className="inspector-plan-block">
        <p>{plan.plan_id}</p>
        <ul className="inspector-ref-list">
          {plan.tasks.map((task) => (
            <li key={task.task_id}>{task.title}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
