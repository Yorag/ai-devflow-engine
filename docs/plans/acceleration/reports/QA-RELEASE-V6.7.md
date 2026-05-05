# QA-RELEASE-V6.7 Worker Evidence Report

## Claim

| Field | Value |
| --- | --- |
| Claim | `QA-RELEASE-V6.7` |
| Lane | `QA-RELEASE` |
| Task | `V6.7` |
| Branch | `test/qa-release-candidate` |
| Coordination Base | `73a00b8` |
| Evidence report | `docs/plans/acceleration/reports/QA-RELEASE-V6.7.md` |
| Local result | `reported` |
| Expected ingest result after checkpoint commit | `implemented` |
| Implementation plan | `docs/plans/implementation/v6.7-regression-release-candidate.md` |

Worker HEAD is intentionally not declared here. The main coordination session reads the branch head during ingest.

## Gate Summary

Read-only worker gate passed for `QA-RELEASE-V6.7`:

```text
Command: uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py current-worker --json
Exit code: 0
Key output: claim QA-RELEASE-V6.7, task V6.7, lane QA-RELEASE, branch test/qa-release-candidate, status claimed, coordination_base 73a00b8
```

No coordination store, checkpoint snapshot, `docs/plans/function-one-acceleration-execution-plan.md`, `docs/plans/function-one-platform-plan.md`, split-plan final status, package manifest, lock file, migration, environment file, or Git state was modified.

## Scope

Implemented only `V6.7`: release-candidate regression coverage and acceptance checklist.

Changed files:

- `backend/app/runtime/deterministic.py`
- `backend/tests/regression/test_run_lifecycle_regression.py`
- `backend/tests/regression/test_projection_regression.py`
- `docs/plans/function-one-platform-acceptance-checklist.md`
- `docs/plans/implementation/v6.7-regression-release-candidate.md`
- `docs/plans/acceleration/reports/QA-RELEASE-V6.7.md`

The production change is narrow and was triggered by a V6.7 red regression: successful demo delivery generated a succeeded `DeliveryRecord` and `delivery_result`, but `PipelineRun.status` remained `running`. The fix completes the run/session in the deterministic demo-delivery success path and appends `RUN_COMPLETED` without adding a completed-run `system_status`.

## Implementation Summary

- Added lifecycle regression coverage for the deterministic success path through `Delivery Integration`, including completed run status, one `delivery_result`, succeeded `DeliveryRecord`, second `new_requirement` rejection, and stable history replay.
- Added projection/SSE regression coverage for duplicate approval result events, approval request non-regression, workspace/timeline identity de-duplication, and SSE replay monotonicity.
- Added `docs/plans/function-one-platform-acceptance-checklist.md` covering product, frontend, backend, regression evidence, frontend design gate, log/audit evidence, validation commands, and residual risks.
- Updated the V6.7 implementation plan execution status and recorded the resolved E2E dependency blocker.

## TDD Evidence

Lifecycle behavior RED:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py -v
Exit code: 1
Key output: 2 failed because PipelineRunModel.status was RunStatus.RUNNING after successful delivery, expected RunStatus.COMPLETED.
```

Lifecycle GREEN:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py -v
Exit code: 0
Key output: 2 passed in 2.58s
```

Projection missing-file RED:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_projection_regression.py -v
Exit code: 1
Key output: ERROR: file or directory not found: backend/tests/regression/test_projection_regression.py
```

Projection GREEN:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_projection_regression.py -v
Exit code: 0
Key output: 2 passed in 1.97s
```

Checklist missing-file RED:

```text
Command: rg -n "Release Candidate Acceptance Checklist" docs/plans/function-one-platform-acceptance-checklist.md
Exit code: 1
Key output: system cannot find the file
```

Checklist heading GREEN:

```text
Command: rg -n "Release Candidate Acceptance Checklist|Frontend Design Gate|Log And Audit Evidence|Residual Risks|QA-E2E-V6.3-LIVE|QA-OBS-L6.2" docs/plans/function-one-platform-acceptance-checklist.md
Exit code: 0
Key output: required heading and evidence references printed.
```

