# TD-009 Timeline Pause/Resume Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fallback to `superpowers:executing-plans` only when this environment cannot dispatch bounded subagents; preserve the same TDD, review, and verification gates. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close TD-009 by adding focused backend coverage proving pause/resume state is visible through `GET /api/runs/{runId}/timeline`.

**Architecture:** This is a focused regression-test slice. Reuse the H4.5 pause/resume API fixture so the test exercises the public FastAPI routes and timeline endpoint against real SQLite-backed stores. Production code remains unchanged unless the new red test proves the timeline API or projection implementation is missing required behavior.

**Tech Stack:** Python, pytest, FastAPI `TestClient`, SQLAlchemy SQLite test stores, repository-local `uv`.

---

## Source Trace

- `docs/plans/technical-debt-cleanup-index.md` TD-009 records that H4.5 did not explicitly assert `/api/runs/{runId}/timeline` pause/resume replay.
- `docs/plans/acceleration/reports/AL03-H4.5.md` records H4.5 pause/resume service/API coverage and the residual timeline endpoint risk.
- `docs/specs/function-one-backend-engine-design-v1.md` section `7.4` requires pause/resume to restore the same waiting approval or tool-confirmation checkpoint.
- `docs/specs/function-one-backend-engine-design-v1.md` section `8.5.2` defines `RunTimelineProjection` as the single-run read-only replay structure and requires entries to match `SessionWorkspaceProjection.narrative_feed`.
- `docs/specs/function-one-backend-engine-design-v1.md` event contract lists `RunPaused` and `RunResumed` as external domain events that must map to status changes, not new `control_item` entries.

## Branch And Scope Gate

- Branch: `main`.
- Existing unrelated worktree changes are outside TD-009: `frontend/vite.config.ts` and `frontend/src/app/__tests__/`.
- TD-009 writes only:
  - Create: `backend/tests/api/test_run_timeline_api.py`
  - Modify: `docs/plans/implementation/td-009-timeline-pause-resume-replay.md`
- Conditional production files, only if the red test proves a production gap:
  - `backend/app/services/projections/timeline.py`
  - `backend/app/api/routes/runs.py`
- Forbidden: Git write operations, dependency installation, lock/manifest edits, migrations, file deletion or moves, frontend changes, coordination-store updates, central technical-debt index edits.

## Current Coverage Finding

No `backend/tests/api/test_run_timeline_api.py` exists before this slice. Existing H4.5 API tests assert pause/resume command responses and workspace projection behavior, while existing query/timeline tests assert generic timeline projection behavior. They do not explicitly exercise pause/resume through the timeline endpoint.

## Task 1: RED Verification For Missing Focused Timeline Test

**Files:**
- Read: `backend/tests/services/test_pause_resume.py`
- Expected missing before implementation: `backend/tests/api/test_run_timeline_api.py`

- [x] **Step 1: Run the TD-009 verification command before creating the test file**

Run:

```powershell
uv run python -m pytest backend/tests/services/test_pause_resume.py backend/tests/api/test_run_timeline_api.py -q
```

Expected RED output:

```text
ERROR: file or directory not found: backend/tests/api/test_run_timeline_api.py
```

- [x] **Step 2: Record that RED proves the focused timeline API regression is absent**

The expected failure is a coverage gap, not a production-code failure. Continue to Task 2 and do not modify production code before a concrete behavior failure exists.

Actual RED output:

```text
Command: uv run python -m pytest backend/tests/services/test_pause_resume.py backend/tests/api/test_run_timeline_api.py -q
Exit code: 1
Key output: no tests ran in 0.00s; ERROR: file or directory not found: backend/tests/api/test_run_timeline_api.py
```

## Task 2: Add Pause/Resume Timeline API Regression

**Files:**
- Create: `backend/tests/api/test_run_timeline_api.py`
- Reuse helpers from: `backend/tests/api/test_pause_resume_api.py`
- Reuse service test constants/fakes from: `backend/tests/services/test_pause_resume.py`

- [x] **Step 1: Write the focused API tests**

