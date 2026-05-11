from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
import threading
from typing import Any

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.graph import (
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
    ToolRiskCategory,
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
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
from backend.app.services.tool_confirmations import ToolConfirmationService
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
        artifact_refs: list[str] | None = None,
        start_result: Any | None = None,
    ) -> None:
        self.fail_start_with = fail_start_with
        self.step_status = step_status
        self.artifact_refs = artifact_refs or []
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
        return _step_result(
            context,
            status=self.step_status,
            artifact_refs=self.artifact_refs,
        )

    def run_next(self, *, context, runtime_port, checkpoint_port):  # noqa: ANN001
        self.run_next_calls.append(
            EngineCall(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
            )
        )
        return _step_result(
            context,
            status=self.step_status,
            artifact_refs=self.artifact_refs,
        )

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
        return _step_result(
            context,
            status=self.step_status,
            artifact_refs=self.artifact_refs,
        )


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


class ResumingStageToolConfirmationEngine:
    def __init__(self) -> None:
        self.resume_calls: list[EngineCall] = []
        self.stage_tool_confirmation_resume_calls: list[EngineCall] = []

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
        del context, interrupt, resume_payload, runtime_port, checkpoint_port
        raise AssertionError("graph resume should not be called")

    def resume_stage_tool_confirmation(  # noqa: ANN001
        self,
        *,
        context,
        interrupt,
        resume_payload,
        runtime_port,
        checkpoint_port,
    ):
        self.stage_tool_confirmation_resume_calls.append(
            EngineCall(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
                interrupt=interrupt,
                resume_payload=resume_payload,
            )
        )
        runtime_port.resume_tool_confirmation(
            interrupt=interrupt.interrupt_ref,
            resume_payload=resume_payload,
            trace_context=interrupt.trace_context,
        )
        return _step_result(context, status=StageStatus.COMPLETED)


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


def test_resume_async_spawns_background_worker_without_waiting(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: CapturingRuntimeEngine(),
    )
    interrupt = _runtime_interrupt(fixture)
    resume_payload = RuntimeResumePayload(
        resume_id="resume-runtime-dispatch-async",
        payload_ref="payload-runtime-dispatch-async",
        values={"answer": "Continue."},
    )
    started = threading.Event()
    release = threading.Event()
    recorded: list[tuple[RuntimeInterrupt, RuntimeResumePayload, TraceContext]] = []

    def blocking_resume(*, interrupt, resume_payload, trace_context):  # noqa: ANN001
        recorded.append((interrupt, resume_payload, trace_context))
        started.set()
        release.wait(timeout=5)
        return None

    service.resume = blocking_resume  # type: ignore[method-assign]

    service.resume_async(
        interrupt=interrupt,
        resume_payload=resume_payload,
        trace_context=fixture.command.trace_context,
    )

    assert started.wait(timeout=2)
    assert recorded == [
        (interrupt, resume_payload, fixture.command.trace_context)
    ]
    release.set()


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


