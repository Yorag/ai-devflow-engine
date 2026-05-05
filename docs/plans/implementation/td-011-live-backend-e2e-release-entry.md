# TD-011 Live Backend E2E Release Entry Implementation Note

**Goal:** Close TD-011 by making the live backend Playwright control-flow check a stable release/display verification command instead of an ad hoc environment-variable invocation.

**Architecture:** Keep the existing Playwright live backend harness and live control-flow spec unchanged. Add a zero-dependency npm script wrapper that sets `E2E_LIVE_BACKEND=1` and runs `function-one-control-flow-live.spec.ts` through the local Playwright binary. Update verification documentation and the technical-debt index to point at the stable command.

**Tech Stack:** Node.js package scripts, Playwright, Vite frontend dev server, FastAPI live E2E backend harness, repository-local `uv`.

## Scope

**Debt item:** `TD-011`

**Sources:**
- `docs/plans/technical-debt-cleanup-index.md`
- `docs/plans/acceleration/reports/QA-E2E-V6.3-LIVE.md`
- `docs/plans/acceleration/reports/QA-RELEASE-V6.7.md`

**Allowed write set:**
- `e2e/package.json`
- `e2e/support/run-live-e2e.mjs`
- `README.md`
- `docs/development/verification.md`
- `docs/getting-started.md`
- `docs/plans/technical-debt-cleanup-index.md`
- `docs/plans/implementation/td-011-live-backend-e2e-release-entry.md`

**Non-goals:**
- No frontend UI changes.
- No backend API, runtime, projection, or SSE behavior changes.
- No dependency installation, lockfile edits, migrations, environment-file edits, or Git write operations.
- No TD-012 runtime-root cleanup in this slice.

## Plan

- [x] Add `npm --prefix e2e run test:live` as the stable live backend E2E command.
- [x] Implement the script without new dependencies by using a local Node wrapper.
- [x] Update verification docs to use the stable command.
- [x] Mark TD-011 as resolved by current verification.
- [x] Reclassify TD-004 as an accepted single-writer production boundary.
- [x] Run focused command discovery for the new script.
- [x] Run the live backend E2E command.
- [x] Run EventStore focused verification for the TD-004 accepted boundary.

## Verification Targets

```powershell
npm --prefix e2e run test:live -- --list
npm --prefix e2e run test:live
uv run python -m pytest backend/tests/events/test_event_store.py -q
```

## Evidence

- Script discovery command: `npm --prefix e2e run test:live -- --list`
  - Exit code: `1`
  - Key output: `Missing local Playwright dependency. Run npm --prefix e2e install or npm --prefix e2e ci before live E2E verification.`
  - Interpretation: the stable script is reachable and fails closed when local E2E dependencies are absent, rather than falling through to an undeclared global Playwright command.
- Dependency installation after user approval: `npm --prefix e2e ci`
  - Exit code: `0`
  - Key output: `added 3 packages, and audited 4 packages in 1s`; `found 0 vulnerabilities`
- Script discovery after dependency installation: `npm --prefix e2e run test:live -- --list`
  - Exit code: `0`
  - Key output: `Total: 2 tests in 1 file`
- Final live E2E command: `npm --prefix e2e run test:live`
  - Exit code: `0`
  - Key output: `2 passed (13.8s)`; backend web server ran on `http://127.0.0.1:8000`
  - Coverage: live backend manual intervention path through approval rejection, pause/resume, terminate, rerun, SSE, and narrow-layout tool confirmation allow/deny through the project default E2E ports.
- TD-004 focused boundary verification: `uv run python -m pytest backend/tests/events/test_event_store.py -q`
  - Exit code: `0`
  - Key output: `17 passed in 0.47s`
- TD-011 debt-index recommendation: mark `resolved-by-verification`.
