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
from backend.app.db.base import DatabaseRole, ROLE_METADATA
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    SseEventType,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.domain.runtime_refs import (
    CheckpointRef,
    GraphInterruptRef,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeCommandResult,
    RuntimeCommandType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.feed import ApprovalRequestFeedEntry, ToolConfirmationFeedEntry
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
from backend.app.services.runs import RunLifecycleService, RunLifecycleServiceError


NOW = datetime(2026, 5, 3, 14, 0, 0, tzinfo=UTC)


class PauseResumeTestDatabaseManager:
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


class FakeCheckpointPort:
    def __init__(self, *, fail_on_save: bool = False) -> None:
        self.fail_on_save = fail_on_save
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def save_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        self.calls.append(("save_checkpoint", kwargs))
        if self.fail_on_save:
            raise RuntimeError("checkpoint save failed")
        thread = kwargs["thread"]
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{kwargs['purpose'].value}-{thread.thread_id}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=kwargs.get("stage_run_id"),
            stage_type=kwargs.get("stage_type"),
            purpose=kwargs["purpose"],
            workspace_snapshot_ref=kwargs.get("workspace_snapshot_ref"),
            payload_ref=kwargs.get("payload_ref"),
        )

    def load_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        self.calls.append(("load_checkpoint", kwargs))
        return kwargs["checkpoint"]


class FakeRuntimePort:
    def __init__(
        self,
        *,
        fail_on_pause: bool = False,
        fail_on_resume: bool = False,
    ) -> None:
        self.fail_on_pause = fail_on_pause
        self.fail_on_resume = fail_on_resume
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        raise AssertionError("create_interrupt is not used in pause/resume tests")

    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_interrupt is not used in pause/resume tests")

    def resume_tool_confirmation(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError(
            "resume_tool_confirmation is not used in pause/resume tests"
        )

    def pause_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("pause_thread", kwargs))
        if self.fail_on_pause:
            raise RuntimeError("runtime pause failed")
        thread = kwargs["thread"]
        checkpoint = kwargs["checkpoint"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.PAUSE_THREAD,
            thread=thread.model_copy(
                update={
                    "status": GraphThreadStatus.PAUSED,
                    "checkpoint_id": checkpoint.checkpoint_id,
                }
            ),
            checkpoint_ref=checkpoint,
            trace_context=kwargs["trace_context"],
        )

    def resume_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_thread", kwargs))
        if self.fail_on_resume:
            raise RuntimeError("runtime resume failed")
        thread = kwargs["thread"]
        checkpoint = kwargs["checkpoint"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_THREAD,
            thread=thread.model_copy(
                update={
                    "status": GraphThreadStatus.RUNNING,
                    "checkpoint_id": checkpoint.checkpoint_id,
                }
            ),
            checkpoint_ref=checkpoint,
            trace_context=kwargs["trace_context"],
        )

    def terminate_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("terminate_thread is not used in pause/resume tests")

    def assert_thread_terminal(self, **kwargs: Any) -> GraphThreadRef:
        raise AssertionError("assert_thread_terminal is not used in pause/resume tests")


def build_manager(tmp_path: Path) -> PauseResumeTestDatabaseManager:
    return PauseResumeTestDatabaseManager(tmp_path)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-pause-resume",
        trace_id="trace-pause-resume",
        correlation_id="correlation-pause-resume",
        span_id="root-span",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def build_service(
    manager: PauseResumeTestDatabaseManager,
    *,
    runtime_port: FakeRuntimePort | None = None,
    checkpoint_port: FakeCheckpointPort | None = None,
    audit_service: RecordingAuditService | None = None,
    log_writer: RecordingRunLogWriter | None = None,
) -> tuple[
    RunLifecycleService,
    FakeRuntimePort,
    FakeCheckpointPort,
    RecordingAuditService,
    RecordingRunLogWriter,
]:
    resolved_runtime_port = runtime_port or FakeRuntimePort()
    resolved_checkpoint_port = checkpoint_port or FakeCheckpointPort()
    resolved_audit_service = audit_service or RecordingAuditService()
    resolved_log_writer = log_writer or RecordingRunLogWriter()
    service = RunLifecycleService(
        control_session=manager.open_session(DatabaseRole.CONTROL),
        runtime_session=manager.open_session(DatabaseRole.RUNTIME),
        event_session=manager.open_session(DatabaseRole.EVENT),
        runtime_orchestration=RuntimeOrchestrationService(
            runtime_port=resolved_runtime_port,
            checkpoint_port=resolved_checkpoint_port,
            clock=lambda: NOW,
        ),
        audit_service=resolved_audit_service,
        log_writer=resolved_log_writer,
        now=lambda: NOW,
    )
    return (
        service,
        resolved_runtime_port,
        resolved_checkpoint_port,
        resolved_audit_service,
        resolved_log_writer,
    )


