import type { ComposerStateProjection, StageType } from "../../api/types";

export type ResolvedComposerMode =
  | {
      mode: "draft" | "waiting_clarification";
      canSend: true;
      messageType: "new_requirement" | "clarification_reply";
      buttonLabel: "发送";
    }
  | {
      mode: "running_requirement_analysis" | "paused" | "readonly" | "control_only";
      canSend: false;
      messageType: null;
      buttonLabel: "暂停" | "恢复" | "不可用";
    };

export function resolveComposerMode(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): ResolvedComposerMode {
  if (!composerState) {
    return {
      mode: "readonly",
      canSend: false,
      messageType: null,
      buttonLabel: "不可用",
    };
  }

  if (composerState.mode === "draft") {
    return {
      mode: "draft",
      canSend: true,
      messageType: "new_requirement",
      buttonLabel: "发送",
    };
  }

  if (composerState.mode === "waiting_clarification") {
    return {
      mode: "waiting_clarification",
      canSend: true,
      messageType: "clarification_reply",
      buttonLabel: "发送",
    };
  }

  if (
    composerState.mode === "running" &&
    currentStageType === "requirement_analysis"
  ) {
    return {
      mode: "running_requirement_analysis",
      canSend: false,
      messageType: null,
      buttonLabel: "暂停",
    };
  }

  if (composerState.mode === "paused") {
    return {
      mode: "paused",
      canSend: false,
      messageType: null,
      buttonLabel: "恢复",
    };
  }

  if (composerState.mode === "readonly") {
    return {
      mode: "readonly",
      canSend: false,
      messageType: null,
      buttonLabel: "不可用",
    };
  }

  return {
    mode: "control_only",
    canSend: false,
    messageType: null,
    buttonLabel: "暂停",
  };
}

export function canSubmitComposerMessage(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): boolean {
  return resolveComposerMode(composerState, currentStageType).canSend;
}

export function getComposerButtonLabel(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): string {
  return resolveComposerMode(composerState, currentStageType).buttonLabel;
}

export function getComposerHelperText(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): string {
  const resolved = resolveComposerMode(composerState, currentStageType);

  switch (resolved.mode) {
    case "draft":
      return "输入首条需求后将自动启动当前会话的首个 run。";
    case "waiting_clarification":
      return "当前 run 正在等待你的澄清回复。发送后会继续同一个 Requirement Analysis 回合。";
    case "running_requirement_analysis":
      return "Agent 正在继续分析并准备回复，当前输入框不承担发送动作。";
    case "paused":
      return "当前 run 已暂停，恢复入口由后续运行控制切片接管。";
    case "control_only":
      return "当前阶段以运行控制为主，Composer 不承担聊天输入。";
    case "readonly":
    default:
      return "当前 run 已结束，Composer 仅保留只读占位。";
  }
}