def test_completed_step_result_projects_stage_process_records_as_feed_items(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            StageArtifactModel(
                artifact_id="artifact-stage-progress",
                run_id=fixture.result.run.run_id,
                stage_run_id=fixture.result.stage.stage_run_id,
                artifact_type="requirement_intake_stage_agent_stage",
                payload_ref="stage-artifact://artifact-stage-progress/output",
                process={
                    "model_call_trace": {
                        "model_call_ref": "model-call-1",
                        "provider_id": "openai",
                        "model_id": "gpt-5.2",
                        "model_call_type": "stage_execution",
                        "usage": {
                            "input_tokens": 120,
                            "output_tokens": 42,
                            "total_tokens": 162,
                        },
                        "display_summary": (
                            "Need to inspect the workspace tool implementation."
                        ),
                        "raw_output_text": (
                            "I need to inspect the workspace tool implementation "
                            "before answering."
                        ),
                        "input_summary": {
                            "excerpt": "User asked what code search mode is active.",
                            "content_hash": "sha256:input",
                        },
                        "output_summary": {
                            "excerpt": (
                                "I need to inspect the workspace tool implementation "
                                "before answering."
                            ),
                            "content_hash": "sha256:output",
                        },
                    },
                    "decision_trace": {
                        "trace_ref": "decision-trace-1",
                        "decision_type": "submit_stage_artifact",
                        "status": "accepted",
                        "safe_message": "Selected the structured artifact path.",
                    },
                    "tool_trace": {
                        "tool_name": "read_workspace",
                        "call_id": "tool-call-1",
                        "status": "succeeded",
                        "artifact_refs": ["tool-artifact-1"],
                        "output_preview": "workspace tools include grep, glob, and read_file",
                        "safe_details": {"summary": "Read workspace state."},
                        "input_payload_summary": {
                            "path": "backend/app/workspace/tools.py",
                            "limit": 60,
                        },
                    },
                    "change_set": {
                        "change_set_id": "changeset-1",
                        "summary": "Updated workspace feed projection.",
                        "changed_files": ["frontend/src/features/feed/StageNode.tsx"],
                        "diff_refs": ["diff://changeset-1/feed"],
                    },
                    "output_snapshot": {
                        "artifact_type": "requirement_summary",
                        "risk_summary": "Ready for the next stage.",
                    },
                    "output_refs": ["evidence://requirement-summary"],
                },
                metrics={},
                created_at=NOW,
            )
        )
        session.commit()
    fake_engine = CapturingRuntimeEngine(
        step_status=StageStatus.COMPLETED,
        artifact_refs=["artifact-stage-progress"],
    )
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(fixture.command)

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        stage_updated = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == fixture.result.run.run_id,
                DomainEventModel.event_type == "stage_updated",
            )
            .one()
        )
        items = stage_updated.payload["stage_node"]["items"]
        item_types = [item["type"] for item in items]
        assert item_types == [
            "model_call",
            "decision",
            "tool_call",
            "diff_preview",
            "result",
        ]
        assert items[0]["title"] == "Call gpt-5.2"
        assert items[0]["metrics"]["total_tokens"] == 162
        assert "inspect the workspace tool implementation" in items[0]["summary"]
        assert items[0]["content"] == (
            "I need to inspect the workspace tool implementation before answering."
        )
        assert items[1]["content"] is None
        assert "Selected the structured artifact path." in items[1]["summary"]
        assert items[2]["title"] == (
            "read_workspace path=backend/app/workspace/tools.py limit=60"
        )
        assert items[2]["summary"] == "Read workspace state."
        assert "backend/app/workspace/tools.py" in items[2]["content"]
        assert items[2]["artifact_refs"] == ["tool-artifact-1"]
        assert "frontend/src/features/feed/StageNode.tsx" in items[3]["content"]
        assert "artifact-stage-progress" in items[4]["artifact_refs"]
        assert "evidence://requirement-summary" in items[4]["artifact_refs"]
        assert "Ready for the next stage." in items[4]["content"]


def test_stage_progress_callback_publishes_realtime_stage_update(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
    )
    factory_input = _factory_input_for_fixture(service, fixture)
    try:
        engine = service._default_engine_factory(factory_input)  # noqa: SLF001
        with fixture.manager.session(DatabaseRole.RUNTIME) as session:
            session.add(
                StageArtifactModel(
                    artifact_id="artifact-realtime-progress",
                    run_id=fixture.result.run.run_id,
                    stage_run_id=fixture.result.stage.stage_run_id,
                    artifact_type="requirement_intake_stage_agent_stage",
                    payload_ref="stage-artifact://artifact-realtime-progress/input",
                    process={
                        "model_call_trace": {
                            "model_call_ref": "model-call-realtime",
                            "provider_id": "openai",
                            "model_id": "gpt-5.2",
                            "usage": {"total_tokens": 12},
                        }
                    },
                    metrics={},
                    created_at=NOW,
                )
            )
            session.commit()

        request = SimpleNamespace(
            invocation=SimpleNamespace(
                run_id=fixture.result.run.run_id,
                stage_run_id=fixture.result.stage.stage_run_id,
                trace_context=fixture.command.trace_context,
                runtime_context=SimpleNamespace(
                    session_id=fixture.result.session.session_id
                ),
            ),
            stage_artifact_id="artifact-realtime-progress",
        )

        engine._stage_runner._publish_stage_progress(  # noqa: SLF001
            request,
            "model_call_trace",
            "stage-artifact://artifact-realtime-progress#process/model_call_trace",
        )
    finally:
        factory_input.control_session.close()
        factory_input.runtime_session.close()
        factory_input.graph_session.close()
        factory_input.event_session.close()
        factory_input.log_session.close()

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == fixture.result.run.run_id,
                DomainEventModel.event_type == "stage_updated",
            )
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert event is not None
        assert event.payload["stage_node"]["items"][0]["type"] == "model_call"
        assert event.payload["stage_node"]["items"][0]["metrics"]["total_tokens"] == 12


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