def seed_active_run(
    manager: PauseResumeTestDatabaseManager,
    *,
    run_status: RunStatus,
    session_status: SessionStatus,
    stage_status: StageStatus,
    with_pending_approval: bool = False,
    with_pending_tool_confirmation: bool = False,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Pause Resume Project",
                root_path="C:/repo/pause-resume-project",
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
                display_name="Pause resume session",
                status=session_status,
                selected_template_id="template-1",
                current_run_id="run-1",
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
                    trace_id="trace-pause-resume",
                    started_at=NOW,
                    ended_at=None,
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
                    summary="Current stage.",
                    started_at=NOW,
                    ended_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        if with_pending_approval:
            session.add(
                ApprovalRequestModel(
                    approval_id="approval-1",
                    run_id="run-1",
                    stage_run_id="stage-run-1",
                    approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
                    status=ApprovalStatus.PENDING,
                    payload_ref="approval-payload-1",
                    graph_interrupt_ref="interrupt-approval-1",
                    requested_at=NOW,
                    resolved_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        if with_pending_tool_confirmation:
            session.add(
                ToolConfirmationRequestModel(
                    tool_confirmation_id="tool-confirmation-1",
                    run_id="run-1",
                    stage_run_id="stage-run-1",
                    confirmation_object_ref="tool-action-1",
                    tool_name="bash",
                    command_preview="Remove-Item -Recurse build",
                    target_summary="Deletes generated build outputs.",
                    risk_level=ToolRiskLevel.HIGH_RISK,
                    risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE.value],
                    reason="The command deletes files and requires explicit confirmation.",
                    expected_side_effects=["Deletes build outputs."],
                    alternative_path_summary="Keep generated files and stop the run.",
                    user_decision=None,
                    status=ToolConfirmationStatus.PENDING,
                    graph_interrupt_ref="interrupt-tool-confirmation-1",
                    audit_log_ref=None,
                    process_ref=None,
                    requested_at=NOW,
                    responded_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


def seed_latest_approval_request_event(
    manager: PauseResumeTestDatabaseManager,
) -> None:
    with manager.session(DatabaseRole.EVENT) as session:
        projection = ApprovalRequestFeedEntry(
            entry_id="entry-approval-1",
            run_id="run-1",
            occurred_at=NOW,
            approval_id="approval-1",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            status=ApprovalStatus.PENDING,
            title="Review code review result",
            approval_object_excerpt="Review the approval object.",
            risk_excerpt="One risk remains.",
            approval_object_preview={"payload_ref": "approval-payload-1"},
            approve_action="approve",
            reject_action="reject",
            is_actionable=True,
            requested_at=NOW,
            delivery_readiness_status=None,
            delivery_readiness_message=None,
            open_settings_action=None,
            disabled_reason=None,
        )
        EventStore(
            session,
            now=lambda: NOW,
            id_factory=lambda: "event-approval-request",
        ).append(
            DomainEventType.APPROVAL_REQUESTED,
            payload={"approval_request": projection.model_dump(mode="json")},
            trace_context=build_trace(),
        )


def seed_latest_tool_confirmation_event(
    manager: PauseResumeTestDatabaseManager,
) -> None:
    with manager.session(DatabaseRole.EVENT) as session:
        projection = ToolConfirmationFeedEntry(
            entry_id="entry-tool-confirmation-1",
            run_id="run-1",
            occurred_at=NOW,
            stage_run_id="stage-run-1",
            tool_confirmation_id="tool-confirmation-1",
            status=ToolConfirmationStatus.PENDING,
            title="Confirm bash tool action",
            tool_name="bash",
            command_preview="Remove-Item -Recurse build",
            target_summary="Deletes generated build outputs.",
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE],
            reason="The command deletes files and requires explicit confirmation.",
            expected_side_effects=["Deletes build outputs."],
            allow_action="allow:tool-confirmation-1",
            deny_action="deny:tool-confirmation-1",
            is_actionable=True,
            requested_at=NOW,
            responded_at=None,
            decision=None,
            disabled_reason=None,
        )
        EventStore(
            session,
            now=lambda: NOW,
            id_factory=lambda: "event-tool-confirmation-request",
        ).append(
            DomainEventType.TOOL_CONFIRMATION_REQUESTED,
            payload={"tool_confirmation": projection.model_dump(mode="json")},
            trace_context=build_trace(),
        )


def test_pause_running_run_marks_session_and_run_paused_and_persists_recovery_checkpoint(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    service, runtime_port, checkpoint_port, audit, _log_writer = build_service(manager)

    result = service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.run.status is RunStatus.PAUSED
    assert result.session.status is SessionStatus.PAUSED
    assert result.checkpoint_ref is not None
    assert runtime_port.calls[-1][0] == "pause_thread"
    assert checkpoint_port.calls[-1][0] == "save_checkpoint"
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.PAUSED
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        checkpoint_artifact = session.query(StageArtifactModel).one()
        assert run is not None and run.status is RunStatus.PAUSED
        assert stage is not None and stage.status is StageStatus.RUNNING
        assert checkpoint_artifact.artifact_type == "recovery_checkpoint"
        assert checkpoint_artifact.process["run_status_before_pause"] == "running"
        assert checkpoint_artifact.process["session_status_before_pause"] == "running"
        assert checkpoint_artifact.process["stage_status_before_pause"] == "running"
        assert checkpoint_artifact.process["checkpoint"]["checkpoint_id"] == (
            "checkpoint-pause-thread-1"
        )
    with manager.session(DatabaseRole.EVENT) as session:
        event = session.query(DomainEventModel).one()
        assert event.event_type is SseEventType.SESSION_STATUS_CHANGED
        assert event.payload["status"] == "paused"
    assert audit.records[0]["action"] == "runtime.pause"


def test_pause_waiting_approval_refreshes_pending_approval_projection_as_non_actionable(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.WAITING_APPROVAL,
        session_status=SessionStatus.WAITING_APPROVAL,
        stage_status=StageStatus.WAITING_APPROVAL,
        with_pending_approval=True,
    )
    seed_latest_approval_request_event(manager)
    service, _runtime_port, _checkpoint_port, _audit, _log_writer = build_service(manager)

    service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, "approval-1")
        assert approval is not None and approval.status is ApprovalStatus.PENDING
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.APPROVAL_REQUESTED)
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert event is not None
        approval_request = event.payload["approval_request"]
        assert approval_request["is_actionable"] is False
        assert "paused" in approval_request["disabled_reason"]


def test_pause_waiting_tool_confirmation_refreshes_pending_tool_confirmation_as_non_actionable(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.WAITING_TOOL_CONFIRMATION,
        session_status=SessionStatus.WAITING_TOOL_CONFIRMATION,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
        with_pending_tool_confirmation=True,
    )
    seed_latest_tool_confirmation_event(manager)
    service, _runtime_port, _checkpoint_port, _audit, _log_writer = build_service(manager)

    service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, "tool-confirmation-1")
        assert request is not None and request.status is ToolConfirmationStatus.PENDING
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.event_type
                == SseEventType.TOOL_CONFIRMATION_REQUESTED
            )
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert event is not None
        tool_confirmation = event.payload["tool_confirmation"]
        assert tool_confirmation["is_actionable"] is False
        assert "paused" in tool_confirmation["disabled_reason"]


