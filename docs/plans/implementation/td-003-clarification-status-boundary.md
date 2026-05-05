# TD-003 Clarification Status Boundary Implementation Plan

> **For agentic workers:** This cleanup runs inline because the current main worktree contains unrelated user changes and the write set is narrow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ClarificationRecord.status` explicit in the runtime model without adding a database migration before the Alembic baseline is fixed.

**Architecture:** Add a small `ClarificationStatus` contract enum and expose `ClarificationRecordModel.status` as a derived domain property from the existing persisted `answer` / `answered_at` fields. This keeps current storage stable and avoids new runtime columns until TD-013 provides a migration baseline.

**Tech Stack:** Python 3.11+, SQLAlchemy model properties, pytest through `uv run`.

---

## Source Trace

- Debt item: `TD-003` in `docs/plans/technical-debt-cleanup-index.md`.
- Evidence source: `docs/plans/acceleration/reports/AL03-H4.1.md`.
- Backend spec trace: `docs/specs/function-one-backend-engine-design-v1.md` lists `ClarificationRecord.status` and states clarification answers must resume the same `Requirement Analysis` stage.
- Constraint: `TD-013` shows Alembic has no current revision or head, so this slice must not add runtime database columns.

## File Structure

- Modify: `backend/app/domain/enums.py`
  - Add `ClarificationStatus` with `pending` and `answered`.
- Modify: `backend/app/db/models/runtime.py`
  - Add a read-only derived `ClarificationRecordModel.status` property.
- Modify: `backend/tests/db/test_runtime_model_boundary.py`
  - Add focused model-boundary coverage proving the explicit status property exists and remains non-column-backed.
- Modify: `docs/plans/technical-debt-cleanup-index.md`
  - Record that the status drift is cleaned while rich metadata remains open.

## Tasks

### Task 1: Red Test

- [x] Add `test_clarification_record_exposes_derived_status_without_schema_column` to `backend/tests/db/test_runtime_model_boundary.py`.
- [x] Run `uv run python -m pytest backend/tests/db/test_runtime_model_boundary.py::test_clarification_record_exposes_derived_status_without_schema_column -q`.
- [x] Confirm it fails because `ClarificationStatus` or `ClarificationRecordModel.status` is missing.

Actual red result:

```text
Exit code: 1
ImportError: cannot import name 'ClarificationStatus' from 'backend.app.domain.enums'
```

### Task 2: Minimal Implementation

- [x] Add `ClarificationStatus` to `backend/app/domain/enums.py`.
- [x] Add `ClarificationRecordModel.status` in `backend/app/db/models/runtime.py`.
- [x] Run the focused red test again and confirm it passes.

Actual green result:

```text
uv run python -m pytest backend/tests/db/test_runtime_model_boundary.py::test_clarification_record_exposes_derived_status_without_schema_column -q
Exit code: 0
1 passed in 0.03s
```

### Task 3: Documentation And Regression

- [x] Update `docs/plans/technical-debt-cleanup-index.md` so TD-003 no longer treats the status attribute as unresolved.
- [x] Run `uv run python -m pytest backend/tests/db/test_runtime_model_boundary.py backend/tests/services/test_clarification_flow.py -q`.
- [x] Run `git diff --check -- backend/app/domain/enums.py backend/app/db/models/runtime.py backend/tests/db/test_runtime_model_boundary.py docs/plans/technical-debt-cleanup-index.md docs/plans/implementation/td-003-clarification-status-boundary.md`.

Actual regression result:

```text
uv run python -m pytest backend/tests/db/test_runtime_model_boundary.py backend/tests/services/test_clarification_flow.py -q
Exit code: 0
13 passed in 1.92s
```

Actual diff check result:

```text
git diff --check -- backend/app/domain/enums.py backend/app/db/models/runtime.py backend/tests/db/test_runtime_model_boundary.py docs/plans/technical-debt-cleanup-index.md docs/plans/implementation/td-003-clarification-status-boundary.md
Exit code: 0
```
