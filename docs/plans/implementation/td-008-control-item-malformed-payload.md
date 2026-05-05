# TD-008 Control Item Malformed Payload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task when a subagent tool is available. Fallback to `superpowers:executing-plans` in the current worker session only when no subagent dispatch tool is available. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add focused regression coverage proving malformed `control_item` event payloads do not break control item detail projection or replace valid control item facts.

**Architecture:** Keep the cleanup in the existing projection service boundary. The expected first path is test-only proof of existing defensive parsing in `InspectorProjectionService._control_event`; production code changes are allowed only if a red test exposes an uncaught malformed payload or incorrect projection.

**Tech Stack:** Python, pytest, SQLAlchemy test fixtures, Pydantic projection schemas, repository-local `uv` environment.

---

## Source Trace

- TD index: `docs/plans/technical-debt-cleanup-index.md` row `TD-008`.
- Original evidence: `docs/plans/acceleration/reports/AL02-Q3.4.md`, remaining risk: malformed `control_item` payload handling is indirectly covered but lacks dedicated regression coverage.
- Backend spec: `docs/specs/function-one-backend-engine-design-v1.md` section `8.2` requires `control_item` as a Narrative Feed top-level entry; section `8.4` requires `ControlItemInspectorProjection` to expose directly related control action input/process/output/artifact/metric facts; section `11.2` requires SSE `control_item` payload semantics to match query projection entry semantics.
- Existing implementation target: `backend/app/services/projections/inspector.py`, especially `_control_event()` defensive Pydantic validation.

## Files

- Modify: `backend/tests/projections/test_control_item_detail_projection.py`
- Conditional modify only if red test proves a production gap: `backend/app/services/projections/inspector.py`
- Modify tracking: `docs/plans/implementation/td-008-control-item-malformed-payload.md`

## Execution Path

This worker environment has no subagent dispatch tool, so execution falls back to inline `superpowers:executing-plans` discipline with the same TDD, review, and verification gates. The slice is a single focused regression task, so subtask parallelism is not useful.

## Task 1: Add Malformed `control_item` Payload Regression Coverage

**Files:**
- Test: `backend/tests/projections/test_control_item_detail_projection.py`
- Conditional implementation: `backend/app/services/projections/inspector.py`

- [x] **Step 1: Add the failing regression test**

Add this test near the existing malformed `stage_node` coverage in `backend/tests/projections/test_control_item_detail_projection.py`:

```python
def test_control_item_detail_projection_ignores_malformed_control_item_payloads(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_retry_control_projection(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        original_list_for_session = service._event_store.list_for_session

        def _list_with_malformed_control_items(session_id: str):
            return [
                SimpleNamespace(
                    run_id="run-active",
                    stage_run_id="stage-active",
                    payload={
                        "control_item": {
                            "entry_id": "entry-control-malformed-1",
                            "run_id": "run-active",
                            "occurred_at": (NOW + timedelta(minutes=8)).isoformat(),
                            "type": "control_item",
                            "control_record_id": "control-retry-1",
                            "control_type": "retry",
                            "source_stage_type": "code_review",
                            "target_stage_type": "code_generation",
                            "title": "Malformed retry control item",
                        }
                    },
                ),
                SimpleNamespace(
                    run_id="run-active",
                    stage_run_id="stage-active",
                    payload={
                        "control_item": {
                            "entry_id": "entry-control-malformed-2",
                            "run_id": "run-active",
                            "occurred_at": (NOW + timedelta(minutes=9)).isoformat(),
                            "type": "control_item",
                            "control_record_id": "control-retry-1",
                            "control_type": "not_a_control_type",
                            "source_stage_type": "code_review",
                            "target_stage_type": "code_generation",
                            "title": "Invalid retry control item",
                            "summary": "Invalid enum must be ignored.",
                        }
                    },
                ),
                *original_list_for_session(session_id),
                SimpleNamespace(
                    run_id="run-active",
                    stage_run_id="stage-active",
                    payload={"control_item": "not-a-control-item-payload"},
                ),
                SimpleNamespace(
                    run_id="run-active",
                    stage_run_id="stage-active",
                    payload={
                        "control_item": {
                            "entry_id": "entry-control-malformed-3",
                            "run_id": "run-other",
                            "occurred_at": (NOW + timedelta(minutes=10)).isoformat(),
                            "type": "control_item",
                            "control_record_id": "control-retry-1",
                            "control_type": "retry",
                            "source_stage_type": "code_review",
                            "target_stage_type": "code_generation",
                            "title": "Mismatched run control item",
                            "summary": "Mismatched run payload must be ignored.",
                        }
                    },
                ),
            ]

        monkeypatch.setattr(
            service._event_store,
            "list_for_session",
            _list_with_malformed_control_items,
        )
        projection = service.get_control_item_detail("control-retry-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["control_record_id"] == "control-retry-1"
    assert dumped["process"]["records"]["control_event"]["entry_id"] == (
        "entry-control-retry-1"
    )
    assert dumped["input"]["records"]["trigger_reason"] == (
        "Regression test failed after review."
    )
    assert "entry-control-malformed-1" not in str(dumped)
    assert "entry-control-malformed-2" not in str(dumped)
    assert "Malformed retry control item" not in str(dumped)
    assert "Invalid enum must be ignored." not in str(dumped)
    assert "not-a-control-item-payload" not in str(dumped)
    assert "entry-control-malformed-3" not in str(dumped)
    assert "Mismatched run payload must be ignored." not in str(dumped)
```

