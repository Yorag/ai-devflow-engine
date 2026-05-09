from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt as langgraph_interrupt

from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.runtime.base import RuntimeExecutionContext
from backend.app.runtime.stage_runner_port import (
    StageNodeInvocation,
    StageNodeResult,
    StageNodeRunnerPort,
)


DEFAULT_ROUTE_KEY = "__default__"
NON_COMPLETED_ROUTE_KEY = "__non_completed_stage_result__"
NON_COMPLETED_BLOCKED_NODE = "__blocked_non_completed_stage_result__"
APPROVAL_APPROVED_ROUTE_KEY = "__approval_approved__"
APPROVAL_REJECTED_ROUTE_KEY = "__approval_rejected__"


class LangGraphRuntimeState(TypedDict, total=False):
    run_id: str
    session_id: str
    current_node_key: str
    completed_stage_run_ids: list[str]
    last_result: dict[str, Any]
    route_key: str


def build_stage_graph(
    *,
    graph_definition: GraphDefinition,
    stage_runner: StageNodeRunnerPort,
    runtime_context: RuntimeExecutionContext,
    now: Callable[[], datetime],
) -> StateGraph:
    stage_nodes = tuple(graph_definition.stage_nodes)
    node_lookup = {
        _node_key(node): dict(node)
        for node in stage_nodes
    }
    graph = StateGraph(LangGraphRuntimeState)
    graph.add_node(NON_COMPLETED_BLOCKED_NODE, _non_completed_stage_result_action)

    for node in stage_nodes:
        node_key = _node_key(node)
        stage_type = _stage_type(node)
        graph.add_node(
            node_key,
            _stage_node_action(
                graph_definition=graph_definition,
                stage_runner=stage_runner,
                runtime_context=runtime_context,
                now=now,
                graph_node_key=node_key,
                stage_type=stage_type,
            ),
        )
        success_node_key = _success_node_key(node)
        if _is_approval_gate(success_node_key):
            graph.add_node(
                success_node_key,
                _approval_gate_action(
                    graph_node_key=success_node_key,
                    stage_node=node,
                ),
            )

    graph.add_edge(START, _node_key(stage_nodes[0]))

    for index, node in enumerate(stage_nodes):
        node_key = _node_key(node)
        default_target = _resolve_success_target(
            node=node,
            node_lookup=node_lookup,
            stage_nodes=stage_nodes,
            index=index,
        )
        conditional_routes = tuple(node.get("conditional_routes") or ())
        if conditional_routes:
            route_map = {
                str(route["route_key"]): str(route["to"])
                for route in conditional_routes
            }
            route_map[DEFAULT_ROUTE_KEY] = default_target
            route_map[NON_COMPLETED_ROUTE_KEY] = NON_COMPLETED_BLOCKED_NODE
            graph.add_conditional_edges(
                node_key,
                _route_selector(frozenset(route_map)),
                route_map,
            )
        else:
            route_map = {
                DEFAULT_ROUTE_KEY: default_target,
                NON_COMPLETED_ROUTE_KEY: NON_COMPLETED_BLOCKED_NODE,
            }
            graph.add_conditional_edges(
                node_key,
                _route_selector(frozenset(route_map)),
                route_map,
            )

        success_node_key = _success_node_key(node)
        if _is_approval_gate(success_node_key):
            graph.add_conditional_edges(
                success_node_key,
                _approval_gate_route_selector(),
                _approval_gate_route_map(node=node, node_lookup=node_lookup),
            )

    return graph


def run_stage_node(
    *,
    state: LangGraphRuntimeState,
    graph_definition: GraphDefinition,
    stage_runner: StageNodeRunnerPort,
    runtime_context: RuntimeExecutionContext,
    now: Callable[[], datetime],
    graph_node_key: str,
    stage_type: StageType,
) -> LangGraphRuntimeState:
    stage_run_id = _stage_run_id(runtime_context, stage_type)
    trace_context = runtime_context.trace_context.child_span(
        span_id=f"langgraph-{graph_node_key}-{stage_run_id}",
        created_at=now(),
        run_id=runtime_context.run_id,
        stage_run_id=stage_run_id,
        graph_thread_id=runtime_context.thread.thread_id,
    )
    invocation = StageNodeInvocation(
        run_id=runtime_context.run_id,
        stage_run_id=stage_run_id,
        stage_type=stage_type,
        graph_node_key=graph_node_key,
        stage_contract_ref=_stage_contract_ref(graph_definition, stage_type),
        runtime_context=runtime_context,
        trace_context=trace_context,
    )
    result = StageNodeResult.model_validate(
        stage_runner.run_stage(invocation)
    )
    _validate_stage_node_result_identity(result, invocation)
    completed_stage_run_ids = list(state.get("completed_stage_run_ids") or [])
    if result.status is StageStatus.COMPLETED:
        completed_stage_run_ids.append(result.stage_run_id)
    return {
        "run_id": runtime_context.run_id,
        "session_id": runtime_context.session_id,
        "current_node_key": graph_node_key,
        "completed_stage_run_ids": completed_stage_run_ids,
        "last_result": result.model_dump(mode="json"),
        "route_key": result.route_key or DEFAULT_ROUTE_KEY,
    }