def test_waiting_tool_confirmation_step_reuses_request_created_by_stage_tool_gate(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    created_ids: list[str] = []

    class StageToolGateEngine:
        def start(self, *, context, runtime_port, checkpoint_port):  # noqa: ANN001
            created = ToolConfirmationService(
                control_session=factory_input.control_session,
                runtime_session=factory_input.runtime_session,
                event_session=factory_input.event_session,
                graph_session=factory_input.graph_session,
                runtime_orchestration=RuntimeOrchestrationService(
                    runtime_port=runtime_port,
                    checkpoint_port=checkpoint_port,
                    clock=lambda: NOW,
                ),
                log_writer=factory_input.log_writer,
                now=lambda: NOW,
            ).create_request(
                session_id=context.session_id,
                run_id=context.run_id,
                stage_run_id=context.thread.current_stage_run_id,
                confirmation_object_ref="tool-action://bash/vitest",
                tool_name="bash",
                command_preview="npx vitest run src/pages/__tests__/HomePage.test.tsx",
                target_summary="command: npx vitest run src/pages/__tests__/HomePage.test.tsx",
                risk_level=ToolRiskLevel.HIGH_RISK,
                risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
                reason="Verify the homepage copy change.",
                expected_side_effects=["Runs focused frontend tests."],
                alternative_path_summary=None,
                planned_deny_followup_action="run_failed",
                planned_deny_followup_summary=(
                    "The current run will fail because no low-risk alternative path exists."
                ),
                trace_context=context.trace_context,
            )
            created_ids.append(created.tool_confirmation_id)
            artifact_id = "artifact-stage-tool-gate-confirmation"
            factory_input.runtime_session.add(
                StageArtifactModel(
                    artifact_id=artifact_id,
                    run_id=context.run_id,
                    stage_run_id=context.thread.current_stage_run_id,
                    artifact_type="test_generation_execution_stage_agent_stage",
                    payload_ref=f"stage-artifact://{artifact_id}/input",
                    process={
                        "tool_confirmation_trace": {
                            "tool_name": "bash",
                            "tool_confirmation_ref": created.tool_confirmation_id,
                            "status": "waiting_confirmation",
                            "risk_level": "high_risk",
                            "risk_categories": ["unknown_command"],
                            "target_summary": (
                                "command: npx vitest run "
                                "src/pages/__tests__/HomePage.test.tsx"
                            ),
                        }
                    },
                    metrics={},
                    created_at=NOW,
                )
            )
            factory_input.runtime_session.commit()
            return _step_result(
                context,
                status=StageStatus.WAITING_TOOL_CONFIRMATION,
                artifact_refs=[f"stage-artifact://{artifact_id}"],
            )

    factory_input: RuntimeEngineFactoryInput

    def factory(input_: RuntimeEngineFactoryInput) -> StageToolGateEngine:
        nonlocal factory_input
        factory_input = input_
        return StageToolGateEngine()

    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=factory,
    )

    service.dispatch_started_run(fixture.command)

    assert len(created_ids) == 1
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        requests = session.query(ToolConfirmationRequestModel).all()
        assert [request.tool_confirmation_id for request in requests] == created_ids
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.WAITING_TOOL_CONFIRMATION
        assert stage.status is StageStatus.WAITING_TOOL_CONFIRMATION


