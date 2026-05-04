from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.enums import StageType
from backend.app.domain.runtime_refs import (
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadStatus,
    RuntimeResumePayload,
)
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
    langgraph_checkpoint_config_from_ref,
    langgraph_thread_config,
    save_graph_checkpoint,
    save_graph_interrupt_checkpoint,
)
from backend.app.runtime.nodes import LangGraphRuntimeState, build_stage_graph
from backend.app.runtime.stage_runner_port import StageNodeResult, StageNodeRunnerPort
from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus
from backend.app.services.runtime_orchestration import (
    CheckpointPort,
    RuntimeCommandPort,
    RuntimeOrchestrationService,
)


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
        compiled_graph = self._compile_graph(context)
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
            snapshot = compiled_graph.get_state(config)
            interrupts = _interrupts_from_snapshot(snapshot)
            if interrupts:
                return self.create_graph_interrupt(
                    compiled_graph=compiled_graph,
                    config=config,
                    context=context,
                    runtime_port=runtime_port,
                    checkpoint_port=checkpoint_port,
                    graph_interrupt=interrupts[0],
                    fallback_stage_type=self._stage_type_for_node(next_node),
                )
            values = snapshot.values
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
        self._validate_resume_context(context, interrupt)
        compiled_graph = self._compile_graph(context)
        checkpoint_payload_ref = interrupt.interrupt_ref.checkpoint_ref.payload_ref
        if checkpoint_payload_ref is None:
            raise ValueError("LangGraph interrupt checkpoint payload_ref is required")
        config = langgraph_checkpoint_config_from_ref(
            state_ref=checkpoint_payload_ref,
            expected_thread_id=context.thread.thread_id,
        )
        return self.resume_graph_interrupt(
            compiled_graph=compiled_graph,
            config=config,
            context=context,
            interrupt=interrupt,
            resume_payload=resume_payload,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    def resume_from_interrupt(
        self,
        *,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult:
        return self.resume(
            context=context,
            interrupt=interrupt,
            resume_payload=resume_payload,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    def create_graph_interrupt(
        self,
        *,
        compiled_graph: Any,
        config: dict[str, Any],
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        graph_interrupt: Any,
        fallback_stage_type: StageType | None = None,
    ) -> RuntimeInterrupt:
        payload = _coerce_interrupt_payload(graph_interrupt)
        interrupt_type = _required_interrupt_type(payload)
        stage_run_id = _required_str(payload, "stage_run_id")
        stage_type = _stage_type_from_payload(payload, fallback_stage_type)
        payload_ref = _required_str(payload, "payload_ref")
        clarification_id = _optional_str(payload.get("clarification_id"))
        approval_id = _optional_str(payload.get("approval_id"))
        tool_confirmation_id = _optional_str(payload.get("tool_confirmation_id"))
        tool_action_ref = _optional_str(payload.get("tool_action_ref"))
        interrupt_trace = context.trace_context.child_span(
            span_id=f"langgraph-interrupt-{interrupt_type.value}-{stage_run_id}",
            created_at=self._now(),
            run_id=context.run_id,
            stage_run_id=stage_run_id,
            approval_id=approval_id,
            tool_confirmation_id=tool_confirmation_id,
            graph_thread_id=context.thread.thread_id,
        )
        checkpoint = save_graph_interrupt_checkpoint(
            compiled_graph=compiled_graph,
            config=config,
            checkpoint_port=checkpoint_port,
            thread=context.thread,
            trace_context=interrupt_trace,
            interrupt_type=interrupt_type,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            workspace_snapshot_ref=context.workspace_snapshot_ref,
        )
        interrupt_ref = runtime_port.create_interrupt(
            thread=context.thread,
            interrupt_type=interrupt_type,
            run_id=context.run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            payload_ref=payload_ref,
            checkpoint=checkpoint,
            trace_context=interrupt_trace,
            clarification_id=clarification_id,
            approval_id=approval_id,
            tool_confirmation_id=tool_confirmation_id,
            tool_action_ref=tool_action_ref,
        )
        self._record_log(
            "LangGraph interrupt requested.",
            trace_context=interrupt_trace,
            payload_type="langgraph_interrupt_requested",
            summary={
                "action": "interrupt_requested",
                "run_id": context.run_id,
                "session_id": context.session_id,
                "graph_thread_id": context.thread.thread_id,
                "interrupt_id": interrupt_ref.interrupt_id,
                "interrupt_type": interrupt_type.value,
                "payload_ref": payload_ref,
                "stage_run_id": stage_run_id,
                "stage_type": stage_type.value,
                "clarification_id": clarification_id,
                "approval_id": approval_id,
                "tool_confirmation_id": tool_confirmation_id,
                "tool_action_ref": tool_action_ref,
                "checkpoint_id": checkpoint.checkpoint_id,
                "checkpoint_payload_ref": checkpoint.payload_ref,
            },
        )
        return RuntimeInterrupt(
            run_id=context.run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            interrupt_ref=interrupt_ref,
            payload_ref=payload_ref,
            trace_context=interrupt_trace,
            artifact_refs=[],
            domain_event_refs=[],
            log_summary_refs=[],
            audit_refs=[],
        )

    def resume_graph_interrupt(
        self,
        *,
        compiled_graph: Any,
        config: dict[str, Any],
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult:
        resume_trace = context.trace_context.child_span(
            span_id=f"langgraph-resume-{interrupt.interrupt_ref.interrupt_id}",
            created_at=self._now(),
            run_id=context.run_id,
            stage_run_id=interrupt.stage_run_id,
            approval_id=interrupt.interrupt_ref.approval_id,
            tool_confirmation_id=interrupt.interrupt_ref.tool_confirmation_id,
            graph_thread_id=interrupt.interrupt_ref.thread.thread_id,
        )
        self._record_log(
            "LangGraph resume command started.",
            trace_context=resume_trace,
            payload_type="langgraph_resume_command",
            summary={
                "action": "resume_command",
                "run_id": context.run_id,
                "session_id": context.session_id,
                "graph_thread_id": interrupt.interrupt_ref.thread.thread_id,
                "interrupt_id": interrupt.interrupt_ref.interrupt_id,
                "interrupt_type": interrupt.interrupt_ref.interrupt_type.value,
                "resume_id": resume_payload.resume_id,
                "payload_ref": resume_payload.payload_ref,
                "stage_run_id": interrupt.stage_run_id,
                "stage_type": interrupt.stage_type.value,
            },
        )
        orchestration = RuntimeOrchestrationService(
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            clock=self._now,
        )
        command_result = None
        try:
            if (
                interrupt.interrupt_ref.interrupt_type
                is GraphInterruptType.TOOL_CONFIRMATION
            ):
                command_result = orchestration.resume_tool_confirmation(
                    interrupt=interrupt.interrupt_ref,
                    resume_payload=resume_payload,
                    trace_context=resume_trace,
                )
            else:
                command_result = orchestration.resume_interrupt(
                    interrupt=interrupt.interrupt_ref,
                    resume_payload=resume_payload,
                    trace_context=resume_trace,
                )
            resume_node = self._node_key_for_stage(interrupt.stage_type)
            compiled_graph.invoke(
                Command(resume=resume_payload.model_dump(mode="json")),
                config=config,
                interrupt_after=[resume_node],
            )
            latest_config = langgraph_thread_config(thread_id=context.thread.thread_id)
            snapshot = compiled_graph.get_state(latest_config)
            interrupts = _interrupts_from_snapshot(snapshot)
            if interrupts:
                return self.create_graph_interrupt(
                    compiled_graph=compiled_graph,
                    config=latest_config,
                    context=context,
                    runtime_port=runtime_port,
                    checkpoint_port=checkpoint_port,
                    graph_interrupt=interrupts[0],
                    fallback_stage_type=interrupt.stage_type,
                )
            result = StageNodeResult.model_validate(snapshot.values["last_result"])
            checkpoint = save_graph_checkpoint(
                compiled_graph=compiled_graph,
                config=latest_config,
                checkpoint_port=checkpoint_port,
                thread=command_result.thread,
                trace_context=resume_trace,
                stage_run_id=result.stage_run_id,
                stage_type=result.stage_type,
                workspace_snapshot_ref=context.workspace_snapshot_ref,
            )
        except Exception as exc:
            self._record_log(
                "LangGraph resume failed.",
                trace_context=resume_trace,
                payload_type="langgraph_resume_failed",
                summary={
                    "action": "resume_failed",
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "graph_thread_id": interrupt.interrupt_ref.thread.thread_id,
                    "interrupt_id": interrupt.interrupt_ref.interrupt_id,
                    "interrupt_type": interrupt.interrupt_ref.interrupt_type.value,
                    "resume_id": resume_payload.resume_id,
                    "payload_ref": resume_payload.payload_ref,
                    "stage_run_id": interrupt.stage_run_id,
                    "stage_type": interrupt.stage_type.value,
                    "error_type": type(exc).__name__,
                    "error_category": "runtime_resume_failed",
                    "status": "failed",
                },
                level=LogLevel.ERROR,
            )
            raise
        result_trace = resume_trace.child_span(
            span_id=f"langgraph-resume-result-{result.stage_run_id}",
            created_at=self._now(),
            run_id=result.run_id,
            stage_run_id=result.stage_run_id,
            graph_thread_id=context.thread.thread_id,
        )
        self._record_log(
            "LangGraph resume succeeded.",
            trace_context=result_trace,
            payload_type="langgraph_resume_succeeded",
            summary={
                "action": "resume_succeeded",
                "run_id": result.run_id,
                "session_id": context.session_id,
                "graph_thread_id": context.thread.thread_id,
                "interrupt_id": interrupt.interrupt_ref.interrupt_id,
                "interrupt_type": interrupt.interrupt_ref.interrupt_type.value,
                "resume_id": resume_payload.resume_id,
                "command_type": command_result.command_type.value,
                "stage_run_id": result.stage_run_id,
                "stage_type": result.stage_type.value,
                "status": result.status.value,
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

    def _validate_resume_context(
        self,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
    ) -> None:
        if context.graph_definition_ref != self._graph_definition.graph_definition_id:
            raise ValueError(
                "RuntimeExecutionContext.graph_definition_ref does not match graph_definition"
            )
        if context.run_id != interrupt.run_id:
            raise ValueError("LangGraph resume requires the same run_id")
        if context.thread.thread_id != interrupt.interrupt_ref.thread.thread_id:
            raise ValueError("LangGraph resume requires the same GraphThreadRef.thread_id")
        if interrupt.interrupt_ref.status is not GraphInterruptStatus.PENDING:
            raise ValueError("LangGraph resume requires a pending GraphInterrupt")
        expected_status = _waiting_status_for_interrupt_type(
            interrupt.interrupt_ref.interrupt_type
        )
        if context.thread.status is not expected_status:
            raise ValueError(
                "LangGraph resume context waiting status must match interrupt type"
            )
        if (
            context.thread.current_stage_run_id is not None
            and context.thread.current_stage_run_id != interrupt.stage_run_id
        ):
            raise ValueError(
                "LangGraph resume context current stage must match interrupt stage"
            )
        if (
            context.thread.current_stage_type is not None
            and context.thread.current_stage_type is not interrupt.stage_type
        ):
            raise ValueError(
                "LangGraph resume context current stage must match interrupt stage"
            )

    def _compile_graph(self, context: RuntimeExecutionContext) -> Any:
        return build_stage_graph(
            graph_definition=self._graph_definition,
            stage_runner=self._stage_runner,
            runtime_context=context,
            now=self._now,
        ).compile(checkpointer=self._checkpointer)

    def _next_node(self, snapshot: Any) -> str:
        if snapshot.next:
            return str(snapshot.next[0])
        if not snapshot.values:
            return self._first_node_key
        raise ValueError("LangGraph main chain has no next node")

    def _node_key_for_stage(self, stage_type: StageType) -> str:
        for node in self._graph_definition.stage_nodes:
            if StageType(str(node["stage_type"])) is stage_type:
                return str(node["node_key"])
        return stage_type.value

    def _stage_type_for_node(self, node_key: str) -> StageType | None:
        for node in self._graph_definition.stage_nodes:
            if str(node["node_key"]) == node_key:
                return StageType(str(node["stage_type"]))
        return None

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


def _interrupts_from_snapshot(snapshot: Any) -> tuple[Any, ...]:
    interrupts: list[Any] = []
    seen: set[tuple[str, str]] = set()

    def _append(values: object) -> None:
        for interrupt in values or ():
            key = (
                type(interrupt).__name__,
                str(getattr(interrupt, "id", id(interrupt))),
            )
            if key in seen:
                continue
            seen.add(key)
            interrupts.append(interrupt)

    _append(getattr(snapshot, "interrupts", ()) or ())
    for task in getattr(snapshot, "tasks", ()) or ():
        _append(getattr(task, "interrupts", ()) or ())
    return tuple(interrupts)


def _coerce_interrupt_payload(graph_interrupt: Any) -> dict[str, Any]:
    value = getattr(graph_interrupt, "value", graph_interrupt)
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    raise ValueError("LangGraph interrupt payload must be an object")


def _required_interrupt_type(payload: Mapping[str, Any]) -> GraphInterruptType:
    value = payload.get("interrupt_type")
    if not isinstance(value, str) or not value:
        raise ValueError("LangGraph interrupt payload requires interrupt_type")
    return GraphInterruptType(value)


def _required_str(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"LangGraph interrupt payload requires {field_name}")
    return value


def _stage_type_from_payload(
    payload: Mapping[str, Any],
    fallback_stage_type: StageType | None,
) -> StageType:
    value = payload.get("stage_type")
    if isinstance(value, StageType):
        return value
    if isinstance(value, str) and value:
        return StageType(value)
    if fallback_stage_type is not None:
        return fallback_stage_type
    raise ValueError("LangGraph interrupt payload requires stage_type")


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("LangGraph interrupt optional ref fields must be a string")
    return value or None


def _waiting_status_for_interrupt_type(
    interrupt_type: GraphInterruptType,
) -> GraphThreadStatus:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return GraphThreadStatus.WAITING_CLARIFICATION
    if interrupt_type is GraphInterruptType.APPROVAL:
        return GraphThreadStatus.WAITING_APPROVAL
    if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
        return GraphThreadStatus.WAITING_TOOL_CONFIRMATION
    raise ValueError(f"Unsupported graph interrupt type: {interrupt_type!r}")


__all__ = [
    "LangGraphRuntimeEngine",
    "RunLogWriter",
]
