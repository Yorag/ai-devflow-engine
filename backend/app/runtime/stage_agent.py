from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from backend.app.context.builder import ContextBuildRequest, ContextEnvelopeBuilder
from backend.app.domain.enums import StageStatus, StageType, ToolRiskLevel
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.template_snapshot import TemplateSnapshot
from backend.app.providers.langchain_adapter import (
    LangChainProviderAdapter,
    ModelCallResult,
)
from backend.app.runtime.agent_decision import (
    AgentDecision,
    AgentDecisionErrorCode,
    AgentDecisionParser,
    AgentDecisionParserError,
    AgentDecisionType,
)
from backend.app.runtime.stage_runner_port import StageNodeInvocation, StageNodeResult
from backend.app.schemas.prompts import ModelCallType
from backend.app.schemas.runtime_settings import (
    ModelBindingSnapshotRead,
    RuntimeLimitSnapshotRead,
)
from backend.app.services.artifacts import ArtifactStore, ArtifactStoreError
from backend.app.tools.execution_gate import ToolExecutionContext, ToolExecutionRequest
from backend.app.tools.protocol import (
    ToolReconciliationStatus,
    ToolResult,
    ToolResultStatus,
)
from backend.app.tools.registry import ToolRegistry


JsonObject = dict[str, Any]
StageProgressCallback = Callable[["StageExecutionRequest", str, str], None]


@dataclass(frozen=True, slots=True)
class StageExecutionRequest:
    invocation: StageNodeInvocation
    stage_artifact_id: str
    template_snapshot: TemplateSnapshot
    graph_definition: GraphDefinition
    runtime_limit_snapshot: RuntimeLimitSnapshotRead
    provider_snapshot: ProviderSnapshot
    model_binding_snapshot: ModelBindingSnapshotRead
    task_objective: str
    specified_action: str
    response_schema: dict[str, object]
    output_schema_ref: str
    tool_schema_version: str = "tool-schema-v1"
    template_version: str = "template-version-v1"
    requested_max_output_tokens: int | None = None
    model_call_type: ModelCallType = ModelCallType.STAGE_EXECUTION
    parse_error: str | None = None
    stage_artifacts: tuple[Any, ...] = ()
    context_references: tuple[Any, ...] = ()
    change_sets: tuple[Any, ...] = ()
    clarifications: tuple[Any, ...] = ()
    approval_decisions: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class StageRecoveryCursor:
    cursor_id: str
    run_id: str
    stage_run_id: str
    stage_type: StageType
    iteration_index: int
    last_decision_trace_ref: str | None = None
    last_model_call_ref: str | None = None
    last_tool_call_id: str | None = None
    last_tool_confirmation_ref: str | None = None
    completed_tool_call_ids: tuple[str, ...] = ()
    created_at: datetime | None = None

    def to_record(self) -> dict[str, object]:
        created_at = self.created_at or datetime.now(UTC)
        return {
            "cursor_id": self.cursor_id,
            "run_id": self.run_id,
            "stage_run_id": self.stage_run_id,
            "stage_type": self.stage_type.value,
            "iteration_index": self.iteration_index,
            "last_decision_trace_ref": self.last_decision_trace_ref,
            "last_model_call_ref": self.last_model_call_ref,
            "last_tool_call_id": self.last_tool_call_id,
            "last_tool_confirmation_ref": self.last_tool_confirmation_ref,
            "completed_tool_call_ids": list(self.completed_tool_call_ids),
            "created_at": created_at.isoformat(),
        }


