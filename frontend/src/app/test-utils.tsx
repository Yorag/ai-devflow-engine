import { QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import type { ApiRequestOptions } from "../api/client";
import {
  mockApiRequestOptions,
  resetMockApiRequestOptions,
} from "../mocks/handlers";
import { createQueryClient } from "./query-client";
import { createTestRouter } from "./router";

type RenderWithAppProvidersOptions = {
  route?: string;
  request?: ApiRequestOptions;
};

export function renderWithAppProviders(
  ui: ReactElement | null,
  options: RenderWithAppProvidersOptions = {},
): RenderResult {
  if (!options.request) {
    resetMockApiRequestOptions();
  }
  const queryClient = createQueryClient();
  const initialEntries = [options.route ?? "/"];
  const request = options.request ?? mockApiRequestOptions;
  const router = ui
    ? createMemoryRouter([{ path: "*", element: ui }], { initialEntries })
    : createTestRouter(initialEntries, { request });

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
