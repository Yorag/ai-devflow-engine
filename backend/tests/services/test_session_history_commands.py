from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.app.db.base import DatabaseRole
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.db.models.control import (
    ControlBase,
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
            raise RuntimeError("success audit unavailable")
        return super().record_command_result(**kwargs)


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    return manager


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="req-session-delete",
        trace_id="trace-session-delete",
        correlation_id="corr-session-delete",
        span_id="span-session-delete",
        parent_span_id=None,
        created_at=NOW,
    )


def seed_runtime_run(
    manager: DatabaseManager,
    *,
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
                project_id="project-default",
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
                trace_id="trace-run-1",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def seed_session(
    manager: DatabaseManager,
    *,
    session_id: str = "session-1",
    session_status: SessionStatus = SessionStatus.DRAFT,
    current_run_id: str | None = None,
    run_status: RunStatus | None = None,
    is_visible: bool = True,
    updated_at: datetime = NOW,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        if session.get(ProjectModel, "project-default") is None:
            session.add(
                ProjectModel(
                    project_id="project-default",
                    name="AI Devflow Engine",
                    root_path="C:/repo/ai-devflow-engine",
                    default_delivery_channel_id="delivery-default",
                    is_default=True,
                    is_visible=True,
                    visibility_removed_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
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
        session.add(
            SessionModel(
                session_id=session_id,
                project_id="project-default",
                display_name="Delete me",
                status=session_status,
                selected_template_id="template-feature",
                current_run_id=current_run_id,
                latest_stage_type=None,
                is_visible=is_visible,
                visibility_removed_at=None if is_visible else LATER,
                created_at=NOW,
                updated_at=updated_at,
            )
        )
        session.commit()

    if current_run_id and run_status is not None:
        seed_runtime_run(
            manager,
            session_id=session_id,
            run_id=current_run_id,
            run_status=run_status,
        )


def seed_pending_startup_publication(
    manager: DatabaseManager,
    *,
    session_id: str,
    run_id: str = "run-startup-pending",
) -> None:
    seed_runtime_run(
        manager,
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


def test_list_visible_sessions_returns_only_product_visible_history(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager, session_id="session-old")
    seed_session(manager, session_id="session-new", updated_at=LATER)
    seed_session(manager, session_id="session-hidden", is_visible=False)

    with manager.session(DatabaseRole.CONTROL) as control_session:
        listed = SessionService(
            control_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).list_visible_sessions(
            project_id="project-default",
            trace_context=build_trace(),
        )

    assert [item.session_id for item in listed] == ["session-new", "session-old"]


def test_delete_session_soft_hides_visible_session_without_active_run_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).delete_session(
            session_id="session-1",
            trace_context=build_trace(),
        )
        saved = control_session.get(SessionModel, "session-1")

    assert result.visibility_removed is True
    assert result.blocked_by_active_run is False
    assert result.blocking_run_id is None
    assert result.error_code is None
    assert result.message == "Session removed from regular product history."
    assert saved is not None
    assert saved.is_visible is False
    assert saved.visibility_removed_at == LATER.replace(tzinfo=None)
    assert saved.status is SessionStatus.DRAFT
    assert saved.current_run_id is None
    assert audit.records[-1]["action"] == "session.delete"
    assert audit.records[-1]["result"] is AuditResult.SUCCEEDED
    assert audit.records[-1]["metadata"]["visibility_removed"] is True
    assert audit.records[-1]["metadata"]["visibility_removed_at"] == LATER.isoformat()
    assert audit.records[-1]["metadata"]["status"] == "draft"
    assert audit.records[-1]["metadata"]["current_run_id"] is None


def test_delete_session_updates_loaded_same_session_state_after_success(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        preloaded = control_session.get(SessionModel, "session-1")
        assert preloaded is not None
        assert preloaded.is_visible is True

        result = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).delete_session(
            session_id="session-1",
            trace_context=build_trace(),
        )
        same_session_loaded = control_session.get(SessionModel, "session-1")

    assert result.visibility_removed is True
    assert same_session_loaded is preloaded
    assert same_session_loaded.is_visible is False
    assert same_session_loaded.visibility_removed_at == LATER.replace(tzinfo=None)
    assert same_session_loaded.updated_at == LATER.replace(tzinfo=None)


def test_delete_session_restores_visibility_when_success_audit_fails(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        with pytest.raises(RuntimeError, match="success audit unavailable"):
            SessionService(
                control_session,
                runtime_session=runtime_session,
                audit_service=FailingSuccessAuditService(),
                now=lambda: LATER,
            ).delete_session(
                session_id="session-1",
                trace_context=build_trace(),
            )

    with manager.session(DatabaseRole.CONTROL) as verify_session:
        saved = verify_session.get(SessionModel, "session-1")

    assert saved is not None
    assert saved.is_visible is True
    assert saved.visibility_removed_at is None
    assert saved.updated_at == NOW.replace(tzinfo=None)


def test_delete_session_restores_visibility_when_success_audit_primary_ledger_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.core.config import EnvironmentSettings
    from backend.app.observability.audit import AuditService
    from backend.app.observability.log_writer import JsonlLogWriter
    from backend.app.observability.runtime_data import RuntimeDataSettings
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)
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
                SessionService(
                    control_session,
                    runtime_session=runtime_session,
                    audit_service=audit,
                    now=lambda: LATER,
                ).delete_session(
                    session_id="session-1",
                    trace_context=build_trace(),
                )

    with (
        manager.session(DatabaseRole.CONTROL) as verify_control,
        manager.session(DatabaseRole.LOG) as verify_log,
    ):
        saved = verify_control.get(SessionModel, "session-1")
        success_audit_count = (
            verify_log.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "session.delete",
                AuditLogEntryModel.result == AuditResult.SUCCEEDED,
            )
            .count()
        )

    assert saved is not None
    assert saved.is_visible is True
    assert saved.visibility_removed_at is None
    assert saved.updated_at == NOW.replace(tzinfo=None)
    assert success_audit_count == 0


def test_delete_session_treats_after_ledger_audit_failure_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.core.config import EnvironmentSettings
    from backend.app.observability.audit import AuditService, AuditWriteError
    from backend.app.observability.log_writer import JsonlLogWriter
    from backend.app.observability.runtime_data import RuntimeDataSettings
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)
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
            result = SessionService(
                control_session,
                runtime_session=runtime_session,
                audit_service=audit,
                now=lambda: LATER,
            ).delete_session(
                session_id="session-1",
                trace_context=build_trace(),
            )
            saved = control_session.get(SessionModel, "session-1")

        success_audits = (
            log_session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "session.delete",
                AuditLogEntryModel.result == AuditResult.SUCCEEDED,
            )
            .all()
        )

    assert result.visibility_removed is True
    assert result.blocked_by_active_run is False
    assert saved is not None
    assert saved.is_visible is False
    assert saved.visibility_removed_at == LATER.replace(tzinfo=None)
    assert len(success_audits) == 1


def test_delete_session_does_not_record_success_audit_when_control_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        monkeypatch.setattr(
            control_session,
            "commit",
            lambda: (_ for _ in ()).throw(RuntimeError("control commit unavailable")),
        )
        with pytest.raises(RuntimeError, match="control commit unavailable"):
            SessionService(
                control_session,
                runtime_session=runtime_session,
                audit_service=audit,
                now=lambda: LATER,
            ).delete_session(
                session_id="session-1",
                trace_context=build_trace(),
            )

    with manager.session(DatabaseRole.CONTROL) as verify_session:
        saved = verify_session.get(SessionModel, "session-1")

    assert saved is not None
    assert saved.is_visible is True
    assert saved.visibility_removed_at is None
    assert audit.records == []


def test_delete_session_returns_blocked_result_for_active_run_and_keeps_facts(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(
        manager,
        session_status=SessionStatus.RUNNING,
        current_run_id="run-active",
        run_status=RunStatus.RUNNING,
    )
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).delete_session(
            session_id="session-1",
            trace_context=build_trace(),
        )
        saved = control_session.get(SessionModel, "session-1")
        run = runtime_session.get(PipelineRunModel, "run-active")

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-active"
    assert result.error_code == "session_active_run_blocks_delete"
    assert result.message == "Session has an active run."
    assert saved is not None
    assert saved.is_visible is True
    assert saved.visibility_removed_at is None
    assert saved.status is SessionStatus.RUNNING
    assert saved.current_run_id == "run-active"
    assert run is not None
    assert run.status is RunStatus.RUNNING
    assert audit.records[-1]["action"] == "session.delete"
    assert audit.records[-1]["result"] is AuditResult.BLOCKED
    assert audit.records[-1]["metadata"]["visibility_removed"] is False
    assert audit.records[-1]["metadata"]["blocking_run_id"] == "run-active"
    assert audit.records[-1]["metadata"]["status"] == "running"
    assert audit.records[-1]["metadata"]["current_run_id"] == "run-active"


def test_delete_session_returns_blocked_for_pending_startup_publication(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)
    seed_pending_startup_publication(
        manager,
        session_id="session-1",
        run_id="run-startup-pending",
    )
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).delete_session(
            session_id="session-1",
            trace_context=build_trace(),
        )
        saved = control_session.get(SessionModel, "session-1")
        publication = control_session.get(
            StartupPublicationModel,
            "publication-run-startup-pending",
        )

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-startup-pending"
    assert result.error_code == "session_active_run_blocks_delete"
    assert result.message == "Session has an active run."
    assert saved is not None
    assert saved.is_visible is True
    assert saved.visibility_removed_at is None
    assert saved.status is SessionStatus.DRAFT
    assert saved.current_run_id is None
    assert publication is not None
    assert publication.publication_state == PUBLICATION_STATE_PENDING
    assert publication.pending_session_id == "session-1"
    assert audit.records[-1]["action"] == "session.delete"
    assert audit.records[-1]["result"] is AuditResult.BLOCKED
    assert audit.records[-1]["metadata"]["visibility_removed"] is False
    assert audit.records[-1]["metadata"]["blocking_run_id"] == "run-startup-pending"
    assert audit.records[-1]["metadata"]["status"] == "draft"
    assert audit.records[-1]["metadata"]["current_run_id"] is None