class StageAgentRuntime:
    def __init__(
        self,
        *,
        context_builder: ContextEnvelopeBuilder,
        provider_adapter: LangChainProviderAdapter,
        decision_parser: AgentDecisionParser,
        tool_registry: ToolRegistry,
        artifact_store: ArtifactStore,
        template_snapshot: TemplateSnapshot,
        graph_definition: GraphDefinition,
        runtime_limit_snapshot: RuntimeLimitSnapshotRead,
        provider_snapshot: ProviderSnapshot,
        model_binding_snapshot: ModelBindingSnapshotRead,
        task_objective: str,
        specified_action: str,
        response_schema: Mapping[str, object],
        output_schema_ref: str,
        stage_artifact_id: str | None = None,
        tool_schema_version: str = "tool-schema-v1",
        template_version: str = "template-version-v1",
        requested_max_output_tokens: int | None = None,
        stage_artifacts: Sequence[Any] = (),
        context_references: Sequence[Any] = (),
        change_sets: Sequence[Any] = (),
        clarifications: Sequence[Any] = (),
        approval_decisions: Sequence[Any] = (),
        runtime_tool_timeout_seconds: float | None = None,
        platform_tool_timeout_hard_limit_seconds: float | None = None,
        workspace_boundary: object | None = None,
        audit_recorder: object | None = None,
        run_log_recorder: object | None = None,
        risk_policy: object | None = None,
        confirmation_port: object | None = None,
        progress_callback: StageProgressCallback | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._context_builder = context_builder
        self._provider_adapter = provider_adapter
        self._decision_parser = decision_parser
        self._tool_registry = tool_registry
        self._artifact_store = artifact_store
        self._stage_artifact_id = stage_artifact_id
        self._template_snapshot = template_snapshot
        self._graph_definition = graph_definition
        self._runtime_limit_snapshot = runtime_limit_snapshot
        self._provider_snapshot = provider_snapshot
        self._model_binding_snapshot = model_binding_snapshot
        self._task_objective = task_objective
        self._specified_action = specified_action
        self._response_schema = dict(response_schema)
        self._output_schema_ref = output_schema_ref
        self._tool_schema_version = tool_schema_version
        self._template_version = template_version
        self._requested_max_output_tokens = requested_max_output_tokens
        self._stage_artifacts = tuple(stage_artifacts)
        self._context_references = tuple(context_references)
        self._change_sets = tuple(change_sets)
        self._clarifications = tuple(clarifications)
        self._approval_decisions = tuple(approval_decisions)
        self._runtime_tool_timeout_seconds = runtime_tool_timeout_seconds
        self._platform_tool_timeout_hard_limit_seconds = (
            platform_tool_timeout_hard_limit_seconds
        )
        self._workspace_boundary = workspace_boundary
        self._audit_recorder = audit_recorder
        self._run_log_recorder = run_log_recorder
        self._risk_policy = risk_policy
        self._confirmation_port = confirmation_port
        self._progress_callback = progress_callback
        self._now = now or (lambda: datetime.now(UTC))
        self._process_records: dict[str, object] = {}
        self._process_refs: list[str] = []

    def run_stage(self, invocation: StageNodeInvocation) -> StageNodeResult:
        self._process_records = {}
        self._process_refs = []
        request = self._request_from_invocation(invocation)
        self._ensure_stage_input(request)
        self._append_process_record(
            request,
            "stage_agent_started",
            {
                "run_id": request.invocation.run_id,
                "stage_run_id": request.invocation.stage_run_id,
                "stage_type": request.invocation.stage_type.value,
                "stage_contract_ref": request.invocation.stage_contract_ref,
                "graph_node_key": request.invocation.graph_node_key,
                "started_at": self._now().isoformat(),
            },
        )
        return self._run_loop(request)

    def run_iteration(
        self,
        request: StageExecutionRequest,
        iteration_index: int,
        tool_results: tuple[ToolResult, ...],
    ) -> tuple[StageNodeResult | None, ToolResult | None, StageExecutionRequest]:
        build_result = self._context_builder.build_for_stage_call(
            self._context_request(request)
        )
        capability_failure = self._capability_failure_reason(
            request,
            available_tools=tuple(build_result.envelope.available_tools),
        )
        if capability_failure is not None:
            return (
                self._failed_result(
                    request,
                    reason=capability_failure,
                    iteration_index=iteration_index,
                ),
                None,
                request,
            )

        iteration_trace = request.invocation.trace_context.child_span(
            span_id=f"stage-agent-iteration-{iteration_index}",
            created_at=self._now(),
            run_id=request.invocation.run_id,
            stage_run_id=request.invocation.stage_run_id,
        )
        model_result = self._provider_adapter.invoke_with_retry(
            messages=self._provider_messages(build_result.rendered_messages),
            response_schema=dict(build_result.envelope.response_schema),
            model_call_type=request.model_call_type,
            tool_descriptions=tuple(build_result.envelope.available_tools),
            trace_context=iteration_trace,
            requested_max_output_tokens=request.requested_max_output_tokens,
        )
        model_call_ref = self._append_model_call_traces(request, model_result)
        stage_contract = self._stage_contract(request)
        try:
            decision = self._decision_parser.parse_model_result(
                model_result,
                context_envelope=build_result.envelope,
                stage_contract=stage_contract,
            )
        except AgentDecisionParserError as exc:
            self._append_process_record(
                request,
                "decision_trace",
                exc.error.model_dump(mode="json"),
            )
            repair_result = self._repair_from_parser_error(
                request,
                exc,
                iteration_index=iteration_index,
                last_model_call_ref=model_call_ref,
            )
            if repair_result is not None:
                return repair_result
            return (
                self._failed_result(
                    request,
                    reason=exc.error.error_code.value,
                    iteration_index=iteration_index,
                    last_model_call_ref=model_call_ref,
                    last_decision_trace_ref=exc.error.decision_trace.trace_ref,
                ),
                None,
                request,
            )

        self._append_process_record(
            request,
            "decision_trace",
            decision.decision_trace.model_dump(mode="json"),
        )

        cursor_kwargs = {
            "last_decision_trace_ref": decision.decision_trace.trace_ref,
            "last_model_call_ref": model_call_ref,
        }
        if decision.decision_type is AgentDecisionType.REQUEST_TOOL_CALL:
            limits = request.runtime_limit_snapshot.agent_limits
            if len(tool_results) >= limits.max_tool_calls_per_stage:
                return (
                    self._failed_result(
                        request,
                        reason="max_tool_calls_exceeded",
                        iteration_index=iteration_index,
                        **cursor_kwargs,
                    ),
                    None,
                    request,
                )
            tool_result = self.execute_tool_decision(request, decision, iteration_index)
            result = self._result_from_tool_result(
                request,
                decision,
                tool_result,
                iteration_index,
                completed_tool_call_ids=tuple(
                    item.call_id
                    for item in tool_results
                    if item.status is ToolResultStatus.SUCCEEDED
                ),
                **cursor_kwargs,
            )
            return result, tool_result, request

        if decision.decision_type is AgentDecisionType.SUBMIT_STAGE_ARTIFACT:
            recovery_ref = self.persist_recovery_checkpoint(
                request,
                self._recovery_cursor(
                    request,
                    iteration_index=iteration_index,
                    **cursor_kwargs,
                ),
            )
            return (
                self.submit_stage_artifact(
                    request,
                    decision,
                    iteration_index,
                    recovery_ref=recovery_ref,
                ),
                None,
                request,
            )

        if decision.decision_type is AgentDecisionType.REPAIR_STRUCTURED_OUTPUT:
            repair = decision.structured_repair
            if repair is None:
                return (
                    self._failed_result(
                        request,
                        reason="structured_output_repair_payload_missing",
                        iteration_index=iteration_index,
                        **cursor_kwargs,
                    ),
                    None,
                    request,
                )
            repair_count = self._process_record_count("structured_output_repair_trace")
            if (
                repair_count
                >= request.runtime_limit_snapshot.agent_limits.max_structured_output_repair_attempts
            ):
                return (
                    self._failed_result(
                        request,
                        reason="max_structured_output_repair_attempts_exceeded",
                        iteration_index=iteration_index,
                        **cursor_kwargs,
                    ),
                    None,
                    request,
                )
            self._append_process_record(
                request,
                "structured_output_repair_trace",
                {
                    "parse_error_summary": _bounded_string(repair.parse_error),
                    "invalid_output_ref": repair.invalid_output_ref,
                    "repair_instruction_summary": _bounded_string(
                        repair.repair_instruction
                    ),
                    "decision_trace_ref": decision.decision_trace.trace_ref,
                    "iteration_index": iteration_index,
                },
            )
            self.persist_recovery_checkpoint(
                request,
                self._recovery_cursor(
                    request,
                    iteration_index=iteration_index,
                    **cursor_kwargs,
                ),
            )
            return (
                None,
                None,
                replace(
                    request,
                    model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR,
                    parse_error=repair.parse_error,
                ),
            )

        if decision.decision_type is AgentDecisionType.RETRY_WITH_REVISED_PLAN:
            self.persist_recovery_checkpoint(
                request,
                self._recovery_cursor(
                    request,
                    iteration_index=iteration_index,
                    **cursor_kwargs,
                ),
            )
            return (None, None, request)

        if (
            decision.decision_type is AgentDecisionType.REQUEST_TOOL_CONFIRMATION
            and self._should_skip_structured_tool_confirmation(request, decision)
        ):
            limits = request.runtime_limit_snapshot.agent_limits
            if len(tool_results) >= limits.max_tool_calls_per_stage:
                return (
                    self._failed_result(
                        request,
                        reason="max_tool_calls_exceeded",
                        iteration_index=iteration_index,
                        **cursor_kwargs,
                    ),
                    None,
                    request,
                )
            tool_result = self.execute_tool_confirmation_decision(
                request,
                decision,
                iteration_index,
            )
            result = self._result_from_tool_result(
                request,
                decision,
                tool_result,
                iteration_index,
                completed_tool_call_ids=tuple(
                    item.call_id
                    for item in tool_results
                    if item.status is ToolResultStatus.SUCCEEDED
                ),
                **cursor_kwargs,
            )
            return result, tool_result, request

        self.persist_recovery_checkpoint(
            request,
            self._recovery_cursor(
                request,
                iteration_index=iteration_index,
                **cursor_kwargs,
            ),
        )
        return (
            self._result_from_control_decision(
                request,
                decision,
                iteration_index,
                **cursor_kwargs,
            ),
            None,
            request,
        )

    def execute_tool_decision(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
        iteration_index: int,
    ) -> ToolResult:
        del iteration_index
        if decision.tool_call is None:
            raise ValueError("Tool decision payload is required")
        stage_contract = self._stage_contract(request)
        tool_request = ToolExecutionRequest(
            tool_name=decision.tool_call.tool_name,
            call_id=decision.tool_call.call_id,
            input_payload=dict(decision.tool_call.input_payload),
            trace_context=request.invocation.trace_context,
            coordination_key=(
                f"{request.invocation.stage_run_id}:{decision.tool_call.call_id}"
            ),
        )
        return self._execute_tool_request(
            request,
            tool_request,
            stage_contract=stage_contract,
        )

    def execute_tool_confirmation_decision(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
        iteration_index: int,
    ) -> ToolResult:
        del iteration_index
        if decision.tool_confirmation is None:
            raise ValueError("Tool confirmation decision payload is required")
        stage_contract = self._stage_contract(request)
        call_id = self._structured_tool_confirmation_call_id(decision)
        self._append_process_record(
            request,
            "tool_confirmation_trace",
            {
                **decision.tool_confirmation.model_dump(mode="json"),
                "status": "skipped",
                "skip_high_risk_tool_confirmations": True,
                "tool_call_id": call_id,
                "decision_trace_ref": decision.decision_trace.trace_ref,
            },
        )
        tool_request = ToolExecutionRequest(
            tool_name=decision.tool_confirmation.tool_name,
            call_id=call_id,
            input_payload=dict(decision.tool_confirmation.input_payload),
            trace_context=request.invocation.trace_context,
            coordination_key=f"{request.invocation.stage_run_id}:{call_id}",
        )
        return self._execute_tool_request(
            request,
            tool_request,
            stage_contract=stage_contract,
        )

    def _execute_tool_request(
        self,
        request: StageExecutionRequest,
        tool_request: ToolExecutionRequest,
        *,
        stage_contract: dict[str, object],
    ) -> ToolResult:
        return self._tool_registry.execute(
            tool_request,
            ToolExecutionContext(
                stage_type=request.invocation.stage_type,
                stage_contracts={request.invocation.stage_type.value: stage_contract},
                trace_context=request.invocation.trace_context,
                runtime_tool_timeout_seconds=self._runtime_tool_timeout_seconds,
                platform_tool_timeout_hard_limit_seconds=(
                    self._platform_tool_timeout_hard_limit_seconds
                ),
                workspace_boundary=self._workspace_boundary,
                audit_recorder=self._audit_recorder,
                run_log_recorder=self._run_log_recorder,
                risk_policy=self._risk_policy,
                confirmation_port=self._confirmation_port,
                skip_high_risk_tool_confirmations=(
                    self._skip_high_risk_tool_confirmations(stage_contract)
                ),
            ),
        )

    def submit_stage_artifact(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
        iteration_index: int,
        *,
        recovery_ref: str | None = None,
    ) -> StageNodeResult:
        del iteration_index, recovery_ref
        if decision.stage_artifact is None:
            return self._failed_result(
                request,
                reason="stage_artifact_payload_missing",
            )
        payload_ref = f"stage-artifact://{request.stage_artifact_id}/output"
        self._artifact_store.complete_stage_output(
            artifact_id=request.stage_artifact_id,
            payload_ref=payload_ref,
            output_snapshot={
                "artifact_type": decision.stage_artifact.artifact_type,
                "artifact_payload": dict(decision.stage_artifact.artifact_payload),
                "evidence_refs": list(decision.stage_artifact.evidence_refs),
                "risk_summary": decision.stage_artifact.risk_summary,
                "failure_summary": decision.stage_artifact.failure_summary,
            },
            output_refs=list(decision.stage_artifact.evidence_refs),
            trace_context=request.invocation.trace_context,
        )
        return self._node_result(
            request,
            status=StageStatus.COMPLETED,
            artifact_refs=[request.stage_artifact_id],
        )

    def persist_recovery_checkpoint(
        self,
        request: StageExecutionRequest,
        cursor: StageRecoveryCursor,
    ) -> str:
        return self._append_process_record(
            request,
            "recovery_checkpoint",
            cursor.to_record(),
        )

    def _run_loop(self, request: StageExecutionRequest) -> StageNodeResult:
        tool_results: list[ToolResult] = []
        current_request = request
        max_iterations = (
            request.runtime_limit_snapshot.agent_limits.max_react_iterations_per_stage
        )
        for iteration_index in range(1, max_iterations + 1):
            result, tool_result, next_request = self.run_iteration(
                current_request,
                iteration_index,
                tuple(tool_results),
            )
            current_request = next_request
            if tool_result is not None:
                tool_results.append(tool_result)
            if result is not None:
                return result
        return self._failed_result(
            current_request,
            reason="max_react_iterations_exceeded",
            iteration_index=max_iterations,
        )

    def _request_from_invocation(
        self,
        invocation: StageNodeInvocation,
    ) -> StageExecutionRequest:
        return StageExecutionRequest(
            invocation=invocation,
            stage_artifact_id=self._stage_artifact_id
            or f"artifact-{invocation.stage_run_id}",
            template_snapshot=self._template_snapshot,
            graph_definition=self._graph_definition,
            runtime_limit_snapshot=self._runtime_limit_snapshot,
            provider_snapshot=self._provider_snapshot,
            model_binding_snapshot=self._model_binding_snapshot,
            task_objective=self._task_objective,
            specified_action=self._specified_action,
            response_schema=dict(self._response_schema),
            output_schema_ref=self._output_schema_ref,
            tool_schema_version=self._tool_schema_version,
            template_version=self._template_version,
            requested_max_output_tokens=self._requested_max_output_tokens,
            stage_artifacts=self._stage_artifacts,
            context_references=self._context_references,
            change_sets=self._change_sets,
            clarifications=self._clarifications,
            approval_decisions=self._approval_decisions,
        )

    def _context_request(self, request: StageExecutionRequest) -> ContextBuildRequest:
        return ContextBuildRequest(
            session_id=request.invocation.runtime_context.session_id,
            run_id=request.invocation.run_id,
            stage_run_id=request.invocation.stage_run_id,
            stage_artifact_id=request.stage_artifact_id,
            stage_type=request.invocation.stage_type,
            stage_contract_ref=request.invocation.stage_contract_ref,
            model_call_type=request.model_call_type,
            task_objective=request.task_objective,
            specified_action=request.specified_action,
            response_schema=dict(request.response_schema),
            output_schema_ref=request.output_schema_ref,
            tool_schema_version=request.tool_schema_version,
            template_version=request.template_version,
            trace_context=request.invocation.trace_context,
            template_snapshot=request.template_snapshot,
            graph_definition=request.graph_definition,
            runtime_limit_snapshot=request.runtime_limit_snapshot,
            provider_snapshot=request.provider_snapshot,
            model_binding_snapshot=request.model_binding_snapshot,
            parse_error=request.parse_error,
            stage_artifacts=request.stage_artifacts,
            context_references=request.context_references,
            change_sets=request.change_sets,
            clarifications=request.clarifications,
            approval_decisions=request.approval_decisions,
            provider_adapter=self._provider_adapter,
            reserved_output_tokens=request.requested_max_output_tokens or 0,
        )

    def _repair_from_parser_error(
        self,
        request: StageExecutionRequest,
        exc: AgentDecisionParserError,
        *,
        iteration_index: int,
        last_model_call_ref: str,
    ) -> tuple[None, None, StageExecutionRequest] | None:
        if exc.error.error_code in {
            AgentDecisionErrorCode.PROVIDER_CALL_FAILED,
            AgentDecisionErrorCode.CLARIFICATION_NOT_ALLOWED,
        }:
            return None
        repair_count = self._process_record_count("structured_output_repair_trace")
        if (
            repair_count
            >= request.runtime_limit_snapshot.agent_limits.max_structured_output_repair_attempts
        ):
            return None
        self._append_process_record(
            request,
            "structured_output_repair_trace",
            {
                "parse_error_summary": _bounded_string(exc.error.safe_message),
                "parse_error_code": exc.error.error_code.value,
                "invalid_output_ref": exc.error.decision_trace.model_call_ref,
                "repair_instruction_summary": (
                    "Return a valid AgentDecision matching the current response schema."
                ),
                "decision_trace_ref": exc.error.decision_trace.trace_ref,
                "iteration_index": iteration_index,
            },
        )
        self.persist_recovery_checkpoint(
            request,
            self._recovery_cursor(
                request,
                iteration_index=iteration_index,
                last_decision_trace_ref=exc.error.decision_trace.trace_ref,
                last_model_call_ref=last_model_call_ref,
            ),
        )
        return (
            None,
            None,
            replace(
                request,
                model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR,
                parse_error=exc.error.error_code.value,
            ),
        )

    def _ensure_stage_input(self, request: StageExecutionRequest) -> None:
        try:
            self._artifact_store.get_stage_artifact(
                request.stage_artifact_id,
                trace_context=request.invocation.trace_context,
                log_missing_failure=False,
            )
            return
        except ArtifactStoreError as exc:
            if "not found" not in str(exc).lower():
                raise

        self._artifact_store.create_stage_input(
            run_id=request.invocation.run_id,
            stage_run_id=request.invocation.stage_run_id,
            artifact_id=request.stage_artifact_id,
            artifact_type=f"{request.invocation.stage_type.value}_stage_agent_stage",
            payload_ref=f"stage-artifact://{request.stage_artifact_id}/input",
            input_snapshot={
                "runtime": "stage_agent",
                "stage_type": request.invocation.stage_type.value,
                "stage_contract_ref": request.invocation.stage_contract_ref,
                "graph_node_key": request.invocation.graph_node_key,
                "snapshot_refs": {
                    "template_snapshot_ref": request.template_snapshot.snapshot_ref,
                    "provider_snapshot_ref": request.provider_snapshot.snapshot_id,
                    "model_binding_snapshot_ref": (
                        request.model_binding_snapshot.snapshot_id
                    ),
                    "runtime_limit_snapshot_ref": (
                        request.runtime_limit_snapshot.snapshot_id
                    ),
                },
            },
            input_refs=self._input_refs(request),
            trace_context=request.invocation.trace_context,
        )

    def _input_refs(self, request: StageExecutionRequest) -> tuple[str, ...]:
        refs: list[str] = []
        for item in request.stage_artifacts:
            artifact_id = getattr(item, "artifact_id", None)
            if isinstance(artifact_id, str) and artifact_id:
                refs.append(artifact_id)
                continue
            payload_ref = getattr(item, "payload_ref", None)
            if isinstance(payload_ref, str) and payload_ref:
                refs.append(payload_ref)
        return tuple(dict.fromkeys(refs))

    def _capability_failure_reason(
        self,
        request: StageExecutionRequest,
        *,
        available_tools: tuple[object, ...],
    ) -> str | None:
        capabilities = request.model_binding_snapshot.capabilities
        requested_tokens = request.requested_max_output_tokens
        if (
            requested_tokens is not None
            and requested_tokens > capabilities.max_output_tokens
        ):
            return "max_output_tokens_insufficient"
        if available_tools and not capabilities.supports_tool_calling:
            return "tool_calling_unsupported"
        if not capabilities.supports_structured_output:
            return "structured_output_unsupported"
        return None

    def _append_model_call_traces(
        self,
        request: StageExecutionRequest,
        model_result: ModelCallResult,
    ) -> str:
        model_call_ref = model_result.raw_response_ref or self._fallback_model_call_ref(
            model_result
        )
        retry_refs = [
            item.trace_ref for item in model_result.provider_retry_trace
        ]
        circuit_refs = [
            item.trace_ref for item in model_result.provider_circuit_breaker_trace
        ]
        self._append_process_record(
            request,
            "model_call_trace",
            {
                "model_call_ref": model_call_ref,
                "provider_snapshot_id": model_result.provider_snapshot_id,
                "model_binding_snapshot_id": model_result.model_binding_snapshot_id,
                "provider_id": request.provider_snapshot.provider_id,
                "model_id": request.model_binding_snapshot.model_id,
                "model_call_type": model_result.model_call_type.value,
                "raw_response_ref": model_result.raw_response_ref,
                "native_reasoning_ref": model_result.native_reasoning_ref,
                "usage": model_result.usage.model_dump(mode="json"),
                "retry_trace_refs": retry_refs,
                "retry_trace_count": len(retry_refs),
                "circuit_breaker_trace_refs": circuit_refs,
                "circuit_breaker_trace_count": len(circuit_refs),
                "trace": _safe_trace_summary(model_result),
                "input_summary": _safe_payload_summary(
                    model_result.trace_summary.input_summary
                ),
                "output_summary": _safe_payload_summary(
                    model_result.trace_summary.output_summary
                ),
            },
        )
        for retry_trace in model_result.provider_retry_trace:
            self._append_process_record(
                request,
                "provider_retry_trace",
                retry_trace.model_dump(mode="json"),
            )
        for circuit_trace in model_result.provider_circuit_breaker_trace:
            self._append_process_record(
                request,
                "provider_circuit_breaker_trace",
                circuit_trace.model_dump(mode="json"),
            )
        return model_call_ref

    def _result_from_tool_result(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
        tool_result: ToolResult,
        iteration_index: int,
        *,
        last_decision_trace_ref: str | None,
        last_model_call_ref: str | None,
        completed_tool_call_ids: tuple[str, ...],
    ) -> StageNodeResult | None:
        self._append_process_record(
            request,
            "tool_trace",
            self._tool_trace(decision, tool_result, iteration_index),
        )
        completed_ids = completed_tool_call_ids
        if tool_result.status is ToolResultStatus.SUCCEEDED:
            completed_ids = (*completed_tool_call_ids, tool_result.call_id)
            self.persist_recovery_checkpoint(
                request,
                self._recovery_cursor(
                    request,
                    iteration_index=iteration_index,
                    last_decision_trace_ref=last_decision_trace_ref,
                    last_model_call_ref=last_model_call_ref,
                    last_tool_call_id=tool_result.call_id,
                    completed_tool_call_ids=completed_ids,
                ),
            )
            return None

        confirmation_ref = tool_result.tool_confirmation_ref
        if tool_result.status is ToolResultStatus.WAITING_CONFIRMATION:
            self._append_process_record(
                request,
                "tool_confirmation_trace",
                {
                    "tool_name": tool_result.tool_name,
                    "call_id": tool_result.call_id,
                    "tool_confirmation_ref": confirmation_ref,
                    "decision_trace_ref": last_decision_trace_ref,
                    "status": tool_result.status.value,
                    "safe_details": _tool_error_safe_details(tool_result),
                },
            )
            self.persist_recovery_checkpoint(
                request,
                self._recovery_cursor(
                    request,
                    iteration_index=iteration_index,
                    last_decision_trace_ref=last_decision_trace_ref,
                    last_model_call_ref=last_model_call_ref,
                    last_tool_call_id=tool_result.call_id,
                    last_tool_confirmation_ref=confirmation_ref,
                    completed_tool_call_ids=completed_ids,
                ),
            )
            return self._node_result(
                request,
                status=StageStatus.WAITING_TOOL_CONFIRMATION,
                route_key="waiting_tool_confirmation",
            )

        if (
            tool_result.status is ToolResultStatus.BLOCKED
            or tool_result.reconciliation_status
            in {
                ToolReconciliationStatus.FAILED,
                ToolReconciliationStatus.UNKNOWN,
            }
        ):
            self._append_process_record(
                request,
                "side_effect_reconciliation_trace",
                {
                    "tool_name": tool_result.tool_name,
                    "call_id": tool_result.call_id,
                    "status": tool_result.status.value,
                    "reconciliation_status": tool_result.reconciliation_status.value,
                    "side_effect_refs": list(tool_result.side_effect_refs),
                    "safe_details": _tool_error_safe_details(tool_result),
                },
            )
        return self._failed_result(
            request,
            reason=f"tool_{tool_result.status.value}",
            iteration_index=iteration_index,
            last_decision_trace_ref=last_decision_trace_ref,
            last_model_call_ref=last_model_call_ref,
            last_tool_call_id=tool_result.call_id,
            completed_tool_call_ids=completed_ids,
        )

    def _result_from_control_decision(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
        iteration_index: int,
        *,
        last_decision_trace_ref: str | None,
        last_model_call_ref: str | None,
    ) -> StageNodeResult:
        del iteration_index, last_decision_trace_ref, last_model_call_ref
        if decision.decision_type is AgentDecisionType.REQUEST_CLARIFICATION:
            if decision.clarification is None:
                return self._failed_result(
                    request,
                    reason="clarification_payload_missing",
                )
            self._append_process_record(
                request,
                "clarification_request",
                {
                    **decision.clarification.model_dump(mode="json"),
                    "decision_trace_ref": decision.decision_trace.trace_ref,
                },
            )
            return self._node_result(
                request,
                status=StageStatus.WAITING_CLARIFICATION,
                route_key="waiting_clarification",
            )
        if decision.decision_type is AgentDecisionType.REQUEST_TOOL_CONFIRMATION:
            self._append_process_record(
                request,
                "tool_confirmation_trace",
                decision.tool_confirmation.model_dump(mode="json")
                if decision.tool_confirmation is not None
                else {},
            )
            return self._node_result(
                request,
                status=StageStatus.WAITING_TOOL_CONFIRMATION,
                route_key="waiting_tool_confirmation",
            )
        if decision.fail_stage is not None:
            return self._failed_result(
                request,
                reason=decision.fail_stage.failure_reason,
                safe_details={
                    "evidence_refs": list(decision.fail_stage.evidence_refs),
                    "incomplete_items": list(decision.fail_stage.incomplete_items),
                    "user_visible_summary": decision.fail_stage.user_visible_summary,
                },
            )
        return self._failed_result(request, reason="unsupported_agent_decision")

    def _failed_result(
        self,
        request: StageExecutionRequest,
        *,
        reason: str,
        iteration_index: int | None = None,
        last_decision_trace_ref: str | None = None,
        last_model_call_ref: str | None = None,
        last_tool_call_id: str | None = None,
        completed_tool_call_ids: tuple[str, ...] = (),
        safe_details: Mapping[str, object] | None = None,
    ) -> StageNodeResult:
        if iteration_index is not None:
            self.persist_recovery_checkpoint(
                request,
                self._recovery_cursor(
                    request,
                    iteration_index=iteration_index,
                    last_decision_trace_ref=last_decision_trace_ref,
                    last_model_call_ref=last_model_call_ref,
                    last_tool_call_id=last_tool_call_id,
                    completed_tool_call_ids=completed_tool_call_ids,
                ),
            )
        self._append_process_record(
            request,
            "stage_agent_failed",
            {
                "reason": _bounded_string(reason),
                "safe_details": dict(safe_details or {}),
                "failed_at": self._now().isoformat(),
            },
        )
        return self._node_result(
            request,
            status=StageStatus.FAILED,
            route_key="failed",
        )

    def _node_result(
        self,
        request: StageExecutionRequest,
        *,
        status: StageStatus,
        artifact_refs: Sequence[str] = (),
        route_key: str | None = None,
    ) -> StageNodeResult:
        return StageNodeResult(
            run_id=request.invocation.run_id,
            stage_run_id=request.invocation.stage_run_id,
            stage_type=request.invocation.stage_type,
            status=status,
            artifact_refs=list(artifact_refs),
            domain_event_refs=[],
            log_summary_refs=list(self._process_refs),
            audit_refs=[],
            route_key=route_key,
        )

    def _append_process_record(
        self,
        request: StageExecutionRequest,
        process_key: str,
        process_value: object,
    ) -> str:
        if process_key in self._process_records:
            existing = self._process_records[process_key]
            if isinstance(existing, list):
                next_value = [*existing, process_value]
            else:
                next_value = [existing, process_value]
        else:
            next_value = process_value
        self._process_records[process_key] = next_value
        self._artifact_store.append_process_record(
            artifact_id=request.stage_artifact_id,
            process_key=process_key,
            process_value=next_value,
            trace_context=request.invocation.trace_context,
        )
        process_ref = f"stage-artifact://{request.stage_artifact_id}#process/{process_key}"
        self._process_refs.append(process_ref)
        if self._progress_callback is not None:
            self._progress_callback(request, process_key, process_ref)
        return process_ref

    def _process_record_count(self, process_key: str) -> int:
        existing = self._process_records.get(process_key)
        if existing is None:
            return 0
        if isinstance(existing, list):
            return len(existing)
        return 1

    def _recovery_cursor(
        self,
        request: StageExecutionRequest,
        *,
        iteration_index: int,
        last_decision_trace_ref: str | None = None,
        last_model_call_ref: str | None = None,
        last_tool_call_id: str | None = None,
        last_tool_confirmation_ref: str | None = None,
        completed_tool_call_ids: tuple[str, ...] = (),
    ) -> StageRecoveryCursor:
        source = {
            "run_id": request.invocation.run_id,
            "stage_run_id": request.invocation.stage_run_id,
            "stage_type": request.invocation.stage_type.value,
            "iteration_index": iteration_index,
            "last_decision_trace_ref": last_decision_trace_ref,
            "last_model_call_ref": last_model_call_ref,
            "last_tool_call_id": last_tool_call_id,
            "last_tool_confirmation_ref": last_tool_confirmation_ref,
            "completed_tool_call_ids": list(completed_tool_call_ids),
        }
        encoded = json.dumps(source, sort_keys=True, separators=(",", ":"))
        digest = sha256(encoded.encode("utf-8")).hexdigest()[:24]
        return StageRecoveryCursor(
            cursor_id=f"stage-recovery-{digest}",
            run_id=request.invocation.run_id,
            stage_run_id=request.invocation.stage_run_id,
            stage_type=request.invocation.stage_type,
            iteration_index=iteration_index,
            last_decision_trace_ref=last_decision_trace_ref,
            last_model_call_ref=last_model_call_ref,
            last_tool_call_id=last_tool_call_id,
            last_tool_confirmation_ref=last_tool_confirmation_ref,
            completed_tool_call_ids=completed_tool_call_ids,
            created_at=self._now(),
        )

    def _stage_contract(self, request: StageExecutionRequest) -> dict[str, object]:
        return dict(
            request.graph_definition.stage_contracts[request.invocation.stage_type.value]
        )

    def _should_skip_structured_tool_confirmation(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
    ) -> bool:
        confirmation = decision.tool_confirmation
        return (
            confirmation is not None
            and confirmation.risk_level is ToolRiskLevel.HIGH_RISK
            and self._skip_high_risk_tool_confirmations(self._stage_contract(request))
        )

    @staticmethod
    def _skip_high_risk_tool_confirmations(
        stage_contract: Mapping[str, object],
    ) -> bool:
        runtime_limits = stage_contract.get("runtime_limits", {})
        return (
            isinstance(runtime_limits, Mapping)
            and runtime_limits.get("skip_high_risk_tool_confirmations") is True
        )

    @staticmethod
    def _provider_messages(messages: Sequence[object]) -> tuple[BaseMessage, ...]:
        converted: list[BaseMessage] = []
        for message in messages:
            if isinstance(message, BaseMessage):
                converted.append(message)
                continue
            role = getattr(message, "role", "user")
            content = str(getattr(message, "content", ""))
            if role == "system":
                converted.append(SystemMessage(content=content))
            elif role == "assistant":
                converted.append(AIMessage(content=content))
            else:
                converted.append(HumanMessage(content=content))
        return tuple(converted)

    @staticmethod
    def _fallback_model_call_ref(model_result: ModelCallResult) -> str:
        source = {
            "provider_snapshot_id": model_result.provider_snapshot_id,
            "model_binding_snapshot_id": model_result.model_binding_snapshot_id,
            "model_call_type": model_result.model_call_type.value,
            "request_id": model_result.trace_summary.request_id,
            "trace_id": model_result.trace_summary.trace_id,
            "stage_run_id": model_result.trace_summary.stage_run_id,
        }
        encoded = json.dumps(source, sort_keys=True, separators=(",", ":"))
        return f"model-call:{sha256(encoded.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _structured_tool_confirmation_call_id(decision: AgentDecision) -> str:
        digest = sha256(
            decision.decision_trace.trace_ref.encode("utf-8")
        ).hexdigest()[:16]
        return f"structured-confirmation-{digest}"

    @staticmethod
    def _tool_trace(
        decision: AgentDecision,
        tool_result: ToolResult,
        iteration_index: int,
    ) -> dict[str, object]:
        return {
            "tool_name": tool_result.tool_name,
            "call_id": tool_result.call_id,
            "status": tool_result.status.value,
            "artifact_refs": list(tool_result.artifact_refs),
            "side_effect_refs": list(tool_result.side_effect_refs),
            "tool_confirmation_ref": tool_result.tool_confirmation_ref,
            "reconciliation_status": tool_result.reconciliation_status.value,
            "error_code": (
                tool_result.error.error_code.value
                if tool_result.error is not None
                else None
            ),
            "safe_details": _tool_error_safe_details(tool_result),
            "decision_trace_ref": decision.decision_trace.trace_ref,
            "iteration_index": iteration_index,
        }


def _tool_error_safe_details(tool_result: ToolResult) -> dict[str, object]:
    if tool_result.error is None:
        return {}
    return dict(tool_result.error.safe_details)


def _safe_trace_summary(model_result: ModelCallResult) -> dict[str, object]:
    summary = model_result.trace_summary
    return {
        "request_id": summary.request_id,
        "trace_id": summary.trace_id,
        "correlation_id": summary.correlation_id,
        "span_id": summary.span_id,
        "parent_span_id": summary.parent_span_id,
        "run_id": summary.run_id,
        "stage_run_id": summary.stage_run_id,
    }


def _safe_payload_summary(summary: Mapping[str, object]) -> dict[str, object]:
    safe_keys = (
        "content_hash",
        "payload_size_bytes",
        "redaction_status",
        "token_count",
        "tool_call_count",
        "structured_candidate_count",
        "invalid_tool_call_count",
    )
    return {key: summary[key] for key in safe_keys if key in summary}


def _bounded_string(value: str, *, limit: int = 200) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


__all__ = [
    "StageAgentRuntime",
    "StageExecutionRequest",
    "StageRecoveryCursor",
]
