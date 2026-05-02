from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.domain.enums import StageType, ToolConfirmationStatus
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
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-runtime-boundary",
        trace_id="trace-runtime-boundary",
        correlation_id="correlation-runtime-boundary",
        span_id="span-parent",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def build_thread(
    *,
    status: GraphThreadStatus = GraphThreadStatus.RUNNING,
) -> GraphThreadRef:
    return GraphThreadRef(
        thread_id="graph-thread-1",
        run_id="run-1",
        status=status,
        current_stage_run_id="stage-run-1",
        current_stage_type=StageType.CODE_GENERATION,
    )


def build_checkpoint(
    *,
    purpose: CheckpointPurpose = CheckpointPurpose.RUNNING_SAFE_POINT,
) -> CheckpointRef:
    return CheckpointRef(
        checkpoint_id=f"checkpoint-{purpose.value}",
        thread_id="graph-thread-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        purpose=purpose,
        workspace_snapshot_ref="workspace-snapshot-1",
    )


class FakeCheckpointPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

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
            (
                "save_checkpoint",
                {
                    "thread": thread,
                    "purpose": purpose,
                    "trace_context": trace_context,
                    "stage_run_id": stage_run_id,
                    "stage_type": stage_type,
                    "workspace_snapshot_ref": workspace_snapshot_ref,
                    "payload_ref": payload_ref,
                },
            )
        )
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
        self.calls.append(
            (
                "load_checkpoint",
                {
                    "thread": thread,
                    "checkpoint": checkpoint,
                    "trace_context": trace_context,
                },
            )
        )
        return checkpoint


class FakeRuntimeCommandPort:
    def __init__(self) -> None:
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
            interrupt_id=f"interrupt-{interrupt_type.value}",
            thread=thread,
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
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_INTERRUPT,
            thread=interrupt.thread,
            interrupt_ref=interrupt,
            trace_context=trace_context,
        )

    def resume_tool_confirmation(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        self.calls.append(
            (
                "resume_tool_confirmation",
                {
                    "interrupt": interrupt,
                    "resume_payload": resume_payload,
                    "trace_context": trace_context,
                },
            )
        )
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_TOOL_CONFIRMATION,
            thread=interrupt.thread,
            interrupt_ref=interrupt,
            trace_context=trace_context,
        )

    def pause_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        self.calls.append(
            (
                "pause_thread",
                {
                    "thread": thread,
                    "checkpoint": checkpoint,
                    "trace_context": trace_context,
                },
            )
        )
        paused_thread = thread.model_copy(
            update={
                "status": GraphThreadStatus.PAUSED,
                "checkpoint_id": checkpoint.checkpoint_id,
            }
        )
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.PAUSE_THREAD,
            thread=paused_thread,
            checkpoint_ref=checkpoint,
            trace_context=trace_context,
        )

    def resume_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        self.calls.append(
            (
                "resume_thread",
                {
                    "thread": thread,
                    "checkpoint": checkpoint,
                    "trace_context": trace_context,
                },
            )
        )
        resumed_thread = thread.model_copy(
            update={
                "status": GraphThreadStatus.WAITING_TOOL_CONFIRMATION,
                "checkpoint_id": checkpoint.checkpoint_id,
            }
        )
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_THREAD,
            thread=resumed_thread,
            checkpoint_ref=checkpoint,
            trace_context=trace_context,
        )

    def terminate_thread(
        self,
        *,
        thread: GraphThreadRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        self.calls.append(
            (
                "terminate_thread",
                {"thread": thread, "trace_context": trace_context},
            )
        )
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.TERMINATE_THREAD,
            thread=thread.model_copy(update={"status": GraphThreadStatus.TERMINATED}),
            trace_context=trace_context,
        )

    def assert_thread_terminal(
        self,
        *,
        thread: GraphThreadRef,
        trace_context: TraceContext,
    ) -> GraphThreadRef:
        self.calls.append(
            (
                "assert_thread_terminal",
                {"thread": thread, "trace_context": trace_context},
            )
        )
        return thread


def build_service() -> tuple[
    RuntimeOrchestrationService,
    FakeRuntimeCommandPort,
    FakeCheckpointPort,
]:
    runtime_port = FakeRuntimeCommandPort()
    checkpoint_port = FakeCheckpointPort()
    service = RuntimeOrchestrationService(
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
        clock=lambda: NOW,
    )
    return service, runtime_port, checkpoint_port


