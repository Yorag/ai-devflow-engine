import { defineConfig, devices } from "@playwright/test";

const frontendPort = Number(process.env.E2E_FRONTEND_PORT ?? "5173");
const defaultBaseURL = `http://127.0.0.1:${frontendPort}`;
const baseURL = process.env.E2E_BASE_URL ?? defaultBaseURL;
const liveBackend = process.env.E2E_LIVE_BACKEND === "1";
const backendPort = Number(process.env.E2E_BACKEND_PORT ?? "8000");
const apiBaseURL =
  process.env.E2E_API_BASE_URL ?? `http://127.0.0.1:${backendPort}/api`;

if (liveBackend && !process.env.E2E_API_BASE_URL) {
  process.env.E2E_API_BASE_URL = apiBaseURL;
}

const frontendEnv = liveBackend
  ? {
      ...process.env,
      VITE_API_BASE_URL: apiBaseURL,
      E2E_API_BASE_URL: apiBaseURL,
    }
  : process.env;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : liveBackend
      ? [
          {
            command: `uv run --no-sync python e2e/support/live-backend-server.py --host 127.0.0.1 --port ${backendPort} --frontend-origin ${defaultBaseURL}`,
            url: `http://127.0.0.1:${backendPort}/api/openapi.json`,
            reuseExistingServer: false,
            timeout: 120_000,
            cwd: "..",
          },
          {
            command: `npm --prefix ../frontend run dev -- --host 127.0.0.1 --port ${frontendPort}`,
            url: baseURL,
            reuseExistingServer: false,
            timeout: 120_000,
            env: frontendEnv,
          },
        ]
      : {
          command: `npm --prefix ../frontend run dev -- --host 127.0.0.1 --port ${frontendPort}`,
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
});
