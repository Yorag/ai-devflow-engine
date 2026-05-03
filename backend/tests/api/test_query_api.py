from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProjectModel, SessionModel
from backend.app.db.models.event import EventBase
from backend.app.db.models.log import LogBase
from backend.app.db.models.runtime import (
    ClarificationRecordModel,
    RunControlRecordModel,
    RuntimeBase,
    StageArtifactModel,
)
from backend.app.schemas.common import RunControlRecordType, StageType
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


def _seed_control_item_projection(app) -> None:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                ClarificationRecordModel(
                    clarification_id="clarification-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    question="Should the change affect backend only?",
                    answer=None,
                    payload_ref="clarification-payload-1",
                    graph_interrupt_ref="interrupt-clarification-1",
                    requested_at=NOW.replace(minute=8),
                    answered_at=None,
                    created_at=NOW.replace(minute=8),
                    updated_at=NOW.replace(minute=8),
                ),
                RunControlRecordModel(
                    control_record_id="control-clarification-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    control_type=RunControlRecordType.CLARIFICATION_WAIT,
                    source_stage_type=StageType.CODE_GENERATION,
                    target_stage_type=StageType.CODE_GENERATION,
                    payload_ref="clarification-1",
                    graph_interrupt_ref="interrupt-clarification-1",
                    occurred_at=NOW.replace(minute=8),
                    created_at=NOW.replace(minute=8),
                ),
                StageArtifactModel(
                    artifact_id="artifact-control-clarification-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    artifact_type="control_item_trace",
                    payload_ref="payload-control-clarification-1",
                    process={
                        "control_record_id": "control-clarification-1",
                        "trigger_reason": "Need the user to clarify file scope.",
                        "context_refs": ["requirement-clarification-1"],
                        "control_process_trace_ref": "control-trace-clarification-1",
                        "history_attempt_refs": ["run-active:attempt-2"],
                        "output_snapshot": {"result_status": "waiting_clarification"},
                        "log_refs": ["log-control-clarification-1"],
                    },
                    metrics={"retry_index": 0, "source_attempt_index": 1},
                    created_at=NOW.replace(minute=8, second=5),
                ),
            ]
        )
        session.commit()


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

def test_session_event_stream_returns_event_store_frames(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/sessions/session-1/events/stream",
            params={"after": 0, "limit": 1},
            headers={
                "X-Request-ID": "req-event-stream",
                "X-Correlation-ID": "corr-event-stream",
            },
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = []
            for line in response.iter_lines():
                lines.append(line)
                if line == "":
                    break

    assert "event: session_message_appended" in lines
    data_line = next(line for line in lines if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["session_id"] == "session-1"
    assert payload["run_id"] == "run-active"
    assert payload["event_type"] == "session_message_appended"
    assert payload["payload"]["message_item"]["content"] == "Add workspace projection."


def test_session_event_stream_resumes_after_last_event_id(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/sessions/session-1/events/stream",
            headers={
                "Last-Event-ID": "1",
                "X-Request-ID": "req-event-stream-replay",
                "X-Correlation-ID": "corr-event-stream-replay",
            },
            params={"limit": 1},
        ) as response:
            assert response.status_code == 200
            lines = []
            for line in response.iter_lines():
                lines.append(line)
                if line == "":
                    break

    assert "id: 1" not in lines
    assert "id: 2" in lines
    data_line = next(line for line in lines if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["event_type"] == "stage_updated"


def test_get_stage_inspector_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/stages/stage-active/inspector",
            headers={
                "X-Request-ID": "req-inspector",
                "X-Correlation-ID": "corr-inspector",
            },
        )
        missing_response = client.get(
            "/api/stages/stage-missing/inspector",
            headers={
                "X-Request-ID": "req-inspector-missing",
                "X-Correlation-ID": "corr-inspector-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["stage_run_id"] == "stage-active"
    assert payload["run_id"] == "run-active"
    assert payload["stage_type"] == "code_generation"
    assert payload["status"] == "waiting_tool_confirmation"
    assert {
        "identity",
        "input",
        "process",
        "output",
        "artifacts",
        "metrics",
    }.issubset(payload)
    assert "process-tool-confirmation-1" in payload["tool_confirmation_trace_refs"]

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Stage inspector was not found.",
        "request_id": "req-inspector-missing",
        "correlation_id": "corr-inspector-missing",
    }


def test_get_control_item_detail_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _seed_control_item_projection(app)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/control-records/control-clarification-1",
            headers={
                "X-Request-ID": "req-control-clarification",
                "X-Correlation-ID": "corr-control-clarification",
            },
        )
        missing_response = client.get(
            "/api/control-records/control-missing",
            headers={
                "X-Request-ID": "req-control-missing",
                "X-Correlation-ID": "corr-control-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["control_record_id"] == "control-clarification-1"
    assert payload["run_id"] == "run-active"
    assert payload["control_type"] == "clarification_wait"
    assert payload["source_stage_type"] == "code_generation"
    assert (
        payload["input"]["records"]["clarification_question"]
        == "Should the change affect backend only?"
    )
    assert payload["output"]["records"]["result_status"] == "waiting_clarification"
    assert payload["artifacts"]["records"]["clarification_id"] == "clarification-1"
    assert payload["artifacts"]["log_refs"] == ["log-control-clarification-1"]

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Control item inspector was not found.",
        "request_id": "req-control-missing",
        "correlation_id": "corr-control-missing",
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

    stream_route = paths["/api/sessions/{sessionId}/events/stream"]["get"]
    assert set(stream_route["responses"]) == {"200", "422"}
    assert (
        stream_route["responses"]["200"]["content"]["text/event-stream"]["schema"][
            "type"
        ]
        == "string"
    )
    session_id_parameter = next(
        parameter
        for parameter in stream_route["parameters"]
        if parameter["name"] == "sessionId"
    )
    assert session_id_parameter["in"] == "path"
    assert session_id_parameter["required"] is True
    assert session_id_parameter["schema"]["type"] == "string"
    assert (
        stream_route["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )


    inspector_route = paths["/api/stages/{stageRunId}/inspector"]["get"]
    assert set(inspector_route["responses"]) == {"200", "404", "422", "500"}
    assert (
        inspector_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/StageInspectorProjection"
    )
    stage_run_id_parameter = next(
        parameter
        for parameter in inspector_route["parameters"]
        if parameter["name"] == "stageRunId"
    )
    assert stage_run_id_parameter["in"] == "path"
    assert stage_run_id_parameter["required"] is True
    assert stage_run_id_parameter["schema"]["type"] == "string"
    for status_code in ("404", "422", "500"):
        assert (
            inspector_route["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    control_record_route = paths["/api/control-records/{controlRecordId}"]["get"]
    assert set(control_record_route["responses"]) == {"200", "404", "422", "500"}
    assert (
        control_record_route["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/ControlItemInspectorProjection"
    )
    control_record_id_parameter = next(
        parameter
        for parameter in control_record_route["parameters"]
        if parameter["name"] == "controlRecordId"
    )
    assert control_record_id_parameter["in"] == "path"
    assert control_record_id_parameter["required"] is True
    assert control_record_id_parameter["schema"]["type"] == "string"
    for status_code in ("404", "422", "500"):
        assert (
            control_record_route["responses"][status_code]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    assert "StageInspectorProjection" in schemas
    assert "ControlItemInspectorProjection" in schemas
    assert "ErrorResponse" in schemas
