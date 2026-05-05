from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeLimitSnapshotModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    SseEventType,
    StageStatus,
    StageType,
)
from backend.app.domain.runtime_refs import (
    CheckpointRef,
    GraphInterruptRef,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeCommandResult,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.feed import SystemStatusFeedEntry
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
from backend.app.services.runs import RunLifecycleService, RunLifecycleServiceError


NOW = datetime(2026, 5, 3, 16, 0, 0, tzinfo=UTC)


class RerunTestDatabaseManager:
    def __init__(self, root: Path) -> None:
        self._engines = {
            role: create_engine(
                f"sqlite:///{root / f'{role.value}.sqlite'}",
                future=True,
            )
            for role in DatabaseRole
        }
        for role, metadata in ROLE_METADATA.items():
            metadata.create_all(self._engines[role])
        self._sessionmakers = {
            role: sessionmaker(bind=engine, expire_on_commit=False, future=True)
            for role, engine in self._engines.items()
        }

    @contextmanager
    def session(self, role: DatabaseRole) -> Iterator[Session]:
        session = self.open_session(role)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def open_session(self, role: DatabaseRole) -> Session:
        return self._sessionmakers[role]()


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_failed_command", **kwargs})
        return object()


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FailingEventCommitSession:
    def __init__(self, inner: Session) -> None:
        self._inner = inner
        self.commit_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def commit(self) -> None:
        self.commit_calls += 1
        raise RuntimeError("event commit failed")


class FailingControlCommitSession:
    def __init__(self, inner: Session) -> None:
        self._inner = inner
        self.commit_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def commit(self) -> None:
        self.commit_calls += 1
        raise RuntimeError("control commit failed")


class FakeCheckpointPort:
    def save_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        raise AssertionError("save_checkpoint is not used in rerun tests")

    def load_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        raise AssertionError("load_checkpoint is not used in rerun tests")


class FakeRuntimePort:
    def __init__(
        self,
        *,
        terminal_status: GraphThreadStatus = GraphThreadStatus.TERMINATED,
        fail_on_terminal_check: bool = False,
    ) -> None:
        self.terminal_status = terminal_status
        self.fail_on_terminal_check = fail_on_terminal_check
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        raise AssertionError("create_interrupt is not used in rerun tests")

    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_interrupt is not used in rerun tests")

    def resume_tool_confirmation(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_tool_confirmation is not used in rerun tests")

    def pause_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("pause_thread is not used in rerun tests")

    def resume_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_thread is not used in rerun tests")

    def terminate_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("terminate_thread is not used in rerun tests")

    def assert_thread_terminal(self, **kwargs: Any) -> GraphThreadRef:
        self.calls.append(("assert_thread_terminal", kwargs))
        if self.fail_on_terminal_check:
            raise RuntimeError("terminal check failed")
        thread = kwargs["thread"]
        return thread.model_copy(update={"status": self.terminal_status})


def build_manager(tmp_path: Path) -> RerunTestDatabaseManager:
    return RerunTestDatabaseManager(tmp_path)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-rerun",
        trace_id="trace-rerun-command",
        correlation_id="correlation-rerun",
        span_id="root-span",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def build_service(
    manager: RerunTestDatabaseManager,
    *,
    runtime_port: FakeRuntimePort | None = None,
    audit_service: RecordingAuditService | None = None,
    log_writer: RecordingRunLogWriter | None = None,
    control_session: Session | None = None,
    runtime_session: Session | None = None,
    event_session: Session | None = None,
) -> tuple[
    RunLifecycleService,
    FakeRuntimePort,
    RecordingAuditService,
    RecordingRunLogWriter,
]:
    resolved_runtime_port = runtime_port or FakeRuntimePort()
    resolved_audit_service = audit_service or RecordingAuditService()
    resolved_log_writer = log_writer or RecordingRunLogWriter()
    service = RunLifecycleService(
        control_session=control_session or manager.open_session(DatabaseRole.CONTROL),
        runtime_session=runtime_session or manager.open_session(DatabaseRole.RUNTIME),
        event_session=event_session or manager.open_session(DatabaseRole.EVENT),
        runtime_orchestration=RuntimeOrchestrationService(
            runtime_port=resolved_runtime_port,
            checkpoint_port=FakeCheckpointPort(),
            clock=lambda: NOW,
        ),
        audit_service=resolved_audit_service,
        log_writer=resolved_log_writer,
        now=lambda: NOW,
    )
    return service, resolved_runtime_port, resolved_audit_service, resolved_log_writer


def seed_rerunnable_session(
    manager: RerunTestDatabaseManager,
    *,
    run_status: RunStatus,
    session_status: SessionStatus,
    stage_status: StageStatus,
    current_run_id: str | None = "run-1",
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Rerun Project",
                root_path="C:/repo/rerun-project",
                default_delivery_channel_id=None,
                is_default=True,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            SessionModel(
                session_id="session-1",
                project_id="project-1",
                display_name="Rerun session",
                status=session_status,
                selected_template_id="template-1",
                current_run_id=current_run_id,
                latest_stage_type=StageType.CODE_GENERATION,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limits-1",
                    run_id="run-1",
                    agent_limits={},
                    context_limits={},
                    source_config_version="test",
                    hard_limits_version="test",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-policy-1",
                    run_id="run-1",
                    provider_call_policy={},
                    source_config_version="test",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
                PipelineRunModel(
                    run_id="run-1",
                    session_id="session-1",
                    project_id="project-1",
                    attempt_index=1,
                    status=run_status,
                    trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                    template_snapshot_ref="template-snapshot-1",
                    graph_definition_ref="graph-definition-1",
                    graph_thread_ref="thread-1",
                    workspace_ref="workspace-1",
                    runtime_limit_snapshot_ref="runtime-limits-1",
                    provider_call_policy_snapshot_ref="provider-policy-1",
                    delivery_channel_snapshot_ref=None,
                    current_stage_run_id="stage-run-1",
                    trace_id="trace-old",
                    started_at=NOW,
                    ended_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                StageRunModel(
                    stage_run_id="stage-run-1",
                    run_id="run-1",
                    stage_type=StageType.CODE_GENERATION,
                    status=stage_status,
                    attempt_index=1,
                    graph_node_key="code_generation.main",
                    stage_contract_ref="stage-contract-code-generation",
                    input_ref=None,
                    output_ref=None,
                    summary="Terminal stage.",
                    started_at=NOW,
                    ended_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )


def seed_terminal_system_status(
    manager: RerunTestDatabaseManager,
    *,
    status: RunStatus = RunStatus.TERMINATED,
) -> None:
    with manager.session(DatabaseRole.EVENT) as session:
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


def test_create_rerun_creates_new_run_updates_session_and_appends_run_created_and_session_status_events(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
    )
    seed_terminal_system_status(manager)
    service, runtime_port, audit, log_writer = build_service(manager)

    result = service.create_rerun(
        session_id="session-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.session.current_run_id == result.run.run_id
    assert result.session.status is SessionStatus.RUNNING
    assert result.session.latest_stage_type is StageType.REQUIREMENT_ANALYSIS
    assert result.stage is None
    assert result.run.run_id != "run-1"
    assert result.run.attempt_index == 2
    assert result.run.status is RunStatus.RUNNING
    assert result.run.trigger_source is RunTriggerSource.RETRY
    assert result.run.graph_thread_ref != "thread-1"
    assert result.run.trace_id != "trace-old"
    assert result.run.template_snapshot_ref == "template-snapshot-1"
    assert result.run.graph_definition_ref == "graph-definition-1"
    assert result.run.workspace_ref == "workspace-1"
    assert result.run.runtime_limit_snapshot_ref == "runtime-limits-1"
    assert result.run.provider_call_policy_snapshot_ref == "provider-policy-1"
    assert runtime_port.calls[-1][0] == "assert_thread_terminal"
    assert audit.records[0]["action"] == "runtime.rerun"
    assert [record.message for record in log_writer.records] == [
        "Run rerun command accepted.",
        "Run rerun command completed.",
    ]
    with manager.session(DatabaseRole.RUNTIME) as session:
        runs = (
            session.query(PipelineRunModel)
            .filter(PipelineRunModel.session_id == "session-1")
            .order_by(PipelineRunModel.attempt_index.asc())
            .all()
        )
        assert [row.run_id for row in runs] == ["run-1", result.run.run_id]
        assert runs[0].status is RunStatus.TERMINATED
        assert runs[1].status is RunStatus.RUNNING
        assert runs[1].current_stage_run_id is None
    with manager.session(DatabaseRole.EVENT) as session:
        created = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.PIPELINE_RUN_CREATED)
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        changed = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SESSION_STATUS_CHANGED)
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert created is not None
        assert created.payload["run"]["run_id"] == result.run.run_id
        assert created.payload["run"]["attempt_index"] == 2
        assert created.payload["run"]["trigger_source"] == "retry"
        assert created.payload["run"]["current_stage_type"] == "requirement_analysis"
        assert created.payload["run"]["is_active"] is True
        assert changed is not None
        assert changed.payload["current_run_id"] == result.run.run_id
        assert changed.payload["status"] == "running"
        assert changed.payload["current_stage_type"] == "requirement_analysis"


def test_create_rerun_accepts_failed_current_run_tail(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.FAILED,
        session_status=SessionStatus.FAILED,
        stage_status=StageStatus.FAILED,
    )
    seed_terminal_system_status(manager, status=RunStatus.FAILED)
    service, runtime_port, _audit, _log_writer = build_service(
        manager,
        runtime_port=FakeRuntimePort(terminal_status=GraphThreadStatus.FAILED),
    )

    result = service.create_rerun(
        session_id="session-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.run.status is RunStatus.RUNNING
    assert result.run.trigger_source is RunTriggerSource.RETRY
    assert result.run.attempt_index == 2
    assert result.session.status is SessionStatus.RUNNING
    assert runtime_port.calls[-1][0] == "assert_thread_terminal"
    with manager.session(DatabaseRole.EVENT) as session:
        events = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SYSTEM_STATUS)
            .order_by(DomainEventModel.sequence_index.asc())
            .all()
        )
        assert len(events) == 2
        assert events[0].payload["system_status"]["status"] == "failed"
        assert events[0].payload["system_status"]["retry_action"] is None
        assert events[1].payload["system_status"]["status"] == "failed"
        assert events[1].payload["system_status"]["retry_action"] == "retry:run-1"


def test_build_rerun_trigger_metadata_returns_retry_machine_value_and_old_new_links(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    service, _runtime_port, _audit, _log_writer = build_service(manager)
    old_run = PipelineRunModel(
        run_id="run-1",
        session_id="session-1",
        project_id="project-1",
        attempt_index=1,
        status=RunStatus.TERMINATED,
        trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
        template_snapshot_ref="template-snapshot-1",
        graph_definition_ref="graph-definition-1",
        graph_thread_ref="thread-1",
        workspace_ref="workspace-1",
        runtime_limit_snapshot_ref="runtime-limits-1",
        provider_call_policy_snapshot_ref="provider-policy-1",
        delivery_channel_snapshot_ref=None,
        current_stage_run_id="stage-run-1",
        trace_id="trace-old",
        started_at=NOW,
        ended_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    new_run = PipelineRunModel(
        run_id="run-2",
        session_id="session-1",
        project_id="project-1",
        attempt_index=2,
        status=RunStatus.RUNNING,
        trigger_source=RunTriggerSource.RETRY,
        template_snapshot_ref="template-snapshot-1",
        graph_definition_ref="graph-definition-1",
        graph_thread_ref="thread-2",
        workspace_ref="workspace-1",
        runtime_limit_snapshot_ref="runtime-limits-1",
        provider_call_policy_snapshot_ref="provider-policy-1",
        delivery_channel_snapshot_ref=None,
        current_stage_run_id=None,
        trace_id="trace-new",
        started_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )

    metadata = service.build_rerun_trigger_metadata(
        old_run=old_run,
        new_run=new_run,
        old_trace_id="trace-old",
    )

    assert metadata == {
        "trigger_source": "retry",
        "source_run_id": "run-1",
        "new_run_id": "run-2",
        "source_attempt_index": 1,
        "attempt_index": 2,
        "source_trace_id": "trace-old",
        "trace_id": "trace-new",
    }


def test_create_rerun_appends_terminal_system_status_retry_action_for_current_tail(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
    )
    seed_terminal_system_status(manager)
    service, _runtime_port, _audit, _log_writer = build_service(manager)

    service.create_rerun(
        session_id="session-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.EVENT) as session:
        events = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SYSTEM_STATUS)
            .order_by(DomainEventModel.sequence_index.asc())
            .all()
        )
        assert len(events) == 2
        assert events[0].payload["system_status"]["run_id"] == "run-1"
        assert events[0].payload["system_status"]["retry_action"] is None
        assert events[1].payload["system_status"]["run_id"] == "run-1"
        assert events[1].payload["system_status"]["retry_action"] == "retry:run-1"


def test_create_rerun_rejects_non_terminal_or_completed_current_run(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    service, runtime_port, audit, log_writer = build_service(manager)

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.create_rerun(
            session_id="session-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.RUN_COMMAND_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert runtime_port.calls == []
    assert audit.records[0]["method"] == "record_rejected_command"
    assert log_writer.records[-1].message == "Run rerun command rejected."


def test_create_rerun_rejects_session_without_current_run_tail(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
        current_run_id=None,
    )
    service, _runtime_port, audit, log_writer = build_service(manager)

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.create_rerun(
            session_id="session-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.RUN_COMMAND_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert "existing current run tail" in str(exc_info.value)
    assert audit.records[-1]["method"] == "record_rejected_command"
    assert audit.records[-1]["action"] == "runtime.rerun.rejected"
    assert audit.records[-1]["target_type"] == "session"
    assert audit.records[-1]["target_id"] == "session-1"
    assert log_writer.records[-1].message == "Run rerun command rejected."


def test_create_rerun_allows_terminal_current_run_tail_without_stage_row(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
    )
    seed_terminal_system_status(manager)
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert run is not None
        assert stage is not None
        run.current_stage_run_id = None
        session.add(run)
        session.delete(stage)
    service, runtime_port, audit, log_writer = build_service(manager)

    result = service.create_rerun(
        session_id="session-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.run.run_id != "run-1"
    assert result.run.trigger_source is RunTriggerSource.RETRY
    assert runtime_port.calls[-1][0] == "assert_thread_terminal"
    assert audit.records[0]["action"] == "runtime.rerun"
    assert [record.message for record in log_writer.records] == [
        "Run rerun command accepted.",
        "Run rerun command completed.",
    ]


def test_create_rerun_rejects_when_runtime_boundary_reports_non_terminal_old_thread(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
    )
    runtime_port = FakeRuntimePort(terminal_status=GraphThreadStatus.RUNNING)
    service, _runtime_port, audit, log_writer = build_service(
        manager,
        runtime_port=runtime_port,
    )

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.create_rerun(
            session_id="session-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.RUN_COMMAND_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert audit.records[-1]["method"] == "record_rejected_command"
    assert audit.records[-1]["action"] == "runtime.rerun.rejected"
    assert "runtime.rerun" not in [record["action"] for record in audit.records]
    assert all(record["method"] != "record_failed_command" for record in audit.records)
    assert log_writer.records[-1].message == "Run rerun command rejected."
    assert "Run rerun command accepted." not in [
        record.message for record in log_writer.records
    ]
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(PipelineRunModel).count() == 1


def test_create_rerun_rolls_back_new_run_when_terminal_check_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
    )
    seed_terminal_system_status(manager)
    runtime_port = FakeRuntimePort(fail_on_terminal_check=True)
    service, _runtime_port, _audit, _log_writer = build_service(
        manager,
        runtime_port=runtime_port,
    )

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.create_rerun(
            session_id="session-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(PipelineRunModel).count() == 1
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 1


def test_create_rerun_compensates_new_run_when_event_commit_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
    )
    seed_terminal_system_status(manager)
    control_session = manager.open_session(DatabaseRole.CONTROL)
    runtime_session = manager.open_session(DatabaseRole.RUNTIME)
    event_session = FailingEventCommitSession(manager.open_session(DatabaseRole.EVENT))
    service, _runtime_port, audit, log_writer = build_service(
        manager,
        control_session=control_session,
        runtime_session=runtime_session,
        event_session=event_session,
    )

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.create_rerun(
            session_id="session-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    assert audit.records[0]["action"] == "runtime.rerun"
    assert audit.records[-1]["action"] == "runtime.rerun.failed"
    assert [record.message for record in log_writer.records] == [
        "Run rerun command accepted.",
        "Run rerun command failed.",
    ]
    with manager.session(DatabaseRole.CONTROL) as session:
        control = session.get(SessionModel, "session-1")
        assert control is not None
        assert control.current_run_id == "run-1"
        assert control.status is SessionStatus.TERMINATED
        assert control.latest_stage_type is StageType.CODE_GENERATION
    with manager.session(DatabaseRole.RUNTIME) as session:
        runs = (
            session.query(PipelineRunModel)
            .filter(PipelineRunModel.session_id == "session-1")
            .order_by(PipelineRunModel.attempt_index.asc())
            .all()
        )
        assert [row.run_id for row in runs] == ["run-1"]
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 1


def test_create_rerun_compensates_partial_state_when_control_commit_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_rerunnable_session(
        manager,
        run_status=RunStatus.TERMINATED,
        session_status=SessionStatus.TERMINATED,
        stage_status=StageStatus.TERMINATED,
    )
    seed_terminal_system_status(manager)
    control_session = FailingControlCommitSession(manager.open_session(DatabaseRole.CONTROL))
    runtime_session = manager.open_session(DatabaseRole.RUNTIME)
    event_session = manager.open_session(DatabaseRole.EVENT)
    service, _runtime_port, audit, log_writer = build_service(
        manager,
        control_session=control_session,
        runtime_session=runtime_session,
        event_session=event_session,
    )

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.create_rerun(
            session_id="session-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    assert audit.records[0]["action"] == "runtime.rerun"
    assert audit.records[-1]["action"] == "runtime.rerun.failed"
    assert [record.message for record in log_writer.records] == [
        "Run rerun command accepted.",
        "Run rerun command failed.",
    ]
    with manager.session(DatabaseRole.CONTROL) as session:
        control = session.get(SessionModel, "session-1")
        assert control is not None
        assert control.current_run_id == "run-1"
        assert control.status is SessionStatus.TERMINATED
        assert control.latest_stage_type is StageType.CODE_GENERATION
    with manager.session(DatabaseRole.RUNTIME) as session:
        runs = (
            session.query(PipelineRunModel)
            .filter(PipelineRunModel.session_id == "session-1")
            .order_by(PipelineRunModel.attempt_index.asc())
            .all()
        )
        assert [row.run_id for row in runs] == ["run-1"]
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 1
