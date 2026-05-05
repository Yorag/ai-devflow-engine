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
    ApprovalRequestModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeLimitSnapshotModel,
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
    GraphThreadStatus,
    RuntimeCommandResult,
    RuntimeCommandType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.feed import ApprovalRequestFeedEntry, ToolConfirmationFeedEntry
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
from backend.app.services.runs import (
    RunLifecycleService,
    RunLifecycleServiceError,
    TerminalStatusProjector,
)
from backend.app.services.tool_confirmations import ToolConfirmationService


NOW = datetime(2026, 5, 3, 15, 0, 0, tzinfo=UTC)


class TerminateTestDatabaseManager:
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


class FailingToolConfirmationCancelAuditService(RecordingAuditService):
    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        if kwargs["action"] == "tool_confirmation.cancel":
            raise RuntimeError("tool confirmation cancel audit failed")
        return object()


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FakeCheckpointPort:
    def save_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        raise AssertionError("save_checkpoint is not used in terminate tests")

    def load_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        raise AssertionError("load_checkpoint is not used in terminate tests")


class FakeRuntimePort:
    def __init__(self, *, fail_on_terminate: bool = False) -> None:
        self.fail_on_terminate = fail_on_terminate
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        raise AssertionError("create_interrupt is not used in terminate tests")

    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_interrupt is not used in terminate tests")

    def resume_tool_confirmation(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError(
            "resume_tool_confirmation is not used in terminate tests"
        )

    def pause_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("pause_thread is not used in terminate tests")

    def resume_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_thread is not used in terminate tests")

    def terminate_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("terminate_thread", kwargs))
        if self.fail_on_terminate:
            raise RuntimeError("runtime terminate failed")
        thread = kwargs["thread"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.TERMINATE_THREAD,
            thread=thread.model_copy(update={"status": GraphThreadStatus.TERMINATED}),
            checkpoint_ref=None,
            trace_context=kwargs["trace_context"],
        )

    def assert_thread_terminal(self, **kwargs: Any) -> GraphThreadRef:
        raise AssertionError("assert_thread_terminal is not used in terminate tests")


