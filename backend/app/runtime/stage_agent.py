from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from backend.app.context.builder import ContextBuildRequest, ContextEnvelopeBuilder
from backend.app.domain.enums import (
    StageStatus,
    StageType,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.template_snapshot import TemplateSnapshot
from backend.app.observability.langsmith_tracing import (
    NoopRuntimeTracer,
    RuntimeTracer,
)
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
    agent_decision_response_schema,
    stage_response_schema,
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
from backend.app.tools.risk import ToolConfirmationGrant


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
    user_messages: tuple[Any, ...] = ()


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


@dataclass(frozen=True, slots=True)
class _StageArtifactEvidencePolicy:
    artifact_type: str
    payload_field: str
    tool_names: tuple[str, ...]
    ref_prefix: str


@dataclass(frozen=True, slots=True)
class _StageArtifactEvidenceResult:
    decision: AgentDecision
    request: StageExecutionRequest
    result: StageNodeResult | None = None


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
        user_messages: Sequence[Any] = (),
        runtime_tool_timeout_seconds: float | None = None,
        platform_tool_timeout_hard_limit_seconds: float | None = None,
        workspace_boundary: object | None = None,
        audit_recorder: object | None = None,
        run_log_recorder: object | None = None,
        risk_policy: object | None = None,
        confirmation_port: object | None = None,
        progress_callback: StageProgressCallback | None = None,
        runtime_tracer: RuntimeTracer | None = None,
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
        self._user_messages = tuple(user_messages)
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
        self._runtime_tracer = runtime_tracer or NoopRuntimeTracer()
        self._now = now or (lambda: datetime.now(UTC))
        self._process_records: dict[str, object] = {}
        self._process_refs: list[str] = []

    def run_stage(self, invocation: StageNodeInvocation) -> StageNodeResult:
        self._process_records = {}
        self._process_refs = []
        request = self._request_from_invocation(invocation)
        with self._runtime_tracer.trace_stage(
            run_id=request.invocation.run_id,
            stage_run_id=request.invocation.stage_run_id,
            stage_type=request.invocation.stage_type.value,
            graph_node_key=request.invocation.graph_node_key,
        ):
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
    ) -> tuple[StageNodeResult | None, tuple[ToolResult, ...], StageExecutionRequest]:
        with self._runtime_tracer.trace_iteration(
            iteration_index=iteration_index,
            model_call_type=request.model_call_type.value,
            tool_result_count=len(tool_results),
        ):
            return self._run_iteration(request, iteration_index, tool_results)

    def _run_iteration(
        self,
        request: StageExecutionRequest,
        iteration_index: int,
        tool_results: tuple[ToolResult, ...],
    ) -> tuple[StageNodeResult | None, tuple[ToolResult, ...], StageExecutionRequest]:
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
                (),
                request,
            )

        iteration_trace = request.invocation.trace_context.child_span(
            span_id=f"stage-agent-iteration-{iteration_index}",
            created_at=self._now(),
            run_id=request.invocation.run_id,
            stage_run_id=request.invocation.stage_run_id,
        )
        model_result = self._provider_adapter.invoke_with_retry(
            messages=self._provider_messages(
                build_result.rendered_messages,
                tool_results=tool_results,
            ),
            response_schema=dict(build_result.envelope.response_schema),
            model_call_type=request.model_call_type,
            tool_descriptions=self._tool_descriptions_for_model_call(
                request,
                tuple(build_result.envelope.available_tools),
            ),
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
            self._runtime_tracer.record_model_decision(
                decision_type=(
                    exc.error.decision_trace.decision_type.value
                    if exc.error.decision_trace.decision_type is not None
                    else None
                ),
                status=exc.error.decision_trace.status,
                trace_ref=exc.error.decision_trace.trace_ref,
                model_call_ref=exc.error.decision_trace.model_call_ref,
                reason=exc.error.safe_message,
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
                (),
                request,
            )

        self._append_process_record(
            request,
            "decision_trace",
            decision.decision_trace.model_dump(mode="json"),
        )
        self._runtime_tracer.record_model_decision(
            decision_type=decision.decision_type.value,
            status=decision.decision_trace.status,
            trace_ref=decision.decision_trace.trace_ref,
            model_call_ref=decision.decision_trace.model_call_ref,
            reason=decision.decision_trace.reason,
        )

        cursor_kwargs = {
            "last_decision_trace_ref": decision.decision_trace.trace_ref,
            "last_model_call_ref": model_call_ref,
        }
        if decision.decision_type is AgentDecisionType.REQUEST_TOOL_CALL:
            limits = request.runtime_limit_snapshot.agent_limits
            batch_tool_calls = decision.tool_calls or (
                (decision.tool_call,) if decision.tool_call is not None else ()
            )
            if (
                len(tool_results) + len(batch_tool_calls)
                > limits.max_tool_calls_per_stage
            ):
                return (
                    self._failed_result(
                        request,
                        reason="max_tool_calls_exceeded",
                        iteration_index=iteration_index,
                        **cursor_kwargs,
                    ),
                    (),
                    request,
                )
            batch_results: list[ToolResult] = []
            completed_ids = tuple(
                item.call_id
                for item in tool_results
                if item.status is ToolResultStatus.SUCCEEDED
            )
            for tool_call in batch_tool_calls:
                single_decision = decision.model_copy(
                    update={"tool_call": tool_call, "tool_calls": (tool_call,)}
                )
                tool_result = self.execute_tool_decision(
                    request,
                    single_decision,
                    iteration_index,
                )
                batch_results.append(tool_result)
                result = self._result_from_tool_result(
                    request,
                    single_decision,
                    tool_result,
                    iteration_index,
                    completed_tool_call_ids=completed_ids,
                    **cursor_kwargs,
                )
                if tool_result.status is ToolResultStatus.SUCCEEDED:
                    completed_ids = (*completed_ids, tool_result.call_id)
                if result is not None:
                    return result, tuple(batch_results), request
            return None, tuple(batch_results), request

        if decision.decision_type is AgentDecisionType.SUBMIT_STAGE_ARTIFACT:
            evidence_result = self._normalize_or_repair_stage_artifact_evidence(
                request,
                decision,
                tool_results=tool_results,
                iteration_index=iteration_index,
                **cursor_kwargs,
            )
            if evidence_result.result is not None or evidence_result.request is not request:
                return (evidence_result.result, (), evidence_result.request)
            decision = evidence_result.decision
            semantic_failure = self._semantic_failure_for_stage_artifact(
                request,
                decision,
                iteration_index=iteration_index,
                **cursor_kwargs,
            )
            if semantic_failure is not None:
                return (semantic_failure, (), request)
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
                (),
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
                    (),
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
                    (),
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
                (),
                replace(
                    request,
                    model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR,
                    parse_error=repair.parse_error,
                    response_schema=self._structured_output_repair_response_schema(
                        request
                    ),
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
            return (
                None,
                (),
                replace(
                    request,
                    model_call_type=ModelCallType.STAGE_EXECUTION,
                    parse_error=None,
                    response_schema=self._base_response_schema(request),
                ),
            )

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
                    (),
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
            return result, (tool_result,), request

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
            (),
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
            confirmation_grant=self._confirmation_grant_for_tool_call(
                request,
                tool_name=decision.tool_call.tool_name,
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

    def _confirmation_grant_for_tool_call(
        self,
        request: StageExecutionRequest,
        *,
        tool_name: str,
    ) -> ToolConfirmationGrant | None:
        confirmation_id = request.invocation.trace_context.tool_confirmation_id
        if confirmation_id is None:
            return None
        confirmation = self._matching_tool_confirmation_trace(
            request,
            tool_confirmation_id=confirmation_id,
            tool_name=tool_name,
        )
        if confirmation is None:
            return None
        safe_details = confirmation.get("safe_details")
        if not isinstance(safe_details, Mapping):
            return None
        input_digest = _optional_string(safe_details.get("input_digest"))
        target_summary = _optional_string(safe_details.get("target_summary"))
        risk_level = _tool_risk_level_from_value(safe_details.get("risk_level"))
        risk_categories = _tool_risk_categories_from_value(
            safe_details.get("risk_categories")
        )
        if input_digest is None or target_summary is None or risk_level is None:
            return None
        return ToolConfirmationGrant(
            tool_confirmation_id=confirmation_id,
            confirmation_object_ref=_confirmation_object_ref(
                tool_name=tool_name,
                call_id=_optional_string(confirmation.get("call_id")) or "unknown",
                input_digest=input_digest,
            ),
            tool_name=tool_name,
            input_digest=input_digest,
            target_summary=target_summary,
            risk_level=risk_level,
            risk_categories=risk_categories,
        )

    def _matching_tool_confirmation_trace(
        self,
        request: StageExecutionRequest,
        *,
        tool_confirmation_id: str,
        tool_name: str,
    ) -> Mapping[str, object] | None:
        records = [
            record
            for record in self._tool_confirmation_trace_records(request)
            if record.get("tool_confirmation_ref") == tool_confirmation_id
            and record.get("tool_name") == tool_name
        ]
        return records[-1] if records else None

    def _tool_confirmation_trace_records(
        self,
        request: StageExecutionRequest,
    ) -> tuple[Mapping[str, object], ...]:
        records: list[Mapping[str, object]] = []
        process_record = self._process_records.get("tool_confirmation_trace")
        records.extend(_mapping_records(process_record))
        for artifact in request.stage_artifacts:
            if getattr(artifact, "stage_run_id", None) != request.invocation.stage_run_id:
                continue
            process = getattr(artifact, "process", None)
            if not isinstance(process, Mapping):
                continue
            records.extend(_mapping_records(process.get("tool_confirmation_trace")))
        return tuple(records)

    def _execute_tool_request(
        self,
        request: StageExecutionRequest,
        tool_request: ToolExecutionRequest,
        *,
        stage_contract: dict[str, object],
    ) -> ToolResult:
        with self._runtime_tracer.trace_tool_call(
            tool_name=tool_request.tool_name,
            call_id=tool_request.call_id,
            input_payload=tool_request.input_payload,
        ):
            tool_result = self._tool_registry.execute(
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
            self._runtime_tracer.record_tool_result(
                tool_name=tool_result.tool_name,
                call_id=tool_result.call_id,
                status=tool_result.status.value,
                artifact_refs=tuple(tool_result.artifact_refs),
                side_effect_refs=tuple(tool_result.side_effect_refs),
                error_code=(
                    tool_result.error.error_code.value
                    if tool_result.error is not None
                    else None
                ),
                safe_details=_tool_error_safe_details(tool_result),
            )
            return tool_result

    def _normalize_or_repair_stage_artifact_evidence(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
        *,
        tool_results: tuple[ToolResult, ...],
        iteration_index: int,
        last_decision_trace_ref: str | None,
        last_model_call_ref: str | None,
    ) -> _StageArtifactEvidenceResult:
        stage_artifact = decision.stage_artifact
        if stage_artifact is None:
            return _StageArtifactEvidenceResult(
                decision=decision,
                request=request,
            )
        policy = _evidence_policy_for_artifact(
            stage_artifact.artifact_type,
            allowed_tools=_allowed_tool_names(
                self._stage_contract(request).get("allowed_tools")
            ),
        )
        if policy is None:
            return _StageArtifactEvidenceResult(
                decision=decision,
                request=request,
            )

        refs = _successful_side_effect_refs(
            tool_results,
            tool_names=policy.tool_names,
            ref_prefix=policy.ref_prefix,
        )
        if not refs:
            return self._repair_or_fail_missing_stage_artifact_evidence(
                request,
                decision,
                policy=policy,
                iteration_index=iteration_index,
                last_decision_trace_ref=last_decision_trace_ref,
                last_model_call_ref=last_model_call_ref,
                completed_tool_call_ids=tuple(
                    item.call_id
                    for item in tool_results
                    if item.status is ToolResultStatus.SUCCEEDED
                ),
            )

        payload = dict(stage_artifact.artifact_payload)
        payload[policy.payload_field] = list(refs)
        evidence_refs = _dedupe_strings((*stage_artifact.evidence_refs, *refs))
        normalized_stage_artifact = stage_artifact.model_copy(
            update={
                "artifact_payload": payload,
                "evidence_refs": evidence_refs,
            }
        )
        return _StageArtifactEvidenceResult(
            decision=decision.model_copy(
                update={"stage_artifact": normalized_stage_artifact}
            ),
            request=request,
        )

    def _repair_or_fail_missing_stage_artifact_evidence(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
        *,
        policy: "_StageArtifactEvidencePolicy",
        iteration_index: int,
        last_decision_trace_ref: str | None,
        last_model_call_ref: str | None,
        completed_tool_call_ids: tuple[str, ...],
    ) -> _StageArtifactEvidenceResult:
        return _StageArtifactEvidenceResult(
            decision=decision,
            request=request,
            result=self._failed_result(
                request,
                reason="stage_artifact_missing_tool_evidence",
                iteration_index=iteration_index,
                last_decision_trace_ref=last_decision_trace_ref,
                last_model_call_ref=last_model_call_ref,
                completed_tool_call_ids=completed_tool_call_ids,
                safe_details={
                    "artifact_type": policy.artifact_type,
                    "missing_field": policy.payload_field,
                    "required_tools": list(policy.tool_names),
                    "required_ref_prefix": policy.ref_prefix,
                },
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
        self._runtime_tracer.record_stage_result(
            status=StageStatus.COMPLETED.value,
            artifact_type=decision.stage_artifact.artifact_type,
            artifact_refs=(request.stage_artifact_id,),
            evidence_refs=tuple(decision.stage_artifact.evidence_refs),
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
            result, tool_batch, next_request = self.run_iteration(
                current_request,
                iteration_index,
                tuple(tool_results),
            )
            current_request = next_request
            tool_results.extend(tool_batch)
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
            user_messages=self._user_messages,
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
            user_messages=request.user_messages,
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
    ) -> tuple[None, tuple[ToolResult, ...], StageExecutionRequest] | None:
        intended_decision_type = _repairable_decision_type_from_parser_error(
            request,
            exc,
        )
        if intended_decision_type is None:
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
                    "Repair only the structured format while preserving "
                    f"{intended_decision_type.value}."
                ),
                "decision_trace_ref": exc.error.decision_trace.trace_ref,
                "iteration_index": iteration_index,
                "intended_decision_type": intended_decision_type.value,
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
            (),
            replace(
                request,
                model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR,
                parse_error=exc.error.error_code.value,
                response_schema=self._structured_output_repair_response_schema(
                    request,
                    intended_decision_type=intended_decision_type,
                ),
            ),
        )

    def _structured_output_repair_response_schema(
        self,
        request: StageExecutionRequest,
        *,
        intended_decision_type: AgentDecisionType | None = None,
    ) -> dict[str, object]:
        if intended_decision_type is None:
            allowed = [
                decision_type
                for decision_type in _base_response_schema_decision_types(request)
                if decision_type is not AgentDecisionType.REPAIR_STRUCTURED_OUTPUT
            ]
        else:
            allowed = [intended_decision_type]
        return agent_decision_response_schema(
            artifact_type=_stage_artifact_type(request),
            allowed_decision_types=tuple(allowed),
        )

    def _base_response_schema(
        self,
        request: StageExecutionRequest,
    ) -> dict[str, object]:
        return stage_response_schema(
            artifact_type=_stage_artifact_type(request),
            allowed_decision_types=_base_response_schema_decision_types(request),
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
            semantic_failure = self._semantic_failure_for_control_decision(
                request,
                decision,
            )
            if semantic_failure is not None:
                return semantic_failure
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

    def _semantic_failure_for_stage_artifact(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
        *,
        iteration_index: int,
        last_decision_trace_ref: str | None,
        last_model_call_ref: str | None,
    ) -> StageNodeResult | None:
        stage_artifact = decision.stage_artifact
        if stage_artifact is None:
            return None
        violation = _stage_artifact_semantic_violation(request, stage_artifact)
        if violation is None:
            return None
        return self._failed_result(
            request,
            reason="stage_semantic_gate_failed",
            iteration_index=iteration_index,
            last_decision_trace_ref=last_decision_trace_ref,
            last_model_call_ref=last_model_call_ref,
            safe_details=violation,
        )

    def _semantic_failure_for_control_decision(
        self,
        request: StageExecutionRequest,
        decision: AgentDecision,
    ) -> StageNodeResult | None:
        violation = _control_decision_semantic_violation(request, decision)
        if violation is None:
            return None
        return self._failed_result(
            request,
            reason="stage_semantic_gate_failed",
            safe_details=violation,
        )

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
        self._runtime_tracer.record_stage_failure(
            reason=reason,
            safe_details=dict(safe_details or {}),
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

    def _provider_messages(
        self,
        messages: Sequence[object],
        *,
        tool_results: Sequence[ToolResult] = (),
    ) -> tuple[BaseMessage, ...]:
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
        tool_observation = self._tool_result_observation(tool_results)
        if tool_observation is not None:
            converted.append(HumanMessage(content=tool_observation))
        return tuple(converted)

    @staticmethod
    def _tool_descriptions_for_model_call(
        request: StageExecutionRequest,
        available_tools: tuple[object, ...],
    ) -> tuple[object, ...]:
        if request.model_call_type is ModelCallType.STRUCTURED_OUTPUT_REPAIR:
            return ()
        return available_tools

    @staticmethod
    def _tool_result_observation(
        tool_results: Sequence[ToolResult],
    ) -> str | None:
        if not tool_results:
            return None
        payload = []
        for result in tool_results:
            payload.append(
                {
                    "tool_name": result.tool_name,
                    "call_id": result.call_id,
                    "status": result.status.value,
                    "output_payload": dict(result.output_payload),
                    "artifact_refs": list(result.artifact_refs),
                    "side_effect_refs": list(result.side_effect_refs),
                    "error_code": (
                        result.error.error_code.value
                        if result.error is not None
                        else None
                    ),
                    "safe_details": _tool_error_safe_details(result),
                }
            )
        return (
            "Recent Tool Results\n"
            "Use these tool results as evidence for the next single decision. "
            "Do not repeat a successful read-only tool call unless a different "
            "specific target is required.\n"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )

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
            "input_payload_summary": _safe_tool_input_payload_summary(
                decision.tool_call.input_payload if decision.tool_call is not None else {}
            ),
            "decision_trace_ref": decision.decision_trace.trace_ref,
            "iteration_index": iteration_index,
        }


def _tool_error_safe_details(tool_result: ToolResult) -> dict[str, object]:
    if tool_result.error is None:
        return {}
    return dict(tool_result.error.safe_details)


def _mapping_records(value: object) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _tool_risk_level_from_value(value: object) -> ToolRiskLevel | None:
    if isinstance(value, ToolRiskLevel):
        return value
    if not isinstance(value, str):
        return None
    try:
        return ToolRiskLevel(value)
    except ValueError:
        return None


def _tool_risk_categories_from_value(value: object) -> list[ToolRiskCategory]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    categories: list[ToolRiskCategory] = []
    for item in value:
        if isinstance(item, ToolRiskCategory):
            category = item
        elif isinstance(item, str):
            try:
                category = ToolRiskCategory(item)
            except ValueError:
                continue
        else:
            continue
        if category not in categories:
            categories.append(category)
    return categories


def _confirmation_object_ref(
    *,
    tool_name: str,
    call_id: str,
    input_digest: str,
) -> str:
    return f"tool-call:{tool_name}:{call_id}:{input_digest[:12]}"


def _evidence_policy_for_artifact(
    artifact_type: str,
    *,
    allowed_tools: tuple[str, ...] | None,
) -> _StageArtifactEvidencePolicy | None:
    if artifact_type == "CodeGenerationArtifact":
        policy = _StageArtifactEvidencePolicy(
            artifact_type=artifact_type,
            payload_field="file_edit_trace_refs",
            tool_names=("write_file", "edit_file"),
            ref_prefix="file_edit_trace:",
        )
    elif artifact_type == "TestGenerationExecutionArtifact":
        policy = _StageArtifactEvidencePolicy(
            artifact_type=artifact_type,
            payload_field="command_trace_refs",
            tool_names=("bash",),
            ref_prefix="command_trace:",
        )
    else:
        return None

    if allowed_tools is None:
        return None
    if not any(tool_name in allowed_tools for tool_name in policy.tool_names):
        return None
    return policy


def _allowed_tool_names(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        names = tuple(item for item in value if isinstance(item, str) and item)
        return names
    return None


def _stage_artifact_type(request: StageExecutionRequest) -> str | None:
    contract = request.graph_definition.stage_contracts[request.invocation.stage_type.value]
    artifact_type = contract.get("structured_artifact_required")
    if isinstance(artifact_type, str) and artifact_type:
        return artifact_type
    return None


def _base_response_schema_decision_types(
    request: StageExecutionRequest,
) -> tuple[AgentDecisionType, ...]:
    contract = request.graph_definition.stage_contracts[request.invocation.stage_type.value]
    decision_types: tuple[AgentDecisionType, ...] = (
        AgentDecisionType.REQUEST_TOOL_CONFIRMATION,
        AgentDecisionType.SUBMIT_STAGE_ARTIFACT,
        AgentDecisionType.RETRY_WITH_REVISED_PLAN,
        AgentDecisionType.FAIL_STAGE,
    )
    if (
        contract.get("clarification_allowed") is True
        or contract.get("can_request_clarification") is True
    ):
        decision_types = (
            AgentDecisionType.REQUEST_TOOL_CONFIRMATION,
            AgentDecisionType.SUBMIT_STAGE_ARTIFACT,
            AgentDecisionType.REQUEST_CLARIFICATION,
            AgentDecisionType.RETRY_WITH_REVISED_PLAN,
            AgentDecisionType.FAIL_STAGE,
        )
    return decision_types


def _successful_side_effect_refs(
    tool_results: Sequence[ToolResult],
    *,
    tool_names: tuple[str, ...],
    ref_prefix: str,
) -> tuple[str, ...]:
    refs: list[str] = []
    for result in tool_results:
        if result.status is not ToolResultStatus.SUCCEEDED:
            continue
        if result.tool_name not in tool_names:
            continue
        refs.extend(
            ref
            for ref in result.side_effect_refs
            if isinstance(ref, str) and ref.startswith(ref_prefix)
        )
    return _dedupe_strings(refs)


def _dedupe_strings(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _stage_artifact_semantic_violation(
    request: StageExecutionRequest,
    stage_artifact: object,
) -> dict[str, object] | None:
    artifact_type = getattr(stage_artifact, "artifact_type", None)
    payload = getattr(stage_artifact, "artifact_payload", None)
    if not isinstance(artifact_type, str) or not isinstance(payload, Mapping):
        return None
    if (
        request.invocation.stage_type is StageType.SOLUTION_DESIGN
        and artifact_type == "SolutionDesignArtifact"
    ):
        return _solution_design_semantic_violation(request, payload)
    if (
        request.invocation.stage_type is StageType.CODE_GENERATION
        and artifact_type == "CodeGenerationArtifact"
    ):
        return _code_generation_artifact_semantic_violation(request, payload)
    return None


def _repairable_decision_type_from_parser_error(
    request: StageExecutionRequest,
    exc: AgentDecisionParserError,
) -> AgentDecisionType | None:
    del request
    if exc.error.error_code is not AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT:
        return None
    decision_type = exc.error.decision_trace.decision_type
    if decision_type in {
        AgentDecisionType.SUBMIT_STAGE_ARTIFACT,
        AgentDecisionType.REQUEST_TOOL_CONFIRMATION,
        AgentDecisionType.REQUEST_CLARIFICATION,
        AgentDecisionType.RETRY_WITH_REVISED_PLAN,
        AgentDecisionType.FAIL_STAGE,
    }:
        return decision_type
    return None


def _solution_design_semantic_violation(
    request: StageExecutionRequest,
    payload: Mapping[str, object],
) -> dict[str, object] | None:
    if not _non_empty_string_refs(payload.get("requirement_refs")):
        return {
            "semantic_rule": "solution_design_requirement_refs_required",
            "artifact_type": "SolutionDesignArtifact",
        }
    if not _implementation_plan_has_actionable_steps(payload.get("implementation_plan")):
        return {
            "semantic_rule": "solution_design_implementation_plan_required",
            "artifact_type": "SolutionDesignArtifact",
        }
    if not _objective_targets_homepage_copy(request.task_objective):
        return None

    plan_text = _flatten_text(
        (
            payload.get("technical_plan"),
            payload.get("implementation_plan"),
            payload.get("impacted_files"),
            payload.get("test_strategy"),
            payload.get("validation_report"),
        )
    )
    if _text_mentions_homepage_target(plan_text):
        return None
    return {
        "semantic_rule": "solution_design_unrelated_to_homepage_requirement",
        "artifact_type": "SolutionDesignArtifact",
        "required_target": "homepage",
    }


def _code_generation_artifact_semantic_violation(
    request: StageExecutionRequest,
    payload: Mapping[str, object],
) -> dict[str, object] | None:
    expected_files = _solution_design_target_files(request.stage_artifacts)
    changed_files = _string_tuple(payload.get("changed_files"))
    if not expected_files or not changed_files:
        return None
    expected = {_normalize_path_for_semantics(path) for path in expected_files}
    unexpected = [
        path
        for path in changed_files
        if _normalize_path_for_semantics(path) not in expected
    ]
    if not unexpected:
        return None
    return {
        "semantic_rule": "code_generation_changed_files_outside_solution_boundary",
        "artifact_type": "CodeGenerationArtifact",
        "unexpected_files": unexpected,
        "expected_files": sorted(expected_files),
    }


def _control_decision_semantic_violation(
    request: StageExecutionRequest,
    decision: AgentDecision,
) -> dict[str, object] | None:
    if (
        request.invocation.stage_type is not StageType.CODE_GENERATION
        or decision.fail_stage is None
    ):
        return None
    if not _text_claims_missing_file(decision.fail_stage.failure_reason):
        return None
    target_files = _solution_design_target_files(request.stage_artifacts)
    if not target_files and not _objective_targets_homepage_copy(request.task_objective):
        return None
    if _has_missing_file_tool_evidence(decision.fail_stage.evidence_refs):
        return None
    return {
        "semantic_rule": "code_generation_missing_file_failure_without_evidence",
        "artifact_type": "CodeGenerationArtifact",
        "known_target_files": sorted(target_files),
    }


def _solution_design_target_files(stage_artifacts: Sequence[object]) -> set[str]:
    files: set[str] = set()
    for payload in _solution_design_payloads(stage_artifacts):
        files.update(_string_tuple(payload.get("impacted_files")))
        implementation_plan = payload.get("implementation_plan")
        if isinstance(implementation_plan, Mapping):
            tasks = implementation_plan.get("tasks")
            if isinstance(tasks, Sequence) and not isinstance(tasks, str):
                for task in tasks:
                    if isinstance(task, Mapping):
                        files.update(_string_tuple(task.get("target_files")))
        elif isinstance(implementation_plan, Sequence) and not isinstance(
            implementation_plan,
            str,
        ):
            for item in implementation_plan:
                files.update(_path_like_strings(item))
        else:
            files.update(_path_like_strings(implementation_plan))
    return {
        path
        for path in files
        if "/" in path or "\\" in path or path.lower().endswith((".py", ".tsx", ".ts"))
    }


def _solution_design_payloads(
    stage_artifacts: Sequence[object],
) -> tuple[Mapping[str, object], ...]:
    payloads: list[Mapping[str, object]] = []
    for artifact in stage_artifacts:
        direct_payload = getattr(artifact, "payload", None)
        if isinstance(direct_payload, Mapping) and (
            getattr(artifact, "artifact_type", None) == "SolutionDesignArtifact"
            or "implementation_plan" in direct_payload
        ):
            payloads.append(direct_payload)
        process = getattr(artifact, "process", None)
        if not isinstance(process, Mapping):
            continue
        output_snapshot = process.get("output_snapshot")
        if isinstance(output_snapshot, Mapping):
            artifact_type = output_snapshot.get("artifact_type")
            artifact_payload = output_snapshot.get("artifact_payload")
            if (
                artifact_type == "SolutionDesignArtifact"
                and isinstance(artifact_payload, Mapping)
            ):
                payloads.append(artifact_payload)
        legacy_payload = process.get("solution_design_artifact")
        if isinstance(legacy_payload, Mapping):
            payloads.append(legacy_payload)
    return tuple(payloads)


def _implementation_plan_has_actionable_steps(value: object) -> bool:
    if isinstance(value, Mapping):
        tasks = value.get("tasks")
        return isinstance(tasks, Sequence) and not isinstance(tasks, str) and bool(tasks)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Sequence):
        return any(isinstance(item, object) and _flatten_text(item) for item in value)
    return False


def _objective_targets_homepage_copy(task_objective: str) -> bool:
    text = task_objective.lower()
    return any(
        token in text
        for token in (
            "homepage",
            "home page",
            "homepage.tsx",
            "官网",
            "主页面",
            "make delivery work",
        )
    )


def _text_mentions_homepage_target(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "homepage",
            "home page",
            "homepage.tsx",
            "frontend/src/pages",
            "官网",
            "主页面",
            "make delivery work",
        )
    )


def _text_claims_missing_file(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("missing", "not found", "unavailable")) and any(
        token in lowered for token in ("file", "path", "target", "文件")
    )


def _has_missing_file_tool_evidence(evidence_refs: Sequence[str]) -> bool:
    return any(
        "read_file" in ref
        or "tool-result://" in ref
        or "tool_trace" in ref
        or "file_read" in ref
        for ref in evidence_refs
    )


def _non_empty_string_refs(value: object) -> tuple[str, ...]:
    return tuple(item for item in _string_tuple(value) if item.strip())


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, Sequence):
        return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ()


def _path_like_strings(value: object) -> tuple[str, ...]:
    text = _flatten_text(value)
    if not text:
        return ()
    candidates = []
    for raw in text.replace(",", " ").split():
        token = raw.strip("`'\".()[]{}")
        if "/" in token or "\\" in token or token.lower().endswith((".py", ".tsx", ".ts")):
            candidates.append(token)
    return tuple(candidates)


def _normalize_path_for_semantics(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def _flatten_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


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


def _safe_tool_input_payload_summary(payload: Mapping[str, object]) -> dict[str, object]:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    summary: dict[str, object] = {
        "input_keys": sorted(str(key) for key in payload),
        "payload_size_bytes": len(encoded.encode("utf-8")),
        "redaction_status": "summary_only",
    }
    for key in (
        "path",
        "pattern",
        "glob",
        "query",
        "command",
        "argv",
        "cwd",
        "old_path",
        "new_path",
        "old_text",
        "new_text",
    ):
        if key not in payload or _is_sensitive_input_key(key):
            continue
        value = payload[key]
        if isinstance(value, str):
            summary[key] = _redact_inline_secret_text(_bounded_string(value, limit=500))
        elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
            summary[key] = [
                _redact_inline_secret_text(_bounded_string(str(item), limit=200))
                for item in value[:20]
            ]
        elif isinstance(value, int | float | bool) or value is None:
            summary[key] = value
    return summary


def _is_sensitive_input_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        token in lowered
        for token in (
            "api_key",
            "authorization",
            "bearer",
            "content",
            "password",
            "secret",
            "token",
        )
    )


def _redact_inline_secret_text(value: str) -> str:
    lowered = value.lower()
    for marker in ("bearer ", "api_key=", "token=", "password=", "secret="):
        index = lowered.find(marker)
        if index == -1:
            continue
        return f"{value[: index + len(marker)]}[redacted]"
    return value


def _bounded_string(value: str, *, limit: int = 200) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


__all__ = [
    "StageAgentRuntime",
    "StageExecutionRequest",
    "StageRecoveryCursor",
]
