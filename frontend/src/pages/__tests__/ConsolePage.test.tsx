import { QueryClient, useQueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Link, useLocation } from "react-router-dom";

import { renderWithAppProviders } from "../../app/test-utils";
import { mockApiRequestOptions } from "../../mocks/handlers";
import { ConsolePage } from "../ConsolePage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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
  it("uses the real API client by default instead of fixture handlers", async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(<ConsolePage />, { request: undefined });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(fetchMock.mock.calls.some(([input]) => input === "/api/projects")).toBe(true);
  });

  it("renders the workspace shell inside the SPA providers", async () => {
    renderWithAppProviders(
      <>
        <ConsolePage request={mockApiRequestOptions} />
        <QueryClientProbe />
      </>,
    );

    expect(
      await screen.findByRole("complementary", {
        name: "Project and session sidebar",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("region", { name: "Narrative workspace" }),
    ).toBeTruthy();
    const shell = screen.getByRole("region", { name: "Workspace shell" });
    expect(shell.getAttribute("class")).toContain(
      "workspace-shell--inspector-closed",
    );
    expect(screen.queryByRole("complementary", { name: "Inspector" })).toBeNull();
    expect(screen.queryByText("Inspector closed")).toBeNull();
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
        name: "Workspace",
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

  it("uses product workspace copy instead of implementation notes", async () => {
    renderWithAppProviders(null, { route: "/console" });

    expect(await screen.findByText("Narrative Workspace")).toBeTruthy();
    expect(await screen.findByText("C:/Users/.../ai-devflow-engine")).toBeTruthy();
    expect(screen.queryByText("Default delivery")).toBeNull();
    expect(screen.queryByText("Inspector closed")).toBeNull();
    expect(screen.queryByText(/workflow surface comes online/i)).toBeNull();
    expect(screen.queryByText(/baseline/i)).toBeNull();
    expect(screen.queryByText(/feature slices/i)).toBeNull();
    expect(screen.queryByText("Routing")).toBeNull();
    expect(screen.queryByText("Data layer")).toBeNull();
    expect(screen.queryByText("Design tone")).toBeNull();
  });
});
