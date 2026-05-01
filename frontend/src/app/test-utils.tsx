import { QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { RouterProvider } from "react-router-dom";

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

  if (ui) {
    return render(
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
    );
  }

  const router = createTestRouter([options.route ?? "/"]);

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
