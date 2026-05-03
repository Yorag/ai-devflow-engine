from __future__ import annotations

from collections.abc import Callable, Iterator
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
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RunControlRecordModel,
    RuntimeLimitSnapshotModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    RunControlRecordType,
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.domain.runtime_refs import (
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeCommandResult,
    RuntimeCommandType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.observability import AuditActorType
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
from backend.app.services.tool_confirmations import (
    ToolConfirmationService,
    ToolConfirmationServiceError,
)


NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)


class ToolConfirmationTestDatabaseManager:
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


class FailingRequiredAuditService(RecordingAuditService):
    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        raise RuntimeError("required audit unavailable")


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FakeCheckpointPort:
    def save_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        thread = kwargs["thread"]
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{thread.thread_id}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=kwargs.get("stage_run_id"),
            stage_type=kwargs.get("stage_type"),
            purpose=kwargs["purpose"],
            workspace_snapshot_ref=kwargs.get("workspace_snapshot_ref"),
            payload_ref=kwargs.get("payload_ref"),
        )

    def load_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        return kwargs["checkpoint"]


class FakeRuntimePort:
    def __init__(self, *, fail_on_resume: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail_on_resume = fail_on_resume

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        self.calls.append(("create_interrupt", kwargs))
        return GraphInterruptRef(
            interrupt_id="interrupt-tool-confirmation-1",
            thread=kwargs["thread"].model_copy(
                update={"status": GraphThreadStatus.WAITING_TOOL_CONFIRMATION}
            ),
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            status=GraphInterruptStatus.PENDING,
            run_id=kwargs["run_id"],
            stage_run_id=kwargs["stage_run_id"],
            stage_type=kwargs["stage_type"],
            payload_ref=kwargs["payload_ref"],
            tool_confirmation_id=kwargs["tool_confirmation_id"],
            tool_action_ref=kwargs["tool_action_ref"],
            checkpoint_ref=kwargs["checkpoint"],
        )

    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_interrupt is not used for tool confirmations")

    def resume_tool_confirmation(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_tool_confirmation", kwargs))
        if self._fail_on_resume:
            raise RuntimeError("runtime resume failed")
        interrupt = kwargs["interrupt"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_TOOL_CONFIRMATION,
            thread=interrupt.thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            interrupt_ref=interrupt.model_copy(
                update={"status": GraphInterruptStatus.RESUMED}
            ),
            payload_ref=kwargs["resume_payload"].payload_ref,
            trace_context=kwargs["trace_context"],
        )

    def pause_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("pause_thread is not used for tool confirmations")

    def resume_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_thread is not used for tool confirmations")

    def terminate_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("terminate_thread is not used for tool confirmations")

    def assert_thread_terminal(self, **kwargs: Any) -> GraphThreadRef:
        raise AssertionError("assert_thread_terminal is not used for tool confirmations")


class FailingCommitSession:
    def __init__(self, wrapped: Session) -> None:
        self._wrapped = wrapped
        self.rollback_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def commit(self) -> None:
        raise RuntimeError("runtime commit unavailable")

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._wrapped.rollback()


def build_manager(tmp_path: Path) -> ToolConfirmationTestDatabaseManager:
    return ToolConfirmationTestDatabaseManager(tmp_path)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-tool-confirmation",
        trace_id="trace-tool-confirmation",
        correlation_id="correlation-tool-confirmation",
        span_id="root-span",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def build_service(
    manager: ToolConfirmationTestDatabaseManager,
    *,
    runtime_port: FakeRuntimePort | None = None,
    audit_service: RecordingAuditService | None = None,
    log_writer: RecordingRunLogWriter | None = None,
    runtime_session_wrapper: Callable[[Session], Any] | None = None,
) -> tuple[
    ToolConfirmationService,
    FakeRuntimePort,
    RecordingAuditService,
    RecordingRunLogWriter,
]:
    resolved_runtime_port = runtime_port or FakeRuntimePort()
    resolved_audit_service = audit_service or RecordingAuditService()
    resolved_log_writer = log_writer or RecordingRunLogWriter()
    runtime_session = manager.open_session(DatabaseRole.RUNTIME)
    if runtime_session_wrapper is not None:
        runtime_session = runtime_session_wrapper(runtime_session)
    service = ToolConfirmationService(
        control_session=manager.open_session(DatabaseRole.CONTROL),
        runtime_session=runtime_session,
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


def seed_running_target(manager: ToolConfirmationTestDatabaseManager) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Tool Project",
                root_path="C:/repo/tool-project",
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
                display_name="Tool session",
                status=SessionStatus.RUNNING,
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
                    status=RunStatus.RUNNING,
                    trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                    template_snapshot_ref="template-snapshot-1",
                    graph_definition_ref="graph-definition-1",
                    graph_thread_ref="thread-1",
                    workspace_ref="workspace-1",
                    runtime_limit_snapshot_ref="runtime-limits-1",
                    provider_call_policy_snapshot_ref="provider-policy-1",
                    delivery_channel_snapshot_ref=None,
                    current_stage_run_id="stage-run-1",
                    trace_id="trace-tool-confirmation",
                    started_at=NOW,
                    ended_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                StageRunModel(
                    stage_run_id="stage-run-1",
                    run_id="run-1",
                    stage_type=StageType.CODE_GENERATION,
                    status=StageStatus.RUNNING,
                    attempt_index=1,
                    graph_node_key="code_generation.main",
                    stage_contract_ref="stage-contract-code-generation",
                    input_ref=None,
                    output_ref=None,
                    summary="Generating code.",
                    started_at=NOW,
                    ended_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )


def create_request(service: ToolConfirmationService):
    return service.create_request(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        confirmation_object_ref="tool-action-1",
        tool_name="bash",
        command_preview="Remove-Item -Recurse build",
        target_summary="Deletes generated build outputs.",
        risk_level=ToolRiskLevel.HIGH_RISK,
        risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE],
        reason="The command deletes files and requires explicit confirmation.",
        expected_side_effects=["Deletes build outputs."],
        alternative_path_summary="Keep generated files and stop the run.",
        planned_deny_followup_action="continue_current_stage",
        planned_deny_followup_summary=(
            "Code Generation will continue with a low-risk fallback."
        ),
        trace_context=build_trace(),
    )


def seed_pending_confirmation(
    manager: ToolConfirmationTestDatabaseManager,
    *,
    request_status: ToolConfirmationStatus = ToolConfirmationStatus.PENDING,
    user_decision: ToolConfirmationStatus | None = None,
    planned_deny_followup_action: str | None = "continue_current_stage",
    planned_deny_followup_summary: str | None = (
        "Code Generation will continue with a low-risk fallback."
    ),
    run_status: RunStatus = RunStatus.WAITING_TOOL_CONFIRMATION,
    session_status: SessionStatus = SessionStatus.WAITING_TOOL_CONFIRMATION,
    stage_status: StageStatus = StageStatus.WAITING_TOOL_CONFIRMATION,
) -> str:
    seed_running_target(manager)
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        control_session.status = session_status
        control_session.updated_at = NOW
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert run is not None
        assert stage is not None
        run.status = run_status
        run.updated_at = NOW
        stage.status = stage_status
        stage.updated_at = NOW
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
                planned_deny_followup_action=planned_deny_followup_action,
                planned_deny_followup_summary=planned_deny_followup_summary,
                deny_followup_action=None,
                deny_followup_summary=None,
                user_decision=user_decision,
                status=request_status,
                graph_interrupt_ref="interrupt-tool-confirmation-1",
                audit_log_ref=None,
                process_ref=None,
                requested_at=NOW,
                responded_at=None if user_decision is None else NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return "tool-confirmation-1"


def seed_duplicate_visible_session_for_run(
    manager: ToolConfirmationTestDatabaseManager,
    *,
    session_id: str = "session-shadow",
    current_run_id: str = "run-1",
    status: SessionStatus = SessionStatus.WAITING_TOOL_CONFIRMATION,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            SessionModel(
                session_id=session_id,
                project_id="project-1",
                display_name="Shadow session",
                status=status,
                selected_template_id="template-1",
                current_run_id=current_run_id,
                latest_stage_type=StageType.CODE_GENERATION,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def test_create_request_persists_confirmation_control_record_event_and_waiting_statuses(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_target(manager)
    service, runtime_port, audit, log_writer = build_service(manager)

    result = create_request(service)

    assert result.tool_confirmation.tool_confirmation_id.startswith("tool-confirmation-")
    assert result.tool_confirmation.status is ToolConfirmationStatus.PENDING
    assert result.tool_confirmation.type.value == "tool_confirmation"
    assert (
        result.tool_confirmation.allow_action
        == f"allow:{result.tool_confirmation.tool_confirmation_id}"
    )
    assert (
        result.tool_confirmation.deny_action
        == f"deny:{result.tool_confirmation.tool_confirmation_id}"
    )
    assert result.graph_interrupt_ref == "interrupt-tool-confirmation-1"
    assert runtime_port.calls[0][0] == "create_interrupt"
    assert runtime_port.calls[0][1]["tool_action_ref"] == "tool-action-1"
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.WAITING_TOOL_CONFIRMATION
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(
            ToolConfirmationRequestModel,
            result.tool_confirmation.tool_confirmation_id,
        )
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        control_record = session.query(RunControlRecordModel).one()
        assert request is not None
        assert request.graph_interrupt_ref == "interrupt-tool-confirmation-1"
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.planned_deny_followup_action == "continue_current_stage"
        assert request.planned_deny_followup_summary == (
            "Code Generation will continue with a low-risk fallback."
        )
        assert request.deny_followup_action is None
        assert request.deny_followup_summary is None
        assert run is not None and run.status is RunStatus.WAITING_TOOL_CONFIRMATION
        assert stage is not None and stage.status is StageStatus.WAITING_TOOL_CONFIRMATION
        assert control_record.control_type is RunControlRecordType.TOOL_CONFIRMATION
        assert control_record.graph_interrupt_ref == "interrupt-tool-confirmation-1"
        assert control_record.payload_ref == request.tool_confirmation_id
    with manager.session(DatabaseRole.EVENT) as session:
        event = session.query(DomainEventModel).one()
        payload = event.payload["tool_confirmation"]
        assert event.event_type.value == "tool_confirmation_requested"
        assert payload["tool_confirmation_id"] == result.tool_confirmation.tool_confirmation_id
        assert payload["is_actionable"] is True
    assert audit.records[0]["method"] == "require_audit_record"
    assert audit.records[0]["action"] == "tool_confirmation.request"
    assert callable(audit.records[0]["rollback"])
    assert log_writer.records[-1].payload.excerpt is not None
    assert '"result_status":"created"' in log_writer.records[-1].payload.excerpt


def test_allow_updates_request_result_projection_and_resumes_runtime(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(manager)
    service, runtime_port, audit, _log_writer = build_service(manager)

    result = service.allow(
        tool_confirmation_id=confirmation_id,
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.tool_confirmation.tool_confirmation_id == confirmation_id
    assert result.tool_confirmation.status is ToolConfirmationStatus.ALLOWED
    assert result.tool_confirmation.decision is ToolConfirmationStatus.ALLOWED
    assert result.tool_confirmation.is_actionable is False
    assert runtime_port.calls[-1][0] == "resume_tool_confirmation"
    assert runtime_port.calls[-1][1]["resume_payload"].values == {
        "decision": "allowed",
        "tool_confirmation_id": confirmation_id,
        "confirmation_object_ref": "tool-action-1",
    }
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.ALLOWED
        assert request.user_decision is ToolConfirmationStatus.ALLOWED
        assert request.responded_at == NOW.replace(tzinfo=None)
    with manager.session(DatabaseRole.EVENT) as session:
        event = session.query(DomainEventModel).one()
        payload = event.payload["tool_confirmation"]
        assert event.event_type.value == "tool_confirmation_result"
        assert payload["decision"] == "allowed"
        assert payload["tool_confirmation_id"] == confirmation_id
    assert audit.records[0]["action"] == "tool_confirmation.allow"
    assert callable(audit.records[0]["rollback"])


def test_deny_updates_request_result_projection_and_resumes_runtime(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(manager)
    service, runtime_port, audit, log_writer = build_service(manager)

    result = service.deny(
        tool_confirmation_id=confirmation_id,
        reason="The command deletes too much state.",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.tool_confirmation.status is ToolConfirmationStatus.DENIED
    assert result.tool_confirmation.decision is ToolConfirmationStatus.DENIED
    assert runtime_port.calls[-1][1]["resume_payload"].values == {
        "decision": "denied",
        "tool_confirmation_id": confirmation_id,
        "confirmation_object_ref": "tool-action-1",
        "deny_followup_action": "continue_current_stage",
        "deny_followup_summary": "Code Generation will continue with a low-risk fallback.",
        "reason": "The command deletes too much state.",
    }
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.DENIED
        assert request.user_decision is ToolConfirmationStatus.DENIED
        assert request.planned_deny_followup_action == "continue_current_stage"
        assert request.planned_deny_followup_summary == (
            "Code Generation will continue with a low-risk fallback."
        )
        assert request.deny_followup_action == "continue_current_stage"
        assert request.deny_followup_summary == (
            "Code Generation will continue with a low-risk fallback."
        )
    assert audit.records[0]["action"] == "tool_confirmation.deny"
    assert audit.records[0]["reason"] == "The command deletes too much state."
    assert log_writer.records[-1].payload.excerpt is not None
    assert '"reason":"The command deletes too much state."' in log_writer.records[-1].payload.excerpt


@pytest.mark.parametrize(
    ("planned_action", "planned_summary"),
    [
        (
            "run_failed",
            "The run will fail because no low-risk fallback is available.",
        ),
        (
            "awaiting_run_control",
            "The run is waiting for an explicit pause or terminate decision.",
        ),
    ],
)
def test_deny_persists_non_continue_followup_fields(
    tmp_path: Path,
    planned_action: str,
    planned_summary: str,
) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        planned_deny_followup_action=planned_action,
        planned_deny_followup_summary=planned_summary,
    )
    service, runtime_port, _audit, _log_writer = build_service(manager)

    result = service.deny(
        tool_confirmation_id=confirmation_id,
        reason="Do not run this tool action.",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.tool_confirmation.status is ToolConfirmationStatus.DENIED
    assert runtime_port.calls[-1][1]["resume_payload"].values["deny_followup_action"] == (
        planned_action
    )
    assert runtime_port.calls[-1][1]["resume_payload"].values["deny_followup_summary"] == (
        planned_summary
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.deny_followup_action == planned_action
        assert request.deny_followup_summary == planned_summary


def test_deny_requires_persisted_followup_source(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        planned_deny_followup_action=None,
        planned_deny_followup_summary=None,
    )
    service, runtime_port, audit, log_writer = build_service(manager)

    with pytest.raises(ToolConfirmationServiceError) as exc_info:
        service.deny(
            tool_confirmation_id=confirmation_id,
            reason="Do not run this tool action.",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.planned_deny_followup_action is None
        assert request.planned_deny_followup_summary is None
        assert request.deny_followup_action is None
        assert request.deny_followup_summary is None
    assert runtime_port.calls == []
    assert audit.records[-1]["action"] == "tool_confirmation.deny.failed"
    assert log_writer.records[-1].message == "Tool confirmation command failed."


def test_paused_run_rejects_without_mutation(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
    )
    service, runtime_port, audit, log_writer = build_service(manager)

    with pytest.raises(ToolConfirmationServiceError) as exc_info:
        service.allow(
            tool_confirmation_id=confirmation_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.TOOL_CONFIRMATION_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert "paused" in exc_info.value.message
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert runtime_port.calls == []
    assert audit.records[0]["method"] == "record_rejected_command"
    assert audit.records[0]["action"] == "tool_confirmation.allow.rejected"
    assert log_writer.records[-1].payload.excerpt is not None
    assert '"result_status":"rejected"' in log_writer.records[-1].payload.excerpt


def test_deny_paused_run_rejects_without_mutation(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
    )
    service, runtime_port, audit, log_writer = build_service(manager)

    with pytest.raises(ToolConfirmationServiceError) as exc_info:
        service.deny(
            tool_confirmation_id=confirmation_id,
            reason="Need a later operator decision.",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.TOOL_CONFIRMATION_NOT_ACTIONABLE
    assert exc_info.value.status_code == 409
    assert "paused" in exc_info.value.message
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.deny_followup_action is None
        assert request.deny_followup_summary is None
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert runtime_port.calls == []
    assert audit.records[0]["method"] == "record_rejected_command"
    assert audit.records[0]["action"] == "tool_confirmation.deny.rejected"
    assert log_writer.records[-1].payload.excerpt is not None
    assert '"result_status":"rejected"' in log_writer.records[-1].payload.excerpt


@pytest.mark.parametrize(
    ("status", "decision", "run_status"),
    [
        (
            ToolConfirmationStatus.ALLOWED,
            ToolConfirmationStatus.ALLOWED,
            RunStatus.WAITING_TOOL_CONFIRMATION,
        ),
        (
            ToolConfirmationStatus.PENDING,
            None,
            RunStatus.COMPLETED,
        ),
    ],
)
def test_terminal_or_already_resolved_request_rejects_without_mutation(
    tmp_path: Path,
    status: ToolConfirmationStatus,
    decision: ToolConfirmationStatus | None,
    run_status: RunStatus,
) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        request_status=status,
        user_decision=decision,
        run_status=run_status,
    )
    service, runtime_port, audit, log_writer = build_service(manager)

    with pytest.raises(ToolConfirmationServiceError) as exc_info:
        service.allow(
            tool_confirmation_id=confirmation_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.TOOL_CONFIRMATION_NOT_ACTIONABLE
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is status
        assert request.user_decision is decision
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert runtime_port.calls == []
    assert audit.records[0]["method"] == "record_rejected_command"
    assert audit.records[0]["action"] == "tool_confirmation.allow.rejected"
    assert log_writer.records[-1].payload.excerpt is not None
    assert '"result_status":"rejected"' in log_writer.records[-1].payload.excerpt


def test_deny_terminal_request_rejects_without_mutation(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        run_status=RunStatus.COMPLETED,
        session_status=SessionStatus.COMPLETED,
        stage_status=StageStatus.COMPLETED,
    )
    service, runtime_port, audit, log_writer = build_service(manager)

    with pytest.raises(ToolConfirmationServiceError) as exc_info:
        service.deny(
            tool_confirmation_id=confirmation_id,
            reason="The run is already terminal.",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.TOOL_CONFIRMATION_NOT_ACTIONABLE
    assert "terminal" in exc_info.value.message
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.deny_followup_action is None
        assert request.deny_followup_summary is None
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert runtime_port.calls == []
    assert audit.records[0]["method"] == "record_rejected_command"
    assert audit.records[0]["action"] == "tool_confirmation.deny.rejected"
    assert log_writer.records[-1].payload.excerpt is not None
    assert '"result_status":"rejected"' in log_writer.records[-1].payload.excerpt


def test_cancel_for_terminal_run_marks_pending_request_cancelled_without_result_event(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        run_status=RunStatus.FAILED,
        session_status=SessionStatus.FAILED,
        stage_status=StageStatus.FAILED,
    )
    service, _runtime_port, _audit, _log_writer = build_service(manager)

    result = service.cancel_for_terminal_run(
        run_id="run-1",
        trace_context=build_trace(),
    )

    assert [entry.tool_confirmation_id for entry in result.cancelled_confirmations] == [
        confirmation_id
    ]
    assert result.cancelled_confirmations[0].status is ToolConfirmationStatus.CANCELLED
    assert result.cancelled_confirmations[0].is_actionable is False
    assert result.cancelled_confirmations[0].allow_action == f"allow:{confirmation_id}"
    assert result.cancelled_confirmations[0].deny_action == f"deny:{confirmation_id}"
    assert result.cancelled_confirmations[0].disabled_reason == (
        "Tool confirmation is no longer pending."
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.CANCELLED
        assert request.user_decision is None
        assert request.responded_at == NOW.replace(tzinfo=None)
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert any(
        record["action"] == "tool_confirmation.cancel"
        for record in _audit.records
    )
    cancel_records = [
        record for record in _audit.records if record["action"] == "tool_confirmation.cancel"
    ]
    assert len(cancel_records) == 1
    assert callable(cancel_records[0]["rollback"])
    assert any(
        record.payload.excerpt is not None
        and '"result_status":"cancelled"' in record.payload.excerpt
        for record in _log_writer.records
    )


def test_cancel_for_terminal_run_can_defer_commit_for_shared_terminal_transaction(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        run_status=RunStatus.FAILED,
        session_status=SessionStatus.FAILED,
        stage_status=StageStatus.FAILED,
    )
    service, _runtime_port, audit, log_writer = build_service(
        manager,
        runtime_session_wrapper=FailingCommitSession,
    )

    result = service.cancel_for_terminal_run(
        run_id="run-1",
        trace_context=build_trace(),
        commit=False,
    )

    assert [entry.tool_confirmation_id for entry in result.cancelled_confirmations] == [
        confirmation_id
    ]
    assert result.cancelled_confirmations[0].status is ToolConfirmationStatus.CANCELLED
    assert result.cancelled_confirmations[0].decision is None
    assert service._runtime_session.rollback_calls == 0
    service._runtime_session.rollback()
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.responded_at is None
    assert [record["action"] for record in audit.records] == [
        "tool_confirmation.cancel",
    ]
    assert [record.message for record in log_writer.records] == [
        "Tool confirmation cancelled for terminal run.",
    ]


def test_allow_rolls_back_status_and_events_when_runtime_resume_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(manager)
    runtime_port = FakeRuntimePort(fail_on_resume=True)
    service, _runtime_port, audit, _log_writer = build_service(
        manager,
        runtime_port=runtime_port,
    )

    with pytest.raises(ToolConfirmationServiceError) as exc_info:
        service.allow(
            tool_confirmation_id=confirmation_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.responded_at is None
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert audit.records[-1]["action"] == "tool_confirmation.allow.failed"


def test_allow_uses_run_session_id_when_other_visible_session_shares_current_run_id(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(manager)
    seed_duplicate_visible_session_for_run(manager)
    service, runtime_port, _audit, _log_writer = build_service(manager)

    result = service.allow(
        tool_confirmation_id=confirmation_id,
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.tool_confirmation.status is ToolConfirmationStatus.ALLOWED
    assert runtime_port.calls[-1][0] == "resume_tool_confirmation"
    with manager.session(DatabaseRole.CONTROL) as session:
        primary = session.get(SessionModel, "session-1")
        shadow = session.get(SessionModel, "session-shadow")
        assert primary is not None
        assert shadow is not None
        assert primary.status is SessionStatus.RUNNING
        assert shadow.status is SessionStatus.WAITING_TOOL_CONFIRMATION


def test_allow_rolls_back_when_required_audit_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(manager)
    service, runtime_port, audit, log_writer = build_service(
        manager,
        audit_service=FailingRequiredAuditService(),
    )

    with pytest.raises(ToolConfirmationServiceError) as exc_info:
        service.allow(
            tool_confirmation_id=confirmation_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.__cause__ is not None
    assert str(exc_info.value.__cause__) == "required audit unavailable"
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert request is not None
        assert run is not None
        assert stage is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.responded_at is None
        assert run.status is RunStatus.WAITING_TOOL_CONFIRMATION
        assert stage.status is StageStatus.WAITING_TOOL_CONFIRMATION
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert runtime_port.calls == []
    assert [record["action"] for record in audit.records] == [
        "tool_confirmation.allow",
        "tool_confirmation.allow.failed",
    ]
    assert [record.message for record in log_writer.records] == [
        "Tool confirmation command failed."
    ]


def test_cancel_for_terminal_run_rolls_back_when_runtime_commit_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    confirmation_id = seed_pending_confirmation(
        manager,
        run_status=RunStatus.FAILED,
        session_status=SessionStatus.FAILED,
        stage_status=StageStatus.FAILED,
    )
    service, _runtime_port, audit, log_writer = build_service(
        manager,
        runtime_session_wrapper=FailingCommitSession,
    )

    with pytest.raises(RuntimeError, match="runtime commit unavailable"):
        service.cancel_for_terminal_run(
            run_id="run-1",
            trace_context=build_trace(),
        )

    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.responded_at is None
    assert service._runtime_session.rollback_calls >= 1
    assert [record["action"] for record in audit.records] == [
        "tool_confirmation.cancel",
    ]
    assert [record.message for record in log_writer.records] == [
        "Tool confirmation cancelled for terminal run.",
    ]
