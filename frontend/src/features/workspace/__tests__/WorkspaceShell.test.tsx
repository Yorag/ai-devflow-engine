import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiRequestOptions } from "../../../api/client";
import type { ExecutionNodeProjection } from "../../../api/types";
import { renderWithAppProviders } from "../../../app/test-utils";
import { mockStageInspectorProjection } from "../../../mocks/fixtures";
import {
  createMockApiFetcher,
  mockApiRequestOptions,
} from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { useWorkspaceStore } from "../workspace-store";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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
});

type MockEventSource = {
  url: string;
  close: ReturnType<typeof vi.fn>;
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
  listeners: Map<string, (event: MessageEvent<string>) => void>;
};
