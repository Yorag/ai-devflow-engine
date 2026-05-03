from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    PipelineTemplateModel,
    ProjectModel,
    SessionModel,
)
from backend.app.db.models.event import DomainEventModel, EventBase
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    ClarificationRecordModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RunControlRecordModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    RunControlRecordType,
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    StageStatus,
    StageType,
    SseEventType,
    TemplateSource,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeCommandResult,
    RuntimeCommandType,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditResult
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


NOW = datetime(2026, 5, 3, 8, 0, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
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

    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append(
            {
                "method": "record_failed_command",
                "result": AuditResult.FAILED,
                **kwargs,
            }
        )
        return object()


class FailingRequiredAuditService(RecordingAuditService):
    def __init__(self, *, fail_action: str) -> None:
        super().__init__()
        self._fail_action = fail_action

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        if kwargs["action"] == self._fail_action:
            raise RuntimeError("required audit unavailable")
        return object()


class FakeCheckpointPort:
    def save_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        purpose: CheckpointPurpose,
        trace_context: TraceContext,
        stage_run_id: str | None = None,
        stage_type: StageType | None = None,
        workspace_snapshot_ref: str | None = None,
        payload_ref: str | None = None,
    ) -> CheckpointRef:
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{purpose.value}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            purpose=purpose,
            workspace_snapshot_ref=workspace_snapshot_ref,
            payload_ref=payload_ref,
        )

    def load_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> CheckpointRef:
        return checkpoint