def test_runtime_approval_interrupt_creates_actionable_request_and_interrupt(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    command = _move_fixture_to_stage(fixture, StageType.SOLUTION_DESIGN)
    interrupt = _runtime_approval_interrupt(
        fixture,
        stage_run_id=command.stage_run_id,
        stage_type=command.stage_type,
    )
    fake_engine = CapturingRuntimeEngine(start_result=interrupt)
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.dispatch_started_run(command)

    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.query(ApprovalRequestModel).one()
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, command.stage_run_id)
        assert approval.run_id == fixture.result.run.run_id
        assert approval.stage_run_id == command.stage_run_id
        assert approval.approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL
        assert approval.status is ApprovalStatus.PENDING
        assert approval.graph_interrupt_ref == interrupt.interrupt_ref.interrupt_id
        assert approval.payload_ref == interrupt.payload_ref
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.WAITING_APPROVAL
        assert stage.status is StageStatus.WAITING_APPROVAL

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.WAITING_APPROVAL

    with fixture.manager.session(DatabaseRole.EVENT) as session:
        event_types = {
            event.event_type
            for event in session.query(DomainEventModel)
            .filter(DomainEventModel.run_id == fixture.result.run.run_id)
            .all()
        }
        assert "approval_requested" in event_types


def test_allowed_stage_tool_gate_confirmation_resumes_current_stage(
    tmp_path: Path,
) -> None:
    fixture = _start_first_run(tmp_path)
    interrupt = _persist_waiting_tool_confirmation_interrupt(fixture)
    resume_payload = RuntimeResumePayload(
        resume_id="resume-stage-tool-gate-confirmation",
        payload_ref="tool-confirmation-runtime-dispatch",
        values={
            "decision": "allowed",
            "tool_confirmation_id": "tool-confirmation-runtime-dispatch",
            "confirmation_object_ref": "tool-call:bash:call-bash:abc123",
        },
    )
    fake_engine = ResumingStageToolConfirmationEngine()
    service = RuntimeExecutionService(
        database_manager=fixture.manager,
        environment_settings=fixture.settings,
        engine_factory=lambda _factory_input: fake_engine,
    )

    service.resume(
        interrupt=interrupt,
        resume_payload=resume_payload,
        trace_context=interrupt.trace_context,
    )

    assert fake_engine.stage_tool_confirmation_resume_calls
    assert fake_engine.stage_tool_confirmation_resume_calls[0].resume_payload == resume_payload
    assert fake_engine.resume_calls == []
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        assert run.status is RunStatus.RUNNING
        assert stage.status is StageStatus.COMPLETED

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        graph_interrupt = session.get(
            GraphInterruptModel,
            interrupt.interrupt_ref.interrupt_id,
        )
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert graph_interrupt is not None
        assert thread is not None
        assert graph_interrupt.status == "responded"
        assert thread.status == "running"
        assert thread.current_interrupt_id is None


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
    user_messages = kwargs["user_messages"]
    assert user_messages
    assert "Implement production runtime dispatch." in json.dumps(
        user_messages,
        ensure_ascii=False,
        default=str,
    )


