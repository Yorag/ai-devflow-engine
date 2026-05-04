from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

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

    graph.add_edge(START, _node_key(stage_nodes[0]))

    for index, node in enumerate(stage_nodes):
        node_key = _node_key(node)
        default_target = (
            _node_key(stage_nodes[index + 1])
            if index + 1 < len(stage_nodes)
            else END
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


__all__ = [
    "DEFAULT_ROUTE_KEY",
    "LangGraphRuntimeState",
    "NON_COMPLETED_BLOCKED_NODE",
    "NON_COMPLETED_ROUTE_KEY",
    "build_stage_graph",
    "run_stage_node",
]