- [x] **Step 2: Run the red command**

Run:

```powershell
uv run python -m pytest backend/tests/projections/test_control_item_detail_projection.py::test_control_item_detail_projection_ignores_malformed_control_item_payloads -q
```

Expected before any production change: fail if malformed or contract-invalid payloads are not ignored; pass only if existing defensive parsing is already sufficient.

- [x] **Step 3: Apply minimal implementation only if required**

If the red command fails with a Pydantic validation exception or malformed payload replacing the valid control event, update only `_control_event()` in `backend/app/services/projections/inspector.py` so invalid `control_item` payloads are skipped and parsed payload identity matches the visible run:

```python
try:
    control_item = CONTROL_ITEM_ADAPTER.validate_python(payload)
except ValidationError:
    continue
if (
    control_item.run_id == run.run_id
    and control_item.control_record_id == control_record_id
):
    matched = control_item
```

If the existing code already contains this behavior and the new test passes, leave production code unchanged.

- [x] **Step 4: Run the green focused test**

Run:

```powershell
uv run python -m pytest backend/tests/projections/test_control_item_detail_projection.py::test_control_item_detail_projection_ignores_malformed_control_item_payloads -q
```

Expected pass output:

```text
1 passed
```

- [x] **Step 5: Run the slice verification command**

Run:

```powershell
uv run python -m pytest backend/tests/projections/test_control_item_detail_projection.py -q
```

Expected pass output after this test is added:

```text
7 passed
```

## Review Checklist

- [x] Spec/plan compliance: test covers malformed `control_item` event payloads for the control item detail projection and does not change public API, route, or schema semantics.
- [x] Code quality/testing: test uses real projection service behavior, isolates malformed event payloads through event-store list monkeypatching, and asserts malformed content does not appear in the projection.
- [x] Scope: no frontend, migration, manifest, lock, coordination store, central debt index, or Git write changes.
- [x] Verification: focused control item projection suite is run with fresh output after all code/test changes.

## Results

- Baseline command: `uv run python -m pytest backend/tests/projections/test_control_item_detail_projection.py -q`
  - Exit code: `0`
  - Key output: `6 passed in 1.58s`
- Red command: `uv run python -m pytest backend/tests/projections/test_control_item_detail_projection.py::test_control_item_detail_projection_ignores_malformed_control_item_payloads -q`
  - Exit code: `1`
  - Key output: `AssertionError: assert 'entry-control-malformed-3' == 'entry-control-retry-1'`
  - Root cause: `_control_event()` skipped Pydantic-invalid payloads but accepted a schema-valid `control_item` whose parsed `run_id` did not match the visible run, allowing it to replace the valid event.
- Green command: `uv run python -m pytest backend/tests/projections/test_control_item_detail_projection.py::test_control_item_detail_projection_ignores_malformed_control_item_payloads -q`
  - Exit code: `0`
  - Key output: `1 passed in 0.39s`
- Final verification command: `uv run python -m pytest backend/tests/projections/test_control_item_detail_projection.py -q`
  - Exit code: `0`
  - Key output: `7 passed in 1.81s`
- Production code changed: yes, `backend/app/services/projections/inspector.py` now requires parsed `control_item.run_id` to match the visible run before selecting the control event.
- Review result: inline spec/plan compliance and code quality review found no Critical or Important issues. Subagent review was not available in this worker environment.
- Remaining risk: this closes the focused malformed/contract-invalid `control_item` projection gap for the current detail projection path. It does not add new API, OpenAPI, or SSE schema tests because TD-008 is scoped to projection regression coverage.
