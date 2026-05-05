# QA-E2E-V6.3-LIVE Worker Evidence

## Metadata

| Field | Value |
| --- | --- |
| claim_id | QA-E2E-V6.3-LIVE |
| lane_id | QA-E2E |
| task_id | V6.3 |
| branch | test/qa-e2e-regression |
| coordination_base | cec9bb3 |
| local_result | blocked |
| expected_coordination_result | blocked |

## Scope

This worker claim attempted to replace the existing V6.3 route-fixture `mock_ready` checkpoint with live backend-backed Playwright coverage. The worktree adds an opt-in live backend Playwright mode and a live V6.3 spec that uses real REST projections, SSE event frames, and the A4.3a hidden deterministic advancement route.

The worker did not write the coordination store, did not update central plan status, did not update platform or split-plan final status, did not edit current split specs, did not change backend runtime/API/projection source, did not edit frontend source, and did not modify dependency manifests or lockfiles.

## Changed Files

- `docs/plans/implementation/v6.3-playwright-control-flow-live.md`
- `docs/plans/acceleration/reports/QA-E2E-V6.3-LIVE.md`
- `e2e/playwright.config.ts`
- `e2e/support/live-backend-server.py`
- `e2e/tests/function-one-control-flow-live.spec.ts`
- `e2e/tests/function-one-control-flow.spec.ts`

## Implementation Summary

- Added `E2E_LIVE_BACKEND=1` mode to `e2e/playwright.config.ts`.
- Added `e2e/support/live-backend-server.py`, which runs `backend.app.testing.create_e2e_test_app()` with isolated runtime root and CORS for the Vite origin.
- Added `e2e/tests/function-one-control-flow-live.spec.ts`.
- Added a scoped live-spec reject-submit helper that refills and submits the current approval form instance when live workspace refetch/SSE updates replace the form during the submit window.
- Kept existing route-fixture tests opt-in default behavior unchanged.
- Updated existing V6.3 route fixture terminal `system_status.retry_action` values from the legacy mock-only marker to backend-shaped `retry:<run_id>`.
- Updated the existing V6.3 route fixture rerun API response to match the backend `{ session, run }` response shape, so the fixture no longer masks the live frontend integration defect.

## TDD Evidence

### RED

Command:

```powershell
$env:E2E_LIVE_BACKEND='1'; npm --prefix e2e run test -- function-one-control-flow-live.spec.ts; Remove-Item Env:E2E_LIVE_BACKEND
```

Observed before live backend support:

```text
2 failed
ECONNREFUSED 127.0.0.1:8000
```

This was the expected red result: the live spec existed, but Playwright config did not yet start the backend test app or provide a live API base.

### GREEN / Partial

Command:

```powershell
$env:E2E_LIVE_BACKEND='1'; npm --prefix e2e run test -- function-one-control-flow-live.spec.ts; Remove-Item Env:E2E_LIVE_BACKEND
```

Observed after live backend support:

```text
1 failed, 1 passed
```

Passing scenario:

```text
tests\function-one-control-flow-live.spec.ts › covers live tool confirmation allow and deny follow-up on narrow layout
```

Remaining failure:

```text
expect(getByLabel('Run 2 boundary')).toBeFocused()
Expected: focused
Received: inactive
```

The failure page snapshot shows:

- Run 2 boundary exists.
- Run 2 is the current run.
- Run 2 status is `Running`.
- Run 2 stage is `Requirement Analysis`.
- Composer binds to the new Run 2 run id.

This means the backend rerun command succeeds and the workspace projection refreshes, but the frontend does not focus the new run boundary.

## Blocker

Live V6.3 is blocked by a frontend owner contract mismatch in the rerun response consumer.

Backend route:

```text
POST /api/sessions/{sessionId}/runs
```

returns `RunCommandResponse`:

```json
{
  "session": { "...": "..." },
  "run": { "run_id": "..." }
}
```

Current frontend `RerunAction` calls:

```ts
const run = await createRerun(sessionId, request ?? {});
await invalidateWorkspaceQueries();
focusRunBoundaryWhenAvailable(run.run_id);
```

The existing frontend API type declares `createRerun()` as returning a bare `RunSummaryProjection`, so live response consumption loses the actual run id. The live test cannot be completed without changing frontend source or weakening the focus assertion. Both are outside this QA-E2E worker claim:

- Frontend source is owned by AL06.
- V6.3 acceptance requires rerun focus to the new run boundary.
- Weakening the assertion would hide a real integrated behavior defect.

## Source Trace Evidence

- `docs/plans/function-one-platform/09-regression-hardening-and-logs.md#v63` requires rerun creates a new run and moves focus.
- `docs/plans/function-one-platform/04-human-loop-and-runtime.md#f44a` states the rerun UI still calls the existing `createRerun(sessionId)` API and must consume true `retry:<run_id>` projections.
- `backend/tests/api/test_rerun_command_api.py` asserts the backend response shape is `{ session, run }`.
- `frontend/src/api/runs.ts` currently types `createRerun()` as `Promise<RunSummaryProjection>`.
- `frontend/src/features/runs/RerunAction.tsx` focuses `run.run_id` after calling `createRerun()`.
- The live Playwright snapshot shows a correct new current run boundary but failed focus.

