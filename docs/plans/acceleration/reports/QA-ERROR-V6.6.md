# QA-ERROR-V6.6 Worker Evidence Report

- Claim: `QA-ERROR-V6.6`
- Lane: `QA-ERROR`
- Task: `V6.6`
- Branch: `test/qa-error-regression`
- Worktree: `C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.worktrees\test-qa-error-regression`
- Coordination base: `2e682ec`
- Implementation plan: `docs/plans/implementation/v6.6-error-states-regression.md`
- Local result: `reported`
- Expected ingest result after user-approved checkpoint commit: `implemented`

## Execution Path

Execution path: `subagent-driven-development`

- User explicitly allowed subagents, and all subagents used `gpt-5.5` with `xhigh` reasoning.
- Backend implementer owned backend error catalog, approval/run service mapping, and backend tests.
- Frontend implementer owned `ErrorState`, frontend API error-code types, component integrations, and CSS.
- Separate read-only reviewers performed spec/plan compliance review and code-quality/testing/regression review.
- Main agent retained claim validation, Source Trace gate, review-fix integration, final verification, implementation plan update, and this evidence report.

## Changed Files

Backend implementation:

- `backend/app/api/error_codes.py`
- `backend/app/services/approvals.py`
- `backend/app/services/runs.py`

Backend tests:

- `backend/tests/regression/test_error_contract_regression.py`
- `backend/tests/api/test_approval_api.py`
- `backend/tests/api/test_pause_resume_api.py`
- `backend/tests/api/test_rerun_command_api.py`
- `backend/tests/api/test_terminate_run_api.py`
- `backend/tests/services/test_approval_commands.py`
- `backend/tests/services/test_pause_resume.py`
- `backend/tests/services/test_rerun_command_projection.py`
- `backend/tests/services/test_terminate_run.py`

Frontend implementation:

- `frontend/src/api/types.ts`
- `frontend/src/features/errors/ErrorState.tsx`
- `frontend/src/features/approvals/ApprovalBlock.tsx`
- `frontend/src/features/feed/ToolConfirmationBlock.tsx`
- `frontend/src/features/runs/RerunAction.tsx`
- `frontend/src/styles/global.css`

Frontend tests:

- `frontend/src/features/errors/__tests__/ErrorState.test.tsx`

Tracking:

- `docs/plans/implementation/v6.6-error-states-regression.md`
- `docs/plans/acceleration/reports/QA-ERROR-V6.6.md`

## Unchanged Central Files

- Shared coordination store
- `docs/plans/function-one-acceleration-execution-plan.md`
- `docs/plans/function-one-platform-plan.md`
- `docs/plans/function-one-platform/09-regression-hardening-and-logs.md`
- Split specs under `docs/specs/`
- Dependency manifests, lock files, migrations, and environment files
- `frontend/src/features/inspector/*`

## Implementation Summary

- Added `approval_not_actionable` and `run_command_not_actionable` to the backend error-code catalog with HTTP 409 defaults.
- Remapped approval command state conflicts from generic `validation_error` to `approval_not_actionable` while preserving request-shape validation behavior.
- Remapped run command state conflicts in rerun, pause, resume, and terminate flows to `run_command_not_actionable`.
- Added V6.6 regression coverage for registered error codes, catalog HTTP status matching, safe user-visible messages, trace header propagation, paused approval, DeliveryChannel-not-ready, illegal rerun, and non-paused resume.
- Added `ErrorState` and `formatApiError()` for reusable frontend API error presentation with request id, recovery copy, field-error support, unknown fallback, and sensitive diagnostic hiding.
- Replaced raw API error rendering in approval, rerun, and tool confirmation UI with `ErrorState`.
- Added restrained product UI styling for `.error-state` with mobile single-column behavior and long-text wrapping.

## TDD Evidence

Backend RED:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_error_contract_regression.py -v
Exit code: 1
Key output: 4 failed. Missing approval_not_actionable and run_command_not_actionable; paused approval, illegal rerun, and non-paused resume returned validation_error.
```

Backend GREEN:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_error_contract_regression.py -v
Exit code: 0
Key output: 4 passed
```