def test_delete_session_returns_blocked_if_run_starts_between_check_and_write(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)
    audit = RecordingAuditService()

    class RaceSessionService(SessionService):
        injected = False

        def assert_session_deletable(self, **kwargs: Any) -> Any:
            result = super().assert_session_deletable(**kwargs)
            if self.injected:
                return result
            self.injected = True
            seed_runtime_run(
                manager,
                session_id="session-1",
                run_id="run-raced",
                run_status=RunStatus.RUNNING,
            )
            with manager.session(DatabaseRole.CONTROL) as concurrent_session:
                row = concurrent_session.get(SessionModel, "session-1")
                assert row is not None
                row.status = SessionStatus.RUNNING
                row.current_run_id = "run-raced"
                row.updated_at = LATER
                concurrent_session.add(row)
                concurrent_session.commit()
            return result

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = RaceSessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).delete_session(
            session_id="session-1",
            trace_context=build_trace(),
        )
        saved = control_session.get(SessionModel, "session-1")

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-raced"
    assert result.error_code == "session_active_run_blocks_delete"
    assert saved is not None
    assert saved.is_visible is True
    assert saved.visibility_removed_at is None
    assert saved.status is SessionStatus.RUNNING
    assert saved.current_run_id == "run-raced"
    assert audit.records[-1]["action"] == "session.delete"
    assert audit.records[-1]["result"] is AuditResult.BLOCKED


