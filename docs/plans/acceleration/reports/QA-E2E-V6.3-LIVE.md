# QA-E2E-V6.3-LIVE Worker Evidence

## Metadata

| Field | Value |
| --- | --- |
| claim_id | QA-E2E-V6.3-LIVE |
| lane_id | QA-E2E |
| task_id | V6.3 |
| branch | test/qa-e2e-regression |
| coordination_base | f8ae3e7 |
| local_result | reported |
| post_commit_ingest_expectation | implemented |

## Scope

This worker claim restores the V6.3 live backend-backed Playwright path after the AL06 `F4.4b` rerun response-shape fix. The worktree keeps an opt-in live backend Playwright mode and a live V6.3 spec that uses real REST projections, SSE event frames, and the A4.3a hidden deterministic advancement route.

The worker did not update central plan status, did not update platform or split-plan final status, did not edit current split specs, did not change backend runtime/API/projection source, did not edit frontend source, and did not modify dependency manifests or lockfiles.

## Recovery Summary

The previous checkpoint at `517fbbf` correctly recorded a blocker: live and route-fixture V6.3 both failed rerun focus because the frontend consumed the backend `{ session, run }` rerun response as a bare run. AL06 fixed that owner issue in `AL06-F4.4b-RERUN-FOCUS`, and `test/qa-e2e-regression` merged the integration checkpoint at `f8ae3e7`.

After the merge:

- the route-fixture V6.3 scenario passes with `retry:<run_id>` and `{ session, run }`
- the live backend V6.3 scenario now passes the previously blocked `Run 2 boundary` focus assertion
- the live spec assertion after rerun was narrowed from a fixture-only pending-approval historical disabled message to the live backend truth: Run 1 is historical, the original approval request is already `Rejected`, and no Approve / Reject actions remain

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

## Resolved Blocker

Live V6.3 was blocked by a frontend owner contract mismatch in the rerun response consumer.

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

The previous frontend `RerunAction` path called:

```ts
const run = await createRerun(sessionId, request ?? {});
await invalidateWorkspaceQueries();
focusRunBoundaryWhenAvailable(run.run_id);
```

The old frontend API type declared `createRerun()` as returning a bare `RunSummaryProjection`, so live response consumption lost the actual run id. AL06 fixed this by returning `RunCommandResponse` and focusing `response.run.run_id`. The QA-E2E recovery keeps the rerun focus assertion intact.

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

### Recovery Verification After AL06 F4.4b

Command:

```powershell
npm --prefix e2e run test -- function-one-control-flow.spec.ts
```

Exit code: 0

```text
Running 2 tests using 1 worker
2 passed
```

Command:

```powershell
$env:E2E_LIVE_BACKEND='1'; npm --prefix e2e run test -- function-one-control-flow-live.spec.ts; Remove-Item Env:E2E_LIVE_BACKEND
```

Exit code: 0

```text
Running 2 tests using 1 worker
2 passed
```

Command:

```powershell
npm --prefix e2e run test -- function-one-full-flow.spec.ts
```

Exit code: 0

```text
Running 1 test using 1 worker
1 passed
```

Command:

```powershell
git diff --check
```

Exit code: 0; CRLF normalization warnings only, no whitespace errors.

## Mock-First / Live Status

- Existing route-fixture V6.3 coverage matches the real `retry:<run_id>` projection marker and `{ session, run }` rerun response shape.
- Live backend-backed V6.3 coverage passes for approval request, pause/resume disabled state, rejection, rollback, terminate, rerun focus, SSE, tool confirmation pause/resume, allow, deny, `continue_current_stage` follow-up, narrow viewport, and overflow checks.
- Full live V6.3 is no longer blocked on rerun focus after AL06 F4.4b.

## Review Checkpoint

- Spec/source reviewer found no Critical or Important issues. The reviewer confirmed the blocked owner attribution, live-vs-fixture scope, and retry marker repair are consistent with V6.3, F4.4a, and backend rerun API evidence.
- Code-quality reviewer found two Important issues, both fixed in this checkpoint:
  - Live Playwright `webServer` entries now use `reuseExistingServer: false`, so live runs do not attach to a stale frontend or backend process.
  - The V6.3 route fixture rerun response now matches the backend `{ session, run }` shape, so fixture coverage exposes the same frontend response-consumption blocker as live coverage.
- Code-quality reviewer also noted that `.runtime/e2e-live` can accumulate sessions after interrupted local runs. This is recorded as a remaining risk and is not a blocker for the recovered checkpoint.
- Final re-review after the live reject-submit helper found no Critical or Important issues. It confirmed the helper does not mask product behavior because it still uses the visible approval form, asserts the entered reason and enabled submit state, and retries only DOM replacement/timing failures from live refetch/SSE. It also confirmed live `webServer` `reuseExistingServer: false` and unchanged default fixture mode.

## Owner Conflict

Owner conflict resolved by AL06 frontend runtime UI.

Completed owner fix:

- Frontend `createRerun()` response typing and `RerunAction` consumption now read `RunCommandResponse.run.run_id`.
- `RerunAction` visibility remains tied to `system_status.retry_action = retry:<run_id>`.
- Focus behavior moves to the new run boundary after successful rerun.

QA-E2E follow-up after AL06 fix:

- Completed in this recovery checkpoint.

## Remaining Risks

- Backend harness regression could not be rerun locally because the uv environment lacks pytest and dependency install/sync was not permitted.
- The live backend server uses `.runtime/e2e-live`, so repeated interrupted runs can leave local test sessions. This path is ignored by Git and does not affect committed source, but a unique runtime-root strategy remains a future hardening option.

## Commit Readiness

Local result is `reported`. After this recovery checkpoint commit, the main coordination session can scan and ingest `QA-E2E-V6.3-LIVE` as `implemented`.
