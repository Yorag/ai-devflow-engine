import {
  NavLink,
  Outlet,
  createBrowserRouter,
  createMemoryRouter,
  type RouteObject,
} from "react-router-dom";

import type { ApiRequestOptions } from "../api/client";
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

type AppRoutesOptions = {
  request?: ApiRequestOptions;
};

export function createAppRoutes(options: AppRoutesOptions = {}): RouteObject[] {
  return [
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
        element: <ConsolePage request={options.request} />,
      },
    ],
  },
  ];
}

export const appRoutes: RouteObject[] = createAppRoutes();

export function createAppRouter() {
  return createBrowserRouter(appRoutes);
}

export function createTestRouter(
  initialEntries: string[] = ["/"],
  options: AppRoutesOptions = {},
) {
  return createMemoryRouter(createAppRoutes(options), { initialEntries });
}
