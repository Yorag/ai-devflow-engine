from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.context.schemas import (
    ContextBlock,
    ContextBoundaryAction,
    ContextEnvelope,
    ContextEnvelopeSection,
    ContextManifest,
    ContextSourceRef,
    ContextTrustLevel,
    RenderedOutputKind,
)
from backend.app.domain.enums import (
    ApprovalType,
    ProviderProtocolType,
    ProviderSource,
    StageType,
    TemplateSource,
    ToolRiskLevel,
)
from backend.app.context.source_resolver import ResolvedContextSources
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.prompts.registry import PromptRegistry
from backend.app.prompts.renderer import (
    PromptRenderException,
    PromptRenderRequest,
    PromptRenderer,
)
from backend.app.providers.langchain_adapter import (
    ModelCallResult,
    ModelCallTraceSummary,
    ModelCallUsage,
)
from backend.app.schemas.prompts import ModelCallType
from backend.app.schemas.prompts import (
    PromptAssetRead,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptSectionRead,
    PromptType,
)
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    ModelBindingSnapshotRead,
    RuntimeLimitSnapshotRead,
    SnapshotModelRuntimeCapabilities,
)
from backend.app.tools.protocol import ToolBindableDescription


NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


class FakeArtifactStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def append_process_record(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


class MergingFakeArtifactStore:
    def __init__(self) -> None:
        self.process: dict[str, object] = {}
        self.calls: list[dict[str, object]] = []

    def append_process_record(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))
        process_key = kwargs["process_key"]
        assert isinstance(process_key, str)
        self.process[process_key] = kwargs["process_value"]

    def get_stage_artifact(self, artifact_id: str) -> object:
        del artifact_id
        return type("Artifact", (), {"process": self.process})()


