from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import PipelineTemplateModel, SessionModel
from backend.app.db.models.graph import (
    GraphCheckpointModel,
    GraphDefinitionModel,
    GraphInterruptModel,
    GraphThreadModel,
)
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ClarificationRecordModel,
    ModelBindingSnapshotModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    ProviderSnapshotModel,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.changes import ChangeSet, ContextReference
from backend.app.domain.enums import (
    ApprovalType,
    RunStatus,
    SessionStatus,
    StageStatus,
    StageType,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.runtime_refs import (
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeResumePayload,
)
from backend.app.domain.template_snapshot import TemplateSnapshot, TemplateSnapshotBuilder
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.audit import AuditService
from backend.app.observability.log_index import LogIndexRepository
from backend.app.observability.log_writer import (
    JsonlLogWriter,
    LogPayloadSummary,
    LogRecordInput,
)
from backend.app.observability.redaction import RedactionPolicy
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.providers.langchain_adapter import LangChainProviderAdapter
from backend.app.providers.provider_registry import ProviderRegistry
from backend.app.prompts.registry import PromptRegistry
from backend.app.prompts.renderer import PromptRenderer
from backend.app.runtime.agent_decision import (
    AgentDecisionParser,
    agent_decision_response_schema,
)
from backend.app.runtime.base import (
    RuntimeEngine,
    RuntimeEngineResult,
    RuntimeExecutionContext,
    RuntimeInterrupt,
    RuntimeStepResult,
    RuntimeTerminalResult,
)
from backend.app.runtime.langgraph_engine import LangGraphRuntimeEngine
from backend.app.runtime.persistent_checkpointer import SQLiteLangGraphCheckpointSaver
from backend.app.runtime.stage_agent import StageAgentRuntime
from backend.app.runtime.stage_runner_port import StageNodeInvocation, StageNodeResult
from backend.app.schemas import common
from backend.app.schemas.feed import ExecutionNodeProjection, StageItemProjection
from backend.app.schemas.observability import AuditActorType, LogCategory, LogLevel
from backend.app.schemas.runtime_settings import (
    ModelBindingSnapshotRead,
    ProviderCallPolicySnapshotRead,
    ProviderSnapshotRead,
    RuntimeLimitSnapshotRead,
)
from backend.app.services.artifacts import ArtifactStore
from backend.app.services.approvals import ApprovalService
from backend.app.services.clarifications import ClarificationService
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.graph_runtime import GraphCheckpointPort, GraphRuntimeCommandPort
from backend.app.services.runs import TerminalStatusProjector
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
from backend.app.services.stages import StageRunService
from backend.app.services.tool_confirmations import ToolConfirmationService
from backend.app.tools.registry import ToolRegistry


_LOGGER = logging.getLogger(__name__)


class RuntimeDispatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    graph_thread_id: str = Field(min_length=1)
    trace_context: TraceContext


class RuntimeExecutionDispatcher(Protocol):
    def dispatch_started_run(self, command: RuntimeDispatchCommand) -> None: ...

    def run_next(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
    ) -> RuntimeEngineResult | None: ...

    def resume(
        self,
        *,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeEngineResult | None: ...


@dataclass(frozen=True)
class RuntimeEngineFactoryInput:
    context: RuntimeExecutionContext
    control_session: Session
    runtime_session: Session
    graph_session: Session
    event_session: Session
    log_session: Session
    environment_settings: EnvironmentSettings
    log_writer: JsonlLogWriter
    now: Callable[[], datetime]


RuntimeEngineFactory = Callable[[RuntimeEngineFactoryInput], RuntimeEngine]


class RuntimeExecutionService:
    def __init__(
        self,
        *,
        database_manager: DatabaseManager,
        environment_settings: EnvironmentSettings,
        engine_factory: RuntimeEngineFactory | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._environment_settings = environment_settings
        self._auto_continue_completed_steps = engine_factory is None
        self._engine_factory = engine_factory or self._default_engine_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._redaction_policy = RedactionPolicy()
        self._langgraph_checkpointer: Any | None = None

    def dispatch_started_run(self, command: RuntimeDispatchCommand) -> None:
        if not self._auto_continue_completed_steps:
            self._execute(
                run_id=command.run_id,
                trace_context=command.trace_context,
                method_name="start",
                expected_command=command,
            )
            return
        self._execute_until_blocked_or_terminal(
            run_id=command.run_id,
            trace_context=command.trace_context,
            expected_command=command,
        )

    def _execute_until_blocked_or_terminal(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
        expected_command: RuntimeDispatchCommand | None = None,
    ) -> RuntimeEngineResult | None:
        result = self._execute(
            run_id=run_id,
            trace_context=trace_context,
            method_name="start",
            expected_command=expected_command,
        )
        return self._continue_completed_steps(
            run_id=run_id,
            trace_context=trace_context,
            result=result,
        )

    def _continue_completed_steps(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
        result: RuntimeEngineResult | None,
    ) -> RuntimeEngineResult | None:
        max_steps = self._max_auto_run_next_steps(run_id)
        steps = 0
        while self._should_auto_continue(result):
            if steps >= max_steps:
                self._mark_auto_continue_limit_failed(
                    run_id=run_id,
                    trace_context=trace_context,
                    max_steps=max_steps,
                )
                return None
            steps += 1
            result = self._execute(
                run_id=run_id,
                trace_context=trace_context,
                method_name="run_next",
            )
        return result

    def run_next(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
    ) -> RuntimeEngineResult | None:
        return self._execute(
            run_id=run_id,
            trace_context=trace_context,
            method_name="run_next",
        )

    def resume(
        self,
        *,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
    ) -> RuntimeEngineResult | None:
        result = self._execute(
            run_id=interrupt.run_id,
            trace_context=trace_context,
            method_name="resume",
            interrupt=interrupt,
            resume_payload=resume_payload,
        )
        if not self._auto_continue_completed_steps:
            return result
        return self._continue_completed_steps(
            run_id=interrupt.run_id,
            trace_context=trace_context,
            result=result,
        )

    @staticmethod
    def _should_auto_continue(result: RuntimeEngineResult | None) -> bool:
        return (
            isinstance(result, RuntimeStepResult)
            and result.status is StageStatus.COMPLETED
        )

    def _execute(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
        method_name: str,
        expected_command: RuntimeDispatchCommand | None = None,
        interrupt: RuntimeInterrupt | None = None,
        resume_payload: RuntimeResumePayload | None = None,
    ) -> RuntimeEngineResult | None:
        control_session = self._database_manager.session(DatabaseRole.CONTROL)
        runtime_session = self._database_manager.session(DatabaseRole.RUNTIME)
        graph_session = self._database_manager.session(DatabaseRole.GRAPH)
        event_session = self._database_manager.session(DatabaseRole.EVENT)
        log_session = self._database_manager.session(DatabaseRole.LOG)
        log_writer = JsonlLogWriter(
            RuntimeDataSettings.from_environment_settings(self._environment_settings)
        )
        try:
            context = self._build_context(
                run_id=run_id,
                trace_context=trace_context,
                runtime_session=runtime_session,
                graph_session=graph_session,
                expected_command=expected_command,
                interrupt=interrupt,
                span_prefix=f"runtime-execution-{method_name}",
            )
            engine = self._engine_factory(
                RuntimeEngineFactoryInput(
                    context=context,
                    control_session=control_session,
                    runtime_session=runtime_session,
                    graph_session=graph_session,
                    event_session=event_session,
                    log_session=log_session,
                    environment_settings=self._environment_settings,
                    log_writer=log_writer,
                    now=self._now,
                )
            )
            runtime_port = GraphRuntimeCommandPort(graph_session, now=self._now)
            checkpoint_port = GraphCheckpointPort(graph_session, now=self._now)
            if method_name == "start":
                result = engine.start(
                    context=context,
                    runtime_port=runtime_port,
                    checkpoint_port=checkpoint_port,
                )
            elif method_name == "run_next":
                result = engine.run_next(
                    context=context,
                    runtime_port=runtime_port,
                    checkpoint_port=checkpoint_port,
                )
            elif method_name == "resume":
                if interrupt is None or resume_payload is None:
                    raise ValueError("resume requires interrupt and resume_payload")
                result = engine.resume(
                    context=context,
                    interrupt=interrupt,
                    resume_payload=resume_payload,
                    runtime_port=runtime_port,
                    checkpoint_port=checkpoint_port,
                )
            else:
                raise ValueError(f"unsupported runtime execution method: {method_name}")
            if self._result_is_failed(result):
                self._mark_execution_failed(
                    run_id=run_id,
                    trace_context=context.trace_context,
                    reason="Runtime engine reported a failed stage result.",
                    error_type="RuntimeStepResult",
                    interrupt=interrupt,
                    control_session=control_session,
                    runtime_session=runtime_session,
                    graph_session=graph_session,
                    event_session=event_session,
                    log_session=log_session,
                    log_writer=log_writer,
                )
            else:
                self._project_runtime_result(
                    result=result,
                    context=context,
                    control_session=control_session,
                    runtime_session=runtime_session,
                    graph_session=graph_session,
                    event_session=event_session,
                    log_session=log_session,
                    log_writer=log_writer,
                )
                self._commit_sessions(
                    control_session=control_session,
                    runtime_session=runtime_session,
                    graph_session=graph_session,
                    event_session=event_session,
                )
            return result
        except Exception as exc:
            safe_reason = _safe_failure_reason(exc)
            failure_trace = self._failure_trace(
                trace_context=trace_context,
                run_id=run_id,
                runtime_session=runtime_session,
            )
            self._rollback_sessions(
                control_session=control_session,
                runtime_session=runtime_session,
                graph_session=graph_session,
                event_session=event_session,
            )
            try:
                self._mark_execution_failed(
                    run_id=run_id,
                    trace_context=failure_trace,
                    reason=safe_reason,
                    error_type=type(exc).__name__,
                    interrupt=interrupt,
                    control_session=control_session,
                    runtime_session=runtime_session,
                    graph_session=graph_session,
                    event_session=event_session,
                    log_session=log_session,
                    log_writer=log_writer,
                )
            except Exception:
                _LOGGER.exception(
                    "Runtime execution failed and failure projection failed.",
                    extra={"run_id": run_id, "method_name": method_name},
                )
                raise
            return None
        finally:
            control_session.close()
            runtime_session.close()
            graph_session.close()
            event_session.close()
            log_session.close()

    def _build_context(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
        runtime_session: Session,
        graph_session: Session,
        expected_command: RuntimeDispatchCommand | None = None,
        interrupt: RuntimeInterrupt | None = None,
        span_prefix: str,
    ) -> RuntimeExecutionContext:
        run = self._require_run(runtime_session, run_id)
        stage = self._require_current_stage(runtime_session, run)
        thread_model = self._require_thread(graph_session, run)
        if expected_command is not None:
            self._validate_started_command(
                command=expected_command,
                run=run,
                stage=stage,
                thread_model=thread_model,
            )
        provider_refs = self._provider_snapshot_refs(runtime_session, run.run_id)
        model_binding_refs = self._model_binding_snapshot_refs(runtime_session, run.run_id)
        if not provider_refs or not model_binding_refs:
            raise RuntimeError("PipelineRun runtime snapshots are incomplete.")
        resolved_trace = self._execution_trace(
            trace_context=trace_context,
            run=run,
            stage=stage,
            graph_thread_id=thread_model.graph_thread_id,
            span_id=f"{span_prefix}-{run.run_id}",
        )
        return RuntimeExecutionContext(
            run_id=run.run_id,
            session_id=run.session_id,
            thread=self._thread_ref(
                graph_session,
                run=run,
                stage=stage,
                thread_model=thread_model,
                interrupt=interrupt,
            ),
            trace_context=resolved_trace,
            template_snapshot_ref=run.template_snapshot_ref,
            provider_snapshot_refs=provider_refs,
            model_binding_snapshot_refs=model_binding_refs,
            runtime_limit_snapshot_ref=run.runtime_limit_snapshot_ref,
            provider_call_policy_snapshot_ref=run.provider_call_policy_snapshot_ref,
            graph_definition_ref=run.graph_definition_ref,
            delivery_channel_snapshot_ref=run.delivery_channel_snapshot_ref,
            workspace_snapshot_ref=run.workspace_ref,
        )

    def _mark_execution_failed(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
        reason: str,
        error_type: str,
        interrupt: RuntimeInterrupt | None = None,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session,
        event_session: Session,
        log_session: Session,
        log_writer: JsonlLogWriter,
    ) -> None:
        run = self._require_run(runtime_session, run_id)
        stage = self._require_current_stage(runtime_session, run)
        session_model = control_session.get(SessionModel, run.session_id)
        if session_model is None:
            raise RuntimeError("Runtime execution failure session was not found.")
        thread = self._require_thread(graph_session, run)
        occurred_at = self._now()
        failure_trace = self._execution_trace(
            trace_context=trace_context,
            run=run,
            stage=stage,
            graph_thread_id=thread.graph_thread_id,
            span_id=f"runtime-execution-failed-{run.run_id}",
            created_at=occurred_at,
        )
        run.status = RunStatus.FAILED
        run.ended_at = occurred_at
        run.updated_at = occurred_at
        stage.status = StageStatus.FAILED
        stage.summary = reason
        stage.ended_at = occurred_at
        stage.updated_at = occurred_at
        session_model.status = SessionStatus.FAILED
        session_model.latest_stage_type = stage.stage_type
        session_model.updated_at = occurred_at
        thread.status = "failed"
        thread.current_node_key = stage.graph_node_key
        thread.updated_at = occurred_at
        self._cancel_current_interrupt(
            graph_session,
            interrupt=interrupt,
            thread=thread,
            cancelled_at=occurred_at,
        )
        thread.current_interrupt_id = None
        runtime_session.add_all([run, stage])
        control_session.add(session_model)
        graph_session.add(thread)

        events = EventStore(event_session, now=self._now)
        stage_node = ExecutionNodeProjection(
            entry_id=_bounded_id("entry", stage.stage_run_id, "failed"),
            run_id=run.run_id,
            occurred_at=occurred_at,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            status=stage.status,
            attempt_index=stage.attempt_index,
            started_at=stage.started_at,
            ended_at=stage.ended_at,
            summary=reason,
            items=self._stage_progress_items(
                runtime_session,
                run=run,
                stage=stage,
                occurred_at=occurred_at,
                artifact_refs=[],
            ),
            metrics=self._stage_metrics(
                runtime_session,
                artifact_refs=[],
            ),
        )
        events.append(
            DomainEventType.STAGE_UPDATED,
            payload={"stage_node": stage_node.model_dump(mode="json")},
            trace_context=failure_trace,
            session_id=session_model.session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            occurred_at=occurred_at,
        )
        TerminalStatusProjector(events=events, now=self._now).append_terminal_system_status(
            domain_event_type=DomainEventType.RUN_FAILED,
            run=run,
            title="Run failed",
            reason=reason,
            trace_context=failure_trace,
            is_current_tail=session_model.current_run_id == run.run_id,
            occurred_at=occurred_at,
        )
        self._commit_sessions(
            control_session=control_session,
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
        )
        self._record_failure_audit(
            log_session=log_session,
            log_writer=log_writer,
            run=run,
            stage=stage,
            thread=thread,
            reason=reason,
            error_type=error_type,
            trace_context=failure_trace,
            occurred_at=occurred_at,
        )
        self._record_failure_log(
            log_session=log_session,
            log_writer=log_writer,
            run=run,
            stage=stage,
            thread=thread,
            reason=reason,
            error_type=error_type,
            trace_context=failure_trace,
            occurred_at=occurred_at,
        )

    def _project_runtime_result(
        self,
        *,
        result: RuntimeEngineResult,
        context: RuntimeExecutionContext,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session,
        event_session: Session,
        log_session: Session,
        log_writer: JsonlLogWriter,
    ) -> None:
        if isinstance(result, RuntimeStepResult):
            if self._project_waiting_step_as_actionable_interrupt(
                result=result,
                context=context,
                control_session=control_session,
                runtime_session=runtime_session,
                graph_session=graph_session,
                event_session=event_session,
                log_session=log_session,
                log_writer=log_writer,
            ):
                return
            self._project_step_result(
                result=result,
                context=context,
                control_session=control_session,
                runtime_session=runtime_session,
                event_session=event_session,
            )
            return
        if isinstance(result, RuntimeInterrupt):
            self._project_interrupt_result(
                result=result,
                context=context,
                control_session=control_session,
                runtime_session=runtime_session,
                graph_session=graph_session,
                event_session=event_session,
            )
            return
        if isinstance(result, RuntimeTerminalResult):
            self._project_terminal_result(
                result=result,
                context=context,
                control_session=control_session,
                runtime_session=runtime_session,
                graph_session=graph_session,
                event_session=event_session,
            )

    def _project_step_result(
        self,
        *,
        result: RuntimeStepResult,
        context: RuntimeExecutionContext,
        control_session: Session,
        runtime_session: Session,
        event_session: Session,
    ) -> None:
        run = self._require_run(runtime_session, result.run_id)
        stage = runtime_session.get(StageRunModel, result.stage_run_id)
        if stage is None:
            raise RuntimeError("Runtime step result StageRun was not found.")
        if stage.run_id != run.run_id or stage.stage_type is not result.stage_type:
            raise RuntimeError("Runtime step result does not match StageRun.")
        session_model = control_session.get(SessionModel, run.session_id)
        if session_model is None:
            raise RuntimeError("Runtime step result session was not found.")

        occurred_at = self._now()
        stage.status = result.status
        stage.updated_at = occurred_at
        stage.summary = _stage_result_summary(stage, result.status)
        if result.status is StageStatus.COMPLETED:
            stage.ended_at = occurred_at
            if stage.output_ref is None and result.artifact_refs:
                stage.output_ref = result.artifact_refs[0]
        run.status = _run_status_for_stage_status(result.status)
        run.current_stage_run_id = stage.stage_run_id
        run.updated_at = occurred_at
        session_model.status = _session_status_for_stage_status(result.status)
        session_model.latest_stage_type = stage.stage_type
        session_model.updated_at = occurred_at
        runtime_session.add_all([run, stage])
        control_session.add(session_model)

        stage_node = ExecutionNodeProjection(
            entry_id=_bounded_id("entry", stage.stage_run_id, result.status.value),
            run_id=run.run_id,
            occurred_at=occurred_at,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            status=stage.status,
            attempt_index=stage.attempt_index,
            started_at=stage.started_at,
            ended_at=stage.ended_at,
            summary=stage.summary or _stage_result_summary(stage, result.status),
            items=self._stage_progress_items(
                runtime_session,
                run=run,
                stage=stage,
                occurred_at=occurred_at,
                artifact_refs=result.artifact_refs,
            ),
            metrics=self._stage_metrics(
                runtime_session,
                artifact_refs=result.artifact_refs,
            ),
        )
        EventStore(event_session, now=self._now).append(
            DomainEventType.STAGE_UPDATED,
            payload={"stage_node": stage_node.model_dump(mode="json")},
            trace_context=result.trace_context,
            session_id=session_model.session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            occurred_at=occurred_at,
        )

    def _project_waiting_step_as_actionable_interrupt(
        self,
        *,
        result: RuntimeStepResult,
        context: RuntimeExecutionContext,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session,
        event_session: Session,
        log_session: Session,
        log_writer: JsonlLogWriter,
    ) -> bool:
        if result.status is StageStatus.WAITING_CLARIFICATION:
            self._request_runtime_clarification(
                result=result,
                context=context,
                control_session=control_session,
                runtime_session=runtime_session,
                graph_session=graph_session,
                event_session=event_session,
                log_session=log_session,
                log_writer=log_writer,
            )
            return True
        if result.status is StageStatus.WAITING_TOOL_CONFIRMATION:
            self._request_runtime_tool_confirmation(
                result=result,
                context=context,
                control_session=control_session,
                runtime_session=runtime_session,
                graph_session=graph_session,
                event_session=event_session,
                log_session=log_session,
                log_writer=log_writer,
            )
            return True
        if result.status is StageStatus.WAITING_APPROVAL:
            self._request_runtime_approval(
                result=result,
                context=context,
                control_session=control_session,
                runtime_session=runtime_session,
                graph_session=graph_session,
                event_session=event_session,
                log_session=log_session,
                log_writer=log_writer,
            )
            return True
        return False

    def _request_runtime_clarification(
        self,
        *,
        result: RuntimeStepResult,
        context: RuntimeExecutionContext,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session,
        event_session: Session,
        log_session: Session,
        log_writer: JsonlLogWriter,
    ) -> None:
        artifact = self._latest_stage_artifact(
            runtime_session,
            run_id=result.run_id,
            stage_run_id=result.stage_run_id,
            artifact_refs=result.artifact_refs,
        )
        process = dict(artifact.process) if artifact is not None else {}
        clarification = self._latest_process_mapping(process, "clarification_request")
        question = _first_text(
            clarification,
            ("question", "prompt", "summary"),
            default=f"{result.stage_type.value} requires clarification before continuing.",
        )
        payload_ref = _first_text(
            clarification,
            ("payload_ref", "source_ref"),
            default=(
                f"stage-artifact://{artifact.artifact_id}#process/clarification_request"
                if artifact is not None
                else f"runtime-wait://{result.stage_run_id}/clarification"
            ),
        )
        ClarificationService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
            graph_session=graph_session,
            audit_service=AuditService(log_session, audit_writer=log_writer),
            runtime_orchestration=self._runtime_orchestration(graph_session),
            now=self._now,
        ).request_clarification(
            session_id=context.session_id,
            run_id=result.run_id,
            stage_run_id=result.stage_run_id,
            question=question,
            payload_ref=payload_ref,
            trace_context=result.trace_context,
        )

    def _request_runtime_tool_confirmation(
        self,
        *,
        result: RuntimeStepResult,
        context: RuntimeExecutionContext,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session,
        event_session: Session,
        log_session: Session,
        log_writer: JsonlLogWriter,
    ) -> None:
        artifact = self._latest_stage_artifact(
            runtime_session,
            run_id=result.run_id,
            stage_run_id=result.stage_run_id,
            artifact_refs=result.artifact_refs,
        )
        process = dict(artifact.process) if artifact is not None else {}
        confirmation = self._latest_process_mapping(process, "tool_confirmation_trace")
        tool_name = _first_text(confirmation, ("tool_name",), default="runtime_tool")
        command_preview = _optional_text(confirmation.get("command_summary")) or _optional_text(
            confirmation.get("command_preview")
        )
        confirmation_ref = _first_text(
            confirmation,
            ("tool_confirmation_ref", "confirmation_object_ref", "call_id"),
            default=(
                f"stage-artifact://{artifact.artifact_id}#process/tool_confirmation_trace"
                if artifact is not None
                else f"runtime-wait://{result.stage_run_id}/tool-confirmation"
            ),
        )
        ToolConfirmationService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
            graph_session=graph_session,
            runtime_orchestration=self._runtime_orchestration(graph_session),
            audit_service=AuditService(log_session, audit_writer=log_writer),
            log_writer=log_writer,
            redaction_policy=self._redaction_policy,
            now=self._now,
        ).create_request(
            session_id=context.session_id,
            run_id=result.run_id,
            stage_run_id=result.stage_run_id,
            confirmation_object_ref=confirmation_ref,
            tool_name=tool_name,
            command_preview=command_preview,
            target_summary=_first_text(
                confirmation,
                ("target_resource", "target_summary"),
                default="Runtime tool action requires confirmation.",
            ),
            risk_level=_tool_risk_level(confirmation.get("risk_level")),
            risk_categories=_tool_risk_categories(confirmation.get("risk_categories")),
            reason=_first_text(
                confirmation,
                ("reason",),
                default="Runtime requested confirmation before continuing.",
            ),
            expected_side_effects=_string_list(
                confirmation.get("expected_side_effects"),
                default=("Runtime action may modify project state.",),
            ),
            alternative_path_summary=_optional_text(
                confirmation.get("alternative_path_summary")
            ),
            planned_deny_followup_action=_optional_text(
                confirmation.get("planned_deny_followup_action")
            ),
            planned_deny_followup_summary=_optional_text(
                confirmation.get("planned_deny_followup_summary")
            ),
            trace_context=result.trace_context,
        )

    def _request_runtime_approval(
        self,
        *,
        result: RuntimeStepResult,
        context: RuntimeExecutionContext,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session,
        event_session: Session,
        log_session: Session,
        log_writer: JsonlLogWriter,
    ) -> None:
        del log_session
        approval_type = (
            ApprovalType.CODE_REVIEW_APPROVAL
            if result.stage_type is StageType.CODE_REVIEW
            else ApprovalType.SOLUTION_DESIGN_APPROVAL
        )
        service = ApprovalService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
            graph_session=graph_session,
            runtime_orchestration=self._runtime_orchestration(graph_session),
            log_writer=log_writer,
            redaction_policy=self._redaction_policy,
            now=self._now,
        )
        kwargs = {
            "session_id": context.session_id,
            "run_id": result.run_id,
            "stage_run_id": result.stage_run_id,
            "payload_ref": f"runtime-wait://{result.stage_run_id}/approval",
            "approval_object_excerpt": (
                f"{result.stage_type.value} is waiting for approval."
            ),
            "risk_excerpt": "Runtime requested approval before continuing.",
            "approval_object_preview": {"stage_type": result.stage_type.value},
            "trace_context": result.trace_context,
        }
        if approval_type is ApprovalType.CODE_REVIEW_APPROVAL:
            service.create_code_review_approval(**kwargs)
        else:
            service.create_solution_design_approval(**kwargs)

    def _project_interrupt_result(
        self,
        *,
        result: RuntimeInterrupt,
        context: RuntimeExecutionContext,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session,
        event_session: Session,
    ) -> None:
        run = self._require_run(runtime_session, result.run_id)
        stage = runtime_session.get(StageRunModel, result.stage_run_id)
        if stage is None:
            raise RuntimeError("Runtime interrupt StageRun was not found.")
        if stage.run_id != run.run_id or stage.stage_type is not result.stage_type:
            raise RuntimeError("Runtime interrupt does not match StageRun.")
        session_model = control_session.get(SessionModel, run.session_id)
        if session_model is None:
            raise RuntimeError("Runtime interrupt session was not found.")
        thread = self._require_thread(graph_session, run)

        status = _stage_status_for_interrupt(result)
        occurred_at = self._now()
        stage.status = status
        stage.updated_at = occurred_at
        stage.summary = _stage_result_summary(stage, status)
        run.status = _run_status_for_stage_status(status)
        run.current_stage_run_id = stage.stage_run_id
        run.updated_at = occurred_at
        session_model.status = _session_status_for_stage_status(status)
        session_model.latest_stage_type = stage.stage_type
        session_model.updated_at = occurred_at
        thread.status = "interrupted"
        thread.current_interrupt_id = result.interrupt_ref.interrupt_id
        thread.current_node_key = stage.graph_node_key or thread.current_node_key
        thread.last_checkpoint_ref = (
            result.interrupt_ref.checkpoint_ref.payload_ref
            or thread.last_checkpoint_ref
        )
        thread.updated_at = occurred_at
        runtime_session.add_all([run, stage])
        control_session.add(session_model)
        graph_session.add(thread)

        stage_node = ExecutionNodeProjection(
            entry_id=_bounded_id("entry", stage.stage_run_id, status.value),
            run_id=run.run_id,
            occurred_at=occurred_at,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            status=stage.status,
            attempt_index=stage.attempt_index,
            started_at=stage.started_at,
            ended_at=stage.ended_at,
            summary=stage.summary or _stage_result_summary(stage, status),
            items=self._stage_progress_items(
                runtime_session,
                run=run,
                stage=stage,
                occurred_at=occurred_at,
                artifact_refs=[],
            ),
            metrics=self._stage_metrics(
                runtime_session,
                artifact_refs=[],
            ),
        )
        EventStore(event_session, now=self._now).append(
            DomainEventType.STAGE_UPDATED,
            payload={"stage_node": stage_node.model_dump(mode="json")},
            trace_context=result.trace_context,
            session_id=session_model.session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            occurred_at=occurred_at,
        )

    def _project_terminal_result(
        self,
        *,
        result: RuntimeTerminalResult,
        context: RuntimeExecutionContext,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session,
        event_session: Session,
    ) -> None:
        run = self._require_run(runtime_session, result.run_id)
        session_model = control_session.get(SessionModel, run.session_id)
        if session_model is None:
            raise RuntimeError("Runtime terminal result session was not found.")
        thread = self._require_thread(graph_session, run)
        occurred_at = self._now()
        if result.status is GraphThreadStatus.COMPLETED:
            run.status = RunStatus.COMPLETED
            session_model.status = SessionStatus.COMPLETED
            thread.status = "completed"
            event_type = DomainEventType.RUN_COMPLETED
            event_payload = {
                "session_id": context.session_id,
                "status": session_model.status.value,
                "current_run_id": context.run_id,
                "current_stage_type": None,
            }
        elif result.status is GraphThreadStatus.TERMINATED:
            run.status = RunStatus.TERMINATED
            session_model.status = SessionStatus.TERMINATED
            thread.status = "terminated"
            event_type = DomainEventType.RUN_TERMINATED
            event_payload = None
        else:
            return
        run.current_stage_run_id = None
        run.ended_at = occurred_at
        run.updated_at = occurred_at
        session_model.updated_at = occurred_at
        thread.current_interrupt_id = None
        thread.updated_at = occurred_at
        runtime_session.add(run)
        control_session.add(session_model)
        graph_session.add(thread)
        events = EventStore(event_session, now=self._now)
        if event_payload is not None:
            events.append(
                event_type,
                payload=event_payload,
                trace_context=result.trace_context,
                session_id=context.session_id,
                run_id=context.run_id,
                occurred_at=occurred_at,
            )
        else:
            TerminalStatusProjector(events=events, now=self._now).append_terminal_system_status(
                domain_event_type=event_type,
                run=run,
                title="Run terminated",
                reason="Run was terminated by runtime execution.",
                trace_context=result.trace_context,
                is_current_tail=session_model.current_run_id == run.run_id,
                occurred_at=occurred_at,
            )

    def _default_engine_factory(
        self,
        factory_input: RuntimeEngineFactoryInput,
    ) -> RuntimeEngine:
        context = factory_input.context
        graph_definition = self._graph_definition(
            factory_input.graph_session,
            factory_input.runtime_session,
            context=context,
        )
        runtime_limit_snapshot = self._runtime_limit_snapshot(
            factory_input.runtime_session,
            context.runtime_limit_snapshot_ref,
        )
        provider_call_policy_snapshot = self._provider_call_policy_snapshot(
            factory_input.runtime_session,
            context.provider_call_policy_snapshot_ref,
        )
        provider_reads = self._provider_snapshot_reads(
            factory_input.runtime_session,
            context.run_id,
        )
        binding_reads = self._model_binding_snapshot_reads(
            factory_input.runtime_session,
            context.run_id,
        )
        template_snapshot = self._template_snapshot(
            factory_input.control_session,
            factory_input.runtime_session,
            context=context,
        )
        artifact_store = ArtifactStore(
            runtime_session=factory_input.runtime_session,
            log_writer=factory_input.log_writer,
            now=factory_input.now,
        )
        prompt_renderer = PromptRenderer(PromptRegistry.load_builtin_assets())
        tool_registry = ToolRegistry()
        context_builder = self._context_builder(
            prompt_renderer=prompt_renderer,
            tool_registry=tool_registry,
            artifact_store=artifact_store,
            now=factory_input.now,
        )
        stage_artifacts = self._stage_artifacts_for_context(
            factory_input.runtime_session,
            run_id=context.run_id,
        )
        provider_registry = ProviderRegistry(
            provider_snapshots=provider_reads,
            model_binding_snapshots=binding_reads,
        )
        stage_runner = _RuntimeDispatchStageRunner(
            service=self,
            runtime_session=factory_input.runtime_session,
            event_session=factory_input.event_session,
            log_writer=factory_input.log_writer,
            now=factory_input.now,
            context_builder=context_builder,
            provider_registry=provider_registry,
            provider_reads=provider_reads,
            binding_reads=binding_reads,
            provider_call_policy_snapshot=provider_call_policy_snapshot,
            tool_registry=tool_registry,
            artifact_store=artifact_store,
            template_snapshot=template_snapshot,
            graph_definition=graph_definition,
            runtime_limit_snapshot=runtime_limit_snapshot,
            stage_artifacts=stage_artifacts,
            context_references=self._context_references_from_stage_artifacts(
                stage_artifacts
            ),
            change_sets=self._change_sets_from_stage_artifacts(stage_artifacts),
            clarifications=self._clarifications_for_context(
                factory_input.runtime_session,
                run_id=context.run_id,
            ),
            approval_decisions=self._approval_decisions_for_context(
                factory_input.runtime_session,
                run_id=context.run_id,
            ),
        )
        return LangGraphRuntimeEngine(
            graph_definition=graph_definition,
            stage_runner=stage_runner,
            checkpointer=self._default_checkpointer(),
            log_writer=factory_input.log_writer,
            now=factory_input.now,
        )

    def _default_checkpointer(self) -> Any:
        if self._langgraph_checkpointer is None:
            self._langgraph_checkpointer = SQLiteLangGraphCheckpointSaver(
                self._environment_settings.resolve_platform_runtime_root()
                / "langgraph_checkpoints.sqlite3"
            )
        return self._langgraph_checkpointer

    def _context_builder(
        self,
        *,
        prompt_renderer: PromptRenderer,
        tool_registry: ToolRegistry,
        artifact_store: ArtifactStore,
        now: Callable[[], datetime],
    ) -> Any:
        from backend.app.context.builder import ContextEnvelopeBuilder

        return ContextEnvelopeBuilder(
            prompt_renderer=prompt_renderer,
            tool_registry=tool_registry,
            artifact_store=artifact_store,
            now=now,
        )

    def _max_auto_run_next_steps(self, run_id: str) -> int:
        runtime_session = self._database_manager.session(DatabaseRole.RUNTIME)
        graph_session = self._database_manager.session(DatabaseRole.GRAPH)
        try:
            run = self._require_run(runtime_session, run_id)
            graph_definition = graph_session.get(
                GraphDefinitionModel,
                run.graph_definition_ref,
            )
            if graph_definition is None:
                return 1
            runtime_limit = runtime_session.get(
                RuntimeLimitSnapshotModel,
                run.runtime_limit_snapshot_ref,
            )
            auto_regression_retries = (
                runtime_limit.agent_limits.get("max_auto_regression_retries", 0)
                if runtime_limit is not None
                and isinstance(runtime_limit.agent_limits, dict)
                else 0
            )
            return max(
                1,
                len(tuple(graph_definition.stage_nodes))
                + int(auto_regression_retries) * 3
                + 1,
            )
        finally:
            runtime_session.close()
            graph_session.close()

    def _mark_auto_continue_limit_failed(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
        max_steps: int,
    ) -> None:
        control_session = self._database_manager.session(DatabaseRole.CONTROL)
        runtime_session = self._database_manager.session(DatabaseRole.RUNTIME)
        graph_session = self._database_manager.session(DatabaseRole.GRAPH)
        event_session = self._database_manager.session(DatabaseRole.EVENT)
        log_session = self._database_manager.session(DatabaseRole.LOG)
        log_writer = JsonlLogWriter(
            RuntimeDataSettings.from_environment_settings(self._environment_settings)
        )
        try:
            self._mark_execution_failed(
                run_id=run_id,
                trace_context=self._failure_trace(
                    trace_context=trace_context,
                    run_id=run_id,
                    runtime_session=runtime_session,
                ),
                reason=(
                    "Runtime execution exceeded automatic continuation limit "
                    f"({max_steps} steps)."
                ),
                error_type="RuntimeAutoContinuationLimit",
                control_session=control_session,
                runtime_session=runtime_session,
                graph_session=graph_session,
                event_session=event_session,
                log_session=log_session,
                log_writer=log_writer,
            )
        finally:
            control_session.close()
            runtime_session.close()
            graph_session.close()
            event_session.close()
            log_session.close()

    def _graph_definition(
        self,
        graph_session: Session,
        runtime_session: Session,
        *,
        context: RuntimeExecutionContext,
    ) -> GraphDefinition:
        model = graph_session.get(GraphDefinitionModel, context.graph_definition_ref)
        if model is None:
            raise RuntimeError("GraphDefinition was not found.")
        runtime_limit = runtime_session.get(
            RuntimeLimitSnapshotModel,
            context.runtime_limit_snapshot_ref,
        )
        if runtime_limit is None:
            raise RuntimeError("RuntimeLimitSnapshot was not found.")
        return GraphDefinition(
            graph_definition_id=model.graph_definition_id,
            run_id=model.run_id,
            template_snapshot_ref=model.template_snapshot_ref,
            runtime_limit_snapshot_ref=context.runtime_limit_snapshot_ref,
            runtime_limit_source_config_version=runtime_limit.source_config_version,
            graph_version=model.graph_version,
            stage_nodes=tuple(model.stage_nodes),
            stage_contracts=dict(model.stage_contracts),
            interrupt_policy=dict(model.interrupt_policy),
            retry_policy=dict(model.retry_policy),
            delivery_routing_policy=dict(model.delivery_routing_policy),
            source_node_group_map=_source_node_group_map(),
            schema_version=model.schema_version,
            created_at=model.created_at,
        )

    def _template_snapshot(
        self,
        control_session: Session,
        runtime_session: Session,
        *,
        context: RuntimeExecutionContext,
    ) -> TemplateSnapshot:
        persisted_snapshot = self._persisted_template_snapshot(
            runtime_session=runtime_session,
            context=context,
        )
        if persisted_snapshot is not None:
            return persisted_snapshot
        session_model = control_session.get(SessionModel, context.session_id)
        if session_model is None:
            raise RuntimeError("Session was not found for runtime template snapshot.")
        template = control_session.get(
            PipelineTemplateModel,
            session_model.selected_template_id,
        )
        if template is None:
            raise RuntimeError("Pipeline template was not found for runtime execution.")
        snapshot = TemplateSnapshotBuilder.build_for_run(
            template,
            run_id=context.run_id,
            created_at=context.trace_context.created_at,
        )
        if snapshot.snapshot_ref != context.template_snapshot_ref:
            raise RuntimeError("TemplateSnapshot ref does not match PipelineRun.")
        return snapshot

    @staticmethod
    def _persisted_template_snapshot(
        *,
        runtime_session: Session,
        context: RuntimeExecutionContext,
    ) -> TemplateSnapshot | None:
        artifact = (
            runtime_session.query(StageArtifactModel)
            .filter(
                StageArtifactModel.run_id == context.run_id,
                StageArtifactModel.artifact_type == "template_snapshot",
                StageArtifactModel.payload_ref == context.template_snapshot_ref,
            )
            .order_by(StageArtifactModel.created_at.asc())
            .first()
        )
        if artifact is None:
            return None
        payload = artifact.process.get("template_snapshot")
        if not isinstance(payload, dict):
            raise RuntimeError("Persisted template snapshot payload is invalid.")
        snapshot = TemplateSnapshot.model_validate(payload)
        if snapshot.snapshot_ref != context.template_snapshot_ref:
            raise RuntimeError("Persisted TemplateSnapshot ref does not match PipelineRun.")
        return snapshot

    @staticmethod
    def _runtime_limit_snapshot(
        runtime_session: Session,
        snapshot_id: str,
    ) -> RuntimeLimitSnapshotRead:
        model = runtime_session.get(RuntimeLimitSnapshotModel, snapshot_id)
        if model is None:
            raise RuntimeError("RuntimeLimitSnapshot was not found.")
        return RuntimeLimitSnapshotRead(
            snapshot_id=model.snapshot_id,
            run_id=model.run_id,
            agent_limits=model.agent_limits,
            context_limits=model.context_limits,
            source_config_version=model.source_config_version,
            hard_limits_version=model.hard_limits_version,
            schema_version=model.schema_version,
            created_at=model.created_at,
        )

    @staticmethod
    def _provider_call_policy_snapshot(
        runtime_session: Session,
        snapshot_id: str,
    ) -> ProviderCallPolicySnapshotRead:
        model = runtime_session.get(ProviderCallPolicySnapshotModel, snapshot_id)
        if model is None:
            raise RuntimeError("ProviderCallPolicySnapshot was not found.")
        return ProviderCallPolicySnapshotRead(
            snapshot_id=model.snapshot_id,
            run_id=model.run_id,
            provider_call_policy=model.provider_call_policy,
            source_config_version=model.source_config_version,
            schema_version=model.schema_version,
            created_at=model.created_at,
        )

    @staticmethod
    def _provider_snapshot_reads(
        runtime_session: Session,
        run_id: str,
    ) -> tuple[ProviderSnapshotRead, ...]:
        models = (
            runtime_session.query(ProviderSnapshotModel)
            .filter(ProviderSnapshotModel.run_id == run_id)
            .order_by(ProviderSnapshotModel.snapshot_id.asc())
            .all()
        )
        return tuple(
            ProviderSnapshotRead(
                snapshot_id=model.snapshot_id,
                run_id=model.run_id,
                provider_id=model.provider_id,
                display_name=model.display_name,
                provider_source=model.provider_source,
                protocol_type=model.protocol_type,
                base_url=model.base_url,
                api_key_ref=model.api_key_ref,
                model_id=model.model_id,
                capabilities=model.capabilities,
                source_config_version=model.source_config_version,
                schema_version=model.schema_version,
                created_at=model.created_at,
            )
            for model in models
        )

    @staticmethod
    def _model_binding_snapshot_reads(
        runtime_session: Session,
        run_id: str,
    ) -> tuple[ModelBindingSnapshotRead, ...]:
        models = (
            runtime_session.query(ModelBindingSnapshotModel)
            .filter(ModelBindingSnapshotModel.run_id == run_id)
            .order_by(ModelBindingSnapshotModel.snapshot_id.asc())
            .all()
        )
        return tuple(
            ModelBindingSnapshotRead(
                snapshot_id=model.snapshot_id,
                run_id=model.run_id,
                binding_id=model.binding_id,
                binding_type=model.binding_type,
                stage_type=model.stage_type,
                role_id=model.role_id,
                provider_snapshot_id=model.provider_snapshot_id,
                provider_id=model.provider_id,
                model_id=model.model_id,
                capabilities=model.capabilities,
                model_parameters=model.model_parameters,
                source_config_version=model.source_config_version,
                schema_version=model.schema_version,
                created_at=model.created_at,
            )
            for model in models
        )

    @staticmethod
    def _select_stage_binding(
        bindings: Sequence[ModelBindingSnapshotRead],
        *,
        stage_type: StageType,
    ) -> ModelBindingSnapshotRead:
        matches = [
            binding
            for binding in bindings
            if binding.binding_type == "agent_role" and binding.stage_type is stage_type
        ]
        if len(matches) != 1:
            raise RuntimeError("Exactly one stage model binding snapshot is required.")
        return matches[0]

    @staticmethod
    def _select_provider_read(
        providers: Sequence[ProviderSnapshotRead],
        *,
        provider_snapshot_id: str,
    ) -> ProviderSnapshotRead:
        for provider in providers:
            if provider.snapshot_id == provider_snapshot_id:
                return provider
        raise RuntimeError("Provider snapshot was not found for model binding.")

    @staticmethod
    def _provider_snapshot_domain(provider: ProviderSnapshotRead) -> ProviderSnapshot:
        return ProviderSnapshot(
            snapshot_id=provider.snapshot_id,
            run_id=provider.run_id,
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            provider_source=provider.provider_source,
            protocol_type=provider.protocol_type,
            base_url=provider.base_url,
            api_key_ref=provider.api_key_ref,
            model_id=provider.model_id,
            capabilities=provider.capabilities,
            source_config_version=provider.source_config_version,
            schema_version=provider.schema_version,
            created_at=provider.created_at,
        )

    @staticmethod
    def _task_objective(
        graph_definition: GraphDefinition,
        stage_type: StageType,
    ) -> str:
        contract = graph_definition.stage_contracts.get(stage_type.value) or {}
        value = contract.get("stage_responsibility")
        if isinstance(value, str) and value:
            return value
        return f"Execute the {stage_type.value} stage."

    def _runtime_orchestration(
        self,
        graph_session: Session,
    ) -> RuntimeOrchestrationService:
        return RuntimeOrchestrationService(
            runtime_port=GraphRuntimeCommandPort(graph_session, now=self._now),
            checkpoint_port=GraphCheckpointPort(graph_session, now=self._now),
            clock=self._now,
        )

    @staticmethod
    def _latest_stage_artifact(
        runtime_session: Session,
        *,
        run_id: str,
        stage_run_id: str,
        artifact_refs: Sequence[str],
    ) -> StageArtifactModel | None:
        for artifact_ref in reversed(tuple(artifact_refs)):
            artifact_id = _stage_artifact_id_from_ref(artifact_ref)
            artifact = runtime_session.get(StageArtifactModel, artifact_id)
            if (
                artifact is not None
                and artifact.run_id == run_id
                and artifact.stage_run_id == stage_run_id
            ):
                return artifact
        return (
            runtime_session.query(StageArtifactModel)
            .filter(
                StageArtifactModel.run_id == run_id,
                StageArtifactModel.stage_run_id == stage_run_id,
            )
            .order_by(
                StageArtifactModel.created_at.desc(),
                StageArtifactModel.artifact_id.desc(),
            )
            .first()
        )

    @staticmethod
    def _latest_process_mapping(
        process: dict[str, Any],
        key: str,
    ) -> dict[str, Any]:
        records = _mapping_records(process.get(key))
        if not records:
            return {}
        return dict(records[-1])

    @staticmethod
    def _stage_artifacts_for_context(
        runtime_session: Session,
        *,
        run_id: str,
    ) -> tuple[StageArtifactModel, ...]:
        return tuple(
            runtime_session.query(StageArtifactModel)
            .filter(StageArtifactModel.run_id == run_id)
            .order_by(
                StageArtifactModel.created_at.asc(),
                StageArtifactModel.artifact_id.asc(),
            )
            .all()
        )

    @staticmethod
    def _clarifications_for_context(
        runtime_session: Session,
        *,
        run_id: str,
    ) -> tuple[ClarificationRecordModel, ...]:
        return tuple(
            runtime_session.query(ClarificationRecordModel)
            .filter(ClarificationRecordModel.run_id == run_id)
            .order_by(
                ClarificationRecordModel.requested_at.asc(),
                ClarificationRecordModel.clarification_id.asc(),
            )
            .all()
        )

    @staticmethod
    def _approval_decisions_for_context(
        runtime_session: Session,
        *,
        run_id: str,
    ) -> tuple[ApprovalDecisionModel, ...]:
        return tuple(
            runtime_session.query(ApprovalDecisionModel)
            .filter(ApprovalDecisionModel.run_id == run_id)
            .order_by(
                ApprovalDecisionModel.decided_at.asc(),
                ApprovalDecisionModel.decision_id.asc(),
            )
            .all()
        )

    @staticmethod
    def _context_references_from_stage_artifacts(
        stage_artifacts: Sequence[StageArtifactModel],
    ) -> tuple[ContextReference, ...]:
        references: list[ContextReference] = []
        seen: set[str] = set()
        for artifact in stage_artifacts:
            process = artifact.process if isinstance(artifact.process, dict) else {}
            for raw in (
                *_mapping_records(process.get("context_reference")),
                *_mapping_records(process.get("context_references")),
            ):
                try:
                    reference = ContextReference.model_validate(raw)
                except (TypeError, ValueError):
                    continue
                if reference.reference_id in seen:
                    continue
                seen.add(reference.reference_id)
                references.append(reference)
            for change_set in RuntimeExecutionService._change_sets_from_process(
                process
            ):
                for reference in change_set.context_references:
                    if reference.reference_id in seen:
                        continue
                    seen.add(reference.reference_id)
                    references.append(reference)
        return tuple(references)

    @staticmethod
    def _change_sets_from_stage_artifacts(
        stage_artifacts: Sequence[StageArtifactModel],
    ) -> tuple[ChangeSet, ...]:
        change_sets: list[ChangeSet] = []
        seen: set[str] = set()
        for artifact in stage_artifacts:
            process = artifact.process if isinstance(artifact.process, dict) else {}
            for change_set in RuntimeExecutionService._change_sets_from_process(process):
                if change_set.change_set_id in seen:
                    continue
                seen.add(change_set.change_set_id)
                change_sets.append(change_set)
        return tuple(change_sets)

    @staticmethod
    def _change_sets_from_process(process: dict[str, Any]) -> tuple[ChangeSet, ...]:
        change_sets: list[ChangeSet] = []
        for raw in (
            *_mapping_records(process.get("change_set")),
            *_mapping_records(process.get("change_sets")),
        ):
            try:
                change_sets.append(ChangeSet.model_validate(raw))
            except (TypeError, ValueError):
                continue
        return tuple(change_sets)

    @staticmethod
    def _require_run(runtime_session: Session, run_id: str) -> PipelineRunModel:
        run = runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise RuntimeError("PipelineRun was not found.")
        return run

    @staticmethod
    def _require_current_stage(
        runtime_session: Session,
        run: PipelineRunModel,
    ) -> StageRunModel:
        if run.current_stage_run_id is None:
            raise RuntimeError("PipelineRun has no current StageRun.")
        stage = runtime_session.get(StageRunModel, run.current_stage_run_id)
        if stage is None:
            raise RuntimeError("Current StageRun was not found.")
        if stage.run_id != run.run_id:
            raise RuntimeError("Current StageRun does not belong to PipelineRun.")
        return stage

    @staticmethod
    def _require_thread(
        graph_session: Session,
        run: PipelineRunModel,
    ) -> GraphThreadModel:
        thread = graph_session.get(GraphThreadModel, run.graph_thread_ref)
        if thread is None:
            raise RuntimeError("GraphThread was not found.")
        if thread.run_id != run.run_id:
            raise RuntimeError("GraphThread does not belong to PipelineRun.")
        return thread

    @staticmethod
    def _validate_started_command(
        *,
        command: RuntimeDispatchCommand,
        run: PipelineRunModel,
        stage: StageRunModel,
        thread_model: GraphThreadModel,
    ) -> None:
        if command.session_id != run.session_id:
            raise RuntimeError("RuntimeDispatchCommand session_id does not match run.")
        if command.run_id != run.run_id:
            raise RuntimeError("RuntimeDispatchCommand run_id does not match run.")
        if command.stage_run_id != stage.stage_run_id:
            raise RuntimeError("RuntimeDispatchCommand stage_run_id does not match stage.")
        if command.stage_type is not stage.stage_type:
            raise RuntimeError("RuntimeDispatchCommand stage_type does not match stage.")
        if command.graph_thread_id != thread_model.graph_thread_id:
            raise RuntimeError("RuntimeDispatchCommand graph_thread_id does not match thread.")

    @staticmethod
    def _provider_snapshot_refs(runtime_session: Session, run_id: str) -> list[str]:
        return [
            snapshot.snapshot_id
            for snapshot in runtime_session.query(ProviderSnapshotModel)
            .filter(ProviderSnapshotModel.run_id == run_id)
            .order_by(ProviderSnapshotModel.snapshot_id.asc())
            .all()
        ]

    @staticmethod
    def _model_binding_snapshot_refs(runtime_session: Session, run_id: str) -> list[str]:
        return [
            snapshot.snapshot_id
            for snapshot in runtime_session.query(ModelBindingSnapshotModel)
            .filter(ModelBindingSnapshotModel.run_id == run_id)
            .order_by(ModelBindingSnapshotModel.snapshot_id.asc())
            .all()
        ]

    @staticmethod
    def _stage_metrics(
        runtime_session: Session,
        *,
        artifact_refs: Sequence[str],
    ) -> dict[str, Any]:
        if not artifact_refs:
            return {}
        metrics: dict[str, Any] = {}
        for artifact_id in artifact_refs:
            artifact = runtime_session.get(StageArtifactModel, artifact_id)
            if artifact is not None and isinstance(artifact.metrics, dict):
                metrics.update(artifact.metrics)
        return metrics

    @staticmethod
    def _stage_progress_items(
        runtime_session: Session,
        *,
        run: PipelineRunModel,
        stage: StageRunModel,
        occurred_at: datetime,
        artifact_refs: Sequence[str],
    ) -> list[StageItemProjection]:
        artifact = RuntimeExecutionService._latest_stage_artifact(
            runtime_session,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            artifact_refs=artifact_refs,
        )
        if artifact is None or not isinstance(artifact.process, dict):
            return []

        process = dict(artifact.process)
        items: list[StageItemProjection] = []
        for index, record in enumerate(_mapping_records(process.get("model_call_trace")), 1):
            usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
            items.append(
                StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "model",
                        str(index),
                    ),
                    type=common.StageItemType.MODEL_CALL,
                    occurred_at=occurred_at,
                    title="Model call",
                    summary=_model_call_summary(record),
                    content=_json_content(_public_record(record)),
                    artifact_refs=_stage_ref_list(
                        record.get("artifact_refs"),
                        fallback=[_first_existing_text(record, ("model_call_ref",))],
                    ),
                    metrics={key: value for key, value in usage.items() if value is not None},
                )
            )

        for index, record in enumerate(_mapping_records(process.get("decision_trace")), 1):
            items.append(
                StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "reasoning",
                        str(index),
                    ),
                    type=common.StageItemType.REASONING,
                    occurred_at=occurred_at,
                    title="Reasoning",
                    summary=_decision_summary(record),
                    content=None,
                    artifact_refs=_stage_ref_list(
                        record.get("artifact_refs"),
                        fallback=[_first_existing_text(record, ("trace_ref",))],
                    ),
                    metrics=_compact_metrics(record, ("status", "decision_type")),
                )
            )

        for index, record in enumerate(_mapping_records(process.get("tool_trace")), 1):
            items.append(
                StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "tool",
                        str(index),
                    ),
                    type=common.StageItemType.TOOL_CALL,
                    occurred_at=occurred_at,
                    title=_tool_title(record),
                    summary=_tool_summary(record),
                    content=_json_content(_public_record(record)),
                    artifact_refs=_stage_ref_list(record.get("artifact_refs")),
                    metrics=_compact_metrics(record, ("status", "call_id", "tool_name")),
                )
            )

        for index, record in enumerate(
            (
                *_mapping_records(process.get("change_set")),
                *_mapping_records(process.get("change_sets")),
            ),
            1,
        ):
            refs = _stage_ref_list(record.get("diff_refs"))
            items.append(
                StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "diff",
                        str(index),
                    ),
                    type=common.StageItemType.DIFF_PREVIEW,
                    occurred_at=occurred_at,
                    title="Diff preview",
                    summary=_change_set_summary(record),
                    content=_change_set_content(record),
                    artifact_refs=refs,
                    metrics=_compact_metrics(record, ("change_set_id",)),
                )
            )

        output_records = _mapping_records(process.get("output_snapshot"))
        if output_records:
            output = output_records[-1]
            items.append(
                StageItemProjection(
                    item_id=_bounded_id("item", stage.stage_run_id, "result"),
                    type=common.StageItemType.RESULT,
                    occurred_at=occurred_at,
                    title="Result",
                    summary=_result_summary(output, stage.stage_type),
                    content=_json_content(_public_record(output)),
                    artifact_refs=[
                        artifact.artifact_id,
                        *_stage_ref_list(process.get("output_refs")),
                    ],
                    metrics=dict(artifact.metrics) if isinstance(artifact.metrics, dict) else {},
                )
            )

        return items

    @staticmethod
    def _thread_ref(
        graph_session: Session,
        *,
        run: PipelineRunModel,
        stage: StageRunModel,
        thread_model: GraphThreadModel,
        interrupt: RuntimeInterrupt | None = None,
    ) -> GraphThreadRef:
        if interrupt is not None:
            return interrupt.interrupt_ref.thread
        return GraphThreadRef(
            thread_id=thread_model.graph_thread_id,
            run_id=run.run_id,
            status=_thread_status(thread_model.status, run.status),
            current_stage_run_id=stage.stage_run_id,
            current_stage_type=stage.stage_type,
            checkpoint_id=_checkpoint_id_for_thread_state_ref(
                graph_session,
                thread_model=thread_model,
            ),
        )

    @staticmethod
    def _cancel_current_interrupt(
        graph_session: Session,
        *,
        interrupt: RuntimeInterrupt | None,
        thread: GraphThreadModel,
        cancelled_at: datetime,
    ) -> None:
        interrupt_id = (
            interrupt.interrupt_ref.interrupt_id
            if interrupt is not None
            else thread.current_interrupt_id
        )
        if not interrupt_id:
            return
        graph_interrupt = graph_session.get(GraphInterruptModel, interrupt_id)
        if graph_interrupt is None:
            return
        if graph_interrupt.graph_thread_id != thread.graph_thread_id:
            return
        if graph_interrupt.status != "pending":
            return
        graph_interrupt.status = "cancelled"
        graph_interrupt.responded_at = cancelled_at
        graph_interrupt.updated_at = cancelled_at
        graph_session.add(graph_interrupt)

    def _execution_trace(
        self,
        *,
        trace_context: TraceContext,
        run: PipelineRunModel,
        stage: StageRunModel,
        graph_thread_id: str,
        span_id: str,
        created_at: datetime | None = None,
    ) -> TraceContext:
        return TraceContext.model_validate(
            {
                **trace_context.model_dump(),
                "trace_id": run.trace_id,
                "parent_span_id": trace_context.span_id,
                "span_id": span_id,
                "created_at": created_at or self._now(),
                "session_id": run.session_id,
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id,
                "graph_thread_id": graph_thread_id,
            }
        )

    def _failure_trace(
        self,
        *,
        trace_context: TraceContext,
        run_id: str,
        runtime_session: Session,
    ) -> TraceContext:
        run = runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            return trace_context
        stage = (
            runtime_session.get(StageRunModel, run.current_stage_run_id)
            if run.current_stage_run_id is not None
            else None
        )
        return TraceContext.model_validate(
            {
                **trace_context.model_dump(),
                "trace_id": run.trace_id,
                "parent_span_id": trace_context.span_id,
                "span_id": f"runtime-execution-failed-{run.run_id}",
                "created_at": self._now(),
                "session_id": run.session_id,
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id if stage is not None else None,
                "graph_thread_id": run.graph_thread_ref,
            }
        )

    def _record_failure_audit(
        self,
        *,
        log_session: Session,
        log_writer: JsonlLogWriter,
        run: PipelineRunModel,
        stage: StageRunModel,
        thread: GraphThreadModel,
        reason: str,
        error_type: str,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        try:
            AuditService(log_session, audit_writer=log_writer).record_failed_command(
                actor_type=AuditActorType.SYSTEM,
                actor_id="runtime-execution-service",
                action="runtime.execution.failed",
                target_type="run",
                target_id=run.run_id,
                reason=reason,
                metadata={
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": thread.graph_thread_id,
                    "error_type": error_type,
                    "result_status": "failed",
                },
                trace_context=trace_context,
                created_at=occurred_at,
            )
        except Exception:
            _LOGGER.exception("Runtime execution failure audit write failed.")

    def _record_failure_log(
        self,
        *,
        log_session: Session,
        log_writer: JsonlLogWriter,
        run: PipelineRunModel,
        stage: StageRunModel,
        thread: GraphThreadModel,
        reason: str,
        error_type: str,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        summary = {
            "action": "runtime_execution_failed",
            "run_id": run.run_id,
            "stage_run_id": stage.stage_run_id,
            "graph_thread_id": thread.graph_thread_id,
            "error_type": error_type,
            "result_status": "failed",
            "reason": reason,
        }
        encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"))
        record = LogRecordInput(
            source="services.runtime_execution",
            category=LogCategory.RUNTIME,
            level=LogLevel.ERROR,
            message="Runtime execution failed.",
            trace_context=trace_context,
            payload=LogPayloadSummary(
                payload_type="runtime_execution_failed",
                summary=summary,
                excerpt=reason,
                payload_size_bytes=len(encoded.encode("utf-8")),
                content_hash=f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}",
                redaction_status=self._redaction_policy.summarize_payload(
                    summary,
                    payload_type="runtime_execution_failed",
                ).redaction_status,
            ),
            created_at=occurred_at,
            error_code="runtime_execution_failed",
        )
        try:
            write_result = log_writer.write_run_log(record)
            LogIndexRepository(log_session, failure_writer=log_writer).append_run_log_index(
                record,
                write_result,
            )
        except Exception:
            _LOGGER.exception("Runtime execution failure log write failed.")

    @staticmethod
    def _result_is_failed(result: RuntimeEngineResult) -> bool:
        if isinstance(result, RuntimeStepResult):
            return result.status is StageStatus.FAILED
        if isinstance(result, RuntimeTerminalResult):
            return result.status is GraphThreadStatus.FAILED
        return False

    @staticmethod
    def _commit_sessions(**sessions: Session | None) -> None:
        for session in sessions.values():
            if session is not None:
                session.commit()

    @staticmethod
    def _rollback_sessions(**sessions: Session | None) -> None:
        for session in sessions.values():
            if session is not None:
                session.rollback()


class _RuntimeDispatchStageRunner:
    def __init__(
        self,
        *,
        service: RuntimeExecutionService,
        runtime_session: Session,
        event_session: Session,
        log_writer: JsonlLogWriter,
        now: Callable[[], datetime],
        context_builder: Any,
        provider_registry: ProviderRegistry,
        provider_reads: Sequence[ProviderSnapshotRead],
        binding_reads: Sequence[ModelBindingSnapshotRead],
        provider_call_policy_snapshot: ProviderCallPolicySnapshotRead,
        tool_registry: ToolRegistry,
        artifact_store: ArtifactStore,
        template_snapshot: TemplateSnapshot,
        graph_definition: GraphDefinition,
        runtime_limit_snapshot: RuntimeLimitSnapshotRead,
        stage_artifacts: Sequence[StageArtifactModel],
        context_references: Sequence[ContextReference],
        change_sets: Sequence[ChangeSet],
        clarifications: Sequence[ClarificationRecordModel],
        approval_decisions: Sequence[ApprovalDecisionModel],
    ) -> None:
        self._service = service
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._log_writer = log_writer
        self._now = now
        self._context_builder = context_builder
        self._provider_registry = provider_registry
        self._provider_reads = tuple(provider_reads)
        self._binding_reads = tuple(binding_reads)
        self._provider_call_policy_snapshot = provider_call_policy_snapshot
        self._tool_registry = tool_registry
        self._artifact_store = artifact_store
        self._template_snapshot = template_snapshot
        self._graph_definition = graph_definition
        self._runtime_limit_snapshot = runtime_limit_snapshot
        self._stage_artifacts = tuple(stage_artifacts)
        self._context_references = tuple(context_references)
        self._change_sets = tuple(change_sets)
        self._clarifications = tuple(clarifications)
        self._approval_decisions = tuple(approval_decisions)

    def run_stage(self, invocation: StageNodeInvocation) -> StageNodeResult:
        self._ensure_stage(invocation)
        stage_agent = self._stage_agent(invocation.stage_type)
        try:
            return StageNodeResult.model_validate(stage_agent.run_stage(invocation))
        except Exception:
            _LOGGER.exception(
                "Stage Agent Runtime failed during production dispatch.",
                extra={
                    "run_id": invocation.run_id,
                    "stage_run_id": invocation.stage_run_id,
                    "stage_type": invocation.stage_type.value,
                },
            )
            return StageNodeResult(
                run_id=invocation.run_id,
                stage_run_id=invocation.stage_run_id,
                stage_type=invocation.stage_type,
                status=StageStatus.FAILED,
                artifact_refs=[],
                domain_event_refs=[],
                log_summary_refs=[],
                audit_refs=[],
            )

    def _ensure_stage(self, invocation: StageNodeInvocation) -> StageRunModel:
        stage = self._runtime_session.get(StageRunModel, invocation.stage_run_id)
        if stage is not None:
            if (
                stage.run_id != invocation.run_id
                or stage.stage_type is not invocation.stage_type
            ):
                raise RuntimeError("Runtime invocation does not match persisted StageRun.")
            return stage

        stage = StageRunService(
            runtime_session=self._runtime_session,
            log_writer=self._log_writer,
            redaction_policy=self._service._redaction_policy,
            now=self._now,
        ).start_stage(
            run_id=invocation.run_id,
            stage_run_id=invocation.stage_run_id,
            stage_type=invocation.stage_type,
            attempt_index=1,
            graph_node_key=invocation.graph_node_key,
            stage_contract_ref=invocation.stage_contract_ref,
            input_ref=None,
            summary=f"{invocation.stage_type.value} started by runtime execution.",
            trace_context=invocation.trace_context,
        )
        stage_node = ExecutionNodeProjection(
            entry_id=_bounded_id("entry", stage.stage_run_id, "started"),
            run_id=stage.run_id,
            occurred_at=stage.started_at,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            status=stage.status,
            attempt_index=stage.attempt_index,
            started_at=stage.started_at,
            ended_at=stage.ended_at,
            summary=stage.summary or f"{stage.stage_type.value} started.",
            items=[],
            metrics={},
        )
        EventStore(self._event_session, now=self._now).append(
            DomainEventType.STAGE_STARTED,
            payload={"stage_node": stage_node.model_dump(mode="json")},
            trace_context=invocation.trace_context,
            session_id=invocation.runtime_context.session_id,
            run_id=stage.run_id,
            stage_run_id=stage.stage_run_id,
            occurred_at=stage.started_at,
        )
        return stage

    def _stage_agent(self, stage_type: StageType) -> StageAgentRuntime:
        binding = self._service._select_stage_binding(
            self._binding_reads,
            stage_type=stage_type,
        )
        provider_read = self._service._select_provider_read(
            self._provider_reads,
            provider_snapshot_id=binding.provider_snapshot_id,
        )
        provider_config = self._provider_registry.resolve_from_model_binding_snapshot(
            binding
        )
        return StageAgentRuntime(
            context_builder=self._context_builder,
            provider_adapter=LangChainProviderAdapter(
                provider_config=provider_config,
                provider_call_policy_snapshot=self._provider_call_policy_snapshot,
            ),
            decision_parser=AgentDecisionParser(),
            tool_registry=self._tool_registry,
            artifact_store=self._artifact_store,
            template_snapshot=self._template_snapshot,
            graph_definition=self._graph_definition,
            runtime_limit_snapshot=self._runtime_limit_snapshot,
            provider_snapshot=self._service._provider_snapshot_domain(provider_read),
            model_binding_snapshot=binding,
            task_objective=self._service._task_objective(
                self._graph_definition,
                stage_type,
            ),
            specified_action="Produce the structured stage artifact for the current stage.",
            response_schema=agent_decision_response_schema(),
            output_schema_ref=f"schema://stage-agent/{stage_type.value}",
            requested_max_output_tokens=provider_config.max_output_tokens,
            stage_artifacts=self._stage_artifacts,
            context_references=self._context_references,
            change_sets=self._change_sets,
            clarifications=self._clarifications,
            approval_decisions=self._approval_decisions,
            progress_callback=self._publish_stage_progress,
            now=self._now,
        )

    def _publish_stage_progress(
        self,
        request: Any,
        process_key: str,
        process_ref: str,
    ) -> None:
        del process_key, process_ref
        stage = self._runtime_session.get(
            StageRunModel,
            request.invocation.stage_run_id,
        )
        run = self._runtime_session.get(PipelineRunModel, request.invocation.run_id)
        if stage is None or run is None:
            return
        occurred_at = self._now()
        stage_node = ExecutionNodeProjection(
            entry_id=_bounded_id(
                "entry",
                stage.stage_run_id,
                "progress",
                str(int(occurred_at.timestamp() * 1_000_000)),
            ),
            run_id=run.run_id,
            occurred_at=occurred_at,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            status=stage.status,
            attempt_index=stage.attempt_index,
            started_at=stage.started_at,
            ended_at=stage.ended_at,
            summary=stage.summary or f"{stage.stage_type.value} in progress.",
            items=self._service._stage_progress_items(
                self._runtime_session,
                run=run,
                stage=stage,
                occurred_at=occurred_at,
                artifact_refs=[request.stage_artifact_id],
            ),
            metrics=self._service._stage_metrics(
                self._runtime_session,
                artifact_refs=[request.stage_artifact_id],
            ),
        )
        EventStore(self._event_session, now=self._now).append(
            DomainEventType.STAGE_UPDATED,
            payload={"stage_node": stage_node.model_dump(mode="json")},
            trace_context=request.invocation.trace_context,
            session_id=request.invocation.runtime_context.session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            occurred_at=occurred_at,
        )
        self._event_session.commit()


def runtime_dispatcher_from_app_state(request: Request) -> RuntimeExecutionDispatcher:
    dispatcher = getattr(request.app.state, "runtime_execution_dispatcher", None)
    if dispatcher is None:
        raise RuntimeError("runtime_execution_dispatcher is not configured")
    return dispatcher


def _thread_status(raw_status: str, run_status: RunStatus) -> GraphThreadStatus:
    if raw_status == "interrupted":
        return GraphThreadStatus(run_status.value)
    if raw_status == "pending":
        return GraphThreadStatus.RUNNING
    try:
        return GraphThreadStatus(raw_status)
    except ValueError:
        return GraphThreadStatus(run_status.value)


def _run_status_for_stage_status(status: StageStatus) -> RunStatus:
    if status is StageStatus.WAITING_CLARIFICATION:
        return RunStatus.WAITING_CLARIFICATION
    if status is StageStatus.WAITING_APPROVAL:
        return RunStatus.WAITING_APPROVAL
    if status is StageStatus.WAITING_TOOL_CONFIRMATION:
        return RunStatus.WAITING_TOOL_CONFIRMATION
    return RunStatus.RUNNING


def _session_status_for_stage_status(status: StageStatus) -> SessionStatus:
    if status is StageStatus.WAITING_CLARIFICATION:
        return SessionStatus.WAITING_CLARIFICATION
    if status is StageStatus.WAITING_APPROVAL:
        return SessionStatus.WAITING_APPROVAL
    if status is StageStatus.WAITING_TOOL_CONFIRMATION:
        return SessionStatus.WAITING_TOOL_CONFIRMATION
    return SessionStatus.RUNNING


def _stage_status_for_interrupt(result: RuntimeInterrupt) -> StageStatus:
    if result.interrupt_ref.interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return StageStatus.WAITING_CLARIFICATION
    if result.interrupt_ref.interrupt_type is GraphInterruptType.APPROVAL:
        return StageStatus.WAITING_APPROVAL
    if result.interrupt_ref.interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
        return StageStatus.WAITING_TOOL_CONFIRMATION
    raise RuntimeError(
        f"Unsupported runtime interrupt type: {result.interrupt_ref.interrupt_type!r}"
    )


def _stage_result_summary(stage: StageRunModel, status: StageStatus) -> str:
    if status is StageStatus.COMPLETED:
        return f"{stage.stage_type.value} completed."
    if status is StageStatus.WAITING_CLARIFICATION:
        return f"{stage.stage_type.value} is waiting for clarification."
    if status is StageStatus.WAITING_APPROVAL:
        return f"{stage.stage_type.value} is waiting for approval."
    if status is StageStatus.WAITING_TOOL_CONFIRMATION:
        return f"{stage.stage_type.value} is waiting for tool confirmation."
    if status is StageStatus.RUNNING:
        return stage.summary or f"{stage.stage_type.value} is running."
    return stage.summary or f"{stage.stage_type.value} updated to {status.value}."


def _checkpoint_id_for_thread_state_ref(
    graph_session: Session,
    *,
    thread_model: GraphThreadModel,
) -> str | None:
    if thread_model.last_checkpoint_ref is None:
        return None
    checkpoint = (
        graph_session.query(GraphCheckpointModel)
        .filter(
            GraphCheckpointModel.graph_thread_id == thread_model.graph_thread_id,
            GraphCheckpointModel.state_ref == thread_model.last_checkpoint_ref,
        )
        .order_by(GraphCheckpointModel.sequence_index.desc())
        .first()
    )
    if checkpoint is None:
        return None
    return checkpoint.checkpoint_id


def _safe_failure_reason(exc: Exception) -> str:
    message = str(exc) or type(exc).__name__
    message = re.sub(
        r"(?i)(secret|token|api[_-]?key|password)[^\s,;]*",
        "[redacted]",
        message,
    )
    message = re.sub(r"(?i)(bearer)\s+[a-z0-9._~+/=-]+", r"\1 [redacted]", message)
    message = " ".join(message.split())
    if len(message) > 300:
        message = message[:297] + "..."
    return message or "Runtime execution failed."


def _stage_artifact_id_from_ref(value: str) -> str:
    if not value.startswith("stage-artifact://"):
        return value
    without_scheme = value.removeprefix("stage-artifact://")
    without_fragment = without_scheme.split("#", 1)[0]
    return without_fragment.split("/", 1)[0]


def _mapping_records(value: object) -> tuple[dict[str, Any], ...]:
    if isinstance(value, dict):
        return (dict(value),)
    if isinstance(value, list | tuple):
        return tuple(dict(item) for item in value if isinstance(item, dict))
    return ()


def _model_call_summary(record: dict[str, Any]) -> str:
    provider = _optional_text(record.get("provider_id")) or "provider"
    model = _optional_text(record.get("model_id")) or "model"
    call_type = _optional_text(record.get("model_call_type")) or "stage call"
    usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    total_tokens = usage.get("total_tokens")
    suffix = f", {total_tokens} tokens" if total_tokens is not None else ""
    return f"{provider} {model} handled {call_type}{suffix}."


def _decision_summary(record: dict[str, Any]) -> str:
    message = _optional_text(record.get("safe_message"))
    decision_type = _optional_text(record.get("decision_type")) or _optional_text(
        record.get("decision")
    )
    status = _optional_text(record.get("status"))
    parts = [part for part in (message, decision_type, status) if part]
    if not parts:
        return "Model decision summary is available."
    return " | ".join(parts)


def _tool_title(record: dict[str, Any]) -> str:
    tool_name = _optional_text(record.get("tool_name")) or "runtime tool"
    return f"Tool call: {tool_name}"


def _tool_summary(record: dict[str, Any]) -> str:
    status = _optional_text(record.get("status")) or "completed"
    safe_details = record.get("safe_details")
    if isinstance(safe_details, dict):
        detail = _optional_text(safe_details.get("summary")) or _optional_text(
            safe_details.get("message")
        )
        if detail:
            return f"{status}: {detail}"
    return f"Tool call {status}."


def _change_set_summary(record: dict[str, Any]) -> str:
    summary = _optional_text(record.get("summary"))
    if summary:
        return summary
    files = _stage_ref_list(record.get("changed_files"))
    if files:
        return f"{len(files)} file change(s) projected."
    return "Workspace diff preview is available."


def _change_set_content(record: dict[str, Any]) -> str:
    lines: list[str] = []
    change_set_id = _optional_text(record.get("change_set_id"))
    if change_set_id:
        lines.append(f"Change set: {change_set_id}")
    files = _stage_ref_list(record.get("changed_files"))
    if files:
        lines.append("Changed files:")
        lines.extend(f"- {file_path}" for file_path in files)
    diff_refs = _stage_ref_list(record.get("diff_refs"))
    if diff_refs:
        lines.append("Diff refs:")
        lines.extend(f"- {diff_ref}" for diff_ref in diff_refs)
    return "\n".join(lines) or _json_content(_public_record(record)) or "Diff preview."


def _result_summary(record: dict[str, Any], stage_type: StageType) -> str:
    for key in ("summary", "risk_summary", "failure_summary", "artifact_type"):
        value = _optional_text(record.get(key))
        if value:
            return value
    return f"{stage_type.value} produced a stage result."


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    blocked_fragments = ("raw", "prompt", "response", "payload")
    public: dict[str, Any] = {}
    for key, value in record.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in blocked_fragments):
            continue
        public[key] = value
    return public