def test_runtime_refs_are_strict_and_link_interrupts_to_domain_objects() -> None:
    thread = build_thread()
    interrupt = GraphInterruptRef(
        interrupt_id="interrupt-tool-1",
        thread=thread,
        interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
        status=GraphInterruptStatus.PENDING,
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        payload_ref="tool-confirmation-1",
        tool_confirmation_id="tool-confirmation-1",
        tool_action_ref="tool-call-1",
        checkpoint_ref=build_checkpoint(
            purpose=CheckpointPurpose.WAITING_TOOL_CONFIRMATION
        ),
    )

    assert interrupt.thread.thread_id == "graph-thread-1"
    assert interrupt.payload_ref == "tool-confirmation-1"
    assert interrupt.tool_confirmation_id == "tool-confirmation-1"
    assert interrupt.tool_action_ref == "tool-call-1"

    with pytest.raises(ValidationError):
        GraphThreadRef(
            thread_id="graph-thread-1",
            run_id="run-1",
            status=GraphThreadStatus.RUNNING,
            raw_state={"forbidden": True},
        )

    with pytest.raises(ValidationError, match="tool confirmation interrupt"):
        GraphInterruptRef(
            interrupt_id="interrupt-tool-missing-links",
            thread=thread,
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            status=GraphInterruptStatus.PENDING,
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            payload_ref="tool-confirmation-1",
            checkpoint_ref=build_checkpoint(
                purpose=CheckpointPurpose.WAITING_TOOL_CONFIRMATION
            ),
        )


def test_create_interrupt_links_run_stage_payload_and_child_trace() -> None:
    service, runtime_port, checkpoint_port = build_service()
    trace = build_trace()

    interrupt = service.create_interrupt(
        thread=build_thread(),
        interrupt_type=GraphInterruptType.APPROVAL,
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        payload_ref="approval-payload-1",
        trace_context=trace,
        approval_id="approval-1",
    )

    assert interrupt.interrupt_type is GraphInterruptType.APPROVAL
    assert interrupt.run_id == "run-1"
    assert interrupt.stage_run_id == "stage-run-1"
    assert interrupt.stage_type is StageType.SOLUTION_DESIGN
    assert interrupt.payload_ref == "approval-payload-1"
    assert interrupt.approval_id == "approval-1"
    assert checkpoint_port.calls[0][1]["purpose"] is CheckpointPurpose.WAITING_APPROVAL
    create_call = runtime_port.calls[0][1]
    child_trace = create_call["trace_context"]
    assert child_trace.request_id == trace.request_id
    assert child_trace.trace_id == trace.trace_id
    assert child_trace.correlation_id == trace.correlation_id
    assert child_trace.parent_span_id == trace.span_id
    assert child_trace.span_id.startswith("runtime-create-interrupt-approval-run-1")
    assert child_trace.run_id == "run-1"
    assert child_trace.stage_run_id == "stage-run-1"
    assert child_trace.approval_id == "approval-1"
    assert child_trace.graph_thread_id == "graph-thread-1"


def test_create_tool_confirmation_interrupt_links_confirmation_and_action() -> None:
    service, runtime_port, checkpoint_port = build_service()

    interrupt = service.create_tool_confirmation_interrupt(
        thread=build_thread(),
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        tool_confirmation_id="tool-confirmation-1",
        tool_action_ref="tool-call-1",
        trace_context=build_trace(),
    )

    assert interrupt.interrupt_type is GraphInterruptType.TOOL_CONFIRMATION
    assert interrupt.payload_ref == "tool-confirmation-1"
    assert interrupt.tool_confirmation_id == "tool-confirmation-1"
    assert interrupt.tool_action_ref == "tool-call-1"
    assert checkpoint_port.calls[0][1]["purpose"] is (
        CheckpointPurpose.WAITING_TOOL_CONFIRMATION
    )
    create_call = runtime_port.calls[0][1]
    assert create_call["tool_confirmation_id"] == "tool-confirmation-1"
    assert create_call["tool_action_ref"] == "tool-call-1"
    assert create_call["trace_context"].tool_confirmation_id == "tool-confirmation-1"


def test_resume_interrupt_delegates_with_resume_payload_and_child_trace() -> None:
    service, runtime_port, _checkpoint_port = build_service()
    interrupt = GraphInterruptRef(
        interrupt_id="interrupt-approval",
        thread=build_thread(status=GraphThreadStatus.WAITING_APPROVAL),
        interrupt_type=GraphInterruptType.APPROVAL,
        status=GraphInterruptStatus.PENDING,
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        payload_ref="approval-payload-1",
        approval_id="approval-1",
        checkpoint_ref=build_checkpoint(purpose=CheckpointPurpose.WAITING_APPROVAL),
    )
    payload = RuntimeResumePayload(
        resume_id="resume-approval-1",
        payload_ref="approval-decision-1",
        values={"decision": "approved"},
    )

    result = service.resume_interrupt(
        interrupt=interrupt,
        resume_payload=payload,
        trace_context=build_trace(),
    )

    assert result.command_type is RuntimeCommandType.RESUME_INTERRUPT
    resume_call = runtime_port.calls[0][1]
    assert resume_call["interrupt"] == interrupt
    assert resume_call["resume_payload"] == payload
    assert resume_call["trace_context"].parent_span_id == "span-parent"
    assert resume_call["trace_context"].approval_id == "approval-1"


