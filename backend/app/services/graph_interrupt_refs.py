from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models.graph import (
    GraphCheckpointModel,
    GraphInterruptModel,
    GraphThreadModel,
)
from backend.app.db.models.runtime import PipelineRunModel, StageRunModel
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
)


class GraphInterruptRefError(RuntimeError):
    pass


def build_persisted_graph_interrupt_ref(
    *,
    graph_session: Session,
    run: PipelineRunModel,
    stage: StageRunModel,
    interrupt_id: str,
    interrupt_type: GraphInterruptType,
    payload_ref: str,
    checkpoint_purpose: CheckpointPurpose,
    thread_status: GraphThreadStatus,
    clarification_id: str | None = None,
    approval_id: str | None = None,
    tool_confirmation_id: str | None = None,
    tool_action_ref: str | None = None,
) -> GraphInterruptRef:
    thread_model = graph_session.get(GraphThreadModel, run.graph_thread_ref)
    if thread_model is None:
        raise GraphInterruptRefError("Graph thread was not found for interrupt resume.")
    if thread_model.run_id != run.run_id:
        raise GraphInterruptRefError("Graph thread does not belong to the run.")

    interrupt_model = graph_session.get(GraphInterruptModel, interrupt_id)
    if interrupt_model is None:
        raise GraphInterruptRefError("Graph interrupt was not found for resume.")
    if interrupt_model.graph_thread_id != thread_model.graph_thread_id:
        raise GraphInterruptRefError("Graph interrupt does not belong to the thread.")
    if interrupt_model.status != "pending":
        raise GraphInterruptRefError("Graph interrupt is no longer pending.")
    if interrupt_model.source_stage_type is not stage.stage_type:
        raise GraphInterruptRefError("Graph interrupt source stage does not match.")

    checkpoint_model = _load_resume_checkpoint(
        graph_session=graph_session,
        thread_model=thread_model,
    )
    return GraphInterruptRef(
        interrupt_id=interrupt_id,
        thread=GraphThreadRef(
            thread_id=thread_model.graph_thread_id,
            run_id=run.run_id,
            status=thread_status,
            current_stage_run_id=stage.stage_run_id,
            current_stage_type=stage.stage_type,
            checkpoint_id=checkpoint_model.checkpoint_id,
        ),
        interrupt_type=interrupt_type,
        status=GraphInterruptStatus.PENDING,
        run_id=run.run_id,
        stage_run_id=stage.stage_run_id,
        stage_type=stage.stage_type,
        payload_ref=payload_ref,
        clarification_id=clarification_id,
        approval_id=approval_id,
        tool_confirmation_id=tool_confirmation_id,
        tool_action_ref=tool_action_ref,
        checkpoint_ref=CheckpointRef(
            checkpoint_id=checkpoint_model.checkpoint_id,
            thread_id=thread_model.graph_thread_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            purpose=checkpoint_purpose,
            workspace_snapshot_ref=None,
            payload_ref=checkpoint_model.state_ref,
        ),
    )


def _load_resume_checkpoint(
    *,
    graph_session: Session,
    thread_model: GraphThreadModel,
) -> GraphCheckpointModel:
    if thread_model.last_checkpoint_ref:
        checkpoint = graph_session.scalar(
            select(GraphCheckpointModel).where(
                GraphCheckpointModel.graph_thread_id == thread_model.graph_thread_id,
                GraphCheckpointModel.state_ref == thread_model.last_checkpoint_ref,
            )
        )
        if checkpoint is not None:
            return checkpoint

    checkpoint = graph_session.scalar(
        select(GraphCheckpointModel)
        .where(GraphCheckpointModel.graph_thread_id == thread_model.graph_thread_id)
        .order_by(GraphCheckpointModel.sequence_index.desc())
    )
    if checkpoint is None:
        raise GraphInterruptRefError("Graph checkpoint was not found for resume.")
    return checkpoint


__all__ = [
    "GraphInterruptRefError",
    "build_persisted_graph_interrupt_ref",
]
