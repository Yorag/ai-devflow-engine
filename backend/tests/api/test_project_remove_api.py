from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.routes import projects as project_routes
from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    ProjectModel,
    SessionModel,
    StartupPublicationModel,
)
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
)
from backend.app.domain.enums import RunStatus, RunTriggerSource, SessionStatus
from backend.app.domain.publication_boundary import PUBLICATION_STATE_PENDING
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult
from backend.app.schemas.project import ProjectRemoveResult
from backend.app.services.delivery_channels import DEFAULT_PROJECT_ID
from backend.app.services.projects import (
    DEFAULT_PROJECT_REMOVE_BLOCKED_MESSAGE,
    PROJECT_ALREADY_REMOVED_MESSAGE,
    PROJECT_REMOVE_BLOCKED_ERROR_CODE,
    PROJECT_REMOVE_BLOCKED_MESSAGE,
    PROJECT_REMOVE_SUCCESS_MESSAGE,
    PROJECT_RUNTIME_STATE_UNAVAILABLE_MESSAGE,
)


def build_project_remove_api_app(tmp_path: Path, default_project_root: Path):
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_project_root,
    )
    app = create_app(settings=settings)
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.RUNTIME))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    return app


def _create_project(client: TestClient, root_path: Path) -> dict[str, Any]:
    response = client.post("/api/projects", json={"root_path": str(root_path)})
    assert response.status_code == 201
    return response.json()


def _create_session(client: TestClient, project_id: str) -> dict[str, Any]:
    response = client.post(f"/api/projects/{project_id}/sessions")
    assert response.status_code == 201
    return response.json()


