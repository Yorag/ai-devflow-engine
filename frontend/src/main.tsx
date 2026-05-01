import React from "react";
import { createRoot, type Root } from "react-dom/client";

import { App } from "./App";
import "./styles/global.css";

export function mountEngineeringBaseline(rootElement: HTMLElement): void {
  rootElement.dataset.engineeringBaseline = "ready";
}

type RenderApp = (rootElement: HTMLElement) => Root;

export function mountApp(
  rootElement: HTMLElement,
  renderApp: RenderApp = createRoot,
): Root {
  const root = renderApp(rootElement);

  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );

  return root;
}

const rootElement = document.getElementById("root");

if (rootElement) {
  mountApp(rootElement);
}
