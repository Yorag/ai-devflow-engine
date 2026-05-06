# Runtime Agent Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fallback to `superpowers:executing-plans` only if subagent dispatch is unavailable or the task boundary cannot be precisely limited. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the no-op first-run dispatch handoff with a production `RuntimeExecutionService` that reconstructs persisted runtime context, calls the runtime engine, and projects startup execution failures.

**Architecture:** `GraphRuntimeCommandPort` remains the graph command/status port. `RuntimeExecutionService` owns production execution dispatch: it opens fresh DB sessions, reconstructs `RuntimeExecutionContext` from committed run/stage/snapshot/thread rows, creates graph runtime/checkpoint ports, invokes `RuntimeEngine.start/run_next/resume`, and marks run/stage/session/thread failed if engine startup fails. `create_app()` wires the service by default; tests may override it with fakes.

**Tech Stack:** Python 3.11+, FastAPI dependency injection, SQLAlchemy sessions split by role, Pydantic runtime contracts, LangGraph runtime engine protocol, pytest through `uv run --extra dev`.

---

## Source Trace

- User target: fix the production gap where `GraphRuntimeCommandPort` was only a status/command port and the default app path still no-oped after first `new_requirement`.
- Product source: `docs/specs/function-one-product-overview-v1.md` requires first `new_requirement` to auto-start the first `PipelineRun` and failed/terminated tails to get top-level `system_status`.
- Backend source: `docs/specs/function-one-backend-engine-design-v1.md` treats graph state as execution recovery truth, `PipelineRun`/`StageRun` as product truth, and failed `PipelineRun` as projecting to failed `Session`.
- Platform plan source: `docs/plans/function-one-platform-plan.md` records runtime boundary first, production user runs through LangGraph, and deterministic test runtime remains test/demo harness only.
- Code fact: current `backend/app/services/runtime_dispatch.py` has a no-op default dispatcher and `backend/app/main.py` does not register a real production dispatcher.

No Source Trace Conflict Gate conflict is identified. This slice does not expose `__test__/runtime/advance`, does not route production through `backend.app.testing`, and does not make `GraphRuntimeCommandPort` an executor.

## File Map

- Modify: `backend/app/services/runtime_dispatch.py`
  - Keep `RuntimeDispatchCommand` and `RuntimeExecutionDispatcher`.
  - Add `RuntimeExecutionService`, context reconstruction, engine invocation methods, default engine factory, stage-scoped runner, bounded startup/resume continuation, and failure projection.
  - Remove no-op as the default app-state fallback; tests can inject explicit fakes.
- Create: `backend/app/runtime/persistent_checkpointer.py`
  - Add a SQLite-backed LangGraph checkpointer for the default production engine factory.
- Modify: `backend/app/runtime/langgraph_engine.py`
  - Return a completed terminal result when the saved LangGraph state has no next node.
- Modify: `backend/app/services/runs.py`
  - Persist the run template snapshot as a runtime artifact at first-run startup.
- Modify: `backend/app/services/publication_boundary.py`
  - Delete staged `StageArtifactModel` rows before staged `StageRunModel` rows during startup publication cleanup.
- Modify: `backend/app/main.py`
  - Register `RuntimeExecutionService` on `app.state.runtime_execution_dispatcher` in `create_app()`.
- Modify: `backend/app/api/routes/sessions.py`
  - Keep route schema unchanged.
  - Call dispatcher after first-run startup; route no longer relies on missing app-state no-op and no longer suppresses escaped dispatcher failures.
- Modify: clarification, approval, and tool-confirmation command routes/services
  - Return `RuntimeInterrupt` and `RuntimeResumePayload` from command services and call the dispatcher resume boundary from routes.
- Create: `backend/tests/services/test_runtime_execution_service.py`
  - Service-level TDD coverage for context reconstruction, graph port boundary, engine start/run_next/resume calls, stage-scoped execution, startup/resume continuation, persisted template snapshots, durable checkpointer, terminal projection, and failed execution projection.
