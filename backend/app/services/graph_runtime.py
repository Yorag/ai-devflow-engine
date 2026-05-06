from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.models.graph import (
    GraphCheckpointModel,
    GraphInterruptModel,
    GraphThreadModel,
)
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
from backend.app.domain.trace_context import TraceContext


class GraphRuntimePortError(RuntimeError):
    pass


class GraphCheckpointPort:
    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))

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
        del trace_context
        try:
            thread_model = self._load_thread(thread)
            sequence_index = self._next_sequence_index(thread.thread_id)
            checkpoint_id = _bounded_id(
                "checkpoint",
                thread.thread_id,
                purpose.value,
                str(sequence_index),
                uuid4().hex,
            )
            state_ref = payload_ref or _checkpoint_state_ref(
                thread_id=thread.thread_id,
                checkpoint_id=checkpoint_id,
            )
            node_key = thread_model.current_node_key or (
                stage_type.value if stage_type is not None else "runtime-control"
            )
            checkpoint = GraphCheckpointModel(
                checkpoint_id=checkpoint_id,
                graph_thread_id=thread.thread_id,
                checkpoint_ref=state_ref,
                node_key=node_key,
                state_ref=state_ref,
                sequence_index=sequence_index,
                created_at=self._now(),
            )
            thread_model.last_checkpoint_ref = state_ref
            thread_model.updated_at = self._now()
            self._session.add(checkpoint)
            self._session.add(thread_model)
            self._session.flush()
            return CheckpointRef(
                checkpoint_id=checkpoint_id,
                thread_id=thread.thread_id,
                run_id=thread.run_id,
                stage_run_id=stage_run_id,
                stage_type=stage_type,
                purpose=purpose,
                workspace_snapshot_ref=workspace_snapshot_ref,
                payload_ref=state_ref,
            )
        except SQLAlchemyError as exc:
            raise GraphRuntimePortError(
                "Graph checkpoint storage is unavailable."
            ) from exc

    def load_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> CheckpointRef:
        del trace_context
        try:
            self._load_thread(thread)
            checkpoint_model = self._session.get(
                GraphCheckpointModel,
                checkpoint.checkpoint_id,
            )
        except SQLAlchemyError as exc:
            raise GraphRuntimePortError(
                "Graph checkpoint storage is unavailable."
            ) from exc
        if checkpoint_model is None:
            raise GraphRuntimePortError("Graph checkpoint was not found.")
        if checkpoint_model.graph_thread_id != thread.thread_id:
            raise GraphRuntimePortError(
                "Graph checkpoint does not belong to the requested thread."
            )
        return checkpoint

    def _load_thread(self, thread: GraphThreadRef) -> GraphThreadModel:
        thread_model = self._session.get(GraphThreadModel, thread.thread_id)
        if thread_model is None:
            raise GraphRuntimePortError("Graph thread was not found.")
        if thread_model.run_id != thread.run_id:
            raise GraphRuntimePortError(
                "Graph thread run_id does not match RuntimeExecutionContext."
            )
        return thread_model

    def _next_sequence_index(self, thread_id: str) -> int:
        latest = self._session.scalar(
            select(func.max(GraphCheckpointModel.sequence_index)).where(
                GraphCheckpointModel.graph_thread_id == thread_id
            )
        )
        return int(latest or 0) + 1