def test_delete_session_returns_blocked_if_startup_publication_begins_between_check_and_write(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(manager)
    audit = RecordingAuditService()

    class RaceSessionService(SessionService):
        injected = False

        def assert_session_deletable(self, **kwargs: Any) -> Any:
            result = super().assert_session_deletable(**kwargs)
            if self.injected:
                return result
            self.injected = True
            seed_pending_startup_publication(
                manager,
                session_id="session-1",
                run_id="run-startup-raced",
            )
            return result

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = RaceSessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        ).delete_session(
            session_id="session-1",
            trace_context=build_trace(),
        )
        saved = control_session.get(SessionModel, "session-1")
        publication = control_session.get(
            StartupPublicationModel,
            "publication-run-startup-raced",
        )

    assert result.visibility_removed is False
    assert result.blocked_by_active_run is True
    assert result.blocking_run_id == "run-startup-raced"
    assert result.error_code == "session_active_run_blocks_delete"
    assert saved is not None
    assert saved.is_visible is True
    assert saved.visibility_removed_at is None
    assert saved.status is SessionStatus.DRAFT
    assert saved.current_run_id is None
    assert publication is not None
    assert publication.pending_session_id == "session-1"
    assert audit.records[-1]["action"] == "session.delete"
    assert audit.records[-1]["result"] is AuditResult.BLOCKED


