import { cleanup, fireEvent, screen } from "@testing-library/react";
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
});