class GraphRuntimeCommandPort:
    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))

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
        del trace_context
        try:
            thread_model = self._load_thread(thread)
            runtime_object_ref = _runtime_object_ref(
                interrupt_type=interrupt_type,
                clarification_id=clarification_id,
                approval_id=approval_id,
                tool_confirmation_id=tool_confirmation_id,
            )
            interrupt_id = _bounded_id("interrupt", runtime_object_ref)
            now = self._now()
            source_node_key = thread_model.current_node_key or stage_type.value
            graph_interrupt = GraphInterruptModel(
                interrupt_id=interrupt_id,
                graph_thread_id=thread.thread_id,
                interrupt_type=_graph_interrupt_type(
                    interrupt_type=interrupt_type,
                    stage_type=stage_type,
                ),
                source_stage_type=stage_type,
                source_node_key=source_node_key,
                payload_ref=payload_ref,
                runtime_object_ref=runtime_object_ref,
                runtime_object_type=_runtime_object_type(interrupt_type),
                status="pending",
                requested_at=now,
                responded_at=None,
                created_at=now,
                updated_at=now,
            )
            thread_model.status = "interrupted"
            thread_model.current_interrupt_id = interrupt_id
            thread_model.current_node_key = source_node_key
            thread_model.last_checkpoint_ref = (
                checkpoint.payload_ref or thread_model.last_checkpoint_ref
            )
            thread_model.updated_at = now
            self._session.add(graph_interrupt)
            self._session.add(thread_model)
            self._session.flush()
            return GraphInterruptRef(
                interrupt_id=interrupt_id,
                thread=thread.model_copy(
                    update={"status": _waiting_status(interrupt_type)}
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
        except SQLAlchemyError as exc:
            raise GraphRuntimePortError(
                "Graph interrupt storage is unavailable."
            ) from exc

    def resume_interrupt(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        return self._resume(
            interrupt=interrupt,
            resume_payload=resume_payload,
            trace_context=trace_context,
            command_type=RuntimeCommandType.RESUME_INTERRUPT,
        )

    def resume_tool_confirmation(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        return self._resume(
            interrupt=interrupt,
            resume_payload=resume_payload,
            trace_context=trace_context,
            command_type=RuntimeCommandType.RESUME_TOOL_CONFIRMATION,
        )

    def pause_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        try:
            thread_model = self._load_thread(thread)
            thread_model.status = "paused"
            thread_model.last_checkpoint_ref = (
                checkpoint.payload_ref or thread_model.last_checkpoint_ref
            )
            thread_model.updated_at = self._now()
            self._session.add(thread_model)
            self._session.flush()
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
        except SQLAlchemyError as exc:
            raise GraphRuntimePortError("Graph thread storage is unavailable.") from exc

    def resume_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        try:
            thread_model = self._load_thread(thread)
            next_status = self._resume_thread_model_status(thread_model)
            thread_model.status = next_status
            thread_model.last_checkpoint_ref = (
                checkpoint.payload_ref or thread_model.last_checkpoint_ref
            )
            thread_model.updated_at = self._now()
            self._session.add(thread_model)
            self._session.flush()
            return RuntimeCommandResult(
                command_type=RuntimeCommandType.RESUME_THREAD,
                thread=thread.model_copy(
                    update={
                        "status": self._domain_thread_status(thread_model, thread),
                        "checkpoint_id": checkpoint.checkpoint_id,
                    }
                ),
                checkpoint_ref=checkpoint,
                trace_context=trace_context,
            )
        except SQLAlchemyError as exc:
            raise GraphRuntimePortError("Graph thread storage is unavailable.") from exc

    def terminate_thread(
        self,
        *,
        thread: GraphThreadRef,
        trace_context: TraceContext,
    ) -> RuntimeCommandResult:
        try:
            thread_model = self._load_thread(thread)
            now = self._now()
            self._cancel_current_interrupt(thread_model, responded_at=now)
            thread_model.status = "terminated"
            thread_model.current_interrupt_id = None
            thread_model.updated_at = now
            self._session.add(thread_model)
            self._session.flush()
            return RuntimeCommandResult(
                command_type=RuntimeCommandType.TERMINATE_THREAD,
                thread=thread.model_copy(update={"status": GraphThreadStatus.TERMINATED}),
                trace_context=trace_context,
            )
        except SQLAlchemyError as exc:
            raise GraphRuntimePortError("Graph thread storage is unavailable.") from exc

    def assert_thread_terminal(
        self,
        *,
        thread: GraphThreadRef,
        trace_context: TraceContext,
    ) -> GraphThreadRef:
        del trace_context
        try:
            thread_model = self._load_thread(thread)
        except SQLAlchemyError as exc:
            raise GraphRuntimePortError("Graph thread storage is unavailable.") from exc
        return thread.model_copy(
            update={"status": self._domain_thread_status(thread_model, thread)}
        )

    def _resume(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
        command_type: RuntimeCommandType,
    ) -> RuntimeCommandResult:
        try:
            thread_model = self._load_thread(interrupt.thread)
            graph_interrupt = self._session.get(
                GraphInterruptModel,
                interrupt.interrupt_id,
            )
            if graph_interrupt is None:
                raise GraphRuntimePortError("Graph interrupt was not found.")
            now = self._now()
            graph_interrupt.status = "responded"
            graph_interrupt.responded_at = now
            graph_interrupt.updated_at = now
            thread_model.status = "running"
            thread_model.current_interrupt_id = None
            thread_model.updated_at = now
            self._session.add_all([thread_model, graph_interrupt])
            self._session.flush()
            return RuntimeCommandResult(
                command_type=command_type,
                thread=interrupt.thread.model_copy(
                    update={"status": GraphThreadStatus.RUNNING}
                ),
                interrupt_ref=interrupt.model_copy(
                    update={"status": GraphInterruptStatus.RESUMED}
                ),
                payload_ref=resume_payload.payload_ref,
                trace_context=trace_context,
            )
        except SQLAlchemyError as exc:
            raise GraphRuntimePortError("Graph interrupt storage is unavailable.") from exc

    def _load_thread(self, thread: GraphThreadRef) -> GraphThreadModel:
        thread_model = self._session.get(GraphThreadModel, thread.thread_id)
        if thread_model is None:
            raise GraphRuntimePortError("Graph thread was not found.")
        if thread_model.run_id != thread.run_id:
            raise GraphRuntimePortError(
                "Graph thread run_id does not match RuntimeExecutionContext."
            )
        return thread_model

    def _resume_thread_model_status(self, thread_model: GraphThreadModel) -> str:
        if thread_model.current_interrupt_id:
            return "interrupted"
        return "running"

    def _domain_thread_status(
        self,
        thread_model: GraphThreadModel,
        fallback: GraphThreadRef,
    ) -> GraphThreadStatus:
        if thread_model.status == "interrupted":
            interrupt = (
                self._session.get(GraphInterruptModel, thread_model.current_interrupt_id)
                if thread_model.current_interrupt_id
                else None
            )
            if interrupt is None:
                return fallback.status
            return _waiting_status_from_graph_interrupt_type(interrupt.interrupt_type)
        return GraphThreadStatus(thread_model.status)

    def _cancel_current_interrupt(
        self,
        thread_model: GraphThreadModel,
        *,
        responded_at: datetime,
    ) -> None:
        if not thread_model.current_interrupt_id:
            return
        interrupt = self._session.get(
            GraphInterruptModel,
            thread_model.current_interrupt_id,
        )
        if interrupt is None or interrupt.status != "pending":
            return
        interrupt.status = "cancelled"
        interrupt.responded_at = responded_at
        interrupt.updated_at = responded_at
        self._session.add(interrupt)


def _bounded_id(prefix: str, *parts: str) -> str:
    candidate = f"{prefix}-{'-'.join(parts)}"
    if len(candidate) <= 80:
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _checkpoint_state_ref(*, thread_id: str, checkpoint_id: str) -> str:
    return f"graph-checkpoint://{thread_id}/{checkpoint_id}"


def _runtime_object_ref(
    *,
    interrupt_type: GraphInterruptType,
    clarification_id: str | None,
    approval_id: str | None,
    tool_confirmation_id: str | None,
) -> str:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST and clarification_id:
        return clarification_id
    if interrupt_type is GraphInterruptType.APPROVAL and approval_id:
        return approval_id
    if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION and tool_confirmation_id:
        return tool_confirmation_id
    raise GraphRuntimePortError("Graph interrupt is missing its runtime object ref.")


def _runtime_object_type(interrupt_type: GraphInterruptType) -> str:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return "clarification_record"
    if interrupt_type is GraphInterruptType.APPROVAL:
        return "approval_request"
    if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
        return "tool_confirmation_request"
    raise GraphRuntimePortError(f"Unsupported graph interrupt type: {interrupt_type!r}")


def _graph_interrupt_type(
    *,
    interrupt_type: GraphInterruptType,
    stage_type: StageType,
) -> str:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return "clarification_request"
    if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
        return "tool_confirmation"
    if stage_type is StageType.SOLUTION_DESIGN:
        return "solution_design_approval"
    if stage_type is StageType.CODE_REVIEW:
        return "code_review_approval"
    raise GraphRuntimePortError(
        "Approval graph interrupts require solution_design or code_review stage."
    )


def _waiting_status(interrupt_type: GraphInterruptType) -> GraphThreadStatus:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return GraphThreadStatus.WAITING_CLARIFICATION
    if interrupt_type is GraphInterruptType.APPROVAL:
        return GraphThreadStatus.WAITING_APPROVAL
    if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
        return GraphThreadStatus.WAITING_TOOL_CONFIRMATION
    raise GraphRuntimePortError(f"Unsupported graph interrupt type: {interrupt_type!r}")


def _waiting_status_from_graph_interrupt_type(value: str) -> GraphThreadStatus:
    if value == "clarification_request":
        return GraphThreadStatus.WAITING_CLARIFICATION
    if value in {"solution_design_approval", "code_review_approval"}:
        return GraphThreadStatus.WAITING_APPROVAL
    if value == "tool_confirmation":
        return GraphThreadStatus.WAITING_TOOL_CONFIRMATION
    raise GraphRuntimePortError(f"Unsupported stored graph interrupt type: {value!r}")


__all__ = [
    "GraphCheckpointPort",
    "GraphRuntimeCommandPort",
    "GraphRuntimePortError",
]
