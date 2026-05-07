from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from backend.app.context.builder import ContextBuildRequest
from backend.app.context.schemas import ContextEnvelope
from backend.app.domain.enums import (
    ApprovalType,
    ProviderProtocolType,
    ProviderSource,
    StageStatus,
    StageType,
    TemplateSource,
    ToolRiskLevel,
)
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.runtime_refs import GraphThreadRef, GraphThreadStatus
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.prompts.renderer import PromptRenderedMessage
from backend.app.providers.langchain_adapter import (
    ModelCallResult,
    ModelCallToolRequest,
    ModelCallTraceSummary,
    ModelCallUsage,
)
from backend.app.runtime.agent_decision import AgentDecisionParser
from backend.app.runtime.base import RuntimeExecutionContext
from backend.app.runtime.stage_runner_port import StageNodeInvocation
from backend.app.schemas.prompts import ModelCallType
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    ModelBindingSnapshotRead,
    RuntimeLimitSnapshotRead,
    SnapshotModelRuntimeCapabilities,
)
from backend.app.services.artifacts import ArtifactStoreError
from backend.app.tools.execution_gate import ToolExecutionContext, ToolExecutionRequest
from backend.app.tools.protocol import (
    ToolBindableDescription,
    ToolError,
    ToolResult,
    ToolResultStatus,
)


NOW = datetime(2026, 5, 4, 18, 0, tzinfo=UTC)


class FakeContextBuilder:
    def __init__(self, envelope: ContextEnvelope) -> None:
        self.envelope = envelope
        self.requests: list[ContextBuildRequest] = []

    def build_for_stage_call(self, request: ContextBuildRequest) -> object:
        self.requests.append(request)
        return SimpleNamespace(
            envelope=self.envelope.model_copy(
                update={
                    "model_call_type": request.model_call_type,
                    "response_schema": dict(request.response_schema),
                    "trace_context": request.trace_context,
                }
            ),
            manifest=SimpleNamespace(model_dump=lambda mode="json": {"manifest": "ok"}),
            rendered_messages=(
                PromptRenderedMessage(role="system", content="runtime"),
                PromptRenderedMessage(role="user", content="task"),
            ),
            rendered_output_ref=(
                "artifact://context-envelopes/run-1/stage-run-1/"
                f"{request.model_call_type.value}"
            ),
            render_hash="0" * 64,
            prompt_render_result=None,
        )


