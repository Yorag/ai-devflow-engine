# QA-E2E-V6.3-LIVE Worker Evidence

## Metadata

| Field | Value |
| --- | --- |
| claim_id | QA-E2E-V6.3-LIVE |
| lane_id | QA-E2E |
| task_id | V6.3 |
| branch | test/qa-e2e-regression |
| coordination_base | 11a5f19 |
| local_result | blocked |
| expected_coordination_result | blocked |

## Scope

This worker claim investigated whether V6.3 can move from the existing route-fixture `mock_ready` checkpoint to full live Playwright coverage. The worker did not write the coordination store, did not update central plan status, did not update platform or split-plan final status, and did not modify backend, frontend, Playwright fixture, package, or lock files.

## Blocker

Full live V6.3 Playwright coverage is blocked by a missing HTTP/dev-server advancement surface for the deterministic runtime.

The current backend exposes real routes for:

- creating sessions and starting the first run from a requirement
- querying workspace projection
- consuming SSE events
- approval approve/reject commands
- tool confirmation allow/deny commands
- pause, resume, terminate, and rerun commands

However, after `POST /api/sessions/{sessionId}/messages`, the normal HTTP path only creates the initial `requirement_analysis` run/stage state. The source-traced path that advances a run into `waiting_approval` and `waiting_tool_confirmation` exists only in backend Python tests, where test helpers construct `DeterministicRuntimeEngine` directly and call `engine.run_next(...)`.

Without a reviewed backend/runtime-owned route, worker harness, or background advancement mechanism, a browser test cannot reach the required approval and tool confirmation states through live backend orchestration, persistence, projections, and SSE. Adding such a route or harness is outside QA-E2E ownership. Adding another route-level projection fixture would duplicate the already integrated `QA-E2E-V6.3` mock-ready checkpoint and would not satisfy this live claim.

## Source Trace Evidence

- `docs/plans/function-one-platform-plan.md` keeps V6.3 at `[/]` for `Playwright 人工介入路径`.
- `docs/plans/function-one-platform/09-regression-hardening-and-logs.md#v63` states the integrated V6.3 checkpoint is `mock_ready` and that full `[x]` still waits for real backend orchestration, event persistence, and SSE delivery.
- `docs/plans/function-one-acceleration-execution-plan.md` records `QA-E2E-V6.3` as route-fixture `mock_ready`; platform and split status remain `[/]`.
- `backend/tests/api/test_session_message_api.py` verifies `POST /api/sessions/{sessionId}/messages` returns a `running` session with `latest_stage_type=requirement_analysis`, and creates only the initial run/startup events.
- `backend/tests/e2e/test_full_api_flow.py` advances full manual-intervention flow by calling `_advance_until_interrupt_or_stage_result(...)`, which constructs `DeterministicRuntimeEngine` directly and calls `engine.run_next(...)`.
- `backend/app/api/routes/sessions.py`, `backend/app/api/routes/runs.py`, `backend/app/api/routes/approvals.py`, and `backend/app/api/routes/tool_confirmations.py` expose command routes, but no route that advances the deterministic runtime to the next stage or configured interrupt.
- `e2e/playwright.config.ts` starts only the Vite frontend server by default and does not start a backend deterministic advancement harness.
- `e2e/tests/function-one-control-flow.spec.ts` uses route-level projection fixtures and a mocked `EventSource`; it is not live backend coverage.

## Changed Files

- `docs/plans/implementation/v6.3-playwright-control-flow-live.md`
- `docs/plans/acceleration/reports/QA-E2E-V6.3-LIVE.md`

## TDD Evidence

TDD is not applicable to this blocked checkpoint because no production code, test behavior, fixture behavior, frontend source, backend source, package manifest, or lockfile was changed.

The implementation decision was made at the Source Trace Conflict Gate before code changes. The blocker is a missing owner surface, not a defect inside a QA-E2E-owned file.

## Review Evidence

- Spec / source-trace compliance review: no Critical, Important, or Minor findings. The reviewer confirmed the blocked result is justified, no owner boundary is crossed, and the report does not claim `mock_ready`, `implemented`, or live completion.
- Evidence quality / regression-risk review: no Critical, Important, or Minor findings. The reviewer confirmed the report has required blocked-ingest fields, changed files, owner attribution, and verification evidence that explicitly does not claim live coverage.

## Verification Commands

```powershell
npm --prefix e2e run test -- function-one-control-flow.spec.ts
```

Exit code: 0

```text
Running 2 tests using 1 worker
  ok 1 [chromium] tests\function-one-control-flow.spec.ts:83:3 ... covers approval rejection, paused approval, terminate, and rerun focus
  ok 2 [chromium] tests\function-one-control-flow.spec.ts:144:3 ... covers high-risk tool allow, deny, paused disablement, and narrow layout
  2 passed (4.8s)
```

This command verifies the prior mock-ready V6.3 regression remains runnable; it does not unblock or prove live V6.3 coverage.

## Mock-First / Live Status

Existing V6.3 mock-first browser coverage remains in `e2e/tests/function-one-control-flow.spec.ts` under the prior `QA-E2E-V6.3` checkpoint.

This live claim is blocked. It should not be ingested as `implemented` or `mock_ready`.

## Owner Conflict

The missing capability belongs to backend/runtime or integration ownership, not QA-E2E:

- A backend/runtime owner must provide a reviewed way to advance a real run through deterministic approval/tool-confirmation interrupts while preserving normal API, projection, event, and SSE semantics.
- QA-E2E can then add live Playwright coverage against that surface without route fixtures.

## Remaining Risks

- V6.3 remains partially covered by route-level projection fixtures only.
- Browser-level live coverage does not yet prove backend orchestration, event persistence, or SSE delivery for approval rejection, tool confirmation allow/deny, pause/resume, terminate, and rerun.
- A narrow live smoke test that only creates a session and starts a first requirement would overlap V6.2 success-path startup coverage and would not satisfy V6.3 manual-intervention acceptance criteria.

## Commit Readiness

Local result is `blocked`. The diff is scoped to the live claim's implementation plan and evidence report. A checkpoint commit is useful only to let the main coordination session ingest the blocker; it should not be represented as implementation progress for V6.3.
