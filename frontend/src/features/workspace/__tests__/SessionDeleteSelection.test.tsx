import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "../../../app/test-utils";
import { mockApiRequestOptions } from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { useWorkspaceStore } from "../workspace-store";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useWorkspaceStore.getState().resetWorkspace();
});

describe("session delete selection", () => {
  it("removes a deleted historical session without changing the current session", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("button", { name: "Open Blank requirement" }),
    ).toHaveProperty("ariaCurrent", "page");

    fireEvent.click(
      screen.getByRole("button", { name: "Delete Renamed checkout flow fix" }),
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("button", {
          name: "Open Renamed checkout flow fix",
        }),
      ).toBeNull();
    });
    expect(
      screen.getByRole("button", { name: "Open Blank requirement" }),
    ).toHaveProperty("ariaCurrent", "page");
    expect(screen.getByRole("region", { name: "Template empty state" })).toBeTruthy();
  });

  it("deletes the current session and leaves the workspace unselected", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    expect(
      await screen.findByRole("button", { name: "Open Blank requirement" }),
    ).toHaveProperty("ariaCurrent", "page");

    fireEvent.click(
      screen.getByRole("button", { name: "Delete Blank requirement" }),
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Open Blank requirement" }),
      ).toBeNull();
    });
    expect(screen.getByRole("heading", { level: 1, name: "Workspace" })).toBeTruthy();
    expect(
      screen.getByText("Create or select a session to review its execution feed."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("region", { name: "Template empty state" }),
    ).toBeNull();
    expect(
      screen
        .getAllByRole("button", { name: /^Open /u })
        .every((button) => button.getAttribute("aria-current") !== "page"),
    ).toBe(true);
  });
});