def _stage_node_action(
    *,
    graph_definition: GraphDefinition,
    stage_runner: StageNodeRunnerPort,
    runtime_context: RuntimeExecutionContext,
    now: Callable[[], datetime],
    graph_node_key: str,
    stage_type: StageType,
) -> Callable[[LangGraphRuntimeState], LangGraphRuntimeState]:
    def _run(state: LangGraphRuntimeState) -> LangGraphRuntimeState:
        return run_stage_node(
            state=state,
            graph_definition=graph_definition,
            stage_runner=stage_runner,
            runtime_context=runtime_context,
            now=now,
            graph_node_key=graph_node_key,
            stage_type=stage_type,
        )

    return _run


def _approval_gate_action(
    *,
    graph_node_key: str,
    stage_node: dict[str, Any],
) -> Callable[[LangGraphRuntimeState], LangGraphRuntimeState]:
    def _run(state: LangGraphRuntimeState) -> LangGraphRuntimeState:
        last_result = state.get("last_result")
        if not isinstance(last_result, dict):
            raise ValueError("Approval gate requires last_result from source stage")
        stage_type = _stage_type(stage_node)
        stage_run_id = _required_last_result_str(last_result, "stage_run_id")
        artifact_refs = last_result.get("artifact_refs")
        payload_ref = (
            artifact_refs[0]
            if isinstance(artifact_refs, list)
            and artifact_refs
            and isinstance(artifact_refs[0], str)
            and artifact_refs[0]
            else f"runtime-approval://{stage_run_id}"
        )
        approval_type = (
            "solution_design_approval"
            if stage_type is StageType.SOLUTION_DESIGN
            else "code_review_approval"
        )
        approval_id = f"approval-{uuid4().hex}"
        resume_value = langgraph_interrupt(
            {
                "interrupt_type": "approval",
                "payload_ref": payload_ref,
                "approval_id": approval_id,
                "approval_type": approval_type,
                "stage_run_id": stage_run_id,
                "stage_type": stage_type.value,
                "graph_node_key": graph_node_key,
            }
        )
        route_key = _approval_route_key(resume_value, stage_type=stage_type)
        return {
            "current_node_key": graph_node_key,
            "route_key": route_key,
            "approval_resume_payload": (
                resume_value if isinstance(resume_value, dict) else None
            ),
            "last_approval_gate": {
                "graph_node_key": graph_node_key,
                "stage_run_id": stage_run_id,
                "stage_type": stage_type.value,
            },
        }

    return _run


def _route_selector(valid_route_keys: frozenset[str]) -> Callable[[LangGraphRuntimeState], str]:
    def _select(state: LangGraphRuntimeState) -> str:
        if _last_stage_status(state) is not StageStatus.COMPLETED:
            return (
                NON_COMPLETED_ROUTE_KEY
                if NON_COMPLETED_ROUTE_KEY in valid_route_keys
                else DEFAULT_ROUTE_KEY
            )
        route_key = state.get("route_key") or DEFAULT_ROUTE_KEY
        if route_key in valid_route_keys:
            return route_key
        return DEFAULT_ROUTE_KEY

    return _select


def _approval_gate_route_selector() -> Callable[[LangGraphRuntimeState], str]:
    def _select(state: LangGraphRuntimeState) -> str:
        route_key = state.get("route_key")
        if route_key == APPROVAL_REJECTED_ROUTE_KEY:
            return APPROVAL_REJECTED_ROUTE_KEY
        return APPROVAL_APPROVED_ROUTE_KEY

    return _select


def _last_stage_status(state: LangGraphRuntimeState) -> StageStatus | None:
    last_result = state.get("last_result")
    if not isinstance(last_result, dict):
        return None
    status = last_result.get("status")
    try:
        return StageStatus(str(status))
    except ValueError:
        return None


def _non_completed_stage_result_action(
    state: LangGraphRuntimeState,
) -> LangGraphRuntimeState:
    last_result = state.get("last_result") or {}
    status = last_result.get("status") if isinstance(last_result, dict) else None
    raise ValueError(
        "LangGraph cannot advance after non-completed stage result: "
        f"{status or 'unknown'}"
    )


def _node_key(node: dict[str, Any]) -> str:
    return str(node["node_key"])


def _success_node_key(node: dict[str, Any]) -> str | None:
    value = node.get("success_node_key")
    if not isinstance(value, str) or not value:
        return None
    return value


def _stage_type(node: dict[str, Any]) -> StageType:
    return StageType(str(node["stage_type"]))


