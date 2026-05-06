import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ApiRequestOptions } from "../../../api/client";
import { renderWithAppProviders } from "../../../app/test-utils";
import {
  mockPipelineTemplates,
  mockProviderList,
  mockSessionWorkspaces,
} from "../../../mocks/fixtures";
import { createMockApiFetcher, mockApiRequestOptions } from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { TemplateEmptyState } from "../../templates/TemplateEmptyState";

afterEach(() => {
  cleanup();
});

describe("SettingsBoundary", () => {
  it("keeps platform runtime and prompt asset fields out of settings surfaces", async () => {
    const dialog = await openSettings();
    const forbiddenTerms = [
      "EnvironmentSettings",
      "environment variable",
      "process.env",
      ".env",
      "AI_DEVFLOW_PLATFORM_RUNTIME_ROOT",
      "PLATFORM_RUNTIME_ROOT",
      "platform_runtime_root",
      ".runtime",
      "SQLite",
      "control.db",
      "runtime.db",
      "graph.db",
      "event.db",
      "log.db",
      "PlatformRuntimeSettings",
      "platform run limits",
      "max_react_iterations",
      "max_stage_attempts",
      "run_timeout_seconds",
      "log policy",
      "log_retention_policy",
      "log_truncation_policy",
      "compression_threshold_ratio",
      "built-in prompt asset",
      "PromptRegistry",
      "backend://prompts",
      "prompt_id",
      "prompt_version",
      "runtime_instructions",
      "structured output repair prompt",
      "compression_prompt",
      "deterministic runtime",
      "deterministic test runtime",
      "sk-real-secret-value",
      "ghp_real_secret_token",
      "VOLCENGINE_API_KEY=",
    ];

    expect(await within(dialog).findByDisplayValue("demo_delivery")).toBeTruthy();
    expectTextToExclude(dialog, forbiddenTerms);

    fireEvent.click(within(dialog).getByRole("tab", { name: "模型提供商" }));
    expect(await within(dialog).findByText("火山引擎")).toBeTruthy();
    expectTextToExclude(dialog, forbiddenTerms);

    fireEvent.click(within(dialog).getByRole("tab", { name: "导入导出" }));
    expect(await within(dialog).findByText("Project: AI Devflow Engine")).toBeTruthy();
    expectTextToExclude(dialog, forbiddenTerms);
  });

  it("keeps provider identity fields out of user visible settings", async () => {
    const dialog = await openSettings();

    expect(await within(dialog).findByDisplayValue("demo_delivery")).toBeTruthy();
    const generalPanel = within(dialog).getByRole("tabpanel", {
      name: "通用配置",
    });
    expect(within(generalPanel).getByLabelText("Delivery mode")).toBeTruthy();
    expect(within(generalPanel).queryByText("context_window_tokens")).toBeNull();
    expect(within(generalPanel).queryByText("supports_structured_output")).toBeNull();

    fireEvent.click(within(dialog).getByRole("tab", { name: "模型提供商" }));
    expect(await within(dialog).findByText("火山引擎")).toBeTruthy();
    const providerPanel = within(dialog).getByRole("tabpanel", {
      name: "模型提供商",
    });
    fireEvent.click(
      within(providerPanel)
        .getAllByRole("button", { name: "Configure" })[0],
    );
    expect(within(providerPanel).queryByLabelText("Provider id")).toBeNull();
    expect(within(providerPanel).queryByLabelText("Provider source")).toBeNull();
    expect(within(providerPanel).queryByLabelText("Protocol type")).toBeNull();
    expect(within(providerPanel).getAllByLabelText("Base URL").length).toBeGreaterThan(
      0,
    );
    expect(within(providerPanel).getAllByLabelText("API key").length).toBeGreaterThan(
      0,
    );
    expect(within(providerPanel).getAllByLabelText("Supported models").length).toBeGreaterThan(
      0,
    );
    expect(within(providerPanel).getAllByLabelText("Default model").length).toBeGreaterThan(
      0,
    );
    fireEvent.click(within(providerPanel).getByText("高级设置"));
    expect(within(providerPanel).getByLabelText("Context window")).toBeTruthy();
    expect(within(providerPanel).getByLabelText("Max output tokens")).toBeTruthy();
    expect(within(providerPanel).getByLabelText("Tool calling")).toBeTruthy();
    expect(within(providerPanel).getByLabelText("Structured output")).toBeTruthy();
    expect(within(providerPanel).getByLabelText("Native reasoning")).toBeTruthy();
    expect(within(providerPanel).queryByText("context_window_tokens")).toBeNull();
    expect(within(providerPanel).queryByText("max_output_tokens")).toBeNull();
    expect(within(providerPanel).queryByText("supports_tool_calling")).toBeNull();
    expect(within(providerPanel).queryByText("supports_structured_output")).toBeNull();
    expect(within(providerPanel).queryByText("supports_native_reasoning")).toBeNull();
    expect(within(providerPanel).queryByLabelText("model_id")).toBeNull();

    fireEvent.click(within(dialog).getByRole("tab", { name: "通用配置" }));
    const refreshedGeneralPanel = within(dialog).getByRole("tabpanel", {
      name: "通用配置",
    });
    expect(within(refreshedGeneralPanel).queryByText("context_window_tokens")).toBeNull();
    expect(
      within(refreshedGeneralPanel).queryByText("supports_structured_output"),
    ).toBeNull();
  });

  it("exports only project scoped user visible configuration", async () => {
    const dialog = await openSettings(createBoundaryPackageRequest());

    fireEvent.click(within(dialog).getByRole("tab", { name: "导入导出" }));
    expect(await within(dialog).findByText("Project: AI Devflow Engine")).toBeTruthy();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Download JSON" }),
    );

    expect(await within(dialog).findByText("function-one-config-v1")).toBeTruthy();
    expect(within(dialog).getByText("project-default")).toBeTruthy();
    expect(
      within(dialog).getByText("Providers 1; delivery channels 1; templates 1"),
    ).toBeTruthy();
    expectTextToExclude(dialog, [
      "api_key_value",
      "sk-real-secret-value",
      "platform_runtime_settings",
      "PlatformRuntimeSettings",
      "compression_threshold_ratio",
      "platform_runtime_root",
      "control.db",
      "runtime.db",
      "system prompt asset body",
      "SYSTEM TRUSTED STRUCTURED OUTPUT REPAIR PROMPT BODY",
      "runtime_snapshot",
      "runtime_snapshots",
      "historical_runs",
      "run-secret-history",
      "logs",
      "log body text",
      "audit",
      "audit body text",
    ]);

    uploadConfigurationPackage(dialog, "project-default");

    expect(await within(dialog).findByText("Boundary import completed.")).toBeTruthy();
    expect(within(dialog).getByText(/provider-visible/u)).toBeTruthy();
    expect(within(dialog).getByText(/delivery-visible/u)).toBeTruthy();
    expect(within(dialog).getByText(/template-visible/u)).toBeTruthy();
    expectTextToExclude(dialog, [
      "api_key_value",
      "sk-real-secret-value",
      "ghp_real_secret_token",
      "platform_runtime_settings",
      "PlatformRuntimeSettings",
      "compression_threshold_ratio",
      "platform_runtime_root",
      "control.db",
      "runtime.db",
      "system prompt asset body",
      "SYSTEM TRUSTED STRUCTURED OUTPUT REPAIR PROMPT BODY",
      "runtime_snapshot",
      "runtime_snapshots",
      "historical_runs",
      "run-secret-history",
      "logs",
      "log body text",
      "audit",
      "audit body text",
    ]);
  });

  it("keeps template editing separate from system prompt assets", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={mockProviderList}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
      />,
    );

    const editor = screen.getByRole("region", { name: "Template editor" });
    expect(within(editor).getByText("Run configuration")).toBeTruthy();
    expect(within(editor).getByLabelText("requirement_analysis role")).toBeTruthy();
    expect(within(editor).getByLabelText("requirement_analysis provider")).toBeTruthy();
    expect(
      within(editor).getByLabelText("requirement_analysis system prompt"),
    ).toBeTruthy();
    expect(within(editor).getByLabelText("Auto regression")).toBeTruthy();
    expect(
      within(editor).getByLabelText("Maximum auto regression retries"),
    ).toBeTruthy();
    expectTextToExclude(editor, [
      "DeliveryChannel",
      "delivery_channel",
      "SQLite",
      "control.db",
      "runtime.db",
      "graph.db",
      "event.db",
      "log.db",
      "platform run limits",
      "PlatformRuntimeSettings",
      "max_react_iterations",
      "max_stage_attempts",
      "run_timeout_seconds",
      "log_retention_policy",
      "compression_threshold_ratio",
      "prompt_id",
      "prompt_version",
      "PromptRegistry",
      "backend://prompts",
      "runtime_instructions",
      "structured output repair prompt",
      "compression_prompt",
    ]);
  });
});

