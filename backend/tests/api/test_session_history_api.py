from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, SessionModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
)
from backend.app.domain.enums import RunStatus, RunTriggerSource, SessionStatus
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


NOW = datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC)


def build_session_history_app(tmp_path: Path):
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    app = create_app(settings=settings)
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.RUNTIME))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    return app


def _create_session(client: TestClient) -> dict:
    response = client.post("/api/projects/project-default/sessions")
    assert response.status_code == 201
    return response.json()


def _seed_active_run(app, *, session_id: str, run_id: str = "run-active") -> None:
    manager = app.state.database_manager
    runtime_limit_ref = f"runtime-limit-{run_id}"
    provider_policy_ref = f"policy-{run_id}"
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        runtime_session.add(
            RuntimeLimitSnapshotModel(
                snapshot_id=runtime_limit_ref,
                run_id=run_id,
                agent_limits={},
                context_limits={},
                source_config_version="config-v1",
                hard_limits_version="hard-limits-v1",
                schema_version="runtime-limit-v1",
                created_at=NOW,
            )
        )
        runtime_session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id=provider_policy_ref,
                run_id=run_id,
                provider_call_policy={},
                source_config_version="config-v1",
                schema_version="provider-policy-v1",
                created_at=NOW,
            )
        )
        runtime_session.commit()
        runtime_session.add(
            PipelineRunModel(
                run_id=run_id,
                session_id=session_id,
                project_id="project-default",
                attempt_index=1,
                status=RunStatus.RUNNING,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-1",
                graph_definition_ref="graph-definition-1",
                graph_thread_ref="graph-thread-1",
                workspace_ref="workspace-1",
                runtime_limit_snapshot_ref=runtime_limit_ref,
                provider_call_policy_snapshot_ref=provider_policy_ref,
                delivery_channel_snapshot_ref=None,
                current_stage_run_id=None,
                trace_id="trace-run-active",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        runtime_session.commit()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        session = control_session.get(SessionModel, session_id)
        assert session is not None
        session.status = SessionStatus.RUNNING
        session.current_run_id = run_id
        session.updated_at = NOW
        control_session.add(session)
        control_session.commit()


def _assert_error(
    response,
    *,
    status_code: int,
    error_code: str,
    message: str,
    request_id: str,
    correlation_id: str,
) -> None:
    assert response.status_code == status_code
    assert response.json() == {
        "error_code": error_code,
        "message": message,
        "request_id": request_id,
        "correlation_id": correlation_id,
    }


def test_delete_session_route_soft_hides_session_and_records_success_audit(
    tmp_path: Path,
) -> None:
    app = build_session_history_app(tmp_path)

    with TestClient(app) as client:
        created = _create_session(client)
        response = client.delete(
            f"/api/sessions/{created['session_id']}",
            headers={
                "X-Request-ID": "req-session-delete",
                "X-Correlation-ID": "corr-session-delete",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": created["session_id"],
        "project_id": "project-default",
        "visibility_removed": True,
        "blocked_by_active_run": False,
        "blocking_run_id": None,
        "error_code": None,
        "message": "Session removed from regular product history.",
        "deletes_local_project_folder": False,
        "deletes_target_repository": False,
        "deletes_remote_repository": False,
        "deletes_remote_branch": False,
        "deletes_commits": False,
        "deletes_code_review_requests": False,
    }

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        model = session.get(SessionModel, created["session_id"])
    assert model is not None
    assert model.is_visible is False
    assert model.visibility_removed_at is not None

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "session.delete")
            .one()
        )
    assert audit.target_id == created["session_id"]
    assert audit.result is AuditResult.SUCCEEDED
    assert audit.request_id == "req-session-delete"
    assert audit.correlation_id == "corr-session-delete"


def test_delete_session_route_returns_blocked_payload_for_active_run(
    tmp_path: Path,
) -> None:
    app = build_session_history_app(tmp_path)

    with TestClient(app) as client:
        created = _create_session(client)
        _seed_active_run(app, session_id=created["session_id"])
        response = client.delete(
            f"/api/sessions/{created['session_id']}",
            headers={
                "X-Request-ID": "req-session-delete-blocked",
                "X-Correlation-ID": "corr-session-delete-blocked",
            },
        )

    assert response.status_code == 200
    assert response.json()["visibility_removed"] is False
    assert response.json()["blocked_by_active_run"] is True
    assert response.json()["blocking_run_id"] == "run-active"
    assert response.json()["error_code"] == "session_active_run_blocks_delete"
    assert response.json()["message"] == "Session has an active run."

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        model = session.get(SessionModel, created["session_id"])
    assert model is not None
    assert model.is_visible is True
    assert model.status is SessionStatus.RUNNING
    assert model.current_run_id == "run-active"

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "session.delete")
            .one()
        )
    assert audit.target_id == created["session_id"]
    assert audit.result is AuditResult.BLOCKED
    assert audit.request_id == "req-session-delete-blocked"
    assert audit.correlation_id == "corr-session-delete-blocked"


def test_delete_session_route_returns_conflict_for_repeated_and_not_found_for_missing(
    tmp_path: Path,
) -> None:
    app = build_session_history_app(tmp_path)

    with TestClient(app) as client:
        created = _create_session(client)
        first = client.delete(f"/api/sessions/{created['session_id']}")
        repeated = client.delete(
            f"/api/sessions/{created['session_id']}",
            headers={
                "X-Request-ID": "req-session-delete-repeat",
                "X-Correlation-ID": "corr-session-delete-repeat",
            },
        )
        missing = client.delete(
            "/api/sessions/session-missing",
            headers={
                "X-Request-ID": "req-session-delete-missing",
                "X-Correlation-ID": "corr-session-delete-missing",
            },
        )

    assert first.status_code == 200
    _assert_error(
        repeated,
        status_code=409,
        error_code="validation_error",
        message="Session was already removed from product history.",
        request_id="req-session-delete-repeat",
        correlation_id="corr-session-delete-repeat",
    )
    _assert_error(
        missing,
        status_code=404,
        error_code="not_found",
        message="Session was not found.",
        request_id="req-session-delete-missing",
        correlation_id="corr-session-delete-missing",
    )


def test_session_delete_route_is_documented_in_openapi(tmp_path: Path) -> None:
    app = build_session_history_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    route = document["paths"]["/api/sessions/{sessionId}"]["delete"]
    schemas = document["components"]["schemas"]

    assert "requestBody" not in route
    assert set(route["responses"]) == {"200", "404", "409", "422", "500"}
    assert (
        route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionDeleteResult"
    )
    for status_code in ("404", "409", "422", "500"):
        assert (
            route["responses"][status_code]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )
    assert "SessionDeleteResult" in schemas
