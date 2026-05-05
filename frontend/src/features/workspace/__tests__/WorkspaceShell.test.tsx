import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiRequestOptions } from "../../../api/client";
import { terminateRun } from "../../../api/runs";
import type {
  ExecutionNodeProjection,
  ProviderRead,
  SessionRead,
  SessionStatus,
  SessionWorkspaceProjection,
} from "../../../api/types";
import { createQueryClient } from "../../../app/query-client";
import { renderWithAppProviders } from "../../../app/test-utils";
import {
  mockFeedEntriesByType,
  mockProviderList,
  mockSessionWorkspaces,
  mockStageInspectorProjection,
} from "../../../mocks/fixtures";
import {
  createMockApiFetcher,
  mockApiRequestOptions,
} from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { TerminateRunAction } from "../../runs/TerminateRunAction";
import { useWorkspaceStore } from "../workspace-store";

vi.mock("../../../api/runs", async () => {
  const actual = await vi.importActual<typeof import("../../../api/runs")>(
    "../../../api/runs",
  );
  return {
    ...actual,
    terminateRun: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useWorkspaceStore.getState().resetWorkspace();
});

describe("WorkspaceShell", () => {
  it("renders the three workspace regions with inspector closed by default", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("complementary", {
        name: "Project and session sidebar",
      }),
    ).toBeTruthy();
    expect(screen.getByRole("region", { name: "Narrative workspace" })).toBeTruthy();
    expect(screen.getByRole("complementary", { name: "Inspector" })).toBeTruthy();
    expect(screen.getByText("Inspector closed")).toBeTruthy();
    expect(screen.queryByText(/workflow surface comes online/i)).toBeNull();
  });

  it("shows project navigation, delivery summary, and session management affordances", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "AI Devflow Engine",
      }),
    ).toBeTruthy();
    expect(
      screen.getByText("C:/Users/lkw/Desktop/github/agent-project/ai-devflow-engine"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Load project" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "New session" })).toBeTruthy();
    expect(screen.getByText("Default delivery")).toBeTruthy();
    expect(await screen.findByText("demo_delivery")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Default project cannot be removed" }),
    ).toHaveProperty("disabled", true);
    expect(screen.getByText("Add workspace shell")).toBeTruthy();
    expect(screen.getByText("Waiting approval")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Rename Add workspace shell" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: "Delete Add workspace shell blocked by active run",
      }),
    ).toHaveProperty("disabled", true);
  });

  it("switches the current project and keeps shell-only destructive actions disabled", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "AI Devflow Engine",
      }),
    ).toBeTruthy();
    expect(
      await screen.findByRole("button", {
        name: "Delete Blank requirement unavailable",
      }),
    ).toHaveProperty("disabled", true);

    fireEvent.change(await screen.findByLabelText("Switch project"), {
      target: { value: "project-loaded" },
    });

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Checkout Service",
      }),
    ).toBeTruthy();
    expect(screen.getByText("C:/work/checkout-service")).toBeTruthy();
    expect(await screen.findByText("git_auto_delivery")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Remove Checkout Service unavailable" }),
    ).toHaveProperty("disabled", true);
  });

  it("opens a selected session from the sidebar and shows session metadata", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("region", { name: "Template empty state" }),
    ).toBeTruthy();
    const runningSessionItem = screen
      .getByRole("button", { name: "Open Add workspace shell" })
      .closest("article");
    expect(runningSessionItem).toBeTruthy();
    expect(
      within(runningSessionItem as HTMLElement).getByText("Updated 2026-05-01 09:25"),
    ).toBeTruthy();
    expect(
      within(runningSessionItem as HTMLElement).getByText(
        "Current stage Solution Design",
      ),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Open Add workspace shell" }),
    );

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Add workspace shell",
      }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("region", { name: "Template empty state" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Open Add workspace shell",
      }),
    ).toHaveProperty("ariaCurrent", "page");
  });

  it("creates a new draft session from the sidebar and switches to it", async () => {
    const createdSession: SessionRead = {
      session_id: "session-created-from-sidebar",
      project_id: "project-default",
      display_name: "Untitled requirement",
      status: "draft",
      selected_template_id: "template-feature",
      current_run_id: null,
      latest_stage_type: null,
      created_at: "2026-05-05T07:30:00.000Z",
      updated_at: "2026-05-05T07:30:00.000Z",
    };
    const baseFetcher = createMockApiFetcher();
    const projectSessions = Object.values(mockSessionWorkspaces)
      .map((workspace) => workspace.session)
      .filter((session) => session.project_id === "project-default");
    let createSessionCalls = 0;
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (
          method === "GET" &&
          path === "/api/projects/project-default/sessions"
        ) {
          return jsonTestResponse(projectSessions);
        }

        if (
          method === "POST" &&
          path === "/api/projects/project-default/sessions"
        ) {
          createSessionCalls += 1;
          projectSessions.unshift(createdSession);
          return jsonTestResponse(createdSession);
        }

        if (
          method === "GET" &&
          path === "/api/sessions/session-created-from-sidebar/workspace"
        ) {
          return jsonTestResponse(createDraftWorkspace(createdSession));
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    const newSessionButton = await screen.findByRole("button", {
      name: "New session",
    });
    await waitFor(() => {
      expect(newSessionButton).toHaveProperty("disabled", false);
    });

    fireEvent.click(newSessionButton);

    await waitFor(() => {
      expect(createSessionCalls).toBe(1);
    });
    expect(
      await screen.findByRole("button", { name: "Open Untitled requirement" }),
    ).toHaveProperty("ariaCurrent", "page");
    expect(
      screen.getByRole("region", { name: "Template empty state" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", false);
  });

  it("keeps the current session selected when new session creation fails", async () => {
    const baseFetcher = createMockApiFetcher();
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (
          method === "POST" &&
          path === "/api/projects/project-default/sessions"
        ) {
          return jsonTestResponse(
            {
              error_code: "validation_error",
              code: "validation_error",
              message: "Project cannot create a new session.",
              request_id: "request-new-session-failed",
            },
            409,
          );
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    await screen.findByRole("heading", {
      level: 1,
      name: "Add workspace shell",
    });

    const newSessionButton = screen.getByRole("button", { name: "New session" });
    await waitFor(() => {
      expect(newSessionButton).toHaveProperty("disabled", false);
    });

    fireEvent.click(newSessionButton);

    expect((await screen.findByRole("alert")).textContent ?? "").toContain(
      "Request needs correction",
    );
    expect(
      screen.getByRole("button", { name: "Open Add workspace shell" }),
    ).toHaveProperty("ariaCurrent", "page");
    expect(screen.getByRole("region", { name: "Run 1 boundary" })).toBeTruthy();
  });

  it("uses product workspace copy and avoids implementation placeholder text", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(await screen.findByText("Narrative Workspace")).toBeTruthy();
    expect(screen.getByText("Inspector closed")).toBeTruthy();
    expect(screen.queryByText(/feature slices/i)).toBeNull();
    expect(screen.queryByText(/routing/i)).toBeNull();
    expect(screen.queryByText(/data layer/i)).toBeNull();
    expect(screen.queryByText(/workflow surface comes online/i)).toBeNull();
  });

  it("renders the draft session template selector as narrative feed empty content", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("region", { name: "Template empty state" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("radio", { name: /新功能开发流程/u }),
    ).toHaveProperty("checked", true);
    fireEvent.click(screen.getByRole("radio", { name: /Bug 修复流程/u }));
    expect(
      screen.getByRole("heading", { level: 1, name: "Bug 修复流程" }),
    ).toBeTruthy();
    expect(
      screen.queryByText(
        "Select a session to review its run history and execution feed.",
      ),
    ).toBeNull();
  });

  it("renders template editing inside the draft narrative empty state", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    const editor = await screen.findByRole("region", { name: "Template editor" });
    expect(within(editor).getByText("Run configuration")).toBeTruthy();
    expect(
      within(editor).getByLabelText("requirement_analysis system prompt"),
    ).toBeTruthy();
    expect(within(editor).getByLabelText("requirement_analysis provider")).toBeTruthy();

    fireEvent.change(within(editor).getByLabelText("requirement_analysis system prompt"), {
      target: { value: "Clarify only when missing facts block implementation." },
    });

    expect(within(editor).getByText(/Save this edited system template/u)).toBeTruthy();
    expect(
      within(editor).getByRole("button", { name: "Save as user template" }),
    ).toBeTruthy();
    expect(document.body.textContent ?? "").not.toContain("DeliveryChannel");
    expect(document.body.textContent ?? "").not.toContain("deterministic test runtime");
  });

  it("initializes the workspace store from the loaded session snapshot", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );

    await screen.findByRole("heading", {
      level: 1,
      name: "Add workspace shell",
    });
    await waitFor(() => {
      expect(useWorkspaceStore.getState().session?.session_id).toBe(
        "session-running",
      );
    });
    expect(useWorkspaceStore.getState().narrativeFeed).toContainEqual(
      expect.objectContaining({ type: "stage_node" }),
    );
  });

  it("applies session stream events through the workspace store reducer", async () => {
    const eventSources: MockEventSource[] = [];
    vi.stubGlobal(
      "EventSource",
      vi.fn(function EventSourceMock(this: MockEventSource, url: string) {
        this.url = url;
        this.close = vi.fn();
        this.listeners = new Map();
        this.addEventListener = vi.fn(
          (type: string, listener: (event: MessageEvent<string>) => void) => {
            this.listeners.set(type, listener);
          },
        );
        this.removeEventListener = vi.fn((type: string) => {
          this.listeners.delete(type);
        });
        eventSources.push(this);
      }),
    );

    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    await screen.findByRole("heading", {
      level: 1,
      name: "Add workspace shell",
    });
    await waitFor(() => {
      expect(eventSources.some((source) => source.url.includes("session-running"))).toBe(
        true,
      );
    });
    const runningSource = eventSources.find((source) =>
      source.url.includes("session-running"),
    );
    expect(runningSource).toBeTruthy();

    runningSource?.listeners.get("session_message_appended")?.({
      data: JSON.stringify({
        event_id: "event-stream-message",
        session_id: "session-running",
        run_id: "run-running",
        event_type: "session_message_appended",
        occurred_at: "2026-05-01T10:10:00.000Z",
        payload: {
          message_item: {
            entry_id: "entry-stream-message",
            run_id: "run-running",
            type: "user_message",
            occurred_at: "2026-05-01T10:10:00.000Z",
            message_id: "message-stream",
            author: "user",
            content: "Streamed update from backend.",
            stage_run_id: null,
          },
        },
      }),
    } as MessageEvent<string>);

    expect(await screen.findByText("Streamed update from backend.")).toBeTruthy();
    expect(useWorkspaceStore.getState().narrativeFeed).toContainEqual(
      expect.objectContaining({
        entry_id: "entry-stream-message",
        type: "user_message",
      }),
    );
  });

  it("refreshes open inspector detail when the matching live stage entry updates", async () => {
    let useUpdatedDetail = false;
    const baseFetcher = createMockApiFetcher();
    const updatedStageInspectorProjection = {
      ...mockStageInspectorProjection,
      output: {
        ...mockStageInspectorProjection.output,
        records: {
          ...mockStageInspectorProjection.output.records,
          design_summary: "Refined execution plan",
        },
      },
    };
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/stages/stage-solution-design-running/inspector")) {
          return new Response(
            JSON.stringify(
              useUpdatedDetail
                ? updatedStageInspectorProjection
                : mockStageInspectorProjection,
            ),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          );
        }

        return baseFetcher(input, init);
      },
    };
    const eventSources: MockEventSource[] = [];
    vi.stubGlobal(
      "EventSource",
      vi.fn(function EventSourceMock(this: MockEventSource, url: string) {
        this.url = url;
        this.close = vi.fn();
        this.listeners = new Map();
        this.addEventListener = vi.fn(
          (type: string, listener: (event: MessageEvent<string>) => void) => {
            this.listeners.set(type, listener);
          },
        );
        this.removeEventListener = vi.fn((type: string) => {
          this.listeners.delete(type);
        });
        eventSources.push(this);
      }),
    );

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Solution Design details" }),
    );

    expect(await screen.findByText("Draft execution plan")).toBeTruthy();
    await waitFor(() => {
      expect(eventSources.some((source) => source.url.includes("session-running"))).toBe(
        true,
      );
    });

    useUpdatedDetail = true;
    const updatedStageNode: ExecutionNodeProjection = {
      ...(useWorkspaceStore
        .getState()
        .narrativeFeed.find((entry) => entry.type === "stage_node") as ExecutionNodeProjection),
      occurred_at: "2026-05-01T09:19:00.000Z",
      summary: "Design refined after live workspace update.",
    };
    eventSources
      .find((source) => source.url.includes("session-running"))
      ?.listeners.get("stage_updated")
      ?.({
        data: JSON.stringify({
          event_id: "event-stage-update-inspector-refresh",
          session_id: "session-running",
          run_id: "run-running",
          event_type: "stage_updated",
          occurred_at: "2026-05-01T09:19:00.000Z",
          payload: {
            stage_node: updatedStageNode,
          },
        }),
      } as MessageEvent<string>);

    expect(await screen.findByText("Refined execution plan")).toBeTruthy();
  });

  it("refreshes open stage inspector detail when a same-run approval result arrives", async () => {
    let useUpdatedDetail = false;
    const baseFetcher = createMockApiFetcher();
    const updatedStageInspectorProjection = {
      ...mockStageInspectorProjection,
      artifacts: {
        ...mockStageInspectorProjection.artifacts,
        records: {
          ...mockStageInspectorProjection.artifacts.records,
          approval_summary: "Approval recorded in stage detail",
        },
      },
    };
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/stages/stage-solution-design-running/inspector")) {
          return new Response(
            JSON.stringify(
              useUpdatedDetail
                ? updatedStageInspectorProjection
                : mockStageInspectorProjection,
            ),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          );
        }

        return baseFetcher(input, init);
      },
    };
    const eventSources: MockEventSource[] = [];
    vi.stubGlobal(
      "EventSource",
      vi.fn(function EventSourceMock(this: MockEventSource, url: string) {
        this.url = url;
        this.close = vi.fn();
        this.listeners = new Map();
        this.addEventListener = vi.fn(
          (type: string, listener: (event: MessageEvent<string>) => void) => {
            this.listeners.set(type, listener);
          },
        );
        this.removeEventListener = vi.fn((type: string) => {
          this.listeners.delete(type);
        });
        eventSources.push(this);
      }),
    );

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Solution Design details" }),
    );

    expect(await screen.findByText("Draft execution plan")).toBeTruthy();
    await waitFor(() => {
      expect(eventSources.some((source) => source.url.includes("session-running"))).toBe(
        true,
      );
    });

    useUpdatedDetail = true;
    eventSources
      .find((source) => source.url.includes("session-running"))
      ?.listeners.get("approval_result")
      ?.({
        data: JSON.stringify({
          event_id: "event-approval-result-inspector-refresh",
          session_id: "session-running",
          run_id: "run-running",
          event_type: "approval_result",
          occurred_at: "2026-05-01T09:21:00.000Z",
          payload: {
            approval_result: {
              entry_id: "entry-approval-result-live",
              run_id: "run-running",
              type: "approval_result",
              occurred_at: "2026-05-01T09:21:00.000Z",
              approval_id: "approval-solution-design-live",
              approval_type: "solution_design_approval",
              decision: "approved",
              reason: null,
              created_at: "2026-05-01T09:21:00.000Z",
              next_stage_type: "code_generation",
            },
          },
        }),
      } as MessageEvent<string>);

    expect(await screen.findByText("Approval recorded in stage detail")).toBeTruthy();
  });

  it("keeps the inspector open when Escape is pressed inside settings", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Solution Design details" }),
    );

    expect(await screen.findByText("Draft execution plan")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    expect(dialog).toBeTruthy();

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull();
    });
    expect(screen.getByRole("heading", { name: "Stage details" })).toBeTruthy();
    expect(screen.getByText("Draft execution plan")).toBeTruthy();
  });

  it("opens settings from a delivery-readiness-blocked approval block", async () => {
    const baseFetcher = createMockApiFetcher();
    const blockedWorkspace = {
      ...mockSessionWorkspaces["session-waiting-approval"],
      narrative_feed: mockSessionWorkspaces[
        "session-waiting-approval"
      ].narrative_feed.map((entry) =>
        entry.type === "approval_request"
          ? {
              ...entry,
              approval_type: "code_review_approval",
              delivery_readiness_status: "invalid",
              delivery_readiness_message: "Credential reference cannot be resolved.",
              open_settings_action: "open_general_settings",
            }
          : entry,
      ),
    };
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/sessions/session-waiting-approval/workspace")) {
          return new Response(JSON.stringify(blockedWorkspace), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Review delivery snapshot" }),
    );
    const approvalEntry = await screen.findByRole("article", {
      name: "Approval request feed entry",
    });
    expect(
      within(approvalEntry).getByText("Credential reference cannot be resolved."),
    ).toBeTruthy();
    fireEvent.click(
      within(approvalEntry).getByRole("button", { name: "Open settings" }),
    );

    expect(await screen.findByRole("dialog", { name: "Settings" })).toBeTruthy();
    expect(screen.getByRole("tabpanel", { name: "通用配置" })).toBeTruthy();
  });

  it("refetches workspace state after an inline reject and shows the returned approval result reason in the feed", async () => {
    let workspace = {
      ...mockSessionWorkspaces["session-waiting-approval"],
    };
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();

        if (url.endsWith("/api/sessions/session-waiting-approval/workspace")) {
          return new Response(JSON.stringify(workspace), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }

        if (url.endsWith("/api/approvals/approval-solution-design/reject")) {
          workspace = {
            ...workspace,
            narrative_feed: [
              ...workspace.narrative_feed.map((entry) =>
                entry.type === "approval_request"
                  ? { ...entry, status: "rejected" as const, is_actionable: false }
                  : entry,
              ),
              {
                entry_id: "entry-approval-result-rejected",
                run_id: "run-waiting-approval",
                type: "approval_result",
                occurred_at: "2026-05-01T09:56:00.000Z",
                approval_id: "approval-solution-design",
                approval_type: "solution_design_approval",
                decision: "rejected",
                reason: "Need a clearer rollback explanation.",
                created_at: "2026-05-01T09:56:00.000Z",
                next_stage_type: "code_generation",
              },
            ],
          };
          return new Response(
            JSON.stringify(workspace.narrative_feed[workspace.narrative_feed.length - 1]),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }

        return createMockApiFetcher()(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Review delivery snapshot" }),
    );
    const approvalEntry = await screen.findByRole("article", {
      name: "Approval request feed entry",
    });
    fireEvent.click(within(approvalEntry).getByRole("button", { name: "Reject" }));
    fireEvent.change(screen.getByLabelText("Reject reason"), {
      target: { value: "Need a clearer rollback explanation." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit reject reason" }));

    expect(await screen.findByText("Need a clearer rollback explanation.")).toBeTruthy();
  });

  it("refetches workspace state after a tool confirmation deny and renders denied follow-up summary in the feed", async () => {
    let workspace: SessionWorkspaceProjection = {
      ...mockSessionWorkspaces["session-running"],
      narrative_feed: [
        ...mockSessionWorkspaces["session-running"].narrative_feed,
        mockFeedEntriesByType.tool_confirmation,
      ],
    };
    const baseFetcher = createMockApiFetcher();
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();

        if (url.endsWith("/api/sessions/session-running/workspace")) {
          return new Response(JSON.stringify(workspace), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }

        const response = await baseFetcher(input, init);
        if (url.endsWith("/api/tool-confirmations/tool-confirmation-1/deny")) {
          workspace = {
            ...workspace,
            narrative_feed: workspace.narrative_feed.map((entry) =>
              entry.type === "tool_confirmation"
                ? {
                    ...entry,
                    status: "denied",
                    decision: "denied",
                    is_actionable: false,
                    responded_at: "2026-05-01T09:21:00.000Z",
                    deny_followup_action: "run_failed",
                    deny_followup_summary:
                      "The current run will fail because no low-risk alternative path exists.",
                  }
                : entry,
            ),
          };
        }
        return response;
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    const toolEntry = await screen.findByRole("article", {
      name: "Tool confirmation feed entry",
    });
    fireEvent.click(within(toolEntry).getByRole("button", { name: "拒绝本次执行" }));

    expect(
      await screen.findByText(
        "The current run will fail because no low-risk alternative path exists.",
      ),
    ).toBeTruthy();
  });

  it("keeps historical tool confirmations disabled in the workspace surface", async () => {
    const historicalWorkspace: SessionWorkspaceProjection = {
      ...mockSessionWorkspaces["session-running"],
      narrative_feed: [
        ...mockSessionWorkspaces["session-running"].narrative_feed,
        {
          ...mockFeedEntriesByType.tool_confirmation,
          run_id: "run-historical",
        },
      ],
    };
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/sessions/session-running/workspace")) {
          return new Response(JSON.stringify(historicalWorkspace), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }

        return createMockApiFetcher()(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    const toolEntry = await screen.findByRole("article", {
      name: "Tool confirmation feed entry",
    });

    expect(
      within(toolEntry).getByRole("button", { name: "允许本次执行" }),
    ).toHaveProperty("disabled", true);
    expect(
      within(toolEntry).getByText(
        "This tool confirmation belongs to a historical run.",
      ),
    ).toBeTruthy();
  });

  it("renders Composer beneath the draft template workspace and allows first requirement input", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(await screen.findByRole("form", { name: "Composer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "发送" })).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toBeTruthy();
  });

  it("blocks first requirement input when the selected template has unavailable providers", async () => {
    const baseFetcher = createMockApiFetcher();
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (method === "GET" && path === "/api/providers") {
          return jsonTestResponse([]);
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    await waitFor(() => {
      expect(
        screen.getAllByText(
          "This template references unavailable providers: provider-deepseek.",
        ),
      ).toHaveLength(2);
    });
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "发送" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("keeps first requirement input enabled when a configured provider replaces stale template bindings", async () => {
    const baseFetcher = createMockApiFetcher();
    const mimoProvider: ProviderRead = {
      ...mockProviderList[2],
      provider_id: "provider-mimo",
      display_name: "MiMo",
      default_model_id: "mimo-chat",
      supported_model_ids: ["mimo-chat"],
      runtime_capabilities: [
        {
          ...mockProviderList[2].runtime_capabilities[0],
          model_id: "mimo-chat",
        },
      ],
    };
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (method === "GET" && path === "/api/providers") {
          return jsonTestResponse([mimoProvider]);
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    const editor = await screen.findByRole("region", { name: "Template editor" });
    const providerSelect = within(editor).getByLabelText("requirement_analysis provider");
    await waitFor(() => {
      expect(providerSelect).toHaveProperty("value", "provider-mimo");
    });
    expect(
      screen.queryByText(/This template references unavailable providers/u),
    ).toBeNull();

    const input = screen.getByLabelText("当前输入");
    fireEvent.change(input, {
      target: { value: "Start with the configured provider." },
    });

    expect(input).toHaveProperty("disabled", false);
    expect(screen.getByRole("button", { name: "发送" })).toHaveProperty(
      "disabled",
      false,
    );
  });

  it("keeps Composer send-enabled for waiting clarification sessions", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Clarify provider behavior",
      }),
    );

    expect(await screen.findByRole("button", { name: "发送" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "暂停当前运行" })).toBeTruthy();
    expect(screen.getByText(/等待你的澄清回复/u)).toBeTruthy();
  });

  it("resets unsent Composer input when the selected session changes", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    const input = await screen.findByLabelText("当前输入");
    fireEvent.change(input, {
      target: { value: "This draft should not leak into another session." },
    });
    expect(input).toHaveProperty(
      "value",
      "This draft should not leak into another session.",
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Clarify provider behavior",
      }),
    );

    expect(await screen.findByRole("button", { name: "发送" })).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toHaveProperty("value", "");
  });

  it("appends a draft requirement to Narrative Feed after Composer submit", async () => {
    renderWithAppProviders(
      <ConsolePage
        request={{ fetcher: createMockApiFetcher({ persistSessionMessages: true }) }}
      />,
    );

    fireEvent.change(await screen.findByLabelText("当前输入"), {
      target: { value: "Persist the first requirement in the feed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      const userEntries = screen.getAllByRole("article", {
        name: "User message feed entry",
      });
      expect(
        userEntries.some((entry) =>
          within(entry).queryByText("Persist the first requirement in the feed."),
        ),
      ).toBe(true);
    });
  });

  it("appends a clarification reply to Narrative Feed after Composer submit", async () => {
    renderWithAppProviders(
      <ConsolePage
        request={{ fetcher: createMockApiFetcher({ persistSessionMessages: true }) }}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Clarify provider behavior",
      }),
    );

    fireEvent.change(await screen.findByLabelText("当前输入"), {
      target: { value: "Use the configured default provider." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      const userEntries = screen.getAllByRole("article", {
        name: "User message feed entry",
      });
      expect(
        userEntries.some((entry) =>
          within(entry).queryByText("Use the configured default provider."),
        ),
      ).toBe(true);
    });

    expect(await screen.findByRole("button", { name: "暂停" })).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", true);
  });

  it("shows the pause presentation when the active run is still in requirement analysis", async () => {
    const baseFetcher = createMockApiFetcher();
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/sessions/session-running/workspace")) {
          const workspace = mockSessionWorkspaces["session-running"];
          return new Response(
            JSON.stringify({
              ...workspace,
              session: {
                ...workspace.session,
                latest_stage_type: "requirement_analysis",
              },
              current_stage_type: "requirement_analysis",
              runs: workspace.runs.map((run) => ({
                ...run,
                current_stage_type: "requirement_analysis",
              })),
            }),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          );
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );

    expect(await screen.findByRole("button", { name: "暂停" })).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", true);
  });

  it("updates Composer from live session status changes", async () => {
    const eventSources: MockEventSource[] = [];
    vi.stubGlobal(
      "EventSource",
      vi.fn(function EventSourceMock(this: MockEventSource, url: string) {
        this.url = url;
        this.close = vi.fn();
        this.listeners = new Map();
        this.addEventListener = vi.fn(
          (type: string, listener: (event: MessageEvent<string>) => void) => {
            this.listeners.set(type, listener);
          },
        );
        this.removeEventListener = vi.fn((type: string) => {
          this.listeners.delete(type);
        });
        eventSources.push(this);
      }),
    );

    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Clarify provider behavior",
      }),
    );
    expect(await screen.findByRole("button", { name: "发送" })).toBeTruthy();

    await waitFor(() => {
      expect(
        eventSources.some((source) =>
          source.url.includes("session-waiting-clarification"),
        ),
      ).toBe(true);
    });

    eventSources
      .find((source) => source.url.includes("session-waiting-clarification"))
      ?.listeners.get("session_status_changed")
      ?.( {
        data: JSON.stringify({
          event_id: "event-clarification-resumed",
          session_id: "session-waiting-clarification",
          run_id: "run-waiting-clarification",
          event_type: "session_status_changed",
          occurred_at: "2026-05-01T09:39:00.000Z",
          payload: {
            session_id: "session-waiting-clarification",
            status: "running",
            current_run_id: "run-waiting-clarification",
            current_stage_type: "requirement_analysis",
          },
        }),
      } as MessageEvent<string>);

    expect(await screen.findByRole("button", { name: "暂停" })).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", true);
  });

  it("shows a terminate entry in the workspace toolbar for the current active run only", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );

    expect(await screen.findByRole("button", { name: "终止当前运行" })).toBeTruthy();
  });

  it("hides the terminate entry for completed sessions without an active run", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Renamed checkout flow fix" }),
    );

    expect(screen.queryByRole("button", { name: "终止当前运行" })).toBeNull();
  });

  it("reruns a failed session into a new current run and keeps the previous run historical", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    const fetcher = createMockApiFetcher();
    const request: ApiRequestOptions = { fetcher };

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Investigate failing run" }),
    );

    const firstBoundary = await screen.findByRole("region", {
      name: "Run 1 boundary",
    });
    fireEvent.click(within(firstBoundary).getByRole("button", { name: "Retry run" }));

    const secondBoundary = await screen.findByRole("region", {
      name: "Run 2 boundary",
    });

    expect(within(secondBoundary).getByText("Current run")).toBeTruthy();
    expect(within(secondBoundary).getByText("0 entries")).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "Run 1 boundary" })).getByText(
        "Historical run",
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "Run 1 boundary" })).queryByRole(
        "button",
        { name: "Retry run" },
      ),
    ).toBeNull();
    await waitFor(() => {
      expect(document.activeElement?.id).toBe("run-boundary-run-failed-retry-2");
    });
  });

  it("rejects mock rerun requests for non-terminal sessions", async () => {
    const fetcher = createMockApiFetcher();

    const response = await fetcher("/api/sessions/session-running/runs", {
      method: "POST",
    });

    expect(response.status).toBe(409);
    const workspaceResponse = await fetcher(
      "/api/sessions/session-running/workspace",
    );
    const workspace = (await workspaceResponse.json()) as SessionWorkspaceProjection;
    expect(workspace.current_run_id).toBe("run-running");
    expect(workspace.runs).toHaveLength(1);
  });
});