Backend review-fix coverage:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_error_contract_regression.py -v
Exit code: 0
Key output: 5 passed
```

Frontend RED:

```text
Command: npm --prefix frontend run test -- ErrorState
Exit code: 1
Key output: Failed to resolve import "../ErrorState".
```

Frontend GREEN:

```text
Command: npm --prefix frontend run test -- ErrorState
Exit code: 0
Key output: 1 passed, 4 tests passed
```

Frontend sensitive-detail hardening RED/GREEN:

```text
Command: npm --prefix frontend run test -- ErrorState
RED exit code: 1
Key output: token/client_secret/credential-shaped message was shown instead of hidden.
GREEN exit code: 0
Key output: 1 passed, 5 tests passed
```

## Review Evidence

Spec / plan compliance review:

- Initial Important finding: DeliveryChannel-not-ready did not use the V6.6 full response contract helper.
- Fix: added `test_delivery_channel_not_ready_uses_stable_contract_code()` with trace headers, catalog/status/message checks, and `detail_ref` assertion.
- Re-review result: previous Important finding resolved; no new Critical or Important issues.

Code-quality / testing / regression review:

- Result: no Critical or Important issues.
- Minor fixed: expanded frontend sensitive-message filtering to hide token, secret, client secret, and credential-shaped diagnostics.
- Minor left as residual cleanup: stale `.rerun-action__error` and `.tool-confirmation-block__error` selectors remain harmless; `.approval-block__error` is still used by `RejectReasonForm`.

## Verification

Focused backend:

```text
Command: uv run --no-sync python -m pytest backend/tests/regression/test_error_contract_regression.py -v
Exit code: 0
Key output: 5 passed
```

Impacted backend:

```text
Command: uv run --no-sync python -m pytest backend/tests/api/test_approval_api.py backend/tests/api/test_rerun_command_api.py backend/tests/api/test_pause_resume_api.py backend/tests/api/test_terminate_run_api.py backend/tests/services/test_approval_commands.py backend/tests/services/test_rerun_command_projection.py backend/tests/services/test_pause_resume.py backend/tests/services/test_terminate_run.py backend/tests/errors/test_error_code_catalog.py backend/tests/regression/test_error_contract_regression.py -v
Exit code: 0
Key output: 91 passed
```

Focused and impacted frontend:

```text
Command: npm --prefix frontend run test -- ErrorState
Exit code: 0
Key output: 1 passed, 5 tests passed

Command: npm --prefix frontend run test -- ApprovalBlock RerunAction ErrorState
Exit code: 0
Key output: 3 passed, 14 tests passed

Command: npm --prefix frontend run test -- ToolConfirmationBlock ErrorState
Exit code: 0
Key output: 2 passed, 11 tests passed
```

Full backend:

```text
Command: uv run --no-sync python -m pytest -q
Exit code: 0
Key output: 1288 passed, 3 warnings in 577.39s
Warnings: existing LangChain adapter warnings that temperature should be specified explicitly instead of passed through model_kwargs.
```

Frontend build:

```text
Command: npm --prefix frontend run build
Exit code: 0
Key output: tsc --noEmit and vite build passed; 137 modules transformed.
```

Full frontend:

```text
Command: npm --prefix frontend run test -- --run
Exit code: 1
Key output: 1 failed, 216 passed. Failing test: src/features/inspector/__tests__/InspectorPanel.test.tsx "opens stage, control item, tool confirmation, and delivery result details" because Testing Library finds delivery-record-1 twice.

Isolation command: npm --prefix frontend run test -- InspectorPanel
Exit code: 1
Key output: same InspectorPanel failure reproduces in isolation.
Scope check: git diff shows no changes under frontend/src/features/inspector.
```

## Remaining Risk

- Full frontend Vitest is blocked by an existing InspectorPanel test ambiguity outside this claim's write set. V6.6 focused and impacted frontend tests pass, and frontend build passes.
- Backend regression covers representative approval, rerun, resume, and delivery readiness responses, but not every possible pause/terminate response path directly.
- Frontend formatter tests now cover credential, token, secret, credential, and stack-shaped diagnostics, but field-error formatting and `error_code` / `request_id` snake-case compatibility remain residual coverage opportunities.

## Commit Readiness

The local worker result is `reported`.

After a user-approved checkpoint commit containing the implementation plan, code, tests, and this evidence report, the main coordination session can ingest this claim as `implemented`.

No Git merge, PR, push, central Claim Ledger update, platform-plan status update, split-plan final status update, acceleration checkpoint snapshot update, or coordination-store write was performed.