class FakeProviderAdapter:
    def __init__(self, results: Sequence[ModelCallResult]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def invoke_with_retry(self, **kwargs: Any) -> ModelCallResult:
        self.calls.append(kwargs)
        if not self._results:
            raise AssertionError("No provider result configured")
        return self._results.pop(0)


class FakeToolRegistry:
    def __init__(self, results: Sequence[ToolResult]) -> None:
        self._results = list(results)
        self.execute_calls: list[
            dict[str, ToolExecutionRequest | ToolExecutionContext]
        ] = []

    def execute(
        self,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
    ) -> ToolResult:
        self.execute_calls.append({"request": request, "context": context})
        if not self._results:
            raise AssertionError("No tool result configured")
        return self._results.pop(0)


class FakeArtifactStore:
    def __init__(self) -> None:
        self.process: dict[str, Any] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.append_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []

    def create_stage_input(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        artifact_id: str,
        artifact_type: str,
        payload_ref: str,
        input_snapshot: dict[str, Any],
        input_refs: Sequence[str] | None,
        trace_context: TraceContext,
    ) -> object:
        self.create_calls.append(
            {
                "run_id": run_id,
                "stage_run_id": stage_run_id,
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "payload_ref": payload_ref,
                "input_snapshot": input_snapshot,
                "input_refs": list(input_refs or []),
                "trace_context": trace_context,
            }
        )
        return SimpleNamespace(artifact_id=artifact_id, payload_ref=payload_ref)

    def get_stage_artifact(
        self,
        artifact_id: str,
        *,
        trace_context: TraceContext | None = None,
        log_missing_failure: bool = True,
    ) -> object:
        self.get_calls.append(
            {
                "artifact_id": artifact_id,
                "trace_context": trace_context,
                "log_missing_failure": log_missing_failure,
            }
        )
        if self.create_calls and self.create_calls[-1]["artifact_id"] == artifact_id:
            return SimpleNamespace(artifact_id=artifact_id)
        raise ArtifactStoreError("Stage artifact was not found.")

    def append_process_record(
        self,
        *,
        artifact_id: str,
        process_key: str,
        process_value: Any,
        trace_context: TraceContext,
    ) -> object:
        if not self.create_calls or self.create_calls[-1]["artifact_id"] != artifact_id:
            raise AssertionError("append_process_record called before stage input exists")
        self.append_calls.append(
            {
                "artifact_id": artifact_id,
                "process_key": process_key,
                "process_value": process_value,
                "trace_context": trace_context,
            }
        )
        self.process[process_key] = process_value
        return SimpleNamespace(artifact_id=artifact_id, process=dict(self.process))

    def complete_stage_output(
        self,
        *,
        artifact_id: str,
        payload_ref: str,
        output_snapshot: dict[str, Any],
        output_refs: Sequence[str] | None,
        trace_context: TraceContext,
    ) -> object:
        self.complete_calls.append(
            {
                "artifact_id": artifact_id,
                "payload_ref": payload_ref,
                "output_snapshot": output_snapshot,
                "output_refs": list(output_refs or []),
                "trace_context": trace_context,
            }
        )
        return SimpleNamespace(artifact_id=artifact_id, payload_ref=payload_ref)

    def append_keys(self) -> list[str]:
        return [str(call["process_key"]) for call in self.append_calls]


def build_runtime(
    *,
    provider_results: Sequence[ModelCallResult],
    tool_results: Sequence[ToolResult] = (),
    allowed_tools: Sequence[str] = ("read_file",),
    available_tools: tuple[ToolBindableDescription, ...] | None = None,
    model_binding_snapshot: ModelBindingSnapshotRead | None = None,
    requested_max_output_tokens: int | None = 100,
    stage_artifacts: Sequence[Any] = (),
    context_references: Sequence[Any] = (),
    change_sets: Sequence[Any] = (),
    clarifications: Sequence[Any] = (),
    approval_decisions: Sequence[Any] = (),
    progress_callback: Any | None = None,
) -> Any:
    from backend.app.runtime.stage_agent import StageAgentRuntime

    resolved_tools = (
        tuple(available_tools)
        if available_tools is not None
        else (read_file_description(),)
    )
    context_builder = FakeContextBuilder(
        context_envelope(available_tools=resolved_tools)
    )
    provider_adapter = FakeProviderAdapter(provider_results)
    tool_registry = FakeToolRegistry(tool_results)
    artifact_store = FakeArtifactStore()
    runtime = StageAgentRuntime(
        context_builder=context_builder,
        provider_adapter=provider_adapter,
        decision_parser=AgentDecisionParser(),
        tool_registry=tool_registry,
        artifact_store=artifact_store,
        stage_artifact_id="artifact-stage-run-1",
        template_snapshot=template_snapshot(),
        graph_definition=graph_definition(allowed_tools=allowed_tools),
        runtime_limit_snapshot=runtime_limits(),
        provider_snapshot=provider_snapshot(),
        model_binding_snapshot=model_binding_snapshot or model_binding(),
        task_objective="Implement the assigned runtime slice.",
        specified_action="Return a structured stage decision.",
        response_schema={"type": "object", "properties": {}},
        output_schema_ref="schema://agent-decision",
        requested_max_output_tokens=requested_max_output_tokens,
        stage_artifacts=stage_artifacts,
        context_references=context_references,
        change_sets=change_sets,
        clarifications=clarifications,
        approval_decisions=approval_decisions,
        progress_callback=progress_callback,
        now=lambda: NOW,
    )
    runtime.context_builder = context_builder
    runtime.provider_adapter = provider_adapter
    runtime.tool_registry = tool_registry
    runtime.artifact_store = artifact_store
    return runtime


def invocation() -> StageNodeInvocation:
    return StageNodeInvocation(
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        graph_node_key="code_generation",
        stage_contract_ref="stage-contract-code_generation",
        runtime_context=runtime_context(),
        trace_context=trace_context(),
    )


def runtime_context() -> RuntimeExecutionContext:
    return RuntimeExecutionContext(
        run_id="run-1",
        session_id="session-1",
        thread=GraphThreadRef(
            thread_id="graph-thread-1",
            run_id="run-1",
            status=GraphThreadStatus.RUNNING,
            current_stage_run_id="stage-run-1",
            current_stage_type=StageType.CODE_GENERATION,
        ),
        trace_context=trace_context(stage_run_id=None),
        template_snapshot_ref="template-snapshot-run-1",
        provider_snapshot_refs=["provider-snapshot-run-1"],
        model_binding_snapshot_refs=["model-binding-snapshot-run-1"],
        runtime_limit_snapshot_ref="runtime-limit-snapshot-run-1",
        provider_call_policy_snapshot_ref="provider-call-policy-snapshot-run-1",
        graph_definition_ref="graph-definition-run-1",
        workspace_snapshot_ref="workspace-snapshot-run-1",
    )


def trace_context(*, stage_run_id: str | None = "stage-run-1") -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="span-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id=stage_run_id,
        graph_thread_id="graph-thread-1",
        created_at=NOW,
    )