def _seed_pending_startup_publication(
    app,
    *,
    project_id: str,
    session_id: str,
    run_id: str,
) -> None:
    manager = app.state.database_manager
    with manager.session(DatabaseRole.CONTROL) as session:
        row = session.get(SessionModel, session_id)
        assert row is not None
        timestamp = row.created_at
        session.add(
            StartupPublicationModel(
                publication_id=f"publication-{run_id}",
                session_id=session_id,
                run_id=run_id,
                stage_run_id=f"stage-{run_id}",
                publication_state=PUBLICATION_STATE_PENDING,
                pending_session_id=session_id,
                published_at=None,
                aborted_at=None,
                abort_reason=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.commit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RuntimeLimitSnapshotModel(
                snapshot_id=f"runtime-limit-{run_id}",
                run_id=run_id,
                agent_limits={},
                context_limits={},
                source_config_version="config-v1",
                hard_limits_version="hard-limits-v1",
                schema_version="runtime-limit-v1",
                created_at=timestamp,
            )
        )
        session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id=f"provider-policy-{run_id}",
                run_id=run_id,
                provider_call_policy={},
                source_config_version="config-v1",
                schema_version="provider-policy-v1",
                created_at=timestamp,
            )
        )
        session.commit()
        session.add(
            PipelineRunModel(
                run_id=run_id,
                session_id=session_id,
                project_id=project_id,
                attempt_index=1,
                status=RunStatus.COMPLETED,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-1",
                graph_definition_ref="graph-definition-1",
                graph_thread_ref="graph-thread-1",
                workspace_ref="workspace-1",
                runtime_limit_snapshot_ref=f"runtime-limit-{run_id}",
                provider_call_policy_snapshot_ref=f"provider-policy-{run_id}",
                delivery_channel_snapshot_ref=None,
                current_stage_run_id=None,
                trace_id=f"trace-{run_id}",
                started_at=timestamp,
                ended_at=timestamp,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.commit()


def test_delete_project_soft_removes_project_history_and_audits(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    app = build_project_remove_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        project_id = _create_project(client, loaded_root)["project_id"]
        response = client.delete(
            f"/api/projects/{project_id}",
            headers={
                "X-Request-ID": "req-project-remove",
                "X-Correlation-ID": "corr-project-remove",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-project-remove"
    assert response.headers["x-correlation-id"] == "corr-project-remove"
    assert response.json() == {
        "project_id": project_id,
        "visibility_removed": True,
        "blocked_by_active_run": False,
        "blocking_run_id": None,
        "error_code": None,
        "message": PROJECT_REMOVE_SUCCESS_MESSAGE,
        "deletes_local_project_folder": False,
        "deletes_target_repository": False,
        "deletes_remote_repository": False,
        "deletes_remote_branch": False,
        "deletes_commits": False,
        "deletes_code_review_requests": False,
    }

    manager = app.state.database_manager
    with manager.session(DatabaseRole.CONTROL) as session:
        project = session.get(ProjectModel, project_id)
    with manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "project.remove")
            .one()
        )

    assert project is not None
    assert project.is_visible is False
    assert project.visibility_removed_at is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert audit.request_id == "req-project-remove"
    assert audit.correlation_id == "corr-project-remove"
    assert str(loaded_root.resolve()) not in audit.target_id


def test_delete_project_real_active_run_block_returns_200_structured_payload(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    app = build_project_remove_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        project = _create_project(client, loaded_root)
        session_row = _create_session(client, project["project_id"])

        with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
            model = session.get(SessionModel, session_row["session_id"])
            assert model is not None
            model.status = SessionStatus.RUNNING
            model.current_run_id = "run-active"
            session.add(model)
            session.commit()

        with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
            session.add(
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-active",
                    run_id="run-active",
                    agent_limits={},
                    context_limits={},
                    source_config_version="config-v1",
                    hard_limits_version="hard-limits-v1",
                    schema_version="runtime-limit-v1",
                    created_at=model.created_at,
                )
            )
            session.add(
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-policy-active",
                    run_id="run-active",
                    provider_call_policy={},
                    source_config_version="config-v1",
                    schema_version="provider-policy-v1",
                    created_at=model.created_at,
                )
            )
            session.commit()
            session.add(
                PipelineRunModel(
                    run_id="run-active",
                    session_id=session_row["session_id"],
                    project_id=project["project_id"],
                    attempt_index=1,
                    status=RunStatus.RUNNING,
                    trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                    template_snapshot_ref="template-snapshot-1",
                    graph_definition_ref="graph-definition-1",
                    graph_thread_ref="graph-thread-1",
                    workspace_ref="workspace-1",
                    runtime_limit_snapshot_ref="runtime-limit-active",
                    provider_call_policy_snapshot_ref="provider-policy-active",
                    delivery_channel_snapshot_ref=None,
                    current_stage_run_id=None,
                    trace_id="trace-run-active",
                    started_at=model.created_at,
                    ended_at=None,
                    created_at=model.created_at,
                    updated_at=model.created_at,
                )
            )
            session.commit()

        response = client.delete(
            f"/api/projects/{project['project_id']}",
            headers={
                "X-Request-ID": "req-project-blocked",
                "X-Correlation-ID": "corr-project-blocked",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "project_id": project["project_id"],
        "visibility_removed": False,
        "blocked_by_active_run": True,
        "blocking_run_id": "run-active",
        "error_code": PROJECT_REMOVE_BLOCKED_ERROR_CODE,
        "message": PROJECT_REMOVE_BLOCKED_MESSAGE,
        "deletes_local_project_folder": False,
        "deletes_target_repository": False,
        "deletes_remote_repository": False,
        "deletes_remote_branch": False,
        "deletes_commits": False,
        "deletes_code_review_requests": False,
    }
    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "project.remove")
            .order_by(AuditLogEntryModel.created_at.desc())
            .first()
        )
    assert audit is not None
    assert audit.result is AuditResult.BLOCKED
    assert audit.request_id == "req-project-blocked"
    assert audit.correlation_id == "corr-project-blocked"


def test_delete_project_blocks_real_pending_startup_publication(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    app = build_project_remove_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        project = _create_project(client, loaded_root)
        session_row = _create_session(client, project["project_id"])
        _seed_pending_startup_publication(
            app,
            project_id=project["project_id"],
            session_id=session_row["session_id"],
            run_id="run-startup-pending",
        )

        response = client.delete(
            f"/api/projects/{project['project_id']}",
            headers={
                "X-Request-ID": "req-project-startup-blocked",
                "X-Correlation-ID": "corr-project-startup-blocked",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "project_id": project["project_id"],
        "visibility_removed": False,
        "blocked_by_active_run": True,
        "blocking_run_id": "run-startup-pending",
        "error_code": PROJECT_REMOVE_BLOCKED_ERROR_CODE,
        "message": PROJECT_REMOVE_BLOCKED_MESSAGE,
        "deletes_local_project_folder": False,
        "deletes_target_repository": False,
        "deletes_remote_repository": False,
        "deletes_remote_branch": False,
        "deletes_commits": False,
        "deletes_code_review_requests": False,
    }
    manager = app.state.database_manager
    with manager.session(DatabaseRole.CONTROL) as session:
        saved_project = session.get(ProjectModel, project["project_id"])
        saved_session = session.get(SessionModel, session_row["session_id"])
    with manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "project.remove")
            .order_by(AuditLogEntryModel.created_at.desc())
            .first()
        )

    assert saved_project is not None
    assert saved_project.is_visible is True
    assert saved_project.visibility_removed_at is None
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert saved_session.visibility_removed_at is None
    assert saved_session.current_run_id is None
    assert audit is not None
    assert audit.result is AuditResult.BLOCKED
    assert audit.request_id == "req-project-startup-blocked"
    assert audit.correlation_id == "corr-project-startup-blocked"
    assert "blocking_run_id" in (audit.metadata_excerpt or "")
    assert "run-startup-pending" in (audit.metadata_excerpt or "")


def test_delete_project_returns_500_when_runtime_barrier_cannot_be_acquired(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    app = build_project_remove_api_app(tmp_path, default_root)
    manager = app.state.database_manager

    with TestClient(app) as client:
        project = _create_project(client, loaded_root)
        session_row = _create_session(client, project["project_id"])

        runtime_engine = create_engine(
            f"sqlite:///{manager.database_path(DatabaseRole.RUNTIME).as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 0},
        )
        runtime_session_factory = sessionmaker(
            bind=runtime_engine,
            expire_on_commit=False,
        )
        lock_connection = runtime_engine.connect()
        lock_connection.exec_driver_sql("BEGIN IMMEDIATE")
        original_get_runtime_session = project_routes.get_runtime_session

        def locked_runtime_session_override():
            runtime_session = runtime_session_factory()
            try:
                yield runtime_session
            finally:
                runtime_session.close()

        app.dependency_overrides[original_get_runtime_session] = (
            locked_runtime_session_override
        )
        try:
            response = client.delete(
                f"/api/projects/{project['project_id']}",
                headers={
                    "X-Request-ID": "req-project-runtime-locked",
                    "X-Correlation-ID": "corr-project-runtime-locked",
                },
            )
        finally:
            app.dependency_overrides.pop(original_get_runtime_session, None)
            lock_connection.rollback()
            lock_connection.close()
            runtime_engine.dispose()

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "internal_error",
        "message": PROJECT_RUNTIME_STATE_UNAVAILABLE_MESSAGE,
        "request_id": "req-project-runtime-locked",
        "correlation_id": "corr-project-runtime-locked",
    }
    with manager.session(DatabaseRole.CONTROL) as session:
        saved_project = session.get(ProjectModel, project["project_id"])
        saved_session = session.get(SessionModel, session_row["session_id"])
    with manager.session(DatabaseRole.LOG) as session:
        remove_audits = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "project.remove")
            .all()
        )

    assert saved_project is not None
    assert saved_project.is_visible is True
    assert saved_project.visibility_removed_at is None
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert saved_session.visibility_removed_at is None
    assert remove_audits == []