class FakeRuntimePort:
    def __init__(self, *, fail_resume: bool = False) -> None:
        self.fail_resume = fail_resume
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_interrupt(
        self,
        *,
        thread: GraphThreadRef,
        interrupt_type: GraphInterruptType,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        payload_ref: str,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
        clarification_id: str | None = None,
        approval_id: str | None = None,
        tool_confirmation_id: str | None = None,
        tool_action_ref: str | None = None,
    ) -> GraphInterruptRef:
        self.calls.append(
            (
                "create_interrupt",
                {
                    "thread": thread,
                    "interrupt_type": interrupt_type,
                    "run_id": run_id,
                    "stage_run_id": stage_run_id,
                    "stage_type": stage_type,
                    "payload_ref": payload_ref,
                    "checkpoint": checkpoint,
                    "trace_context": trace_context,
                    "clarification_id": clarification_id,
                    "approval_id": approval_id,
                    "tool_confirmation_id": tool_confirmation_id,
                    "tool_action_ref": tool_action_ref,
                },
            )
        )
        return GraphInterruptRef(
            interrupt_id=f"interrupt-{clarification_id}",
            thread=thread.model_copy(
                update={"status": GraphThreadStatus.WAITING_CLARIFICATION}
            ),
            interrupt_type=interrupt_type,
            status=GraphInterruptStatus.PENDING,
            run_id=run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            payload_ref=payload_ref,
            clarification_id=clarification_id,
            approval_id=approval_id,
            tool_confirmation_id=tool_confirmation_id,
            tool_action_ref=tool_action_ref,
            checkpoint_ref=checkpoint,
        )

    def resume_interrupt(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        self.calls.append(
            (
                "resume_interrupt",
                {
                    "interrupt": interrupt,
                    "resume_payload": resume_payload,
                    "trace_context": trace_context,
                },
            )
        )
        if self.fail_resume:
            raise RuntimeError("runtime resume failed")
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_INTERRUPT,
            thread=interrupt.thread.model_copy(
                update={"status": GraphThreadStatus.RUNNING}
            ),
            interrupt_ref=interrupt.model_copy(
                update={"status": GraphInterruptStatus.RESUMED}
            ),
            payload_ref=resume_payload.payload_ref,
            trace_context=trace_context,
        )

    def resume_tool_confirmation(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("clarification must not use tool confirmation resume")

    def pause_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("not used")

    def resume_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("not used")

    def terminate_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("not used")

    def assert_thread_terminal(self, **kwargs: Any) -> GraphThreadRef:
        raise AssertionError("not used")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-h41",
        trace_id="trace-h41",
        correlation_id="correlation-h41",
        span_id="span-h41",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


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
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    return manager


def seed_waiting_requirement_analysis(manager: DatabaseManager) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Project",
                root_path="C:/repo/project",
                default_delivery_channel_id=None,
                is_default=True,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            PipelineTemplateModel(
                template_id="template-1",
                name="Default",
                description=None,
                template_source=TemplateSource.SYSTEM_TEMPLATE,
                base_template_id=None,
                fixed_stage_sequence=[StageType.REQUIREMENT_ANALYSIS.value],
                stage_role_bindings=[],
                approval_checkpoints=[],
                auto_regression_enabled=False,
                max_auto_regression_retries=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            SessionModel(
                session_id="session-1",
                project_id="project-1",
                display_name="Requirement",
                status=SessionStatus.RUNNING,
                selected_template_id="template-1",
                current_run_id="run-1",
                latest_stage_type=StageType.REQUIREMENT_ANALYSIS,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RuntimeLimitSnapshotModel(
                snapshot_id="limit-1",
                run_id="run-1",
                agent_limits={},
                context_limits={},
                source_config_version="test",
                hard_limits_version="test",
                schema_version="runtime-limit-v1",
                created_at=NOW,
            )
        )
        session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id="policy-1",
                run_id="run-1",
                provider_call_policy={},
                source_config_version="test",
                schema_version="provider-call-policy-snapshot-v1",
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
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
                runtime_limit_snapshot_ref="limit-1",
                provider_call_policy_snapshot_ref="policy-1",
                delivery_channel_snapshot_ref=None,
                current_stage_run_id="stage-run-1",
                trace_id="trace-h41",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            StageRunModel(
                stage_run_id="stage-run-1",
                run_id="run-1",
                stage_type=StageType.REQUIREMENT_ANALYSIS,
                status=StageStatus.RUNNING,
                attempt_index=1,
                input_ref="requirement-input-1",
                output_ref=None,
                summary="Analyzing requirement.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def build_service(
    manager: DatabaseManager,
    *,
    fail_resume: bool = False,
    audit: RecordingAuditService | None = None,
) -> tuple[Any, RecordingAuditService, FakeRuntimePort]:
    from backend.app.services.clarifications import ClarificationService

    audit = audit or RecordingAuditService()
    runtime_port = FakeRuntimePort(fail_resume=fail_resume)
    service = ClarificationService(
        control_session=manager.session(DatabaseRole.CONTROL),
        runtime_session=manager.session(DatabaseRole.RUNTIME),
        event_session=manager.session(DatabaseRole.EVENT),
        audit_service=audit,
        runtime_orchestration=RuntimeOrchestrationService(
            runtime_port=runtime_port,
            checkpoint_port=FakeCheckpointPort(),
            clock=lambda: NOW,
        ),
        now=lambda: NOW,
    )
    return service, audit, runtime_port


def request_clarification(manager: DatabaseManager) -> tuple[str, FakeRuntimePort]:
    service, _audit, runtime_port = build_service(manager)
    result = service.request_clarification(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        question="Which package should be changed?",
        payload_ref="clarification-payload-1",
        trace_context=build_trace(),
    )
    return result.clarification_id, runtime_port


def test_request_clarification_creates_wait_record_interrupt_event_and_no_approval(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_waiting_requirement_analysis(manager)
    service, audit, runtime_port = build_service(manager)

    result = service.request_clarification(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        question="Which package should be changed?",
        payload_ref="clarification-payload-1",
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        clarification = session.get(ClarificationRecordModel, result.clarification_id)
        control = session.get(RunControlRecordModel, result.control_record_id)
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        approval_count = session.query(ApprovalRequestModel).count()
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.CLARIFICATION_REQUESTED)
            .one()
        )

    assert clarification is not None
    assert clarification.question == "Which package should be changed?"
    assert clarification.answer is None
    assert clarification.graph_interrupt_ref == f"interrupt-{clarification.clarification_id}"
    assert control is not None
    assert control.control_type is RunControlRecordType.CLARIFICATION_WAIT
    assert control.graph_interrupt_ref == clarification.graph_interrupt_ref
    assert run is not None and run.status is RunStatus.WAITING_CLARIFICATION
    assert stage is not None and stage.status is StageStatus.WAITING_CLARIFICATION
    assert control_session is not None
    assert control_session.status is SessionStatus.WAITING_CLARIFICATION
    assert approval_count == 0
    assert runtime_port.calls[0][0] == "create_interrupt"
    assert runtime_port.calls[0][1]["interrupt_type"] is (
        GraphInterruptType.CLARIFICATION_REQUEST
    )
    assert event.payload["control_item"]["control_record_id"] == result.control_record_id
    assert event.payload["control_item"]["payload_ref"] == result.clarification_id
    assert audit.records[-1]["action"] == "clarification.request"
    assert audit.records[-1]["result"] is AuditResult.SUCCEEDED
    assert audit.records[-1]["metadata"]["stage_type"] == "requirement_analysis"
    assert audit.records[-1]["metadata"]["session_status"] == "waiting_clarification"
    assert audit.records[-1]["metadata"]["run_status"] == "waiting_clarification"
    assert audit.records[-1]["metadata"]["stage_status"] == "waiting_clarification"


def test_request_clarification_required_audit_failure_blocks_runtime_side_effects(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_waiting_requirement_analysis(manager)
    audit = FailingRequiredAuditService(fail_action="clarification.request.accepted")
    service, _audit, runtime_port = build_service(manager, audit=audit)

    with pytest.raises(RuntimeError, match="required audit unavailable"):
        service.request_clarification(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            question="Which package should be changed?",
            payload_ref="clarification-payload-1",
            trace_context=build_trace(),
        )

    assert runtime_port.calls == []
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert run is not None and run.status is RunStatus.RUNNING
        assert stage is not None and stage.status is StageStatus.RUNNING
        assert session.query(ClarificationRecordModel).count() == 0
        assert session.query(RunControlRecordModel).count() == 0
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_request_clarification_rejects_non_requirement_analysis_before_interrupt(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_waiting_requirement_analysis(manager)
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, "stage-run-1")
        assert stage is not None
        stage.stage_type = StageType.CODE_GENERATION
        session.add(stage)
        session.commit()
    service, audit, runtime_port = build_service(manager)

    from backend.app.services.clarifications import ClarificationServiceError

    with pytest.raises(ClarificationServiceError) as exc_info:
        service.request_clarification(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            question="Which package should be changed?",
            payload_ref="clarification-payload-1",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    assert "requirement_analysis" in exc_info.value.message
    assert runtime_port.calls == []
    assert audit.records[-1]["method"] == "record_rejected_command"
    assert audit.records[-1]["action"] == "clarification.request.rejected"
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(ClarificationRecordModel).count() == 0
        assert session.query(RunControlRecordModel).count() == 0
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_answer_clarification_restores_running_and_resumes_same_interrupt(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_waiting_requirement_analysis(manager)
    clarification_id, _request_runtime_port = request_clarification(manager)
    service, audit, runtime_port = build_service(manager)

    result = service.answer_clarification(
        session_id="session-1",
        answer="Change backend only.",
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        clarification = session.get(ClarificationRecordModel, clarification_id)
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.CLARIFICATION_ANSWERED)
            .one()
        )

    assert clarification is not None
    assert clarification.answer == "Change backend only."
    assert clarification.answered_at is not None
    assert clarification.answered_at.replace(tzinfo=UTC) == NOW
    assert run is not None and run.status is RunStatus.RUNNING
    assert stage is not None and stage.status is StageStatus.RUNNING
    assert control_session is not None and control_session.status is SessionStatus.RUNNING
    assert runtime_port.calls[0][0] == "resume_interrupt"
    assert runtime_port.calls[0][1]["interrupt"].interrupt_id == (
        clarification.graph_interrupt_ref
    )
    assert runtime_port.calls[0][1]["resume_payload"].values == {
        "clarification_id": clarification_id,
        "answer": "Change backend only.",
    }
    assert result.message_item.content == "Change backend only."
    assert event.payload["message_item"]["content"] == "Change backend only."
    assert audit.records[-1]["action"] == "session.message.clarification_reply"
    assert audit.records[-1]["result"] is AuditResult.SUCCEEDED
    assert audit.records[-1]["metadata"]["stage_type"] == "requirement_analysis"
    assert audit.records[-1]["metadata"]["session_status"] == "running"
    assert audit.records[-1]["metadata"]["run_status"] == "running"
    assert audit.records[-1]["metadata"]["stage_status"] == "running"
    assert audit.records[-1]["metadata"]["answer_length"] == len("Change backend only.")


def test_answer_clarification_required_audit_failure_blocks_runtime_resume(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_waiting_requirement_analysis(manager)
    clarification_id, _request_runtime_port = request_clarification(manager)
    audit = FailingRequiredAuditService(
        fail_action="session.message.clarification_reply.accepted"
    )
    service, _audit, runtime_port = build_service(manager, audit=audit)

    with pytest.raises(RuntimeError, match="required audit unavailable"):
        service.answer_clarification(
            session_id="session-1",
            answer="Change backend only.",
            trace_context=build_trace(),
        )

    assert runtime_port.calls == []
    with manager.session(DatabaseRole.RUNTIME) as session:
        clarification = session.get(ClarificationRecordModel, clarification_id)
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        assert clarification is not None
        assert clarification.answer is None
        assert clarification.answered_at is None
        assert run is not None and run.status is RunStatus.WAITING_CLARIFICATION
        assert stage is not None and stage.status is StageStatus.WAITING_CLARIFICATION
    with manager.session(DatabaseRole.EVENT) as session:
        answered_count = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.CLARIFICATION_ANSWERED)
            .count()
        )
        assert answered_count == 0


def test_answer_clarification_rejects_when_session_is_not_waiting(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_waiting_requirement_analysis(manager)
    service, audit, runtime_port = build_service(manager)

    from backend.app.services.clarifications import ClarificationServiceError

    with pytest.raises(ClarificationServiceError) as exc_info:
        service.answer_clarification(
            session_id="session-1",
            answer="Too early.",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    assert "waiting_clarification" in exc_info.value.message
    assert runtime_port.calls == []
    assert audit.records[-1]["method"] == "record_rejected_command"
    assert audit.records[-1]["action"] == "session.message.clarification_reply.rejected"
    assert audit.records[-1]["metadata"]["session_status"] == "running"
    assert audit.records[-1]["metadata"]["run_status"] == "running"
    assert audit.records[-1]["metadata"]["stage_type"] == "requirement_analysis"
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_answer_clarification_rolls_back_when_runtime_resume_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_waiting_requirement_analysis(manager)
    clarification_id, _request_runtime_port = request_clarification(manager)
    service, audit, _runtime_port = build_service(manager, fail_resume=True)

    from backend.app.services.clarifications import ClarificationServiceError

    with pytest.raises(ClarificationServiceError) as exc_info:
        service.answer_clarification(
            session_id="session-1",
            answer="Change backend only.",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    assert "runtime resume failed" in exc_info.value.message
    with manager.session(DatabaseRole.RUNTIME) as session:
        clarification = session.get(ClarificationRecordModel, clarification_id)
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
    with manager.session(DatabaseRole.EVENT) as session:
        answered_count = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.CLARIFICATION_ANSWERED)
            .count()
        )

    assert clarification is not None
    assert clarification.answer is None
    assert clarification.answered_at is None
    assert run is not None and run.status is RunStatus.WAITING_CLARIFICATION
    assert stage is not None and stage.status is StageStatus.WAITING_CLARIFICATION
    assert control_session is not None
    assert control_session.status is SessionStatus.WAITING_CLARIFICATION
    assert answered_count == 0
    assert audit.records[-1]["method"] == "record_failed_command"
    assert audit.records[-1]["action"] == "session.message.clarification_reply.resume_failed"
    assert audit.records[-1]["metadata"]["stage_type"] == "requirement_analysis"
    assert audit.records[-1]["metadata"]["session_status"] == "waiting_clarification"
    assert audit.records[-1]["metadata"]["run_status"] == "waiting_clarification"
    assert audit.records[-1]["metadata"]["stage_status"] == "waiting_clarification"
