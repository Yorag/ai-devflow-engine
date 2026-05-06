import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithAppProviders } from "../../../app/test-utils";
import {
  mockPipelineTemplates,
  mockProviderList,
  mockSessionWorkspaces,
} from "../../../mocks/fixtures";
import type { PipelineTemplateRead, ProviderRead } from "../../../api/types";
import { TemplateEmptyState } from "../TemplateEmptyState";
import {
  createTemplateDraft,
  isTemplateDirty,
  resolveTemplateStartGuard,
} from "../template-state";

afterEach(() => {
  cleanup();
});

describe("template-state", () => {
  it("detects editable template draft changes without treating fixed skeleton fields as editable", () => {
    const template = mockPipelineTemplates.find(
      (candidate) => candidate.template_id === "template-feature",
    )!;
    const cleanDraft = createTemplateDraft(template);
    const changedDraft = {
      ...cleanDraft,
      stage_role_bindings: cleanDraft.stage_role_bindings.map((binding, index) =>
        index === 0
          ? { ...binding, system_prompt: `${binding.system_prompt} Keep scope bounded.` }
          : binding,
      ),
    };

    expect(isTemplateDirty(template, cleanDraft)).toBe(false);
    expect(isTemplateDirty(template, changedDraft)).toBe(true);
    expect(cleanDraft.name).toBe(template.name);
    expect(cleanDraft.description).toBe(template.description);
    expect(cleanDraft.max_react_iterations_per_stage).toBe(30);
    expect(cleanDraft.max_tool_calls_per_stage).toBe(80);
    expect(cleanDraft.skip_high_risk_tool_confirmations).toBe(false);
    expect(
      isTemplateDirty(template, {
        ...cleanDraft,
        skip_high_risk_tool_confirmations: true,
      }),
    ).toBe(true);
    expect((cleanDraft as Record<string, unknown>).fixed_stage_sequence).toBeUndefined();
    expect((cleanDraft as Record<string, unknown>).approval_checkpoints).toBeUndefined();
  });

  it("blocks run start for dirty system and user templates with source-specific actions", () => {
    const systemTemplate = mockPipelineTemplates.find(
      (candidate) => candidate.template_id === "template-feature",
    )!;
    const userTemplate = {
      ...systemTemplate,
      template_id: "template-user-feature",
      template_source: "user_template" as const,
      base_template_id: systemTemplate.template_id,
    };

    expect(resolveTemplateStartGuard(systemTemplate, false)).toEqual({
      canStart: true,
      reason: null,
      actions: [],
    });
    expect(resolveTemplateStartGuard(systemTemplate, true)).toEqual({
      canStart: true,
      reason:
        "Unsaved edits will not affect this session until you save as a user template.",
      actions: ["save_as", "discard"],
    });
    expect(resolveTemplateStartGuard(userTemplate, true)).toEqual({
      canStart: true,
      reason:
        "Unsaved edits will not affect this session until you save the template.",
      actions: ["overwrite", "discard"],
    });
  });
});
describe("TemplateEditor", () => {
  it("renders fixed stage tabs and only edits the selected stage", () => {
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
    expect(within(editor).getAllByRole("tab")).toHaveLength(6);
    expect(editor.textContent ?? "").not.toContain("requirement_analysis");
    expect(
      within(editor)
        .getByRole("tab", { name: "Requirement Analysis" })
        .getAttribute("aria-selected"),
    ).toBe("true");
    expect(
      within(editor).getByLabelText("Requirement Analysis system prompt"),
    ).toHaveProperty(
      "value",
      "Analyze the requirement and ask clarifying questions when needed.",
    );
    expect(
      within(editor).queryByLabelText("Solution Design system prompt"),
    ).toBeNull();

    fireEvent.click(within(editor).getByRole("tab", { name: "Solution Design" }));

    expect(
      within(editor)
        .getByRole("tab", { name: "Solution Design" })
        .getAttribute("aria-selected"),
    ).toBe("true");
    expect(
      within(editor).getByLabelText("Solution Design system prompt"),
    ).toHaveProperty("value", "Design a bounded implementation plan.");
    expect(
      within(editor).queryByLabelText("Requirement Analysis system prompt"),
    ).toBeNull();
  });

  it("does not expose a stage role select while retaining the bound role id", () => {
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
    expect(within(editor).queryByLabelText(/ role$/u)).toBeNull();
    expect(within(editor).queryByText("Role")).toBeNull();
    expect(within(editor).queryByText("role-requirement-analyst")).toBeNull();
  });

  it("shows a no-provider configured state without leaking template provider ids", () => {
    const workspace = mockSessionWorkspaces["session-draft"];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={[]}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
      />,
    );

    const editor = screen.getByRole("region", { name: "Template editor" });
    const providerSelect = within(editor).getByLabelText(
      "Requirement Analysis provider",
    );

    expect(within(editor).getByText("No provider configured.")).toBeTruthy();
    expect(providerSelect).toHaveProperty("disabled", true);
    expect(providerSelect).toHaveProperty("value", "");
    expect(within(providerSelect).getByRole("option", {
      name: "No provider configured",
    })).toBeTruthy();
    expect(editor.textContent ?? "").not.toContain("provider-deepseek");
    expect(editor.textContent ?? "").not.toContain("provider-volcengine");
  });

  it("moves stage bindings to the configured provider when saved providers do not match", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const providers: ProviderRead[] = [
      {
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
      },
    ];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={providers}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
      />,
    );

    const editor = screen.getByRole("region", { name: "Template editor" });
    const providerSelect = within(editor).getByLabelText("Requirement Analysis provider");

    await waitFor(() => {
      expect(providerSelect).toHaveProperty("value", "provider-mimo");
    });
    expect(
      within(providerSelect).getByRole("option", { name: "MiMo" }),
    ).toBeTruthy();
    expect(
      within(providerSelect).queryByRole("option", {
        name: "Unavailable provider",
      }),
    ).toBeNull();
    expect(
      within(editor).queryByText("This template references unavailable providers."),
    ).toBeNull();
    expect(editor.textContent ?? "").not.toContain("provider-deepseek");
  });

  it("edits only allowed runtime configuration fields for a system template", () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const savedAsTemplateIds: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={mockProviderList}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
        onTemplateSaveAs={(template) => savedAsTemplateIds.push(template.template_id)}
      />,
    );

    const editor = screen.getByRole("region", { name: "Template editor" });
    expect(within(editor).getByText("Run configuration")).toBeTruthy();
    expect(within(editor).queryByText("role-requirement-analyst")).toBeNull();
    expect(within(editor).getByLabelText("Requirement Analysis provider")).toBeTruthy();
    expect(
      within(editor).getByLabelText("Requirement Analysis system prompt"),
    ).toBeTruthy();
    const policyRow = editor.querySelector(".template-editor__policy-row");
    expect(policyRow).toBeTruthy();
    if (!policyRow) {
      throw new Error("Template policy row was not rendered.");
    }

    expect(within(policyRow as HTMLElement).getByLabelText("Auto regression")).toHaveProperty(
      "checked",
      true,
    );
    expect(
      within(policyRow as HTMLElement).getByLabelText("Skip high-risk confirmations"),
    ).toHaveProperty("checked", false);
    expect(
      within(policyRow as HTMLElement).getByLabelText("Maximum auto regression retries"),
    ).toHaveProperty("value", "1");
    expect(policyRow.textContent ?? "").toMatch(
      /Auto regression.*Skip high-risk confirmations.*Maximum auto regression retries/su,
    );
    expect(within(editor).queryByLabelText("Max ReAct iterations")).toBeNull();
    expect(within(editor).queryByLabelText("Max tool calls")).toBeNull();
    expect(within(editor).queryByLabelText("Template name")).toBeNull();
    expect(within(editor).queryByLabelText("Template description")).toBeNull();

    fireEvent.change(within(editor).getByLabelText("Requirement Analysis system prompt"), {
      target: { value: "Analyze the requirement and preserve explicit constraints." },
    });

    expect(within(editor).getByText(/Unsaved edits will not affect/u)).toBeTruthy();
    expect(
      within(editor).getByRole("button", { name: "Save template" }),
    ).toBeTruthy();
    expect(
      within(editor).queryByRole("button", { name: "Overwrite template" }),
    ).toBeNull();
    expect(within(editor).queryByRole("button", { name: "Delete template" })).toBeNull();

    fireEvent.click(within(editor).getByRole("button", { name: "Save template" }));

    expect(savedAsTemplateIds).toEqual(["template-user-template-feature-1"]);
  });

  it("saves visible template-level run policy fields while retaining hidden backend limits", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    let savedTemplate: PipelineTemplateRead | null = null;

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={mockProviderList}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
        onTemplateSaveAs={(template) => {
          savedTemplate = template;
        }}
      />,
    );

    const editor = screen.getByRole("region", { name: "Template editor" });
    fireEvent.click(within(editor).getByLabelText("Auto regression"));
    fireEvent.change(within(editor).getByLabelText("Maximum auto regression retries"), {
      target: { value: "2" },
    });
    fireEvent.click(within(editor).getByLabelText("Skip high-risk confirmations"));
    fireEvent.click(within(editor).getByRole("button", { name: "Save template" }));

    await waitFor(() => {
      expect(savedTemplate).toMatchObject({
        auto_regression_enabled: false,
        max_auto_regression_retries: 2,
        max_react_iterations_per_stage: 30,
        max_tool_calls_per_stage: 80,
        skip_high_risk_tool_confirmations: true,
      });
    });
  });

  it("shows system template names as read-only and supports inline rename for user templates", () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const userTemplate = {
      ...mockPipelineTemplates[1],
      template_id: "template-user-existing",
      name: "Team feature flow",
      template_source: "user_template" as const,
      base_template_id: "template-feature",
    };
    const savedTemplates: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={mockProviderList}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
      />,
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "新功能开发流程" }),
    ).toBeTruthy();
    expect(screen.queryByLabelText("Template name")).toBeNull();

    cleanup();

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={[...mockPipelineTemplates, userTemplate]}
        providers={mockProviderList}
        selectedTemplateId="template-user-existing"
        onTemplateChange={() => undefined}
        onTemplateOverwrite={(template) => savedTemplates.push(template.name)}
      />,
    );

    const nameInput = screen.getByLabelText("Template name");
    expect(nameInput).toHaveProperty("value", "Team feature flow");
    fireEvent.change(nameInput, { target: { value: "Checkout feature flow" } });
    fireEvent.change(screen.getByLabelText("Requirement Analysis system prompt"), {
      target: { value: "Clarify checkout requirements." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save template" }));

    expect(savedTemplates).toEqual(["Checkout feature flow"]);
  });

  it("Save template persists all edited stage bindings in one full template payload", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    let savedTemplate: PipelineTemplateRead | null = null;

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={mockProviderList}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
        onTemplateSaveAs={(template) => {
          savedTemplate = template;
        }}
      />,
    );

    const original = mockPipelineTemplates.find(
      (template) => template.template_id === "template-feature",
    )!;
    fireEvent.change(screen.getByLabelText("Requirement Analysis system prompt"), {
      target: { value: "Clarify all checkout constraints before design." },
    });
    fireEvent.click(screen.getByRole("tab", { name: "Solution Design" }));
    fireEvent.change(screen.getByLabelText("Solution Design system prompt"), {
      target: { value: "Design only the approved checkout solution." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save template" }));

    await waitFor(() => {
      expect(savedTemplate?.stage_role_bindings).toEqual(
        original.stage_role_bindings.map((binding) =>
          binding.stage_type === "solution_design"
            ? {
                ...binding,
                system_prompt: "Design only the approved checkout solution.",
              }
            : binding.stage_type === "requirement_analysis"
              ? {
                  ...binding,
                  system_prompt: "Clarify all checkout constraints before design.",
                }
            : binding,
        ),
      );
    });
  });

  it("creates unique user template ids for repeated save-as from system templates", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const systemSaveAsIds: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={mockProviderList}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
        onTemplateSaveAs={(template) => systemSaveAsIds.push(template.template_id)}
      />,
    );

    const systemEditor = screen.getByRole("region", { name: "Template editor" });
    fireEvent.click(
      within(systemEditor).getByRole("button", { name: "Save template" }),
    );
    await waitFor(() => {
      expect(systemSaveAsIds).toEqual(["template-user-template-feature-1"]);
    });
    fireEvent.click(
      within(systemEditor).getByRole("button", { name: "Save template" }),
    );

    await waitFor(() => {
      expect(systemSaveAsIds).toEqual([
        "template-user-template-feature-1",
        "template-user-template-feature-2",
      ]);
    });
  });

  it("supports template overwrite, delete, and discard for user templates", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const systemTemplate = mockPipelineTemplates[1];
    const userTemplate = {
      ...systemTemplate,
      template_id: "template-user-existing",
      name: "Team feature flow",
      template_source: "user_template" as const,
      base_template_id: systemTemplate.template_id,
    };
    const overwrittenTemplateIds: string[] = [];
    const deletedTemplateIds: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={[...mockPipelineTemplates, userTemplate]}
        providers={mockProviderList}
        selectedTemplateId="template-user-existing"
        onTemplateChange={() => undefined}
        onTemplateOverwrite={(template) =>
          overwrittenTemplateIds.push(template.template_id)
        }
        onTemplateDelete={(templateId) => {
          deletedTemplateIds.push(templateId);
        }}
      />,
    );

    const editor = screen.getByRole("region", { name: "Template editor" });
    fireEvent.change(within(editor).getByLabelText("Maximum auto regression retries"), {
      target: { value: "3" },
    });

    expect(
      within(editor).getByText(
        "Unsaved edits will not affect this session until you save the template.",
      ),
    ).toBeTruthy();
    fireEvent.click(within(editor).getByRole("button", { name: "Save template" }));
    await waitFor(() => {
      expect(overwrittenTemplateIds).toEqual(["template-user-existing"]);
      expect(within(editor).queryByText(/Unsaved edits will not affect/u)).toBeNull();
    });

    fireEvent.change(within(editor).getByLabelText("Maximum auto regression retries"), {
      target: { value: "4" },
    });
    expect(
      within(editor).getByText(
        "Save or discard changes before deleting this user template.",
      ),
    ).toBeTruthy();
    expect(within(editor).getByRole("button", { name: "Delete template" })).toHaveProperty(
      "disabled",
      true,
    );
    fireEvent.click(within(editor).getByRole("button", { name: "Discard changes" }));
    expect(
      within(editor).getByLabelText("Maximum auto regression retries"),
    ).toHaveProperty("value", "3");

    fireEvent.click(within(editor).getByRole("button", { name: "Delete template" }));
    expect(deletedTemplateIds).toEqual(["template-user-existing"]);
  });

  it("supports saving a user template as a new template", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const systemTemplate = mockPipelineTemplates[1];
    const userTemplate = {
      ...systemTemplate,
      template_id: "template-user-existing",
      name: "Team feature flow",
      template_source: "user_template" as const,
      base_template_id: systemTemplate.template_id,
    };
    const savedAsTemplates: PipelineTemplateRead[] = [];
    const overwrittenTemplateIds: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={[...mockPipelineTemplates, userTemplate]}
        providers={mockProviderList}
        selectedTemplateId="template-user-existing"
        onTemplateChange={() => undefined}
        onTemplateSaveAs={(template) => {
          savedAsTemplates.push(template);
        }}
        onTemplateOverwrite={(template) =>
          overwrittenTemplateIds.push(template.template_id)
        }
      />,
    );

    const editor = screen.getByRole("region", { name: "Template editor" });
    fireEvent.change(within(editor).getByLabelText("Requirement Analysis system prompt"), {
      target: { value: "Clarify copied template requirements." },
    });
    fireEvent.click(
      within(editor).getByRole("button", { name: "Save as new template" }),
    );

    await waitFor(() => {
      expect(savedAsTemplates).toHaveLength(1);
    });
    expect(savedAsTemplates[0]).toMatchObject({
      template_id: "template-user-template-user-existing-1",
      template_source: "user_template",
      base_template_id: "template-user-existing",
    });
    expect(
      savedAsTemplates[0].stage_role_bindings.find(
        (binding) => binding.stage_type === "requirement_analysis",
      )?.system_prompt,
    ).toBe("Clarify copied template requirements.");
    expect(overwrittenTemplateIds).toEqual([]);
  });

  it("uses fallback template selection after deleting a user template without a base match", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const userTemplate = {
      ...mockPipelineTemplates[1],
      template_id: "template-user-with-missing-base",
      template_source: "user_template" as const,
      base_template_id: "template-missing",
    };
    const selectedTemplateIds: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={[mockPipelineTemplates[0], mockPipelineTemplates[1], userTemplate]}
        providers={mockProviderList}
        selectedTemplateId="template-user-with-missing-base"
        onTemplateChange={(templateId) => selectedTemplateIds.push(templateId)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete template" }));

    await waitFor(() => {
      expect(selectedTemplateIds).toEqual(["template-feature"]);
    });
    expect(selectedTemplateIds).not.toContain("template-user-with-missing-base");
  });

  it("reports an empty fallback when deleting the only local user template", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const userTemplate = {
      ...mockPipelineTemplates[1],
      template_id: "template-user-only",
      template_source: "user_template" as const,
      base_template_id: "template-missing",
    };
    const selectedTemplateIds: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={[userTemplate]}
        providers={mockProviderList}
        selectedTemplateId="template-user-only"
        onTemplateChange={(templateId) => selectedTemplateIds.push(templateId)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete template" }));

    await waitFor(() => {
      expect(selectedTemplateIds).toEqual([""]);
    });
  });

  it("blocks saving invalid retry counts with backend-style field errors", () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const userTemplate = {
      ...mockPipelineTemplates[1],
      template_id: "template-user-existing",
      template_source: "user_template" as const,
      base_template_id: "template-feature",
    };

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={[...mockPipelineTemplates, userTemplate]}
        providers={mockProviderList}
        selectedTemplateId="template-user-existing"
        onTemplateChange={() => undefined}
      />,
    );

    const editor = screen.getByRole("region", { name: "Template editor" });
    fireEvent.change(within(editor).getByLabelText("Maximum auto regression retries"), {
      target: { value: "-1" },
    });

    expect(
      within(editor).getByText(/Cannot save current field: config_invalid_value/u),
    ).toBeTruthy();
    expect(
      within(editor).getByRole("button", { name: "Save template" }),
    ).toHaveProperty("disabled", true);
    expect(within(editor).queryByRole("button", { name: "Overwrite template" })).toBeNull();

    fireEvent.change(within(editor).getByLabelText("Maximum auto regression retries"), {
      target: { value: "4" },
    });

    expect(
      within(editor).getByText(/Cannot save current field: config_hard_limit_exceeded/u),
    ).toBeTruthy();
    expect(within(editor).queryByText(/10 or less/u)).toBeNull();
    expect(
      within(editor).getByRole("button", { name: "Save template" }),
    ).toHaveProperty("disabled", true);
    expect(within(editor).queryByRole("button", { name: "Overwrite template" })).toBeNull();
  });

  it("keeps visible run policy controls in one ordered row with responsive CSS", () => {
    const cwd = process.cwd();
    const frontendRoot = cwd.endsWith("frontend") ? cwd : join(cwd, "frontend");
    const css = readFileSync(join(frontendRoot, "src", "styles", "global.css"), "utf8");

    expect(css).toMatch(
      /\.template-editor__policy-row\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(132px,\s*0\.9fr\)\s+minmax\(196px,\s*1\.1fr\)\s+minmax\(180px,\s*1fr\);[^}]*align-items:\s*center;/su,
    );
    expect(css).toMatch(
      /@media\s*\(max-width:\s*720px\)[\s\S]*\.template-editor__global,\s*\.template-editor__policy-row,\s*\.template-editor-stage__fields\s*\{[^}]*grid-template-columns:\s*1fr;/u,
    );
  });

  it("keeps local save-as templates when incoming templates refresh", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];

    function RefreshHarness(): JSX.Element {
      const [templates, setTemplates] = useState(mockPipelineTemplates);

      return (
        <>
          <button
            type="button"
            onClick={() =>
              setTemplates(mockPipelineTemplates.map((template) => ({ ...template })))
            }
          >
            Refresh templates
          </button>
          <TemplateEmptyState
            session={workspace.session}
            templates={templates}
            providers={mockProviderList}
            selectedTemplateId="template-feature"
            onTemplateChange={() => undefined}
          />
        </>
      );
    }

    renderWithAppProviders(<RefreshHarness />);

    expect(screen.getAllByRole("radio", { name: /新功能开发流程/u })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Save template" }));
    await waitFor(() => {
      expect(screen.getAllByRole("radio", { name: /新功能开发流程/u })).toHaveLength(2);
    });

    fireEvent.click(screen.getByRole("button", { name: "Refresh templates" }));

    expect(screen.getAllByRole("radio", { name: /新功能开发流程/u })).toHaveLength(2);
  });

  it("keeps local save-as templates unavailable for session start until persisted", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const selectedTemplateIds: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        providers={mockProviderList}
        selectedTemplateId="template-feature"
        onTemplateChange={(templateId) => selectedTemplateIds.push(templateId)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save template" }));

    await waitFor(() => {
      const featureOptions = screen.getAllByRole("radio", {
        name: /新功能开发流程/u,
      });
      expect(featureOptions).toHaveLength(2);
      expect(featureOptions[0]).toHaveProperty("disabled", false);
      expect(featureOptions[1]).toHaveProperty("disabled", true);
    });
    expect(selectedTemplateIds).toEqual([]);
  });

  it("does not reset an unsaved draft when the selected template object refreshes", () => {
    const workspace = mockSessionWorkspaces["session-draft"];

    function RefreshHarness(): JSX.Element {
      const [templates, setTemplates] = useState(mockPipelineTemplates);

      return (
        <>
          <button
            type="button"
            onClick={() =>
              setTemplates(
                templates.map((template) =>
                  template.template_id === "template-feature"
                    ? {
                        ...template,
                        stage_role_bindings: template.stage_role_bindings.map(
                          (binding, index) =>
                            index === 0
                              ? {
                                  ...binding,
                                  system_prompt:
                                    "Server refresh should not replace dirty drafts.",
                                }
                              : binding,
                        ),
                      }
                    : template,
                ),
              )
            }
          >
            Refresh selected template
          </button>
          <TemplateEmptyState
            session={workspace.session}
            templates={templates}
            providers={mockProviderList}
            selectedTemplateId="template-feature"
            onTemplateChange={() => undefined}
          />
        </>
      );
    }

    renderWithAppProviders(<RefreshHarness />);

    const prompt = screen.getByLabelText("Requirement Analysis system prompt");
    fireEvent.change(prompt, {
      target: { value: "Keep this unsaved local prompt." },
    });

    fireEvent.click(screen.getByRole("button", { name: "Refresh selected template" }));

    expect(screen.getByLabelText("Requirement Analysis system prompt")).toHaveProperty(
      "value",
      "Keep this unsaved local prompt.",
    );
  });

  it("accepts refreshed selected template data when the current draft is clean", async () => {
    const workspace = mockSessionWorkspaces["session-draft"];

    function RefreshHarness(): JSX.Element {
      const [templates, setTemplates] = useState(mockPipelineTemplates);

      return (
        <>
          <button
            type="button"
            onClick={() =>
              setTemplates(
                templates.map((template) =>
                  template.template_id === "template-feature"
                    ? {
                        ...template,
                        name: "Imported feature flow",
                        max_auto_regression_retries: 2,
                        stage_role_bindings: template.stage_role_bindings.map(
                          (binding, index) =>
                            index === 0
                              ? {
                                  ...binding,
                                  system_prompt:
                                    "Use imported configuration prompt.",
                                }
                              : binding,
                        ),
                      }
                    : template,
                ),
              )
            }
          >
            Import selected template update
          </button>
          <TemplateEmptyState
            session={workspace.session}
            templates={templates}
            providers={mockProviderList}
            selectedTemplateId="template-feature"
            onTemplateChange={() => undefined}
          />
        </>
      );
    }

    renderWithAppProviders(<RefreshHarness />);

    fireEvent.click(
      screen.getByRole("button", { name: "Import selected template update" }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Imported feature flow" }),
    ).toBeTruthy();
    expect(
      await screen.findByDisplayValue("Use imported configuration prompt."),
    ).toBeTruthy();
    expect(screen.getByLabelText("Maximum auto regression retries")).toHaveProperty(
      "value",
      "2",
    );
    expect(screen.getByText("Saved")).toBeTruthy();
    expect(screen.queryByText(/Unsaved edits will not affect/u)).toBeNull();
  });

  it("resets draft edits when switching draft sessions with the same template", () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const secondDraftSession = {
      ...workspace.session,
      session_id: "session-second-draft",
      display_name: "Second blank requirement",
    };

    function SessionHarness(): JSX.Element {
      const [session, setSession] = useState(workspace.session);

      return (
        <>
          <button type="button" onClick={() => setSession(secondDraftSession)}>
            Open second draft session
          </button>
          <TemplateEmptyState
            session={session}
            templates={mockPipelineTemplates}
            providers={mockProviderList}
            selectedTemplateId="template-feature"
            onTemplateChange={() => undefined}
          />
        </>
      );
    }

    renderWithAppProviders(<SessionHarness />);

    fireEvent.change(screen.getByLabelText("Requirement Analysis system prompt"), {
      target: { value: "Session one unsaved prompt." },
    });
    expect(screen.getByLabelText("Requirement Analysis system prompt")).toHaveProperty(
      "value",
      "Session one unsaved prompt.",
    );

    fireEvent.click(screen.getByRole("button", { name: "Open second draft session" }));

    expect(screen.getByLabelText("Requirement Analysis system prompt")).toHaveProperty(
      "value",
      "Analyze the requirement and ask clarifying questions when needed.",
    );
    expect(screen.getByText("Saved")).toBeTruthy();
    expect(screen.queryByText(/Unsaved edits will not affect/u)).toBeNull();
  });

  it("keeps forbidden template and platform fields out of the editor", () => {
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

    const text = screen.getByRole("region", { name: "Template editor" }).textContent ?? "";
    expect(text).not.toContain("stage order");
    expect(text).not.toContain("approval checkpoint");
    expect(text).not.toContain("AgentRole.role_name");
    expect(text).not.toContain("DeliveryChannel");
    expect(text).not.toContain("SQLite");
    expect(text).not.toContain("compression_threshold_ratio");
    expect(text).not.toContain("deterministic test runtime");
    expect(text).not.toContain("prompt_version");
    expect(text).not.toContain("runtime_instructions");
    expect(text).not.toContain("compression_prompt");
  });

  it("uses stable class hooks and wraps long editable content", () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const longTemplate = {
      ...mockPipelineTemplates[1],
      name: "Extremely long template name for a project workflow that still needs to wrap cleanly in the editor",
      stage_role_bindings: mockPipelineTemplates[1].stage_role_bindings.map(
        (binding) => ({
          ...binding,
          system_prompt: "Use project facts only. ".repeat(24).trim(),
        }),
      ),
    };

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={[longTemplate]}
        providers={mockProviderList}
        selectedTemplateId={longTemplate.template_id}
        onTemplateChange={() => undefined}
      />,
    );

    expect(document.querySelector(".template-editor")).toBeTruthy();
    expect(document.querySelector(".template-editor__stages")).toBeTruthy();
    expect(document.querySelector(".template-editor-stage__prompt")).toBeTruthy();
  });
});
