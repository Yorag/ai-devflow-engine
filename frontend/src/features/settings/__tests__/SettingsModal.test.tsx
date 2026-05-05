import { QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiQueryKeys } from "../../../api/hooks";
import type {
  ConfigurationPackageExport,
  ConfigurationPackageImportResult,
  ProjectDeliveryChannelDetailProjection,
  ProjectRead,
  ProviderRead,
  ProviderWriteRequest,
} from "../../../api/types";
import { createQueryClient } from "../../../app/query-client";
import { renderWithAppProviders } from "../../../app/test-utils";
import { mockApiRequestOptions } from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { ConfigurationPackageSettings } from "../ConfigurationPackageSettings";
import { SettingsModal } from "../SettingsModal";

afterEach(() => {
  cleanup();
});

describe("SettingsModal", () => {
  it("opens from the global tools area with the required settings sections", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    expect(dialog).toBeTruthy();
    expect(
      within(dialog).getByRole("button", { name: "Close settings" }),
    ).toBeTruthy();
    expect(within(dialog).getByRole("tab", { name: "通用配置" })).toBeTruthy();
    expect(within(dialog).getByRole("tab", { name: "模型提供商" })).toBeTruthy();
    expect(within(dialog).getByRole("tab", { name: "导入导出" })).toBeTruthy();
    expect(
      within(dialog).getByRole("tabpanel", { name: "通用配置" }),
    ).toBeTruthy();
    expect(within(dialog).getByText("AI Devflow Engine")).toBeTruthy();
  });

  it("moves focus into the dialog, traps tab navigation, and restores focus when closed", async () => {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <SettingsFocusHarness />
      </QueryClientProvider>,
    );

    const opener = screen.getByRole("button", { name: "Open settings" });
    opener.focus();
    expect(document.activeElement).toBe(opener);

    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    const closeButton = within(dialog).getByRole("button", {
      name: "Close settings",
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(closeButton);
    });

    const focusableControls = getFocusableElements(dialog);
    const lastControl = focusableControls[focusableControls.length - 1];
    lastControl.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(closeButton);

    closeButton.focus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(lastControl);

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull();
    });
    expect(document.activeElement).toBe(opener);

    opener.focus();
    fireEvent.click(opener);
    const reopenedDialog = screen.getByRole("dialog", { name: "Settings" });
    const reopenedCloseButton = within(reopenedDialog).getByRole("button", {
      name: "Close settings",
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(reopenedCloseButton);
    });

    fireEvent.click(reopenedCloseButton);

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull();
    });
    expect(document.activeElement).toBe(opener);
  });

  it("shows project delivery channel fields without exposing platform runtime settings", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    expect(await within(dialog).findByDisplayValue("demo_delivery")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Repository"), {
      target: { value: "example/new-repo" },
    });
    expect(within(dialog).getByDisplayValue("example/new-repo")).toBeTruthy();
    expect(within(dialog).getByText("ready")).toBeTruthy();
    expect(
      within(dialog).getByRole("button", { name: "Validate delivery channel" }),
    ).toBeTruthy();
    expect(
      within(dialog).getByRole("button", { name: "Save delivery channel" }),
    ).toBeTruthy();
    expect(within(dialog).queryByText(/compression_threshold_ratio/i)).toBeNull();
    expect(within(dialog).queryByText(/SQLite/i)).toBeNull();
    expect(within(dialog).queryByText(/deterministic test runtime/i)).toBeNull();
  });

  it("shows git delivery fields and credential references for git_auto_delivery projects", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.change(await screen.findByLabelText("Switch project"), {
      target: { value: "project-loaded" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    expect(await within(dialog).findByDisplayValue("git_auto_delivery")).toBeTruthy();
    expect(within(dialog).getByDisplayValue("example/checkout-service")).toBeTruthy();
    expect(within(dialog).getByDisplayValue("main")).toBeTruthy();
    expect(within(dialog).getByDisplayValue("env:GITHUB_TOKEN")).toBeTruthy();
    expect(
      within(dialog).getByText("Credential reference cannot be resolved."),
    ).toBeTruthy();
  });

  it("does not show stale delivery controls when project is cleared or changed before fresh channel data arrives", async () => {
    const projectA = {
      ...createSettingsProject(),
      project_id: "project-delivery-a",
      name: "Delivery Project A",
    };
    const projectB = {
      ...createSettingsProject(),
      project_id: "project-delivery-b",
      name: "Delivery Project B",
    };
    const projectBResponse = createDeferred<Response>();
    const projectAChannel: ProjectDeliveryChannelDetailProjection = {
      ...createDeliveryChannel(projectA.project_id),
      delivery_mode: "git_auto_delivery",
      scm_provider_type: "github",
      repository_identifier: "example/project-a",
      default_branch: "release/a",
      code_review_request_type: "pull_request",
      credential_ref: "env:PROJECT_A_TOKEN",
    };
    const projectBChannel: ProjectDeliveryChannelDetailProjection = {
      ...createDeliveryChannel(projectB.project_id),
      delivery_mode: "git_auto_delivery",
      scm_provider_type: "github",
      repository_identifier: "example/project-b",
      default_branch: "main",
      code_review_request_type: "pull_request",
      credential_ref: "env:PROJECT_B_TOKEN",
    };
    const queryClient = createQueryClient();

    function renderModal(project: ProjectRead | null) {
      return (
        <QueryClientProvider client={queryClient}>
          <SettingsModal
            isOpen
            onClose={() => undefined}
            project={project}
            request={{
              fetcher: async (input) => {
                const path = normalizePath(input);

                if (path.endsWith(`/${projectA.project_id}/delivery-channel`)) {
                  return jsonResponse(projectAChannel);
                }

                if (path.endsWith(`/${projectB.project_id}/delivery-channel`)) {
                  return projectBResponse.promise;
                }

                return jsonResponse([]);
              },
            }}
          />
        </QueryClientProvider>
      );
    }

    const { rerender } = render(renderModal(projectA));
    const dialog = screen.getByRole("dialog", { name: "Settings" });

    expect(await within(dialog).findByDisplayValue("example/project-a")).toBeTruthy();

    rerender(renderModal(null));

    expect(within(dialog).getByText("No project loaded")).toBeTruthy();
    expect(within(dialog).queryByLabelText("Repository")).toBeNull();
    expect(within(dialog).queryByDisplayValue("example/project-a")).toBeNull();

    rerender(renderModal(projectB));

    expect(within(dialog).getByText("Loading delivery channel...")).toBeTruthy();
    expect(within(dialog).queryByLabelText("Repository")).toBeNull();
    expect(within(dialog).queryByDisplayValue("example/project-a")).toBeNull();

    projectBResponse.resolve(jsonResponse(projectBChannel));

    expect(await within(dialog).findByDisplayValue("example/project-b")).toBeTruthy();
    expect(within(dialog).queryByDisplayValue("example/project-a")).toBeNull();
  });

  it("starts provider settings empty and adds a selected provider through the backend", async () => {
    const project = createSettingsProject();
    const createdProvider = createProvider({
      provider_id: "provider-deepseek",
      display_name: "DeepSeek",
      provider_source: "builtin",
      protocol_type: "openai_completions_compatible",
      base_url: "https://api.deepseek.com",
      api_key_ref: "env:DEEPSEEK_API_KEY",
      default_model_id: "deepseek-chat",
      supported_model_ids: ["deepseek-chat", "deepseek-reasoner"],
      runtime_capabilities: [
        createCapabilities({ model_id: "deepseek-chat" }),
        createCapabilities({
          model_id: "deepseek-reasoner",
          supports_native_reasoning: true,
        }),
      ],
    });
    const calls: Array<{
      path: string;
      method: string;
      body: ProviderWriteRequest | null;
    }> = [];
    let providers: ProviderRead[] = [];

    renderSettingsModalWithRequest(project, async (input, init) => {
      const path = normalizePath(input);

      if (path.endsWith("/providers") && (init?.method ?? "GET") === "GET") {
        return jsonResponse(providers);
      }

      if (path.endsWith("/providers/provider-deepseek") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as ProviderWriteRequest;
        calls.push({ path, method: "PATCH", body });
        providers = [
          {
            ...createdProvider,
            ...body,
            provider_id: "provider-deepseek",
            display_name: "DeepSeek",
            provider_source: "builtin",
            protocol_type: "openai_completions_compatible",
            runtime_capabilities: body.runtime_capabilities.map((capability) =>
              createCapabilities(capability),
            ),
            updated_at: "2026-05-02T02:00:00.000Z",
          },
        ];
        return jsonResponse(providers[0]);
      }

      if (path.endsWith("/delivery-channel")) {
        return jsonResponse(createDeliveryChannel(project.project_id));
      }

      return jsonResponse([]);
    });

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "模型提供商" }));

    expect(await within(dialog).findByText("No providers added")).toBeTruthy();
    expect(within(dialog).queryByText("Provider id")).toBeNull();
    expect(within(dialog).queryByText("Provider source")).toBeNull();
    expect(within(dialog).queryByText("Protocol type")).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Add custom provider" }));
    expect(
      within(dialog).getByRole("menuitem", { name: "Add 火山引擎" }),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("menuitem", { name: "Add DeepSeek" }));

    const card = await within(dialog).findByRole("article", { name: "DeepSeek" });
    expect(within(card).getByLabelText("Base URL")).toHaveProperty(
      "value",
      "https://api.deepseek.com",
    );
    expect(within(card).getByLabelText("API key")).toHaveProperty("value", "");
    expect(within(card).getByLabelText("Supported models")).toHaveProperty(
      "value",
      "deepseek-chat, deepseek-reasoner",
    );
    expect(within(card).getByLabelText("Default model")).toHaveProperty(
      "value",
      "deepseek-chat",
    );
    expect(within(card).getByLabelText("Provider enabled")).toHaveProperty(
      "checked",
      true,
    );
    expect(within(card).queryByText("model_id")).toBeNull();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "PATCH",
      path: "/api/providers/provider-deepseek",
    });
    expect(calls[0].body).toMatchObject({
      base_url: "https://api.deepseek.com",
      api_key_ref: "env:DEEPSEEK_API_KEY",
      default_model_id: "deepseek-chat",
      supported_model_ids: ["deepseek-chat", "deepseek-reasoner"],
      is_enabled: true,
    });
  });

  it("creates OpenAI Completions providers, edits fields, and saves changes", async () => {
    const project = createSettingsProject();
    const calls: Array<{
      path: string;
      method: string;
      body: ProviderWriteRequest | null;
    }> = [];
    let providers: ProviderRead[] = [];

    renderSettingsModalWithRequest(project, async (input, init) => {
      const path = normalizePath(input);

      if (path.endsWith("/providers") && (init?.method ?? "GET") === "GET") {
        return jsonResponse(providers);
      }

      if (path.endsWith("/providers") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as ProviderWriteRequest;
        calls.push({ path, method: "POST", body });
        providers = [
          createProvider({
            ...body,
            provider_id: "provider-custom-openai",
            display_name: body.display_name ?? "OpenAI Completions",
            provider_source: "custom",
            protocol_type: "openai_completions_compatible",
            is_enabled: body.is_enabled,
            runtime_capabilities: body.runtime_capabilities.map((capability) =>
              createCapabilities(capability),
            ),
          }),
        ];
        return jsonResponse(providers[0]);
      }

      if (
        path.endsWith("/providers/provider-custom-openai") &&
        init?.method === "PATCH"
      ) {
        const body = JSON.parse(String(init.body)) as ProviderWriteRequest;
        calls.push({ path, method: "PATCH", body });
        providers = [
          {
            ...providers[0],
            ...body,
            display_name: body.display_name ?? providers[0].display_name,
            is_enabled: body.is_enabled,
            runtime_capabilities: body.runtime_capabilities.map((capability) =>
              createCapabilities(capability),
            ),
            updated_at: "2026-05-02T03:00:00.000Z",
          },
        ];
        return jsonResponse(providers[0]);
      }

      if (path.endsWith("/delivery-channel")) {
        return jsonResponse(createDeliveryChannel(project.project_id));
      }

      return jsonResponse([]);
    });

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "模型提供商" }));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Add custom provider" }),
    );
    fireEvent.click(
      within(dialog).getByRole("menuitem", { name: "Add OpenAI Completions" }),
    );

    const card = await within(dialog).findByRole("article", {
      name: "OpenAI Completions",
    });
    fireEvent.change(within(card).getByLabelText("Base URL"), {
      target: { value: "https://gateway.example.test/v1" },
    });
    fireEvent.change(within(card).getByLabelText("API key"), {
      target: { value: "env:OPENAI_TEAM_API_KEY" },
    });
    fireEvent.change(within(card).getByLabelText("Supported models"), {
      target: { value: "gpt-4.1, gpt-4.1-mini" },
    });
    fireEvent.change(within(card).getByLabelText("Default model"), {
      target: { value: "gpt-4.1-mini" },
    });
    fireEvent.click(within(card).getByLabelText("Provider enabled"));
    fireEvent.click(within(card).getByText("高级设置"));

    const miniCapabilities = await within(card).findByRole("group", {
      name: "Runtime capabilities for gpt-4.1-mini",
    });
    fireEvent.change(within(miniCapabilities).getByLabelText("Context window"), {
      target: { value: "256000" },
    });
    fireEvent.change(within(miniCapabilities).getByLabelText("Max output tokens"), {
      target: { value: "16384" },
    });
    fireEvent.click(within(miniCapabilities).getByLabelText("Tool calling"));
    fireEvent.click(within(miniCapabilities).getByLabelText("Native reasoning"));
    fireEvent.click(within(card).getByRole("button", { name: "Save provider" }));

    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: "/api/providers",
    });
    expect(calls[0].body).toMatchObject({
      display_name: "OpenAI Completions",
      base_url: "https://gateway.example.test/v1",
      api_key_ref: "env:OPENAI_TEAM_API_KEY",
      default_model_id: "gpt-4.1-mini",
      supported_model_ids: ["gpt-4.1", "gpt-4.1-mini"],
      is_enabled: false,
    });
    expect(calls[0].body?.runtime_capabilities.map((item) => item.model_id)).toEqual([
      "gpt-4.1",
      "gpt-4.1-mini",
    ]);
    expect(
      calls[0].body?.runtime_capabilities.find(
        (capability) => capability.model_id === "gpt-4.1-mini",
      ),
    ).toMatchObject({
      context_window_tokens: 256000,
      max_output_tokens: 16384,
      supports_tool_calling: true,
      supports_native_reasoning: true,
    });
  });

  it("shows provider configuration with only user-visible fields", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));
    const dialog = screen.getByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "模型提供商" }));

    expect(await within(dialog).findByText("火山引擎")).toBeTruthy();
    expect(within(dialog).queryByText(/builtin/u)).toBeNull();
    expect(within(dialog).queryByText(/volcengine_native/u)).toBeNull();
    expect(within(dialog).queryByText("Provider id")).toBeNull();
    expect(within(dialog).queryByText("Provider source")).toBeNull();
    expect(within(dialog).queryByText("Protocol type")).toBeNull();
    expect(within(dialog).queryByText("env:VOLCENGINE_API_KEY")).toBeNull();
    const providerCard = within(dialog).getByRole("article", { name: "火山引擎" });
    fireEvent.click(within(providerCard).getByRole("button", { name: "Configure" }));
    fireEvent.change(
      within(providerCard).getByDisplayValue(
        "https://ark.cn-beijing.volces.com/api/v3",
      ),
      {
        target: { value: "https://ark.example.test/api/v3" },
      },
    );
    expect(
      within(providerCard).getByDisplayValue("https://ark.example.test/api/v3"),
    ).toBeTruthy();
    const defaultModelInput = within(providerCard).getByLabelText("Default model");
    fireEvent.change(defaultModelInput, {
      target: { value: "doubao-seed-1-6-thinking" },
    });
    expect(
      within(dialog).getByDisplayValue("doubao-seed-1-6-thinking"),
    ).toBeTruthy();
    expect(
      within(dialog).getByRole("button", { name: "Add custom provider" }),
    ).toBeTruthy();
    fireEvent.click(within(providerCard).getByText("高级设置"));
    const runtimeCapabilities = within(providerCard).getByRole("group", {
      name: "Runtime capabilities for doubao-seed-1-6",
    });
    expect(within(runtimeCapabilities).getByLabelText("Context window")).toBeTruthy();
    expect(
      within(runtimeCapabilities).getByLabelText("Max output tokens"),
    ).toBeTruthy();
    expect(within(runtimeCapabilities).getByLabelText("Tool calling")).toBeTruthy();
    expect(
      within(runtimeCapabilities).getByLabelText("Structured output"),
    ).toBeTruthy();
    expect(
      within(runtimeCapabilities).getByLabelText("Native reasoning"),
    ).toBeTruthy();
    expect(within(dialog).queryByText("context_window_tokens")).toBeNull();
    expect(within(dialog).queryByText("max_output_tokens")).toBeNull();
    expect(within(dialog).queryByText("supports_tool_calling")).toBeNull();
    expect(within(dialog).queryByText("supports_structured_output")).toBeNull();
    expect(within(dialog).queryByText("supports_native_reasoning")).toBeNull();
    expect(within(dialog).queryByText("model_id")).toBeNull();
    expect(within(dialog).queryByText(/prompt_version/i)).toBeNull();
    expect(within(dialog).queryByText(/compression_prompt/i)).toBeNull();
  });

  it("keeps provider fields in a two-column grid", () => {
    const cwd = process.cwd();
    const frontendRoot = cwd.endsWith("frontend") ? cwd : join(cwd, "frontend");
    const css = readFileSync(join(frontendRoot, "src", "styles", "global.css"), "utf8");

    expect(css).toMatch(
      /\.settings-form-grid--compact\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/u,
    );
    expect(css).toMatch(
      /\.capability-grid__number-fields\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/u,
    );
    expect(css).toMatch(
      /\.capability-toggle-row\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\);/u,
    );
    expect(css).not.toMatch(/\.capability-grid__group\s*\{[^}]*border:/u);
    expect(css).not.toMatch(/\.capability-toggle-row label\s*\{[^}]*border:/u);
  });

  it("updates visible provider controls when providers query refetches fresh data", async () => {
    const project = createSettingsProject();
    const queryClient = createQueryClient();
    let providers = [
      createProvider({
        base_url: "https://provider.initial.test/v1",
        api_key_ref: "env:INITIAL_PROVIDER_KEY",
        default_model_id: "initial-model",
        supported_model_ids: ["initial-model"],
        runtime_capabilities: [
          createCapabilities({
            model_id: "initial-model",
            context_window_tokens: 64000,
            supports_structured_output: true,
          }),
        ],
        updated_at: "2026-05-02T00:00:00.000Z",
      }),
    ];

    renderSettingsModalWithRequest(
      project,
      async (input) => {
        const path = normalizePath(input);

        if (path.endsWith("/providers")) {
          return jsonResponse(providers);
        }

        if (path.endsWith("/delivery-channel")) {
          return jsonResponse(createDeliveryChannel(project.project_id));
        }

        return jsonResponse([]);
      },
      queryClient,
    );

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "模型提供商" }));

    const card = await within(dialog).findByRole("article", {
      name: "Refetch Provider",
    });
    fireEvent.click(within(card).getByRole("button", { name: "Configure" }));
    expect(
      await within(dialog).findByDisplayValue("https://provider.initial.test/v1"),
    ).toBeTruthy();
    expect(within(dialog).getByLabelText("API key")).toHaveProperty("value", "");
    expect(within(dialog).queryByText("env:INITIAL_PROVIDER_KEY")).toBeNull();
    expect(within(dialog).getByLabelText("Default model")).toHaveProperty(
      "value",
      "initial-model",
    );

    providers = [
      createProvider({
        base_url: "https://provider.fresh.test/v1",
        api_key_ref: "env:FRESH_PROVIDER_KEY",
        default_model_id: "fresh-default",
        supported_model_ids: ["fresh-default", "fresh-alt"],
        runtime_capabilities: [
          createCapabilities({
            model_id: "fresh-default",
            context_window_tokens: 96000,
            max_output_tokens: 8192,
            supports_tool_calling: true,
            supports_structured_output: false,
            supports_native_reasoning: true,
          }),
        ],
        updated_at: "2026-05-02T01:00:00.000Z",
      }),
    ];

    await queryClient.invalidateQueries({
      queryKey: apiQueryKeys.providers,
      refetchType: "all",
    });

    await waitFor(() => {
      expect(within(dialog).getByLabelText("Base URL")).toHaveProperty(
        "value",
        "https://provider.fresh.test/v1",
      );
    });
    expect(within(dialog).getByLabelText("API key")).toHaveProperty("value", "");
    expect(within(dialog).queryByText("env:FRESH_PROVIDER_KEY")).toBeNull();
    expect(within(dialog).getByLabelText("Default model")).toHaveProperty(
      "value",
      "fresh-default",
    );
    expect(within(dialog).getByLabelText("Supported models")).toHaveProperty(
      "value",
      "fresh-default, fresh-alt",
    );
    expect(within(dialog).queryByText("context_window_tokens")).toBeNull();
    expect(within(dialog).queryByText("max_output_tokens")).toBeNull();
    expect(within(dialog).queryByText("supports_tool_calling")).toBeNull();
    expect(within(dialog).queryByText("supports_structured_output")).toBeNull();
    expect(within(dialog).queryByText("supports_native_reasoning")).toBeNull();
  });

  it("shows project-scoped configuration package export and import results", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));
    const dialog = screen.getByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "导入导出" }));

    expect(await within(dialog).findByText("Project: AI Devflow Engine")).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Export configuration package" }),
    );
    expect(await within(dialog).findByText("function-one-config-v1")).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Import configuration package" }),
    );
    expect(
      await within(dialog).findByText("Imported 2 configuration objects."),
    ).toBeTruthy();
    expect(within(dialog).getByText(/provider-custom/u)).toBeTruthy();
    expect(within(dialog).queryByText(/api_key_value/i)).toBeNull();
    expect(within(dialog).queryByText(/runtime_snapshot/i)).toBeNull();
    expect(within(dialog).queryByText(/audit/i)).toBeNull();
  });

  it("waits for package client responses instead of showing optimistic package results", async () => {
    const project = createSettingsProject();
    const exportResponse = createDeferred<Response>();
    const importResponse = createDeferred<Response>();

    renderSettingsModalWithRequest(project, async (input) => {
      const path = normalizePath(input);

      if (path.endsWith("/configuration-package/export")) {
        return exportResponse.promise;
      }

      if (path.endsWith("/configuration-package/import")) {
        return importResponse.promise;
      }

      return jsonResponse(createDeliveryChannel(project.project_id));
    });

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "导入导出" }));
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Export configuration package" }),
    );

    expect(within(dialog).queryByText("function-one-config-v1")).toBeNull();

    exportResponse.resolve(
      jsonResponse({
        export_id: "backend-export",
        exported_at: "2026-05-02T00:00:00.000Z",
        package_schema_version: "backend-config-v2",
        scope: { scope_type: "project", project_id: project.project_id },
        providers: [],
        delivery_channels: [],
        pipeline_templates: [],
      } satisfies ConfigurationPackageExport),
    );

    expect(await within(dialog).findByText("backend-config-v2")).toBeTruthy();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Import configuration package" }),
    );

    expect(within(dialog).queryByText("Imported 2 configuration objects.")).toBeNull();
    expect(within(dialog).queryByText(/provider-custom/u)).toBeNull();

    importResponse.resolve(
      jsonResponse({
        package_id: "backend-import",
        summary: "Backend import completed.",
        changed_objects: [
          {
            object_type: "provider",
            object_id: "provider-from-backend",
            action: "created",
          },
        ],
      } satisfies ConfigurationPackageImportResult),
    );

    expect(await within(dialog).findByText("Backend import completed.")).toBeTruthy();
    expect(within(dialog).getByText(/provider-from-backend/u)).toBeTruthy();
  });

  it("invalidates project configuration queries after successful package import", async () => {
    const project = createSettingsProject();
    const importResponse = createDeferred<Response>();
    const queryClient = createQueryClient();
    const deliveryQueryFn = vi.fn(async () => createDeliveryChannel(project.project_id));
    const providersQueryFn = vi.fn(async () => []);
    const templatesQueryFn = vi.fn(async () => []);

    await queryClient.prefetchQuery({
      queryKey: apiQueryKeys.projectDeliveryChannel(project.project_id),
      queryFn: deliveryQueryFn,
    });
    await queryClient.prefetchQuery({
      queryKey: apiQueryKeys.providers,
      queryFn: providersQueryFn,
    });
    await queryClient.prefetchQuery({
      queryKey: apiQueryKeys.pipelineTemplates,
      queryFn: templatesQueryFn,
    });

    expect(deliveryQueryFn).toHaveBeenCalledTimes(1);
    expect(providersQueryFn).toHaveBeenCalledTimes(1);
    expect(templatesQueryFn).toHaveBeenCalledTimes(1);

    render(
      <QueryClientProvider client={queryClient}>
        <ConfigurationPackageSettings
          project={project}
          request={{
            fetcher: async (input) => {
              const path = normalizePath(input);

              if (path.endsWith("/configuration-package/import")) {
                return importResponse.promise;
              }

              return jsonResponse(createDeliveryChannel(project.project_id));
            },
          }}
        />
      </QueryClientProvider>,
    );

    expect(deliveryQueryFn).toHaveBeenCalledTimes(1);
    expect(providersQueryFn).toHaveBeenCalledTimes(1);
    expect(templatesQueryFn).toHaveBeenCalledTimes(1);

    fireEvent.click(
      screen.getByRole("button", { name: "Import configuration package" }),
    );

    importResponse.resolve(
      jsonResponse({
        package_id: "backend-import",
        summary: "Backend import refreshed queries.",
        changed_objects: [
          {
            object_type: "delivery_channel",
            object_id: "delivery-settings-test",
            action: "updated",
          },
        ],
      } satisfies ConfigurationPackageImportResult),
    );

    expect(
      await screen.findByText("Backend import refreshed queries."),
    ).toBeTruthy();

    await waitFor(() => {
      expect(deliveryQueryFn).toHaveBeenCalledTimes(2);
      expect(providersQueryFn).toHaveBeenCalledTimes(2);
      expect(templatesQueryFn).toHaveBeenCalledTimes(2);
    });
  });

  it("closes settings and keeps settings outside template editing and workspace placeholders", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));
    const dialog = screen.getByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Close settings" }));

    expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull();
    expect(screen.queryByText(/DeliveryChannel.*template/i)).toBeNull();
    expect(screen.queryByText(/runtime_instructions/i)).toBeNull();
    expect(screen.queryByText(/PlatformRuntimeSettings/i)).toBeNull();
    expect(screen.queryByText(/workflow surface comes online/i)).toBeNull();
  });

  it("closes settings with Escape", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull();
  });
});

