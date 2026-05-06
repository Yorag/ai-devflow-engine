from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.graph import (
    GraphCheckpointModel,
    GraphInterruptModel,
    GraphThreadModel,
)
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ApprovalRequestModel,
    ClarificationRecordModel,
    PipelineRunModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    RunStatus,
    SessionStatus,
    SseEventType,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
    ToolRiskLevel,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.runtime.base import (
    RuntimeInterrupt,
    RuntimeStepResult,
    RuntimeTerminalResult,
)
from backend.app.schemas.observability import AuditResult
from backend.app.services.runtime_dispatch import (
    RuntimeDispatchCommand,
    RuntimeEngineFactoryInput,
    RuntimeExecutionService,
)
from backend.app.services.graph_runtime import GraphCheckpointPort, GraphRuntimeCommandPort
import backend.app.services.runtime_dispatch as runtime_dispatch_module
from backend.tests.services.test_start_first_run import (
    NOW,
    RecordingAuditService,
    RecordingLogWriter,
    build_manager,
    build_settings,
    build_trace,
    seed_control_plane,
)


@dataclass(frozen=True)
class StartedRunFixture:
    settings: Any
    manager: Any
    result: Any
    command: RuntimeDispatchCommand


@dataclass(frozen=True)
class EngineCall:
    context: Any
    runtime_port: Any
    checkpoint_port: Any
    interrupt: RuntimeInterrupt | None = None
    resume_payload: RuntimeResumePayload | None = None


class CapturingRuntimeEngine:
    def __init__(
        self,
        *,
        fail_start_with: Exception | None = None,
        step_status: StageStatus = StageStatus.RUNNING,
        start_result: Any | None = None,
    ) -> None:
        self.fail_start_with = fail_start_with
        self.step_status = step_status
        self.start_result = start_result
        self.start_calls: list[EngineCall] = []
        self.run_next_calls: list[EngineCall] = []
        self.resume_calls: list[EngineCall] = []

    def start(self, *, context, runtime_port, checkpoint_port):  # noqa: ANN001
        self.start_calls.append(
            EngineCall(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
            )
        )
        if self.fail_start_with is not None:
            raise self.fail_start_with
        if self.start_result is not None:
            return self.start_result
        return _step_result(context, status=self.step_status)

    def run_next(self, *, context, runtime_port, checkpoint_port):  # noqa: ANN001
        self.run_next_calls.append(
            EngineCall(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
            )
        )
        return _step_result(context, status=self.step_status)

    def resume(  # noqa: ANN001
        self,
        *,
        context,
        interrupt,
        resume_payload,
        runtime_port,
        checkpoint_port,
    ):
        self.resume_calls.append(
            EngineCall(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
                interrupt=interrupt,
                resume_payload=resume_payload,
            )
        )
        return _step_result(context, status=self.step_status)


class FailingAfterGraphResumeEngine:
    def start(self, *, context, runtime_port, checkpoint_port):  # noqa: ANN001
        del context, runtime_port, checkpoint_port
        raise AssertionError("start should not be called")

    def run_next(self, *, context, runtime_port, checkpoint_port):  # noqa: ANN001
        del context, runtime_port, checkpoint_port
        raise AssertionError("run_next should not be called")

    def resume(  # noqa: ANN001
        self,
        *,
        context,
        interrupt,
        resume_payload,
        runtime_port,
        checkpoint_port,
    ):
        del context, checkpoint_port
        runtime_port.resume_interrupt(
            interrupt=interrupt.interrupt_ref,
            resume_payload=resume_payload,
            trace_context=interrupt.trace_context,
        )
        raise RuntimeError("langgraph resume crashed after graph command")