def test_resume_restores_waiting_tool_confirmation_checkpoint_without_creating_new_request(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.WAITING_TOOL_CONFIRMATION,
        session_status=SessionStatus.WAITING_TOOL_CONFIRMATION,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
        with_pending_tool_confirmation=True,
    )
    seed_latest_tool_confirmation_event(manager)
    service, runtime_port, _checkpoint_port, _audit, _log_writer = build_service(manager)
    service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    result = service.resume_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.run.status is RunStatus.WAITING_TOOL_CONFIRMATION
    assert result.session.status is SessionStatus.WAITING_TOOL_CONFIRMATION
    assert runtime_port.calls[-1][0] == "resume_thread"
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, "tool-confirmation-1")
        assert request is not None and request.status is ToolConfirmationStatus.PENDING
        assert session.query(ToolConfirmationRequestModel).count() == 1
        assert session.query(StageArtifactModel).count() == 1
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.event_type
                == SseEventType.TOOL_CONFIRMATION_REQUESTED
            )
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert event is not None
        tool_confirmation = event.payload["tool_confirmation"]
        assert tool_confirmation["is_actionable"] is True
        assert tool_confirmation["disabled_reason"] is None


def test_resume_rejects_non_paused_run(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    service, runtime_port, _checkpoint_port, audit, _log_writer = build_service(manager)

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.resume_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.RUN_COMMAND_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert "paused" in str(exc_info.value)
    assert runtime_port.calls == []
    assert audit.records[0]["method"] == "record_rejected_command"
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None and run.status is RunStatus.RUNNING


def test_pause_rejects_invalid_state_without_mutation(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.COMPLETED,
        session_status=SessionStatus.COMPLETED,
        stage_status=StageStatus.COMPLETED,
    )
    service, runtime_port, _checkpoint_port, audit, log_writer = build_service(manager)

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.pause_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.RUN_COMMAND_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert runtime_port.calls == []
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.COMPLETED
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert run is not None and run.status is RunStatus.COMPLETED
        assert stage is not None and stage.status is StageStatus.COMPLETED
        assert session.query(StageArtifactModel).count() == 0
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert audit.records[0]["action"] == "runtime.pause.rejected"
    assert log_writer.records[-1].message == "Run pause command rejected."


def test_resume_rolls_back_status_events_and_logs_when_runtime_resume_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    runtime_port = FakeRuntimePort()
    service, _runtime_port, _checkpoint_port, audit, log_writer = build_service(
        manager,
        runtime_port=runtime_port,
    )
    service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )
    runtime_port.fail_on_resume = True

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.resume_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.PAUSED
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None and run.status is RunStatus.PAUSED
    with manager.session(DatabaseRole.EVENT) as session:
        events = session.query(DomainEventModel).all()
        assert len(events) == 1
        assert events[0].payload["status"] == "paused"
    assert audit.records[-1]["action"] == "runtime.resume.failed"
    assert log_writer.records[-1].message == "Run resume failed."


