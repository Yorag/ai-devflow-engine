import { describe, expect, it } from "vitest";

import type { ComposerStateProjection, StageType } from "../../../api/types";
import {
  canSendMessage,
  resolveComposerActionLabel,
  resolveComposerState,
} from "../composer-state";

function buildComposerState(
  overrides: Partial<ComposerStateProjection>,
): ComposerStateProjection {
  return {
    mode: "draft",
    is_input_enabled: true,
    primary_action: "send",
    secondary_actions: [],
    bound_run_id: "run-current",
    ...overrides,
  };
}

function resolve(
  composerState: Partial<ComposerStateProjection>,
  currentStageType: StageType | null,
) {
  return resolveComposerState(buildComposerState(composerState), currentStageType);
}

describe("resolveComposerState", () => {
  it("keeps draft and waiting clarification sendable", () => {
    expect(resolve({ mode: "draft", primary_action: "send" }, null)).toMatchObject({
      lifecycle: "send",
      canSend: true,
      actionLabel: "发送",
      inputEnabled: true,
    });

    expect(
      resolve(
        {
          mode: "waiting_clarification",
          primary_action: "send",
          secondary_actions: ["pause", "terminate"],
        },
        "requirement_analysis",
      ),
    ).toMatchObject({
      lifecycle: "send",
      canSend: true,
      actionLabel: "发送",
      inputEnabled: true,
    });
  });

  it("shows pause semantics for active requirement analysis and later formal runtime states", () => {
    expect(
      resolve({ mode: "running", primary_action: "pause" }, "requirement_analysis"),
    ).toMatchObject({
      lifecycle: "pause",
      canSend: false,
      actionLabel: "暂停",
      inputEnabled: false,
    });

    expect(
      resolve(
        { mode: "waiting_approval", primary_action: "pause" },
        "solution_design",
      ),
    ).toMatchObject({
      lifecycle: "pause",
      canSend: false,
      actionLabel: "暂停",
      inputEnabled: false,
    });

    expect(
      resolve(
        { mode: "waiting_tool_confirmation", primary_action: "pause" },
        "code_generation",
      ),
    ).toMatchObject({
      lifecycle: "pause",
      canSend: false,
      actionLabel: "暂停",
      inputEnabled: false,
    });
  });

  it("shows resume for paused and disabled for terminal lifecycle states", () => {
    expect(
      resolve({ mode: "paused", primary_action: "resume" }, "solution_design"),
    ).toMatchObject({
      lifecycle: "resume",
      canSend: false,
      actionLabel: "恢复",
      inputEnabled: false,
    });

    expect(
      resolve({ mode: "readonly", primary_action: "disabled" }, "delivery_integration"),
    ).toMatchObject({
      lifecycle: "disabled",
      canSend: false,
      actionLabel: "不可用",
      inputEnabled: false,
    });
  });

  it("fails closed when sendable modes contradict action or input flags", () => {
    expect(
      resolve(
        {
          mode: "draft",
          is_input_enabled: false,
          primary_action: "send",
        },
        null,
      ),
    ).toMatchObject({
      lifecycle: "disabled",
      canSend: false,
      actionLabel: "不可用",
      inputEnabled: false,
      messageType: null,
    });

    expect(
      resolve(
        {
          mode: "waiting_clarification",
          is_input_enabled: true,
          primary_action: "disabled",
        },
        "requirement_analysis",
      ),
    ).toMatchObject({
      lifecycle: "disabled",
      canSend: false,
      actionLabel: "不可用",
      inputEnabled: false,
      messageType: null,
    });
  });

  it("prioritizes terminal disabled projection over contradictory resume actions", () => {
    expect(
      resolve(
        {
          mode: "readonly",
          is_input_enabled: true,
          primary_action: "resume",
        },
        "delivery_integration",
      ),
    ).toMatchObject({
      lifecycle: "disabled",
      canSend: false,
      actionLabel: "不可用",
      inputEnabled: false,
      messageType: null,
    });
  });
});

describe("composer-state helpers", () => {
  it("maps lifecycle actions to labels", () => {
    expect(resolveComposerActionLabel("send")).toBe("发送");
    expect(resolveComposerActionLabel("pause")).toBe("暂停");
    expect(resolveComposerActionLabel("resume")).toBe("恢复");
    expect(resolveComposerActionLabel("disabled")).toBe("不可用");
  });

  it("only allows send when the resolved lifecycle is send", () => {
    expect(
      canSendMessage(
        buildComposerState({ mode: "draft", primary_action: "send" }),
        null,
      ),
    ).toBe(true);
    expect(
      canSendMessage(
        buildComposerState({ mode: "waiting_approval", primary_action: "pause" }),
        "solution_design",
      ),
    ).toBe(false);
  });
});