class CapturingStageAgentRuntime:
    instances: list["CapturingStageAgentRuntime"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        CapturingStageAgentRuntime.instances.append(self)

    def run_stage(self, invocation: Any) -> Any:
        from backend.app.runtime.stage_runner_port import StageNodeResult

        return StageNodeResult(
            run_id=invocation.run_id,
            stage_run_id=invocation.stage_run_id,
            stage_type=invocation.stage_type,
            status=StageStatus.FAILED,
            artifact_refs=[],
            domain_event_refs=[],
            log_summary_refs=[],
            audit_refs=[],
        )


def test_dispatch_started_run_reconstructs_context_and_calls_runtime_engine_start(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    fake_engine = CapturingRuntimeEngine()
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    assert len(fake_engine.start_calls) == 1
    call = fake_engine.start_calls[0]
    assert call.context.run_id == fixture.result.run.run_id
    assert call.context.session_id == fixture.result.session.session_id
    assert call.context.thread.thread_id == fixture.result.run.graph_thread_ref
    assert call.context.thread.status is GraphThreadStatus.RUNNING
    assert call.context.thread.current_stage_run_id == fixture.result.stage.stage_run_id
    assert call.context.thread.current_stage_type == fixture.result.stage.stage_type
    assert call.context.trace_context.run_id == fixture.result.run.run_id
    assert call.context.trace_context.stage_run_id == fixture.result.stage.stage_run_id
    assert call.context.trace_context.graph_thread_id == fixture.result.run.graph_thread_ref
    assert call.context.template_snapshot_ref == fixture.result.run.template_snapshot_ref
    assert call.context.provider_snapshot_refs
    assert call.context.model_binding_snapshot_refs
    assert type(call.runtime_port).__name__ == "GraphRuntimeCommandPort"
    assert type(call.checkpoint_port).__name__ == "GraphCheckpointPort"


def test_run_next_reconstructs_context_and_calls_runtime_engine_run_next(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    fake_engine = CapturingRuntimeEngine()
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.run_next(
        run_id=fixture.result.run.run_id,
        trace_context=fixture.command.trace_context,
    )

    assert len(fake_engine.run_next_calls) == 1
    call = fake_engine.run_next_calls[0]
    assert call.context.run_id == fixture.result.run.run_id
    assert call.context.thread.thread_id == fixture.result.run.graph_thread_ref
    assert call.context.provider_snapshot_refs
    assert type(call.runtime_port).__name__ == "GraphRuntimeCommandPort"
    assert type(call.checkpoint_port).__name__ == "GraphCheckpointPort"


def test_resume_reconstructs_context_and_calls_runtime_engine_resume(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    fake_engine = CapturingRuntimeEngine()
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )
    interrupt = _runtime_interrupt(fixture)
    resume_payload = RuntimeResumePayload(
        resume_id="resume-runtime-dispatch",
        payload_ref="payload-runtime-dispatch",
        values={"answer": "Continue."},
    )

    service.resume(
        interrupt=interrupt,
        resume_payload=resume_payload,
        trace_context=fixture.command.trace_context,
    )

    assert len(fake_engine.resume_calls) == 1
    call = fake_engine.resume_calls[0]
    assert call.context.run_id == fixture.result.run.run_id
    assert call.context.thread.thread_id == fixture.result.run.graph_thread_ref
    assert call.interrupt == interrupt
    assert call.resume_payload == resume_payload
    assert type(call.runtime_port).__name__ == "GraphRuntimeCommandPort"
    assert type(call.checkpoint_port).__name__ == "GraphCheckpointPort"


def test_resume_failure_cancels_pending_graph_interrupt(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    interrupt = _persist_waiting_clarification_interrupt(fixture)
    resume_payload = RuntimeResumePayload(
        resume_id="resume-runtime-dispatch",
        payload_ref="payload-runtime-dispatch",
        values={"answer": "Continue."},
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: FailingAfterGraphResumeEngine(),
    )

    service.resume(
        interrupt=interrupt,
        resume_payload=resume_payload,
        trace_context=fixture.command.trace_context,
    )

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.FAILED
        assert stage.status is StageStatus.FAILED

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        graph_interrupt = session.get(
            GraphInterruptModel,
            interrupt.interrupt_ref.interrupt_id,
        )
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert graph_interrupt is not None
        assert thread is not None
        assert graph_interrupt.status == "cancelled"
        assert graph_interrupt.responded_at is not None
        assert thread.status == "failed"
        assert thread.current_interrupt_id is None


def test_dispatch_started_run_failure_marks_run_failed_and_projects_system_status(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    fake_engine = CapturingRuntimeEngine(
        fail_start_with=RuntimeError("provider unavailable: secret-token")
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.FAILED
        assert run.ended_at is not None
        assert stage.status is StageStatus.FAILED
        assert stage.ended_at is not None
        assert stage.summary is not None
        assert "provider unavailable" in stage.summary
        assert "secret-token" not in stage.summary

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.FAILED
        assert control_session.current_run_id == fixture.result.run.run_id

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert thread is not None
        assert thread.status == "failed"
        assert thread.current_interrupt_id is None

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        system_status = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == fixture.result.run.run_id,
                DomainEventModel.event_type == "system_status",
            )
            .one()
        )
        stage_updated = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == fixture.result.run.run_id,
                DomainEventModel.event_type == "stage_updated",
            )
            .one()
        )
        assert system_status.payload["system_status"]["status"] == "failed"
        assert (
            system_status.payload["system_status"]["retry_action"]
            == f"retry:{fixture.result.run.run_id}"
        )
        assert "secret-token" not in str(system_status.payload)
        assert stage_updated.payload["stage_node"]["status"] == "failed"
        assert "secret-token" not in str(stage_updated.payload)

    with fixture.manager.session(DatabaseRole.LOG) as session:
        failed_audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "runtime.execution.failed")
            .one()
        )
        assert failed_audit.result is AuditResult.FAILED
        assert "secret-token" not in (failed_audit.reason or "")
        assert "secret-token" not in (failed_audit.metadata_excerpt or "")


def test_completed_step_result_marks_stage_completed_and_projects_update(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    fake_engine = CapturingRuntimeEngine(step_status=StageStatus.COMPLETED)
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.RUNNING
        assert run.current_stage_run_id == stage.stage_run_id
        assert stage.status is StageStatus.COMPLETED
        assert stage.ended_at is not None

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.RUNNING
        assert control_session.latest_stage_type is fixture.result.stage.stage_type

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        stage_updated = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == fixture.result.run.run_id,
                DomainEventModel.event_type == "stage_updated",
            )
            .one()
        )
        assert stage_updated.payload["stage_node"]["status"] == "completed"
        assert (
            stage_updated.payload["stage_node"]["stage_run_id"]
            == fixture.result.stage.stage_run_id
        )


def test_runtime_interrupt_marks_run_stage_and_session_waiting(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    interrupt = _runtime_interrupt(fixture)
    fake_engine = CapturingRuntimeEngine(start_result=interrupt)
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.WAITING_CLARIFICATION
        assert stage.status is StageStatus.WAITING_CLARIFICATION
        assert run.current_stage_run_id == stage.stage_run_id
        assert stage.ended_at is None

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.WAITING_CLARIFICATION
        assert control_session.latest_stage_type is fixture.result.stage.stage_type

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert thread is not None
        assert thread.status == "interrupted"
        assert thread.current_interrupt_id == interrupt.interrupt_ref.interrupt_id

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        stage_updated = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == fixture.result.run.run_id,
                DomainEventModel.event_type == "stage_updated",
            )
            .one()
        )
        assert stage_updated.payload["stage_node"]["status"] == "waiting_clarification"


