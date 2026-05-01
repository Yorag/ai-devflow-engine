import { describe, expect, it } from "vitest";

import { mountEngineeringBaseline } from "./main";

describe("mountEngineeringBaseline", () => {
  it("marks the Vite root as ready without rendering feature UI", () => {
    const rootElement = document.createElement("div");

    mountEngineeringBaseline(rootElement);

    expect(rootElement.dataset.engineeringBaseline).toBe("ready");
    expect(rootElement.textContent).toBe("");
  });
});
