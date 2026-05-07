import type {
  ApprovalResultFeedEntry,
  MessageFeedEntry,
  StageItemType,
  StageType,
} from "../../api/types";

export const stageLabels: Record<StageType, string> = {
  requirement_analysis: "需求分析",
  solution_design: "方案设计",
  code_generation: "代码生成",
  test_generation_execution: "测试生成与执行",
  code_review: "代码评审",
  delivery_integration: "交付集成",
};

export const stageItemLabels: Record<StageItemType, string> = {
  dialogue: "澄清对话",
  context: "上下文",
  reasoning: "推理记录",
  decision: "决策",
  model_call: "模型调用",
  provider_call: "模型服务调用",
  tool_call: "工具调用",
  tool_confirmation: "工具确认",
  diff_preview: "变更预览",
  result: "阶段结果",
};

const statusLabels: Record<string, string> = {
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  pending: "待审批",
  approved: "已批准",
  rejected: "已退回",
  denied: "已拒绝",
  allowed: "已允许",
  waiting_approval: "等待审批",
  waiting_clarification: "等待澄清",
  paused: "已暂停",
  terminated: "已终止",
  retrying: "重试中",
  succeeded: "成功",
  cancelled: "已取消",
  closed: "关闭",
  open: "打开",
  circuit_open: "熔断打开",
  unknown: "未知",
};

const metricLabels: Record<string, string> = {
  duration_ms: "耗时",
  clarification_rounds: "澄清轮次",
  total_tokens: "Token 总量",
  tool_call_count: "工具调用",
  changed_file_count: "变更文件",
  passed_test_count: "通过测试",
  failed_test_count: "失败测试",
  file_count: "文件数",
};

export function formatStatusLabel(value: string): string {
  return statusLabels[value] ?? formatLabel(value);
}

export function formatMetricLabel(value: string): string {
  return metricLabels[value] ?? formatLabel(value);
}

export function formatAuthor(author: MessageFeedEntry["author"]): string {
  return author === "user" ? "用户" : formatLabel(author);
}

export function formatApprovalType(
  value: ApprovalResultFeedEntry["approval_type"],
): string {
  return value === "solution_design_approval" ? "方案设计审批" : "代码评审审批";
}

export function formatBoolean(value: boolean): string {
  return value ? "是" : "否";
}

export function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