def context_envelope(
    *,
    available_tools: tuple[ToolBindableDescription, ...],
) -> ContextEnvelope:
    return ContextEnvelope(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        template_snapshot_ref="template-snapshot-run-1",
        stage_contract_ref="stage-contract-code_generation",
        provider_snapshot_ref="provider-snapshot-run-1",
        model_binding_snapshot_ref="model-binding-snapshot-run-1",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        runtime_instructions=(),
        stage_contract=(),
        agent_role_prompt=(),
        task_objective=(),
        specified_action=(),
        input_artifact_refs=(),
        context_references=(),
        working_observations=(),
        reasoning_trace=(),
        available_tools=available_tools,
        recent_observations=(),
        response_schema={"type": "object"},
        trace_context=trace_context(),
        built_at=NOW,
    )


def model_result(
    *,
    structured_output: dict[str, Any] | None = None,
    tool_call_requests: tuple[ModelCallToolRequest, ...] = (),
    provider_retry_trace: tuple[Any, ...] = (),
    provider_circuit_breaker_trace: tuple[Any, ...] = (),
) -> ModelCallResult:
    return ModelCallResult(
        provider_snapshot_id="provider-snapshot-run-1",
        model_binding_snapshot_id="model-binding-snapshot-run-1",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        structured_output=structured_output,
        tool_call_requests=tool_call_requests,
        usage=ModelCallUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        raw_response_ref=f"stage-process://stage-run-1/model-call/{id(structured_output)}",
        native_reasoning_ref="sha256:native-reasoning",
        provider_retry_trace=provider_retry_trace,
        provider_circuit_breaker_trace=provider_circuit_breaker_trace,
        trace_summary=ModelCallTraceSummary(
            request_id="request-1",
            trace_id="trace-1",
            correlation_id="correlation-1",
            span_id="span-provider-1",
            parent_span_id="span-iteration-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            provider_snapshot_id="provider-snapshot-run-1",
            model_binding_snapshot_id="model-binding-snapshot-run-1",
            model_call_type=ModelCallType.STAGE_EXECUTION,
            input_summary={"content_hash": "sha256:input"},
            output_summary={"content_hash": "sha256:output"},
        ),
    )


def read_file_call(call_id: str) -> ModelCallToolRequest:
    return ModelCallToolRequest(
        call_id=call_id,
        tool_name="read_file",
        input_payload={"path": "backend/app/runtime/nodes.py"},
        schema_version="tool-schema-v1",
    )


