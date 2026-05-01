import { QueryClient, useQueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithAppProviders } from "../../app/test-utils";
import { ConsolePage } from "../ConsolePage";

afterEach(() => {
  cleanup();
});

function QueryClientProbe(): JSX.Element {
  const queryClient = useQueryClient();

  return (
    <output aria-label="query client ready">
      {queryClient instanceof QueryClient ? "ready" : "missing"}
    </output>
  );
}

describe("ConsolePage route baseline", () => {
  it("renders the console placeholder inside the SPA providers", () => {
    renderWithAppProviders(
      <>
        <ConsolePage />
        <QueryClientProbe />
      </>,
    );

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "AI delivery workspace",
      }),
    ).toBeTruthy();
    expect(
      screen.getByText("React SPA baseline is ready for feature slices."),
    ).toBeTruthy();
    expect(screen.getByLabelText("query client ready").textContent).toBe(
      "ready",
    );
  });

  it("supports navigation between home and console routes", async () => {
    renderWithAppProviders(null, { route: "/" });

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Requirement delivery flow engine",
      }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("link", {
        name: "Open console",
      }),
    );

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "AI delivery workspace",
      }),
    ).toBeTruthy();
  });

  it("wraps route content in stable product landmarks", () => {
    renderWithAppProviders(null, { route: "/console" });

    expect(screen.getByRole("banner")).toBeTruthy();
    expect(
      screen.getByRole("navigation", { name: "Primary routes" }),
    ).toBeTruthy();
    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Home" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Console" })).toBeTruthy();
  });
});
