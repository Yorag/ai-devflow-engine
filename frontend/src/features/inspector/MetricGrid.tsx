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
      return "耗时";
    case "input_tokens":
      return "输入 Token";
    case "output_tokens":
      return "输出 Token";
    case "total_tokens":
      return "Token 总量";
    case "attempt_index":
      return "尝试次数";
    case "context_file_count":
      return "上下文文件";
    case "reasoning_step_count":
      return "推理步骤";
    case "tool_call_count":
      return "工具调用";
    case "changed_file_count":
      return "变更文件";
    case "added_line_count":
      return "新增行";
    case "removed_line_count":
      return "删除行";
    case "generated_test_count":
      return "生成测试";
    case "executed_test_count":
      return "执行测试";
    case "passed_test_count":
      return "通过测试";
    case "failed_test_count":
      return "失败测试";
    case "skipped_test_count":
      return "跳过测试";
    case "test_gap_count":
      return "测试缺口";
    case "retry_index":
      return "重试序号";
    case "source_attempt_index":
      return "来源尝试";
    case "delivery_artifact_count":
      return "交付产物";
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