- Modify: `backend/tests/api/test_session_message_api.py`
  - Keep API contract assertions.
  - Override dispatcher where route tests need isolation.
  - Replace status-only failure expectation with service-level failure projection coverage.
- Modify: `docs/plans/implementation/runtime-agent-dispatch.md`
  - Record this plan and fresh verification evidence.

## API And OpenAPI Checklist

- Path remains `POST /api/sessions/{sessionId}/messages`.
- Request and response schemas remain `SessionMessageAppendRequest` and `SessionMessageAppendResponse`.
- Response codes remain covered by existing OpenAPI route test.
- No frontend API client or public test runtime route is introduced.

## Log & Audit Integration

- Runtime execution failure writes product truth first: `PipelineRun.failed`, current `StageRun.failed`, `Session.failed`, `GraphThread.failed`, `StageUpdated`, and `RunFailed`/`system_status`.
- Runtime failure audit action: `runtime.execution.failed`, actor `system`, target `run`, result `failed`, with `run_id`, `stage_run_id`, `graph_thread_id`, `error_type`, and redacted reason.
- Runtime failure log payload type: `runtime_execution_failed`, category `runtime`, level `error`, with inherited `request_id`, run `trace_id`, `correlation_id`, `span_id`, `parent_span_id`, `stage_run_id`, and `graph_thread_id`.
- Log/audit write failures do not replace domain state, domain event, or projection facts.
- Sensitive error strings are summarized and bounded before stage summary/system status/audit/log metadata.

## Subagent Execution Contract

Implementer boundaries:

- Allowed create/modify files:
  - `backend/app/services/runtime_dispatch.py`
  - `backend/app/main.py`
  - `backend/app/api/routes/sessions.py`
  - `backend/tests/services/test_runtime_execution_service.py`
  - `backend/tests/api/test_session_message_api.py`
  - `docs/plans/implementation/runtime-agent-dispatch.md`
- Allowed commands:
  - `rg` and `Get-Content` read-only checks.
  - `uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py -q`
  - `uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py -q`
  - `uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py backend/tests/api/test_session_message_api.py backend/tests/services/test_start_first_run.py backend/tests/runtime/test_langgraph_engine.py -q`
- Forbidden:
  - Do not modify current split specs.
  - Do not use `backend.app.testing`, `DeterministicRuntimeEngine`, or `__test__/runtime/advance` in production wiring.
  - Do not make `GraphRuntimeCommandPort` implement `RuntimeEngine`.
  - Do not update coordination store, platform-plan final states, lock files, manifests, env files, or migrations.
  - Do not run Git write actions.

Review order:

1. Spec / plan compliance reviewer.
2. Code quality, test sufficiency, and regression risk reviewer.
3. Fix Critical or Important findings and re-review affected changes.

## Task 1: Runtime Execution Service

**Files:**
- Create/modify: `backend/app/services/runtime_dispatch.py`
- Test: `backend/tests/services/test_runtime_execution_service.py`

- [x] **Step 1: Write failing context reconstruction test**

Add a service test that starts a real first run through `RunLifecycleService` helpers, injects a fake engine factory, calls `RuntimeExecutionService.dispatch_started_run(...)`, and asserts:

```python
assert fake_engine.start_calls[0].context.run_id == result.run.run_id
assert fake_engine.start_calls[0].context.session_id == result.session.session_id
assert fake_engine.start_calls[0].context.thread.thread_id == result.run.graph_thread_ref
assert fake_engine.start_calls[0].context.thread.status is GraphThreadStatus.RUNNING
assert fake_engine.start_calls[0].context.provider_snapshot_refs
assert fake_engine.start_calls[0].context.model_binding_snapshot_refs
assert type(fake_engine.start_calls[0].runtime_port).__name__ == "GraphRuntimeCommandPort"
assert type(fake_engine.start_calls[0].checkpoint_port).__name__ == "GraphCheckpointPort"
```

Run:

```powershell
uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py::test_dispatch_started_run_reconstructs_context_and_calls_runtime_engine_start -q
```

Expected red: import error for `RuntimeExecutionService` or missing `engine.start` call.

- [x] **Step 2: Implement minimal service and context builder**

Implement `RuntimeExecutionService` with injected `DatabaseManager`, optional `engine_factory`, optional `log_writer_factory`, optional `audit_service_factory`, and `now`.

`dispatch_started_run(command)` must:

```python
with manager.session(DatabaseRole.CONTROL) as control_session, ...:
    context = self._build_context(...)
    engine = self._engine_factory(RuntimeEngineFactoryInput(...))
    result = engine.start(
        context=context,
        runtime_port=GraphRuntimeCommandPort(graph_session),
        checkpoint_port=GraphCheckpointPort(graph_session),
    )
```

It must load `PipelineRunModel`, current `StageRunModel`, `GraphThreadModel`, `ProviderSnapshotModel`, and `ModelBindingSnapshotModel`, validate command/run/thread identity, and build `RuntimeExecutionContext`.

- [x] **Step 3: Add run_next and resume boundary tests**

Add tests that call `service.run_next(run_id=..., trace_context=...)` and `service.resume(interrupt=..., resume_payload=...)` with fake engine methods, proving the service boundary can call all production `RuntimeEngine` execution entrypoints.

Run:

```powershell
uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py::test_run_next_reconstructs_context_and_calls_runtime_engine_run_next backend/tests/services/test_runtime_execution_service.py::test_resume_reconstructs_context_and_calls_runtime_engine_resume -q
```

Expected red before implementation: missing service methods.

- [x] **Step 4: Implement run_next and resume**

Add `run_next(...)` and `resume(...)` methods using the same context reconstruction and graph ports. These methods must not call deterministic runtime or test harness code.

- [x] **Step 5: Add failing execution projection test**

Add a fake engine whose `start()` raises `RuntimeError("provider unavailable: secret-token")`. Assert after dispatch:

```python
assert run.status is RunStatus.FAILED
assert stage.status is StageStatus.FAILED
assert control_session.status is SessionStatus.FAILED
assert thread.status == "failed"
assert system_status.payload["system_status"]["status"] == "failed"
assert system_status.payload["system_status"]["retry_action"] == f"retry:{run_id}"
assert "secret-token" not in stage.summary
assert failed_audit.result is AuditResult.FAILED
```

Run:

```powershell
uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py::test_dispatch_started_run_failure_marks_run_failed_and_projects_system_status -q
```

Expected red: current dispatcher leaves run/stage/session/thread running or has no service.

- [x] **Step 6: Implement failure projection**

When engine construction or `start/run_next/resume` raises, service must mark persisted product/graph facts failed, append `STAGE_UPDATED`, append terminal `RUN_FAILED` system status through `TerminalStatusProjector`, write best-effort audit/log, commit all product/event/graph facts, and not leave a started run silently running.

