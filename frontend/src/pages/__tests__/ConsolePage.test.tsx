import { QueryClient, useQueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Link, useLocation } from "react-router-dom";

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

function RouterProbe(): JSX.Element {
  const location = useLocation();

  return (
    <>
      <output aria-label="current path">{location.pathname}</output>
      <Link to="/console">Console link</Link>
    </>
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
      screen.getByText(
        "Project, session, run, and delivery views will appear here as the workflow surface comes online.",
      ),
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

  it("wraps custom UI in router context for focused component tests", () => {
    renderWithAppProviders(<RouterProbe />, { route: "/custom" });

    expect(screen.getByLabelText("current path").textContent).toBe("/custom");
    expect(screen.getByRole("link", { name: "Console link" })).toBeTruthy();
  });

  it("uses product empty-state copy instead of implementation notes", () => {
    renderWithAppProviders(null, { route: "/console" });

    expect(screen.getByText("Workspace")).toBeTruthy();
    expect(screen.getByText("Projects")).toBeTruthy();
    expect(screen.getByText("Runs")).toBeTruthy();
    expect(screen.getByText("Delivery")).toBeTruthy();
    expect(screen.queryByText(/baseline/i)).toBeNull();
    expect(screen.queryByText(/feature slices/i)).toBeNull();
    expect(screen.queryByText("Routing")).toBeNull();
    expect(screen.queryByText("Data layer")).toBeNull();
    expect(screen.queryByText("Design tone")).toBeNull();
  });
});
