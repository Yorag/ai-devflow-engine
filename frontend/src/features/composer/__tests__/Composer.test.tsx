import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiRequestOptions } from "../../../api/client";
import type {
  ComposerStateProjection,
  SessionWorkspaceProjection,
} from "../../../api/types";
import { createQueryClient } from "../../../app/query-client";
import { mockSessionWorkspaces } from "../../../mocks/fixtures";
import {
  createMockApiFetcher,
  mockApiRequestOptions,
} from "../../../mocks/handlers";
import { Composer } from "../Composer";
import {
  canSubmitComposerMessage,
  getComposerHelperText,
  resolveComposerMode,
} from "../composer-mode";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function getComposerState(
  sessionId: keyof typeof mockSessionWorkspaces,
): ComposerStateProjection {
  return mockSessionWorkspaces[sessionId].composer_state;
}

function renderComposerForWorkspace(
  workspace: SessionWorkspaceProjection,
  request: ApiRequestOptions = mockApiRequestOptions,
) {
  const queryClient = createQueryClient();

  return render(
    <QueryClientProvider client={queryClient}>
      <Composer
        session={workspace.session}
        composerState={workspace.composer_state}
        currentStageType={workspace.current_stage_type}
        request={request}
      />
    </QueryClientProvider>,
  );
}

function buildPausedWorkspace(): SessionWorkspaceProjection {
  const base = mockSessionWorkspaces["session-running"];

  return {
    ...base,
    session: {
      ...base.session,
      status: "paused",
      current_run_id: "run-paused",
      latest_stage_type: "solution_design",
    },
    runs: base.runs.map((run) => ({
      ...run,
      run_id: "run-paused",
      status: "paused",
      current_stage_type: "solution_design",
      is_active: true,
    })),
    current_run_id: "run-paused",
    current_stage_type: "solution_design",
    composer_state: {
      ...base.composer_state,
      mode: "paused",
      is_input_enabled: false,
      primary_action: "resume",
      secondary_actions: ["terminate"],
      bound_run_id: "run-paused",
    },
  };
}

describe("composer-mode", () => {
  it("treats draft and waiting clarification as sendable modes", () => {
    expect(resolveComposerMode(getComposerState("session-draft"), null)).toEqual({
      mode: "draft",
      canSend: true,
      messageType: "new_requirement",
      buttonLabel: "发送",
    });

    expect(
      resolveComposerMode(
        getComposerState("session-waiting-clarification"),
        "requirement_analysis",
      ),
    ).toEqual({
      mode: "waiting_clarification",
      canSend: true,
      messageType: "clarification_reply",
      buttonLabel: "发送",
    });
  });

  it("treats running requirement analysis as non-send composer mode with pause presentation", () => {
    expect(
      resolveComposerMode(getComposerState("session-running"), "requirement_analysis"),
    ).toEqual({
      mode: "running_requirement_analysis",
      canSend: false,
      messageType: null,
      buttonLabel: "暂停",
    });
    expect(
      canSubmitComposerMessage(getComposerState("session-running"), "requirement_analysis"),
    ).toBe(false);
    expect(
      getComposerHelperText(getComposerState("session-running"), "requirement_analysis"),
    ).toMatch(/继续分析|继续回复/u);
  });
});

describe("Composer component", () => {
  it("submits a new requirement from draft mode and clears the field", async () => {
    const fetcher = vi.fn(createMockApiFetcher());

    renderComposerForWorkspace(mockSessionWorkspaces["session-draft"], { fetcher });

    fireEvent.change(screen.getByLabelText("当前输入"), {
      target: { value: "Add runtime composer mode." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledWith(
        "/api/sessions/session-draft/messages",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            message_type: "new_requirement",
            content: "Add runtime composer mode.",
          }),
        }),
      );
    });
    expect(screen.getByLabelText("当前输入")).toHaveProperty("value", "");
  });

  it("submits clarification replies in waiting clarification mode", async () => {
    const fetcher = vi.fn(createMockApiFetcher());

    renderComposerForWorkspace(
      mockSessionWorkspaces["session-waiting-clarification"],
      { fetcher },
    );

    fireEvent.change(screen.getByLabelText("当前输入"), {
      target: { value: "Use the current project default provider." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledWith(
        "/api/sessions/session-waiting-clarification/messages",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            message_type: "clarification_reply",
            content: "Use the current project default provider.",
          }),
        }),
      );
    });
  });

  it("disables submit while requirement analysis is still running", () => {
    const workspace = {
      ...mockSessionWorkspaces["session-running"],
      session: {
        ...mockSessionWorkspaces["session-running"].session,
        latest_stage_type: "requirement_analysis" as const,
      },
      current_stage_type: "requirement_analysis" as const,
    };

    renderComposerForWorkspace(workspace);

    const input = screen.getByLabelText("当前输入");
    const button = screen.getByRole("button", { name: "暂停" });
    expect(input).toHaveProperty("disabled", true);
    expect(button).toHaveProperty("disabled", true);
    expect(screen.getByText(/当前输入框不承担发送动作/u)).toBeTruthy();
  });

  it("keeps the lifecycle button bound to the current active run during waiting approval", () => {
    renderComposerForWorkspace(mockSessionWorkspaces["session-waiting-approval"]);

    const button = screen.getByRole("button", { name: "暂停" });
    expect(screen.getByText("绑定 run run-waiting-approval")).toBeTruthy();
    expect(button).toHaveProperty("disabled", true);
    expect(button.getAttribute("type")).toBe("button");
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", true);
  });

  it("shows resume presentation for paused runs without turning the button into send", () => {
    renderComposerForWorkspace(buildPausedWorkspace());

    const button = screen.getByRole("button", { name: "恢复" });
    expect(button).toHaveProperty("disabled", true);
    expect(button.getAttribute("type")).toBe("button");
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", true);
  });

  it("keeps a disabled lifecycle placeholder for completed runs", () => {
    renderComposerForWorkspace(mockSessionWorkspaces["session-completed"]);

    const button = screen.getByRole("button", { name: "不可用" });
    expect(button).toHaveProperty("disabled", true);
    expect(button.getAttribute("type")).toBe("button");
    expect(screen.getByText("绑定 run run-completed")).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", true);
  });

  it("resets unsent local input when the bound session changes", () => {
    const queryClient = createQueryClient();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <Composer
          session={mockSessionWorkspaces["session-draft"].session}
          composerState={mockSessionWorkspaces["session-draft"].composer_state}
          currentStageType={mockSessionWorkspaces["session-draft"].current_stage_type}
          request={mockApiRequestOptions}
        />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText("当前输入"), {
      target: { value: "Leak candidate" },
    });
    expect(screen.getByLabelText("当前输入")).toHaveProperty(
      "value",
      "Leak candidate",
    );

    rerender(
      <QueryClientProvider client={queryClient}>
        <Composer
          session={mockSessionWorkspaces["session-waiting-clarification"].session}
          composerState={
            mockSessionWorkspaces["session-waiting-clarification"].composer_state
          }
          currentStageType={
            mockSessionWorkspaces["session-waiting-clarification"].current_stage_type
          }
          request={mockApiRequestOptions}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText("当前输入")).toHaveProperty("value", "");
  });
});