async function openSettings(
  request: ApiRequestOptions = mockApiRequestOptions,
): Promise<HTMLElement> {
  renderWithAppProviders(<ConsolePage request={request} />);

  fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));

  return screen.getByRole("dialog", { name: "Settings" });
}

function createBoundaryPackageRequest(): ApiRequestOptions {
  const defaultFetcher = createMockApiFetcher();

  return {
    fetcher: async (input, init) => {
      const path = normalizePath(input);

      if (path.endsWith("/configuration-package/export")) {
        return jsonResponse({
          export_id: "boundary-export",
          exported_at: "2026-05-05T00:00:00.000Z",
          package_schema_version: "function-one-config-v1",
          scope: { scope_type: "project", project_id: "project-default" },
          providers: [
            {
              provider_id: "provider-visible",
              display_name: "Visible provider",
              provider_source: "custom",
              protocol_type: "openai_completions_compatible",
              base_url: "https://provider.example.test/v1",
              api_key_ref: null,
              default_model_id: "visible-model",
              supported_model_ids: ["visible-model"],
              is_enabled: true,
              runtime_capabilities: [
                {
                  model_id: "visible-model",
                  context_window_tokens: 128000,
                  max_output_tokens: 4096,
                  supports_tool_calling: false,
                  supports_structured_output: true,
                  supports_native_reasoning: false,
                },
              ],
            },
          ],
          delivery_channels: [
            {
              delivery_mode: "demo_delivery",
              credential_ref: "env:VISIBLE_DELIVERY_TOKEN",
            },
          ],
          pipeline_templates: [
            {
              template_id: "template-visible",
              name: "Visible template",
              template_source: "user_template",
              stage_role_bindings: [],
              auto_regression_enabled: true,
              max_auto_regression_retries: 1,
            },
          ],
          api_key_value: "sk-real-secret-value",
          platform_runtime_settings: {
            platform_runtime_root: "C:/runtime/platform",
            compression_threshold_ratio: 0.8,
            database_paths: ["control.db", "runtime.db"],
          },
          system_prompt_asset_body:
            "SYSTEM TRUSTED STRUCTURED OUTPUT REPAIR PROMPT BODY",
          runtime_snapshots: [{ snapshot_id: "runtime_snapshot-secret" }],
          historical_runs: ["run-secret-history"],
          logs: ["log body text"],
          audit: ["audit body text"],
        });
      }

      if (path.endsWith("/configuration-package/import")) {
        return jsonResponse({
          package_id: "boundary-import",
          summary: "Boundary import completed.",
          changed_objects: [
            {
              object_type: "provider",
              object_id: "provider-visible",
              action: "updated",
            },
            {
              object_type: "delivery_channel",
              object_id: "delivery-visible",
              action: "updated",
            },
            {
              object_type: "pipeline_template",
              object_id: "template-visible",
              action: "updated",
            },
          ],
          api_key_value: "ghp_real_secret_token",
          platform_runtime_settings: {
            platform_runtime_root: "C:/runtime/platform",
            compression_threshold_ratio: 0.8,
            database_paths: ["control.db", "runtime.db"],
          },
          runtime_snapshots: ["runtime_snapshot-import-secret"],
          historical_runs: ["run-secret-history"],
          system_prompt_asset_body:
            "SYSTEM TRUSTED STRUCTURED OUTPUT REPAIR PROMPT BODY",
          logs: ["log body text"],
          audit: ["audit body text"],
        });
      }

      return defaultFetcher(input, init);
    },
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
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

function uploadConfigurationPackage(container: HTMLElement, projectId: string) {
  const file = new File(
    [
      JSON.stringify({
        package_schema_version: "function-one-config-v1",
        scope: { scope_type: "project", project_id: projectId },
        providers: [],
        delivery_channels: [],
        pipeline_templates: [],
      }),
    ],
    "config-package.json",
    { type: "application/json" },
  );

  fireEvent.change(
    within(container).getByLabelText("Configuration package JSON file"),
    { target: { files: [file] } },
  );
}

function expectTextToExclude(container: HTMLElement, terms: string[]) {
  const text = visibleSurfaceText(container);

  for (const term of terms) {
    expect(text).not.toContain(term);
  }
}

function visibleSurfaceText(container: HTMLElement): string {
  const controlValues = Array.from(
    container.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
      "input, textarea, select",
    ),
  )
    .map((control) => control.value)
    .join("\n");

  return `${container.textContent ?? ""}\n${controlValues}`;
}