function renderSettingsModalWithRequest(
  project: ProjectRead,
  fetcher: typeof fetch,
  queryClient = createQueryClient(),
) {
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsModal
        isOpen
        onClose={() => undefined}
        project={project}
        request={{ fetcher }}
      />
    </QueryClientProvider>,
  );
}

function createSettingsProject(): ProjectRead {
  return {
    project_id: "project-settings-test",
    name: "Settings Test Project",
    root_path: "C:/work/settings-test",
    default_delivery_channel_id: "delivery-settings-test",
    is_default: true,
    created_at: "2026-05-02T00:00:00.000Z",
    updated_at: "2026-05-02T00:00:00.000Z",
  };
}

function createDeliveryChannel(
  projectId: string,
): ProjectDeliveryChannelDetailProjection {
  return {
    project_id: projectId,
    delivery_channel_id: "delivery-settings-test",
    delivery_mode: "demo_delivery",
    scm_provider_type: null,
    repository_identifier: null,
    default_branch: null,
    code_review_request_type: null,
    credential_ref: null,
    credential_status: "ready",
    readiness_status: "ready",
    readiness_message: null,
    last_validated_at: "2026-05-02T00:00:00.000Z",
    updated_at: "2026-05-02T00:00:00.000Z",
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });

  return { promise, resolve };
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

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      [
        "button:not([disabled])",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "a[href]",
        "[tabindex]:not([tabindex='-1'])",
      ].join(","),
    ),
  );
}

