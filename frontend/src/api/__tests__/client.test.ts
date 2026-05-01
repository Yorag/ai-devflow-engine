import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiRequestError,
  CONFIG_ERROR_CODES,
  apiRequest,
  createEventSource,
  isConfigErrorCode,
} from "../client";

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: {
      "content-type": "application/json",
      ...(init.headers ?? {}),
    },
  });
}

describe("apiRequest", () => {
  it("serializes JSON bodies and resolves typed JSON responses", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(input).toBe("/api/projects");
        expect(init?.method).toBe("POST");
        expect(init?.headers).toEqual({ "content-type": "application/json" });
        expect(init?.body).toBe(JSON.stringify({ root_path: "C:/repo/app" }));
        return jsonResponse({ project_id: "project-1", name: "App" });
      },
    );

    const result = await apiRequest<{ project_id: string; name: string }>(
      "/api/projects",
      {
        method: "POST",
        body: { root_path: "C:/repo/app" },
        fetcher: fetchMock,
      },
    );

    expect(result).toEqual({ project_id: "project-1", name: "App" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves unified backend errors with request id and field details", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(
        {
          error_code: "config_invalid_value",
          code: "config_invalid_value",
          message: "Configuration value is invalid.",
          request_id: "req-1",
          field_errors: [{ field: "delivery_mode", message: "Invalid mode." }],
        },
        { status: 422 },
      ),
    );

    await expect(
      apiRequest("/api/projects/project-1/delivery-channel", {
        method: "PUT",
        body: { delivery_mode: "bad" },
        fetcher: fetchMock,
      }),
    ).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 422,
      code: "config_invalid_value",
      message: "Configuration value is invalid.",
      requestId: "req-1",
      fieldErrors: [{ field: "delivery_mode", message: "Invalid mode." }],
    });
  });

  it("recognizes all reserved configuration error codes", () => {
    expect(CONFIG_ERROR_CODES).toEqual([
      "config_invalid_value",
      "config_hard_limit_exceeded",
      "config_version_conflict",
      "config_storage_unavailable",
      "config_snapshot_unavailable",
    ]);
    expect(isConfigErrorCode("config_snapshot_unavailable")).toBe(true);
    expect(isConfigErrorCode("validation_error")).toBe(false);
  });
});

describe("createEventSource", () => {
  it("normalizes API base URL and session event stream path", () => {
    const OriginalEventSource = globalThis.EventSource;
    const eventSourceSpy = vi.fn(function MockEventSource(
      this: EventSource,
      url: string,
    ) {
      Object.defineProperty(this, "url", { value: url });
    });

    vi.stubGlobal("EventSource", eventSourceSpy);

    const source = createEventSource("/api/sessions/session-1/events/stream", {
      baseUrl: "http://localhost:8000/api/",
    });

    expect(eventSourceSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/sessions/session-1/events/stream",
    );
    expect((source as EventSource).url).toBe(
      "http://localhost:8000/api/sessions/session-1/events/stream",
    );

    vi.stubGlobal("EventSource", OriginalEventSource);
  });
});