def test_waiting_clarification_step_creates_actionable_request_and_interrupt(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    fake_engine = CapturingRuntimeEngine(step_status=StageStatus.WAITING_CLARIFICATION)
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        clarification = session.query(ClarificationRecordModel).one()
        assert clarification.run_id == fixture.result.run.run_id
        assert clarification.stage_run_id == fixture.result.stage.stage_run_id
        assert clarification.answer is None
        assert clarification.graph_interrupt_ref
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.WAITING_CLARIFICATION
        assert stage.status is StageStatus.WAITING_CLARIFICATION

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        graph_interrupt = session.get(
            GraphInterruptModel,
            clarification.graph_interrupt_ref,
        )
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert graph_interrupt is not None
        assert thread is not None
        assert graph_interrupt.status == "pending"
        assert graph_interrupt.runtime_object_ref == clarification.clarification_id
        assert thread.current_interrupt_id == graph_interrupt.interrupt_id

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        event_types = {
            event.event_type
            for event in session.query(DomainEventModel)
            .filter(DomainEventModel.run_id == fixture.result.run.run_id)
            .all()
        }
        assert "clarification_requested" in event_types


def test_waiting_tool_confirmation_step_creates_actionable_request_and_interrupt(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    fake_engine = CapturingRuntimeEngine(
        step_status=StageStatus.WAITING_TOOL_CONFIRMATION
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        request = session.query(ToolConfirmationRequestModel).one()
        assert request.run_id == fixture.result.run.run_id
        assert request.stage_run_id == fixture.result.stage.stage_run_id
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.graph_interrupt_ref
        assert request.risk_level is ToolRiskLevel.HIGH_RISK
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.WAITING_TOOL_CONFIRMATION
        assert stage.status is StageStatus.WAITING_TOOL_CONFIRMATION

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        graph_interrupt = session.get(GraphInterruptModel, request.graph_interrupt_ref)
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert graph_interrupt is not None
        assert thread is not None
        assert graph_interrupt.status == "pending"
        assert graph_interrupt.runtime_object_ref == request.tool_confirmation_id
        assert thread.current_interrupt_id == graph_interrupt.interrupt_id

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        event_types = {
            event.event_type
            for event in session.query(DomainEventModel)
            .filter(DomainEventModel.run_id == fixture.result.run.run_id)
            .all()
        }
        assert "tool_confirmation_requested" in event_types


def test_terminal_result_marks_run_session_and_thread_completed(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    terminal_result = RuntimeTerminalResult(
        run_id=fixture.result.run.run_id,
        status=GraphThreadStatus.COMPLETED,
        thread=GraphThreadRef(
            thread_id=fixture.result.run.graph_thread_ref,
            run_id=fixture.result.run.run_id,
            status=GraphThreadStatus.COMPLETED,
            current_stage_run_id=None,
            current_stage_type=None,
        ),
        trace_context=fixture.command.trace_context,
    )
    fake_engine = CapturingRuntimeEngine(start_result=terminal_result)
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.current_stage_run_id is None
        assert run.ended_at is not None

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.COMPLETED

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert thread is not None
        assert thread.status == "completed"
        assert thread.current_interrupt_id is None

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == fixture.result.run.run_id,
                DomainEventModel.event_type == SseEventType.SESSION_STATUS_CHANGED,
            )
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert event is not None
        assert event.payload["status"] == "completed"


def test_terminal_terminated_result_projects_system_status(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    terminal_result = RuntimeTerminalResult(
        run_id=fixture.result.run.run_id,
        status=GraphThreadStatus.TERMINATED,
        thread=GraphThreadRef(
            thread_id=fixture.result.run.graph_thread_ref,
            run_id=fixture.result.run.run_id,
            status=GraphThreadStatus.TERMINATED,
            current_stage_run_id=None,
            current_stage_type=None,
        ),
        trace_context=fixture.command.trace_context,
    )
    fake_engine = CapturingRuntimeEngine(start_result=terminal_result)
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        assert run is not None
        assert run.status is RunStatus.TERMINATED
        assert run.current_stage_run_id is None
        assert run.ended_at is not None

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.TERMINATED

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == fixture.result.run.run_id,
                DomainEventModel.event_type == SseEventType.SYSTEM_STATUS,
            )
            .one()
        )
        assert event.payload["system_status"]["status"] == "terminated"


def test_default_engine_factory_uses_persisted_template_snapshot_after_template_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _start_first_run(tmp_path)
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        snapshot_artifact = (
            session.query(StageArtifactModel)
            .filter(
                StageArtifactModel.run_id == fixture.result.run.run_id,
                StageArtifactModel.artifact_type == "template_snapshot",
            )
            .one()
        )
        persisted_prompt = snapshot_artifact.process["template_snapshot"][
            "stage_role_bindings"
        ][0]["system_prompt"]

    mutated_prompt = "MUTATED TEMPLATE PROMPT SHOULD NOT EXECUTE"
    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        template = session.get(
            runtime_dispatch_module.PipelineTemplateModel,
            fixture.result.session.selected_template_id,
        )
        assert template is not None
        bindings = [dict(binding) for binding in template.stage_role_bindings]
        bindings[0]["system_prompt"] = mutated_prompt
        template.stage_role_bindings = bindings
        template.updated_at = datetime.now(UTC)
        session.add(template)
        session.commit()

    captured_template_snapshots: list[Any] = []

    class CapturingStageAgentRuntime:
        def __init__(self, **kwargs: Any) -> None:
            captured_template_snapshots.append(kwargs["template_snapshot"])

        def run_stage(self, invocation: Any) -> Any:
            from backend.app.runtime.stage_runner_port import StageNodeResult

            return StageNodeResult(
                run_id=invocation.run_id,
                stage_run_id=invocation.stage_run_id,
                stage_type=invocation.stage_type,
                status=StageStatus.COMPLETED,
                artifact_refs=[],
                domain_event_refs=[],
                log_summary_refs=[],
                audit_refs=[],
            )

    class CapturingLangGraphRuntimeEngine:
        def __init__(self, **kwargs: Any) -> None:
            self.stage_runner = kwargs["stage_runner"]

    monkeypatch.setattr(
        runtime_dispatch_module,
        "StageAgentRuntime",
        CapturingStageAgentRuntime,
    )
    monkeypatch.setattr(
        runtime_dispatch_module,
        "LangGraphRuntimeEngine",
        CapturingLangGraphRuntimeEngine,
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )
    factory_input = _factory_input_for_fixture(service, fixture)

    try:
        engine = service._default_engine_factory(factory_input)  # noqa: SLF001
        from backend.app.runtime.stage_runner_port import StageNodeInvocation

        engine.stage_runner.run_stage(
            StageNodeInvocation(
                run_id=fixture.result.run.run_id,
                stage_run_id=fixture.result.stage.stage_run_id,
                stage_type=fixture.result.stage.stage_type,
                graph_node_key="requirement_analysis",
                stage_contract_ref="requirement_analysis",
                runtime_context=factory_input.context,
                trace_context=factory_input.context.trace_context,
            )
        )
    finally:
        factory_input.control_session.close()
        factory_input.runtime_session.close()
        factory_input.graph_session.close()
        factory_input.event_session.close()
        factory_input.log_session.close()

    assert len(captured_template_snapshots) == 1
    template_snapshot = captured_template_snapshots[0]
    assert template_snapshot.stage_role_bindings[0].system_prompt == persisted_prompt
    assert template_snapshot.stage_role_bindings[0].system_prompt != mutated_prompt


def test_default_engine_factory_passes_persisted_context_to_stage_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _start_first_run(tmp_path)
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        prior_artifact = StageArtifactModel(
            artifact_id="artifact-prior-solution",
            run_id=fixture.result.run.run_id,
            stage_run_id=fixture.result.stage.stage_run_id,
            artifact_type="solution_design_artifact",
            payload_ref="stage-artifact://artifact-prior-solution/output",
            process={
                "tool_call_ref": "tool-call://runtime-dispatch/prior",
                "reasoning_trace_ref": "reasoning://runtime-dispatch/prior",
            },
            metrics={},
            created_at=NOW,
        )
        clarification = ClarificationRecordModel(
            clarification_id="clarification-context-runtime-dispatch",
            run_id=fixture.result.run.run_id,
            stage_run_id=fixture.result.stage.stage_run_id,
            question="Which module should be changed?",
            answer="Use the production runtime dispatcher.",
            payload_ref="payload://clarification-context-runtime-dispatch",
            graph_interrupt_ref="interrupt-clarification-context-runtime-dispatch",
            requested_at=NOW,
            answered_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        approval_request = ApprovalRequestModel(
            approval_id="approval-context-runtime-dispatch",
            run_id=fixture.result.run.run_id,
            stage_run_id=fixture.result.stage.stage_run_id,
            approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
            status=ApprovalStatus.APPROVED,
            payload_ref="approval-request://approval-context-runtime-dispatch",
            graph_interrupt_ref="interrupt-approval-context-runtime-dispatch",
            requested_at=NOW,
            resolved_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        approval_decision = ApprovalDecisionModel(
            decision_id="approval-decision-context-runtime-dispatch",
            approval_id="approval-context-runtime-dispatch",
            run_id=fixture.result.run.run_id,
            decision=ApprovalStatus.APPROVED,
            reason="Design accepted.",
            decided_by_actor_id="session-user",
            decided_at=NOW,
            created_at=NOW,
        )
        session.add_all([prior_artifact, clarification, approval_request])
        session.flush()
        session.add(approval_decision)
        session.commit()

    CapturingStageAgentRuntime.instances = []
    monkeypatch.setattr(
        runtime_dispatch_module,
        "StageAgentRuntime",
        CapturingStageAgentRuntime,
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )
    factory_input = _factory_input_for_fixture(service, fixture)

    try:
        engine = service._default_engine_factory(factory_input)  # noqa: SLF001
        from backend.app.runtime.stage_runner_port import StageNodeInvocation

        engine._stage_runner.run_stage(  # noqa: SLF001
            StageNodeInvocation(
                run_id=fixture.result.run.run_id,
                stage_run_id=fixture.result.stage.stage_run_id,
                stage_type=fixture.result.stage.stage_type,
                graph_node_key="requirement_analysis",
                stage_contract_ref="requirement_analysis",
                runtime_context=factory_input.context,
                trace_context=factory_input.context.trace_context,
            )
        )
    finally:
        factory_input.control_session.close()
        factory_input.runtime_session.close()
        factory_input.graph_session.close()
        factory_input.event_session.close()
        factory_input.log_session.close()

    assert len(CapturingStageAgentRuntime.instances) == 1
    kwargs = CapturingStageAgentRuntime.instances[0].kwargs
    assert any(
        artifact.artifact_id == "artifact-prior-solution"
        for artifact in kwargs["stage_artifacts"]
    )
    assert any(
        item.clarification_id == "clarification-context-runtime-dispatch"
        for item in kwargs["clarifications"]
    )
    assert any(
        item.decision_id == "approval-decision-context-runtime-dispatch"
        for item in kwargs["approval_decisions"]
    )


def test_default_engine_factory_reuses_checkpointer_across_engine_instances(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _start_first_run(tmp_path)
    captured_checkpointers: list[Any] = []

    class CapturingLangGraphRuntimeEngine:
        def __init__(self, **kwargs: Any) -> None:
            captured_checkpointers.append(kwargs["checkpointer"])

    monkeypatch.setattr(
        runtime_dispatch_module,
        "LangGraphRuntimeEngine",
        CapturingLangGraphRuntimeEngine,
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )

    control_session = fixture.manager.session(DatabaseRole.CONTROL)
    runtime_session = fixture.manager.session(DatabaseRole.RUNTIME)
    graph_session = fixture.manager.session(DatabaseRole.GRAPH)
    event_session = fixture.manager.session(DatabaseRole.EVENT)
    log_session = fixture.manager.session(DatabaseRole.LOG)
    try:
        log_writer = JsonlLogWriter(
            RuntimeDataSettings.from_environment_settings(fixture.settings)
        )
        context = service._build_context(  # noqa: SLF001
            run_id=fixture.result.run.run_id,
            trace_context=fixture.command.trace_context,
            runtime_session=runtime_session,
            graph_session=graph_session,
            span_prefix="runtime-execution-start",
        )
        factory_input = RuntimeEngineFactoryInput(
            context=context,
            control_session=control_session,
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
            log_session=log_session,
            environment_settings=fixture.settings,
            log_writer=log_writer,
            now=lambda: NOW,
        )

        service._default_engine_factory(factory_input)  # noqa: SLF001
        service._default_engine_factory(factory_input)  # noqa: SLF001
    finally:
        control_session.close()
        runtime_session.close()
        graph_session.close()
        event_session.close()
        log_session.close()

    assert len(captured_checkpointers) == 2
    assert captured_checkpointers[0] is captured_checkpointers[1]


def test_default_engine_factory_starts_next_stage_before_projecting_run_next(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _start_first_run(tmp_path)
    captured_stage_configs: list[dict[str, Any]] = []

    class CompletingStageAgentRuntime:
        def __init__(self, **kwargs: Any) -> None:
            captured_stage_configs.append(
                {
                    "model_binding_stage_type": kwargs[
                        "model_binding_snapshot"
                    ].stage_type,
                    "task_objective": kwargs["task_objective"],
                    "response_schema": kwargs["response_schema"],
                    "output_schema_ref": kwargs["output_schema_ref"],
                }
            )

        def run_stage(self, invocation: Any) -> Any:
            from backend.app.runtime.stage_runner_port import StageNodeResult

            return StageNodeResult(
                run_id=invocation.run_id,
                stage_run_id=invocation.stage_run_id,
                stage_type=invocation.stage_type,
                status=StageStatus.COMPLETED,
                artifact_refs=[],
                domain_event_refs=[],
                log_summary_refs=[],
                audit_refs=[],
            )

    monkeypatch.setattr(
        runtime_dispatch_module,
        "StageAgentRuntime",
        CompletingStageAgentRuntime,
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )

    service.dispatch_started_run(fixture.command)

    solution_stage_id = (
        f"stage-run-{fixture.result.run.run_id}-{StageType.SOLUTION_DESIGN.value}"
    )
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        requirement_stage = session.get(
            StageRunModel,
            fixture.result.stage.stage_run_id,
        )
        solution_stage = session.get(StageRunModel, solution_stage_id)
        assert run is not None
        assert requirement_stage is not None
        assert solution_stage is not None
        assert requirement_stage.status is StageStatus.COMPLETED
        assert solution_stage.status is StageStatus.COMPLETED
        assert solution_stage.stage_type is StageType.SOLUTION_DESIGN
        assert run.status is RunStatus.COMPLETED
        assert run.current_stage_run_id is None

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.COMPLETED
        assert control_session.latest_stage_type is StageType.DELIVERY_INTEGRATION

    assert [
        config["model_binding_stage_type"] for config in captured_stage_configs
    ][:2] == [StageType.REQUIREMENT_ANALYSIS, StageType.SOLUTION_DESIGN]
    assert captured_stage_configs[1]["output_schema_ref"] == (
        "schema://stage-agent/solution_design"
    )
    requirement_schema = captured_stage_configs[0]["response_schema"]
    assert requirement_schema["type"] == "object"
    assert "decision_type" in requirement_schema["required"]
    assert requirement_schema["properties"]["decision_type"]["enum"] == [
        "request_tool_confirmation",
        "submit_stage_artifact",
        "request_clarification",
        "repair_structured_output",
        "retry_with_revised_plan",
        "fail_stage",
    ]


def test_dispatch_started_run_default_dispatcher_drives_until_final_stage_completed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _start_first_run(tmp_path)
    captured_stage_types: list[StageType] = []

    class CompletingStageAgentRuntime:
        def __init__(self, **kwargs: Any) -> None:
            captured_stage_types.append(kwargs["model_binding_snapshot"].stage_type)

        def run_stage(self, invocation: Any) -> Any:
            from backend.app.runtime.stage_runner_port import StageNodeResult

            return StageNodeResult(
                run_id=invocation.run_id,
                stage_run_id=invocation.stage_run_id,
                stage_type=invocation.stage_type,
                status=StageStatus.COMPLETED,
                artifact_refs=[],
                domain_event_refs=[],
                log_summary_refs=[],
                audit_refs=[],
            )

    monkeypatch.setattr(
        runtime_dispatch_module,
        "StageAgentRuntime",
        CompletingStageAgentRuntime,
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )

    service.dispatch_started_run(fixture.command)

    expected_stages = [
        StageType.REQUIREMENT_ANALYSIS,
        StageType.SOLUTION_DESIGN,
        StageType.CODE_GENERATION,
        StageType.TEST_GENERATION_EXECUTION,
        StageType.CODE_REVIEW,
        StageType.DELIVERY_INTEGRATION,
    ]
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stages = (
            session.query(StageRunModel)
            .filter(StageRunModel.run_id == fixture.result.run.run_id)
            .order_by(StageRunModel.created_at.asc(), StageRunModel.stage_run_id.asc())
            .all()
        )
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.current_stage_run_id is None
        assert [stage.stage_type for stage in stages] == expected_stages
        assert all(stage.status is StageStatus.COMPLETED for stage in stages)

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.COMPLETED

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert thread is not None
        assert thread.status == "completed"

    assert captured_stage_types == expected_stages


def test_resume_default_dispatcher_continues_after_completed_resume_step(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _start_first_run(tmp_path)
    interrupt = _persist_waiting_clarification_interrupt(fixture)
    resume_payload = RuntimeResumePayload(
        resume_id="resume-runtime-dispatch-auto-continue",
        payload_ref="payload-runtime-dispatch-auto-continue",
        values={"answer": "Continue."},
    )
    run_next_calls = 0

    class CompletingStageAgentRuntime:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        def run_stage(self, invocation: Any) -> Any:
            from backend.app.runtime.stage_runner_port import StageNodeResult

            return StageNodeResult(
                run_id=invocation.run_id,
                stage_run_id=invocation.stage_run_id,
                stage_type=invocation.stage_type,
                status=StageStatus.COMPLETED,
                artifact_refs=[],
                domain_event_refs=[],
                log_summary_refs=[],
                audit_refs=[],
            )

    class ResumeThenTerminalLangGraphRuntimeEngine:
        def __init__(self, **kwargs: Any) -> None:
            self.stage_runner = kwargs["stage_runner"]

        def start(self, *, context, runtime_port, checkpoint_port):  # noqa: ANN001
            del context, runtime_port, checkpoint_port
            raise AssertionError("start should not be called")

        def resume(  # noqa: ANN001
            self,
            *,
            context,
            interrupt,
            resume_payload,
            runtime_port,
            checkpoint_port,
        ):
            del context, checkpoint_port
            runtime_port.resume_interrupt(
                interrupt=interrupt.interrupt_ref,
                resume_payload=resume_payload,
                trace_context=interrupt.trace_context,
            )
            return RuntimeStepResult(
                run_id=interrupt.run_id,
                stage_run_id=interrupt.stage_run_id,
                stage_type=interrupt.stage_type,
                status=StageStatus.COMPLETED,
                trace_context=interrupt.trace_context,
                artifact_refs=[],
                domain_event_refs=[],
                log_summary_refs=[],
                audit_refs=[],
            )

        def run_next(self, *, context, runtime_port, checkpoint_port):  # noqa: ANN001
            del runtime_port, checkpoint_port
            nonlocal run_next_calls
            run_next_calls += 1
            if run_next_calls == 1:
                from backend.app.runtime.stage_runner_port import StageNodeInvocation

                stage_run_id = (
                    f"stage-run-{context.run_id}-{StageType.SOLUTION_DESIGN.value}"
                )
                stage_trace = context.trace_context.child_span(
                    span_id="runtime-dispatch-resume-solution-design",
                    created_at=NOW,
                    run_id=context.run_id,
                    stage_run_id=stage_run_id,
                    graph_thread_id=context.thread.thread_id,
                )
                result = self.stage_runner.run_stage(
                    StageNodeInvocation(
                        run_id=context.run_id,
                        stage_run_id=stage_run_id,
                        stage_type=StageType.SOLUTION_DESIGN,
                        graph_node_key=StageType.SOLUTION_DESIGN.value,
                        stage_contract_ref=(
                            f"{context.graph_definition_ref}/stage-contracts/"
                            f"{StageType.SOLUTION_DESIGN.value}"
                        ),
                        runtime_context=context,
                        trace_context=stage_trace,
                    )
                )
                return RuntimeStepResult(
                    run_id=result.run_id,
                    stage_run_id=result.stage_run_id,
                    stage_type=result.stage_type,
                    status=result.status,
                    trace_context=stage_trace,
                    artifact_refs=result.artifact_refs,
                    domain_event_refs=result.domain_event_refs,
                    log_summary_refs=result.log_summary_refs,
                    audit_refs=result.audit_refs,
                )
            return RuntimeTerminalResult(
                run_id=context.run_id,
                status=GraphThreadStatus.COMPLETED,
                thread=GraphThreadRef(
                    thread_id=context.thread.thread_id,
                    run_id=context.run_id,
                    status=GraphThreadStatus.COMPLETED,
                    current_stage_run_id=None,
                    current_stage_type=None,
                ),
                trace_context=context.trace_context,
            )

    monkeypatch.setattr(
        runtime_dispatch_module,
        "StageAgentRuntime",
        CompletingStageAgentRuntime,
    )
    monkeypatch.setattr(
        runtime_dispatch_module,
        "LangGraphRuntimeEngine",
        ResumeThenTerminalLangGraphRuntimeEngine,
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )

    service.resume(
        interrupt=interrupt,
        resume_payload=resume_payload,
        trace_context=interrupt.trace_context,
    )

    assert run_next_calls == 2
    solution_stage_id = (
        f"stage-run-{fixture.result.run.run_id}-{StageType.SOLUTION_DESIGN.value}"
    )
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        solution_stage = session.get(StageRunModel, solution_stage_id)
        assert run is not None
        assert solution_stage is not None
        assert run.status is RunStatus.COMPLETED
        assert run.current_stage_run_id is None
        assert solution_stage.status is StageStatus.COMPLETED

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.COMPLETED


def test_dispatch_started_run_default_dispatcher_allows_auto_regression_retry_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _start_first_run(tmp_path)
    captured_stage_types: list[StageType] = []
    route_retry_once = True

    class CompletingStageAgentRuntime:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        def run_stage(self, invocation: Any) -> Any:
            from backend.app.runtime.stage_runner_port import StageNodeResult

            nonlocal route_retry_once
            captured_stage_types.append(invocation.stage_type)
            route_key = None
            if invocation.stage_type is StageType.CODE_REVIEW and route_retry_once:
                route_key = "review_regression_retry"
                route_retry_once = False
            return StageNodeResult(
                run_id=invocation.run_id,
                stage_run_id=invocation.stage_run_id,
                stage_type=invocation.stage_type,
                status=StageStatus.COMPLETED,
                artifact_refs=[],
                domain_event_refs=[],
                log_summary_refs=[],
                audit_refs=[],
                route_key=route_key,
            )

    monkeypatch.setattr(
        runtime_dispatch_module,
        "StageAgentRuntime",
        CompletingStageAgentRuntime,
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )

    service.dispatch_started_run(fixture.command)

    assert captured_stage_types == [
        StageType.REQUIREMENT_ANALYSIS,
        StageType.SOLUTION_DESIGN,
        StageType.CODE_GENERATION,
        StageType.TEST_GENERATION_EXECUTION,
        StageType.CODE_REVIEW,
        StageType.CODE_GENERATION,
        StageType.TEST_GENERATION_EXECUTION,
        StageType.CODE_REVIEW,
        StageType.DELIVERY_INTEGRATION,
    ]
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.current_stage_run_id is None


def test_default_checkpointer_persists_across_service_instances(tmp_path: Path) -> None:
    from langgraph.checkpoint.base import empty_checkpoint

    fixture = _start_first_run(tmp_path)
    first_service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )
    second_service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )
    checkpoint = empty_checkpoint()
    saved_config = first_service._default_checkpointer().put(  # noqa: SLF001
        {
            "configurable": {
                "thread_id": "graph-thread-persistent-checkpointer",
                "checkpoint_ns": "",
            }
        },
        checkpoint,
        {},
        {},
    )

    loaded = second_service._default_checkpointer().get_tuple(saved_config)  # noqa: SLF001

    assert loaded is not None
    assert loaded.checkpoint["id"] == checkpoint["id"]


def _start_first_run(tmp_path: Path) -> StartedRunFixture:
    from backend.app.services.sessions import SessionService

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            result = SessionService(
                control_session,
                runtime_session=runtime_session,
                event_session=event_session,
                graph_session=graph_session,
                audit_service=audit,
                log_writer=log_writer,
                environment_settings=settings,
                now=lambda: NOW,
            ).start_run_from_new_requirement(
                session_id=draft.session_id,
                content="Implement production runtime dispatch.",
                trace_context=build_trace(),
            )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    parent_trace = build_trace()
    command_trace = TraceContext.model_validate(
        {
            **parent_trace.model_dump(),
            "trace_id": result.run.trace_id,
            "span_id": f"runtime-dispatch-started-{result.run.run_id}",
            "parent_span_id": parent_trace.span_id,
            "created_at": datetime.now(UTC),
            "session_id": result.session.session_id,
            "run_id": result.run.run_id,
            "stage_run_id": result.stage.stage_run_id,
            "graph_thread_id": result.run.graph_thread_ref,
        }
    )
    command = RuntimeDispatchCommand(
        session_id=result.session.session_id,
        run_id=result.run.run_id,
        stage_run_id=result.stage.stage_run_id,
        stage_type=result.stage.stage_type,
        graph_thread_id=result.run.graph_thread_ref,
        trace_context=command_trace,
    )
    return StartedRunFixture(
        settings=settings,
        manager=manager,
        result=result,
        command=command,
    )


def _factory_input_for_fixture(
    service: RuntimeExecutionService,
    fixture: StartedRunFixture,
) -> RuntimeEngineFactoryInput:
    control_session = fixture.manager.session(DatabaseRole.CONTROL)
    runtime_session = fixture.manager.session(DatabaseRole.RUNTIME)
    graph_session = fixture.manager.session(DatabaseRole.GRAPH)
    event_session = fixture.manager.session(DatabaseRole.EVENT)
    log_session = fixture.manager.session(DatabaseRole.LOG)
    log_writer = JsonlLogWriter(
        RuntimeDataSettings.from_environment_settings(fixture.settings)
    )
    context = service._build_context(  # noqa: SLF001
        run_id=fixture.result.run.run_id,
        trace_context=fixture.command.trace_context,
        runtime_session=runtime_session,
        graph_session=graph_session,
        span_prefix="runtime-execution-start",
    )
    return RuntimeEngineFactoryInput(
        context=context,
        control_session=control_session,
        runtime_session=runtime_session,
        graph_session=graph_session,
        event_session=event_session,
        log_session=log_session,
        environment_settings=fixture.settings,
        log_writer=log_writer,
        now=lambda: NOW,
    )


def _persist_waiting_clarification_interrupt(
    fixture: StartedRunFixture,
) -> RuntimeInterrupt:
    with fixture.manager.session(DatabaseRole.GRAPH) as graph_session:
        thread = GraphThreadRef(
            thread_id=fixture.result.run.graph_thread_ref,
            run_id=fixture.result.run.run_id,
            status=GraphThreadStatus.RUNNING,
            current_stage_run_id=fixture.result.stage.stage_run_id,
            current_stage_type=fixture.result.stage.stage_type,
        )
        checkpoint = GraphCheckpointPort(graph_session, now=lambda: NOW).save_checkpoint(
            thread=thread,
            purpose=CheckpointPurpose.WAITING_CLARIFICATION,
            trace_context=fixture.command.trace_context,
            stage_run_id=fixture.result.stage.stage_run_id,
            stage_type=fixture.result.stage.stage_type,
            payload_ref="graph-checkpoint://runtime-dispatch/resume-failure",
        )
        interrupt_ref = GraphRuntimeCommandPort(
            graph_session,
            now=lambda: NOW,
        ).create_interrupt(
            thread=thread,
            interrupt_type=GraphInterruptType.CLARIFICATION_REQUEST,
            run_id=fixture.result.run.run_id,
            stage_run_id=fixture.result.stage.stage_run_id,
            stage_type=fixture.result.stage.stage_type,
            payload_ref="clarification-payload-runtime-dispatch",
            checkpoint=checkpoint,
            trace_context=fixture.command.trace_context,
            clarification_id="clarification-runtime-dispatch",
        )
        graph_session.commit()

    with fixture.manager.session(DatabaseRole.RUNTIME) as runtime_session:
        run = runtime_session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = runtime_session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        run.status = RunStatus.WAITING_CLARIFICATION
        stage.status = StageStatus.WAITING_CLARIFICATION
        runtime_session.add_all([run, stage])
        runtime_session.commit()

    with fixture.manager.session(DatabaseRole.CONTROL) as control_session:
        session = control_session.get(SessionModel, fixture.result.session.session_id)
        assert session is not None
        session.status = SessionStatus.WAITING_CLARIFICATION
        control_session.add(session)
        control_session.commit()

    return RuntimeInterrupt(
        run_id=fixture.result.run.run_id,
        stage_run_id=fixture.result.stage.stage_run_id,
        stage_type=fixture.result.stage.stage_type,
        interrupt_ref=interrupt_ref,
        payload_ref=interrupt_ref.payload_ref,
        trace_context=fixture.command.trace_context,
    )


def _step_result(
    context,
    *,
    status: StageStatus = StageStatus.RUNNING,
) -> RuntimeStepResult:  # noqa: ANN001
    assert context.thread.current_stage_run_id is not None
    assert context.thread.current_stage_type is not None
    return RuntimeStepResult(
        run_id=context.run_id,
        stage_run_id=context.thread.current_stage_run_id,
        stage_type=context.thread.current_stage_type,
        status=status,
        trace_context=context.trace_context,
        artifact_refs=[],
        domain_event_refs=[],
        log_summary_refs=[],
        audit_refs=[],
    )


def _runtime_interrupt(fixture: StartedRunFixture) -> RuntimeInterrupt:
    checkpoint = CheckpointRef(
        checkpoint_id="checkpoint-runtime-dispatch",
        thread_id=fixture.result.run.graph_thread_ref,
        run_id=fixture.result.run.run_id,
        stage_run_id=fixture.result.stage.stage_run_id,
        stage_type=fixture.result.stage.stage_type,
        purpose=CheckpointPurpose.WAITING_CLARIFICATION,
        payload_ref="graph-checkpoint://runtime-dispatch",
    )
    thread_ref = GraphThreadRef(
        thread_id=fixture.result.run.graph_thread_ref,
        run_id=fixture.result.run.run_id,
        status=GraphThreadStatus.WAITING_CLARIFICATION,
        current_stage_run_id=fixture.result.stage.stage_run_id,
        current_stage_type=fixture.result.stage.stage_type,
        checkpoint_id=checkpoint.checkpoint_id,
    )
    interrupt_ref = GraphInterruptRef(
        interrupt_id="interrupt-runtime-dispatch",
        thread=thread_ref,
        interrupt_type=GraphInterruptType.CLARIFICATION_REQUEST,
        status=GraphInterruptStatus.PENDING,
        run_id=fixture.result.run.run_id,
        stage_run_id=fixture.result.stage.stage_run_id,
        stage_type=fixture.result.stage.stage_type,
        payload_ref="clarification-runtime-dispatch",
        clarification_id="clarification-runtime-dispatch",
        checkpoint_ref=checkpoint,
    )
    return RuntimeInterrupt(
        run_id=fixture.result.run.run_id,
        stage_run_id=fixture.result.stage.stage_run_id,
        stage_type=fixture.result.stage.stage_type,
        interrupt_ref=interrupt_ref,
        payload_ref="clarification-runtime-dispatch",
        trace_context=fixture.command.trace_context.child_span(
            span_id="runtime-interrupt-runtime-dispatch",
            created_at=NOW,
            stage_run_id=fixture.result.stage.stage_run_id,
            graph_thread_id=fixture.result.run.graph_thread_ref,
        ),
    )
