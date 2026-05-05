# TD-006 Project Removal Coverage Implementation Note

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` when a subagent dispatcher is available. This Codex worker has no subagent dispatch tool, so execution uses the `superpowers:executing-plans` fallback inline while preserving the same TDD, review, and verification gates.

**Goal:** Close TD-006 by verifying or adding focused API/service coverage for a real pending-startup blocked Project removal request and a forced runtime-barrier acquisition failure path.

**Architecture:** Keep Project removal semantics unchanged unless focused tests expose a production gap. Add service tests in the Project service suite and API tests in the existing Project removal route suite so the debt index target command covers the two formerly missing paths. Update this note with red/green evidence, review findings, verification output, and debt-index recommendation for the main coordination session.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Pydantic v2, pytest, repository-local `uv run`.

---

## Scope And Sources

**Debt item:** `TD-006`

**Source:** `docs/plans/technical-debt-cleanup-index.md` records that Project removal API coverage lacks a real pending-startup blocked-path request and forced runtime-barrier acquisition failure path.

**Prior evidence:** `docs/plans/acceleration/reports/AL01-C2.9b.md` records implemented Project remove command behavior and the same residual coverage gap.

**Prior implementation plan:** `docs/plans/implementation/c2.9b-project-remove-history.md` defines pending startup publications as active-run blockers and requires runtime-side barrier protection around removal.

**Current implementation paths:**
- `backend/app/services/projects.py`
- `backend/app/api/routes/projects.py`

**Allowed write set for TD-006:**
- `backend/tests/services/test_project_service.py`
- `backend/tests/api/test_project_remove_api.py`
- `docs/plans/implementation/td-006-project-removal-coverage.md`

**Conditional production write set only if red tests prove a production gap:**
- `backend/app/services/projects.py`
- `backend/app/api/routes/projects.py`

**Forbidden:** Git write operations, dependency installs, lock/manifest changes, migrations, deletes/moves, frontend edits, Alembic edits, coordination-store writes, and `docs/plans/technical-debt-cleanup-index.md` edits.

## Branch Gate

- Branch: `main`
- Existing dirty worktree before TD-006: `frontend/vite.config.ts` and `frontend/src/app/__tests__/`, outside this worker's write set.
- Task mode: main-based stabilization, as requested by the user.
- Next Git action: none. Git write operations are prohibited for this worker.

## Execution Plan

### Task 1: Service Coverage

**Files:**
- Modify: `backend/tests/services/test_project_service.py`
- Conditional only if needed: `backend/app/services/projects.py`

- [x] Add helper imports for SQLAlchemy runtime lock forcing and control/runtime seed models.
- [x] Add focused test `test_remove_project_blocks_real_pending_startup_publication_without_mutation`.
- [x] Add focused test `test_remove_project_raises_internal_error_when_runtime_barrier_cannot_be_acquired`.
- [x] Run the focused tests first.

Run:

```powershell
uv run python -m pytest backend/tests/services/test_project_service.py::test_remove_project_blocks_real_pending_startup_publication_without_mutation backend/tests/services/test_project_service.py::test_remove_project_raises_internal_error_when_runtime_barrier_cannot_be_acquired -q
```

Expected:
- If current production behavior is missing, at least one test fails for the asserted behavior.
- If current production behavior already exists, both tests pass and no production service change is made.

### Task 2: API Coverage

**Files:**
- Modify: `backend/tests/api/test_project_remove_api.py`
- Conditional only if needed: `backend/app/api/routes/projects.py`

- [x] Add helper imports for pending startup and runtime lock seeding.
- [x] Add focused test `test_delete_project_blocks_real_pending_startup_publication`.
- [x] Add focused test `test_delete_project_returns_500_when_runtime_barrier_cannot_be_acquired`.
- [x] Run the focused API tests first.

Run:

```powershell
uv run python -m pytest backend/tests/api/test_project_remove_api.py::test_delete_project_blocks_real_pending_startup_publication backend/tests/api/test_project_remove_api.py::test_delete_project_returns_500_when_runtime_barrier_cannot_be_acquired -q
```

Expected:
- If current production behavior is missing, at least one test fails for the asserted behavior.
- If current production behavior already exists, both tests pass and no production API change is made.

### Task 3: Verification

Run:

```powershell
uv run python -m pytest backend/tests/services/test_project_service.py backend/tests/api/test_project_remove_api.py backend/tests/api/test_project_api.py -q
```

Expected: all tests in the debt-index target pass.

## Review Checklist

- Pending-startup tests use real `StartupPublicationModel` and `PipelineRunModel` rows, not a stubbed `ProjectService`.
- Barrier acquisition failure is forced by an independent SQLite runtime write lock before `ProjectService.remove_project()` or `DELETE /api/projects/{projectId}` attempts `BEGIN IMMEDIATE`.
- Blocked pending-startup removal returns structured `ProjectRemoveResult` with `blocked_by_active_run=True` and does not hide the Project or Session.
- Forced barrier acquisition failure maps to `internal_error` / `500` without hiding the Project or Session and without writing a successful/blocked remove audit.
- No production code is changed unless a focused red test proves current production behavior is missing.
- No technical-debt index edit is made by this worker; final output includes the recommended TD-006 index update for the main session.

## Evidence

- Service focused command: `uv run python -m pytest backend/tests/services/test_project_service.py::test_remove_project_blocks_real_pending_startup_publication_without_mutation backend/tests/services/test_project_service.py::test_remove_project_raises_internal_error_when_runtime_barrier_cannot_be_acquired -q`
  - Exit code: `0`
  - Key output: `2 passed in 0.55s`
- API RED command before API tests existed: `uv run python -m pytest backend/tests/api/test_project_remove_api.py::test_delete_project_blocks_real_pending_startup_publication backend/tests/api/test_project_remove_api.py::test_delete_project_returns_500_when_runtime_barrier_cannot_be_acquired -q`
  - Exit code: `1`
  - Key output: both test node ids were not found in `backend/tests/api/test_project_remove_api.py`, confirming the focused API coverage gap.
- API first run after adding tests: same API focused command exited `1` because the tests needed to align with current audit storage and FastAPI dependency override signatures. No production behavior failure was found.
- API GREEN command: same API focused command exited `0` with `2 passed in 1.96s`.
- Final verification command: `uv run python -m pytest backend/tests/services/test_project_service.py backend/tests/api/test_project_remove_api.py backend/tests/api/test_project_api.py -q`
  - Exit code: `0`
  - Key output: `21 passed in 9.99s`
- Reviewer note: read-only review found no Critical or Important issues. Main session reduced the residual pending-startup masking risk by using a terminal `completed` runtime row while keeping `StartupPublicationModel(publication_state="pending")`, so the blocker is proven through the pending startup publication path instead of project-wide active-run scanning.
- Production code changed: no.
- Review result: main-session review found the worker's partially edited `backend/tests/api/test_project_api.py` was unrelated to TD-006 final placement and removed that diff. TD-006 API coverage now lives in `backend/tests/api/test_project_remove_api.py`, matching existing delete-route coverage.
- Debt-index recommendation: mark TD-006 `resolved-by-verification` with verification target `uv run python -m pytest backend/tests/services/test_project_service.py backend/tests/api/test_project_remove_api.py backend/tests/api/test_project_api.py -q`.