function SettingsFocusHarness(): JSX.Element {
  const [isSettingsOpen, setSettingsOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setSettingsOpen(true)}>
        Open settings
      </button>
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setSettingsOpen(false)}
        project={null}
        request={{ fetcher: async () => jsonResponse([]) }}
      />
    </>
  );
}

function createProvider(overrides: Partial<ProviderRead> = {}): ProviderRead {
  const modelId = overrides.default_model_id ?? "provider-test-model";

  return {
    provider_id: "provider-refetch-test",
    display_name: "Refetch Provider",
    provider_source: "custom",
    protocol_type: "openai_completions_compatible",
    base_url: "https://provider.initial.test/v1",
    api_key_ref: "env:INITIAL_PROVIDER_KEY",
    default_model_id: modelId,
    supported_model_ids: [modelId],
    is_enabled: true,
    runtime_capabilities: [createCapabilities({ model_id: modelId })],
    created_at: "2026-05-02T00:00:00.000Z",
    updated_at: "2026-05-02T00:00:00.000Z",
    ...overrides,
  };
}

function createCapabilities(
  overrides: Partial<ProviderRead["runtime_capabilities"][number]> = {},
): ProviderRead["runtime_capabilities"][number] {
  return {
    model_id: "provider-test-model",
    context_window_tokens: 128000,
    max_output_tokens: 4096,
    supports_tool_calling: false,
    supports_structured_output: true,
    supports_native_reasoning: false,
    ...overrides,
  };
}
