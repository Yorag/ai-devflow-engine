import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/query-client";
import { pauseRun, resumeRun } from "../../../api/runs";
import type {
  ComposerStateProjection,
  SessionRead,
  StageType,
} from "../../../api/types";
import { Composer } from "../Composer";
import { RunControlButtons } from "../RunControlButtons";

vi.mock("../../../api/runs", async () => {
  const actual = await vi.importActual<typeof import("../../../api/runs")>(
    "../../../api/runs",
  );
  return {
    ...actual,
    pauseRun: vi.fn(),
    resumeRun: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderButtons(props: Partial<Parameters<typeof RunControlButtons>[0]> = {}) {
  const queryClient = createQueryClient();

  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <RunControlButtons
          projectId="project-default"
          sessionId="session-waiting-clarification"
          runId="run-waiting-clarification"
          lifecycle="send"
          secondaryActions={["pause"]}
          isBusy={false}
          {...props}
        />
      </QueryClientProvider>,
    ),
  };
}

describe("RunControlButtons", () => {
  it("shows a secondary pause entry while waiting clarification still uses send", async () => {
    vi.mocked(pauseRun).mockResolvedValue({
      run_id: "run-waiting-clarification",
      attempt_index: 1,
      status: "paused",
      trigger_source: "initial_requirement",
      started_at: "2026-05-01T09:30:00.000Z",
      ended_at: null,
      current_stage_type: "requirement_analysis",
      is_active: true,
    });

    const { queryClient } = renderButtons();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: "暂停当前运行" }));

    await waitFor(() => {
      expect(pauseRun).toHaveBeenCalledWith(
        "run-waiting-clarification",
        expect.anything(),
      );
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["sessions", "session-waiting-clarification", "workspace"],
        refetchType: "all",
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["projects", "project-default", "sessions"],
        refetchType: "all",
      });
    });
  });

  it("does not render a secondary resume control for paused runs", () => {
    renderButtons({
      sessionId: "session-paused",
      runId: "run-paused",
      lifecycle: "resume",
      secondaryActions: ["terminate"],
    });

    expect(screen.queryByRole("button", { name: "恢复当前运行" })).toBeNull();
  });

  it("does not infer a secondary pause escape hatch from terminate", () => {
    renderButtons({
      lifecycle: "send",
      secondaryActions: ["terminate"],
    });

    expect(screen.queryByRole("button", { name: "暂停当前运行" })).toBeNull();
  });

  it("renders nothing for readonly lifecycle or missing current run binding", () => {
    const { rerender } = renderButtons({
      lifecycle: "disabled",
      secondaryActions: [],
    });
    expect(screen.queryByRole("button", { name: /当前运行/u })).toBeNull();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        <RunControlButtons
          projectId="project-default"
          sessionId="session-running"
          runId={null}
          lifecycle="pause"
          secondaryActions={["terminate"]}
          isBusy={false}
        />
      </QueryClientProvider>,
    );

    expect(screen.queryByRole("button", { name: /当前运行/u })).toBeNull();
  });
});

describe("Composer run controls", () => {
  it("renders only the primary send action in the compact waiting clarification composer", () => {
    renderComposer({
      queryClient: createQueryClient(),
      session: buildSession({
        session_id: "session-waiting-clarification",
        status: "waiting_clarification",
        current_run_id: "run-waiting-clarification",
      }),
      composerState: buildComposerState({
        mode: "waiting_clarification",
        is_input_enabled: true,
        primary_action: "send",
        secondary_actions: ["pause", "terminate"],
        bound_run_id: "run-waiting-clarification",
      }),
      currentStageType: "requirement_analysis",
    });

    expect(screen.getByRole("button", { name: "发送" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "暂停当前运行" })).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("uses the main lifecycle button to pause a running active run", async () => {
    vi.mocked(pauseRun).mockResolvedValue({
      run_id: "run-running",
      attempt_index: 1,
      status: "paused",
      trigger_source: "initial_requirement",
      started_at: "2026-05-01T09:30:00.000Z",
      ended_at: null,
      current_stage_type: "solution_design",
      is_active: true,
    });
    const queryClient = createQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderComposer({
      queryClient,
      session: buildSession({
        session_id: "session-running",
        status: "running",
        current_run_id: "run-running",
      }),
      composerState: buildComposerState({
        mode: "running",
        primary_action: "pause",
        bound_run_id: "run-running",
      }),
      currentStageType: "solution_design",
    });

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));

    await waitFor(() => {
      expect(pauseRun).toHaveBeenCalledWith("run-running", expect.anything());
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["sessions", "session-running", "workspace"],
        refetchType: "all",
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["projects", "project-default", "sessions"],
        refetchType: "all",
      });
    });
  });

  it("uses the main lifecycle button to resume a paused active run", async () => {
    vi.mocked(resumeRun).mockResolvedValue({
      run_id: "run-paused",
      attempt_index: 1,
      status: "running",
      trigger_source: "initial_requirement",
      started_at: "2026-05-01T09:30:00.000Z",
      ended_at: null,
      current_stage_type: "solution_design",
      is_active: true,
    });
    const queryClient = createQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderComposer({
      queryClient,
      session: buildSession({
        session_id: "session-paused",
        status: "paused",
        current_run_id: "run-paused",
      }),
      composerState: buildComposerState({
        mode: "paused",
        primary_action: "resume",
        bound_run_id: "run-paused",
      }),
      currentStageType: "solution_design",
    });

    fireEvent.click(screen.getByRole("button", { name: "恢复" }));

    await waitFor(() => {
      expect(resumeRun).toHaveBeenCalledWith("run-paused", expect.anything());
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["sessions", "session-paused", "workspace"],
        refetchType: "all",
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["projects", "project-default", "sessions"],
        refetchType: "all",
      });
    });
  });

});

function renderComposer({
  queryClient,
  session,
  composerState,
  currentStageType,
}: {
  queryClient: ReturnType<typeof createQueryClient>;
  session: SessionRead;
  composerState: ComposerStateProjection;
  currentStageType: StageType | null;
}) {
  return render(
    <QueryClientProvider client={queryClient}>
      <Composer
        session={session}
        composerState={composerState}
        currentStageType={currentStageType}
      />
    </QueryClientProvider>,
  );
}

function buildSession(overrides: Partial<SessionRead>): SessionRead {
  return {
    session_id: "session-running",
    project_id: "project-default",
    display_name: "Run control test",
    status: "running",
    selected_template_id: "template-feature",
    current_run_id: "run-running",
    latest_stage_type: "solution_design",
    created_at: "2026-05-01T09:30:00.000Z",
    updated_at: "2026-05-01T09:35:00.000Z",
    ...overrides,
  };
}

function buildComposerState(
  overrides: Partial<ComposerStateProjection>,
): ComposerStateProjection {
  return {
    mode: "running",
    is_input_enabled: false,
    primary_action: "pause",
    secondary_actions: ["terminate"],
    bound_run_id: "run-running",
    ...overrides,
  };
}
