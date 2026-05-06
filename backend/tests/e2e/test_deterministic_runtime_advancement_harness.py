from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.testing import (
    InMemoryCheckpointPort,
    InMemoryRuntimeCommandPort,
)
from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProviderModel
from backend.app.db.models.event import EventBase
from backend.app.db.models.graph import GraphBase
from backend.app.db.models.log import LogBase
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    PipelineRunModel,
    RuntimeBase,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import ApprovalStatus, RunStatus, StageStatus, StageType
from backend.app.main import create_app
from backend.app.testing import create_e2e_test_app


def _settings(tmp_path: Path) -> EnvironmentSettings:
    project_root = tmp_path / "project"
    project_root.mkdir()
    return EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=project_root,
    )


def _create_schema(app: Any) -> None:
    ControlBase.metadata.create_all(
        app.state.database_manager.engine(DatabaseRole.CONTROL)
    )
    RuntimeBase.metadata.create_all(
        app.state.database_manager.engine(DatabaseRole.RUNTIME)
    )
    GraphBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.GRAPH))
    EventBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.EVENT))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))


def _configure_required_providers(app: Any) -> None:
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        providers = (
            session.query(ProviderModel)
            .filter(
                ProviderModel.provider_id.in_(
                    ["provider-deepseek", "provider-volcengine"]
                )
            )
            .all()
        )
        assert {provider.provider_id for provider in providers} == {
            "provider-deepseek",
            "provider-volcengine",
        }
        for provider in providers:
            provider.is_configured = True
            provider.is_enabled = True
            session.add(provider)
        session.commit()


def _start_run(client: TestClient) -> tuple[str, str]:
    created = client.post("/api/projects/project-default/sessions")
    assert created.status_code == 201
    _configure_required_providers(client.app)
    session_id = created.json()["session_id"]
    response = client.post(
        f"/api/sessions/{session_id}/messages",
        json={
            "message_type": "new_requirement",
            "content": "Build the live deterministic browser E2E path.",
        },
        headers={
            "X-Request-ID": "req-a43a-new-requirement",
            "X-Correlation-ID": "corr-a43a",
        },
    )
    assert response.status_code == 200
    run_id = response.json()["session"]["current_run_id"]
    assert run_id
    return session_id, run_id


