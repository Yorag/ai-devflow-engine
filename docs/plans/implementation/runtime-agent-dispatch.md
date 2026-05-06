# Runtime Agent Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fallback to `superpowers:executing-plans` only if subagent dispatch is unavailable or the task boundary cannot be precisely limited. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trigger a backend runtime dispatch boundary after the first `new_requirement` successfully creates the initial `PipelineRun`.

**Architecture:** Keep `RunLifecycleService.start_first_run()` as the transactional startup owner, then call an injectable runtime dispatcher from the `POST /api/sessions/{sessionId}/messages` route only after startup returns. The default dispatcher is a no-op boundary so production can wire a durable queue or runtime runner through `app.state` without forcing unsafe LangGraph execution inside the HTTP transaction.

**Tech Stack:** Python 3.11+, FastAPI dependency injection, Pydantic v2, SQLAlchemy-backed tests, existing `TraceContext`, `PipelineRunModel`, `StageRunModel`, `StageType`, and pytest through `uv run --extra dev`.

---

## Source Trace

- Product source: `docs/specs/function-one-product-overview-v1.md` acceptance item 11 says the first requirement message must automatically start the first `PipelineRun`.
- Backend API source: `docs/specs/function-one-backend-engine-design-v1.md` section 9.1 says `POST /api/sessions/{sessionId}/messages` with `new_requirement` must create the run snapshots, graph definition, first graph thread, first workspace ref, first message event, and initial `requirement_analysis` `StageRun`.
- Backend runtime source: `docs/specs/function-one-backend-engine-design-v1.md` section 4.2 says `PipelineRun` and `StageRun` status advancement belongs to the runtime orchestration boundary.
- Existing plan source: `docs/plans/implementation/v6.1-backend-full-api-flow.md` records that current deterministic runtime advancement is in-process test harness only and no public/background runtime advance exists.
- Current code fact: `backend/app/api/routes/sessions.py` calls `SessionService.start_run_from_new_requirement(...)`; `backend/app/services/runs.py` creates committed run/thread/stage/event/audit records but does not call `RuntimeEngine.start()`, `RuntimeEngine.run_next()`, `StageAgentRuntime`, a queue, or a worker.

No Source Trace Conflict Gate conflict is identified. This slice does not expose deterministic runtime to users, does not add a public runtime-advance API, and does not reinterpret first-run startup semantics.

## File Map

- Create: `backend/app/services/runtime_dispatch.py`
  - Owns `RuntimeDispatchCommand`, `RuntimeExecutionDispatcher`, `NoopRuntimeExecutionDispatcher`, and `runtime_dispatcher_from_app_state()`.
  - Does not read or write database state and does not run LangGraph directly.
- Modify: `backend/app/api/routes/sessions.py`
  - Adds a dispatcher dependency.
  - Calls the dispatcher after `start_run_from_new_requirement(...)` returns successfully.
  - Leaves clarification reply and error paths unchanged.
- Modify: `backend/tests/api/test_session_message_api.py`
  - Adds a fake dispatcher.
  - Extends the first-requirement test to assert dispatch occurs exactly once with committed run/stage identity.
  - Extends the duplicate requirement rejection test to assert no second dispatch occurs.

## API And OpenAPI Checklist

- Route path remains `POST /api/sessions/{sessionId}/messages`.
- Method, request schema, response schema, and documented error responses remain unchanged.
- Existing OpenAPI assertion `test_session_message_route_is_documented_for_new_requirement` remains the contract check for this route.
- No frontend API client, schema field, or status enum change is part of this slice.

## Log & Audit Integration

- First-run startup audit/log behavior remains owned by `RunLifecycleService`.
- This slice introduces a dispatch boundary, not a runtime state transition; it must not use logs as product truth and must not write run/stage status.
- The dispatcher receives inherited `request_id`, `trace_id`, `correlation_id`, `span_id`, and run/stage/thread identifiers through `TraceContext`.
- A later durable dispatcher slice can add enqueue logs, queue persistence, retry policy, failure-to-system-status projection, and background worker evidence. This slice only proves that the startup command hands off to that boundary after the transactional startup is visible.

