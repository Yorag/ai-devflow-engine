from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt as langgraph_interrupt

from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.graph_definition import GraphDefinition
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
from backend.app.observability.log_writer import LogRecordInput
from backend.app.runtime.base import (
    RuntimeExecutionContext,
    RuntimeInterrupt,
    RuntimeStepResult,
)
from backend.app.runtime.stage_runner_port import StageNodeResult
from backend.app.services.graph_compiler import GraphCompiler


NOW = datetime(2026, 5, 4, 10, 30, 0, tzinfo=UTC)


class CapturingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return SimpleNamespace(log_id=f"log-{len(self.records)}")


class CapturingCheckpointPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "thread": thread,
                "purpose": purpose,
                "trace_context": trace_context,
                "stage_run_id": stage_run_id,
                "stage_type": stage_type,
                "workspace_snapshot_ref": workspace_snapshot_ref,
                "payload_ref": payload_ref,
            }
        )
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{len(self.calls)}",
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


class CapturingRuntimeCommandPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        self.calls.append(("create_interrupt", kwargs))
        thread = kwargs["thread"].model_copy(
            update={"status": _waiting_status(kwargs["interrupt_type"])}
        )
        return GraphInterruptRef(
            interrupt_id=f"interrupt-{kwargs['payload_ref']}",
            thread=thread,
            interrupt_type=kwargs["interrupt_type"],
            status=GraphInterruptStatus.PENDING,
            run_id=kwargs["run_id"],
            stage_run_id=kwargs["stage_run_id"],
            stage_type=kwargs["stage_type"],
            payload_ref=kwargs["payload_ref"],
            clarification_id=kwargs.get("clarification_id"),
            approval_id=kwargs.get("approval_id"),
            tool_confirmation_id=kwargs.get("tool_confirmation_id"),
            tool_action_ref=kwargs.get("tool_action_ref"),
            checkpoint_ref=kwargs["checkpoint"],
        )

    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_interrupt", kwargs))
        interrupt = kwargs["interrupt"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_INTERRUPT,
            thread=interrupt.thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            interrupt_ref=interrupt.model_copy(update={"status": GraphInterruptStatus.RESUMED}),
            payload_ref=kwargs["resume_payload"].payload_ref,
            trace_context=kwargs["trace_context"],
        )

    def resume_tool_confirmation(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_tool_confirmation", kwargs))
        interrupt = kwargs["interrupt"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_TOOL_CONFIRMATION,
            thread=interrupt.thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            interrupt_ref=interrupt.model_copy(update={"status": GraphInterruptStatus.RESUMED}),
            payload_ref=kwargs["resume_payload"].payload_ref,
            trace_context=kwargs["trace_context"],
        )

    def __getattr__(self, name: str) -> Callable[..., object]:
        def _unexpected(**kwargs: Any) -> object:
            raise AssertionError(f"unexpected runtime command call: {name}")

        return _unexpected


class FailingResumeRuntimeCommandPort(CapturingRuntimeCommandPort):
    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_interrupt", kwargs))
        raise RuntimeError("runtime resume failed")


class InterruptingStageRunner:
    def __init__(self, payload_by_stage: dict[StageType, dict[str, object]]) -> None:
        self.payload_by_stage = payload_by_stage
        self.invocations: list[Any] = []
        self.resume_values: list[object] = []

    def run_stage(self, invocation: Any) -> StageNodeResult:
        self.invocations.append(invocation)
        payload = self.payload_by_stage.get(invocation.stage_type)
        if payload is not None:
            resume_value = langgraph_interrupt(
                {
                    **payload,
                    "stage_run_id": invocation.stage_run_id,
                    "stage_type": invocation.stage_type.value,
                }
            )
            self.resume_values.append(resume_value)
        return StageNodeResult(
            run_id=invocation.run_id,
            stage_run_id=invocation.stage_run_id,
            stage_type=invocation.stage_type,
            status=StageStatus.COMPLETED,
            artifact_refs=[f"artifact-{invocation.stage_type.value}"],
            domain_event_refs=[f"event-{invocation.stage_type.value}"],
            log_summary_refs=[f"log-{invocation.stage_type.value}"],
            audit_refs=[],
            route_key=None,
        )


def _waiting_status(interrupt_type: GraphInterruptType) -> GraphThreadStatus:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return GraphThreadStatus.WAITING_CLARIFICATION
    if interrupt_type is GraphInterruptType.APPROVAL:
        return GraphThreadStatus.WAITING_APPROVAL
    if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
        return GraphThreadStatus.WAITING_TOOL_CONFIRMATION
    raise AssertionError(f"unexpected interrupt type: {interrupt_type}")


def _clock() -> Callable[[], datetime]:
    ticks = iter(NOW + timedelta(milliseconds=index) for index in range(1000))
    return lambda: next(ticks)


def build_definition() -> GraphDefinition:
    from backend.tests.services.test_graph_compiler import (
        build_runtime_limit_snapshot,
        build_template_snapshot,
    )

    return GraphCompiler(now=lambda: NOW).compile(
        template_snapshot=build_template_snapshot(run_id="run-1"),
        runtime_limit_snapshot=build_runtime_limit_snapshot(run_id="run-1"),
    )


def build_trace(**overrides: Any) -> TraceContext:
    values = {
        "request_id": "request-langgraph-interrupt",
        "trace_id": "trace-langgraph-interrupt",
        "correlation_id": "correlation-langgraph-interrupt",
        "span_id": "span-root",
        "parent_span_id": None,
        "session_id": "session-1",
        "run_id": "run-1",
        "stage_run_id": None,
        "graph_thread_id": "graph-thread-1",
        "created_at": NOW,
    }
    values.update(overrides)
    return TraceContext(**values)


def build_context(
    *,
    status: GraphThreadStatus = GraphThreadStatus.RUNNING,
    stage_run_id: str | None = None,
    stage_type: StageType | None = None,
) -> RuntimeExecutionContext:
    return RuntimeExecutionContext(
        run_id="run-1",
        session_id="session-1",
        thread=GraphThreadRef(
            thread_id="graph-thread-1",
            run_id="run-1",
            status=status,
            current_stage_run_id=stage_run_id,
            current_stage_type=stage_type,
        ),
        trace_context=build_trace(stage_run_id=stage_run_id),
        template_snapshot_ref="template-snapshot-run-1",
        provider_snapshot_refs=["provider-snapshot-1"],
        model_binding_snapshot_refs=["model-binding-1"],
        runtime_limit_snapshot_ref="runtime-limit-snapshot-run-1",
        provider_call_policy_snapshot_ref="policy-1",
        graph_definition_ref="graph-definition-run-1",
        delivery_channel_snapshot_ref=None,
        workspace_snapshot_ref="workspace-1",
    )


def build_engine(
    runner: InterruptingStageRunner,
    log_writer: CapturingRunLogWriter,
    checkpointer: object | None = None,
) -> Any:
    from backend.app.runtime.langgraph_engine import LangGraphRuntimeEngine

    return LangGraphRuntimeEngine(
        graph_definition=build_definition(),
        stage_runner=runner,
        checkpointer=checkpointer or InMemorySaver(),
        log_writer=log_writer,
        now=_clock(),
    )


def _steps_before(stage_type: StageType) -> int:
    sequence = [
        StageType.REQUIREMENT_ANALYSIS,
        StageType.SOLUTION_DESIGN,
        StageType.CODE_GENERATION,
        StageType.TEST_GENERATION_EXECUTION,
        StageType.CODE_REVIEW,
        StageType.DELIVERY_INTEGRATION,
    ]
    return sequence.index(stage_type)


def _run_until_interrupt(
    *,
    stage_type: StageType,
    payload: dict[str, object],
    log_writer: CapturingRunLogWriter | None = None,
    checkpointer: object | None = None,
) -> tuple[
    Any,
    InterruptingStageRunner,
    CapturingCheckpointPort,
    CapturingRuntimeCommandPort,
    RuntimeInterrupt,
    CapturingRunLogWriter,
]:
    runner = InterruptingStageRunner({stage_type: payload})
    resolved_log_writer = log_writer or CapturingRunLogWriter()
    engine = build_engine(runner, resolved_log_writer, checkpointer=checkpointer)
    checkpoint_port = CapturingCheckpointPort()
    runtime_port = CapturingRuntimeCommandPort()
    context = build_context()

    for _ in range(_steps_before(stage_type)):
        result = engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
        assert isinstance(result, RuntimeStepResult)

    result = engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    assert isinstance(result, RuntimeInterrupt)
    return engine, runner, checkpoint_port, runtime_port, result, resolved_log_writer


@pytest.mark.parametrize(
    ("stage_type", "payload", "expected_type", "expected_purpose", "expected_link"),
    [
        (
            StageType.REQUIREMENT_ANALYSIS,
            {
                "interrupt_type": GraphInterruptType.CLARIFICATION_REQUEST.value,
                "payload_ref": "clarification-payload-1",
                "clarification_id": "clarification-1",
            },
            GraphInterruptType.CLARIFICATION_REQUEST,
            CheckpointPurpose.WAITING_CLARIFICATION,
            ("clarification_id", "clarification-1"),
        ),
        (
            StageType.SOLUTION_DESIGN,
            {
                "interrupt_type": GraphInterruptType.APPROVAL.value,
                "payload_ref": "approval-payload-1",
                "approval_id": "approval-1",
            },
            GraphInterruptType.APPROVAL,
            CheckpointPurpose.WAITING_APPROVAL,
            ("approval_id", "approval-1"),
        ),
        (
            StageType.CODE_GENERATION,
            {
                "interrupt_type": GraphInterruptType.TOOL_CONFIRMATION.value,
                "payload_ref": "tool-confirmation-payload-1",
                "tool_confirmation_id": "tool-confirmation-1",
                "tool_action_ref": "tool-action-1",
            },
            GraphInterruptType.TOOL_CONFIRMATION,
            CheckpointPurpose.WAITING_TOOL_CONFIRMATION,
            ("tool_confirmation_id", "tool-confirmation-1"),
        ),
    ],
)
def test_native_interrupt_payload_is_persisted_as_runtime_interrupt(
    stage_type: StageType,
    payload: dict[str, object],
    expected_type: GraphInterruptType,
    expected_purpose: CheckpointPurpose,
    expected_link: tuple[str, str],
) -> None:
    (
        _engine,
        runner,
        checkpoint_port,
        runtime_port,
        result,
        log_writer,
    ) = _run_until_interrupt(stage_type=stage_type, payload=payload)

    assert result.run_id == "run-1"
    assert result.stage_type is stage_type
    assert result.stage_run_id == f"stage-run-run-1-{stage_type.value}"
    assert result.payload_ref == payload["payload_ref"]
    assert result.interrupt_ref.interrupt_type is expected_type
    assert result.interrupt_ref.status is GraphInterruptStatus.PENDING
    assert getattr(result.interrupt_ref, expected_link[0]) == expected_link[1]
    if expected_type is GraphInterruptType.TOOL_CONFIRMATION:
        assert result.interrupt_ref.tool_action_ref == "tool-action-1"

    assert runtime_port.calls[-1][0] == "create_interrupt"
    create_call = runtime_port.calls[-1][1]
    assert create_call["thread"].thread_id == "graph-thread-1"
    assert create_call["interrupt_type"] is expected_type
    assert create_call["run_id"] == "run-1"
    assert create_call["stage_run_id"] == result.stage_run_id
    assert create_call["stage_type"] is stage_type
    assert create_call["payload_ref"] == payload["payload_ref"]
    assert create_call[expected_link[0]] == expected_link[1]

    waiting_checkpoint_call = checkpoint_port.calls[-1]
    assert waiting_checkpoint_call["purpose"] is expected_purpose
    assert waiting_checkpoint_call["stage_run_id"] == result.stage_run_id
    assert waiting_checkpoint_call["stage_type"] is stage_type
    assert waiting_checkpoint_call["workspace_snapshot_ref"] == "workspace-1"
    assert waiting_checkpoint_call["payload_ref"].startswith(
        "langgraph://graph-thread-1/checkpoints/default/"
    )
    assert create_call["checkpoint"].purpose is expected_purpose
    assert create_call["checkpoint"].payload_ref == waiting_checkpoint_call["payload_ref"]
    assert runner.resume_values == []

    interrupt_logs = [
        record
        for record in log_writer.records
        if record.payload.summary.get("action") == "interrupt_requested"
    ]
    assert len(interrupt_logs) == 1
    summary = interrupt_logs[0].payload.summary
    assert summary["interrupt_type"] == expected_type.value
    assert summary["payload_ref"] == payload["payload_ref"]
    assert summary["stage_run_id"] == result.stage_run_id
    assert "raw" not in str(summary).lower()
    assert "graph_state" not in summary
    assert "compiled_graph" not in summary


def test_resume_from_clarification_interrupt_uses_command_resume_on_same_thread() -> None:
    payload = {
        "interrupt_type": GraphInterruptType.CLARIFICATION_REQUEST.value,
        "payload_ref": "clarification-payload-1",
        "clarification_id": "clarification-1",
    }
    (
        engine,
        runner,
        checkpoint_port,
        runtime_port,
        interrupt_result,
        log_writer,
    ) = _run_until_interrupt(
        stage_type=StageType.REQUIREMENT_ANALYSIS,
        payload=payload,
    )
    resume_payload = RuntimeResumePayload(
        resume_id="resume-clarification-1",
        payload_ref="clarification-answer-1",
        values={"answer": "Continue with this requirement."},
    )

    result = engine.resume_from_interrupt(
        context=build_context(
            status=GraphThreadStatus.WAITING_CLARIFICATION,
            stage_run_id=interrupt_result.stage_run_id,
            stage_type=interrupt_result.stage_type,
        ),
        interrupt=interrupt_result,
        resume_payload=resume_payload,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.stage_type is StageType.REQUIREMENT_ANALYSIS
    assert result.stage_run_id == interrupt_result.stage_run_id
    assert result.status is StageStatus.COMPLETED
    assert result.trace_context.graph_thread_id == "graph-thread-1"
    assert result.checkpoint_ref is not None
    assert result.checkpoint_ref.purpose is CheckpointPurpose.RUNNING_SAFE_POINT
    assert runtime_port.calls[-1][0] == "resume_interrupt"
    assert runner.resume_values == [resume_payload.model_dump(mode="json")]
    assert any(
        record.payload.summary.get("action") == "resume_command"
        for record in log_writer.records
    )
    assert any(
        record.payload.summary.get("action") == "resume_succeeded"
        for record in log_writer.records
    )


def test_resume_from_approval_interrupt_uses_command_resume_on_same_thread() -> None:
    payload = {
        "interrupt_type": GraphInterruptType.APPROVAL.value,
        "payload_ref": "approval-payload-1",
        "approval_id": "approval-1",
    }
    (
        engine,
        runner,
        checkpoint_port,
        runtime_port,
        interrupt_result,
        log_writer,
    ) = _run_until_interrupt(stage_type=StageType.SOLUTION_DESIGN, payload=payload)
    resume_payload = RuntimeResumePayload(
        resume_id="resume-approval-1",
        payload_ref="approval-decision-1",
        values={"decision": "approved", "approval_id": "approval-1"},
    )

    result = engine.resume_from_interrupt(
        context=build_context(
            status=GraphThreadStatus.WAITING_APPROVAL,
            stage_run_id=interrupt_result.stage_run_id,
            stage_type=interrupt_result.stage_type,
        ),
        interrupt=interrupt_result,
        resume_payload=resume_payload,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.stage_type is StageType.SOLUTION_DESIGN
    assert result.stage_run_id == interrupt_result.stage_run_id
    assert result.trace_context.graph_thread_id == "graph-thread-1"
    assert result.checkpoint_ref is not None
    assert result.checkpoint_ref.thread_id == "graph-thread-1"
    assert runtime_port.calls[-1][0] == "resume_interrupt"
    assert runner.resume_values == [resume_payload.model_dump(mode="json")]
    assert any(
        record.payload.summary.get("action") == "resume_command"
        for record in log_writer.records
    )
    assert any(
        record.payload.summary.get("action") == "resume_succeeded"
        for record in log_writer.records
    )


def test_resume_from_interrupt_uses_saved_interrupt_checkpoint_when_thread_head_changed() -> None:
    checkpointer = InMemorySaver()
    payload = {
        "interrupt_type": GraphInterruptType.CLARIFICATION_REQUEST.value,
        "payload_ref": "clarification-payload-1",
        "clarification_id": "clarification-1",
    }
    (
        engine,
        runner,
        checkpoint_port,
        runtime_port,
        interrupt_result,
        _log_writer,
    ) = _run_until_interrupt(
        stage_type=StageType.REQUIREMENT_ANALYSIS,
        payload=payload,
        checkpointer=checkpointer,
    )
    compiled_graph = engine._compile_graph(build_context())
    thread_config = {"configurable": {"thread_id": "graph-thread-1", "checkpoint_ns": ""}}
    compiled_graph.update_state(
        thread_config,
        {
            "current_node_key": StageType.DELIVERY_INTEGRATION.value,
            "completed_stage_run_ids": ["stale-latest"],
            "last_result": {
                "run_id": "run-1",
                "stage_run_id": "stage-run-run-1-delivery_integration",
                "stage_type": StageType.DELIVERY_INTEGRATION.value,
                "status": StageStatus.COMPLETED.value,
                "artifact_refs": ["stale-latest-artifact"],
                "domain_event_refs": [],
                "log_summary_refs": [],
                "audit_refs": [],
                "route_key": None,
            },
        },
        as_node=StageType.DELIVERY_INTEGRATION.value,
    )
    resume_payload = RuntimeResumePayload(
        resume_id="resume-clarification-from-saved-checkpoint",
        payload_ref="clarification-answer-from-saved-checkpoint",
        values={"answer": "Use the interrupted checkpoint."},
    )

    result = engine.resume_from_interrupt(
        context=build_context(
            status=GraphThreadStatus.WAITING_CLARIFICATION,
            stage_run_id=interrupt_result.stage_run_id,
            stage_type=interrupt_result.stage_type,
        ),
        interrupt=interrupt_result,
        resume_payload=resume_payload,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.stage_type is StageType.REQUIREMENT_ANALYSIS
    assert result.stage_run_id == interrupt_result.stage_run_id
    assert result.artifact_refs == ["artifact-requirement_analysis"]
    assert runner.resume_values == [resume_payload.model_dump(mode="json")]
    assert checkpoint_port.calls[-1]["purpose"] is CheckpointPurpose.RUNNING_SAFE_POINT
    assert checkpoint_port.calls[-1]["payload_ref"] != (
        interrupt_result.interrupt_ref.checkpoint_ref.payload_ref
    )


def test_resume_from_tool_confirmation_uses_tool_confirmation_runtime_boundary() -> None:
    payload = {
        "interrupt_type": GraphInterruptType.TOOL_CONFIRMATION.value,
        "payload_ref": "tool-confirmation-payload-1",
        "tool_confirmation_id": "tool-confirmation-1",
        "tool_action_ref": "tool-action-1",
    }
    (
        engine,
        runner,
        checkpoint_port,
        runtime_port,
        interrupt_result,
        _log_writer,
    ) = _run_until_interrupt(stage_type=StageType.CODE_GENERATION, payload=payload)
    resume_payload = RuntimeResumePayload(
        resume_id="resume-tool-1",
        payload_ref="tool-confirmation-result-1",
        values={
            "decision": "allowed",
            "tool_confirmation_id": "tool-confirmation-1",
        },
    )

    result = engine.resume_from_interrupt(
        context=build_context(
            status=GraphThreadStatus.WAITING_TOOL_CONFIRMATION,
            stage_run_id=interrupt_result.stage_run_id,
            stage_type=interrupt_result.stage_type,
        ),
        interrupt=interrupt_result,
        resume_payload=resume_payload,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.stage_type is StageType.CODE_GENERATION
    assert runtime_port.calls[-1][0] == "resume_tool_confirmation"
    assert runner.resume_values[-1]["values"]["decision"] == "allowed"


def test_resume_rejects_non_pending_interrupt_before_runtime_boundary() -> None:
    payload = {
        "interrupt_type": GraphInterruptType.APPROVAL.value,
        "payload_ref": "approval-payload-1",
        "approval_id": "approval-1",
    }
    (
        engine,
        _runner,
        checkpoint_port,
        runtime_port,
        interrupt_result,
        _log_writer,
    ) = _run_until_interrupt(stage_type=StageType.SOLUTION_DESIGN, payload=payload)

    with pytest.raises(ValueError, match="pending GraphInterrupt"):
        engine.resume_from_interrupt(
            context=build_context(
                status=GraphThreadStatus.WAITING_APPROVAL,
                stage_run_id=interrupt_result.stage_run_id,
                stage_type=interrupt_result.stage_type,
            ),
            interrupt=interrupt_result.model_copy(
                update={
                    "interrupt_ref": interrupt_result.interrupt_ref.model_copy(
                        update={"status": GraphInterruptStatus.RESUMED}
                    )
                }
            ),
            resume_payload=RuntimeResumePayload(
                resume_id="resume-non-pending",
                payload_ref="approval-decision-non-pending",
                values={"decision": "approved"},
            ),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    assert runtime_port.calls[-1][0] == "create_interrupt"


def test_resume_rejects_wrong_waiting_status_before_runtime_boundary() -> None:
    payload = {
        "interrupt_type": GraphInterruptType.TOOL_CONFIRMATION.value,
        "payload_ref": "tool-confirmation-payload-1",
        "tool_confirmation_id": "tool-confirmation-1",
        "tool_action_ref": "tool-action-1",
    }
    (
        engine,
        _runner,
        checkpoint_port,
        runtime_port,
        interrupt_result,
        _log_writer,
    ) = _run_until_interrupt(stage_type=StageType.CODE_GENERATION, payload=payload)

    with pytest.raises(ValueError, match="waiting status"):
        engine.resume_from_interrupt(
            context=build_context(
                status=GraphThreadStatus.WAITING_APPROVAL,
                stage_run_id=interrupt_result.stage_run_id,
                stage_type=interrupt_result.stage_type,
            ),
            interrupt=interrupt_result,
            resume_payload=RuntimeResumePayload(
                resume_id="resume-wrong-waiting-status",
                payload_ref="tool-confirmation-result-wrong-status",
                values={"decision": "allowed"},
            ),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    assert runtime_port.calls[-1][0] == "create_interrupt"


def test_resume_rejects_mismatched_current_stage_before_runtime_boundary() -> None:
    payload = {
        "interrupt_type": GraphInterruptType.APPROVAL.value,
        "payload_ref": "approval-payload-1",
        "approval_id": "approval-1",
    }
    (
        engine,
        _runner,
        checkpoint_port,
        runtime_port,
        interrupt_result,
        _log_writer,
    ) = _run_until_interrupt(stage_type=StageType.SOLUTION_DESIGN, payload=payload)

    with pytest.raises(ValueError, match="current stage"):
        engine.resume_from_interrupt(
            context=build_context(
                status=GraphThreadStatus.WAITING_APPROVAL,
                stage_run_id="other-stage-run",
                stage_type=StageType.CODE_GENERATION,
            ),
            interrupt=interrupt_result,
            resume_payload=RuntimeResumePayload(
                resume_id="resume-wrong-current-stage",
                payload_ref="approval-decision-wrong-current-stage",
                values={"decision": "approved"},
            ),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    assert runtime_port.calls[-1][0] == "create_interrupt"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "interrupt_type": GraphInterruptType.APPROVAL.value,
            "payload_ref": "approval-payload-1",
            "approval_id": 123,
        },
        {
            "interrupt_type": GraphInterruptType.TOOL_CONFIRMATION.value,
            "payload_ref": "tool-confirmation-payload-1",
            "tool_confirmation_id": "tool-confirmation-1",
            "tool_action_ref": 456,
        },
    ],
)
def test_native_interrupt_rejects_non_string_optional_refs_before_create_interrupt(
    payload: dict[str, object],
) -> None:
    stage_type = (
        StageType.SOLUTION_DESIGN
        if payload["interrupt_type"] == GraphInterruptType.APPROVAL.value
        else StageType.CODE_GENERATION
    )
    runner = InterruptingStageRunner({stage_type: payload})
    log_writer = CapturingRunLogWriter()
    engine = build_engine(runner, log_writer)
    checkpoint_port = CapturingCheckpointPort()
    runtime_port = CapturingRuntimeCommandPort()
    context = build_context()

    for _ in range(_steps_before(stage_type)):
        result = engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
        assert isinstance(result, RuntimeStepResult)

    with pytest.raises(ValueError, match="must be a string"):
        engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    assert not any(call[0] == "create_interrupt" for call in runtime_port.calls)


def test_resume_failure_is_logged_and_reraised_without_raw_graph_state() -> None:
    payload = {
        "interrupt_type": GraphInterruptType.APPROVAL.value,
        "payload_ref": "approval-payload-1",
        "approval_id": "approval-1",
    }
    (
        engine,
        runner,
        checkpoint_port,
        _runtime_port,
        interrupt_result,
        log_writer,
    ) = _run_until_interrupt(stage_type=StageType.SOLUTION_DESIGN, payload=payload)

    with pytest.raises(RuntimeError, match="runtime resume failed"):
        engine.resume_from_interrupt(
            context=build_context(
                status=GraphThreadStatus.WAITING_APPROVAL,
                stage_run_id=interrupt_result.stage_run_id,
                stage_type=interrupt_result.stage_type,
            ),
            interrupt=interrupt_result,
            resume_payload=RuntimeResumePayload(
                resume_id="resume-approval-fails",
                payload_ref="approval-decision-fails",
                values={"decision": "approved"},
            ),
            runtime_port=FailingResumeRuntimeCommandPort(),
            checkpoint_port=checkpoint_port,
        )

    failure_logs = [
        record
        for record in log_writer.records
        if record.payload.summary.get("action") == "resume_failed"
    ]
    assert len(failure_logs) == 1
    assert failure_logs[0].level.value == "error"
    assert failure_logs[0].payload.summary["error_type"] == "RuntimeError"
    assert "error_message" not in failure_logs[0].payload.summary
    assert failure_logs[0].payload.summary["error_category"] == "runtime_resume_failed"
    assert "raw" not in str(failure_logs[0].payload.summary).lower()
    assert "graph_state" not in failure_logs[0].payload.summary
    assert "compiled_graph" not in failure_logs[0].payload.summary
    assert runner.resume_values == []
