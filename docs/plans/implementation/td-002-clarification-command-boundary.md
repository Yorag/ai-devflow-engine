# TD-002 Clarification Command Boundary Implementation Plan

> **For agentic workers:** This cleanup is a main-based stabilization documentation slice. It does not implement a new outbox, recovery worker, database schema, or runtime command protocol. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the ambiguous H4.1 clarification atomicity debt for the current display-solidification phase by recording the accepted runtime command boundary and the gate that reopens the debt before broader production deployment.

**Architecture:** Keep the existing H4.1 command sequence: required audit gate first, runtime command through `RuntimeOrchestrationService`, then domain/event commits with rollback coverage for uncommitted changes. Treat true cross-store and external-runtime atomicity as outside the current phase until the system introduces real external side effects, multi-worker execution, or a durable migration baseline.

**Tech Stack:** Markdown project plans, current backend verification through `uv run python -m pytest`.

---

## Source Trace

- Debt item: `TD-002` in `docs/plans/technical-debt-cleanup-index.md`.
- Original evidence source: `docs/plans/acceleration/reports/AL03-H4.1.md`.
- Current implementation source: `backend/app/services/clarifications.py`.
- Current regression source: `backend/tests/services/test_clarification_flow.py`.

## Accepted Boundary

The current H4.1 clarification command boundary is accepted only under the current stabilization/display assumptions:

- The default API path uses in-process runtime command ports unless the application state injects a runtime port.
- The service blocks runtime create/resume when the required accepted audit record cannot be written.
- Runtime resume failure rolls back the uncommitted clarification answer, run/stage/session status changes, and `clarification_answered` event append.
- The service does not provide a durable outbox, idempotency key, replay worker, or side-effect reconciliation ledger for a runtime port that has already performed external side effects before a later SQL commit fails.

## Reopen Gate

Reopen TD-002 before any of these conditions become true:

- The clarification runtime port performs external side effects that survive process rollback.
- Multiple backend workers can process commands for the same run or same graph thread.
- A release claim requires automatic recovery after process crash between runtime-port success and SQL commits.
- Clarification command recovery must be guaranteed across separate SQLite files as a formal production data-integrity claim.

When reopened, the cleanup must be an implementation slice, not a documentation slice. It must add one of:

- a durable command outbox with replay/idempotency semantics,
- an idempotent runtime command contract plus persisted command status,
- or a recovery/reconciliation process record that can safely fail the run when the side effect cannot be proven.

## Tasks

### Task 1: Record The Boundary

- [x] Add this implementation note for TD-002.
- [x] Update `docs/plans/technical-debt-cleanup-index.md` with an accepted-boundary status and reopen gate.
- [x] Update `docs/plans/acceleration/reports/AL03-H4.1.md` so the original evidence report no longer leaves the current phase ambiguous.

### Task 2: Verify Existing Guarantees

- [x] Run `uv run python -m pytest backend/tests/services/test_clarification_flow.py backend/tests/services/test_runtime_orchestration_boundary.py backend/tests/schemas/test_run_feed_event_schemas.py -q`.
- [x] Run `git diff --check -- docs/plans/implementation/td-002-clarification-command-boundary.md docs/plans/technical-debt-cleanup-index.md docs/plans/acceleration/reports/AL03-H4.1.md`.

Actual verification result:

```text
uv run python -m pytest backend/tests/services/test_clarification_flow.py backend/tests/services/test_runtime_orchestration_boundary.py backend/tests/schemas/test_run_feed_event_schemas.py -q
Exit code: 0
24 passed in 1.49s
```

Actual diff check result:

```text
git diff --check -- docs/plans/implementation/td-002-clarification-command-boundary.md docs/plans/technical-debt-cleanup-index.md docs/plans/acceleration/reports/AL03-H4.1.md
Exit code: 0
```