def test_resume_tool_confirmation_uses_tool_confirmation_port_method() -> None:
    service, runtime_port, _checkpoint_port = build_service()
    interrupt = GraphInterruptRef(
        interrupt_id="interrupt-tool",
        thread=build_thread(status=GraphThreadStatus.WAITING_TOOL_CONFIRMATION),
        interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
        status=GraphInterruptStatus.PENDING,
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        payload_ref="tool-confirmation-1",
        tool_confirmation_id="tool-confirmation-1",
        tool_action_ref="tool-call-1",
        checkpoint_ref=build_checkpoint(
            purpose=CheckpointPurpose.WAITING_TOOL_CONFIRMATION
        ),
    )
    payload = RuntimeResumePayload(
        resume_id="resume-tool-1",
        payload_ref="tool-confirmation-result-1",
        values={"decision": ToolConfirmationStatus.ALLOWED.value},
    )

    result = service.resume_tool_confirmation(
        interrupt=interrupt,
        resume_payload=payload,
        trace_context=build_trace(),
    )

    assert result.command_type is RuntimeCommandType.RESUME_TOOL_CONFIRMATION
    assert runtime_port.calls[0][0] == "resume_tool_confirmation"
    assert runtime_port.calls[0][1]["trace_context"].tool_confirmation_id == (
        "tool-confirmation-1"
    )


def test_pause_thread_saves_checkpoint_and_pauses_same_thread() -> None:
    service, runtime_port, checkpoint_port = build_service()
    thread = build_thread()

    result = service.pause_thread(
        thread=thread,
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        workspace_snapshot_ref="workspace-snapshot-1",
        trace_context=build_trace(),
    )

    assert result.command_type is RuntimeCommandType.PAUSE_THREAD
    assert checkpoint_port.calls[0][0] == "save_checkpoint"
    assert checkpoint_port.calls[0][1]["purpose"] is CheckpointPurpose.PAUSE
    assert runtime_port.calls[0][0] == "pause_thread"
    assert runtime_port.calls[0][1]["thread"] == thread
    assert runtime_port.calls[0][1]["checkpoint"] == result.checkpoint_ref
    assert runtime_port.calls[0][1]["trace_context"].graph_thread_id == "graph-thread-1"


def test_resume_thread_restores_same_waiting_tool_checkpoint() -> None:
    service, runtime_port, checkpoint_port = build_service()
    paused_thread = build_thread(status=GraphThreadStatus.PAUSED)
    checkpoint = build_checkpoint(purpose=CheckpointPurpose.WAITING_TOOL_CONFIRMATION)

    result = service.resume_thread(
        thread=paused_thread,
        checkpoint=checkpoint,
        trace_context=build_trace(),
    )

    assert result.command_type is RuntimeCommandType.RESUME_THREAD
    assert result.checkpoint_ref == checkpoint
    assert result.thread.status is GraphThreadStatus.WAITING_TOOL_CONFIRMATION
    assert checkpoint_port.calls[0][0] == "load_checkpoint"
    assert runtime_port.calls[0][0] == "resume_thread"
    assert runtime_port.calls[0][1]["checkpoint"] == checkpoint
    assert not any(call[0] == "create_interrupt" for call in runtime_port.calls)


def test_terminate_thread_delegates_to_current_graph_thread() -> None:
    service, runtime_port, _checkpoint_port = build_service()
    thread = build_thread()

    result = service.terminate_thread(
        thread=thread,
        trace_context=build_trace(),
    )

    assert result.command_type is RuntimeCommandType.TERMINATE_THREAD
    assert result.thread.status is GraphThreadStatus.TERMINATED
    assert runtime_port.calls[0][0] == "terminate_thread"
    assert runtime_port.calls[0][1]["thread"] == thread


def test_rerun_terminal_check_does_not_resume_or_reuse_old_thread() -> None:
    service, runtime_port, _checkpoint_port = build_service()
    old_thread = build_thread(status=GraphThreadStatus.FAILED)

    result = service.assert_thread_terminal_for_rerun(
        thread=old_thread,
        trace_context=build_trace(),
    )

    assert result == old_thread
    assert runtime_port.calls == [
        (
            "assert_thread_terminal",
            {
                "thread": old_thread,
                "trace_context": runtime_port.calls[0][1]["trace_context"],
            },
        )
    ]
    assert runtime_port.calls[0][1]["trace_context"].span_id.startswith(
        "runtime-rerun-terminal-check-graph-thread-1"
    )
    assert not any("resume" in call[0] for call in runtime_port.calls)