def test_delete_session_requires_runtime_truth_when_current_run_id_is_set(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    manager = build_manager(tmp_path)
    seed_session(
        manager,
        session_status=SessionStatus.RUNNING,
        current_run_id="run-active",
    )

    with manager.session(DatabaseRole.CONTROL) as control_session:
        service = SessionService(
            control_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        )
        with pytest.raises(SessionServiceError) as unavailable:
            service.delete_session(
                session_id="session-1",
                trace_context=build_trace(),
            )
        saved = control_session.get(SessionModel, "session-1")

    assert unavailable.value.status_code == 500
    assert unavailable.value.message == (
        "Runtime session is required to verify current run state before deleting "
        "a Session."
    )
    assert saved is not None
    assert saved.is_visible is True
    assert saved.visibility_removed_at is None
    assert saved.status is SessionStatus.RUNNING
    assert saved.current_run_id == "run-active"


def test_delete_session_allows_terminal_current_run_tail_and_keeps_runtime_fact(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    seed_session(
        manager,
        session_status=SessionStatus.FAILED,
        current_run_id="run-failed",
        run_status=RunStatus.FAILED,
    )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        result = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).delete_session(
            session_id="session-1",
            trace_context=build_trace(),
        )
        saved = control_session.get(SessionModel, "session-1")
        run = runtime_session.get(PipelineRunModel, "run-failed")

    assert result.visibility_removed is True
    assert result.blocked_by_active_run is False
    assert saved is not None
    assert saved.status is SessionStatus.FAILED
    assert saved.current_run_id == "run-failed"
    assert run is not None
    assert run.status is RunStatus.FAILED


def test_delete_session_rejects_missing_or_already_removed_session(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    manager = build_manager(tmp_path)
    seed_session(manager, is_visible=False)
    audit = RecordingAuditService()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        service = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=audit,
            now=lambda: LATER,
        )
        with pytest.raises(SessionServiceError) as already_removed:
            service.delete_session(
                session_id="session-1",
                trace_context=build_trace(),
            )
        with pytest.raises(SessionServiceError) as missing:
            service.delete_session(
                session_id="session-missing",
                trace_context=build_trace(),
            )

    assert already_removed.value.status_code == 409
    assert already_removed.value.message == (
        "Session was already removed from product history."
    )
    assert missing.value.status_code == 404
    assert missing.value.message == "Session was not found."
    assert [record["action"] for record in audit.records] == [
        "session.delete.rejected",
        "session.delete.rejected",
    ]