def test_resume_restores_waiting_approval_and_refreshes_approval_actionable(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.WAITING_APPROVAL,
        session_status=SessionStatus.WAITING_APPROVAL,
        stage_status=StageStatus.WAITING_APPROVAL,
        with_pending_approval=True,
    )
    seed_latest_approval_request_event(manager)
    service, runtime_port, _checkpoint_port, _audit, log_writer = build_service(manager)
    service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    result = service.resume_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.run.status is RunStatus.WAITING_APPROVAL
    assert result.session.status is SessionStatus.WAITING_APPROVAL
    assert runtime_port.calls[-1][0] == "resume_thread"
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, "approval-1")
        assert approval is not None and approval.status is ApprovalStatus.PENDING
        assert session.query(ApprovalRequestModel).count() == 1
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.APPROVAL_REQUESTED)
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert event is not None
        approval_request = event.payload["approval_request"]
        assert approval_request["is_actionable"] is True
        assert approval_request["disabled_reason"] is None
    assert log_writer.records[-1].message == "Run resume completed."


def test_resume_restores_running_checkpoint(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    service, runtime_port, _checkpoint_port, _audit, _log_writer = build_service(manager)
    service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    result = service.resume_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.run.status is RunStatus.RUNNING
    assert result.session.status is SessionStatus.RUNNING
    assert runtime_port.calls[-1][0] == "resume_thread"
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, "stage-run-1")
        assert stage is not None and stage.status is StageStatus.RUNNING


def test_resume_restores_waiting_clarification_checkpoint(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.WAITING_CLARIFICATION,
        session_status=SessionStatus.WAITING_CLARIFICATION,
        stage_status=StageStatus.WAITING_CLARIFICATION,
    )
    service, runtime_port, _checkpoint_port, _audit, _log_writer = build_service(manager)
    service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    result = service.resume_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.run.status is RunStatus.WAITING_CLARIFICATION
    assert result.session.status is SessionStatus.WAITING_CLARIFICATION
    assert runtime_port.calls[-1][0] == "resume_thread"


def test_resume_rejects_stale_checkpoint_metadata_without_runtime_resume(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    service, runtime_port, _checkpoint_port, audit, _log_writer = build_service(manager)
    service.pause_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        artifact = session.query(StageArtifactModel).one()
        assert run is not None
        process = dict(artifact.process)
        checkpoint = dict(process["checkpoint"])
        checkpoint["thread_id"] = "thread-stale"
        process["checkpoint"] = checkpoint
        artifact.process = process
        run.status = RunStatus.PAUSED

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.resume_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    assert runtime_port.calls[-1][0] == "pause_thread"
    assert audit.records[-1]["action"] == "runtime.resume.failed"


def test_pause_rolls_back_and_raises_stable_service_error_when_checkpoint_save_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    failing_checkpoint = FakeCheckpointPort(fail_on_save=True)
    service, runtime_port, _checkpoint_port, audit, _log_writer = build_service(
        manager,
        checkpoint_port=failing_checkpoint,
    )

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.pause_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail_ref == "run-1"
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.RUNNING
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None and run.status is RunStatus.RUNNING
        assert session.query(StageArtifactModel).count() == 0
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert runtime_port.calls == []
    assert audit.records[-1]["action"] == "runtime.pause.failed"