## Subagent Execution Contract

Implementer boundaries:

- Allowed create/modify files:
  - `backend/app/services/runtime_dispatch.py`
  - `backend/app/api/routes/sessions.py`
  - `backend/tests/api/test_session_message_api.py`
  - `docs/plans/implementation/runtime-agent-dispatch.md`
- Allowed commands:
  - `rg` and `Get-Content` read-only checks.
  - `uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message -q`
  - `uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py -q`
  - `uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py backend/tests/api/test_startup_publication_visibility.py backend/tests/services/test_start_first_run.py -q`
- Forbidden:
  - Do not modify current split specs.
  - Do not expose deterministic runtime as a user route or setting.
  - Do not run LangGraph inside the startup transaction.
  - Do not update the historical coordination store or acceleration plan status.
  - Do not run Git write actions.
  - Do not install or upgrade dependencies.

Review order:

1. Spec / plan compliance review.
2. Code quality, test sufficiency, and regression risk review.
3. Fix Critical or Important findings and re-review affected changes.

## Task 1: Runtime Dispatch Hook

**Files:**
- Create: `backend/app/services/runtime_dispatch.py`
- Modify: `backend/app/api/routes/sessions.py`
- Test: `backend/tests/api/test_session_message_api.py`

- [x] **Step 1: Write the failing dispatch test**

Add a fake dispatcher to `backend/tests/api/test_session_message_api.py`:

```python
class CapturingRuntimeDispatcher:
    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app
        self.commands = []
        self.visibility_checks = []

    def dispatch_started_run(self, command) -> None:  # noqa: ANN001
        self.commands.append(command)
        with self.app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
            run = session.get(PipelineRunModel, command.run_id)
            stage = session.get(StageRunModel, command.stage_run_id)
            self.visibility_checks.append((run is not None, stage is not None))
```

In `test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message`, assign the dispatcher before creating the `TestClient`:

```python
dispatcher = CapturingRuntimeDispatcher(app)
app.state.runtime_execution_dispatcher = dispatcher
```

After existing `run_id` and `stage_run_id` assertions, add:

```python
assert len(dispatcher.commands) == 1
command = dispatcher.commands[0]
assert command.session_id == created["session_id"]
assert command.run_id == run_id
assert command.stage_run_id == stage_run_id
assert command.stage_type is StageType.REQUIREMENT_ANALYSIS
assert command.graph_thread_id == run.graph_thread_ref
assert command.trace_context.request_id == "req-new-requirement"
assert command.trace_context.correlation_id == "corr-new-requirement"
assert dispatcher.visibility_checks == [(True, True)]
```

Run:

```powershell
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message -q
```

Expected red result:

```text
FAILED ... AttributeError: 'State' object has no attribute 'runtime_execution_dispatcher'
```

or:

```text
FAILED ... assert 0 == 1
```

The expected failure must show that the route does not dispatch after startup.

- [x] **Step 2: Add the dispatch service boundary**

Create `backend/app/services/runtime_dispatch.py`:

```python
from __future__ import annotations

from typing import Protocol

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.enums import StageType
from backend.app.domain.trace_context import TraceContext


class RuntimeDispatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    graph_thread_id: str = Field(min_length=1)
    trace_context: TraceContext


class RuntimeExecutionDispatcher(Protocol):
    def dispatch_started_run(self, command: RuntimeDispatchCommand) -> None: ...


class NoopRuntimeExecutionDispatcher:
    def dispatch_started_run(self, command: RuntimeDispatchCommand) -> None:
        del command


def runtime_dispatcher_from_app_state(request: Request) -> RuntimeExecutionDispatcher:
    dispatcher = getattr(request.app.state, "runtime_execution_dispatcher", None)
    if dispatcher is None:
        return NoopRuntimeExecutionDispatcher()
    return dispatcher


__all__ = [
    "NoopRuntimeExecutionDispatcher",
    "RuntimeDispatchCommand",
    "RuntimeExecutionDispatcher",
    "runtime_dispatcher_from_app_state",
]
```

