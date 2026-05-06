import { readFileSync } from "node:fs";
import { join } from "node:path";

import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiRequestOptions } from "../../../api/client";
import { terminateRun } from "../../../api/runs";
import type {
  ExecutionNodeProjection,
  PipelineTemplateRead,
  PipelineTemplateWriteRequest,
  ProviderRead,
  ProjectRead,
  SessionRead,
  SessionStatus,
  SessionWorkspaceProjection,
} from "../../../api/types";
import { createQueryClient } from "../../../app/query-client";
import { renderWithAppProviders } from "../../../app/test-utils";
import {
  mockFeedEntriesByType,
  mockPipelineTemplates,
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
import { SessionList } from "../SessionList";
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
  it("keeps the Composer dock fixed to the workspace viewport in CSS", () => {
    const cwd = process.cwd();
    const frontendRoot = cwd.endsWith("frontend") ? cwd : join(cwd, "frontend");
    const css = readFileSync(
      join(frontendRoot, "src", "styles", "global.css"),
      "utf8",
    );

    expect(css).toMatch(
      /\.workspace-shell\s*\{[^}]*--workspace-sidebar-width:\s*clamp\(280px,\s*22vw,\s*320px\);[^}]*--workspace-inspector-width:\s*0px;[^}]*height:\s*calc\(100vh\s*-\s*73px\);[^}]*min-height:\s*0;[^}]*grid-template-columns:\s*var\(--workspace-sidebar-width\)\s+minmax\(0,\s*1fr\);/su,
    );
    expect(css).toMatch(
      /\.workspace-shell--inspector-open\s*\{[^}]*--workspace-inspector-width:\s*clamp\(360px,\s*28vw,\s*420px\);[^}]*grid-template-columns:\s*var\(--workspace-sidebar-width\)\s+minmax\(0,\s*1fr\)\s+var\(--workspace-inspector-width\);/su,
    );
    expect(css).toMatch(
      /\.workspace-main__composer-dock\s*\{[^}]*position:\s*fixed;[^}]*left:\s*var\(--workspace-sidebar-width\);[^}]*right:\s*var\(--workspace-inspector-width\);/su,
    );
    expect(css).toMatch(
      /\.composer\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto;[^}]*align-items:\s*end;[^}]*overflow:\s*visible;/su,
    );
    expect(css).toMatch(
      /\.composer\s+textarea\s*\{[^}]*min-height:\s*40px;[^}]*max-height:\s*calc\(1\.45em\s*\*\s*5\s*\+\s*20px\);[^}]*resize:\s*none;[^}]*overflow-y:\s*auto;/su,
    );
    expect(css).toMatch(
      /\.composer__primary-actions\s+\.workspace-button\s*\{[^}]*width:\s*auto;[^}]*min-height:\s*40px;/su,
    );
    expect(css).not.toMatch(
      /@media\s*\(max-width:\s*900px\)[\s\S]*\.workspace-shell,\s*\.workspace-shell--inspector-open\s*\{[^}]*height:\s*auto;/u,
    );
    expect(css).not.toMatch(
      /@media\s*\(max-width:\s*900px\)[\s\S]*\.workspace-shell,\s*\.workspace-shell--inspector-open\s*\{[^}]*overflow:\s*visible;/u,
    );
  });

  it("renders the workspace with inspector closed and no right-column placeholder by default", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("complementary", {
        name: "Project and session sidebar",
      }),
    ).toBeTruthy();
    const shell = screen.getByRole("region", { name: "Workspace shell" });
    expect(shell.getAttribute("class")).toContain(
      "workspace-shell--inspector-closed",
    );
    expect(shell.getAttribute("class")).not.toContain(
      "workspace-shell--inspector-open",
    );
    const main = screen.getByRole("region", { name: "Narrative workspace" });
    expect(main).toBeTruthy();
    const scrollArea = main.querySelector(".workspace-main__scroll");
    expect(scrollArea).toBeTruthy();
    expect(main.querySelector(".workspace-main__content")).toBeTruthy();
    expect(
      await screen.findByRole("region", { name: "Template empty state" }),
    ).toBeTruthy();
    const dock = main.querySelector(".workspace-main__composer-dock");
    expect(dock).toBeTruthy();
    expect(dock?.parentElement).toBe(main);
    expect(
      main.querySelector(".workspace-main__panel--template .template-empty-state"),
    ).toBeTruthy();
    expect(
      dock?.querySelector(".workspace-main__composer-inner .composer"),
    ).toBeTruthy();
    expect(
      scrollArea?.querySelector(".workspace-main__panel--composer"),
    ).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Inspector" })).toBeNull();
    expect(screen.queryByText("Inspector closed")).toBeNull();
    expect(screen.queryByText(/workflow surface comes online/i)).toBeNull();
  });

  it("switches to the open Inspector layout when a feed detail opens", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Solution Design details" }),
    );

    const shell = screen.getByRole("region", { name: "Workspace shell" });
    expect(shell.getAttribute("class")).toContain(
      "workspace-shell--inspector-open",
    );
    expect(shell.getAttribute("class")).not.toContain(
      "workspace-shell--inspector-closed",
    );
    const main = screen.getByRole("region", { name: "Narrative workspace" });
    expect(
      main.querySelector(".workspace-main__panel--feed .narrative-feed"),
    ).toBeTruthy();
    const dock = main.querySelector(".workspace-main__composer-dock");
    expect(
      dock?.querySelector(".workspace-main__composer-inner .composer"),
    ).toBeTruthy();
    expect(await screen.findByRole("complementary", { name: "Inspector" })).toBeTruthy();
  });

  it("shows compact project navigation and session management affordances", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    const projectSwitcher = await screen.findByRole("region", {
      name: "Project switcher",
    });
    expect(within(projectSwitcher).getByText("Project")).toBeTruthy();
    expect(await screen.findByLabelText("Switch project")).toHaveProperty(
      "value",
      "project-default",
    );
    expect(
      screen.queryByText(
        "C:/Users/lkw/Desktop/github/agent-project/ai-devflow-engine",
      ),
    ).toBeNull();
    expect(screen.getByText("C:/Users/.../ai-devflow-engine")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Load" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "New session" })).toBeTruthy();
    expect(
      screen.queryByRole("region", { name: "Current project summary" }),
    ).toBeNull();
    expect(screen.queryByText("Default delivery")).toBeNull();
    expect(screen.queryByText("Latest activity")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Default project cannot be removed" }),
    ).toHaveProperty("disabled", true);
    expect(screen.getByText("Add workspace shell")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Rename Add workspace shell" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Delete Add workspace shell blocked by active run",
      }),
    ).toHaveProperty("disabled", true);
  });

  it("keeps inline session rename and delete controls safe with a long name", async () => {
    const longName =
      "This is a very long session name that should stay on one protected row without pushing delete outside the card";
    const renamedSession = {
      ...mockSessionWorkspaces["session-running"].session,
      display_name: "Renamed protected row",
    };
    const renameFetcher = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        jsonTestResponse(renamedSession),
    );
    const handleSessionRename = vi.fn();

    render(
      <SessionList
        sessions={[
          {
            ...mockSessionWorkspaces["session-running"].session,
            display_name: longName,
          },
        ]}
        currentSessionId="session-running"
        onSessionChange={() => undefined}
        onSessionRename={handleSessionRename}
        request={{ fetcher: renameFetcher }}
      />,
    );

    const item = screen.getByRole("article", { name: `Session ${longName}` });
    const titleRow = item.querySelector(".session-list-item__title-row");
    expect(titleRow).toBeTruthy();
    expect(item.querySelector(".session-list-item__name-text")).toBeTruthy();
    expect(item.querySelector(".session-list-item__delete")).toBeTruthy();
    expect(within(titleRow as HTMLElement).getByRole("button", {
      name: `Open ${longName}`,
    })).toBeTruthy();
    expect(within(titleRow as HTMLElement).getByRole("button", {
      name: `Delete ${longName} blocked by active run`,
    })).toHaveProperty("disabled", true);

    expect(
      within(item).queryByRole("button", { name: `Rename ${longName}` }),
    ).toBeNull();

    fireEvent.doubleClick(
      within(titleRow as HTMLElement).getByRole("button", {
        name: `Open ${longName}`,
      }),
    );

    expect(
      within(item).getByRole("textbox", { name: `Rename ${longName}` }),
    ).toHaveProperty("value", longName);
    expect(
      within(item).getByRole("button", { name: "Save session name" }),
    ).toHaveProperty("disabled", true);
    expect(
      within(item).getByRole("button", { name: "Cancel rename" }),
    ).toBeTruthy();

    const renameInput = within(item).getByRole("textbox", {
      name: `Rename ${longName}`,
    });
    fireEvent.change(renameInput, { target: { value: "Renamed protected row" } });
    const renameForm = renameInput.closest("form");
    expect(renameForm).toBeTruthy();
    expect(
      within(renameForm as HTMLFormElement).getByRole("button", {
        name: "Save session name",
      }),
    ).toBeTruthy();
    fireEvent.submit(renameForm as HTMLFormElement);

    await waitFor(() => {
      expect(renameFetcher).toHaveBeenCalledWith(
        "/api/sessions/session-running",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ display_name: "Renamed protected row" }),
        }),
      );
    });
    expect(handleSessionRename).toHaveBeenCalledWith(renamedSession);
  });

  it("switches the current project and keeps shell-only destructive actions disabled", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(await screen.findByLabelText("Switch project")).toHaveProperty(
      "value",
      "project-default",
    );
    expect(
      await screen.findByRole("button", { name: "Open Blank requirement" }),
    ).toHaveProperty("ariaCurrent", "page");

    fireEvent.change(await screen.findByLabelText("Switch project"), {
      target: { value: "project-loaded" },
    });

    await waitFor(() => {
      expect(screen.getByLabelText("Switch project")).toHaveProperty(
        "value",
        "project-loaded",
      );
    });
    expect(screen.getByText("C:/work/checkout-service")).toBeTruthy();
    expect(screen.queryByText("git_auto_delivery")).toBeNull();
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
      within(runningSessionItem as HTMLElement).queryByText(/Updated/u),
    ).toBeNull();
    expect(
      within(runningSessionItem as HTMLElement).queryByText(/Current stage/u),
    ).toBeNull();
    expect(
      within(runningSessionItem as HTMLElement).getByText("09:25"),
    ).toBeTruthy();
    expect(
      within(runningSessionItem as HTMLElement).getByText("Solution Design"),
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

  it("loads a local project from the sidebar and switches to it", async () => {
    const loadedProject: ProjectRead = {
      project_id: "project-loaded-from-path",
      name: "Loaded Flow",
      root_path: "C:/work/loaded-flow",
      default_delivery_channel_id: "delivery-loaded-flow",
      is_default: false,
      created_at: "2026-05-05T08:00:00.000Z",
      updated_at: "2026-05-05T08:00:00.000Z",
    };
    const baseFetcher = createMockApiFetcher();
    const projects: ProjectRead[] = [];
    let createProjectBody: unknown = null;
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (method === "GET" && path === "/api/projects") {
          return jsonTestResponse(projects);
        }

        if (method === "POST" && path === "/api/projects") {
          createProjectBody =
            typeof init?.body === "string" ? JSON.parse(init.body) : null;
          projects.unshift(loadedProject);
          return jsonTestResponse(loadedProject, 201);
        }

        if (
          method === "GET" &&
          path === "/api/projects/project-loaded-from-path/sessions"
        ) {
          return jsonTestResponse([]);
        }

        if (
          method === "GET" &&
          path === "/api/projects/project-loaded-from-path/delivery-channel"
        ) {
          return jsonTestResponse({
            project_id: loadedProject.project_id,
            delivery_channel_id: "delivery-loaded-flow",
            delivery_mode: "demo_delivery",
            scm_provider_type: null,
            repository_identifier: null,
            default_branch: null,
            code_review_request_type: null,
            credential_ref: null,
            credential_status: "ready",
            readiness_status: "ready",
            readiness_message: null,
            last_validated_at: null,
            updated_at: "2026-05-05T08:00:00.000Z",
          });
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    fireEvent.click(await screen.findByRole("button", { name: "Load" }));
    fireEvent.change(screen.getByLabelText("Project root path"), {
      target: { value: "C:/work/loaded-flow" },
    });
    fireEvent.click(
      within(screen.getByRole("form", { name: "Load local project" })).getByRole(
        "button",
        { name: "Load" },
      ),
    );

    await waitFor(() => {
      expect(createProjectBody).toEqual({ root_path: "C:/work/loaded-flow" });
    });
    await waitFor(() => {
      expect(screen.getByLabelText("Switch project")).toHaveProperty(
        "value",
        "project-loaded-from-path",
      );
    });
    expect(screen.getByText("C:/work/loaded-flow")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New session" })).toHaveProperty(
      "disabled",
      false,
    );
  });

  it("keeps a loaded project visible through the query refresh flow", async () => {
    renderWithAppProviders(null, { route: "/console" });

    fireEvent.click(await screen.findByRole("button", { name: "Load" }));
    fireEvent.change(screen.getByLabelText("Project root path"), {
      target: { value: "C:/work/query-refresh-flow" },
    });
    fireEvent.click(
      within(screen.getByRole("form", { name: "Load local project" })).getByRole(
        "button",
        { name: "Load" },
      ),
    );

    await waitFor(() => {
      expect(screen.getByLabelText("Switch project")).toHaveProperty(
        "value",
        "project-loaded-3",
      );
    });
    expect(screen.getByText("C:/work/query-refresh-flow")).toBeTruthy();
  });

  it("persists draft template changes before the first requirement can start", async () => {
    const baseFetcher = createMockApiFetcher();
    const draftSession: SessionRead = {
      ...mockSessionWorkspaces["session-draft"].session,
    };
    const draftWorkspace: SessionWorkspaceProjection = {
      ...mockSessionWorkspaces["session-draft"],
      session: draftSession,
    };
    let templateUpdateBody: unknown = null;
    let messageBody: unknown = null;
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (method === "GET" && path === "/api/sessions/session-draft/workspace") {
          return jsonTestResponse(draftWorkspace);
        }

        if (method === "PUT" && path === "/api/sessions/session-draft/template") {
          templateUpdateBody =
            typeof init?.body === "string" ? JSON.parse(init.body) : null;
          draftSession.selected_template_id = "template-bugfix";
          draftSession.updated_at = "2026-05-05T08:10:00.000Z";
          draftWorkspace.session = draftSession;
          return jsonTestResponse(draftSession);
        }

        if (method === "POST" && path === "/api/sessions/session-draft/messages") {
          messageBody = typeof init?.body === "string" ? JSON.parse(init.body) : null;
          return baseFetcher(input, init);
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    expect(
      await screen.findByRole("region", { name: "Template empty state" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Bug 修复流程/u }));

    await waitFor(() => {
      expect(templateUpdateBody).toEqual({ template_id: "template-bugfix" });
    });
    expect(screen.getByRole("radio", { name: /Bug 修复流程/u })).toHaveProperty(
      "checked",
      true,
    );

    fireEvent.change(screen.getByLabelText("当前输入"), {
      target: { value: "Use the persisted template for this first run." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(messageBody).toEqual({
        message_type: "new_requirement",
        content: "Use the persisted template for this first run.",
      });
    });
    expect(draftSession.selected_template_id).toBe("template-bugfix");
  });

  it("keeps draft template choices disabled while a template save is pending", async () => {
    const pendingTemplateUpdate: {
      resolve?: (session: SessionRead) => void;
    } = {};
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (method === "PUT" && path === "/api/sessions/session-draft/template") {
          return new Promise<Response>((resolve) => {
            pendingTemplateUpdate.resolve = (session) =>
              resolve(jsonTestResponse(session));
          });
        }

        return createMockApiFetcher()(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    expect(
      await screen.findByRole("region", { name: "Template empty state" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Bug 修复流程/u }));

    await waitFor(() => {
      expect(pendingTemplateUpdate.resolve).toBeDefined();
    });
    expect(screen.getByRole("radio", { name: /新功能开发流程/u })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.getByRole("radio", { name: /Bug 修复流程/u })).toHaveProperty(
      "disabled",
      true,
    );

    const completeTemplateUpdate = pendingTemplateUpdate.resolve;
    if (!completeTemplateUpdate) {
      throw new Error("Template update request was not started.");
    }
    completeTemplateUpdate({
      ...mockSessionWorkspaces["session-draft"].session,
      selected_template_id: "template-bugfix",
    });

    await waitFor(() => {
      expect(screen.getByRole("radio", { name: /Bug 修复流程/u })).toHaveProperty(
        "disabled",
        false,
      );
    });
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
    expect(screen.queryByText("Inspector closed")).toBeNull();
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
      within(editor).getByLabelText("Requirement Analysis system prompt"),
    ).toBeTruthy();
    expect(within(editor).getByLabelText("Requirement Analysis provider")).toBeTruthy();

    fireEvent.change(within(editor).getByLabelText("Requirement Analysis system prompt"), {
      target: { value: "Clarify only when missing facts block implementation." },
    });

    expect(within(editor).getByText(/Unsaved edits will not affect/u)).toBeTruthy();
    expect(
      within(editor).getByRole("button", { name: "Save template" }),
    ).toBeTruthy();
    expect(document.body.textContent ?? "").not.toContain("DeliveryChannel");
    expect(document.body.textContent ?? "").not.toContain("deterministic test runtime");
  });

  it("saves a system template as a user template and binds it to the draft session", async () => {
    const baseFetcher = createMockApiFetcher();
    const saveAsBodies: PipelineTemplateWriteRequest[] = [];
    let sessionTemplateBody: unknown = null;
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (
          method === "POST" &&
          path === "/api/pipeline-templates/template-feature/save-as"
        ) {
          const saveAsBody =
            typeof init?.body === "string"
              ? (JSON.parse(init.body) as PipelineTemplateWriteRequest)
              : null;
          if (!saveAsBody) {
            return jsonTestResponse({ message: "Missing template body" }, 400);
          }
          saveAsBodies.push(saveAsBody);
          return jsonTestResponse(
            {
              ...mockPipelineTemplates.find(
                (template) => template.template_id === "template-feature",
              )!,
              ...saveAsBody,
              template_id: "template-user-saved-stage",
              template_source: "user_template",
              base_template_id: "template-feature",
              created_at: "2026-05-05T08:30:00.000Z",
              updated_at: "2026-05-05T08:30:00.000Z",
            },
            201,
          );
        }

        if (method === "PUT" && path === "/api/sessions/session-draft/template") {
          sessionTemplateBody =
            typeof init?.body === "string" ? JSON.parse(init.body) : null;
          return jsonTestResponse({
            ...mockSessionWorkspaces["session-draft"].session,
            selected_template_id: "template-user-saved-stage",
          });
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    const editor = await screen.findByRole("region", { name: "Template editor" });
    fireEvent.change(
      within(editor).getByLabelText("Requirement Analysis system prompt"),
      {
        target: { value: "Clarify the saved requirement before design." },
      },
    );
    fireEvent.click(within(editor).getByRole("tab", { name: "Solution Design" }));
    fireEvent.change(within(editor).getByLabelText("Solution Design system prompt"), {
      target: { value: "Design the saved stage only." },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Save template" }));

    await waitFor(() => {
      expect(sessionTemplateBody).toEqual({
        template_id: "template-user-saved-stage",
      });
    });
    expect(saveAsBodies).toHaveLength(1);
    expect(saveAsBodies[0].stage_role_bindings).toHaveLength(6);
    expect(saveAsBodies[0].stage_role_bindings).toEqual(
      mockPipelineTemplates
        .find((template) => template.template_id === "template-feature")!
        .stage_role_bindings.map((binding) =>
          binding.stage_type === "solution_design"
            ? { ...binding, system_prompt: "Design the saved stage only." }
            : binding.stage_type === "requirement_analysis"
              ? {
                  ...binding,
                  system_prompt: "Clarify the saved requirement before design.",
                }
            : binding,
        ),
    );
  });

  it("hides the template panel after saving and binding while Composer stays ready", async () => {
    renderWithAppProviders(
      <ConsolePage request={{ fetcher: createMockApiFetcher() }} />,
    );

    const editor = await screen.findByRole("region", { name: "Template editor" });
    fireEvent.change(within(editor).getByLabelText("Requirement Analysis system prompt"), {
      target: { value: "Clarify saved requirements before implementation." },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Save template" }));

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Template editor" })).toBeNull();
      expect(
        screen.queryByRole("region", { name: "Template empty state" }),
      ).toBeNull();
    });
    expect(screen.getByRole("form", { name: "Composer" })).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", false);
  });

  it("deletes a user template through the template API before selecting fallback", async () => {
    const userTemplate: PipelineTemplateRead = {
      ...mockPipelineTemplates[1],
      template_id: "template-user-shell-delete",
      template_source: "user_template",
      base_template_id: "template-feature",
      name: "Shell user template",
    };
    const draftSession: SessionRead = {
      ...mockSessionWorkspaces["session-draft"].session,
      selected_template_id: userTemplate.template_id,
    };
    const draftWorkspace: SessionWorkspaceProjection = {
      ...mockSessionWorkspaces["session-draft"],
      session: draftSession,
    };
    const baseFetcher = createMockApiFetcher();
    const deletedTemplateIds: string[] = [];
    const templateUpdates: unknown[] = [];
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (
          method === "GET" &&
          path === "/api/projects/project-default/sessions"
        ) {
          return jsonTestResponse(
            Object.values(mockSessionWorkspaces)
              .map((workspace) => workspace.session)
              .map((session) =>
                session.session_id === "session-draft" ? draftSession : session,
              )
              .filter((session) => session.project_id === "project-default"),
          );
        }

        if (method === "GET" && path === "/api/pipeline-templates") {
          return jsonTestResponse([...mockPipelineTemplates, userTemplate]);
        }

        if (method === "GET" && path === "/api/sessions/session-draft/workspace") {
          return jsonTestResponse(draftWorkspace);
        }

        if (
          method === "DELETE" &&
          path === "/api/pipeline-templates/template-user-shell-delete"
        ) {
          deletedTemplateIds.push(userTemplate.template_id);
          return new Response(null, { status: 204 });
        }

        if (method === "PUT" && path === "/api/sessions/session-draft/template") {
          templateUpdates.push(
            typeof init?.body === "string" ? JSON.parse(init.body) : null,
          );
          draftSession.selected_template_id = "template-feature";
          draftWorkspace.session = draftSession;
          return jsonTestResponse(draftSession);
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    const editor = await screen.findByRole("region", { name: "Template editor" });
    expect(await screen.findByRole("heading", { name: "Shell user template" })).toBeTruthy();
    fireEvent.click(within(editor).getByRole("button", { name: "Delete template" }));

    await waitFor(() => {
      expect(deletedTemplateIds).toEqual(["template-user-shell-delete"]);
      expect(templateUpdates).toEqual([{ template_id: "template-feature" }]);
    });
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

  it("keeps first requirement input available when no provider is configured", async () => {
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

    expect(await screen.findByText("No provider configured.")).toBeTruthy();
    expect(document.body.textContent ?? "").not.toContain("provider-deepseek");
    const input = screen.getByLabelText("当前输入");
    expect(input).toHaveProperty("disabled", false);
    fireEvent.change(input, { target: { value: "Start with the bound template." } });
    expect(screen.getByRole("button", { name: "发送" })).toHaveProperty(
      "disabled",
      false,
    );
  });

  it("keeps first requirement input available when configured providers do not include the selected template binding", async () => {
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
    const providerSelect = within(editor).getByLabelText("Requirement Analysis provider");
    await waitFor(() => {
      expect(providerSelect).toHaveProperty("value", "provider-deepseek");
    });
    expect(
      within(providerSelect).getByRole("option", { name: "MiMo" }),
    ).toBeTruthy();
    expect(
      within(providerSelect).getByRole("option", {
        name: "Unavailable provider",
      }),
    ).toBeTruthy();
    expect(
      screen.getAllByText(
        "This template references unavailable providers.",
      ),
    ).toHaveLength(1);
    expect(document.body.textContent ?? "").not.toContain("provider-deepseek");

    const input = screen.getByLabelText("当前输入");
    expect(input).toHaveProperty("disabled", false);
    fireEvent.change(input, { target: { value: "Send with current template." } });
    expect(screen.getByRole("button", { name: "发送" })).toHaveProperty(
      "disabled",
      false,
    );
  });

  it("sends a draft requirement without persisting unsaved template edits", async () => {
    const baseFetcher = createMockApiFetcher();
    let messageBody: unknown = null;
    let templateSaveCalls = 0;
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (method === "POST" && path === "/api/sessions/session-draft/messages") {
          messageBody = typeof init?.body === "string" ? JSON.parse(init.body) : null;
        }

        if (
          path.startsWith("/api/pipeline-templates/") &&
          (method === "POST" || method === "PATCH")
        ) {
          templateSaveCalls += 1;
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    const editor = await screen.findByRole("region", { name: "Template editor" });
    fireEvent.change(within(editor).getByLabelText("Requirement Analysis system prompt"), {
      target: { value: "This unsaved edit should not be saved before sending." },
    });
    expect(within(editor).getByText(/Unsaved edits will not affect/u)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("当前输入"), {
      target: { value: "Start from the currently selected template." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(messageBody).toEqual({
        message_type: "new_requirement",
        content: "Start from the currently selected template.",
      });
    });
    expect(templateSaveCalls).toBe(0);
  });

  it("surfaces draft Composer submit failures without hiding the editable input", async () => {
    const baseFetcher = createMockApiFetcher();
    const request: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const path = normalizeTestPath(input);
        const method = init?.method ?? "GET";

        if (method === "POST" && path === "/api/sessions/session-draft/messages") {
          return jsonTestResponse(
            {
              error_code: "validation_error",
              message: "Provider is unavailable for the selected template.",
              request_id: "req-workspace-provider",
            },
            422,
          );
        }

        return baseFetcher(input, init);
      },
    };

    renderWithAppProviders(<ConsolePage request={request} />);

    const input = await screen.findByLabelText("当前输入");
    fireEvent.change(input, {
      target: { value: "Start with invalid provider configuration." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(
      await screen.findByText("Provider is unavailable for the selected template."),
    ).toBeTruthy();
    expect(screen.getByText("Request req-workspace-provider")).toBeTruthy();
    expect(screen.getByLabelText("当前输入")).toHaveProperty(
      "value",
      "Start with invalid provider configuration.",
    );
    expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", false);
  });

  it("keeps Composer send-enabled for waiting clarification sessions", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Clarify provider behavior",
      }),
    );

    expect(await screen.findByRole("button", { name: "发送" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "暂停当前运行" })).toBeNull();
    expect(screen.queryByText(/等待你的澄清回复/u)).toBeNull();
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