def write_file_call(call_id: str) -> ModelCallToolRequest:
    return ModelCallToolRequest(
        call_id=call_id,
        tool_name="write_file",
        input_payload={"path": "backend/app/runtime/stage_agent.py", "content": "x"},
        schema_version="tool-schema-v1",
    )


def succeeded_tool_result(call_id: str) -> ToolResult:
    return ToolResult(
        tool_name="read_file",
        call_id=call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={"content_ref": "tool-result://call-1/content"},
        artifact_refs=["tool-result://call-1"],
        trace_context=trace_context(),
        coordination_key=f"stage-run-1:{call_id}",
    )


def waiting_confirmation_tool_result(call_id: str) -> ToolResult:
    error = ToolError.from_code(
        "tool_confirmation_required",
        trace_context=trace_context(),
        safe_details={"risk_level": "high_risk", "target_summary": "stage_agent.py"},
    )
    return ToolResult(
        tool_name="write_file",
        call_id=call_id,
        status=ToolResultStatus.WAITING_CONFIRMATION,
        error=error,
        tool_confirmation_ref="tool-confirmation-1",
        trace_context=trace_context(),
        coordination_key=f"stage-run-1:{call_id}",
    )


def succeeded_write_file_result(call_id: str) -> ToolResult:
    return ToolResult(
        tool_name="write_file",
        call_id=call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={"content_ref": f"tool-result://{call_id}/content"},
        artifact_refs=[f"tool-result://{call_id}"],
        trace_context=trace_context(),
        coordination_key=f"stage-run-1:{call_id}",
    )