- [x] **Step 3: Call the dispatcher after successful startup**

In `backend/app/api/routes/sessions.py`, import the new boundary:

```python
from backend.app.services.runtime_dispatch import (
    RuntimeDispatchCommand,
    RuntimeExecutionDispatcher,
    runtime_dispatcher_from_app_state,
)
```

Add the dependency to `append_session_message`:

```python
    runtime_dispatcher: RuntimeExecutionDispatcher = Depends(
        runtime_dispatcher_from_app_state
    ),
```

After `started = service.start_run_from_new_requirement(...)` succeeds and before returning the response, call the dispatcher with a run-trace-aligned command. Isolate dispatcher transport failures so a committed startup response is not turned into a 500:

```python
    try:
        runtime_dispatcher.dispatch_started_run(
            RuntimeDispatchCommand(
                session_id=started.session.session_id,
                run_id=started.run.run_id,
                stage_run_id=started.stage.stage_run_id,
                stage_type=started.stage.stage_type,
                graph_thread_id=started.run.graph_thread_ref,
                trace_context=TraceContext.model_validate(
                    {
                        **trace_context.model_dump(),
                        "trace_id": started.run.trace_id,
                        "parent_span_id": trace_context.span_id,
                        "span_id": f"runtime-dispatch-started-{started.run.run_id}",
                        "created_at": datetime.now(UTC),
                        "session_id": started.session.session_id,
                        "run_id": started.run.run_id,
                        "stage_run_id": started.stage.stage_run_id,
                        "graph_thread_id": started.run.graph_thread_ref,
                    }
                ),
            )
        )
    except Exception:
        _LOGGER.exception(
            "Runtime dispatch failed after first run startup.",
            extra={
                "session_id": started.session.session_id,
                "run_id": started.run.run_id,
                "stage_run_id": started.stage.stage_run_id,
            },
        )
```

Do not call the dispatcher for `clarification_reply` or exception paths.

- [x] **Step 4: Run focused green test**

Run:

```powershell
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message -q
```

Expected green result:

```text
1 passed
```

- [x] **Step 5: Add duplicate rejection no-dispatch assertion**

In `test_new_requirement_rejects_non_draft_or_existing_run_session`, assign a `CapturingRuntimeDispatcher` before `TestClient`, then assert after the second rejected post:

```python
assert len(dispatcher.commands) == 1
```

This proves the rejected duplicate request does not enqueue or dispatch a second runtime start.

- [x] **Step 6: Run route and impacted regressions**

Run:

```powershell
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py -q
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py backend/tests/api/test_startup_publication_visibility.py backend/tests/services/test_start_first_run.py -q
```

Expected:

```text
all selected tests pass
```

Actual output:

```text
RED:
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message -q
Exit code: 1
FAILED ... assert 0 == 1

GREEN:
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message -q
Exit code: 0
1 passed in 1.52s

REVIEW RED:
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message backend/tests/api/test_session_message_api.py::test_new_requirement_dispatch_failure_does_not_hide_committed_startup -q
Exit code: 1
FAILED ... assert command.trace_context.trace_id == run_trace_id
FAILED ... assert 500 == 200

REVIEW GREEN:
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message backend/tests/api/test_session_message_api.py::test_new_requirement_dispatch_failure_does_not_hide_committed_startup -q
Exit code: 0
2 passed in 2.23s

ROUTE:
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py -q
Exit code: 0
7 passed in 5.69s

IMPACTED:
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py backend/tests/api/test_startup_publication_visibility.py backend/tests/services/test_start_first_run.py -q
Exit code: 0
24 passed in 10.77s
```

## Completion Checklist

- [x] First `new_requirement` dispatches exactly once after run startup is committed and visible.
- [x] Duplicate rejected `new_requirement` does not dispatch.
- [x] Clarification reply path remains unchanged.
- [x] Public API schema remains unchanged and OpenAPI route test still passes.
- [x] No deterministic test runtime route or user-facing runtime mode is introduced.
- [x] No split spec, coordination store, lock file, or dependency manifest is changed.
