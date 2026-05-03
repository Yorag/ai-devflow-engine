import type { MetricSet } from "../../api/types";

type MetricEntry = {
  key: keyof MetricSet;
  label: string;
  value: string;
};

const metricOrder: Array<keyof MetricSet> = [
  "duration_ms",
  "input_tokens",
  "output_tokens",
  "total_tokens",
  "attempt_index",
  "context_file_count",
  "reasoning_step_count",
  "tool_call_count",
  "changed_file_count",
  "added_line_count",
  "removed_line_count",
  "generated_test_count",
  "executed_test_count",
  "passed_test_count",
  "failed_test_count",
  "skipped_test_count",
  "test_gap_count",
  "retry_index",
  "source_attempt_index",
  "delivery_artifact_count",
];

const numberFormatter = new Intl.NumberFormat("en-US");

export function MetricGrid({
  metrics,
}: {
  metrics: MetricSet;
}): JSX.Element | null {
  const entries = getVisibleMetricEntries(metrics);
  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="inspector-metric-grid">
      {entries.map((entry) => (
        <div className="inspector-metric-grid__item" key={entry.key}>
          <span>{entry.label}</span>
          <strong>{entry.value}</strong>
        </div>
      ))}
    </div>
  );
}

export function getVisibleMetricEntries(metrics: MetricSet): MetricEntry[] {
  return metricOrder.flatMap((key) => {
    const rawValue = metrics[key];
    if (rawValue === undefined || rawValue === null) {
      return [];
    }

    return [
      {
        key,
        label: formatMetricLabel(key),
        value: formatMetricValue(key, rawValue),
      },
    ];
  });
}

function formatMetricLabel(key: keyof MetricSet): string {
  switch (key) {
    case "duration_ms":
      return "Duration";
    case "input_tokens":
      return "Input Tokens";
    case "output_tokens":
      return "Output Tokens";
    case "total_tokens":
      return "Total Tokens";
    case "attempt_index":
      return "Attempt";
    case "context_file_count":
      return "Context Files";
    case "reasoning_step_count":
      return "Reasoning Steps";
    case "tool_call_count":
      return "Tool Calls";
    case "changed_file_count":
      return "Changed Files";
    case "added_line_count":
      return "Added Lines";
    case "removed_line_count":
      return "Removed Lines";
    case "generated_test_count":
      return "Generated Tests";
    case "executed_test_count":
      return "Executed Tests";
    case "passed_test_count":
      return "Passed Tests";
    case "failed_test_count":
      return "Failed Tests";
    case "skipped_test_count":
      return "Skipped Tests";
    case "test_gap_count":
      return "Test Gaps";
    case "retry_index":
      return "Retry Index";
    case "source_attempt_index":
      return "Source Attempt";
    case "delivery_artifact_count":
      return "Delivery Artifact Count";
  }
}

function formatMetricValue(key: keyof MetricSet, value: number): string {
  if (key === "duration_ms") {
    return formatDuration(value);
  }

  return numberFormatter.format(value);
}

function formatDuration(value: number): string {
  if (value >= 60_000) {
    const totalSeconds = Math.round(value / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
  }

  if (value >= 1000) {
    return `${Number((value / 1000).toFixed(1))}s`;
  }

  return `${value}ms`;
}