Plan-compliance rename rerun:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_projection_regression.py -v
Exit code: 0
Key output: 2 passed in 3.24s
```

## Review Evidence

Subagent-driven execution was not used because this session did not have explicit user authorization to spawn subagents. Inline fallback review was performed against the V6.7 plan, split specs, and slice-workflow requirements.

Spec / plan compliance review findings:

- The initial lifecycle red test exposed a real spec-aligned gap: completed demo delivery must leave the session/run completed, and completed runs must end with `delivery_result`, not `system_status`.
- The deterministic runtime fix is scoped to successful `Delivery Integration` with a delivery result, requires a control session, and leaves existing failed/terminated terminal logic unchanged.
- Projection regression uses existing `WorkspaceProjectionService`, `TimelineProjectionService`, `EventStore`, and SSE helpers instead of duplicating projection services.
- The acceptance checklist cites the three current split specs and all required evidence reports without changing spec documents.

Code quality / testing review findings:

- No Critical or Important issues remain.
- Test-local identity helpers mirror projection identities for `user_message`, `stage_node`, `approval_request`, `approval_result`, `tool_confirmation`, `control_item`, and `delivery_result`.
- The runtime impacted suite confirms the completion fix does not disturb deterministic terminal-state tests or existing deterministic E2E delivery behavior.

## Verification

Focused V6.7 combined regression:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py backend/tests/regression/test_projection_regression.py -v
Exit code: 0
Key output: 4 passed in 3.71s
```

Impacted runtime and E2E regression:

```text
Command: uv run --no-sync python -m pytest backend/tests/e2e/test_full_api_flow.py backend/tests/e2e/test_deterministic_run_flow.py backend/tests/runtime/test_deterministic_terminal_states.py -v
Exit code: 0
Key output: 15 passed in 6.45s
```

Full regression directory:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression -v
Exit code: 0
Key output: 27 passed in 9.51s
```

Playwright release regression:

```text
Command: npm --prefix e2e run test
Exit code: 0
Key output: 3 passed, 2 skipped in 9.2s
```

Dependency check after user-installed Playwright:

```text
Command: npm --prefix e2e ls --depth=0
Exit code: 0
Key output: @playwright/test@1.59.1
```

Focused V6.7 rerun after E2E dependency resolution:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py backend/tests/regression/test_projection_regression.py -v
Exit code: 0
Key output: 4 passed in 7.18s
```

Commit-gate focused rerun:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py backend/tests/regression/test_projection_regression.py -v
Exit code: 0
Key output: 4 passed in 7.84s
```

Commit-gate E2E rerun:

```text
Command: npm --prefix e2e run test
Exit code: 0
Key output: 3 passed, 2 skipped in 5.6s
```

Full backend suite:

```text
Command: uv run --no-sync python -m pytest -q
Exit code: 0
Key output: 1333 passed, 3 warnings in 514.47s
Warnings: existing LangChain adapter warnings about temperature being passed through model_kwargs.
```

Full frontend suite:

```text
Command: npm --prefix frontend run test -- --run
Exit code: 0
Key output: 29 passed test files, 237 passed tests.
```

Frontend build:

```text
Command: npm --prefix frontend run build
Exit code: 0
Key output: tsc --noEmit and Vite production build passed; 137 modules transformed.
```

## Frontend Design Gate

- Register: product UI.
- Repository root has no `PRODUCT.md` or `DESIGN.md`; Impeccable context loader returned `hasProduct: false` and `hasDesign: false`.
- The V6.7 checklist records the inherited baseline as a quiet, professional, high-information-density workspace UI based on the current split specs and Impeccable product-register reference.
- No frontend source or visible UI was modified in this slice.
- The gate remains evidence-based through prior E2E/error/config reports and the passing `npm --prefix e2e run test` command.

## Resolved Blocker

`e2e/` dependencies were initially missing from this worktree, and `npm --prefix e2e run test` exited `1` with `error: unknown command 'test'`. The user installed Playwright locally. After that, `npm --prefix e2e ls --depth=0` reports `@playwright/test@1.59.1`, and `npm --prefix e2e run test` passes.

## Remaining Risks

- The default E2E run skips the two opt-in live backend-backed Playwright tests; route-fixture E2E and full-flow E2E pass.
- Full backend, full frontend, and frontend build were run before the final evidence-only document update. After that, only implementation/evidence/checklist documentation changed and the focused V6.7 backend regression was rerun.
- Current acceptance checklist records prerequisite worker evidence as `reported`; main coordination must still verify checkpoint commits and update central statuses after ingest.

## Commit Readiness

The local worker result is `reported`. After a user-approved checkpoint commit contains the runtime fix, regression tests, implementation plan, acceptance checklist, and this evidence report, the main coordination session can ingest `QA-RELEASE-V6.7` as `implemented`.
