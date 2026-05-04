from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.domain.enums import StageType
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphThreadRef,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.services.runtime_orchestration import CheckpointPort


@dataclass(frozen=True)
class LangGraphCheckpointSnapshot:
    thread_id: str
    checkpoint_namespace: str
    checkpoint_id: str
    state_ref: str


def langgraph_thread_config(
    *,
    thread_id: str,
    checkpoint_namespace: str = "",
) -> dict[str, Any]:
    if not thread_id:
        raise ValueError("thread_id is required for LangGraph checkpoint config")
    return {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_namespace,
        }
    }


def read_langgraph_checkpoint_snapshot(
    *,
    compiled_graph: Any,
    config: dict[str, Any],
) -> LangGraphCheckpointSnapshot:
    snapshot = compiled_graph.get_state(config)
    configurable = dict(snapshot.config.get("configurable") or {})
    thread_id = str(configurable.get("thread_id") or "")
    if not thread_id:
        raise ValueError("LangGraph checkpoint thread_id was not available")
    checkpoint_namespace = str(configurable.get("checkpoint_ns") or "")
    checkpoint_id = str(configurable.get("checkpoint_id") or "")
    if not checkpoint_id:
        raise ValueError("LangGraph checkpoint_id was not available after graph invocation")
    namespace_segment = checkpoint_namespace or "default"
    return LangGraphCheckpointSnapshot(
        thread_id=thread_id,
        checkpoint_namespace=checkpoint_namespace,
        checkpoint_id=checkpoint_id,
        state_ref=(
            f"langgraph://{thread_id}/checkpoints/"
            f"{namespace_segment}/{checkpoint_id}"
        ),
    )


def save_graph_checkpoint(
    *,
    compiled_graph: Any,
    config: dict[str, Any],
    checkpoint_port: CheckpointPort,
    thread: GraphThreadRef,
    trace_context: TraceContext,
    stage_run_id: str,
    stage_type: StageType,
    workspace_snapshot_ref: str | None,
) -> CheckpointRef:
    snapshot = read_langgraph_checkpoint_snapshot(
        compiled_graph=compiled_graph,
        config=config,
    )
    if snapshot.thread_id != thread.thread_id:
        raise ValueError("LangGraph checkpoint thread_id must match GraphThreadRef.thread_id")
    return checkpoint_port.save_checkpoint(
        thread=thread,
        purpose=CheckpointPurpose.RUNNING_SAFE_POINT,
        trace_context=trace_context,
        stage_run_id=stage_run_id,
        stage_type=stage_type,
        workspace_snapshot_ref=workspace_snapshot_ref,
        payload_ref=snapshot.state_ref,
    )


__all__ = [
    "LangGraphCheckpointSnapshot",
    "langgraph_thread_config",
    "read_langgraph_checkpoint_snapshot",
    "save_graph_checkpoint",
]
