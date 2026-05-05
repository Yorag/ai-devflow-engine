import type { ApiRequestOptions } from "../api/client";
import type {
  MessageFeedEntry,
  ProjectDeliveryChannelDetailProjection,
  ProjectRead,
  SessionRead,
  SessionWorkspaceProjection,
} from "../api/types";
import {
  mockApiError,
  mockCodeGenerationInspectorProjection,
  mockControlItemInspectorProjection,
  mockConfigurationPackageExport,
  mockConfigurationPackageImportFieldError,
  mockConfigurationPackageImportSuccess,
  mockDeliveryResultDetailProjection,
  mockGitProjectDeliveryChannel,
  mockGitDeliveryResultDetailProjection,
  mockPipelineTemplates,
  mockProjectDeliveryChannel,
  mockProjectList,
  mockProviderList,
  mockRunTimelines,
  mockSessionList,
  mockStageInspectorProjection,
  mockSessionWorkspaces,
  mockToolConfirmationInspectorProjection,
} from "./fixtures";

type MockRoute = {
  method: string;
  pattern: RegExp;
  respond: (match: RegExpExecArray, init?: RequestInit) => Response;
};

export type MockApiFetcherOptions = {
  configurationImportMode?: "success" | "field_error";
  persistSessionMessages?: boolean;
};

export function createMockApiFetcher(
  options: MockApiFetcherOptions = {},
): typeof fetch {
  const workspaces = cloneMockSessionWorkspaces();
  const routes = createMockRoutes(options, workspaces);

  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const method = init?.method ?? "GET";
    const path = normalizePath(input);

    for (const route of routes) {
      const match = route.pattern.exec(path);
      if (route.method === method && match) {
        return route.respond(match, init);
      }
    }

    return jsonResponse(mockApiError("not_found"), 404);
  };
}

export const mockApiRequestOptions: ApiRequestOptions = {
  fetcher: createMockApiFetcher(),
};

export function resetMockApiRequestOptions(): void {
  mockApiRequestOptions.fetcher = createMockApiFetcher();
}

