from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.log import AuditLogEntryModel, LogBase
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


NOW = datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append(
            {
                "method": "record_rejected_command",
                "result": AuditResult.REJECTED,
                **kwargs,
            }
        )
        return object()


class FailingSuccessAuditService(RecordingAuditService):
    def record_command_result(self, **kwargs: Any) -> object:
        if kwargs["result"] is AuditResult.SUCCEEDED:
            raise RuntimeError("project remove audit unavailable")
        return super().record_command_result(**kwargs)


def build_settings(tmp_path: Path) -> EnvironmentSettings:
    default_root = tmp_path / "platform"
    default_root.mkdir(exist_ok=True)
    return EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    settings = build_settings(tmp_path)
    manager = DatabaseManager.from_environment_settings(settings)
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    return manager


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="req-project-remove",
        trace_id="trace-project-remove",
        correlation_id="corr-project-remove",
        span_id="span-project-remove",
        parent_span_id=None,
        created_at=NOW,
    )


def seed_project(
    manager: DatabaseManager,
    *,
    project_id: str,
    root_path: Path,
    is_default: bool = False,
    is_visible: bool = True,
    removed_at: datetime | None = None,
) -> None:
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
                    max_react_iterations_per_stage=30,
                    max_tool_calls_per_stage=80,
                    skip_high_risk_tool_confirmations=False,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        project = ProjectModel(
            project_id=project_id,
            name=root_path.name,
            root_path=str(root_path.resolve()),
            default_delivery_channel_id=f"delivery-{project_id}",
            is_default=is_default,
            is_visible=is_visible,
            visibility_removed_at=removed_at,
            created_at=NOW,
            updated_at=NOW if removed_at is None else removed_at,
        )
        session.add(project)
        session.flush()
        session.add(
            DeliveryChannelModel(
                delivery_channel_id=f"delivery-{project_id}",
                project_id=project_id,
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
                scm_provider_type=None,
                repository_identifier=None,
                default_branch=None,
                code_review_request_type=None,
                credential_ref=None,
                credential_status=CredentialStatus.READY,
                readiness_status=DeliveryReadinessStatus.READY,
                readiness_message=None,
                last_validated_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def seed_session(
    manager: DatabaseManager,
    *,
    project_id: str,
    session_id: str,
    status: SessionStatus = SessionStatus.DRAFT,
    current_run_id: str | None = None,
    is_visible: bool = True,
    removed_at: datetime | None = None,
    updated_at: datetime = NOW,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            SessionModel(
                session_id=session_id,
                project_id=project_id,
                display_name=session_id,
                status=status,
                selected_template_id="template-feature",
                current_run_id=current_run_id,
                latest_stage_type=None,
                is_visible=is_visible,
                visibility_removed_at=removed_at,
                created_at=NOW,
                updated_at=updated_at,
            )
        )
        session.commit()


def seed_run(
    manager: DatabaseManager,
    *,
    project_id: str,
    session_id: str,
    run_id: str,
    run_status: RunStatus,
) -> None:
    runtime_limit_ref = f"runtime-limit-{run_id}"
    provider_policy_ref = f"policy-{run_id}"
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
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
        session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id=provider_policy_ref,
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
                status=run_status,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-1",
                graph_definition_ref="graph-definition-1",
                graph_thread_ref="graph-thread-1",
                workspace_ref="workspace-1",
                runtime_limit_snapshot_ref=runtime_limit_ref,
                provider_call_policy_snapshot_ref=provider_policy_ref,
                delivery_channel_snapshot_ref=None,
                current_stage_run_id=None,
                trace_id=f"trace-{run_id}",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def seed_pending_startup_publication(
    manager: DatabaseManager,
    *,
    project_id: str,
    session_id: str,
    run_id: str = "run-startup-pending",
) -> None:
    seed_run(
        manager,
        project_id=project_id,
        session_id=session_id,
        run_id=run_id,
        run_status=RunStatus.RUNNING,
    )
    with manager.session(DatabaseRole.CONTROL) as session:
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


def test_remove_project_soft_hides_project_and_currently_visible_sessions(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-visible")
    seed_session(
        manager,
        project_id="project-alpha",
        session_id="session-hidden",
        is_visible=False,
        removed_at=NOW,
    )
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = ProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).remove_project(
            project_id="project-alpha",
            trace_context=build_trace(),
        )
        project = control_session.get(ProjectModel, "project-alpha")
        visible_session = control_session.get(SessionModel, "session-visible")
        hidden_session = control_session.get(SessionModel, "session-hidden")

    assert result.project_id == "project-alpha"
    assert result.visibility_removed is True
    assert result.blocked_by_active_run is False
    assert result.blocking_run_id is None
    assert result.error_code is None
    assert result.message == "Project removed from regular product history."
    assert project is not None
    assert project.is_visible is False
    assert project.visibility_removed_at == LATER.replace(tzinfo=None)
    assert visible_session is not None
    assert visible_session.is_visible is False
    assert visible_session.visibility_removed_at == LATER.replace(tzinfo=None)
    assert visible_session.status is SessionStatus.DRAFT
    assert visible_session.current_run_id is None
    assert hidden_session is not None
    assert hidden_session.is_visible is False
    assert hidden_session.visibility_removed_at == NOW.replace(tzinfo=None)
    assert audit.records[-1]["action"] == "project.remove"
    assert audit.records[-1]["result"] is AuditResult.SUCCEEDED
    assert str(root.resolve()) not in audit.records[-1]["target_id"]
    assert audit.records[-1]["metadata"]["root_path_hash"].startswith("sha256:")
    assert audit.records[-1]["metadata"]["hidden_visible_session_count"] == 1


def test_remove_project_returns_blocked_result_for_active_run_without_mutation(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(
        manager,
        project_id="project-alpha",
        session_id="session-running",
        status=SessionStatus.RUNNING,
        current_run_id="run-active",
    )
    seed_run(
        manager,
        project_id="project-alpha",
        session_id="session-running",
        run_id="run-active",
        run_status=RunStatus.RUNNING,
    )
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = ProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).remove_project(
            project_id="project-alpha",
            trace_context=build_trace(),
        )
        project = control_session.get(ProjectModel, "project-alpha")
        saved_session = control_session.get(SessionModel, "session-running")
        run = runtime_session.get(PipelineRunModel, "run-active")

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-active"
    assert result.error_code == "project_active_run_blocks_remove"
    assert result.message == "Project has an active run."
    assert project is not None
    assert project.is_visible is True
    assert project.visibility_removed_at is None
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert saved_session.visibility_removed_at is None
    assert saved_session.status is SessionStatus.RUNNING
    assert saved_session.current_run_id == "run-active"
    assert run is not None
    assert run.status is RunStatus.RUNNING
    assert audit.records[-1]["action"] == "project.remove"
    assert audit.records[-1]["result"] is AuditResult.BLOCKED
    assert audit.records[-1]["metadata"]["blocking_run_id"] == "run-active"


def test_remove_project_blocks_when_runtime_has_active_project_run_not_current_tail(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(
        manager,
        project_id="project-alpha",
        session_id="session-rerun",
        status=SessionStatus.FAILED,
        current_run_id="run-old-terminal",
    )
    seed_run(
        manager,
        project_id="project-alpha",
        session_id="session-rerun",
        run_id="run-old-terminal",
        run_status=RunStatus.FAILED,
    )
    seed_run(
        manager,
        project_id="project-alpha",
        session_id="session-rerun",
        run_id="run-new-active",
        run_status=RunStatus.RUNNING,
    )
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = ProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).remove_project(
            project_id="project-alpha",
            trace_context=build_trace(),
        )
        project = control_session.get(ProjectModel, "project-alpha")
        saved_session = control_session.get(SessionModel, "session-rerun")

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-new-active"
    assert result.error_code == "project_active_run_blocks_remove"
    assert project is not None
    assert project.is_visible is True
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert saved_session.current_run_id == "run-old-terminal"
    assert audit.records[-1]["action"] == "project.remove"
    assert audit.records[-1]["result"] is AuditResult.BLOCKED


def test_remove_project_rejects_default_already_removed_and_missing_project(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService, ProjectServiceError

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    default_root = tmp_path / "default-project"
    removed_root = tmp_path / "removed-project"
    default_root.mkdir()
    removed_root.mkdir()
    seed_project(
        manager,
        project_id="project-default",
        root_path=default_root,
        is_default=True,
    )
    seed_project(
        manager,
        project_id="project-removed",
        root_path=removed_root,
        is_visible=False,
        removed_at=NOW,
    )
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        service = ProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        )
        with pytest.raises(ProjectServiceError) as default_error:
            service.remove_project(
                project_id="project-default",
                trace_context=build_trace(),
            )
        with pytest.raises(ProjectServiceError) as removed_error:
            service.remove_project(
                project_id="project-removed",
                trace_context=build_trace(),
            )
        with pytest.raises(ProjectServiceError) as missing_error:
            service.remove_project(
                project_id="project-missing",
                trace_context=build_trace(),
            )

    assert default_error.value.status_code == 409
    assert default_error.value.message == "Default Project cannot be removed."
    assert removed_error.value.status_code == 409
    assert removed_error.value.message == (
        "Project was already removed from regular product history."
    )
    assert missing_error.value.status_code == 404
    assert missing_error.value.message == "Project was not found."
    assert [record["action"] for record in audit.records] == [
        "project.remove.rejected",
        "project.remove.rejected",
        "project.remove.rejected",
    ]


def test_load_project_reactivates_hidden_project_without_restoring_hidden_sessions(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService, _project_id_for_root

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    project_id = _project_id_for_root(root.resolve())
    seed_project(
        manager,
        project_id=project_id,
        root_path=root,
        is_visible=False,
        removed_at=NOW,
    )
    seed_session(
        manager,
        project_id=project_id,
        session_id="session-hidden",
        is_visible=False,
        removed_at=NOW,
    )

    with manager.session(DatabaseRole.CONTROL) as control_session:
        loaded = ProjectService(
            control_session,
            settings=settings,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).load_project(
            root_path=root,
            trace_context=build_trace(),
        )
        hidden_session = control_session.get(SessionModel, "session-hidden")

    assert loaded.project_id == project_id
    assert loaded.is_visible is True
    assert loaded.visibility_removed_at is None
    assert loaded.updated_at == LATER
    assert hidden_session is not None
    assert hidden_session.is_visible is False
    assert hidden_session.visibility_removed_at == NOW.replace(tzinfo=None)


def test_remove_project_returns_blocked_for_pending_startup_publication(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-starting")
    seed_pending_startup_publication(
        manager,
        project_id="project-alpha",
        session_id="session-starting",
        run_id="run-startup-pending",
    )
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = ProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).remove_project(
            project_id="project-alpha",
            trace_context=build_trace(),
        )
        project = control_session.get(ProjectModel, "project-alpha")
        saved_session = control_session.get(SessionModel, "session-starting")

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-startup-pending"
    assert result.error_code == "project_active_run_blocks_remove"
    assert project is not None
    assert project.is_visible is True
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert audit.records[-1]["result"] is AuditResult.BLOCKED


def test_remove_project_restores_project_and_sessions_when_success_audit_fails(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-visible")

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        with pytest.raises(RuntimeError, match="project remove audit unavailable"):
            ProjectService(
                control_session,
                settings=settings,
                runtime_session=runtime_session,
                audit_service=FailingSuccessAuditService(),
                now=lambda: LATER,
            ).remove_project(
                project_id="project-alpha",
                trace_context=build_trace(),
            )

    with manager.session(DatabaseRole.CONTROL) as verify_session:
        project = verify_session.get(ProjectModel, "project-alpha")
        saved_session = verify_session.get(SessionModel, "session-visible")

    assert project is not None
    assert project.is_visible is True
    assert project.visibility_removed_at is None
    assert project.updated_at == NOW.replace(tzinfo=None)
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert saved_session.visibility_removed_at is None
    assert saved_session.updated_at == NOW.replace(tzinfo=None)


def test_remove_project_restores_visibility_when_success_audit_primary_ledger_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.observability.audit import AuditService
    from backend.app.observability.log_writer import JsonlLogWriter
    from backend.app.observability.runtime_data import RuntimeDataSettings
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-visible")
    runtime_settings = RuntimeDataSettings.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )

    with manager.session(DatabaseRole.LOG) as log_session:
        audit = AuditService(
            log_session,
            audit_writer=JsonlLogWriter(runtime_settings),
        )
        monkeypatch.setattr(
            log_session,
            "commit",
            lambda: (_ for _ in ()).throw(
                SQLAlchemyError("audit primary ledger unavailable")
            ),
        )
        with (
            manager.session(DatabaseRole.CONTROL) as control_session,
            manager.session(DatabaseRole.RUNTIME) as runtime_session,
        ):
            with pytest.raises(Exception):
                ProjectService(
                    control_session,
                    settings=settings,
                    runtime_session=runtime_session,
                    audit_service=audit,
                    now=lambda: LATER,
                ).remove_project(
                    project_id="project-alpha",
                    trace_context=build_trace(),
                )

    with (
        manager.session(DatabaseRole.CONTROL) as verify_control,
        manager.session(DatabaseRole.LOG) as verify_log,
    ):
        project = verify_control.get(ProjectModel, "project-alpha")
        saved_session = verify_control.get(SessionModel, "session-visible")
        success_audit_count = (
            verify_log.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "project.remove",
                AuditLogEntryModel.result == AuditResult.SUCCEEDED,
            )
            .count()
        )

    assert project is not None
    assert project.is_visible is True
    assert project.visibility_removed_at is None
    assert project.updated_at == NOW.replace(tzinfo=None)
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert saved_session.visibility_removed_at is None
    assert saved_session.updated_at == NOW.replace(tzinfo=None)
    assert success_audit_count == 0


def test_remove_project_treats_after_ledger_audit_failure_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.observability.audit import AuditService, AuditWriteError
    from backend.app.observability.log_writer import JsonlLogWriter
    from backend.app.observability.runtime_data import RuntimeDataSettings
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-visible")
    runtime_settings = RuntimeDataSettings.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )

    with manager.session(DatabaseRole.LOG) as log_session:
        audit = AuditService(
            log_session,
            audit_writer=JsonlLogWriter(runtime_settings),
        )
        original_record_copy_result = audit._record_audit_copy_result_or_raise

        def fail_after_ledger_commit(*args: Any, **kwargs: Any) -> None:
            original_record_copy_result(*args, **kwargs)
            with manager.session(DatabaseRole.CONTROL) as committed_control:
                committed_project = committed_control.get(ProjectModel, "project-alpha")
                committed_session = committed_control.get(
                    SessionModel,
                    "session-visible",
                )
            assert committed_project is not None
            assert committed_project.is_visible is False
            assert committed_session is not None
            assert committed_session.is_visible is False
            raise AuditWriteError("audit copy metadata unavailable")

        monkeypatch.setattr(
            audit,
            "_record_audit_copy_result_or_raise",
            fail_after_ledger_commit,
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
                now=lambda: LATER,
            ).remove_project(
                project_id="project-alpha",
                trace_context=build_trace(),
            )
            project = control_session.get(ProjectModel, "project-alpha")
            saved_session = control_session.get(SessionModel, "session-visible")

        success_audits = (
            log_session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "project.remove",
                AuditLogEntryModel.result == AuditResult.SUCCEEDED,
            )
            .all()
        )

    assert result.visibility_removed is True
    assert result.blocked_by_active_run is False
    assert project is not None
    assert project.is_visible is False
    assert project.visibility_removed_at == LATER.replace(tzinfo=None)
    assert saved_session is not None
    assert saved_session.is_visible is False
    assert saved_session.visibility_removed_at == LATER.replace(tzinfo=None)
    assert len(success_audits) == 1


