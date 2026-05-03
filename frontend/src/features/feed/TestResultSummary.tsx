import type { StageItemProjection } from "../../api/types";

type TestMetricItem = {
  label: string;
  value: number;
  suffix?: string;
};

export function TestResultSummary({
  metrics,
  resultItem,
}: {
  metrics: Record<string, unknown>;
  resultItem: StageItemProjection | null;
}): JSX.Element | null {
  const metricItems = [
    { label: "Generated Tests", value: metrics.generated_test_count },
    { label: "Executed Tests", value: metrics.executed_test_count },
    { label: "Passed Tests", value: metrics.passed_test_count },
    { label: "Failed Tests", value: metrics.failed_test_count },
    { label: "Skipped Tests", value: metrics.skipped_test_count },
    { label: "Test Gaps", value: metrics.test_gap_count, suffix: "gap" },
  ].filter(isTestMetricItem);
  const hasResultContent = Boolean(resultItem?.summary || resultItem?.content);

  if (metricItems.length === 0 && !hasResultContent) {
    return null;
  }

  return (
    <section className="test-result-summary" aria-label="Test result summary">
      {metricItems.length > 0 ? (
        <div className="test-result-summary__grid">
          {metricItems.map((item) => (
            <Metric
              label={item.label}
              value={item.value}
              suffix={item.suffix}
              key={item.label}
            />
          ))}
        </div>
      ) : null}
      {resultItem?.summary ? <p>{resultItem.summary}</p> : null}
      {resultItem?.content ? (
        <details className="stage-node-item__details">
          <summary>Test detail excerpt</summary>
          <pre>{resultItem.content}</pre>
        </details>
      ) : null}
    </section>
  );
}

function isTestMetricItem(item: {
  label: string;
  value: unknown;
  suffix?: string;
}): item is TestMetricItem {
  return typeof item.value === "number";
}

function Metric({
  label,
  value,
  suffix,
}: {
  label: string;
  value: number;
  suffix?: string;
}): JSX.Element {
  const formattedValue = new Intl.NumberFormat("en-US").format(value);
  return (
    <div className="stage-node-item__datum">
      <strong>{label}</strong>
      <span>{suffix ? `${formattedValue} ${suffix}` : formattedValue}</span>
    </div>
  );
}
