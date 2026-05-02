import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithAppProviders } from "../../../app/test-utils";
import { ConsolePage } from "../../../pages/ConsolePage";

afterEach(() => {
  cleanup();
});

describe("WorkspaceShell", () => {
  it("renders the three workspace regions with inspector closed by default", async () => {
    renderWithAppProviders(<ConsolePage />);

    expect(
      await screen.findByRole("complementary", {
        name: "Project and session sidebar",
      }),
    ).toBeTruthy();
    expect(screen.getByRole("region", { name: "Narrative workspace" })).toBeTruthy();
    expect(screen.getByRole("complementary", { name: "Inspector" })).toBeTruthy();
    expect(screen.getByText("Inspector closed")).toBeTruthy();
    expect(screen.queryByText(/workflow surface comes online/i)).toBeNull();
  });

  it("shows project navigation, delivery summary, and session management affordances", async () => {
    renderWithAppProviders(<ConsolePage />);

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "AI Devflow Engine",
      }),
    ).toBeTruthy();
    expect(
      screen.getByText("C:/Users/lkw/Desktop/github/agent-project/ai-devflow-engine"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Load project" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "New session" })).toBeTruthy();
    expect(screen.getByText("Default delivery")).toBeTruthy();
    expect(await screen.findByText("demo_delivery")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Default project cannot be removed" }),
    ).toHaveProperty("disabled", true);
    expect(screen.getByText("Add workspace shell")).toBeTruthy();
    expect(screen.getByText("Waiting approval")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Rename Add workspace shell" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: "Delete Add workspace shell blocked by active run",
      }),
    ).toHaveProperty("disabled", true);
  });

  it("switches the current project and keeps shell-only destructive actions disabled", async () => {
    renderWithAppProviders(<ConsolePage />);

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "AI Devflow Engine",
      }),
    ).toBeTruthy();
    expect(
      await screen.findByRole("button", {
        name: "Delete Blank requirement unavailable",
      }),
    ).toHaveProperty("disabled", true);

    fireEvent.change(await screen.findByLabelText("Switch project"), {
      target: { value: "project-loaded" },
    });

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Checkout Service",
      }),
    ).toBeTruthy();
    expect(screen.getByText("C:/work/checkout-service")).toBeTruthy();
    expect(await screen.findByText("git_auto_delivery")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Remove Checkout Service unavailable" }),
    ).toHaveProperty("disabled", true);
  });

  it("opens a selected session from the sidebar and shows session metadata", async () => {
    renderWithAppProviders(<ConsolePage />);

    expect(
      await screen.findByRole("region", { name: "Template empty state" }),
    ).toBeTruthy();
    const runningSessionItem = screen
      .getByRole("button", { name: "Open Add workspace shell" })
      .closest("article");
    expect(runningSessionItem).toBeTruthy();
    expect(
      within(runningSessionItem as HTMLElement).getByText("Updated 2026-05-01 09:25"),
    ).toBeTruthy();
    expect(
      within(runningSessionItem as HTMLElement).getByText(
        "Current stage Solution Design",
      ),
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

  it("uses product workspace copy and avoids implementation placeholder text", async () => {
    renderWithAppProviders(<ConsolePage />);

    expect(await screen.findByText("Narrative Workspace")).toBeTruthy();
    expect(screen.getByText("Inspector closed")).toBeTruthy();
    expect(screen.queryByText(/feature slices/i)).toBeNull();
    expect(screen.queryByText(/routing/i)).toBeNull();
    expect(screen.queryByText(/data layer/i)).toBeNull();
    expect(screen.queryByText(/workflow surface comes online/i)).toBeNull();
  });

  it("renders the draft session template selector as narrative feed empty content", async () => {
    renderWithAppProviders(<ConsolePage />);

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
    renderWithAppProviders(<ConsolePage />);

    const editor = await screen.findByRole("region", { name: "Template editor" });
    expect(within(editor).getByText("Run configuration")).toBeTruthy();
    expect(
      within(editor).getByLabelText("requirement_analysis system prompt"),
    ).toBeTruthy();
    expect(within(editor).getByLabelText("requirement_analysis provider")).toBeTruthy();

    fireEvent.change(within(editor).getByLabelText("requirement_analysis system prompt"), {
      target: { value: "Clarify only when missing facts block implementation." },
    });

    expect(within(editor).getByText(/Save this edited system template/u)).toBeTruthy();
    expect(
      within(editor).getByRole("button", { name: "Save as user template" }),
    ).toBeTruthy();
    expect(document.body.textContent ?? "").not.toContain("DeliveryChannel");
    expect(document.body.textContent ?? "").not.toContain("deterministic test runtime");
  });
});