def test_default_stage_runner_uses_workspace_tool_registry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _start_first_run(tmp_path)
    homepage = (
        fixture.settings.default_project_root
        / "frontend"
        / "src"
        / "pages"
        / "HomePage.tsx"
    )
    homepage.parent.mkdir(parents=True, exist_ok=True)
    homepage.write_text(
        "export function HomePage() { return <h1>Make delivery work traceable.</h1>; }\n",
        encoding="utf-8",
    )
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

        stage_type = StageType.TEST_GENERATION_EXECUTION
        engine._stage_runner.run_stage(  # noqa: SLF001
            StageNodeInvocation(
                run_id=fixture.result.run.run_id,
                stage_run_id=f"stage-run-{fixture.result.run.run_id}-{stage_type.value}",
                stage_type=stage_type,
                graph_node_key=stage_type.value,
                stage_contract_ref=f"{factory_input.context.graph_definition_ref}/stage-contracts/{stage_type.value}",
                runtime_context=factory_input.context,
                trace_context=factory_input.context.trace_context.child_span(
                    span_id="runtime-dispatch-test-execution-tools",
                    created_at=NOW,
                    stage_run_id=f"stage-run-{fixture.result.run.run_id}-{stage_type.value}",
                ),
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
    tool_names = {
        tool.name for tool in kwargs["tool_registry"].list_bindable_tools()
    }
    assert {
        "read_file",
        "glob",
        "grep",
        "edit_file",
        "write_file",
        "bash",
        "read_delivery_snapshot",
        "prepare_branch",
        "create_commit",
        "push_branch",
        "create_code_review_request",
    }.issubset(tool_names)
    workspace = kwargs["workspace_boundary"].workspace
    assert (workspace.root / "frontend/src/pages/HomePage.tsx").is_file()
    assert kwargs["audit_recorder"] is not None
    assert kwargs["run_log_recorder"] is not None
    assert kwargs["confirmation_port"] is not None
    assert kwargs["risk_policy"] is not None


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
        assert solution_stage.status is StageStatus.WAITING_APPROVAL
        assert solution_stage.stage_type is StageType.SOLUTION_DESIGN
        assert run.status is RunStatus.WAITING_APPROVAL
        assert run.current_stage_run_id == solution_stage.stage_run_id

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.WAITING_APPROVAL
        assert control_session.latest_stage_type is StageType.SOLUTION_DESIGN

    assert [
        config["model_binding_stage_type"] for config in captured_stage_configs
    ][:2] == [StageType.REQUIREMENT_ANALYSIS, StageType.SOLUTION_DESIGN]
    assert captured_stage_configs[1]["output_schema_ref"] == (
        "schema://stage-agent/solution_design"
    )
    requirement_schema = captured_stage_configs[0]["response_schema"]
    assert requirement_schema["type"] == "object"
    assert "decision_type" not in requirement_schema["required"]
    assert requirement_schema["properties"]["decision_type"]["enum"] == [
        "request_tool_confirmation",
        "submit_stage_artifact",
        "request_clarification",
        "retry_with_revised_plan",
        "fail_stage",
    ]
    solution_schema = captured_stage_configs[1]["response_schema"]
    assert "request_clarification" not in (
        solution_schema["properties"]["decision_type"]["enum"]
    )
    solution_wrapped_submit_schema = next(
        candidate
        for candidate in solution_schema["oneOf"]
        if candidate["properties"].get("decision_type", {}).get("const")
        == "submit_stage_artifact"
    )
    solution_bare_submit_schema = next(
        candidate
        for candidate in solution_schema["oneOf"]
        if "technical_plan" in candidate["properties"]
    )
    assert solution_wrapped_submit_schema["properties"]["artifact_type"]["const"] == (
        "SolutionDesignArtifact"
    )
    assert solution_bare_submit_schema["properties"]["artifact_type"]["const"] == (
        "SolutionDesignArtifact"
    )


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
        assert run.status is RunStatus.WAITING_APPROVAL
        assert run.current_stage_run_id is not None
        assert [stage.stage_type for stage in stages] == expected_stages
        assert stages[0].status is StageStatus.COMPLETED
        assert stages[1].status is StageStatus.WAITING_APPROVAL

    with fixture.manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, fixture.result.session.session_id)
        assert control_session is not None
        assert control_session.status is SessionStatus.WAITING_APPROVAL

    with fixture.manager.session(DatabaseRole.GRAPH) as session:
        thread = session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert thread is not None
        assert thread.status == "interrupted"

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
    ]
    with fixture.manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, fixture.result.run.run_id)
        assert run is not None
        assert run.status is RunStatus.WAITING_APPROVAL
        assert run.current_stage_run_id is not None


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


