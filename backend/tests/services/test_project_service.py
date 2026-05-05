from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    DeliveryChannelModel,
    PipelineTemplateModel,
    ProjectModel,
    SessionModel,
    StartupPublicationModel,
)
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    TemplateSource,
)
from backend.app.domain.publication_boundary import PUBLICATION_STATE_PENDING
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditResult


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return object()


class FailingAuditService:
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")

    def record_rejected_command(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-project-test",
        trace_id="trace-project-test",
        correlation_id="correlation-project-test",
        span_id="span-project-test",
        parent_span_id=None,
        created_at=NOW,
    )


def build_control_manager(tmp_path: Path, default_project_root: Path) -> DatabaseManager:
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_project_root,
    )
    manager = DatabaseManager.from_environment_settings(settings)
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    return manager


def seed_template_if_missing(manager: DatabaseManager) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        if session.get(PipelineTemplateModel, "template-feature") is None:
            session.add(
                PipelineTemplateModel(
                    template_id="template-feature",
                    name="Feature",
                    description=None,
                    template_source=TemplateSource.SYSTEM_TEMPLATE,
                    base_template_id=None,
                    fixed_stage_sequence=[],
                    stage_role_bindings=[],
                    approval_checkpoints=[],
                    auto_regression_enabled=False,
                    max_auto_regression_retries=0,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.commit()


def seed_pending_startup(
    manager: DatabaseManager,
    *,
    project_id: str,
    session_id: str,
    run_id: str,
) -> None:
    seed_template_if_missing(manager)
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            SessionModel(
                session_id=session_id,
                project_id=project_id,
                display_name=session_id,
                status=SessionStatus.DRAFT,
                selected_template_id="template-feature",
                current_run_id=None,
                latest_stage_type=None,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
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
                created_at=NOW,
                updated_at=NOW,
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
                created_at=NOW,
            )
        )
        session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id=f"policy-{run_id}",
                run_id=run_id,
                provider_call_policy={},
                source_config_version="config-v1",
                schema_version="provider-policy-v1",
                created_at=NOW,
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
                provider_call_policy_snapshot_ref=f"policy-{run_id}",
                delivery_channel_snapshot_ref=None,
                current_stage_run_id=None,
                trace_id=f"trace-{run_id}",
                started_at=NOW,
                ended_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def test_ensure_default_project_creates_demo_delivery_channel_and_audit(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    manager = build_control_manager(tmp_path, default_root)
    audit = RecordingAuditService()
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )

    with manager.session(DatabaseRole.CONTROL) as session:
        project = ProjectService(
            session,
            settings=settings,
            audit_service=audit,
            now=lambda: NOW,
        ).ensure_default_project(trace_context=build_trace())
        saved_channel = session.get(
            DeliveryChannelModel,
            project.default_delivery_channel_id,
        )

    assert project.project_id == "project-default"
    assert project.name == "ai-devflow-engine"
    assert project.root_path == str(default_root.resolve())
    assert project.is_default is True
    assert project.is_visible is True
    assert saved_channel is not None
    assert saved_channel.project_id == "project-default"
    assert saved_channel.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert saved_channel.credential_status is CredentialStatus.READY
    assert saved_channel.readiness_status is DeliveryReadinessStatus.READY
    assert saved_channel.readiness_message is None
    assert audit.records[0]["action"] == "project.ensure_default"
    assert audit.records[0]["result"] is AuditResult.SUCCEEDED
    assert str(default_root.resolve()) not in audit.records[0]["target_id"]
    assert audit.records[0]["metadata"]["root_path_hash"].startswith("sha256:")


def test_load_project_is_idempotent_and_list_projects_filters_removed(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    hidden_root = tmp_path / "hidden-app"
    default_root.mkdir()
    loaded_root.mkdir()
    hidden_root.mkdir()
    manager = build_control_manager(tmp_path, default_root)
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    trace = build_trace()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProjectService(
            session,
            settings=settings,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        )
        loaded = service.load_project(root_path=loaded_root, trace_context=trace)
        duplicate = service.load_project(root_path=loaded_root, trace_context=trace)
        hidden = service.load_project(root_path=hidden_root, trace_context=trace)
        hidden.is_visible = False
        session.commit()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProjectService(
            session,
            settings=settings,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        )
        projects = service.list_projects(trace_context=trace)
        channel = session.get(DeliveryChannelModel, loaded.default_delivery_channel_id)

    assert duplicate.project_id == loaded.project_id
    assert channel is not None
    assert channel.project_id == loaded.project_id
    assert [project.project_id for project in projects] == [
        "project-default",
        loaded.project_id,
    ]
    assert all(project.is_visible for project in projects)


def test_load_project_audits_successful_existing_project_load(tmp_path: Path) -> None:
    from backend.app.services.projects import ProjectService

    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    manager = build_control_manager(tmp_path, default_root)
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProjectService(
            session,
            settings=settings,
            audit_service=audit,
            now=lambda: NOW,
        )
        first = service.load_project(root_path=loaded_root, trace_context=build_trace())
        second = service.load_project(root_path=loaded_root, trace_context=build_trace())

    load_records = [
        record for record in audit.records if record["action"] == "project.load"
    ]
    assert second.project_id == first.project_id
    assert len(load_records) == 2
    assert all(record["result"] is AuditResult.SUCCEEDED for record in load_records)
    assert all(str(loaded_root.resolve()) not in record["target_id"] for record in load_records)
    assert all(
        record["metadata"]["root_path_hash"].startswith("sha256:")
        for record in load_records
    )


def test_load_project_rejects_missing_root_and_audits_hashed_target(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService, ProjectServiceError

    default_root = tmp_path / "platform"
    missing_root = tmp_path / "missing"
    default_root.mkdir()
    manager = build_control_manager(tmp_path, default_root)
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProjectService(
            session,
            settings=settings,
            audit_service=audit,
            now=lambda: NOW,
        )
        with pytest.raises(ProjectServiceError) as exc_info:
            service.load_project(root_path=missing_root, trace_context=build_trace())

        saved_projects = session.query(ProjectModel).all()

    assert exc_info.value.message == "Project root_path must be an existing directory."
    assert saved_projects == []
    assert audit.records[0]["method"] == "record_rejected_command"
    assert audit.records[0]["action"] == "project.load.rejected"
    assert audit.records[0]["target_type"] == "project"
    assert str(missing_root.resolve(strict=False)) not in audit.records[0]["target_id"]
    assert audit.records[0]["metadata"]["root_path_hash"].startswith("sha256:")


def test_load_project_rolls_back_control_state_when_success_audit_fails(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    manager = build_control_manager(tmp_path, default_root)
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProjectService(
            session,
            settings=settings,
            audit_service=FailingAuditService(),
            now=lambda: NOW,
        )
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            service.load_project(root_path=loaded_root, trace_context=build_trace())

        saved_projects = session.query(ProjectModel).all()
        saved_channels = session.query(DeliveryChannelModel).all()

    assert saved_projects == []
    assert saved_channels == []


def test_existing_project_load_rolls_back_channel_repair_when_success_audit_fails(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    manager = build_control_manager(tmp_path, default_root)
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )

    with manager.session(DatabaseRole.CONTROL) as session:
        created = ProjectService(
            session,
            settings=settings,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).load_project(root_path=loaded_root, trace_context=build_trace())
        created_project_id = created.project_id

    with manager.session(DatabaseRole.CONTROL) as session:
        project = session.get(ProjectModel, created_project_id)
        assert project is not None
        channel = session.get(DeliveryChannelModel, project.default_delivery_channel_id)
        assert channel is not None
        session.delete(channel)
        project.default_delivery_channel_id = None
        session.commit()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProjectService(
            session,
            settings=settings,
            audit_service=FailingAuditService(),
            now=lambda: NOW,
        )
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            service.load_project(root_path=loaded_root, trace_context=build_trace())

        saved_project = session.get(ProjectModel, created_project_id)
        saved_channels = session.query(DeliveryChannelModel).all()

    assert saved_project is not None
    assert saved_project.default_delivery_channel_id is None
    assert saved_channels == []


def test_remove_project_blocks_real_pending_startup_publication_without_mutation(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import (
        PROJECT_REMOVE_BLOCKED_ERROR_CODE,
        ProjectService,
    )

    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    manager = build_control_manager(tmp_path, default_root)
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = ProjectService(
            session,
            settings=settings,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).load_project(root_path=loaded_root, trace_context=build_trace())
        project_id = project.project_id

    seed_pending_startup(
        manager,
        project_id=project_id,
        session_id="session-startup-pending",
        run_id="run-startup-pending",
    )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = ProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: NOW,
        ).remove_project(project_id=project_id, trace_context=build_trace())
        saved_project = control_session.get(ProjectModel, project_id)
        saved_session = control_session.get(SessionModel, "session-startup-pending")

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-startup-pending"
    assert result.error_code == PROJECT_REMOVE_BLOCKED_ERROR_CODE
    assert saved_project is not None
    assert saved_project.is_visible is True
    assert saved_project.visibility_removed_at is None
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert saved_session.visibility_removed_at is None
    assert saved_session.current_run_id is None
    assert audit.records[-1]["action"] == "project.remove"
    assert audit.records[-1]["result"] is AuditResult.BLOCKED
    assert audit.records[-1]["metadata"]["blocking_run_id"] == "run-startup-pending"


def test_remove_project_raises_internal_error_when_runtime_barrier_cannot_be_acquired(
    tmp_path: Path,
) -> None:
    from backend.app.api.error_codes import ErrorCode
    from backend.app.services.projects import (
        PROJECT_RUNTIME_STATE_UNAVAILABLE_MESSAGE,
        ProjectService,
        ProjectServiceError,
    )

    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    manager = build_control_manager(tmp_path, default_root)
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = ProjectService(
            session,
            settings=settings,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).load_project(root_path=loaded_root, trace_context=build_trace())
        project_id = project.project_id
    seed_template_if_missing(manager)
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            SessionModel(
                session_id="session-removable",
                project_id=project_id,
                display_name="session-removable",
                status=SessionStatus.DRAFT,
                selected_template_id="template-feature",
                current_run_id=None,
                latest_stage_type=None,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

    runtime_engine = create_engine(
        f"sqlite:///{manager.database_path(DatabaseRole.RUNTIME).as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 0},
    )
    runtime_session_factory = sessionmaker(bind=runtime_engine, expire_on_commit=False)
    lock_connection = runtime_engine.connect()
    lock_connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        with (
            manager.session(DatabaseRole.CONTROL) as control_session,
            runtime_session_factory() as runtime_session,
        ):
            with pytest.raises(ProjectServiceError) as exc_info:
                ProjectService(
                    control_session,
                    settings=settings,
                    runtime_session=runtime_session,
                    audit_service=audit,
                    now=lambda: NOW,
                ).remove_project(project_id=project_id, trace_context=build_trace())
            saved_project = control_session.get(ProjectModel, project_id)
            saved_session = control_session.get(SessionModel, "session-removable")
    finally:
        lock_connection.rollback()
        lock_connection.close()
        runtime_engine.dispose()

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    assert exc_info.value.message == PROJECT_RUNTIME_STATE_UNAVAILABLE_MESSAGE
    assert saved_project is not None
    assert saved_project.is_visible is True
    assert saved_project.visibility_removed_at is None
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert saved_session.visibility_removed_at is None
    assert audit.records == []