def test_delete_project_real_conflict_errors_use_error_response(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    app = build_project_remove_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        project_id = _create_project(client, loaded_root)["project_id"]
        first = client.delete(f"/api/projects/{project_id}")
        repeated = client.delete(
            f"/api/projects/{project_id}",
            headers={
                "X-Request-ID": "req-project-repeat",
                "X-Correlation-ID": "corr-project-repeat",
            },
        )
        default_blocked = client.delete(
            f"/api/projects/{DEFAULT_PROJECT_ID}",
            headers={
                "X-Request-ID": "req-project-default",
                "X-Correlation-ID": "corr-project-default",
            },
        )
        missing = client.delete(
            "/api/projects/project-missing",
            headers={
                "X-Request-ID": "req-project-missing",
                "X-Correlation-ID": "corr-project-missing",
            },
        )

    assert first.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json() == {
        "error_code": "validation_error",
        "message": PROJECT_ALREADY_REMOVED_MESSAGE,
        "request_id": "req-project-repeat",
        "correlation_id": "corr-project-repeat",
    }
    assert default_blocked.status_code == 409
    assert default_blocked.json() == {
        "error_code": "validation_error",
        "message": DEFAULT_PROJECT_REMOVE_BLOCKED_MESSAGE,
        "request_id": "req-project-default",
        "correlation_id": "corr-project-default",
    }
    assert missing.status_code == 404
    assert missing.json() == {
        "error_code": "not_found",
        "message": "Project was not found.",
        "request_id": "req-project-missing",
        "correlation_id": "corr-project-missing",
    }


def test_delete_project_dependency_injects_runtime_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    default_root = tmp_path / "platform"
    default_root.mkdir()
    app = build_project_remove_api_app(tmp_path, default_root)
    captured: dict[str, Any] = {}

    class SpyProjectService:
        def __init__(
            self,
            session,
            *,
            settings,
            audit_service,
            runtime_session=None,
        ) -> None:
            captured["control_session"] = session
            captured["runtime_session"] = runtime_session
            captured["settings"] = settings
            captured["audit_service"] = audit_service

        def remove_project(self, *, project_id: str, trace_context: Any):
            return ProjectRemoveResult(
                project_id=project_id,
                visibility_removed=True,
                blocked_by_active_run=False,
                message=PROJECT_REMOVE_SUCCESS_MESSAGE,
            )

    monkeypatch.setattr(project_routes, "ProjectService", SpyProjectService)

    with TestClient(app) as client:
        response = client.delete("/api/projects/project-loaded")

    assert response.status_code == 200
    assert captured["control_session"] is not None
    assert captured["runtime_session"] is not None
    assert captured["runtime_session"] is not captured["control_session"]
    assert captured["settings"] is app.state.environment_settings
    assert captured["audit_service"] is not None


def test_delete_project_route_is_documented_without_request_body(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "platform"
    default_root.mkdir()
    app = build_project_remove_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    delete_project = document["paths"]["/api/projects/{projectId}"]["delete"]
    schemas = document["components"]["schemas"]

    assert "requestBody" not in delete_project
    assert set(delete_project["responses"]) == {"200", "404", "409", "422", "500"}
    assert (
        delete_project["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ProjectRemoveResult"
    )
    for status_code in ["404", "409", "422", "500"]:
        assert (
            delete_project["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    assert "ProjectRemoveResult" in schemas
    assert set(schemas["ProjectRemoveResult"]["required"]) == {
        "project_id",
        "visibility_removed",
        "blocked_by_active_run",
        "message",
    }
    for field_name in [
        "deletes_local_project_folder",
        "deletes_target_repository",
        "deletes_remote_repository",
        "deletes_remote_branch",
        "deletes_commits",
        "deletes_code_review_requests",
    ]:
        field_schema = schemas["ProjectRemoveResult"]["properties"][field_name]
        assert field_schema["type"] == "boolean"
        assert field_schema["const"] is False
