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