def _json_content(value: dict[str, Any]) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _compact_metrics(
    record: dict[str, Any],
    keys: Sequence[str],
) -> dict[str, Any]:
    return {key: record[key] for key in keys if record.get(key) is not None}


def _stage_ref_list(
    value: object,
    *,
    fallback: Sequence[str | None] = (),
) -> list[str]:
    if isinstance(value, str):
        values: list[object] = [value]
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        values = list(fallback)
    return [item for item in values if isinstance(item, str) and item.strip()]


def _first_existing_text(
    mapping: dict[str, Any],
    keys: Sequence[str],
) -> str | None:
    for key in keys:
        value = _optional_text(mapping.get(key))
        if value is not None:
            return value
    return None


def _first_text(
    mapping: dict[str, Any],
    keys: Sequence[str],
    *,
    default: str,
) -> str:
    for key in keys:
        value = _optional_text(mapping.get(key))
        if value is not None:
            return value
    return default


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _string_list(
    value: object,
    *,
    default: Sequence[str],
) -> list[str]:
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else list(default)
    if isinstance(value, list | tuple):
        items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if items:
            return items
    return list(default)


def _tool_risk_level(value: object) -> ToolRiskLevel:
    if isinstance(value, ToolRiskLevel):
        return value
    if isinstance(value, str):
        try:
            return ToolRiskLevel(value.strip())
        except ValueError:
            return ToolRiskLevel.HIGH_RISK
    return ToolRiskLevel.HIGH_RISK


