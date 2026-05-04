from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from backend.app.domain.enums import StageType
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptType,
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


def langgraph_checkpoint_config_from_ref(
    *,
    state_ref: str,
    expected_thread_id: str | None = None,
) -> dict[str, Any]:
    checkpoint_ref = parse_langgraph_checkpoint_ref(state_ref=state_ref)
    if (
        expected_thread_id is not None
        and checkpoint_ref.thread_id != expected_thread_id
    ):
        raise ValueError(
            "LangGraph checkpoint ref thread_id must match GraphThreadRef.thread_id"
        )
    config = langgraph_thread_config(
        thread_id=checkpoint_ref.thread_id,
        checkpoint_namespace=checkpoint_ref.checkpoint_namespace,
    )
    config["configurable"]["checkpoint_id"] = checkpoint_ref.checkpoint_id
    return config


def parse_langgraph_checkpoint_ref(
    *,
    state_ref: str,
) -> LangGraphCheckpointSnapshot:
    if not state_ref:
        raise ValueError("LangGraph checkpoint ref is required")
    parsed = urlparse(state_ref)
    if parsed.scheme != "langgraph":
        raise ValueError("LangGraph checkpoint ref must use langgraph scheme")
    thread_id = parsed.netloc
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if (
        not thread_id
        or len(path_segments) != 3
        or path_segments[0] != "checkpoints"
        or not path_segments[1]
        or not path_segments[2]
    ):
        raise ValueError("LangGraph checkpoint ref format is invalid")
    checkpoint_namespace = "" if path_segments[1] == "default" else path_segments[1]
    return LangGraphCheckpointSnapshot(
        thread_id=thread_id,
        checkpoint_namespace=checkpoint_namespace,
        checkpoint_id=path_segments[2],
        state_ref=state_ref,
    )


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


def checkpoint_purpose_for_interrupt(
    interrupt_type: GraphInterruptType,
) -> CheckpointPurpose:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return CheckpointPurpose.WAITING_CLARIFICATION
    if interrupt_type is GraphInterruptType.APPROVAL:
        return CheckpointPurpose.WAITING_APPROVAL
    if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
        return CheckpointPurpose.WAITING_TOOL_CONFIRMATION
    raise ValueError(f"Unsupported graph interrupt type: {interrupt_type!r}")


def save_graph_interrupt_checkpoint(
    *,
    compiled_graph: Any,
    config: dict[str, Any],
    checkpoint_port: CheckpointPort,
    thread: GraphThreadRef,
    trace_context: TraceContext,
    interrupt_type: GraphInterruptType,
    stage_run_id: str,
    stage_type: StageType,
    workspace_snapshot_ref: str | None,
) -> CheckpointRef:
    snapshot = read_langgraph_checkpoint_snapshot(
        compiled_graph=compiled_graph,
        config=config,
    )
    if snapshot.thread_id != thread.thread_id:
        raise ValueError(
            "LangGraph interrupt checkpoint thread_id must match "
            "GraphThreadRef.thread_id"
        )
    return checkpoint_port.save_checkpoint(
        thread=thread,
        purpose=checkpoint_purpose_for_interrupt(interrupt_type),
        trace_context=trace_context,
        stage_run_id=stage_run_id,
        stage_type=stage_type,
        workspace_snapshot_ref=workspace_snapshot_ref,
        payload_ref=snapshot.state_ref,
    )


__all__ = [
    "LangGraphCheckpointSnapshot",
    "checkpoint_purpose_for_interrupt",
    "langgraph_checkpoint_config_from_ref",
    "langgraph_thread_config",
    "parse_langgraph_checkpoint_ref",
    "read_langgraph_checkpoint_snapshot",
    "save_graph_checkpoint",
    "save_graph_interrupt_checkpoint",
]