class FakeProviderAdapter:
    def __init__(self, result: ModelCallResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def invoke_structured(self, **kwargs: Any) -> ModelCallResult:
        self.calls.append(kwargs)
        return self.result


def _trace_context() -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="span-1",
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def _model_call_result(
    *,
    structured_output: dict[str, object] | None = None,
    provider_error_code: object | None = None,
) -> ModelCallResult:
    return ModelCallResult(
        provider_snapshot_id="provider-snapshot-run-1",
        model_binding_snapshot_id="model-binding-compression-run-1",
        model_call_type=ModelCallType.CONTEXT_COMPRESSION,
        structured_output=structured_output,
        provider_error_code=provider_error_code,
        provider_error_message=(
            "Provider call failed." if provider_error_code is not None else None
        ),
        usage=ModelCallUsage(input_tokens=100, output_tokens=20, total_tokens=120),
        raw_response_ref="sha256:model-response",
        trace_summary=ModelCallTraceSummary(
            request_id="request-1",
            trace_id="trace-1",
            correlation_id="correlation-1",
            span_id="span-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            provider_snapshot_id="provider-snapshot-run-1",
            model_binding_snapshot_id="model-binding-compression-run-1",
            model_call_type=ModelCallType.CONTEXT_COMPRESSION,
            input_summary={"content_hash": "sha256:input"},
            output_summary={"content_hash": "sha256:output"},
        ),
    )


def _structured_output(*, summary: str = "Earlier iterations selected the provider adapter path.") -> dict[str, object]:
    return {
        "summary": summary,
        "decisions_made": ["Use frozen provider snapshots."],
        "files_observed": ["backend/app/providers/langchain_adapter.py"],
        "files_modified": [],
        "failed_attempts": [],
        "open_issues": ["StageAgentRuntime will consume this later."],
        "evidence_refs": ["stage-process://stage-run-1/full"],
    }


def _renderer() -> PromptRenderer:
    return PromptRenderer(PromptRegistry.load_builtin_assets())


def _render_request() -> PromptRenderRequest:
    return PromptRenderRequest(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        model_call_type=ModelCallType.CONTEXT_COMPRESSION,
        template_snapshot_ref="template-snapshot-run-1",
        stage_contracts={
            "code_generation": {
                "stage_type": "code_generation",
                "stage_contract_ref": "stage-contract-code-generation",
                "allowed_tools": [],
            }
        },
        task_objective="Compress prior context.",
        specified_action="Return a compressed context block.",
        available_tools=[],
        response_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        output_schema_ref="schema://compressed-context-block",
        tool_schema_version="tool-schema-v1",
        compression_source_context="older step one\nolder step two",
        compression_trigger_reason="compression_threshold_exceeded",
        full_trace_ref="stage-process://stage-run-1/full",
        created_at=NOW,
    )


def _provider_snapshot(*, context_window_tokens: int = 1000) -> ProviderSnapshot:
    return ProviderSnapshot(
        snapshot_id="provider-snapshot-run-1-openai-gpt-5",
        run_id="run-1",
        provider_id="provider-openai",
        display_name="OpenAI",
        provider_source=ProviderSource.CUSTOM,
        protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url="https://api.openai.test",
        api_key_ref="env:OPENAI_API_KEY",
        model_id="gpt-5",
        is_default_model=True,
        capabilities=SnapshotModelRuntimeCapabilities(
            model_id="gpt-5",
            context_window_tokens=context_window_tokens,
            max_output_tokens=200,
            supports_tool_calling=True,
            supports_structured_output=True,
            supports_native_reasoning=True,
        ),
        source_config_version="provider-config-v1",
        created_at=NOW,
    )


def _block() -> ContextBlock:
    return ContextBlock(
        block_id="working-observation-1",
        section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
        trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
        boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
        summary="Older step one. Older step two.",
        content_ref="artifact://process/run-1/older-observations",
        sources=(
            ContextSourceRef(
                source_kind="process_ref",
                source_ref="artifact://process/run-1/older-observations",
                source_label="older-observations",
            ),
        ),
        estimated_chars=32,
    )


def _minimal_envelope() -> ContextEnvelope:
    return ContextEnvelope(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        template_snapshot_ref="template-snapshot-run-1",
        stage_contract_ref="stage-contract-code-generation",
        provider_snapshot_ref="provider-snapshot-run-1-openai-gpt-5",
        model_binding_snapshot_ref="model-binding-snapshot-run-1-code-generation",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        runtime_instructions=(),
        stage_contract=(),
        agent_role_prompt=(),
        task_objective=(),
        specified_action=(),
        input_artifact_refs=(),
        context_references=(),
        working_observations=(_block(),),
        reasoning_trace=(),
        available_tools=(),
        recent_observations=(),
        response_schema={"type": "object"},
        trace_context=_trace_context(),
        built_at=NOW,
    )


def _minimal_manifest(envelope: ContextEnvelope) -> ContextManifest:
    return ContextManifest.from_envelope(
        envelope,
        provider_snapshot=_provider_snapshot(),
        prompt_refs=[],
        render_hash="a" * 64,
        rendered_output_ref="artifact://context-envelopes/run-1/stage-run-1/stage_execution",
        rendered_output_kind=RenderedOutputKind.MESSAGE_SEQUENCE,
        template_version="template-version-1",
        output_schema_ref="schema://stage-result",
        tool_schema_version="tool-schema-v1",
        runtime_limit_snapshot_ref="runtime-limit-snapshot-run-1",
        compression_threshold_ratio=0.75,
        compression_trigger_token_threshold=750,
    )


def test_prompt_renderer_context_compression_uses_builtin_compression_prompt() -> None:
    result = _renderer().render_messages(_render_request())

    assert result.metadata.model_call_type is ModelCallType.CONTEXT_COMPRESSION
    assert [ref.prompt_id for ref in result.metadata.prompt_refs] == [
        "compression_prompt"
    ]
    assert "Context Compression" in result.messages[0].content
    assert "older step one" in result.messages[1].content
    assert result.rendered_output_ref.endswith("/context_compression")


def test_compression_runner_writes_compressed_block_and_model_call_trace_with_existing_append_process_record() -> None:
    from backend.app.context.compression import (
        ContextCompressionRequest,
        ContextCompressionRunner,
    )

    artifact_store = FakeArtifactStore()
    provider_adapter = FakeProviderAdapter(
        _model_call_result(structured_output=_structured_output())
    )
    envelope = _minimal_envelope()
    result = ContextCompressionRunner(
        prompt_renderer=_renderer(),
        artifact_store=artifact_store,  # type: ignore[arg-type]
        now=lambda: NOW,
    ).compress(
        ContextCompressionRequest(
            envelope=envelope,
            manifest=_minimal_manifest(envelope),
            stage_artifact_id="artifact-stage-1",
            trace_context=_trace_context(),
            full_trace_ref="stage-process://stage-run-1/full",
            covered_step_range="1-8",
            compression_trigger_reason="compression_threshold_exceeded",
            provider_adapter=provider_adapter,
        )
    )

    assert result.compressed_context_block is not None
    assert result.compressed_context_block.compression_prompt_id == "compression_prompt"
    assert result.compressed_context_block.compression_prompt_version == "2026-05-06.1"
    assert provider_adapter.calls[0]["model_call_type"] is ModelCallType.CONTEXT_COMPRESSION
    assert [call["process_key"] for call in artifact_store.calls] == [
        "compressed_context_block",
        "context_compression_model_call_trace",
    ]
    assert artifact_store.calls[0]["process_value"][0]["summary"].startswith(
        "Earlier iterations"
    )
    assert artifact_store.calls[1]["process_value"][0]["model_call_type"] == (
        "context_compression"
    )


def test_compression_runner_preserves_repeated_compression_records_with_named_lists() -> None:
    from backend.app.context.compression import (
        ContextCompressionRequest,
        ContextCompressionRunner,
    )

    artifact_store = MergingFakeArtifactStore()
    provider_adapter = FakeProviderAdapter(
        _model_call_result(structured_output=_structured_output(summary="First summary."))
    )
    envelope = _minimal_envelope()
    runner = ContextCompressionRunner(
        prompt_renderer=_renderer(),
        artifact_store=artifact_store,  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    runner.compress(
        ContextCompressionRequest(
            envelope=envelope,
            manifest=_minimal_manifest(envelope),
            stage_artifact_id="artifact-stage-1",
            trace_context=_trace_context(),
            full_trace_ref="stage-process://stage-run-1/full",
            covered_step_range="1-8",
            compression_trigger_reason="compression_threshold_exceeded",
            provider_adapter=provider_adapter,
        )
    )
    provider_adapter.result = _model_call_result(
        structured_output=_structured_output(summary="Second summary.")
    )
    runner.compress(
        ContextCompressionRequest(
            envelope=envelope,
            manifest=_minimal_manifest(envelope),
            stage_artifact_id="artifact-stage-1",
            trace_context=_trace_context(),
            full_trace_ref="stage-process://stage-run-1/full",
            covered_step_range="9-16",
            compression_trigger_reason="compression_threshold_exceeded",
            provider_adapter=provider_adapter,
        )
    )

    compressed_records = artifact_store.process["compressed_context_block"]
    trace_records = artifact_store.process["context_compression_model_call_trace"]
    assert isinstance(compressed_records, list)
    assert isinstance(trace_records, list)
    assert [record["summary"] for record in compressed_records] == [
        "First summary.",
        "Second summary.",
    ]
    assert [record["model_call_type"] for record in trace_records] == [
        "context_compression",
        "context_compression",
    ]


def test_compression_runner_does_not_fabricate_summary_on_provider_failure() -> None:
    from backend.app.api.error_codes import ErrorCode
    from backend.app.context.compression import (
        ContextCompressionRequest,
        ContextCompressionRunner,
    )

    artifact_store = FakeArtifactStore()
    provider_adapter = FakeProviderAdapter(
        _model_call_result(provider_error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED)
    )
    envelope = _minimal_envelope()

    result = ContextCompressionRunner(
        prompt_renderer=_renderer(),
        artifact_store=artifact_store,  # type: ignore[arg-type]
        now=lambda: NOW,
    ).compress(
        ContextCompressionRequest(
            envelope=envelope,
            manifest=_minimal_manifest(envelope),
            stage_artifact_id="artifact-stage-1",
            trace_context=_trace_context(),
            full_trace_ref="stage-process://stage-run-1/full",
            covered_step_range="1-8",
            compression_trigger_reason="compression_threshold_exceeded",
            provider_adapter=provider_adapter,
        )
    )

    assert result.compressed_context_block is None
    assert result.warning == "Context compression provider call failed."
    assert [call["process_key"] for call in artifact_store.calls] == [
        "context_compression_model_call_trace"
    ]
    assert artifact_store.calls[0]["process_value"][0]["model_call_type"] == (
        "context_compression"
    )


def test_prompt_renderer_context_compression_missing_context_uses_specific_error() -> None:
    request = _render_request().model_copy(update={"compression_source_context": None})

    with pytest.raises(PromptRenderException) as exc_info:
        _renderer().render_messages(request)

    assert exc_info.value.error.code == "compression_context_missing"


def test_prompt_renderer_unsupported_error_mentions_context_compression_support() -> None:
    request = _render_request().model_copy(
        update={"model_call_type": ModelCallType.VALIDATION_PASS}
    )

    with pytest.raises(PromptRenderException) as exc_info:
        _renderer().render_messages(request)

    assert "context_compression" in exc_info.value.error.message


class FakeBuilderArtifactStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def append_process_record(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


class FakeBuilderToolRegistry:
    def list_bindable_tools(self) -> tuple[ToolBindableDescription, ...]:
        return (_tool("grep"), _tool("read_file"))


class ResolverReturningLargeBashOutput:
    def resolve_stage_inputs(self, **kwargs: object) -> tuple[ContextBlock, ...]:
        return ()

    def resolve_context_references(self, **kwargs: object) -> ResolvedContextSources:
        return ResolvedContextSources(
            working_observations=(
                _large_block(summary="x" * 120),
            )
        )


class ResolverReturningLargeEstimatedContext:
    def resolve_stage_inputs(self, **kwargs: object) -> tuple[ContextBlock, ...]:
        return ()

    def resolve_context_references(self, **kwargs: object) -> ResolvedContextSources:
        return ResolvedContextSources(
            working_observations=(
                _large_block(summary="Large estimated context.", estimated_tokens=700),
            )
        )


class ResolverReturningOversizedContext:
    def resolve_stage_inputs(self, **kwargs: object) -> tuple[ContextBlock, ...]:
        return ()

    def resolve_context_references(self, **kwargs: object) -> ResolvedContextSources:
        return ResolvedContextSources(
            working_observations=(
                _large_block(summary="z" * 1200, estimated_tokens=700),
            )
        )


class ResolverReturningHugePinnedAndOversizedContext:
    def resolve_stage_inputs(self, **kwargs: object) -> tuple[ContextBlock, ...]:
        return ()

    def resolve_context_references(self, **kwargs: object) -> ResolvedContextSources:
        return ResolvedContextSources(
            working_observations=(
                _large_block(summary="z" * 1200, estimated_tokens=700),
            )
        )


class ResolverReturningManyWorkingObservations:
    def resolve_stage_inputs(self, **kwargs: object) -> tuple[ContextBlock, ...]:
        return ()

    def resolve_context_references(self, **kwargs: object) -> ResolvedContextSources:
        return ResolvedContextSources(
            working_observations=tuple(
                ContextBlock(
                    block_id=f"working-observation-{index}",
                    section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
                    trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
                    boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
                    summary=f"Working observation {index}.",
                    content_ref=f"artifact://process/run-1/working-{index}",
                    sources=(
                        ContextSourceRef(
                            source_kind="process_ref",
                            source_ref=f"artifact://process/run-1/working-{index}",
                            source_label=f"working-{index}",
                        ),
                    ),
                    estimated_chars=24,
                )
                for index in range(1, 4)
            )
        )


def _asset(
    *,
    prompt_id: str,
    prompt_type: PromptType,
    authority_level: PromptAuthorityLevel,
    model_call_type: ModelCallType,
    source_ref: str,
    body: str,
    cache_scope: PromptCacheScope = PromptCacheScope.GLOBAL_STATIC,
) -> PromptAssetRead:
    return PromptAssetRead(
        prompt_id=prompt_id,
        prompt_version="2026-05-04.1",
        prompt_type=prompt_type,
        authority_level=authority_level,
        model_call_type=model_call_type,
        cache_scope=cache_scope,
        source_ref=source_ref,
        content_hash=PromptAssetRead.calculate_content_hash(body),
        sections=[
            PromptSectionRead(
                section_id=prompt_id,
                title=prompt_id.replace("_", " ").title(),
                body=body,
                cache_scope=cache_scope,
            )
        ],
        applies_to_stage_types=[StageType.CODE_GENERATION],
    )


def _builder_renderer() -> PromptRenderer:
    return PromptRenderer(
        PromptRegistry(
            [
                _asset(
                    prompt_id="runtime_instructions",
                    prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
                    authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
                    model_call_type=ModelCallType.STAGE_EXECUTION,
                    source_ref="backend://prompts/runtime/runtime_instructions.md",
                    body="# Runtime Instructions\nStay inside platform boundaries.",
                ),
                _asset(
                    prompt_id="structured_output_repair",
                    prompt_type=PromptType.STRUCTURED_OUTPUT_REPAIR,
                    authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
                    model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR,
                    source_ref="backend://prompts/repairs/structured_output_repair.md",
                    body="# Structured Output Repair\nRepair only invalid JSON.",
                    cache_scope=PromptCacheScope.DYNAMIC_UNCACHED,
                ),
                _asset(
                    prompt_id="compression_prompt",
                    prompt_type=PromptType.COMPRESSION_PROMPT,
                    authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
                    model_call_type=ModelCallType.CONTEXT_COMPRESSION,
                    cache_scope=PromptCacheScope.RUN_STATIC,
                    source_ref="backend://prompts/compression/compression_context.md",
                    body="# Context Compression\nPreserve decisions and refs.",
                ),
                _asset(
                    prompt_id="stage_prompt_fragment.code_generation",
                    prompt_type=PromptType.STAGE_PROMPT_FRAGMENT,
                    authority_level=PromptAuthorityLevel.STAGE_CONTRACT_RENDERED,
                    model_call_type=ModelCallType.STAGE_EXECUTION,
                    cache_scope=PromptCacheScope.RUN_STATIC,
                    source_ref="backend://prompts/stages/code_generation.md",
                    body=(
                        "# Code Generation Stage Prompt\n"
                        "Use the current stage_contract and response_schema."
                    ),
                ),
                _asset(
                    prompt_id="tool_usage_template",
                    prompt_type=PromptType.TOOL_USAGE_TEMPLATE,
                    authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                    model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                    source_ref="backend://prompts/tools/tool_usage_common.md",
                    body="# Tool Usage\nUse only listed tools.",
                    cache_scope=PromptCacheScope.RUN_STATIC,
                ),
                _asset(
                    prompt_id="tool_prompt_fragment.grep",
                    prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
                    authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                    model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                    source_ref="backend://prompts/tools/grep.md",
                    body="# grep Tool\nUse grep for workspace text search.",
                ),
                _asset(
                    prompt_id="tool_prompt_fragment.read_file",
                    prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
                    authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                    model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                    source_ref="backend://prompts/tools/read_file.md",
                    body="# read_file Tool\nUse read_file for workspace text reads.",
                ),
            ]
        )
    )


def _tool(name: str) -> ToolBindableDescription:
    return ToolBindableDescription(
        name=name,
        description=f"{name} description.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
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


def _template_snapshot() -> TemplateSnapshot:
    stage_sequence = tuple(StageType)
    return TemplateSnapshot(
        snapshot_ref="template-snapshot-run-1",
        run_id="run-1",
        source_template_id="template-1",
        source_template_name="Function One",
        source_template=TemplateSource.SYSTEM_TEMPLATE,
        source_template_updated_at=NOW,
        fixed_stage_sequence=stage_sequence,
        stage_role_bindings=tuple(
            StageRoleSnapshot(
                stage_type=stage,
                role_id=f"role-{stage.value}",
                system_prompt=f"Role prompt for {stage.value}.",
                provider_id="provider-openai",
            )
            for stage in stage_sequence
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


def _graph_definition() -> GraphDefinition:
    return GraphDefinition(
        graph_definition_id="graph-definition-run-1",
        run_id="run-1",
        template_snapshot_ref="template-snapshot-run-1",
        runtime_limit_snapshot_ref="runtime-limit-snapshot-run-1",
        runtime_limit_source_config_version="runtime-settings-v1",
        stage_nodes=tuple({"node_key": stage.value} for stage in StageType),
        stage_contracts={
            stage.value: {
                "stage_type": stage.value,
                "stage_contract_ref": f"stage-contract-{stage.value}",
                "stage_responsibility": stage.value,
                "input_contract": {"requires": []},
                "output_contract": {"produces": []},
                "structured_artifact_required": f"{stage.value}-artifact",
                "allowed_tools": (
                    ["grep", "read_file"] if stage is StageType.CODE_GENERATION else []
                ),
            }
            for stage in StageType
        },
        interrupt_policy={"approval_interrupts": []},
        retry_policy={"max_auto_regression_retries": 2},
        delivery_routing_policy={"stage": "delivery_integration"},
        source_node_group_map={stage.value: stage.value for stage in StageType},
        created_at=NOW,
    )


def _runtime_limits(
    *,
    context_window_tokens: int = 1000,
    bash_stdout_preview_chars: int = 8000,
    compression_threshold_ratio: float = 0.75,
) -> RuntimeLimitSnapshotRead:
    del context_window_tokens
    return RuntimeLimitSnapshotRead(
        snapshot_id="runtime-limit-snapshot-run-1",
        run_id="run-1",
        agent_limits=AgentRuntimeLimits(),
        context_limits=ContextLimits(
            bash_stdout_preview_chars=bash_stdout_preview_chars,
            compression_threshold_ratio=compression_threshold_ratio,
        ),
        source_config_version="runtime-settings-v1",
        hard_limits_version="platform-hard-limits-v1",
        schema_version="runtime-limit-snapshot-v1",
        created_at=NOW,
    )


def _model_binding_snapshot(
    *,
    context_window_tokens: int = 1000,
) -> ModelBindingSnapshotRead:
    return ModelBindingSnapshotRead(
        snapshot_id="model-binding-snapshot-run-1-code-generation",
        run_id="run-1",
        binding_id="agent_role:code_generation:role-code_generation",
        binding_type="agent_role",
        stage_type=StageType.CODE_GENERATION,
        role_id="role-code_generation",
        provider_snapshot_id="provider-snapshot-run-1-openai-gpt-5",
        provider_id="provider-openai",
        model_id="gpt-5",
        capabilities=SnapshotModelRuntimeCapabilities(
            model_id="gpt-5",
            context_window_tokens=context_window_tokens,
            max_output_tokens=200,
            supports_tool_calling=True,
            supports_structured_output=True,
            supports_native_reasoning=True,
        ),
        model_parameters={},
        source_config_version="template-binding-v1",
        schema_version="model-binding-snapshot-v1",
        created_at=NOW,
    )


def _builder_request(
    *,
    context_window_tokens: int = 1000,
    bash_stdout_preview_chars: int = 8000,
    compression_threshold_ratio: float = 0.75,
    reserved_output_tokens: int = 0,
    max_recent_observation_blocks: int | None = None,
    full_trace_ref: str | None = None,
    compression_covered_step_range: str | None = None,
    provider_adapter: FakeProviderAdapter | None = None,
) -> object:
    from backend.app.context.builder import ContextBuildRequest

    return ContextBuildRequest(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_artifact_id="artifact-stage-1",
        stage_type=StageType.CODE_GENERATION,
        stage_contract_ref="stage-contract-code_generation",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        task_objective="Generate context management code.",
        specified_action="Return a structured implementation result.",
        response_schema={
            "type": "object",
            "properties": {"decision": {"type": "string"}},
            "required": ["decision"],
            "additionalProperties": False,
        },
        output_schema_ref="schema://agent-decision",
        tool_schema_version="tool-schema-v1",
        template_version="template-version-1",
        trace_context=_trace_context(),
        template_snapshot=_template_snapshot(),
        graph_definition=_graph_definition(),
        runtime_limit_snapshot=_runtime_limits(
            context_window_tokens=context_window_tokens,
            bash_stdout_preview_chars=bash_stdout_preview_chars,
            compression_threshold_ratio=compression_threshold_ratio,
        ),
        provider_snapshot=_provider_snapshot(
            context_window_tokens=context_window_tokens,
        ),
        model_binding_snapshot=_model_binding_snapshot(
            context_window_tokens=context_window_tokens,
        ),
        reserved_output_tokens=reserved_output_tokens,
        max_recent_observation_blocks=max_recent_observation_blocks,
        full_trace_ref=full_trace_ref,
        compression_covered_step_range=compression_covered_step_range,
        provider_adapter=provider_adapter,
    )


def _large_block(
    *,
    summary: str,
    estimated_tokens: int | None = None,
) -> ContextBlock:
    return ContextBlock(
        block_id="working-observation:bash-stdout",
        section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
        trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
        boundary_action=ContextBoundaryAction.ALLOW,
        summary=summary,
        content_ref="artifact://bash/stdout/full",
        sources=(
            ContextSourceRef(
                source_kind="bash_stdout",
                source_ref="artifact://bash/stdout/full",
                source_label="bash stdout",
            ),
        ),
        estimated_tokens=estimated_tokens,
        estimated_chars=len(summary),
    )


def test_builder_applies_observation_budget_before_rendering_non_prompt_sections() -> None:
    from backend.app.context.builder import ContextEnvelopeBuilder
    from backend.app.context.size_guard import ContextSizeGuard

    builder = ContextEnvelopeBuilder(
        prompt_renderer=_builder_renderer(),
        tool_registry=FakeBuilderToolRegistry(),  # type: ignore[arg-type]
        artifact_store=FakeBuilderArtifactStore(),  # type: ignore[arg-type]
        source_resolver=ResolverReturningLargeBashOutput(),  # type: ignore[arg-type]
        context_size_guard=ContextSizeGuard(),
        now=lambda: NOW,
    )

    result = builder.build_for_stage_call(
        _builder_request(
            context_window_tokens=1000,
            bash_stdout_preview_chars=16,
            compression_threshold_ratio=0.95,
        )
    )

    user_message = result.rendered_messages[1].content
    assert "full_ref=artifact://bash/stdout/full" in user_message
    assert "x" * 80 not in user_message
    assert any(record.truncated for record in result.manifest.records)


def test_builder_raises_context_overflow_when_compression_is_required_without_runner() -> None:
    from backend.app.context.builder import ContextEnvelopeBuilder
    from backend.app.context.size_guard import ContextOverflowError, ContextSizeGuard

    builder = ContextEnvelopeBuilder(
        prompt_renderer=_builder_renderer(),
        tool_registry=FakeBuilderToolRegistry(),  # type: ignore[arg-type]
        artifact_store=FakeBuilderArtifactStore(),  # type: ignore[arg-type]
        source_resolver=ResolverReturningLargeEstimatedContext(),  # type: ignore[arg-type]
        context_size_guard=ContextSizeGuard(),
        now=lambda: NOW,
    )

    with pytest.raises(ContextOverflowError, match="compression required"):
        builder.build_for_stage_call(
            _builder_request(
                context_window_tokens=1000,
                compression_threshold_ratio=0.5,
            )
        )


def test_builder_runs_compression_runner_and_replaces_oversized_context() -> None:
    from backend.app.context.builder import ContextEnvelopeBuilder
    from backend.app.context.compression import ContextCompressionRunner
    from backend.app.context.size_guard import ContextSizeGuard

    artifact_store = FakeBuilderArtifactStore()
    provider_adapter = FakeProviderAdapter(
        _model_call_result(
            structured_output={
                "summary": "Compressed bounded context summary.",
                "decisions_made": ["Keep provider adapter path."],
                "evidence_refs": ["stage-process://stage-run-1/full"],
            }
        )
    )
    builder = ContextEnvelopeBuilder(
        prompt_renderer=_builder_renderer(),
        tool_registry=FakeBuilderToolRegistry(),  # type: ignore[arg-type]
        artifact_store=artifact_store,  # type: ignore[arg-type]
        source_resolver=ResolverReturningOversizedContext(),  # type: ignore[arg-type]
        context_size_guard=ContextSizeGuard(),
        compression_runner=ContextCompressionRunner(
            prompt_renderer=_builder_renderer(),
            artifact_store=artifact_store,  # type: ignore[arg-type]
            now=lambda: NOW,
        ),
        now=lambda: NOW,
    )

    result = builder.build_for_stage_call(
        _builder_request(
            context_window_tokens=1000,
            compression_threshold_ratio=0.5,
            full_trace_ref="stage-process://stage-run-1/full",
            compression_covered_step_range="1-12",
            provider_adapter=provider_adapter,
        )
    )

    user_message = result.rendered_messages[1].content
    assert "z" * 80 not in user_message
    assert "Compressed bounded context summary." in user_message
    assert "compressed_context_block://" in user_message
    assert result.envelope.working_observations == ()
    compressed_block = result.envelope.recent_observations[0]
    assert compressed_block.compressed is True
    assert compressed_block.boundary_action is ContextBoundaryAction.REFERENCE_ONLY
    assert compressed_block.content_ref.startswith("compressed_context_block://")
    assert [call["process_key"] for call in artifact_store.calls] == [
        "compressed_context_block",
        "context_compression_model_call_trace",
        "context_manifest",
    ]


def test_builder_rechecks_size_after_compression_and_rejects_oversized_final_context() -> None:
    from backend.app.context.builder import ContextEnvelopeBuilder
    from backend.app.context.compression import ContextCompressionRunner
    from backend.app.context.size_guard import ContextOverflowError, ContextSizeGuard

    artifact_store = FakeBuilderArtifactStore()
    provider_adapter = FakeProviderAdapter(
        _model_call_result(structured_output=_structured_output(summary="y" * 2100))
    )
    builder = ContextEnvelopeBuilder(
        prompt_renderer=_builder_renderer(),
        tool_registry=FakeBuilderToolRegistry(),  # type: ignore[arg-type]
        artifact_store=artifact_store,  # type: ignore[arg-type]
        source_resolver=ResolverReturningHugePinnedAndOversizedContext(),  # type: ignore[arg-type]
        context_size_guard=ContextSizeGuard(),
        compression_runner=ContextCompressionRunner(
            prompt_renderer=_builder_renderer(),
            artifact_store=artifact_store,  # type: ignore[arg-type]
            now=lambda: NOW,
        ),
        now=lambda: NOW,
    )

    with pytest.raises(ContextOverflowError, match="Compressed context still exceeds"):
        builder.build_for_stage_call(
            _builder_request(
                context_window_tokens=1000,
                compression_threshold_ratio=0.5,
                provider_adapter=provider_adapter,
            )
        )


def test_builder_raises_when_compression_required_with_runner_but_no_provider_adapter() -> None:
    from backend.app.context.builder import ContextEnvelopeBuilder
    from backend.app.context.compression import ContextCompressionRunner
    from backend.app.context.size_guard import ContextOverflowError, ContextSizeGuard

    builder = ContextEnvelopeBuilder(
        prompt_renderer=_builder_renderer(),
        tool_registry=FakeBuilderToolRegistry(),  # type: ignore[arg-type]
        artifact_store=FakeBuilderArtifactStore(),  # type: ignore[arg-type]
        source_resolver=ResolverReturningOversizedContext(),  # type: ignore[arg-type]
        context_size_guard=ContextSizeGuard(),
        compression_runner=ContextCompressionRunner(
            prompt_renderer=_builder_renderer(),
            artifact_store=FakeBuilderArtifactStore(),  # type: ignore[arg-type]
            now=lambda: NOW,
        ),
        now=lambda: NOW,
    )

    with pytest.raises(ContextOverflowError, match="provider adapter"):
        builder.build_for_stage_call(
            _builder_request(
                context_window_tokens=1000,
                compression_threshold_ratio=0.5,
            )
        )


def test_builder_reserved_output_lowers_manifest_trigger_threshold() -> None:
    from backend.app.context.builder import ContextEnvelopeBuilder
    from backend.app.context.size_guard import ContextSizeGuard

    result = ContextEnvelopeBuilder(
        prompt_renderer=_builder_renderer(),
        tool_registry=FakeBuilderToolRegistry(),  # type: ignore[arg-type]
        artifact_store=FakeBuilderArtifactStore(),  # type: ignore[arg-type]
        source_resolver=ResolverReturningLargeBashOutput(),  # type: ignore[arg-type]
        context_size_guard=ContextSizeGuard(),
        now=lambda: NOW,
    ).build_for_stage_call(
        _builder_request(
            context_window_tokens=1000,
            bash_stdout_preview_chars=16,
            compression_threshold_ratio=0.75,
            reserved_output_tokens=200,
        )
    )

    assert result.manifest.compression_trigger_token_threshold == 600


def test_builder_uses_request_max_recent_observation_blocks_for_sliding_window() -> None:
    from backend.app.context.builder import ContextEnvelopeBuilder
    from backend.app.context.size_guard import ContextSizeGuard

    result = ContextEnvelopeBuilder(
        prompt_renderer=_builder_renderer(),
        tool_registry=FakeBuilderToolRegistry(),  # type: ignore[arg-type]
        artifact_store=FakeBuilderArtifactStore(),  # type: ignore[arg-type]
        source_resolver=ResolverReturningManyWorkingObservations(),  # type: ignore[arg-type]
        context_size_guard=ContextSizeGuard(),
        now=lambda: NOW,
    ).build_for_stage_call(
        _builder_request(
            context_window_tokens=4000,
            compression_threshold_ratio=0.95,
            max_recent_observation_blocks=1,
        )
    )

    assert [block.block_id for block in result.envelope.working_observations] == [
        "context-index:stage-run-1:working_observations:1-2",
        "working-observation-3",
    ]
