export function mountEngineeringBaseline(rootElement: HTMLElement): void {
  rootElement.dataset.engineeringBaseline = "ready";
}

const rootElement = document.getElementById("root");

if (rootElement) {
  mountEngineeringBaseline(rootElement);
}