def _advance(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.post(f"/__test__/runtime/runs/{run_id}/advance", json={})
    assert response.status_code == 200, response.text
    return response.json()


def _workspace(client: TestClient, session_id: str) -> dict[str, Any]:
    response = client.get(f"/api/sessions/{session_id}/workspace")
    assert response.status_code == 200
    return response.json()


def _timeline(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.get(f"/api/runs/{run_id}/timeline")
    assert response.status_code == 200
    return response.json()


def _event_stream_text(client: TestClient, session_id: str) -> str:
    response = client.get(f"/api/sessions/{session_id}/events/stream?limit=50")
    assert response.status_code == 200
    return response.text


def _assert_error_envelope(
    body: dict[str, Any],
    *,
    error_code: str,
    message: str,
) -> None:
    assert body["error_code"] == error_code
    assert body["message"] == message
    assert body["request_id"]
    assert body["correlation_id"]


def test_default_app_does_not_register_deterministic_advancement_harness(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    _create_schema(app)
    assert "/__test__/runtime/runs/{runId}/advance" not in {
        route.path for route in app.routes
    }
    with TestClient(app) as client:
        response = client.post("/__test__/runtime/runs/run-missing/advance", json={})
        assert response.status_code == 404

        malformed = client.post(
            "/__test__/runtime/runs/run-missing/advance",
            json={"target": "unsupported"},
        )
        assert malformed.status_code == 404

        openapi = client.get("/api/openapi.json")
        assert openapi.status_code == 200
        assert "/__test__/runtime/runs/{runId}/advance" not in openapi.json()["paths"]


def test_e2e_harness_falls_back_to_h41_ports_when_h45_ports_are_none(
    tmp_path: Path,
) -> None:
    app = create_e2e_test_app(_settings(tmp_path))
    app.state.h45_runtime_port = None
    app.state.h45_checkpoint_port = None
    app.state.h41_runtime_port = InMemoryRuntimeCommandPort()
    app.state.h41_checkpoint_port = InMemoryCheckpointPort()
    _create_schema(app)
    with TestClient(app) as client:
        _session_id, run_id = _start_run(client)

        requirement = _advance(client, run_id)
        assert requirement["result_type"] == "stage_result"
        assert requirement["stage_type"] == "requirement_analysis"

        approval = _advance(client, run_id)
        assert approval["result_type"] == "interrupt"
        assert approval["interrupt_type"] == "approval"


def test_e2e_harness_advances_real_run_to_approval_and_tool_confirmation(
    tmp_path: Path,
) -> None:
    app = create_e2e_test_app(_settings(tmp_path))
    _create_schema(app)
    with TestClient(app) as client:
        session_id, run_id = _start_run(client)

        requirement = _advance(client, run_id)
        assert requirement["result_type"] == "stage_result"
        assert requirement["stage_type"] == "requirement_analysis"

        approval = _advance(client, run_id)
        assert approval["result_type"] == "interrupt"
        assert approval["stage_type"] == "solution_design"
        assert approval["run_status"] == "waiting_approval"
        assert approval["interrupt_type"] == "approval"
        assert approval["approval_id"]
        assert approval["tool_confirmation_id"] is None

        workspace = _workspace(client, session_id)
        timeline = _timeline(client, run_id)
        assert workspace["session"]["status"] == "waiting_approval"
        assert any(
            entry["type"] == "approval_request"
            and entry["approval_id"] == approval["approval_id"]
            for entry in workspace["narrative_feed"]
        )
        assert any(
            entry["type"] == "approval_request"
            and entry["approval_id"] == approval["approval_id"]
            for entry in timeline["entries"]
        )
        assert "approval_requested" in _event_stream_text(client, session_id)

        approval_response = client.post(
            f"/api/approvals/{approval['approval_id']}/approve",
            json={},
        )
        assert approval_response.status_code == 200
        assert approval_response.json()["approval_result"]["decision"] == "approved"
        assert "approval_result" in _event_stream_text(client, session_id)

        solution = _advance(client, run_id)
        assert solution["result_type"] == "stage_result"
        assert solution["stage_type"] == "solution_design"

        tool = _advance(client, run_id)
        assert tool["result_type"] == "interrupt"
        assert tool["stage_type"] == "code_generation"
        assert tool["run_status"] == "waiting_tool_confirmation"
        assert tool["interrupt_type"] == "tool_confirmation"
        assert tool["approval_id"] is None
        assert tool["tool_confirmation_id"]

        workspace = _workspace(client, session_id)
        timeline = _timeline(client, run_id)
        assert workspace["session"]["status"] == "waiting_tool_confirmation"
        workspace_tool = next(
            entry
            for entry in workspace["narrative_feed"]
            if entry["type"] == "tool_confirmation"
            and entry["tool_confirmation_id"] == tool["tool_confirmation_id"]
        )
        assert workspace_tool["status"] == "pending"
        assert "approval_id" not in workspace_tool
        assert any(
            entry["type"] == "tool_confirmation"
            and entry["tool_confirmation_id"] == tool["tool_confirmation_id"]
            for entry in timeline["entries"]
        )
        assert "tool_confirmation_requested" in _event_stream_text(client, session_id)

        with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
            run = session.get(PipelineRunModel, run_id)
            assert run is not None
            assert run.status is RunStatus.WAITING_TOOL_CONFIRMATION
            stage = session.get(StageRunModel, run.current_stage_run_id)
            assert stage is not None
            assert stage.stage_type is StageType.CODE_GENERATION
            assert stage.status is StageStatus.WAITING_TOOL_CONFIRMATION
            assert (
                session.query(ApprovalRequestModel)
                .filter(
                    ApprovalRequestModel.run_id == run_id,
                    ApprovalRequestModel.status == ApprovalStatus.APPROVED,
                )
                .count()
                == 1
            )
            assert (
                session.query(ToolConfirmationRequestModel)
                .filter(
                    ToolConfirmationRequestModel.run_id == run_id,
                )
                .count()
                == 1
            )


def test_e2e_harness_returns_stable_errors_and_stays_out_of_openapi(
    tmp_path: Path,
) -> None:
    app = create_e2e_test_app(_settings(tmp_path))
    _create_schema(app)
    assert "/__test__/runtime/runs/{runId}/advance" in {
        route.path for route in app.routes
    }
    with TestClient(app) as client:
        openapi = client.get("/api/openapi.json")
        assert openapi.status_code == 200
        assert "/__test__/runtime/runs/{runId}/advance" not in openapi.json()["paths"]

        missing = client.post("/__test__/runtime/runs/run-missing/advance", json={})
        assert missing.status_code == 404
        _assert_error_envelope(
            missing.json(),
            error_code="not_found",
            message="PipelineRun was not found.",
        )

        _session_id, run_id = _start_run(client)
        _advance(client, run_id)
        approval = _advance(client, run_id)
        assert approval["run_status"] == "waiting_approval"

        blocked = client.post(f"/__test__/runtime/runs/{run_id}/advance", json={})
        assert blocked.status_code == 409
        _assert_error_envelope(
            blocked.json(),
            error_code="validation_error",
            message="PipelineRun must be running before deterministic advancement.",
        )
