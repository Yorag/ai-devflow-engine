import { QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import { createQueryClient } from "./query-client";
import { createTestRouter } from "./router";

type RenderWithAppProvidersOptions = {
  route?: string;
};

export function renderWithAppProviders(
  ui: ReactElement | null,
  options: RenderWithAppProvidersOptions = {},
): RenderResult {
  const queryClient = createQueryClient();
  const initialEntries = [options.route ?? "/"];
  const router = ui
    ? createMemoryRouter([{ path: "*", element: ui }], { initialEntries })
    : createTestRouter(initialEntries);

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
