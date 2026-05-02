from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from backend.app.domain.enums import StageType
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptType,
    GraphThreadRef,
    RuntimeCommandResult,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext


class RuntimeCommandPort(Protocol):
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
    ) -> GraphInterruptRef: ...

    def resume_interrupt(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult: ...

    def resume_tool_confirmation(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult: ...

    def pause_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult: ...

    def resume_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult: ...

    def terminate_thread(
        self,
        *,
        thread: GraphThreadRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult: ...

    def assert_thread_terminal(
        self,
        *,
        thread: GraphThreadRef,
        trace_context: TraceContext,
    ) -> GraphThreadRef: ...


class CheckpointPort(Protocol):
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
    ) -> CheckpointRef: ...

    def load_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> CheckpointRef: ...


class RuntimeOrchestrationService:
    def __init__(
        self,
        *,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime_port = runtime_port
        self._checkpoint_port = checkpoint_port
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_interrupt(
        self,
        *,
        thread: GraphThreadRef,
        interrupt_type: GraphInterruptType,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        payload_ref: str,
        trace_context: TraceContext,
        clarification_id: str | None = None,
        approval_id: str | None = None,
    ) -> GraphInterruptRef:
        return self._create_interrupt(
            thread=thread,
            interrupt_type=interrupt_type,
            run_id=run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            payload_ref=payload_ref,
            trace_context=trace_context,
            clarification_id=clarification_id,
            approval_id=approval_id,
        )

    def create_tool_confirmation_interrupt(
        self,
        *,
        thread: GraphThreadRef,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        tool_confirmation_id: str,
        tool_action_ref: str,
        trace_context: TraceContext,
    ) -> GraphInterruptRef:
        return self._create_interrupt(
            thread=thread,
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            run_id=run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            payload_ref=tool_confirmation_id,
            trace_context=trace_context,
            tool_confirmation_id=tool_confirmation_id,
            tool_action_ref=tool_action_ref,
        )

    def resume_interrupt(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        child_trace = self._child_trace(
            trace_context,
            span_id=f"runtime-resume-interrupt-{interrupt.interrupt_id}",
            run_id=interrupt.run_id,
            stage_run_id=interrupt.stage_run_id,
            approval_id=interrupt.approval_id,
            tool_confirmation_id=interrupt.tool_confirmation_id,
            graph_thread_id=interrupt.thread.thread_id,
        )
        return self._runtime_port.resume_interrupt(
            interrupt=interrupt,
            resume_payload=resume_payload,
            trace_context=child_trace,
        )

    def resume_tool_confirmation(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        child_trace = self._child_trace(
            trace_context,
            span_id=f"runtime-resume-tool-confirmation-{interrupt.interrupt_id}",
            run_id=interrupt.run_id,
            stage_run_id=interrupt.stage_run_id,
            tool_confirmation_id=interrupt.tool_confirmation_id,
            graph_thread_id=interrupt.thread.thread_id,
        )
        return self._runtime_port.resume_tool_confirmation(
            interrupt=interrupt,
            resume_payload=resume_payload,
            trace_context=child_trace,
        )

    def pause_thread(
        self,
        *,
        thread: GraphThreadRef,
        stage_run_id: str | None,
        stage_type: StageType | None,
        workspace_snapshot_ref: str | None,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        child_trace = self._child_trace(
            trace_context,
            span_id=f"runtime-pause-thread-{thread.thread_id}",
            run_id=thread.run_id,
            stage_run_id=stage_run_id,
            graph_thread_id=thread.thread_id,
        )
        checkpoint = self._checkpoint_port.save_checkpoint(
            thread=thread,
            purpose=CheckpointPurpose.PAUSE,
            trace_context=child_trace,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            workspace_snapshot_ref=workspace_snapshot_ref,
        )
        return self._runtime_port.pause_thread(
            thread=thread,
            checkpoint=checkpoint,
            trace_context=child_trace,
        )

    def resume_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        child_trace = self._child_trace(
            trace_context,
            span_id=f"runtime-resume-thread-{thread.thread_id}",
            run_id=thread.run_id,
            stage_run_id=checkpoint.stage_run_id,
            graph_thread_id=thread.thread_id,
        )
        loaded_checkpoint = self._checkpoint_port.load_checkpoint(
            thread=thread,
            checkpoint=checkpoint,
            trace_context=child_trace,
        )
        return self._runtime_port.resume_thread(
            thread=thread,
            checkpoint=loaded_checkpoint,
            trace_context=child_trace,
        )

    def terminate_thread(
        self,
        *,
        thread: GraphThreadRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        child_trace = self._child_trace(
            trace_context,
            span_id=f"runtime-terminate-thread-{thread.thread_id}",
            run_id=thread.run_id,
            stage_run_id=thread.current_stage_run_id,
            graph_thread_id=thread.thread_id,
        )
        return self._runtime_port.terminate_thread(
            thread=thread,
            trace_context=child_trace,
        )

    def assert_thread_terminal_for_rerun(
        self,
        *,
        thread: GraphThreadRef,
        trace_context: TraceContext,
    ) -> GraphThreadRef:
        child_trace = self._child_trace(
            trace_context,
            span_id=f"runtime-rerun-terminal-check-{thread.thread_id}",
            run_id=thread.run_id,
            stage_run_id=thread.current_stage_run_id,
            graph_thread_id=thread.thread_id,
        )
        return self._runtime_port.assert_thread_terminal(
            thread=thread,
            trace_context=child_trace,
        )

    def _create_interrupt(
        self,
        *,
        thread: GraphThreadRef,
        interrupt_type: GraphInterruptType,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        payload_ref: str,
        trace_context: TraceContext,
        clarification_id: str | None = None,
        approval_id: str | None = None,
        tool_confirmation_id: str | None = None,
        tool_action_ref: str | None = None,
    ) -> GraphInterruptRef:
        child_trace = self._child_trace(
            trace_context,
            span_id=f"runtime-create-interrupt-{interrupt_type.value}-{run_id}",
            run_id=run_id,
            stage_run_id=stage_run_id,
            approval_id=approval_id,
            tool_confirmation_id=tool_confirmation_id,
            graph_thread_id=thread.thread_id,
        )
        checkpoint = self._checkpoint_port.save_checkpoint(
            thread=thread,
            purpose=self._checkpoint_purpose_for_interrupt(interrupt_type),
            trace_context=child_trace,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            payload_ref=payload_ref,
        )
        return self._runtime_port.create_interrupt(
            thread=thread,
            interrupt_type=interrupt_type,
            run_id=run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            payload_ref=payload_ref,
            checkpoint=checkpoint,
            trace_context=child_trace,
            clarification_id=clarification_id,
            approval_id=approval_id,
            tool_confirmation_id=tool_confirmation_id,
            tool_action_ref=tool_action_ref,
        )

    @staticmethod
    def _checkpoint_purpose_for_interrupt(
        interrupt_type: GraphInterruptType,
    ) -> CheckpointPurpose:
        if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
            return CheckpointPurpose.WAITING_CLARIFICATION
        if interrupt_type is GraphInterruptType.APPROVAL:
            return CheckpointPurpose.WAITING_APPROVAL
        return CheckpointPurpose.WAITING_TOOL_CONFIRMATION

    def _child_trace(
        self,
        trace_context: TraceContext,
        *,
        span_id: str,
        run_id: str,
        stage_run_id: str | None = None,
        approval_id: str | None = None,
        tool_confirmation_id: str | None = None,
        graph_thread_id: str | None = None,
    ) -> TraceContext:
        return trace_context.child_span(
            span_id=span_id,
            created_at=self._clock(),
            run_id=run_id,
            stage_run_id=stage_run_id,
            approval_id=approval_id,
            tool_confirmation_id=tool_confirmation_id,
            graph_thread_id=graph_thread_id,
        )


__all__ = [
    "CheckpointPort",
    "RuntimeCommandPort",
    "RuntimeOrchestrationService",
]

