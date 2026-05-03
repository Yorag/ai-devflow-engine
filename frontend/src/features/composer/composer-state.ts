import type { ComposerStateProjection, StageType } from "../../api/types";

export type ComposerLifecycleAction = "send" | "pause" | "resume" | "disabled";

export type ResolvedComposerState = {
  lifecycle: ComposerLifecycleAction;
  canSend: boolean;
  inputEnabled: boolean;
  actionLabel: "发送" | "暂停" | "恢复" | "不可用";
  messageType: "new_requirement" | "clarification_reply" | null;
  mode:
    | "draft"
    | "waiting_clarification"
    | "running_requirement_analysis"
    | "control_only"
    | "paused"
    | "readonly";
};

export function resolveComposerActionLabel(
  action: ComposerLifecycleAction,
): ResolvedComposerState["actionLabel"] {
  switch (action) {
    case "send":
      return "发送";
    case "pause":
      return "暂停";
    case "resume":
      return "恢复";
    case "disabled":
      return "不可用";
  }
}

export function resolveComposerState(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): ResolvedComposerState {
  if (!composerState) {
    return buildResolvedState("disabled", null, "readonly");
  }

  if (composerState.mode === "readonly" || composerState.primary_action === "disabled") {
    return buildResolvedState("disabled", null, "readonly");
  }

  if (composerState.mode === "draft") {
    return composerState.is_input_enabled && composerState.primary_action === "send"
      ? buildResolvedState("send", "new_requirement", "draft")
      : buildResolvedState("disabled", null, "readonly");
  }

  if (composerState.mode === "waiting_clarification") {
    return composerState.is_input_enabled && composerState.primary_action === "send"
      ? buildResolvedState(
          "send",
          "clarification_reply",
          "waiting_clarification",
        )
      : buildResolvedState("disabled", null, "readonly");
  }

  if (composerState.mode === "paused" || composerState.primary_action === "resume") {
    return buildResolvedState("resume", null, "paused");
  }

  if (composerState.mode === "running" && currentStageType === "requirement_analysis") {
    return buildResolvedState("pause", null, "running_requirement_analysis");
  }

  return buildResolvedState("pause", null, "control_only");
}

export function canSendMessage(
  composerState: ComposerStateProjection | null,
  currentStageType: StageType | null,
): boolean {
  return resolveComposerState(composerState, currentStageType).canSend;
}

function buildResolvedState(
  lifecycle: ComposerLifecycleAction,
  messageType: ResolvedComposerState["messageType"],
  mode: ResolvedComposerState["mode"],
): ResolvedComposerState {
  return {
    lifecycle,
    canSend: lifecycle === "send",
    inputEnabled: lifecycle === "send",
    actionLabel: resolveComposerActionLabel(lifecycle),
    messageType,
    mode,
  };
}
