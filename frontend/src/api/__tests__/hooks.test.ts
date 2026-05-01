import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { listProjectSessions, listProjects } from "../hooks";
import { getSessionWorkspace } from "../query";

import { useProjectsQuery, useSessionWorkspaceQuery } from "../hooks";
import {
  mockApiError,
  mockConfigurationPackageExport,
  mockConfigurationPackageImportFieldError,
  mockConfigurationPackageImportSuccess,
  mockDeletedSession,
  mockFeedEntriesByType,
  mockProjectList,
  mockRemovedProject,
  mockSessionList,
  mockSessionWorkspace,
  mockSessionWorkspaces,
} from "../../mocks/fixtures";
import { createMockApiFetcher, mockApiRequestOptions } from "../../mocks/handlers";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
      },
    },
  });

  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("F2.2 mock fixtures", () => {
  it("covers required session states and top-level feed entry contracts", () => {
    expect(Object.keys(mockSessionWorkspaces).sort()).toEqual([
      "session-completed",
      "session-draft",
      "session-failed",
      "session-running",
      "session-terminated",
      "session-waiting-approval",
      "session-waiting-clarification",
    ]);

    expect(
      Object.values(mockSessionWorkspaces).map((workspace) => workspace.session.status),
    ).toEqual([
      "draft",
      "running",
      "waiting_clarification",
      "waiting_approval",
      "completed",
      "failed",
      "terminated",
    ]);

    expect(Object.keys(mockFeedEntriesByType).sort()).toEqual([
      "approval_request",
      "approval_result",
      "control_item",
      "delivery_result",
      "stage_node",
      "system_status",
      "tool_confirmation",
      "user_message",
    ]);
    expect(mockFeedEntriesByType.approval_request.type).toBe("approval_request");
    expect(mockFeedEntriesByType.approval_result.type).toBe("approval_result");
    expect(mockFeedEntriesByType.delivery_result.type).toBe("delivery_result");
  });

  it("keeps removed projects and deleted sessions out of regular lists", () => {
    expect(mockProjectList.map((project) => project.project_id)).not.toContain(
      mockRemovedProject.project_id,
    );
    expect(mockSessionList.map((session) => session.session_id)).not.toContain(
      mockDeletedSession.session_id,
    );
    expect(mockSessionList).toContainEqual(
      expect.objectContaining({
        session_id: "session-completed",
        display_name: "Renamed checkout flow fix",
      }),
    );
  });

  it("exposes config and configuration package fixtures without forbidden fields", () => {
    expect(mockApiError("config_invalid_value", { field: "delivery_mode" })).toEqual({
      error_code: "config_invalid_value",
      code: "config_invalid_value",
      message: "Configuration value is invalid.",
      request_id: "mock-request-config-invalid-value",
      field_errors: [{ field: "delivery_mode", message: "Invalid value." }],
    });
    expect(mockApiError("config_hard_limit_exceeded").code).toBe(
      "config_hard_limit_exceeded",
    );
    expect(mockConfigurationPackageImportSuccess.changed_objects?.length).toBeGreaterThan(0);
    expect(mockConfigurationPackageImportFieldError.field_errors).toEqual([
      { field: "providers[0].default_model_id", message: "Model is not listed." },
    ]);

    const serialized = JSON.stringify(mockConfigurationPackageExport);
    expect(serialized).not.toContain("api_key_value");
    expect(serialized).not.toContain("compression_threshold_ratio");
    expect(serialized).not.toContain("PlatformRuntimeSettings");
    expect(serialized).not.toContain("runtime_snapshot");
    expect(serialized).not.toContain("audit");
    expect(serialized).not.toContain("logs");
  });
});

describe("F2.2 mock API handlers", () => {
  it("serves canonical F2.1 API client paths from mock fixtures", async () => {
    const fetcher = createMockApiFetcher();

    await expect(listProjects({ fetcher })).resolves.toEqual(mockProjectList);
    await expect(
      listProjectSessions("project-default", { fetcher }),
    ).resolves.toEqual(mockSessionList);
    await expect(
      getSessionWorkspace("session-draft", { fetcher }),
    ).resolves.toEqual(mockSessionWorkspace);
  });

  it("returns unified mock errors for unknown paths", async () => {
    const response = await createMockApiFetcher()("/api/missing", { method: "GET" });

    await expect(response.json()).resolves.toMatchObject({
      code: "not_found",
      message: "Mock route not found.",
      request_id: "mock-request-not-found",
    });
    expect(response.status).toBe(404);
  });
});

describe("F2.2 query hooks", () => {
  it("loads project fixtures through useProjectsQuery", async () => {
    const { result } = renderHook(
      () => useProjectsQuery({ request: mockApiRequestOptions }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockProjectList);
  });

  it("loads session workspace fixtures through useSessionWorkspaceQuery", async () => {
    const { result } = renderHook(
      () => useSessionWorkspaceQuery("session-running", { request: mockApiRequestOptions }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.session.session_id).toBe("session-running");
    expect(result.current.data?.narrative_feed).toContainEqual(
      expect.objectContaining({ type: "stage_node" }),
    );
  });
});