def read_file_description() -> ToolBindableDescription:
    return ToolBindableDescription(
        name="read_file",
        description="Read a file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"content_ref": {"type": "string"}},
            "required": ["content_ref"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.READ_ONLY,
        risk_categories=[],
        schema_version="tool-schema-v1",
    )


def write_file_description() -> ToolBindableDescription:
    return ToolBindableDescription(
        name="write_file",
        description="Write a file.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"content_ref": {"type": "string"}},
            "required": ["content_ref"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.HIGH_RISK,
        risk_categories=[],
        schema_version="tool-schema-v1",
    )


def code_generation_payload() -> dict[str, Any]:
    return {
        "changeset_ref": "changeset://run-1/code-generation/1",
        "changed_files": ["backend/app/runtime/stage_agent.py"],
        "diff_refs": ["diff://run-1/code-generation/1"],
        "file_edit_trace_refs": ["file-edit://run-1/stage-agent"],
        "implementation_notes": "Implemented runtime loop.",
        "requirement_refs": ["requirement://run-1/1"],
        "solution_refs": ["solution://run-1/1"],
    }


def graph_definition(
    *,
    allowed_tools: Sequence[str] = ("read_file",),
    skip_high_risk_tool_confirmations: bool = False,
    can_request_clarification: bool = False,
) -> GraphDefinition:
    stage_contracts: dict[str, dict[str, Any]] = {
        stage.value: {
            "stage_type": stage.value,
            "stage_contract_ref": f"stage-contract-{stage.value}",
            "stage_responsibility": stage.value,
            "input_contract": {"requires": []},
            "output_contract": "CodeGenerationArtifact",
            "structured_artifact_required": "CodeGenerationArtifact",
            "allowed_tools": list(allowed_tools)
            if stage is StageType.CODE_GENERATION
            else [],
            "runtime_limits": {
                "skip_high_risk_tool_confirmations": skip_high_risk_tool_confirmations
            },
            "can_request_clarification": (
                can_request_clarification if stage is StageType.CODE_GENERATION else False
            ),
        }
        for stage in StageType
    }
    return GraphDefinition(
        graph_definition_id="graph-definition-run-1",
        run_id="run-1",
        template_snapshot_ref="template-snapshot-run-1",
        runtime_limit_snapshot_ref="runtime-limit-snapshot-run-1",
        runtime_limit_source_config_version="runtime-settings-v1",
        stage_nodes=tuple(
            {"node_key": stage.value, "stage_type": stage.value}
            for stage in StageType
        ),
        stage_contracts=stage_contracts,
        interrupt_policy={"approval_interrupts": []},
        retry_policy={"max_auto_regression_retries": 2},
        delivery_routing_policy={"stage": "delivery_integration"},
        source_node_group_map={stage.value: stage.value for stage in StageType},
        created_at=NOW,
    )


def template_snapshot() -> TemplateSnapshot:
    return TemplateSnapshot(
        snapshot_ref="template-snapshot-run-1",
        run_id="run-1",
        source_template_id="template-1",
        source_template_name="Function One",
        source_template=TemplateSource.SYSTEM_TEMPLATE,
        source_template_updated_at=NOW,
        fixed_stage_sequence=tuple(StageType),
        stage_role_bindings=tuple(
            StageRoleSnapshot(
                stage_type=stage,
                role_id=f"role-{stage.value}",
                system_prompt=f"Role prompt for {stage.value}.",
                provider_id="provider-openai",
            )
            for stage in StageType
        ),
        approval_checkpoints=(
            ApprovalType.SOLUTION_DESIGN_APPROVAL,
            ApprovalType.CODE_REVIEW_APPROVAL,
        ),
        auto_regression_enabled=True,
        max_auto_regression_retries=2,
        max_react_iterations_per_stage=30,
        max_tool_calls_per_stage=80,
        skip_high_risk_tool_confirmations=False,
        created_at=NOW,
    )


def capabilities(
    *,
    supports_tool_calling: bool = True,
    supports_structured_output: bool = True,
    max_output_tokens: int = 200,
) -> SnapshotModelRuntimeCapabilities:
    return SnapshotModelRuntimeCapabilities(
        model_id="gpt-5",
        context_window_tokens=1000,
        max_output_tokens=max_output_tokens,
        supports_tool_calling=supports_tool_calling,
        supports_structured_output=supports_structured_output,
        supports_native_reasoning=True,
    )


def provider_snapshot() -> ProviderSnapshot:
    return ProviderSnapshot(
        snapshot_id="provider-snapshot-run-1",
        run_id="run-1",
        provider_id="provider-openai",
        display_name="OpenAI",
        provider_source=ProviderSource.CUSTOM,
        protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url="https://api.openai.test",
        api_key_ref="env:OPENAI_API_KEY",
        model_id="gpt-5",
        is_default_model=True,
        capabilities=capabilities(),
        source_config_version="provider-config-v1",
        created_at=NOW,
    )


def model_binding(
    *,
    supports_tool_calling: bool = True,
    supports_structured_output: bool = True,
    max_output_tokens: int = 200,
) -> ModelBindingSnapshotRead:
    return ModelBindingSnapshotRead(
        snapshot_id="model-binding-snapshot-run-1",
        run_id="run-1",
        binding_id="agent_role:code_generation:role-code_generation",
        binding_type="agent_role",
        stage_type=StageType.CODE_GENERATION,
        role_id="role-code_generation",
        provider_snapshot_id="provider-snapshot-run-1",
        provider_id="provider-openai",
        model_id="gpt-5",
        capabilities=capabilities(
            supports_tool_calling=supports_tool_calling,
            supports_structured_output=supports_structured_output,
            max_output_tokens=max_output_tokens,
        ),
        model_parameters={},
        source_config_version="template-binding-v1",
        schema_version="model-binding-snapshot-v1",
        created_at=NOW,
    )


def runtime_limits() -> RuntimeLimitSnapshotRead:
    return RuntimeLimitSnapshotRead(
        snapshot_id="runtime-limit-snapshot-run-1",
        run_id="run-1",
        agent_limits=AgentRuntimeLimits(
            max_react_iterations_per_stage=4,
            max_tool_calls_per_stage=2,
            max_structured_output_repair_attempts=1,
        ),
        context_limits=ContextLimits(),
        source_config_version="runtime-settings-v1",
        hard_limits_version="platform-hard-limits-v1",
        schema_version="runtime-limit-snapshot-v1",
        created_at=NOW,
    )


def test_stage_agent_submits_stage_artifact_through_existing_artifact_store() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": code_generation_payload(),
                    "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
                }
            )
        ]
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.COMPLETED
    assert result.artifact_refs == ["artifact-stage-run-1"]
    assert runtime.artifact_store.complete_calls[0]["artifact_id"] == (
        "artifact-stage-run-1"
    )
    assert runtime.artifact_store.complete_calls[0]["payload_ref"] == (
        "stage-artifact://artifact-stage-run-1/output"
    )
    assert runtime.artifact_store.append_keys() == [
        "stage_agent_started",
        "model_call_trace",
        "decision_trace",
        "recovery_checkpoint",
    ]