function createMockRoutes(
  options: MockApiFetcherOptions,
  workspaces: Record<string, SessionWorkspaceProjection>,
): MockRoute[] {
  const projects = mockProjectList.map((project) => ({ ...project }));
  const sessions = mockSessionList.map((session) => ({ ...session }));

  return [
    route("GET", /^\/api\/projects$/u, () => jsonResponse(projects)),
    route("POST", /^\/api\/projects$/u, (_match, init) => {
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : null;
      const rootPath =
        body && typeof body.root_path === "string" ? body.root_path.trim() : "";
      if (!rootPath) {
        return jsonResponse(mockApiError("validation_error"), 422);
      }

      const existingProject = projects.find(
        (project) => project.root_path === rootPath,
      );
      if (existingProject) {
        return jsonResponse(existingProject, 201);
      }

      const project = createMockProject(rootPath, projects.length + 1);
      projects.unshift(project);
      return jsonResponse(project, 201);
    }),
    route("GET", /^\/api\/projects\/([^/]+)\/sessions$/u, ([, projectId]) =>
      jsonResponse(sessions.filter((session) => session.project_id === projectId)),
    ),
    route("POST", /^\/api\/projects\/([^/]+)\/sessions$/u, ([, projectId]) => {
      const project = projects.find(
        (candidate) => candidate.project_id === projectId,
      );
      if (!project) {
        return jsonResponse(mockApiError("not_found"), 404);
      }

      const createdSession = createMockDraftSession(projectId, sessions.length + 1);
      sessions.unshift(createdSession);
      workspaces[createdSession.session_id] = createMockDraftWorkspace(
        createdSession,
        projects,
      );
      return jsonResponse(createdSession);
    }),
    route("GET", /^\/api\/pipeline-templates$/u, () =>
      jsonResponse(mockPipelineTemplates),
    ),
    route("GET", /^\/api\/providers$/u, () => jsonResponse(mockProviderList)),
    route("GET", /^\/api\/stages\/stage-solution-design-running\/inspector$/u, () =>
      jsonResponse(mockStageInspectorProjection),
    ),
    route("GET", /^\/api\/stages\/stage-code-generation-running\/inspector$/u, () =>
      jsonResponse(mockCodeGenerationInspectorProjection),
    ),
    route("GET", /^\/api\/control-records\/control-clarification$/u, () =>
      jsonResponse(mockControlItemInspectorProjection),
    ),
    route("GET", /^\/api\/tool-confirmations\/tool-confirmation-1$/u, () =>
      jsonResponse(mockToolConfirmationInspectorProjection),
    ),
    route("POST", /^\/api\/tool-confirmations\/tool-confirmation-1\/allow$/u, () =>
      jsonResponse({
        tool_confirmation: {
          ...mockToolConfirmationFeedEntry(),
          status: "allowed",
          decision: "allowed",
          responded_at: "2026-05-01T09:21:00.000Z",
          is_actionable: false,
        },
      }),
    ),
    route("POST", /^\/api\/tool-confirmations\/tool-confirmation-1\/deny$/u, () =>
      jsonResponse({
        tool_confirmation: {
          ...mockToolConfirmationFeedEntry(),
          status: "denied",
          decision: "denied",
          responded_at: "2026-05-01T09:21:00.000Z",
          is_actionable: false,
          deny_followup_action: "run_failed",
          deny_followup_summary:
            "The current run will fail because no low-risk alternative path exists.",
        },
      }),
    ),
    route("GET", /^\/api\/delivery-records\/delivery-record-1$/u, () =>
      jsonResponse(mockDeliveryResultDetailProjection),
    ),
    route("GET", /^\/api\/delivery-records\/delivery-record-git-1$/u, () =>
      jsonResponse(mockGitDeliveryResultDetailProjection),
    ),
    route("GET", /^\/api\/projects\/([^/]+)\/delivery-channel$/u, ([, projectId]) => {
      if (!projects.some((project) => project.project_id === projectId)) {
        return jsonResponse(mockApiError("not_found"), 404);
      }

      return jsonResponse(createMockDeliveryChannel(projectId));
    }),
    route(
      "GET",
      /^\/api\/projects\/[^/]+\/configuration-package\/export$/u,
      () => jsonResponse(mockConfigurationPackageExport),
    ),
    route(
      "POST",
      /^\/api\/projects\/[^/]+\/configuration-package\/import$/u,
      () =>
        jsonResponse(
          options.configurationImportMode === "field_error"
            ? mockConfigurationPackageImportFieldError
            : mockConfigurationPackageImportSuccess,
        ),
    ),
    route("GET", /^\/api\/sessions\/([^/]+)\/workspace$/u, ([, sessionId]) => {
      const workspace = workspaces[sessionId];
      return workspace
        ? jsonResponse(workspace)
        : jsonResponse(mockApiError("not_found"), 404);
    }),
    route("PUT", /^\/api\/sessions\/([^/]+)\/template$/u, ([, sessionId], init) => {
      const session = sessions.find((candidate) => candidate.session_id === sessionId);
      const workspace = workspaces[sessionId];
      if (!session || !workspace) {
        return jsonResponse(mockApiError("not_found"), 404);
      }
      if (session.status !== "draft" || session.current_run_id) {
        return jsonResponse(mockApiError("validation_error"), 409);
      }

      const body = typeof init?.body === "string" ? JSON.parse(init.body) : null;
      const templateId =
        body && typeof body.template_id === "string" ? body.template_id : "";
      if (
        !mockPipelineTemplates.some((template) => template.template_id === templateId)
      ) {
        return jsonResponse(mockApiError("validation_error"), 422);
      }

      const updatedSession = {
        ...session,
        selected_template_id: templateId,
        updated_at: "2026-05-05T08:10:00.000Z",
      };
      Object.assign(session, updatedSession);
      workspaces[sessionId] = {
        ...workspace,
        session: updatedSession,
      };

      return jsonResponse(updatedSession);
    }),
    route("POST", /^\/api\/sessions\/([^/]+)\/runs$/u, ([, sessionId]) => {
      const workspace = workspaces[sessionId];
      if (!workspace || !workspace.current_run_id) {
        return jsonResponse(mockApiError("not_found"), 404);
      }
      const currentRun = workspace.runs.find(
        (run) => run.run_id === workspace.current_run_id,
      );
      const isTerminalRerunSource =
        (workspace.session.status === "failed" ||
          workspace.session.status === "terminated") &&
        (currentRun?.status === "failed" || currentRun?.status === "terminated");
      if (!isTerminalRerunSource) {
        return jsonResponse(
          mockApiError("validation_error", {
            message: "Rerun is available only for failed or terminated runs.",
          }),
          409,
        );
      }

      const nextAttemptIndex =
        Math.max(0, ...workspace.runs.map((run) => run.attempt_index)) + 1;
      const newRunId = `${workspace.current_run_id}-retry-${nextAttemptIndex}`;
      const startedAt = "2026-05-04T09:00:00.000Z";
      const nextRun: SessionWorkspaceProjection["runs"][number] = {
        run_id: newRunId,
        attempt_index: nextAttemptIndex,
        status: "running",
        trigger_source: "retry",
        started_at: startedAt,
        ended_at: null,
        current_stage_type: "requirement_analysis",
        is_active: true,
      };

      workspaces[sessionId] = {
        ...workspace,
        session: {
          ...workspace.session,
          status: "running",
          current_run_id: newRunId,
          latest_stage_type: "requirement_analysis",
          updated_at: startedAt,
        },
        runs: [
          ...workspace.runs.map((run) => ({ ...run, is_active: false })),
          nextRun,
        ],
        current_run_id: newRunId,
        current_stage_type: "requirement_analysis",
        composer_state: {
          mode: "running",
          is_input_enabled: false,
          primary_action: "pause",
          secondary_actions: ["terminate"],
          bound_run_id: newRunId,
        },
      };

      return jsonResponse({
        session: workspaces[sessionId].session,
        run: nextRun,
      });
    }),
    route("POST", /^\/api\/sessions\/([^/]+)\/messages$/u, ([, sessionId], init) => {
      const workspace = workspaces[sessionId];
      if (!workspace) {
        return jsonResponse(mockApiError("not_found"), 404);
      }

      const body = typeof init?.body === "string" ? JSON.parse(init.body) : null;
      const content = body && typeof body.content === "string" ? body.content : "";
      const messageType =
        body && body.message_type === "clarification_reply"
          ? "clarification_reply"
          : "new_requirement";
      const messageItem: MessageFeedEntry = {
        entry_id: `entry-${sessionId}-${messageType}`,
        run_id: workspace.current_run_id ?? `draft-${sessionId}`,
        type: "user_message",
        occurred_at: "2026-05-03T09:45:00.000Z",
        message_id: `message-${sessionId}-${messageType}`,
        author: "user",
        content,
        stage_run_id: null,
      };
      const nextWorkspace = options.persistSessionMessages
        ? appendMockMessageToWorkspace(workspace, messageItem)
        : workspace;
      if (options.persistSessionMessages) {
        workspaces[sessionId] = nextWorkspace;
      }

      return jsonResponse({
        session: nextWorkspace.session,
        message_item: messageItem,
      });
    }),
    route("GET", /^\/api\/runs\/([^/?]+)\/timeline(?:\?.*)?$/u, ([, runId]) => {
      const timeline = mockRunTimelines[runId];
      return timeline
        ? jsonResponse(timeline)
        : jsonResponse(mockApiError("not_found"), 404);
    }),
  ];
}

