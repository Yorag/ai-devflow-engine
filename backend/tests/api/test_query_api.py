from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProjectModel, SessionModel
from backend.app.db.models.event import EventBase
from backend.app.db.models.log import LogBase
from backend.app.db.models.runtime import RuntimeBase
from backend.app.main import create_app
from backend.tests.projections.test_workspace_projection import _seed_workspace


NOW = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)


def build_query_api_app(tmp_path: Path):
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    app = create_app(settings=settings)
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.RUNTIME))
    EventBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.EVENT))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    _seed_workspace(app.state.database_manager)
    return app


def test_get_session_workspace_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/sessions/session-1/workspace",
            headers={
                "X-Request-ID": "req-workspace",
                "X-Correlation-ID": "corr-workspace",
            },
        )
        missing_response = client.get(
            "/api/sessions/session-missing/workspace",
            headers={
                "X-Request-ID": "req-workspace-missing",
                "X-Correlation-ID": "corr-workspace-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["session"]["session_id"] == "session-1"
    assert payload["project"]["project_id"] == "project-1"
    assert payload["current_run_id"] == "run-active"
    assert payload["composer_state"]["bound_run_id"] == "run-active"
    assert payload["composer_state"]["is_input_enabled"] is False
    assert payload["composer_state"]["primary_action"] == "pause"
    assert any(entry["type"] == "tool_confirmation" for entry in payload["narrative_feed"])

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Session workspace was not found.",
        "request_id": "req-workspace-missing",
        "correlation_id": "corr-workspace-missing",
    }


def test_get_run_timeline_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/runs/run-active/timeline",
            headers={
                "X-Request-ID": "req-timeline",
                "X-Correlation-ID": "corr-timeline",
            },
        )
        missing_response = client.get(
            "/api/runs/run-missing/timeline",
            headers={
                "X-Request-ID": "req-timeline-missing",
                "X-Correlation-ID": "corr-timeline-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["run_id"] == "run-active"
    assert payload["session_id"] == "session-1"
    assert payload["attempt_index"] == 2
    assert payload["trigger_source"] == "retry"
    assert payload["status"] == "waiting_tool_confirmation"
    assert payload["current_stage_type"] == "code_generation"
    assert [entry["run_id"] for entry in payload["entries"]] == [
        "run-active",
        "run-active",
        "run-active",
    ]
    assert [entry["type"] for entry in payload["entries"]] == [
        "user_message",
        "stage_node",
        "tool_confirmation",
    ]
    assert any(entry["type"] == "tool_confirmation" for entry in payload["entries"])

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Run timeline was not found.",
        "request_id": "req-timeline-missing",
        "correlation_id": "corr-timeline-missing",
    }


def test_get_session_workspace_rejects_removed_session(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        row = session.get(SessionModel, "session-1")
        assert row is not None
        row.is_visible = False
        row.visibility_removed_at = NOW
        session.add(row)
        session.commit()

    with TestClient(app) as client:
        response = client.get(
            "/api/sessions/session-1/workspace",
            headers={
                "X-Request-ID": "req-workspace-removed",
                "X-Correlation-ID": "corr-workspace-removed",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Session workspace was not found.",
        "request_id": "req-workspace-removed",
        "correlation_id": "corr-workspace-removed",
    }


def test_get_session_workspace_rejects_removed_project(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        row = session.get(ProjectModel, "project-1")
        assert row is not None
        row.is_visible = False
        row.visibility_removed_at = NOW
        session.add(row)
        session.commit()

    with TestClient(app) as client:
        response = client.get(
            "/api/sessions/session-1/workspace",
            headers={
                "X-Request-ID": "req-project-removed",
                "X-Correlation-ID": "corr-project-removed",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Session workspace was not found.",
        "request_id": "req-project-removed",
        "correlation_id": "corr-project-removed",
    }


def test_query_workspace_route_is_documented_in_openapi(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]
    route = paths["/api/sessions/{sessionId}/workspace"]["get"]

    assert set(route["responses"]) == {"200", "404", "422", "500"}
    assert (
        route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionWorkspaceProjection"
    )
    for status_code in ("404", "422", "500"):
        assert (
            route["responses"][status_code]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )

    assert "SessionWorkspaceProjection" in schemas
    assert "ComposerStateProjection" in schemas
    assert "RunSummaryProjection" in schemas

    timeline_route = paths["/api/runs/{runId}/timeline"]["get"]
    assert set(timeline_route["responses"]) == {"200", "404", "422", "500"}
    assert (
        timeline_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RunTimelineProjection"
    )
    run_id_parameter = next(
        parameter
        for parameter in timeline_route["parameters"]
        if parameter["name"] == "runId"
    )
    assert run_id_parameter["in"] == "path"
    assert run_id_parameter["required"] is True
    assert run_id_parameter["schema"]["type"] == "string"
    for status_code in ("404", "422", "500"):
        assert (
            timeline_route["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    assert "RunTimelineProjection" in schemas
