from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.domain.enums import RunStatus, SessionStatus, StageStatus
from backend.tests.api.test_pause_resume_api import (
    build_app,
    seed_active_run_for_api,
    seed_approval_event_for_api,
    seed_tool_confirmation_event_for_api,
)
from backend.tests.services.test_terminate_run import FakeRuntimePort


def build_terminate_app(tmp_path: Path):
    app = build_app(tmp_path)
    app.state.h45_runtime_port = FakeRuntimePort()
    app.state.h41_runtime_port = app.state.h45_runtime_port
    return app


def test_run_terminate_route_is_documented_in_openapi(tmp_path: Path) -> None:
    app = build_terminate_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    terminate_route = document["paths"]["/api/runs/{runId}/terminate"]["post"]
    assert (
        terminate_route["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RunTerminateRequest"
    )
    assert (
        "anyOf"
        not in terminate_route["requestBody"]["content"]["application/json"]["schema"]
    )
    assert (
        terminate_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RunCommandResponse"
    )
    assert (
        terminate_route["responses"]["404"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        terminate_route["responses"]["409"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        terminate_route["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        terminate_route["responses"]["500"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )
    assert "RunTerminateRequest" in document["components"]["schemas"]
    assert set(terminate_route["responses"]) == {"200", "404", "409", "422", "500"}


def test_post_run_terminate_returns_terminated_session_and_run(
    tmp_path: Path,
) -> None:
    app = build_terminate_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        response = client.post("/api/runs/run-1/terminate", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "terminated"
    assert body["run"]["status"] == "terminated"
    assert body["run"]["is_active"] is False


def test_post_run_terminate_accepts_bodyless_request(tmp_path: Path) -> None:
    app = build_terminate_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        response = client.post("/api/runs/run-1/terminate")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "terminated"
    assert body["run"]["status"] == "terminated"
    assert body["run"]["is_active"] is False


def test_post_run_terminate_refreshes_workspace_approval_to_non_actionable(
    tmp_path: Path,
) -> None:
    app = build_terminate_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.WAITING_APPROVAL,
        session_status=SessionStatus.WAITING_APPROVAL,
        stage_status=StageStatus.WAITING_APPROVAL,
        with_pending_approval=True,
    )
    seed_approval_event_for_api(app)

    with TestClient(app) as client:
        terminate_response = client.post("/api/runs/run-1/terminate", json={})
        workspace = client.get("/api/sessions/session-1/workspace").json()

    assert terminate_response.status_code == 200
    approval = next(
        entry
        for entry in workspace["narrative_feed"]
        if entry["type"] == "approval_request"
    )
    system_status = next(
        entry
        for entry in workspace["narrative_feed"]
        if entry["type"] == "system_status"
    )
    assert approval["is_actionable"] is False
    assert "terminated" in approval["disabled_reason"]
    assert system_status["status"] == "terminated"


def test_post_run_terminate_cancels_pending_tool_confirmation_in_workspace(
    tmp_path: Path,
) -> None:
    app = build_terminate_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.WAITING_TOOL_CONFIRMATION,
        session_status=SessionStatus.WAITING_TOOL_CONFIRMATION,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
        with_pending_tool_confirmation=True,
    )
    seed_tool_confirmation_event_for_api(app)

    with TestClient(app) as client:
        terminate_response = client.post("/api/runs/run-1/terminate", json={})
        workspace = client.get("/api/sessions/session-1/workspace").json()

    assert terminate_response.status_code == 200
    tool_confirmation = next(
        entry
        for entry in workspace["narrative_feed"]
        if entry["type"] == "tool_confirmation"
    )
    system_status = next(
        entry
        for entry in workspace["narrative_feed"]
        if entry["type"] == "system_status"
    )
    assert tool_confirmation["status"] == "cancelled"
    assert tool_confirmation["is_actionable"] is False
    assert system_status["status"] == "terminated"


def test_post_run_terminate_rejects_terminal_run(tmp_path: Path) -> None:
    app = build_terminate_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
    )

    with TestClient(app) as client:
        response = client.post("/api/runs/run-1/terminate", json={})

    assert response.status_code == 409
    assert response.json()["error_code"] == "run_command_not_actionable"
