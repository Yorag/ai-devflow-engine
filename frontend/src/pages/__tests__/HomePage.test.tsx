import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithAppProviders } from "../../app/test-utils";

describe("HomePage", () => {
  it("presents the website landing page and keeps console navigation available", () => {
    renderWithAppProviders(null, { route: "/" });

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /make delivery work traceable/i,
      }),
    ).toBeTruthy();
    expect(screen.getByText(/local-first ai delivery workflow/i)).toBeTruthy();

    expect(screen.getByRole("navigation", { name: /website sections/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Overview" }).getAttribute("href")).toBe(
      "#overview",
    );
    expect(screen.getByRole("link", { name: "Flow" }).getAttribute("href")).toBe("#flow");
    expect(screen.getByRole("link", { name: "Control" }).getAttribute("href")).toBe(
      "#control",
    );
    expect(screen.getByRole("link", { name: "Start" }).getAttribute("href")).toBe("#start");
    expect(screen.getByRole("link", { name: "Docs" }).getAttribute("href")).toContain(
      "github.com",
    );
    expect(
      screen.getByRole("link", { name: /view flow/i }).getAttribute("href"),
    ).toBe("#flow");
    expect(screen.getAllByRole("link", { name: /open console/i })[0].getAttribute("href")).toBe(
      "/console",
    );

    const deliveryImages = screen.getAllByRole("img", {
      name: /ai devflow engine delivery flow/i,
    });
    expect(deliveryImages).toHaveLength(1);
    expect(deliveryImages[0].getAttribute("src")).toContain("agent-delivery-flow.svg");

    expect(screen.getByText(/preserve intent/i)).toBeTruthy();
    expect(screen.getByText(/review before code/i)).toBeTruthy();
    expect(screen.getByText(/record delivery/i)).toBeTruthy();
    expect(screen.getByText(/one path, six visible stages/i)).toBeTruthy();
    expect(screen.getByText(/human control stays in the workflow/i)).toBeTruthy();
    expect(screen.queryByAltText(/orchestration architecture/i)).toBeNull();
  });
});