def _tool_risk_categories(value: object) -> list[ToolRiskCategory]:
    raw_values: tuple[object, ...]
    if isinstance(value, str):
        raw_values = (value,)
    elif isinstance(value, list | tuple):
        raw_values = tuple(value)
    else:
        raw_values = ()

    categories: list[ToolRiskCategory] = []
    for raw_value in raw_values:
        if isinstance(raw_value, ToolRiskCategory):
            category = raw_value
        elif isinstance(raw_value, str):
            try:
                category = ToolRiskCategory(raw_value.strip())
            except ValueError:
                continue
        else:
            continue
        if category not in categories:
            categories.append(category)
    return categories or [ToolRiskCategory.UNKNOWN_COMMAND]


def _bounded_id(*parts: str) -> str:
    value = "-".join(part for part in parts if part)
    if len(value) <= 80:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return "-".join(parts[:1] + (digest,))


def _source_node_group_map() -> dict[str, str]:
    return {
        "requirement_analysis": "requirement_analysis",
        "solution_design_authoring": "solution_design",
        "solution_design.authoring": "solution_design",
        "solution_validation": "solution_design",
        "solution_design.approval_gate": "solution_design",
        "code_generation": "code_generation",
        "test_generation_execution": "test_generation_execution",
        "code_review": "code_review",
        "code_review.approval_gate": "code_review",
        "delivery_integration": "delivery_integration",
        "delivery_complete": "delivery_integration",
    }


__all__ = [
    "RuntimeDispatchCommand",
    "RuntimeEngineFactoryInput",
    "RuntimeExecutionDispatcher",
    "RuntimeExecutionService",
    "runtime_dispatcher_from_app_state",
]
