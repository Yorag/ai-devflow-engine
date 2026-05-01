import {
  NavLink,
  Outlet,
  createBrowserRouter,
  createMemoryRouter,
  type RouteObject,
} from "react-router-dom";

import { ConsolePage } from "../pages/ConsolePage";
import { HomePage } from "../pages/HomePage";

function AppShell(): JSX.Element {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <p className="brand-title">AI DevFlow Engine</p>
          <p className="brand-subtitle">Local workflow console</p>
        </div>
        <nav className="app-nav" aria-label="Primary routes">
          <NavLink className="nav-link" to="/" aria-label="Home" end>
            Home
          </NavLink>
          <NavLink className="nav-link" to="/console" aria-label="Console">
            Console
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

export const appRoutes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <HomePage />,
      },
      {
        path: "console",
        element: <ConsolePage />,
      },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(appRoutes);
}

export function createTestRouter(initialEntries: string[] = ["/"]) {
  return createMemoryRouter(appRoutes, { initialEntries });
}