describe("resource clients", () => {
  it("uses canonical control-plane paths for project, session, and template commands", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ input, init });
        return jsonResponse({});
      },
    );

    const { listProjects, createProject, removeProject } = await import(
      "../projects"
    );
    const {
      createSession,
      listProjectSessions,
      getSession,
      renameSession,
      deleteSession,
      updateSessionTemplate,
      appendSessionMessage,
    } = await import("../sessions");
    const {
      listPipelineTemplates,
      getPipelineTemplate,
      saveAsPipelineTemplate,
      patchPipelineTemplate,
      deletePipelineTemplate,
    } = await import("../templates");

    await listProjects({ fetcher: fetchMock });
    await createProject({ root_path: "C:/repo/app" }, { fetcher: fetchMock });
    await removeProject("project-1", { fetcher: fetchMock });
    await createSession("project-1", { fetcher: fetchMock });
    await listProjectSessions("project-1", { fetcher: fetchMock });
    await getSession("session-1", { fetcher: fetchMock });
    await renameSession(
      "session-1",
      { display_name: "Renamed" },
      { fetcher: fetchMock },
    );
    await deleteSession("session-1", { fetcher: fetchMock });
    await updateSessionTemplate(
      "session-1",
      { template_id: "template-1" },
      { fetcher: fetchMock },
    );
    await appendSessionMessage(
      "session-1",
      { message_type: "new_requirement", content: "Build it." },
      { fetcher: fetchMock },
    );
    await listPipelineTemplates({ fetcher: fetchMock });
    await getPipelineTemplate("template-1", { fetcher: fetchMock });
    await saveAsPipelineTemplate(
      "template-1",
      {
        name: "Custom",
        stage_role_bindings: [],
        auto_regression_enabled: true,
        max_auto_regression_retries: 1,
      },
      { fetcher: fetchMock },
    );
    await patchPipelineTemplate(
      "template-1",
      {
        name: "Custom",
        stage_role_bindings: [],
        auto_regression_enabled: true,
        max_auto_regression_retries: 1,
      },
      { fetcher: fetchMock },
    );
    await deletePipelineTemplate("template-1", { fetcher: fetchMock });

    expect(calls.map((call) => [call.init?.method ?? "GET", call.input])).toEqual([
      ["GET", "/api/projects"],
      ["POST", "/api/projects"],
      ["DELETE", "/api/projects/project-1"],
      ["POST", "/api/projects/project-1/sessions"],
      ["GET", "/api/projects/project-1/sessions"],
      ["GET", "/api/sessions/session-1"],
      ["PATCH", "/api/sessions/session-1"],
      ["DELETE", "/api/sessions/session-1"],
      ["PUT", "/api/sessions/session-1/template"],
      ["POST", "/api/sessions/session-1/messages"],
      ["GET", "/api/pipeline-templates"],
      ["GET", "/api/pipeline-templates/template-1"],
      ["POST", "/api/pipeline-templates/template-1/save-as"],
      ["PATCH", "/api/pipeline-templates/template-1"],
      ["DELETE", "/api/pipeline-templates/template-1"],
    ]);
  });

  it("uses canonical provider, delivery, run, approval, query, and event paths", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ input, init });
        return jsonResponse({});
      },
    );

    const { listProviders, getProvider, createProvider, patchProvider } =
      await import("../providers");
    const {
      getProjectDeliveryChannel,
      updateProjectDeliveryChannel,
      validateProjectDeliveryChannel,
    } = await import("../delivery-channels");
    const {
      exportProjectConfigurationPackage,
      importProjectConfigurationPackage,
    } = await import("../configuration-package");
    const {
      getRun,
      getRunTimeline,
      createRerun,
      pauseRun,
      resumeRun,
      terminateRun,
    } = await import("../runs");
    const { approveApproval, rejectApproval } = await import("../approvals");
    const {
      getSessionWorkspace,
      getStageInspector,
      getControlRecord,
      getToolConfirmation,
      getDeliveryRecord,
      getRunLogs,
    } = await import("../query");
    const { createSessionEventSource } = await import("../events");

    await listProviders({ fetcher: fetchMock });
    await getProvider("provider-1", { fetcher: fetchMock });
    await createProvider(
      {
        display_name: "Custom",
        protocol_type: "openai_completions_compatible",
        base_url: "https://api.example.test",
        api_key_ref: "env:MODEL_KEY",
        default_model_id: "model-a",
        supported_model_ids: ["model-a"],
        runtime_capabilities: [
          {
            model_id: "model-a",
            context_window_tokens: 128000,
            max_output_tokens: 4096,
            supports_tool_calling: false,
            supports_structured_output: false,
            supports_native_reasoning: false,
          },
        ],
      },
      { fetcher: fetchMock },
    );
    await patchProvider(
      "provider-1",
      {
        base_url: "https://api.example.test",
        api_key_ref: null,
        default_model_id: "model-a",
        supported_model_ids: ["model-a"],
        runtime_capabilities: [
          {
            model_id: "model-a",
            context_window_tokens: 128000,
            max_output_tokens: 4096,
            supports_tool_calling: false,
            supports_structured_output: false,
            supports_native_reasoning: false,
          },
        ],
      },
      { fetcher: fetchMock },
    );
    await getProjectDeliveryChannel("project-1", { fetcher: fetchMock });
    await updateProjectDeliveryChannel(
      "project-1",
      { delivery_mode: "demo_delivery" },
      { fetcher: fetchMock },
    );
    await validateProjectDeliveryChannel("project-1", { fetcher: fetchMock });
    await exportProjectConfigurationPackage("project-1", {
      fetcher: fetchMock,
    });
    await importProjectConfigurationPackage(
      "project-1",
      {
        package_schema_version: "function-one-config-v1",
        scope: { scope_type: "project", project_id: "project-1" },
        providers: [],
        delivery_channels: [],
        pipeline_templates: [],
      },
      { fetcher: fetchMock },
    );
    await createRerun("session-1", { fetcher: fetchMock });
    await getRun("run-1", { fetcher: fetchMock });
    await getRunTimeline("run-1", { fetcher: fetchMock });
    await pauseRun("run-1", { fetcher: fetchMock });
    await resumeRun("run-1", { fetcher: fetchMock });
    await terminateRun("run-1", { fetcher: fetchMock });
    await approveApproval("approval-1", { fetcher: fetchMock });
    await rejectApproval(
      "approval-1",
      { reason: "Needs changes." },
      { fetcher: fetchMock },
    );
    await getSessionWorkspace("session-1", { fetcher: fetchMock });
    await getStageInspector("stage-1", { fetcher: fetchMock });
    await getControlRecord("control-1", { fetcher: fetchMock });
    await getToolConfirmation("tool-1", { fetcher: fetchMock });
    await getDeliveryRecord("delivery-1", { fetcher: fetchMock });
    await getRunLogs("run-1", { limit: 25, level: "error" }, {
      fetcher: fetchMock,
    });

    const OriginalEventSource = globalThis.EventSource;
    const eventSourceSpy = vi.fn(function MockEventSource(
      this: EventSource,
      url: string,
    ) {
      Object.defineProperty(this, "url", { value: url });
    });
    vi.stubGlobal("EventSource", eventSourceSpy);
    createSessionEventSource("session-1", { baseUrl: "/api/" });
    vi.stubGlobal("EventSource", OriginalEventSource);

    expect(calls.map((call) => [call.init?.method ?? "GET", call.input])).toEqual([
      ["GET", "/api/providers"],
      ["GET", "/api/providers/provider-1"],
      ["POST", "/api/providers"],
      ["PATCH", "/api/providers/provider-1"],
      ["GET", "/api/projects/project-1/delivery-channel"],
      ["PUT", "/api/projects/project-1/delivery-channel"],
      ["POST", "/api/projects/project-1/delivery-channel/validate"],
      ["GET", "/api/projects/project-1/configuration-package/export"],
      ["POST", "/api/projects/project-1/configuration-package/import"],
      ["POST", "/api/sessions/session-1/runs"],
      ["GET", "/api/runs/run-1"],
      ["GET", "/api/runs/run-1/timeline"],
      ["POST", "/api/runs/run-1/pause"],
      ["POST", "/api/runs/run-1/resume"],
      ["POST", "/api/runs/run-1/terminate"],
      ["POST", "/api/approvals/approval-1/approve"],
      ["POST", "/api/approvals/approval-1/reject"],
      ["GET", "/api/sessions/session-1/workspace"],
      ["GET", "/api/stages/stage-1/inspector"],
      ["GET", "/api/control-records/control-1"],
      ["GET", "/api/tool-confirmations/tool-1"],
      ["GET", "/api/delivery-records/delivery-1"],
      ["GET", "/api/runs/run-1/logs?limit=25&level=error"],
    ]);
    expect(eventSourceSpy).toHaveBeenCalledWith(
      "/api/sessions/session-1/events/stream",
    );
  });
});