def _persist_waiting_tool_confirmation_interrupt(
    fixture: StartedRunFixture,
) -> RuntimeInterrupt:
    tool_confirmation_id = "tool-confirmation-runtime-dispatch"
    tool_action_ref = "tool-call:bash:call-bash:abc123"
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
            purpose=CheckpointPurpose.WAITING_TOOL_CONFIRMATION,
            trace_context=fixture.command.trace_context,
            stage_run_id=fixture.result.stage.stage_run_id,
            stage_type=fixture.result.stage.stage_type,
            payload_ref="graph-checkpoint://runtime-dispatch/tool-confirmation",
        )
        interrupt_ref = GraphRuntimeCommandPort(
            graph_session,
            now=lambda: NOW,
        ).create_interrupt(
            thread=thread,
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            run_id=fixture.result.run.run_id,
            stage_run_id=fixture.result.stage.stage_run_id,
            stage_type=fixture.result.stage.stage_type,
            payload_ref=tool_confirmation_id,
            checkpoint=checkpoint,
            trace_context=fixture.command.trace_context,
            tool_confirmation_id=tool_confirmation_id,
            tool_action_ref=tool_action_ref,
        )
        graph_session.commit()

    with fixture.manager.session(DatabaseRole.RUNTIME) as runtime_session:
        run = runtime_session.get(PipelineRunModel, fixture.result.run.run_id)
        stage = runtime_session.get(StageRunModel, fixture.result.stage.stage_run_id)
        assert run is not None
        assert stage is not None
        request = ToolConfirmationRequestModel(
            tool_confirmation_id=tool_confirmation_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            confirmation_object_ref=tool_action_ref,
            tool_name="bash",
            command_preview="npm --prefix frontend run build",
            target_summary="command: npm --prefix frontend run build",
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND.value],
            reason="Verify the current stage.",
            expected_side_effects=["Runs focused verification."],
            alternative_path_summary=None,
            planned_deny_followup_action="run_failed",
            planned_deny_followup_summary="The current run will fail.",
            deny_followup_action=None,
            deny_followup_summary=None,
            user_decision=None,
            status=ToolConfirmationStatus.PENDING,
            graph_interrupt_ref=interrupt_ref.interrupt_id,
            audit_log_ref=None,
            process_ref=None,
            requested_at=NOW,
            responded_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        run.status = RunStatus.WAITING_TOOL_CONFIRMATION
        stage.status = StageStatus.WAITING_TOOL_CONFIRMATION
        runtime_session.add_all([run, stage, request])
        runtime_session.commit()

    with fixture.manager.session(DatabaseRole.CONTROL) as control_session:
        session = control_session.get(SessionModel, fixture.result.session.session_id)
        assert session is not None
        session.status = SessionStatus.WAITING_TOOL_CONFIRMATION
        control_session.add(session)
        control_session.commit()

    return RuntimeInterrupt(
        run_id=fixture.result.run.run_id,
        stage_run_id=fixture.result.stage.stage_run_id,
        stage_type=fixture.result.stage.stage_type,
        interrupt_ref=interrupt_ref,
        payload_ref=interrupt_ref.payload_ref,
        trace_context=fixture.command.trace_context.child_span(
            span_id="runtime-interrupt-tool-confirmation",
            created_at=NOW,
            stage_run_id=fixture.result.stage.stage_run_id,
            tool_confirmation_id=tool_confirmation_id,
            graph_thread_id=fixture.result.run.graph_thread_ref,
        ),
    )


def _runtime_approval_interrupt(
    fixture: StartedRunFixture,
    *,
    stage_run_id: str,
    stage_type: StageType,
) -> RuntimeInterrupt:
    checkpoint = CheckpointRef(
        checkpoint_id="checkpoint-runtime-approval",
        thread_id=fixture.result.run.graph_thread_ref,
        run_id=fixture.result.run.run_id,
        stage_run_id=stage_run_id,
        stage_type=stage_type,
        purpose=CheckpointPurpose.WAITING_APPROVAL,
        payload_ref="langgraph://graph-thread-1/checkpoints/default/runtime-approval",
    )
    thread_ref = GraphThreadRef(
        thread_id=fixture.result.run.graph_thread_ref,
        run_id=fixture.result.run.run_id,
        status=GraphThreadStatus.WAITING_APPROVAL,
        current_stage_run_id=stage_run_id,
        current_stage_type=stage_type,
        checkpoint_id=checkpoint.checkpoint_id,
    )
    interrupt_ref = GraphInterruptRef(
        interrupt_id="interrupt-runtime-approval",
        thread=thread_ref,
        interrupt_type=GraphInterruptType.APPROVAL,
        status=GraphInterruptStatus.PENDING,
        run_id=fixture.result.run.run_id,
        stage_run_id=stage_run_id,
        stage_type=stage_type,
        payload_ref="approval-runtime-dispatch",
        approval_id="approval-runtime-dispatch",
        checkpoint_ref=checkpoint,
    )
    return RuntimeInterrupt(
        run_id=fixture.result.run.run_id,
        stage_run_id=stage_run_id,
        stage_type=stage_type,
        interrupt_ref=interrupt_ref,
        payload_ref="approval-runtime-dispatch",
        trace_context=fixture.command.trace_context.child_span(
            span_id="runtime-interrupt-approval",
            created_at=NOW,
            stage_run_id=stage_run_id,
            approval_id="approval-runtime-dispatch",
            graph_thread_id=fixture.result.run.graph_thread_ref,
        ),
    )


