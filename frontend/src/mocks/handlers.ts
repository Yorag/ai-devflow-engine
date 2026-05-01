import type { ApiRequestOptions } from "../api/client";
import {
  mockApiError,
  mockConfigurationPackageExport,
  mockConfigurationPackageImportFieldError,
  mockConfigurationPackageImportSuccess,
  mockGitProjectDeliveryChannel,
  mockPipelineTemplates,
  mockProjectDeliveryChannel,
  mockProjectList,
  mockProviderList,
  mockRunTimelines,
  mockSessionList,
  mockSessionWorkspaces,
} from "./fixtures";

type MockRoute = {
  method: string;
  pattern: RegExp;
  respond: (match: RegExpExecArray, init?: RequestInit) => Response;
};

export type MockApiFetcherOptions = {
  configurationImportMode?: "success" | "field_error";
};

export function createMockApiFetcher(
  options: MockApiFetcherOptions = {},
): typeof fetch {
  const routes = createMockRoutes(options);

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

function createMockRoutes(options: MockApiFetcherOptions): MockRoute[] {
  return [
    route("GET", /^\/api\/projects$/u, () => jsonResponse(mockProjectList)),
    route("GET", /^\/api\/projects\/([^/]+)\/sessions$/u, ([, projectId]) =>
      jsonResponse(mockSessionList.filter((session) => session.project_id === projectId)),
    ),
    route("GET", /^\/api\/pipeline-templates$/u, () =>
      jsonResponse(mockPipelineTemplates),
    ),
    route("GET", /^\/api\/providers$/u, () => jsonResponse(mockProviderList)),
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
      const workspace = mockSessionWorkspaces[sessionId];
      return workspace
        ? jsonResponse(workspace)
        : jsonResponse(mockApiError("not_found"), 404);
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

function normalizePath(input: RequestInfo | URL): string {
  const raw = typeof input === "string" ? input : input.toString();
  if (/^https?:\/\//u.test(raw)) {
    const url = new URL(raw);
    return `${url.pathname}${url.search}`;
  }

  return raw;
}
