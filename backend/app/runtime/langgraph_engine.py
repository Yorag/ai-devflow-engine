from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from langgraph.checkpoint.memory import InMemorySaver

from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.runtime_refs import GraphThreadStatus, RuntimeResumePayload
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.runtime.base import (
    RuntimeEngineResult,
    RuntimeExecutionContext,
    RuntimeInterrupt,
    RuntimeStepResult,
    RuntimeTerminalResult,
)
from backend.app.runtime.checkpoints import (
    langgraph_thread_config,
    save_graph_checkpoint,
)
from backend.app.runtime.nodes import LangGraphRuntimeState, build_stage_graph
from backend.app.runtime.stage_runner_port import StageNodeResult, StageNodeRunnerPort
from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus
from backend.app.services.runtime_orchestration import CheckpointPort, RuntimeCommandPort


_LOGGER = logging.getLogger(__name__)


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class LangGraphRuntimeEngine:
    def __init__(
        self,
        *,
        graph_definition: GraphDefinition,
        stage_runner: StageNodeRunnerPort,
        checkpointer: Any | None = None,
        log_writer: RunLogWriter | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._graph_definition = graph_definition
        self._stage_runner = stage_runner
        self._checkpointer = checkpointer or InMemorySaver()
        self._log_writer = log_writer
        self._now = now or (lambda: datetime.now(UTC))
        self._first_node_key = str(graph_definition.stage_nodes[0]["node_key"])

    def start(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult:
        return self.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    def run_next(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult:
        del runtime_port
        self._validate_context(context)

        self._record_log(
            "LangGraph graph built.",
            trace_context=context.trace_context,
            payload_type="langgraph_graph_build",
            summary={
                "action": "graph_build",
                "run_id": context.run_id,
                "graph_thread_id": context.thread.thread_id,
                "graph_definition_id": self._graph_definition.graph_definition_id,
                "graph_version": self._graph_definition.graph_version,
                "stage_count": len(self._graph_definition.stage_nodes),
            },
        )
        compiled_graph = build_stage_graph(
            graph_definition=self._graph_definition,
            stage_runner=self._stage_runner,
            runtime_context=context,
            now=self._now,
        ).compile(checkpointer=self._checkpointer)
        config = langgraph_thread_config(thread_id=context.thread.thread_id)
        current_snapshot = compiled_graph.get_state(config)
        next_node = self._next_node(current_snapshot)
        graph_input: LangGraphRuntimeState | None = None
        if not current_snapshot.values:
            graph_input = {
                "run_id": context.run_id,
                "session_id": context.session_id,
                "completed_stage_run_ids": [],
            }
            self._record_log(
                "LangGraph thread started.",
                trace_context=context.trace_context,
                payload_type="langgraph_thread_start",
                summary={
                    "action": "thread_start",
                    "run_id": context.run_id,
                    "graph_thread_id": context.thread.thread_id,
                },
            )

        self._record_log(
            "LangGraph node started.",
            trace_context=context.trace_context,
            payload_type="langgraph_node_started",
            summary={
                "action": "node_started",
                "run_id": context.run_id,
                "graph_thread_id": context.thread.thread_id,
                "node_key": next_node,
            },
        )
        try:
            compiled_graph.invoke(
                graph_input,
                config=config,
                interrupt_after=[next_node],
            )
            values = compiled_graph.get_state(config).values
            result = StageNodeResult.model_validate(values["last_result"])
            checkpoint = save_graph_checkpoint(
                compiled_graph=compiled_graph,
                config=config,
                checkpoint_port=checkpoint_port,
                thread=context.thread,
                trace_context=context.trace_context,
                stage_run_id=result.stage_run_id,
                stage_type=result.stage_type,
                workspace_snapshot_ref=context.workspace_snapshot_ref,
            )
        except Exception as exc:
            self._record_log(
                "LangGraph execution failed.",
                trace_context=context.trace_context,
                payload_type="langgraph_graph_failed",
                summary={
                    "action": "graph_failed",
                    "run_id": context.run_id,
                    "graph_thread_id": context.thread.thread_id,
                    "node_key": next_node,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
                level=LogLevel.ERROR,
            )
            raise

        result_trace = context.trace_context.child_span(
            span_id=f"langgraph-result-{result.stage_run_id}",
            created_at=self._now(),
            run_id=result.run_id,
            stage_run_id=result.stage_run_id,
            graph_thread_id=context.thread.thread_id,
        )
        self._record_log(
            "LangGraph node completed.",
            trace_context=result_trace,
            payload_type="langgraph_node_completed",
            summary={
                "action": "node_completed",
                "run_id": result.run_id,
                "graph_thread_id": context.thread.thread_id,
                "node_key": next_node,
                "stage_run_id": result.stage_run_id,
                "stage_type": result.stage_type.value,
                "status": result.status.value,
                "route_key": result.route_key,
                "artifact_ref_count": len(result.artifact_refs),
                "domain_event_ref_count": len(result.domain_event_refs),
                "log_summary_ref_count": len(result.log_summary_refs),
                "audit_ref_count": len(result.audit_refs),
            },
        )
        self._record_log(
            "LangGraph checkpoint synchronized.",
            trace_context=result_trace,
            payload_type="langgraph_checkpoint_saved",
            summary={
                "action": "checkpoint_saved",
                "run_id": result.run_id,
                "graph_thread_id": context.thread.thread_id,
                "stage_run_id": result.stage_run_id,
                "stage_type": result.stage_type.value,
                "checkpoint_id": checkpoint.checkpoint_id,
                "checkpoint_payload_ref": checkpoint.payload_ref,
            },
        )
        return RuntimeStepResult(
            run_id=result.run_id,
            stage_run_id=result.stage_run_id,
            stage_type=result.stage_type,
            status=result.status,
            trace_context=result_trace,
            artifact_refs=result.artifact_refs,
            domain_event_refs=result.domain_event_refs,
            log_summary_refs=result.log_summary_refs,
            audit_refs=result.audit_refs,
            checkpoint_ref=checkpoint,
        )

    def resume(
        self,
        *,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult:
        del context, interrupt, resume_payload, runtime_port, checkpoint_port
        raise NotImplementedError("LangGraph interrupt resume is implemented by A4.6.")

    def terminate(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeTerminalResult:
        del context, runtime_port, checkpoint_port
        raise NotImplementedError("LangGraph terminal control integration is outside A4.5.")

    def _validate_context(self, context: RuntimeExecutionContext) -> None:
        if context.graph_definition_ref != self._graph_definition.graph_definition_id:
            raise ValueError(
                "RuntimeExecutionContext.graph_definition_ref does not match graph_definition"
            )
        if context.thread.status is not GraphThreadStatus.RUNNING:
            raise ValueError("LangGraphRuntimeEngine requires a running GraphThreadRef")

    def _next_node(self, snapshot: Any) -> str:
        if snapshot.next:
            return str(snapshot.next[0])
        if not snapshot.values:
            return self._first_node_key
        raise ValueError("LangGraph main chain has no next node")

    def _record_log(
        self,
        message: str,
        *,
        trace_context: TraceContext,
        payload_type: str,
        summary: dict[str, object],
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        if self._log_writer is None:
            return
        payload = LogPayloadSummary(
            payload_type=payload_type,
            summary=dict(summary),
            excerpt=None,
            payload_size_bytes=0,
            content_hash="",
            redaction_status=RedactionStatus.NOT_REQUIRED,
        )
        try:
            self._log_writer.write_run_log(
                LogRecordInput(
                    source="runtime.langgraph",
                    category=LogCategory.RUNTIME,
                    level=level,
                    message=message,
                    trace_context=trace_context,
                    payload=payload,
                    created_at=self._now(),
                )
            )
        except Exception:
            _LOGGER.exception("LangGraph runtime log write failed")


__all__ = ["LangGraphRuntimeEngine", "RunLogWriter"]
