import type { ApiRequestOptions } from "../api/client";
import type { MessageFeedEntry, SessionWorkspaceProjection } from "../api/types";
import {
  mockApiError,
  mockControlItemInspectorProjection,
  mockConfigurationPackageExport,
  mockConfigurationPackageImportFieldError,
  mockConfigurationPackageImportSuccess,
  mockDeliveryResultDetailProjection,
  mockGitProjectDeliveryChannel,
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
  fetcher: async (input, init) => createMockApiFetcher()(input, init),
};

function createMockRoutes(
  options: MockApiFetcherOptions,
  workspaces: Record<string, SessionWorkspaceProjection>,
): MockRoute[] {
  return [
    route("GET", /^\/api\/projects$/u, () => jsonResponse(mockProjectList)),
    route("GET", /^\/api\/projects\/([^/]+)\/sessions$/u, ([, projectId]) =>
      jsonResponse(mockSessionList.filter((session) => session.project_id === projectId)),
    ),
    route("GET", /^\/api\/pipeline-templates$/u, () =>
      jsonResponse(mockPipelineTemplates),
    ),
    route("GET", /^\/api\/providers$/u, () => jsonResponse(mockProviderList)),
    route("GET", /^\/api\/stages\/stage-solution-design-running\/inspector$/u, () =>
      jsonResponse(mockStageInspectorProjection),
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
    route("GET", /^\/api\/projects\/project-default\/delivery-channel$/u, () =>
      jsonResponse(mockProjectDeliveryChannel),
    ),
    route("GET", /^\/api\/projects\/project-loaded\/delivery-channel$/u, () =>
      jsonResponse(mockGitProjectDeliveryChannel),
    ),
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