describe("TerminateRunAction", () => {
  it("confirms before calling terminate for the current active run", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(terminateRun).mockResolvedValue({
      run_id: "run-running",
      attempt_index: 1,
      status: "terminated",
      trigger_source: "initial_requirement",
      started_at: "2026-05-01T09:10:00.000Z",
      ended_at: "2026-05-01T09:26:00.000Z",
      current_stage_type: "solution_design",
      is_active: false,
    });
    const queryClient = createQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    render(
      <QueryClientProvider client={queryClient}>
        <TerminateRunAction
          projectId="project-default"
          sessionId="session-running"
          runId="run-running"
          sessionStatus={"running" satisfies SessionStatus}
          secondaryActions={["terminate"]}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "终止当前运行" }));

    await waitFor(() => {
      expect(terminateRun).toHaveBeenCalledWith("run-running", expect.anything());
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

  it("hides terminate when the projection omits the terminate action", () => {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <TerminateRunAction
          projectId="project-default"
          sessionId="session-running"
          runId="run-running"
          sessionStatus={"running" satisfies SessionStatus}
          secondaryActions={[]}
        />
      </QueryClientProvider>,
    );

    expect(screen.queryByRole("button", { name: "终止当前运行" })).toBeNull();
  });
});

type MockEventSource = {
  url: string;
  close: ReturnType<typeof vi.fn>;
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
  listeners: Map<string, (event: MessageEvent<string>) => void>;
};

function createDraftWorkspace(session: SessionRead): SessionWorkspaceProjection {
  const draftWorkspace = mockSessionWorkspaces["session-draft"];

  return {
    ...draftWorkspace,
    session,
    project: draftWorkspace.project,
    runs: [],
    narrative_feed: [],
    current_run_id: null,
    current_stage_type: null,
    composer_state: {
      mode: "draft",
      is_input_enabled: true,
      primary_action: "send",
      secondary_actions: [],
      bound_run_id: null,
    },
  };
}

function jsonTestResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function normalizeTestPath(input: RequestInfo | URL): string {
  const raw = typeof input === "string" ? input : input.toString();
  if (/^https?:\/\//u.test(raw)) {
    const url = new URL(raw);
    return url.pathname;
  }
  return raw;
}