def build_manager(tmp_path: Path) -> TerminateTestDatabaseManager:
    return TerminateTestDatabaseManager(tmp_path)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-terminate",
        trace_id="trace-terminate",
        correlation_id="correlation-terminate",
        span_id="root-span",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def build_service(
    manager: TerminateTestDatabaseManager,
    *,
    runtime_port: FakeRuntimePort | None = None,
    audit_service: RecordingAuditService | None = None,
    log_writer: RecordingRunLogWriter | None = None,
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
        control_session=manager.open_session(DatabaseRole.CONTROL),
        runtime_session=manager.open_session(DatabaseRole.RUNTIME),
        event_session=manager.open_session(DatabaseRole.EVENT),
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


def seed_active_run(
    manager: TerminateTestDatabaseManager,
    *,
    run_status: RunStatus,
    session_status: SessionStatus,
    stage_status: StageStatus,
    with_pending_approval: bool = False,
    with_pending_tool_confirmation: bool = False,
    current_run_id: str = "run-1",
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Terminate Project",
                root_path="C:/repo/terminate-project",
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
                display_name="Terminate session",
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
                    trace_id="trace-terminate",
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
                    reason=(
                        "The command deletes files and requires explicit confirmation."
                    ),
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
    manager: TerminateTestDatabaseManager,
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
    manager: TerminateTestDatabaseManager,
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


def test_terminate_running_run_marks_run_stage_and_session_terminated_and_appends_system_status(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    service, runtime_port, audit, log_writer = build_service(manager)

    result = service.terminate_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.run.status is RunStatus.TERMINATED
    assert result.session.status is SessionStatus.TERMINATED
    assert result.stage.status is StageStatus.TERMINATED
    assert runtime_port.calls[-1][0] == "terminate_thread"
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.TERMINATED
        assert control_session.current_run_id == "run-1"
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert run is not None and run.status is RunStatus.TERMINATED
        assert stage is not None and stage.status is StageStatus.TERMINATED
        assert run.ended_at == NOW.replace(tzinfo=None)
        assert stage.ended_at == NOW.replace(tzinfo=None)
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SYSTEM_STATUS)
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert event is not None
        assert event.payload["system_status"]["status"] == "terminated"
        assert event.payload["system_status"]["retry_action"] == "retry:run-1"
    assert [record["action"] for record in audit.records] == ["runtime.terminate"]
    assert [record.message for record in log_writer.records] == [
        "Run terminate command accepted.",
        "Run terminate completed.",
    ]


def test_terminate_waiting_approval_refreshes_pending_approval_as_non_actionable(
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
    service, _runtime_port, _audit, _log_writer = build_service(manager)

    service.terminate_run(
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
        assert event.payload["approval_request"]["is_actionable"] is False
        assert "terminated" in event.payload["approval_request"]["disabled_reason"]


def test_terminate_paused_run_with_pending_approval_refreshes_approval_to_terminated_history(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
        stage_status=StageStatus.WAITING_APPROVAL,
        with_pending_approval=True,
    )
    seed_latest_approval_request_event(manager)
    service, _runtime_port, _audit, _log_writer = build_service(manager)

    service.terminate_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

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
        assert "terminated" in approval_request["disabled_reason"]


def test_terminate_waiting_tool_confirmation_cancels_pending_confirmation_without_allow_or_deny_event(
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
    service, _runtime_port, audit, _log_writer = build_service(manager)

    service.terminate_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, "tool-confirmation-1")
        assert request is not None
        assert request.status is ToolConfirmationStatus.CANCELLED
        assert request.user_decision is None
        assert request.responded_at == NOW.replace(tzinfo=None)
        assert request.updated_at == NOW.replace(tzinfo=None)
    with manager.session(DatabaseRole.EVENT) as session:
        events = session.query(DomainEventModel).all()
        types = [event.event_type for event in events]
        assert SseEventType.TOOL_CONFIRMATION_REQUESTED in types
        assert SseEventType.SYSTEM_STATUS in types
        assert SseEventType.TOOL_CONFIRMATION_RESULT not in types
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
        assert tool_confirmation["status"] == "cancelled"
        assert tool_confirmation["is_actionable"] is False
        assert tool_confirmation["decision"] is None
    assert "tool_confirmation.cancel" in [record["action"] for record in audit.records]


def test_terminate_uses_tool_confirmation_service_cancel_without_early_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.WAITING_TOOL_CONFIRMATION,
        session_status=SessionStatus.WAITING_TOOL_CONFIRMATION,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
        with_pending_tool_confirmation=True,
    )
    calls: list[dict[str, Any]] = []
    original_cancel = ToolConfirmationService.cancel_for_terminal_run

    def recording_cancel(self: ToolConfirmationService, **kwargs: Any):
        calls.append(kwargs)
        return original_cancel(self, **kwargs)

    monkeypatch.setattr(
        ToolConfirmationService,
        "cancel_for_terminal_run",
        recording_cancel,
    )
    service, _runtime_port, _audit, _log_writer = build_service(manager)

    service.terminate_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert calls == [
        {
            "run_id": "run-1",
            "trace_context": calls[0]["trace_context"],
            "commit": False,
        }
    ]
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, "tool-confirmation-1")
        assert request is not None
        assert request.status is ToolConfirmationStatus.CANCELLED


def test_terminate_rolls_back_tool_confirmation_and_terminal_state_when_cancel_audit_fails(
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
    audit = FailingToolConfirmationCancelAuditService()
    service, _runtime_port, _audit, log_writer = build_service(
        manager,
        audit_service=audit,
    )

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.terminate_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.WAITING_TOOL_CONFIRMATION
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        request = session.get(ToolConfirmationRequestModel, "tool-confirmation-1")
        assert run is not None and run.status is RunStatus.WAITING_TOOL_CONFIRMATION
        assert stage is not None and stage.status is StageStatus.WAITING_TOOL_CONFIRMATION
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.responded_at is None
    with manager.session(DatabaseRole.EVENT) as session:
        events = session.query(DomainEventModel).all()
        assert len(events) == 1
        assert events[0].event_type is SseEventType.TOOL_CONFIRMATION_REQUESTED
    assert audit.records[-1]["action"] == "runtime.terminate.failed"
    assert log_writer.records[-1].message == "Run terminate failed."


def test_terminal_status_projector_appends_failed_system_status_payload_for_current_tail(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.FAILED,
        session_status=SessionStatus.FAILED,
        stage_status=StageStatus.FAILED,
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        with manager.session(DatabaseRole.EVENT) as event_session:
            TerminalStatusProjector(
                events=EventStore(event_session, now=lambda: NOW),
                now=lambda: NOW,
            ).append_terminal_system_status(
                domain_event_type=DomainEventType.RUN_FAILED,
                run=run,
                title="Run failed",
                reason="Runtime failed.",
                is_current_tail=True,
                trace_context=build_trace(),
                occurred_at=NOW,
            )

    with manager.session(DatabaseRole.EVENT) as session:
        event = session.query(DomainEventModel).one()
        assert event.event_type is SseEventType.SYSTEM_STATUS
        assert event.payload["system_status"]["status"] == "failed"
        assert event.payload["system_status"]["retry_action"] == "retry:run-1"


def test_terminal_status_projector_leaves_retry_action_unset_without_current_tail_flag(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.FAILED,
        session_status=SessionStatus.FAILED,
        stage_status=StageStatus.FAILED,
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        with manager.session(DatabaseRole.EVENT) as event_session:
            TerminalStatusProjector(
                events=EventStore(event_session, now=lambda: NOW),
                now=lambda: NOW,
            ).append_terminal_system_status(
                domain_event_type=DomainEventType.RUN_FAILED,
                run=run,
                title="Run failed",
                reason="Runtime failed.",
                trace_context=build_trace(),
                occurred_at=NOW,
            )

    with manager.session(DatabaseRole.EVENT) as session:
        event = session.query(DomainEventModel).one()
        assert event.event_type is SseEventType.SYSTEM_STATUS
        assert event.payload["system_status"]["status"] == "failed"
        assert event.payload["system_status"]["retry_action"] is None


def test_terminate_paused_run_is_allowed_and_uses_paused_thread_ref(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
        stage_status=StageStatus.RUNNING,
    )
    service, runtime_port, _audit, _log_writer = build_service(manager)

    result = service.terminate_run(
        run_id="run-1",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert runtime_port.calls[-1][1]["thread"].status is GraphThreadStatus.PAUSED
    assert result.run.status is RunStatus.TERMINATED


@pytest.mark.parametrize(
    ("run_status", "session_status", "stage_status"),
    [
        (RunStatus.COMPLETED, SessionStatus.COMPLETED, StageStatus.COMPLETED),
        (RunStatus.FAILED, SessionStatus.FAILED, StageStatus.FAILED),
        (RunStatus.TERMINATED, SessionStatus.TERMINATED, StageStatus.TERMINATED),
    ],
)
def test_terminate_rejects_terminal_runs_without_mutation(
    tmp_path: Path,
    run_status: RunStatus,
    session_status: SessionStatus,
    stage_status: StageStatus,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=run_status,
        session_status=session_status,
        stage_status=stage_status,
    )
    service, runtime_port, audit, log_writer = build_service(manager)

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.terminate_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.RUN_COMMAND_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert runtime_port.calls == []
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert run is not None and run.status is run_status
        assert stage is not None and stage.status is stage_status
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert audit.records[0]["action"] == "runtime.terminate.rejected"
    assert log_writer.records[-1].message == "Run terminate command rejected."


def test_terminate_rejects_non_current_run_without_mutation(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
        current_run_id="run-stale",
    )
    service, runtime_port, _audit, _log_writer = build_service(manager)

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.terminate_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.RUN_COMMAND_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert runtime_port.calls == []
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert run is not None and run.status is RunStatus.RUNNING
        assert stage is not None and stage.status is StageStatus.RUNNING
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_terminate_rolls_back_terminal_state_when_runtime_terminate_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_active_run(
        manager,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    runtime_port = FakeRuntimePort(fail_on_terminate=True)
    service, _runtime_port, audit, log_writer = build_service(
        manager,
        runtime_port=runtime_port,
    )

    with pytest.raises(RunLifecycleServiceError) as exc_info:
        service.terminate_run(
            run_id="run-1",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.RUNNING
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert run is not None and run.status is RunStatus.RUNNING
        assert stage is not None and stage.status is StageStatus.RUNNING
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert audit.records[-1]["action"] == "runtime.terminate.failed"
    assert log_writer.records[-1].message == "Run terminate failed."
