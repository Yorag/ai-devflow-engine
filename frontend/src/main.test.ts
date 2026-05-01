import type { Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { mountApp, mountEngineeringBaseline } from "./main";

describe("mountEngineeringBaseline", () => {
  it("marks the Vite root as ready without rendering feature UI", () => {
    const rootElement = document.createElement("div");

    mountEngineeringBaseline(rootElement);

    expect(rootElement.dataset.engineeringBaseline).toBe("ready");
    expect(rootElement.textContent).toBe("");
  });
});

describe("mountApp", () => {
  it("renders the React app into the supplied root", () => {
    const rootElement = document.createElement("div");
    const appRoot = {
      render: vi.fn(),
      unmount: vi.fn(),
    } as unknown as Root;
    const createRoot = vi.fn(() => appRoot);

    mountApp(rootElement, createRoot);

    expect(createRoot).toHaveBeenCalledWith(rootElement);
    expect(appRoot.render).toHaveBeenCalledTimes(1);
    expect(rootElement.dataset.engineeringBaseline).toBeUndefined();
  });
});