function route(
  method: string,
  pattern: RegExp,
  respond: MockRoute["respond"],
): MockRoute {
  return { method, pattern, respond };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function createMockProject(rootPath: string, index: number): ProjectRead {
  const timestamp = "2026-05-05T08:00:00.000Z";
  return {
    project_id: `project-loaded-${index}`,
    name: projectNameFromRoot(rootPath),
    root_path: rootPath,
    default_delivery_channel_id: `delivery-loaded-${index}`,
    is_default: false,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function projectNameFromRoot(rootPath: string): string {
  const leaf = rootPath.split(/[\\/]/u).filter(Boolean).pop() ?? rootPath;
  const normalized = leaf.trim();
  if (!normalized) {
    return "Loaded project";
  }

  return normalized
    .split(/[-_\s]+/u)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function createMockDeliveryChannel(
  projectId: string,
): ProjectDeliveryChannelDetailProjection {
  if (projectId === "project-loaded") {
    return { ...mockGitProjectDeliveryChannel };
  }

  return {
    ...mockProjectDeliveryChannel,
    project_id: projectId,
    delivery_channel_id:
      projectId === "project-default"
        ? mockProjectDeliveryChannel.delivery_channel_id
        : `delivery-${projectId}`,
  };
}

function createMockDraftSession(projectId: string, index: number): SessionRead {
  const timestamp = "2026-05-05T07:30:00.000Z";
  return {
    session_id: `session-created-${index}`,
    project_id: projectId,
    display_name: "Untitled requirement",
    status: "draft",
    selected_template_id: "template-feature",
    current_run_id: null,
    latest_stage_type: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function createMockDraftWorkspace(
  session: SessionRead,
  projects: ProjectRead[] = mockProjectList,
): SessionWorkspaceProjection {
  const draftWorkspace = mockSessionWorkspaces["session-draft"];
  const project =
    projects.find((candidate) => candidate.project_id === session.project_id) ??
    draftWorkspace.project;
  const deliveryChannel =
    createMockDeliveryChannel(session.project_id);

  return {
    ...draftWorkspace,
    session,
    project,
    delivery_channel: deliveryChannel,
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

function mockToolConfirmationFeedEntry() {
  return mockSessionWorkspaces["session-running"].narrative_feed.find(
    (entry) => entry.type === "tool_confirmation",
  ) ?? {
    entry_id: "entry-tool-confirmation",
    run_id: "run-running",
    type: "tool_confirmation",
    occurred_at: "2026-05-01T09:20:00.000Z",
    stage_run_id: "stage-code-generation-running",
    tool_confirmation_id: "tool-confirmation-1",
    status: "pending",
    title: "Allow dependency install",
    tool_name: "bash",
    command_preview: "npm install",
    target_summary: "frontend/package-lock.json",
    risk_level: "high_risk",
    risk_categories: ["dependency_change", "network_download"],
    reason: "Installing dependencies changes lock files and downloads packages.",
    expected_side_effects: ["package-lock update"],
    allow_action: "allow_once",
    deny_action: "deny_once",
    is_actionable: true,
    requested_at: "2026-05-01T09:20:00.000Z",
    responded_at: null,
    decision: null,
    deny_followup_action: null,
    deny_followup_summary: null,
    disabled_reason: null,
  };
}

function cloneMockSessionWorkspaces(): Record<string, SessionWorkspaceProjection> {
  return Object.fromEntries(
    Object.entries(mockSessionWorkspaces).map(([sessionId, workspace]) => [
      sessionId,
      {
        ...workspace,
        session: { ...workspace.session },
        project: { ...workspace.project },
        delivery_channel: workspace.delivery_channel
          ? { ...workspace.delivery_channel }
          : null,
        runs: workspace.runs.map((run) => ({ ...run })),
        narrative_feed: workspace.narrative_feed.map((entry) => ({ ...entry })),
        composer_state: { ...workspace.composer_state },
      },
    ]),
  );
}

function appendMockMessageToWorkspace(
  workspace: SessionWorkspaceProjection,
  messageItem: MessageFeedEntry,
): SessionWorkspaceProjection {
  const existingRun = workspace.runs.some((run) => run.run_id === messageItem.run_id);
  const startsFromDraft = workspace.session.status === "draft";
  const resumesClarification = workspace.session.status === "waiting_clarification";
  const initialRun =
    workspace.runs.length === 0 && startsFromDraft
      ? [
          {
            run_id: messageItem.run_id,
            attempt_index: 1,
            status: "running" as const,
            trigger_source: "initial_requirement" as const,
            started_at: messageItem.occurred_at,
            ended_at: null,
            current_stage_type: "requirement_analysis" as const,
            is_active: true,
          },
        ]
      : [];

  return {
    ...workspace,
    session: {
      ...workspace.session,
      status:
        startsFromDraft || resumesClarification
          ? "running"
          : workspace.session.status,
      current_run_id: workspace.current_run_id ?? messageItem.run_id,
      latest_stage_type:
        workspace.session.latest_stage_type ??
        (startsFromDraft ? "requirement_analysis" : null),
      updated_at: messageItem.occurred_at,
    },
    runs: existingRun ? workspace.runs : [...workspace.runs, ...initialRun],
    narrative_feed: [...workspace.narrative_feed, messageItem],
    current_run_id: workspace.current_run_id ?? messageItem.run_id,
    current_stage_type:
      workspace.current_stage_type ??
      (startsFromDraft ? "requirement_analysis" : null),
    composer_state: {
      ...workspace.composer_state,
      mode:
        startsFromDraft || resumesClarification
          ? "running"
          : workspace.composer_state.mode,
      is_input_enabled:
        startsFromDraft || resumesClarification
          ? false
          : workspace.composer_state.is_input_enabled,
      primary_action:
        startsFromDraft || resumesClarification
          ? "pause"
          : workspace.composer_state.primary_action,
      secondary_actions:
        startsFromDraft || resumesClarification
          ? ["terminate"]
          : workspace.composer_state.secondary_actions,
      bound_run_id: workspace.current_run_id ?? messageItem.run_id,
    },
  };
}

function normalizePath(input: RequestInfo | URL): string {
  const raw = typeof input === "string" ? input : input.toString();
  if (/^https?:\/\//u.test(raw)) {
    const url = new URL(raw);
    return `${url.pathname}${url.search}`;
  }

  return raw;
}
