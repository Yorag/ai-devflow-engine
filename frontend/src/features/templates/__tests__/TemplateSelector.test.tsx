import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithAppProviders } from "../../../app/test-utils";
import {
  mockPipelineTemplates,
  mockSessionWorkspaces,
} from "../../../mocks/fixtures";
import { TemplateEmptyState } from "../TemplateEmptyState";

afterEach(() => {
  cleanup();
});

describe("TemplateEmptyState", () => {
  it("renders the draft template empty state inside the narrative feed", () => {
    const workspace = mockSessionWorkspaces["session-draft"];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
      />,
    );

    expect(
      screen.getByRole("region", { name: "Template empty state" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "新功能开发流程",
      }),
    ).toBeTruthy();
    expect(screen.getByText("Requirement Analysis")).toBeTruthy();
    expect(screen.getByText("Solution Design")).toBeTruthy();
    expect(screen.getByText("Code Review")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Bug 修复流程/u })).toBeTruthy();
    expect(
      screen.getByRole("radio", { name: /新功能开发流程/u }),
    ).toHaveProperty("checked", true);
    expect(screen.getByRole("radio", { name: /重构流程/u })).toBeTruthy();
  });

  it("updates the selected template when the user chooses another template", () => {
    const workspace = mockSessionWorkspaces["session-draft"];
    const selectedTemplateIds: string[] = [];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        selectedTemplateId="template-feature"
        onTemplateChange={(templateId) => selectedTemplateIds.push(templateId)}
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: /重构流程/u }));

    expect(selectedTemplateIds).toEqual(["template-refactor"]);
  });

  it("keeps the empty state within template selection boundaries", () => {
    const workspace = mockSessionWorkspaces["session-draft"];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
      />,
    );

    const text = document.body.textContent ?? "";
    expect(text).not.toContain("DeliveryChannel");
    expect(text).not.toContain("SQLite");
    expect(text).not.toContain("compression_threshold_ratio");
    expect(text).not.toContain("deterministic test runtime");
    expect(text).not.toContain("prompt_version");
    expect(text).not.toContain("environment variable");
  });

  it("uses stable class hooks for responsive product styling", () => {
    const workspace = mockSessionWorkspaces["session-draft"];

    renderWithAppProviders(
      <TemplateEmptyState
        session={workspace.session}
        templates={mockPipelineTemplates}
        selectedTemplateId="template-feature"
        onTemplateChange={() => undefined}
      />,
    );

    expect(document.querySelector(".template-empty-state")).toBeTruthy();
    expect(document.querySelector(".template-selector__options")).toBeTruthy();
    expect(document.querySelector(".template-stage-list")).toBeTruthy();
  });
});