def _move_fixture_to_stage(
    fixture: StartedRunFixture,
    stage_type: StageType,
) -> RuntimeDispatchCommand:
    run_id = fixture.result.run.run_id
    stage_run_id = f"stage-run-{run_id}-{stage_type.value}"
    with fixture.manager.session(DatabaseRole.RUNTIME) as runtime_session:
        run = runtime_session.get(PipelineRunModel, run_id)
        assert run is not None
        stage = runtime_session.get(StageRunModel, stage_run_id)
        if stage is None:
            stage = StageRunModel(
                stage_run_id=stage_run_id,
                run_id=run.run_id,
                stage_type=stage_type,
                status=StageStatus.RUNNING,
                attempt_index=1,
                graph_node_key=stage_type.value,
                stage_contract_ref=f"graph-definition-run-1/stage-contracts/{stage_type.value}",
                input_ref=None,
                output_ref=None,
                summary=f"{stage_type.value} started by test fixture.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
            runtime_session.add(stage)
        original_stage = runtime_session.get(
            StageRunModel,
            fixture.result.stage.stage_run_id,
        )
        if original_stage is not None:
            original_stage.status = StageStatus.COMPLETED
            original_stage.ended_at = NOW
            original_stage.updated_at = NOW
            runtime_session.add(original_stage)
        stage.status = StageStatus.RUNNING
        stage.updated_at = NOW
        runtime_session.add(stage)
        run.current_stage_run_id = stage_run_id
        run.updated_at = NOW
        runtime_session.add(run)
        runtime_session.commit()

    with fixture.manager.session(DatabaseRole.CONTROL) as control_session:
        session = control_session.get(SessionModel, fixture.result.session.session_id)
        assert session is not None
        session.latest_stage_type = stage_type
        session.updated_at = NOW
        control_session.add(session)
        control_session.commit()

    with fixture.manager.session(DatabaseRole.GRAPH) as graph_session:
        thread = graph_session.get(GraphThreadModel, fixture.result.run.graph_thread_ref)
        assert thread is not None
        thread.current_node_key = stage_type.value
        thread.updated_at = NOW
        graph_session.add(thread)
        graph_session.commit()

    return RuntimeDispatchCommand(
        session_id=fixture.command.session_id,
        run_id=fixture.command.run_id,
        stage_run_id=stage_run_id,
        stage_type=stage_type,
        graph_thread_id=fixture.command.graph_thread_id,
        trace_context=fixture.command.trace_context.child_span(
            span_id=f"runtime-dispatch-started-{fixture.result.run.run_id}-{stage_type.value}",
            created_at=NOW,
            stage_run_id=stage_run_id,
            graph_thread_id=fixture.result.run.graph_thread_ref,
        ),
    )


def _step_result(
    context,
    *,
    status: StageStatus = StageStatus.RUNNING,
    artifact_refs: list[str] | None = None,
) -> RuntimeStepResult:  # noqa: ANN001
    assert context.thread.current_stage_run_id is not None
    assert context.thread.current_stage_type is not None
    return RuntimeStepResult(
        run_id=context.run_id,
        stage_run_id=context.thread.current_stage_run_id,
        stage_type=context.thread.current_stage_type,
        status=status,
        trace_context=context.trace_context,
        artifact_refs=artifact_refs or [],
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
