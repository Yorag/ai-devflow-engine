from __future__ import annotations

from backend.app.domain.enums import StageType
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


class InMemoryCheckpointPort:
    def save_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        purpose: CheckpointPurpose,
        trace_context,
        stage_run_id: str | None = None,
        stage_type: StageType | None = None,
        workspace_snapshot_ref: str | None = None,
        payload_ref: str | None = None,
    ) -> CheckpointRef:
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{purpose.value}-{thread.thread_id}",
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
        trace_context,
    ) -> CheckpointRef:
        return checkpoint


class InMemoryRuntimeCommandPort:
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
        trace_context,
        clarification_id: str | None = None,
        approval_id: str | None = None,
        tool_confirmation_id: str | None = None,
        tool_action_ref: str | None = None,
    ) -> GraphInterruptRef:
        return GraphInterruptRef(
            interrupt_id=(
                f"interrupt-{clarification_id or approval_id or tool_confirmation_id}"
            ),
            thread=thread.model_copy(update={"status": _waiting_status(interrupt_type)}),
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
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_INTERRUPT,
            thread=interrupt.thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            interrupt_ref=interrupt.model_copy(update={"status": GraphInterruptStatus.RESUMED}),
            payload_ref=resume_payload.payload_ref,
            trace_context=trace_context,
        )

    def resume_tool_confirmation(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_TOOL_CONFIRMATION,
            thread=interrupt.thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            interrupt_ref=interrupt.model_copy(update={"status": GraphInterruptStatus.RESUMED}),
            payload_ref=resume_payload.payload_ref,
            trace_context=trace_context,
        )

    def pause_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.PAUSE_THREAD,
            thread=thread.model_copy(update={"status": GraphThreadStatus.PAUSED}),
            checkpoint_ref=checkpoint,
            trace_context=trace_context,
        )

    def resume_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_THREAD,
            thread=thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            checkpoint_ref=checkpoint,
            trace_context=trace_context,
        )

    def terminate_thread(
        self,
        *,
        thread: GraphThreadRef,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.TERMINATE_THREAD,
            thread=thread.model_copy(update={"status": GraphThreadStatus.TERMINATED}),
            trace_context=trace_context,
        )

    def assert_thread_terminal(
        self,
        *,
        thread: GraphThreadRef,
        trace_context,
    ) -> GraphThreadRef:
        return thread


def _waiting_status(interrupt_type: GraphInterruptType) -> GraphThreadStatus:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return GraphThreadStatus.WAITING_CLARIFICATION
    if interrupt_type is GraphInterruptType.APPROVAL:
        return GraphThreadStatus.WAITING_APPROVAL
    return GraphThreadStatus.WAITING_TOOL_CONFIRMATION


__all__ = ["InMemoryCheckpointPort", "InMemoryRuntimeCommandPort"]