def test_stage_agent_executes_tool_decision_through_tool_registry_and_continues() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(tool_call_requests=(read_file_call("call-1"),)),
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": code_generation_payload(),
                    "evidence_refs": ["tool-result://call-1"],
                }
            ),
        ],
        tool_results=[succeeded_tool_result("call-1")],
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.COMPLETED
    assert runtime.tool_registry.execute_calls[0]["request"].tool_name == "read_file"
    assert runtime.tool_registry.execute_calls[0]["context"].allowed_tools == (
        "read_file",
    )
    assert "tool_trace" in runtime.artifact_store.append_keys()


def test_stage_agent_passes_template_tool_confirmation_skip_policy_to_tool_context() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(tool_call_requests=(read_file_call("call-1"),)),
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": code_generation_payload(),
                    "evidence_refs": ["tool-result://call-1"],
                }
            ),
        ],
        tool_results=[succeeded_tool_result("call-1")],
        allowed_tools=["read_file"],
    )
    runtime._graph_definition = graph_definition(
        allowed_tools=["read_file"],
        skip_high_risk_tool_confirmations=True,
    )

    runtime.run_stage(invocation())

    assert (
        runtime.tool_registry.execute_calls[0][
            "context"
        ].skip_high_risk_tool_confirmations
        is True
    )


