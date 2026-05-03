import type { ComposerStateProjection, StageType } from "../../api/types";
import {
  canSendMessage,
  resolveComposerActionLabel,
  resolveComposerState,
} from "./composer-state";

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
  const resolved = resolveComposerState(composerState, currentStageType);
  switch (resolved.mode) {
    case "draft":
      return {
        mode: "draft",
        canSend: true,
        messageType: "new_requirement",
        buttonLabel: "发送",
      };
    case "waiting_clarification":
      return {
        mode: "waiting_clarification",
        canSend: true,
        messageType: "clarification_reply",
        buttonLabel: "发送",
      };
    case "running_requirement_analysis":
      return {
        mode: "running_requirement_analysis",
        canSend: false,
        messageType: null,
        buttonLabel: "暂停",
      };
    case "paused":
      return {
        mode: "paused",
        canSend: false,
        messageType: null,
        buttonLabel: "恢复",
      };
    case "readonly":
      return {
        mode: "readonly",
        canSend: false,
        messageType: null,
        buttonLabel: "不可用",
      };
    case "control_only":
    default:
      return {
        mode: "control_only",
        canSend: false,
        messageType: null,
        buttonLabel: "暂停",
      };
  }
}

export function canSubmitComposerMessage(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): boolean {
  return canSendMessage(composerState, currentStageType);
}

export function getComposerButtonLabel(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): string {
  return resolveComposerActionLabel(
    resolveComposerState(composerState, currentStageType).lifecycle,
  );
}

export function getComposerHelperText(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): string {
  const resolved = resolveComposerState(composerState, currentStageType);

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
