from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import PipelineRunModel
from backend.app.domain.enums import RunStatus, SessionStatus, StageStatus
from backend.app.domain.runtime_refs import GraphThreadStatus
from backend.app.schemas.feed import SystemStatusFeedEntry
from backend.app.services.events import DomainEventType, EventStore
from backend.tests.api.test_pause_resume_api import (
    build_app,
    seed_active_run_for_api,
)
from backend.tests.services.test_rerun_command_projection import (
    FakeCheckpointPort,
    FakeRuntimePort,
    NOW,
    RecordingAuditService,
    build_trace,
)


def build_rerun_app(tmp_path: Path):
    app = build_app(tmp_path)
    app.state.h45_runtime_port = FakeRuntimePort()
    app.state.h41_runtime_port = app.state.h45_runtime_port
    app.state.h45_checkpoint_port = FakeCheckpointPort()
    app.state.h41_checkpoint_port = app.state.h45_checkpoint_port
    app.state.h45_audit_service = RecordingAuditService()
    return app


def seed_rerunnable_run_for_api(
    app,
    *,
    run_status: RunStatus = RunStatus.TERMINATED,
    session_status: SessionStatus = SessionStatus.TERMINATED,
    stage_status: StageStatus = StageStatus.TERMINATED,
) -> None:
    seed_active_run_for_api(
        app,
        run_status=run_status,
        session_status=session_status,
        stage_status=stage_status,
    )
    session = app.state.database_manager.session(DatabaseRole.RUNTIME)
    try:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        run.started_at = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
        run.created_at = run.started_at
        run.updated_at = run.started_at
        session.add(run)
        session.commit()
    finally:
        session.close()


def seed_terminal_system_status_for_api(
    app,
    *,
    status: RunStatus = RunStatus.TERMINATED,
) -> None:
    session = app.state.database_manager.session(DatabaseRole.EVENT)
    try:
        projection = SystemStatusFeedEntry(
            entry_id="entry-system-status-run-1",
            run_id="run-1",
            occurred_at=NOW,
            status=status,
            title=f"Run {status.value}",
            reason=f"Run was {status.value}.",
            retry_action=None,
        )
        EventStore(session, now=lambda: NOW).append(
            DomainEventType.RUN_TERMINATED
            if status is RunStatus.TERMINATED
            else DomainEventType.RUN_FAILED,
            payload={"system_status": projection.model_dump(mode="json")},
            trace_context=build_trace(),
            occurred_at=NOW,
        )
        session.commit()
    finally:
        session.close()


def test_post_session_runs_creates_new_retry_run_and_returns_run_command_response(
    tmp_path: Path,
) -> None:
    app = build_rerun_app(tmp_path)
    seed_rerunnable_run_for_api(app)
    seed_terminal_system_status_for_api(app)

    with TestClient(app) as client:
        response = client.post("/api/sessions/session-1/runs", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "running"
    assert body["session"]["current_run_id"] == body["run"]["run_id"]
    assert body["session"]["latest_stage_type"] == "requirement_analysis"
    assert body["run"]["status"] == "running"
    assert body["run"]["attempt_index"] == 2
    assert body["run"]["trigger_source"] == "retry"
    assert body["run"]["current_stage_type"] == "requirement_analysis"
    assert body["run"]["is_active"] is True


def test_post_session_runs_accepts_bodyless_request(tmp_path: Path) -> None:
    app = build_rerun_app(tmp_path)
    seed_rerunnable_run_for_api(app)
    seed_terminal_system_status_for_api(app)

    with TestClient(app) as client:
        response = client.post("/api/sessions/session-1/runs")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "running"
    assert body["run"]["trigger_source"] == "retry"


def test_post_session_runs_makes_new_run_boundary_visible_in_workspace_and_timeline(
    tmp_path: Path,
) -> None:
    app = build_rerun_app(tmp_path)
    seed_rerunnable_run_for_api(app)
    seed_terminal_system_status_for_api(app)

    with TestClient(app) as client:
        rerun_response = client.post("/api/sessions/session-1/runs", json={})
        new_run_id = rerun_response.json()["run"]["run_id"]
        workspace = client.get("/api/sessions/session-1/workspace").json()
        timeline = client.get(f"/api/runs/{new_run_id}/timeline").json()
        old_timeline = client.get("/api/runs/run-1/timeline").json()

    assert rerun_response.status_code == 200
    assert workspace["current_run_id"] == new_run_id
    assert [run["attempt_index"] for run in workspace["runs"]] == [1, 2]
    assert workspace["runs"][0]["trigger_source"] == "initial_requirement"
    assert workspace["runs"][1]["trigger_source"] == "retry"
    assert timeline["run_id"] == new_run_id
    assert timeline["attempt_index"] == 2
    assert timeline["trigger_source"] == "retry"
    assert timeline["current_stage_type"] == "requirement_analysis"
    system_status = next(
        entry for entry in old_timeline["entries"] if entry["type"] == "system_status"
    )
    assert system_status["retry_action"] == "retry:run-1"


def test_post_session_runs_rejects_non_terminal_current_run(
    tmp_path: Path,
) -> None:
    app = build_rerun_app(tmp_path)
    seed_rerunnable_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        response = client.post("/api/sessions/session-1/runs", json={})

    assert response.status_code == 409
    assert response.json()["error_code"] == "run_command_not_actionable"


def test_post_session_runs_rejects_non_terminal_old_thread_from_runtime_boundary(
    tmp_path: Path,
) -> None:
    app = build_rerun_app(tmp_path)
    app.state.h45_runtime_port = FakeRuntimePort(terminal_status=GraphThreadStatus.RUNNING)
    app.state.h41_runtime_port = app.state.h45_runtime_port
    seed_rerunnable_run_for_api(app)
    seed_terminal_system_status_for_api(app)

    with TestClient(app) as client:
        response = client.post("/api/sessions/session-1/runs", json={})

    assert response.status_code == 409
    assert response.json()["error_code"] == "run_command_not_actionable"


def test_post_session_runs_rejects_session_without_current_run_tail(
    tmp_path: Path,
) -> None:
    app = build_rerun_app(tmp_path)
    seed_rerunnable_run_for_api(app)
    session = app.state.database_manager.session(DatabaseRole.CONTROL)
    try:
        row = session.get(SessionModel, "session-1")
        assert row is not None
        row.current_run_id = None
        session.add(row)
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        response = client.post("/api/sessions/session-1/runs", json={})

    assert response.status_code == 409
    assert response.json()["error_code"] == "run_command_not_actionable"


def test_post_session_runs_route_is_documented_in_openapi(tmp_path: Path) -> None:
    app = build_rerun_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    rerun_route = document["paths"]["/api/sessions/{sessionId}/runs"]["post"]
    assert (
        rerun_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionRerunRequest"
    )
    assert (
        rerun_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/RunCommandResponse"
    )
    assert rerun_route["requestBody"]["required"] is False
    for status_code in ("404", "409", "422", "500"):
        assert (
            rerun_route["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    assert "SessionRerunRequest" in document["components"]["schemas"]
    assert "RunCommandResponse" in document["components"]["schemas"]
    assert set(rerun_route["responses"]) == {"200", "404", "409", "422", "500"}