## Task 2: Default App Wiring And API Regression

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/routes/sessions.py`
- Modify: `backend/tests/api/test_session_message_api.py`

- [x] **Step 1: Add failing default wiring test**

Add an API or service test asserting:

```python
app = create_app(settings)
assert type(app.state.runtime_execution_dispatcher).__name__ == "RuntimeExecutionService"
```

Run:

```powershell
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_create_app_registers_runtime_execution_service_by_default -q
```

Expected red: app state has no dispatcher or uses no-op.

- [x] **Step 2: Wire production service in create_app**

Set:

```python
app.state.runtime_execution_dispatcher = RuntimeExecutionService(
    database_manager=app.state.database_manager,
    environment_settings=environment_settings,
)
```

Default app path must not use no-op, deterministic harness, or status-only dispatcher.

- [x] **Step 3: Update route tests for explicit fakes**

Route tests that assert first-run startup details may set `app.state.runtime_execution_dispatcher = CapturingRuntimeDispatcher(app)` so API tests stay isolated from live provider execution. Add a dedicated test proving production default is real.

- [x] **Step 4: Run focused API and impacted tests**

Run:

```powershell
uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py -q
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py -q
uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py backend/tests/api/test_session_message_api.py backend/tests/services/test_start_first_run.py backend/tests/runtime/test_langgraph_engine.py -q
```

Expected green: all selected tests pass.

## Completion Checklist

- [x] `RuntimeExecutionDispatcher` and `RuntimeExecutionService` are explicit production boundaries.
- [x] `GraphRuntimeCommandPort` remains graph command/status only.
- [x] Dispatcher reconstructs `RuntimeExecutionContext` from persisted run/stage/snapshot/thread rows.
- [x] Dispatcher invokes production `RuntimeEngine.start`, `run_next`, and `resume` entrypoints.
- [x] `create_app()` default dispatcher is real, not no-op, deterministic harness, or status-only.
- [x] First startup execution failure becomes failed run/stage/session/thread plus projectable `system_status`.
- [x] `__test__/runtime/advance` remains test harness only.
- [x] API/OpenAPI contract remains unchanged.
- [x] Fresh verification evidence is recorded before commit gate.

## Execution Notes

- The default production dispatcher auto-continues completed `start` and `resume` results through bounded `run_next` calls until a waiting, failed, or terminal result is reached.
- The default LangGraph factory uses a stage-scoped runner so each invoked stage gets its own persisted `StageRunModel`, `StageStarted` event, model binding, provider snapshot, objective, and output schema.
- Continuation bound uses persisted graph stage count plus the run snapshot `max_auto_regression_retries` allowance for the current three-node regression retry loop.
- Template snapshots are persisted as `StageArtifactModel(artifact_type="template_snapshot")` because this slice does not include schema/migration approval.
- Production default uses `SQLiteLangGraphCheckpointSaver`; deterministic runtime and `__test__/runtime/advance` remain outside the default app path.

## Review Findings Addressed

- Dispatcher exceptions escaped from first-run startup are no longer swallowed by `POST /sessions/{sessionId}/messages`.
- Default engine factory reads the persisted run template snapshot instead of rebuilding from the current mutable template.
- Default checkpointer is persistent across service instances instead of `InMemorySaver`.
- `RUN_TERMINATED` terminal projection writes a top-level `system_status` instead of using the session-status payload shape.
- Resume failure after graph resume cancels the pending `GraphInterrupt`.
- Later LangGraph stages are persisted before projection and use the correct stage-specific binding.
- Startup and resume success paths continue after completed stage results instead of silently leaving the run running with no production caller.
- Auto-regression retry routes fit within the continuation bound.

## Verification Evidence

- `uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py -q` -> `16 passed`.
- `uv run --extra dev python -m pytest backend/tests/runtime/test_langgraph_engine.py -q` -> `15 passed`.
- `uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py -q` -> `11 passed` with a post-success Windows temp cleanup warning.
- `uv run --extra dev python -m pytest backend/tests/services/test_runtime_execution_service.py backend/tests/api/test_session_message_api.py backend/tests/services/test_start_first_run.py backend/tests/runtime/test_langgraph_engine.py -q` -> `56 passed`.
- `uv run --extra dev python -m pytest backend/tests/services/test_clarification_flow.py backend/tests/api/test_clarification_reply_api.py backend/tests/services/test_approval_commands.py backend/tests/api/test_approval_api.py backend/tests/services/test_tool_confirmation_commands.py backend/tests/api/test_tool_confirmation_api.py -q` -> `60 passed`.
- Reviewer re-review: no Critical/Important findings remain.

## Residual Risks

- Continuation bound encodes the current auto-regression retry loop width as three steps; if the graph retry shape changes, the bound and regression test must change together.
- The default `ToolRegistry()` is still empty unless a production registry wiring source is added in a later slice.
- SQLite checkpointer persistence is covered for basic cross-service reuse; high-contention concurrent write behavior remains a later hardening concern.