## Verification Commands

### Existing V6.3 Route-Fixture Regression

Command:

```powershell
npm --prefix e2e run test -- function-one-control-flow.spec.ts
```

Exit code: 1

```text
Running 2 tests using 1 worker
  failed ... covers approval rejection, paused approval, terminate, and rerun focus
  ok 2 ... covers high-risk tool allow, deny, paused disablement, and narrow layout
  1 failed
  1 passed
```

Failure:

```text
Expected getByLabel('Run 2 boundary') to be focused.
Received: inactive.
```

### Live V6.3 Focused Regression

Command:

```powershell
$env:E2E_LIVE_BACKEND='1'; npm --prefix e2e run test -- function-one-control-flow-live.spec.ts; Remove-Item Env:E2E_LIVE_BACKEND
```

Exit code: 1

```text
Running 2 tests using 1 worker
  failed covers approval rejection, pause resume, terminate, rerun, and SSE
  passed covers live tool confirmation allow and deny follow-up on narrow layout
  1 failed
  1 passed
```

Failure:

```text
Expected getByLabel('Run 2 boundary') to be focused.
Received: inactive.
```

### Existing V6.2 Success-Path Regression

Command:

```powershell
npm --prefix e2e run test -- function-one-full-flow.spec.ts
```

Exit code: 0

```text
Running 1 test using 1 worker
  ok 1 ... completes requirement, clarification, approvals, and delivery result in the console
  1 passed (3.6s)
```

### Backend Harness Regression Attempt

Command:

```powershell
uv run pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py -q
```

Exit code: 1

```text
ImportError: cannot import name 'UTC' from 'datetime' (D:\miniconda3\lib\datetime.py)
```

Follow-up command:

```powershell
uv run python -m pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py -q
```

Exit code: 1

```text
.venv\Scripts\python.exe: No module named pytest
```

The repository-local uv Python is 3.11.13, but pytest is not installed in the local uv environment. Installing or syncing dependencies is outside the worker permission set without approval.

## Mock-First / Live Status

- Existing route-fixture V6.3 coverage now matches the real `retry:<run_id>` projection marker and `{ session, run }` rerun response shape. It therefore exposes the same rerun focus blocker instead of passing through a fixture-only response shape.
- Live backend-backed V6.3 coverage is partially executable:
  - Approval request, pause/resume disabled state, rejection, rollback, terminate, visible rerun entry, and SSE are exercised up to the rerun focus failure.
  - Tool confirmation pause/resume, allow, deny, `continue_current_stage` follow-up, SSE, narrow viewport, and overflow checks pass.
- Full live V6.3 remains blocked until AL06 fixes frontend rerun response-shape consumption.

## Review Checkpoint

- Spec/source reviewer found no Critical or Important issues. The reviewer confirmed the blocked owner attribution, live-vs-fixture scope, and retry marker repair are consistent with V6.3, F4.4a, and backend rerun API evidence.
- Code-quality reviewer found two Important issues, both fixed in this checkpoint:
  - Live Playwright `webServer` entries now use `reuseExistingServer: false`, so live runs do not attach to a stale frontend or backend process.
  - The V6.3 route fixture rerun response now matches the backend `{ session, run }` shape, so fixture coverage exposes the same frontend response-consumption blocker as live coverage.
- Code-quality reviewer also noted that `.runtime/e2e-live` can accumulate sessions after interrupted local runs. This is recorded as a remaining risk and is not a blocker for the current blocked checkpoint.
- Final re-review after the live reject-submit helper found no Critical or Important issues. It confirmed the helper does not mask product behavior because it still uses the visible approval form, asserts the entered reason and enabled submit state, and retries only DOM replacement/timing failures from live refetch/SSE. It also confirmed live `webServer` `reuseExistingServer: false` and unchanged default fixture mode.

## Owner Conflict

Owner: AL06 frontend runtime UI.

Required owner fix:

- Update frontend `createRerun()` response typing and `RerunAction` consumption to read `RunCommandResponse.run.run_id`, or otherwise consume the true backend response shape without changing backend API semantics.
- Keep `RerunAction` visibility tied to `system_status.retry_action = retry:<run_id>`.
- Keep focus behavior on the new run boundary after successful rerun.

QA-E2E follow-up after AL06 fix:

- Rerun `E2E_LIVE_BACKEND=1 npm --prefix e2e run test -- function-one-control-flow-live.spec.ts`.
- If green, this claim can be continued or re-claimed to update local result from `blocked` to `reported` with expected `implemented`.

## Remaining Risks

- The new live backend server uses `.runtime/e2e-live`, so repeated interrupted runs can leave local test sessions. This path is ignored by Git and does not affect committed source, but test isolation can be improved by adding a unique runtime-root strategy in a future non-blocked checkpoint.
- Backend harness regression could not be rerun locally because the uv environment lacks pytest and dependency install/sync was not permitted.
- Full V6.3 live acceptance cannot be claimed while rerun focus fails.

## Commit Readiness

Local result is `blocked`. A checkpoint commit is useful only to let the main coordination session ingest the blocker and the reusable live E2E harness work. It must not be represented as implementation progress for final V6.3 completion.