Create `backend/tests/api/test_run_timeline_api.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.db.base import DatabaseRole
from backend.app.db.models.event import DomainEventModel
from backend.app.domain.enums import (
    RunStatus,
    SessionStatus,
    SseEventType,
    StageStatus,
)
from backend.tests.api.test_pause_resume_api import (
    build_app,
    seed_active_run_for_api,
    seed_tool_confirmation_event_for_api,
)


def test_timeline_endpoint_replays_paused_tool_confirmation_state(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.WAITING_TOOL_CONFIRMATION,
        session_status=SessionStatus.WAITING_TOOL_CONFIRMATION,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
        with_pending_tool_confirmation=True,
    )
    seed_tool_confirmation_event_for_api(app)

    with TestClient(app) as client:
        pause_response = client.post("/api/runs/run-1/pause", json={})
        timeline_response = client.get("/api/runs/run-1/timeline")

    assert pause_response.status_code == 200
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    assert timeline["run_id"] == "run-1"
    assert timeline["session_id"] == "session-1"
    assert timeline["status"] == "paused"
    assert timeline["current_stage_type"] == "code_generation"

    tool_confirmation = _single_tool_confirmation(timeline)
    assert tool_confirmation["tool_confirmation_id"] == "tool-confirmation-1"
    assert tool_confirmation["status"] == "pending"
    assert tool_confirmation["is_actionable"] is False
    assert (
        tool_confirmation["disabled_reason"]
        == "Current run is paused; resume it to continue tool confirmation."
    )
    assert not any(
        entry["type"] in {"control_item", "system_status"}
        for entry in timeline["entries"]
    )
    assert [payload["status"] for payload in _session_status_payloads(app)] == [
        "paused"
    ]


def test_timeline_endpoint_replays_resumed_tool_confirmation_state_after_pause(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.WAITING_TOOL_CONFIRMATION,
        session_status=SessionStatus.WAITING_TOOL_CONFIRMATION,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
        with_pending_tool_confirmation=True,
    )
    seed_tool_confirmation_event_for_api(app)

    with TestClient(app) as client:
        pause_response = client.post("/api/runs/run-1/pause", json={})
        paused_timeline_response = client.get("/api/runs/run-1/timeline")
        resume_response = client.post("/api/runs/run-1/resume", json={})
        resumed_timeline_response = client.get("/api/runs/run-1/timeline")

    assert pause_response.status_code == 200
    assert resume_response.status_code == 200
    assert paused_timeline_response.status_code == 200
    assert resumed_timeline_response.status_code == 200

    paused_timeline = paused_timeline_response.json()
    resumed_timeline = resumed_timeline_response.json()
    assert paused_timeline["status"] == "paused"
    assert resumed_timeline["status"] == "waiting_tool_confirmation"
    assert resumed_timeline["run_id"] == "run-1"
    assert resumed_timeline["session_id"] == "session-1"
    assert resumed_timeline["current_stage_type"] == "code_generation"

    tool_confirmation = _single_tool_confirmation(resumed_timeline)
    assert tool_confirmation["tool_confirmation_id"] == "tool-confirmation-1"
    assert tool_confirmation["status"] == "pending"
    assert tool_confirmation["is_actionable"] is True
    assert tool_confirmation["disabled_reason"] is None
    assert not any(
        entry["type"] in {"control_item", "system_status"}
        for entry in resumed_timeline["entries"]
    )
    assert [payload["status"] for payload in _session_status_payloads(app)] == [
        "paused",
        "waiting_tool_confirmation",
    ]


def _single_tool_confirmation(timeline: dict[str, Any]) -> dict[str, Any]:
    tool_confirmations = [
        entry
        for entry in timeline["entries"]
        if entry["type"] == "tool_confirmation"
    ]
    assert len(tool_confirmations) == 1
    return tool_confirmations[0]


def _session_status_payloads(app) -> list[dict[str, Any]]:
    session = app.state.database_manager.session(DatabaseRole.EVENT)
    try:
        rows = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.event_type == SseEventType.SESSION_STATUS_CHANGED
            )
            .order_by(DomainEventModel.sequence_index.asc())
            .all()
        )
        return [dict(row.payload) for row in rows]
    finally:
        session.close()
```

- [x] **Step 2: Run the new API test**

Run:

```powershell
uv run python -m pytest backend/tests/api/test_run_timeline_api.py -q
```

Expected GREEN if current production behavior already satisfies TD-009:

```text
2 passed
```

If this command fails because timeline status, refreshed tool-confirmation actionability, event ordering, or forbidden `control_item` / `system_status` entries are wrong, inspect the failure and make the smallest production change in `backend/app/services/projections/timeline.py` or `backend/app/api/routes/runs.py` that makes the test pass without changing H4.5 semantics.

Actual GREEN output:

```text
Command: uv run python -m pytest backend/tests/api/test_run_timeline_api.py -q
Exit code: 0
Key output: 2 passed in 2.04s
```

No production code change was required.

## Task 3: Final Focused Verification

**Files:**
- Test: `backend/tests/services/test_pause_resume.py`
- Test: `backend/tests/api/test_run_timeline_api.py`

- [x] **Step 1: Run the TD-009 verification command**

Run:

```powershell
uv run python -m pytest backend/tests/services/test_pause_resume.py backend/tests/api/test_run_timeline_api.py -q
```

Expected GREEN:

```text
14 passed
```

Actual GREEN output:

```text
Command: uv run python -m pytest backend/tests/services/test_pause_resume.py backend/tests/api/test_run_timeline_api.py -q
Exit code: 0
Key output: 14 passed in 5.99s
```

- [x] **Step 2: Inspect diff**

Run:

```powershell
git diff -- backend/tests/api/test_run_timeline_api.py docs/plans/implementation/td-009-timeline-pause-resume-replay.md
```

Expected:
- Only TD-009 test and implementation-plan changes.
- No frontend, migration, dependency manifest, lock file, Git metadata, or coordination-store edits.

Actual:
- Main-session review confirmed TD-009 changes are limited to `backend/tests/api/test_run_timeline_api.py` and this implementation plan.
- No production code, frontend file, migration, dependency manifest, lock file, Git metadata, or coordination-store change was needed for TD-009.

## Review Checklist

- [x] The tests exercise public API routes, not service internals only.
- [x] Pause is visible through timeline status and a disabled pending tool-confirmation entry.
- [x] Resume is visible through timeline status and a re-enabled same pending tool-confirmation entry.
- [x] The status event replay order is `paused` then `waiting_tool_confirmation`.
- [x] The tests assert pause/resume does not introduce top-level `control_item` or `system_status` timeline entries.
- [x] No production code was changed unless a red behavior failure proved it necessary.
- [x] Fresh TD-009 verification command was run with `uv run`.

## Execution Notes

- Worker subagent implemented the focused TD-009 coverage and stopped before Git integration.
- Main-session verification reran `uv run python -m pytest backend/tests/api/test_run_timeline_api.py backend/tests/services/test_pause_resume.py -q` and observed `14 passed in 5.81s`.
- Read-only reviewer found no Critical or Important issues and noted a minor same-pending-request assertion gap; main session added explicit `tool_confirmation_id == "tool-confirmation-1"` assertions for both paused and resumed timeline responses before the final verification rerun.
- Reviewer order: worker inline self-review, then main-session spec/plan compliance and code quality/testing/regression risk review.