def test_remove_project_returns_blocked_if_pending_publication_appears_after_initial_check(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-visible")
    audit = RecordingAuditService()

    class RaceProjectService(ProjectService):
        injected = False

        def assert_project_removable(self, **kwargs: Any) -> Any:
            result = super().assert_project_removable(**kwargs)
            if self.injected:
                return result
            self.injected = True
            seed_pending_startup_publication(
                manager,
                project_id="project-alpha",
                session_id="session-visible",
                run_id="run-startup-raced",
            )
            return result

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = RaceProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).remove_project(
            project_id="project-alpha",
            trace_context=build_trace(),
        )
        project = control_session.get(ProjectModel, "project-alpha")
        saved_session = control_session.get(SessionModel, "session-visible")

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-startup-raced"
    assert result.error_code == "project_active_run_blocks_remove"
    assert project is not None
    assert project.is_visible is True
    assert saved_session is not None
    assert saved_session.is_visible is True
    assert audit.records[-1]["action"] == "project.remove"
    assert audit.records[-1]["result"] is AuditResult.BLOCKED


def test_remove_project_requires_runtime_session_for_project_wide_runtime_truth(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService, ProjectServiceError

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-visible")
    seed_run(
        manager,
        project_id="project-alpha",
        session_id="session-visible",
        run_id="run-runtime-only-active",
        run_status=RunStatus.RUNNING,
    )
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        with pytest.raises(ProjectServiceError) as error:
            ProjectService(
                control_session,
                settings=settings,
                audit_service=audit,
                now=lambda: LATER,
            ).remove_project(
                project_id="project-alpha",
                trace_context=build_trace(),
            )

    assert error.value.status_code == 500
    assert (
        error.value.message
        == "Runtime session is required to verify current run state before removing a Project."
    )
    assert audit.records == []


def test_remove_project_runtime_barrier_blocks_concurrent_runtime_write_during_remove(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-visible")
    audit = RecordingAuditService()

    class RuntimeBarrierProjectService(ProjectService):
        attempted = False

        def hide_project_sessions(self, **kwargs: Any) -> int:
            if not self.attempted:
                self.attempted = True
                engine = create_engine(
                    f"sqlite:///{manager.database_path(DatabaseRole.RUNTIME).as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 0},
                )
                blocked_session = sessionmaker(bind=engine, expire_on_commit=False)()
                try:
                    blocked_session.add(
                        RuntimeLimitSnapshotModel(
                            snapshot_id="runtime-limit-barrier",
                            run_id="run-barrier",
                            agent_limits={},
                            context_limits={},
                            source_config_version="config-v1",
                            hard_limits_version="hard-limits-v1",
                            schema_version="runtime-limit-v1",
                            created_at=NOW,
                        )
                    )
                    with pytest.raises(OperationalError):
                        blocked_session.commit()
                finally:
                    blocked_session.close()
                    engine.dispose()
            return super().hide_project_sessions(**kwargs)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = RuntimeBarrierProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).remove_project(
            project_id="project-alpha",
            trace_context=build_trace(),
        )
        project = control_session.get(ProjectModel, "project-alpha")
        saved_session = control_session.get(SessionModel, "session-visible")

    assert result.visibility_removed is True
    assert result.blocked_by_active_run is False
    assert result.blocking_run_id is None
    assert result.error_code is None
    assert project is not None
    assert project.is_visible is False
    assert project.visibility_removed_at == LATER.replace(tzinfo=None)
    assert saved_session is not None
    assert saved_session.is_visible is False
    assert saved_session.visibility_removed_at == LATER.replace(tzinfo=None)
    assert audit.records[-1]["action"] == "project.remove"
    assert audit.records[-1]["result"] is AuditResult.SUCCEEDED

    with manager.session(DatabaseRole.RUNTIME) as verify_runtime:
        blocked_snapshot = verify_runtime.get(
            RuntimeLimitSnapshotModel,
            "runtime-limit-barrier",
        )

    assert blocked_snapshot is None


def test_runtime_remove_barrier_blocks_concurrent_runtime_writes(
    tmp_path: Path,
) -> None:
    from backend.app.services.projects import ProjectService

    manager = build_manager(tmp_path)
    settings = build_settings(tmp_path)
    root = tmp_path / "project-alpha"
    root.mkdir()
    seed_project(manager, project_id="project-alpha", root_path=root)
    seed_session(manager, project_id="project-alpha", session_id="session-visible")

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        service = ProjectService(
            control_session,
            settings=settings,
            runtime_session=runtime_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        )
        with service._runtime_remove_barrier():
            engine = create_engine(
                f"sqlite:///{manager.database_path(DatabaseRole.RUNTIME).as_posix()}",
                connect_args={"check_same_thread": False, "timeout": 0},
            )
            blocked_session = sessionmaker(bind=engine, expire_on_commit=False)()
            try:
                blocked_session.add(
                    RuntimeLimitSnapshotModel(
                        snapshot_id="runtime-limit-barrier",
                        run_id="run-barrier",
                        agent_limits={},
                        context_limits={},
                        source_config_version="config-v1",
                        hard_limits_version="hard-limits-v1",
                        schema_version="runtime-limit-v1",
                        created_at=NOW,
                    )
                )
                with pytest.raises(OperationalError):
                    blocked_session.commit()
            finally:
                blocked_session.close()
                engine.dispose()
