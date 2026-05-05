import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const playwrightCli = fileURLToPath(
  new URL("node_modules/@playwright/test/cli.js", new URL("..", import.meta.url)),
);

if (!existsSync(playwrightCli)) {
  console.error(
    "Missing local Playwright dependency. Run `npm --prefix e2e install` or `npm --prefix e2e ci` before live E2E verification.",
  );
  process.exit(1);
}

const args = [
  playwrightCli,
  "test",
  "function-one-control-flow-live.spec.ts",
  ...process.argv.slice(2),
];
const result = spawnSync(process.execPath, args, {
  cwd: packageRoot,
  env: {
    ...process.env,
    E2E_LIVE_BACKEND: "1",
  },
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