def test_stage_agent_high_risk_tool_result_waits_for_confirmation_without_completing_stage() -> None:
    runtime = build_runtime(
        provider_results=[model_result(tool_call_requests=(write_file_call("call-1"),))],
        tool_results=[waiting_confirmation_tool_result("call-1")],
        allowed_tools=["write_file"],
        available_tools=(write_file_description(),),
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.WAITING_TOOL_CONFIRMATION
    assert result.route_key == "waiting_tool_confirmation"
    assert "tool_confirmation_trace" in runtime.artifact_store.append_keys()
    assert "recovery_checkpoint" in runtime.artifact_store.append_keys()
    assert runtime.artifact_store.complete_calls == []


def test_stage_agent_persists_structured_clarification_request_before_waiting() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "request_clarification",
                    "question": "Which runtime module should handle dispatch?",
                    "missing_facts": ["runtime dispatcher owner"],
                    "impact_scope": "Production run execution",
                    "related_refs": ["message://run-1/requirement"],
                    "fields_to_update": ["structured_requirement"],
                }
            )
        ],
    )
    runtime._graph_definition = graph_definition(
        allowed_tools=(),
        can_request_clarification=True,
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.WAITING_CLARIFICATION
    assert result.route_key == "waiting_clarification"
    clarification = runtime.artifact_store.process["clarification_request"]
    assert clarification["question"] == "Which runtime module should handle dispatch?"
    assert clarification["missing_facts"] == ["runtime dispatcher owner"]
    assert clarification["decision_trace_ref"].startswith("agent-decision-trace-")
    assert runtime.artifact_store.complete_calls == []


def test_stage_agent_skips_structured_high_risk_tool_confirmation_when_template_allows() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "request_tool_confirmation",
                    "tool_name": "write_file",
                    "command_summary": "Write backend/app/runtime/stage_agent.py",
                    "target_resource": "backend/app/runtime/stage_agent.py",
                    "risk_level": "high_risk",
                    "risk_categories": ["broad_write"],
                    "expected_side_effects": [
                        "Modify backend/app/runtime/stage_agent.py"
                    ],
                    "alternative_path_summary": "Ask for a manual patch instead.",
                    "input_payload": {
                        "path": "backend/app/runtime/stage_agent.py",
                        "content": "x",
                    },
                }
            ),
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": code_generation_payload(),
                    "evidence_refs": ["tool-result://tool-confirmation-decision-1"],
                }
            ),
        ],
        tool_results=[succeeded_write_file_result("tool-confirmation-decision-1")],
        allowed_tools=["write_file"],
        available_tools=(write_file_description(),),
    )
    runtime._graph_definition = graph_definition(
        allowed_tools=["write_file"],
        skip_high_risk_tool_confirmations=True,
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.COMPLETED
    assert runtime.tool_registry.execute_calls[0]["request"].tool_name == "write_file"
    assert (
        runtime.tool_registry.execute_calls[0][
            "context"
        ].skip_high_risk_tool_confirmations
        is True
    )
    trace = runtime.artifact_store.process["tool_confirmation_trace"]
    assert trace["status"] == "skipped"
    assert trace["skip_high_risk_tool_confirmations"] is True
    assert runtime.artifact_store.complete_calls


def test_stage_agent_rejects_tool_call_when_model_binding_lacks_tool_calling() -> None:
    runtime = build_runtime(
        provider_results=[],
        available_tools=(read_file_description(),),
        model_binding_snapshot=model_binding(supports_tool_calling=False),
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.FAILED
    assert "stage_agent_failed" in runtime.artifact_store.append_keys()
    assert runtime.provider_adapter.calls == []


def test_stage_agent_creates_stage_input_before_process_records() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": code_generation_payload(),
                    "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
                }
            )
        ]
    )

    runtime.run_stage(invocation())

    assert runtime.artifact_store.create_calls[0]["artifact_id"] == (
        "artifact-stage-run-1"
    )
    assert runtime.artifact_store.create_calls[0]["payload_ref"] == (
        "stage-artifact://artifact-stage-run-1/input"
    )
    assert runtime.artifact_store.append_calls[0]["process_key"] == (
        "stage_agent_started"
    )


def test_stage_agent_passes_invocation_trace_to_stage_artifact_lookup() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": code_generation_payload(),
                    "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
                }
            )
        ]
    )
    request = invocation()

    runtime.run_stage(request)

    assert runtime.artifact_store.get_calls[0]["artifact_id"] == (
        "artifact-stage-run-1"
    )
    assert runtime.artifact_store.get_calls[0]["trace_context"] is (
        request.trace_context
    )
    assert runtime.artifact_store.get_calls[0]["log_missing_failure"] is False


def test_stage_agent_passes_context_sources_to_context_builder() -> None:
    stage_artifact = SimpleNamespace(artifact_id="previous-artifact")
    context_reference = SimpleNamespace(reference_id="context-reference-1")
    change_set = SimpleNamespace(change_set_id="changeset-1")
    clarification = SimpleNamespace(clarification_id="clarification-1")
    approval_decision = SimpleNamespace(decision_id="approval-decision-1")
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": code_generation_payload(),
                    "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
                }
            )
        ],
        stage_artifacts=[stage_artifact],
        context_references=[context_reference],
        change_sets=[change_set],
        clarifications=[clarification],
        approval_decisions=[approval_decision],
    )

    runtime.run_stage(invocation())
    request = runtime.context_builder.requests[0]

    assert request.stage_artifacts == (stage_artifact,)
    assert request.context_references == (context_reference,)
    assert request.change_sets == (change_set,)
    assert request.clarifications == (clarification,)
    assert request.approval_decisions == (approval_decision,)