def _stage_run_id(
    runtime_context: RuntimeExecutionContext,
    stage_type: StageType,
) -> str:
    thread = runtime_context.thread
    if (
        thread.current_stage_type is stage_type
        and thread.current_stage_run_id is not None
    ):
        return thread.current_stage_run_id
    return f"stage-run-{runtime_context.run_id}-{stage_type.value}"


def _validate_stage_node_result_identity(
    result: StageNodeResult,
    invocation: StageNodeInvocation,
) -> None:
    if result.run_id != invocation.run_id:
        raise ValueError("StageNodeResult.run_id must match StageNodeInvocation.run_id")
    if result.stage_run_id != invocation.stage_run_id:
        raise ValueError(
            "StageNodeResult.stage_run_id must match StageNodeInvocation.stage_run_id"
        )
    if result.stage_type is not invocation.stage_type:
        raise ValueError(
            "StageNodeResult.stage_type must match StageNodeInvocation.stage_type"
        )


def _stage_contract_ref(
    graph_definition: GraphDefinition,
    stage_type: StageType,
) -> str:
    return (
        f"{graph_definition.graph_definition_id}/stage-contracts/{stage_type.value}"
    )


def _is_approval_gate(node_key: str | None) -> bool:
    return node_key in {
        "solution_design.approval_gate",
        "code_review.approval_gate",
    }


def _resolve_success_target(
    *,
    node: dict[str, Any],
    node_lookup: dict[str, dict[str, Any]],
    stage_nodes: tuple[dict[str, Any], ...],
    index: int,
) -> str:
    success_node_key = _success_node_key(node)
    if success_node_key:
        if _is_approval_gate(success_node_key):
            return success_node_key
        if success_node_key in node_lookup:
            return success_node_key
    if index + 1 < len(stage_nodes):
        return _node_key(stage_nodes[index + 1])
    return END


def _approval_gate_route_map(
    *,
    node: dict[str, Any],
    node_lookup: dict[str, dict[str, Any]],
) -> dict[str, str]:
    stage_type = _stage_type(node)
    approved_target = _default_approved_target(stage_type=stage_type)
    if approved_target not in node_lookup:
        raise ValueError(f"Approval gate target is missing: {approved_target}")
    rejected_target = (
        stage_type.value
        if stage_type is StageType.SOLUTION_DESIGN
        else StageType.CODE_GENERATION.value
    )
    if rejected_target not in node_lookup:
        raise ValueError(f"Approval gate reject target is missing: {rejected_target}")
    return {
        APPROVAL_APPROVED_ROUTE_KEY: approved_target,
        APPROVAL_REJECTED_ROUTE_KEY: rejected_target,
    }


def _default_approved_target(*, stage_type: StageType) -> str:
    if stage_type is StageType.SOLUTION_DESIGN:
        return StageType.CODE_GENERATION.value
    if stage_type is StageType.CODE_REVIEW:
        return StageType.DELIVERY_INTEGRATION.value
    raise ValueError(f"Unsupported approval gate stage_type: {stage_type!r}")


def _required_last_result_str(last_result: dict[str, Any], field_name: str) -> str:
    value = last_result.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Approval gate requires last_result.{field_name}")
    return value


def _approval_route_key(
    resume_value: object,
    *,
    stage_type: StageType,
) -> str:
    payload = _approval_resume_values(resume_value)
    if not isinstance(payload, dict):
        return APPROVAL_APPROVED_ROUTE_KEY
    decision = str(payload.get("decision") or "").strip().lower()
    next_stage_type = str(payload.get("next_stage_type") or "").strip()
    if decision == "rejected" or next_stage_type == _rejected_stage_type(stage_type).value:
        return APPROVAL_REJECTED_ROUTE_KEY
    return APPROVAL_APPROVED_ROUTE_KEY


def _approval_resume_values(resume_value: object) -> dict[str, Any] | None:
    if not isinstance(resume_value, dict):
        return None
    values = resume_value.get("values")
    if isinstance(values, dict):
        return values
    return resume_value


def _rejected_stage_type(stage_type: StageType) -> StageType:
    if stage_type is StageType.SOLUTION_DESIGN:
        return StageType.SOLUTION_DESIGN
    if stage_type is StageType.CODE_REVIEW:
        return StageType.CODE_GENERATION
    raise ValueError(f"Unsupported approval gate stage_type: {stage_type!r}")


__all__ = [
    "APPROVAL_APPROVED_ROUTE_KEY",
    "APPROVAL_REJECTED_ROUTE_KEY",
    "DEFAULT_ROUTE_KEY",
    "LangGraphRuntimeState",
    "NON_COMPLETED_BLOCKED_NODE",
    "NON_COMPLETED_ROUTE_KEY",
    "build_stage_graph",
    "run_stage_node",
]
