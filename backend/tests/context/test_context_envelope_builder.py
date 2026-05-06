from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.context.schemas import (
    ContextBlock,
    ContextBoundaryAction,
    ContextEnvelopeSection,
    ContextSourceRef,
    ContextTrustLevel,
)
from backend.app.context.source_resolver import ResolvedContextSources
from backend.app.domain.enums import (
    ApprovalType,
    ProviderProtocolType,
    ProviderSource,
    StageType,
    TemplateSource,
    ToolRiskLevel,
)
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.prompts.registry import PromptRegistry
from backend.app.prompts.renderer import PromptRenderer
from backend.app.schemas.prompts import (
    ModelCallType,
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

    def append_process_record(
        self,
        *,
        artifact_id: str,
        process_key: str,
        process_value: Any,
        trace_context: TraceContext,
    ) -> None:
        self.calls.append(
            {
                "artifact_id": artifact_id,
                "process_key": process_key,
                "process_value": process_value,
                "trace_context": trace_context,
            }
        )


class FakeSourceResolver:
    def __init__(self) -> None:
        self.stage_inputs_allowed_context_run_ids: tuple[str, ...] | None = None
        self.reference_allowed_context_run_ids: tuple[str, ...] | None = None

    def resolve_stage_inputs(self, **kwargs: object) -> tuple[ContextBlock, ...]:
        self.stage_inputs_allowed_context_run_ids = tuple(
            kwargs["allowed_context_run_ids"]  # type: ignore[arg-type]
        )
        return (
            _context_block(
                section=ContextEnvelopeSection.INPUT_ARTIFACT_REFS,
                block_id="input-artifact:solution-design",
                summary="Input artifact refs: plan_id=plan-1.",
                content_ref="stage-artifact://solution-design-1",
            ),
        )

    def resolve_context_references(self, **kwargs: object) -> ResolvedContextSources:
        self.reference_allowed_context_run_ids = tuple(
            kwargs["allowed_context_run_ids"]  # type: ignore[arg-type]
        )
        return ResolvedContextSources(
            context_references=(
                _context_block(
                    section=ContextEnvelopeSection.CONTEXT_REFERENCES,
                    block_id="context-reference:requirement",
                    summary="Context references: requirement message ref.",
                    content_ref="message://session-1/1",
                    trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
                    boundary_action=ContextBoundaryAction.QUARANTINE,
                ),
            ),
            working_observations=(
                _context_block(
                    section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
                    block_id="working-observation:changeset",
                    summary="Working observations: changeset ref.",
                    content_ref="changeset://changeset-1",
                    trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
                    boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
                ),
            ),
            reasoning_trace=(
                _context_block(
                    section=ContextEnvelopeSection.REASONING_TRACE,
                    block_id="reasoning-trace:model",
                    summary="Reasoning trace: model summary ref.",
                    content_ref="reasoning://run-1/stage-1/summary",
                ),
            ),
            recent_observations=(
                _context_block(
                    section=ContextEnvelopeSection.RECENT_OBSERVATIONS,
                    block_id="recent-observation:clarification",
                    summary="Recent observations: clarification answer.",
                    content_ref="clarification://clarification-1",
                    trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
                    boundary_action=ContextBoundaryAction.QUARANTINE,
                ),
            ),
        )


class FakeToolRegistry:
    def list_bindable_tools(self) -> tuple[ToolBindableDescription, ...]:
        return (_tool("write_file"), _tool("grep"), _tool("read_file"))


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


def _renderer() -> PromptRenderer:
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


def _context_block(
    *,
    section: ContextEnvelopeSection,
    block_id: str,
    summary: str,
    content_ref: str,
    trust_level: ContextTrustLevel = ContextTrustLevel.TRUSTED_REFERENCE,
    boundary_action: ContextBoundaryAction = ContextBoundaryAction.REFERENCE_ONLY,
) -> ContextBlock:
    return ContextBlock(
        block_id=block_id,
        section=section,
        trust_level=trust_level,
        boundary_action=boundary_action,
        summary=summary,
        content_ref=content_ref,
        sources=(
            ContextSourceRef(
                source_kind=section.value,
                source_ref=content_ref,
                source_label=block_id,
            ),
        ),
        estimated_chars=len(summary),
    )


def _template_snapshot(*, run_id: str = "run-1") -> TemplateSnapshot:
    stage_sequence = tuple(StageType)
    return TemplateSnapshot(
        snapshot_ref=f"template-snapshot-{run_id}",
        run_id=run_id,
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


def _graph_definition(*, run_id: str = "run-1") -> GraphDefinition:
    return GraphDefinition(
        graph_definition_id=f"graph-definition-{run_id}",
        run_id=run_id,
        template_snapshot_ref=f"template-snapshot-{run_id}",
        runtime_limit_snapshot_ref=f"runtime-limit-snapshot-{run_id}",
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
                "runtime_limits": {
                    "runtime_limit_snapshot_ref": f"runtime-limit-snapshot-{run_id}"
                },
            }
            for stage in StageType
        },
        interrupt_policy={"approval_interrupts": []},
        retry_policy={"max_auto_regression_retries": 2},
        delivery_routing_policy={"stage": "delivery_integration"},
        source_node_group_map={stage.value: stage.value for stage in StageType},
        created_at=NOW,
    )


def _runtime_limits(*, run_id: str = "run-1") -> RuntimeLimitSnapshotRead:
    return RuntimeLimitSnapshotRead(
        snapshot_id=f"runtime-limit-snapshot-{run_id}",
        run_id=run_id,
        agent_limits=AgentRuntimeLimits(),
        context_limits=ContextLimits(compression_threshold_ratio=0.75),
        source_config_version="runtime-settings-v1",
        hard_limits_version="platform-hard-limits-v1",
        schema_version="runtime-limit-snapshot-v1",
        created_at=NOW,
    )


def _capabilities() -> SnapshotModelRuntimeCapabilities:
    return SnapshotModelRuntimeCapabilities(
        model_id="gpt-5",
        context_window_tokens=1000,
        max_output_tokens=200,
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_native_reasoning=True,
    )


def _provider_snapshot(*, run_id: str = "run-1") -> ProviderSnapshot:
    return ProviderSnapshot(
        snapshot_id=f"provider-snapshot-{run_id}-openai-gpt-5",
        run_id=run_id,
        provider_id="provider-openai",
        display_name="OpenAI",
        provider_source=ProviderSource.CUSTOM,
        protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url="https://api.openai.test",
        api_key_ref="env:OPENAI_API_KEY",
        model_id="gpt-5",
        is_default_model=True,
        capabilities=_capabilities(),
        source_config_version="provider-config-v1",
        created_at=NOW,
    )


def _model_binding_snapshot(*, run_id: str = "run-1") -> ModelBindingSnapshotRead:
    return ModelBindingSnapshotRead(
        snapshot_id=f"model-binding-snapshot-{run_id}-code-generation",
        run_id=run_id,
        binding_id="agent_role:code_generation:role-code_generation",
        binding_type="agent_role",
        stage_type=StageType.CODE_GENERATION,
        role_id="role-code_generation",
        provider_snapshot_id=f"provider-snapshot-{run_id}-openai-gpt-5",
        provider_id="provider-openai",
        model_id="gpt-5",
        capabilities=_capabilities(),
        model_parameters={},
        source_config_version="template-binding-v1",
        schema_version="model-binding-snapshot-v1",
        created_at=NOW,
    )


def _trace_context(
    *,
    session_id: str = "session-1",
    run_id: str = "run-1",
    stage_run_id: str = "stage-code-generation-1",
) -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="span-1",
        session_id=session_id,
        run_id=run_id,
        stage_run_id=stage_run_id,
        created_at=NOW,
    )


def _build_request(**overrides: object) -> object:
    from backend.app.context.builder import ContextBuildRequest

    values: dict[str, object] = {
        "session_id": "session-1",
        "run_id": "run-1",
        "stage_run_id": "stage-code-generation-1",
        "stage_artifact_id": "artifact-code-generation-1",
        "stage_type": StageType.CODE_GENERATION,
        "stage_contract_ref": "stage-contract-code_generation",
        "model_call_type": ModelCallType.STAGE_EXECUTION,
        "task_objective": "Generate the context envelope builder.",
        "specified_action": "Return a structured stage decision.",
        "response_schema": {
            "type": "object",
            "properties": {"decision": {"type": "string"}},
            "required": ["decision"],
            "additionalProperties": False,
        },
        "output_schema_ref": "schema://agent-decision",
        "tool_schema_version": "tool-schema-v1",
        "template_version": "caller-frozen-template-v7",
        "trace_context": _trace_context(),
        "template_snapshot": _template_snapshot(),
        "graph_definition": _graph_definition(),
        "runtime_limit_snapshot": _runtime_limits(),
        "provider_snapshot": _provider_snapshot(),
        "model_binding_snapshot": _model_binding_snapshot(),
    }
    values.update(overrides)
    return ContextBuildRequest(**values)


def _builder(
    *,
    artifact_store: FakeArtifactStore | None = None,
    source_resolver: FakeSourceResolver | None = None,
    context_size_guard: object | None = None,
) -> object:
    from backend.app.context.builder import ContextEnvelopeBuilder

    return ContextEnvelopeBuilder(
        prompt_renderer=_renderer(),
        tool_registry=FakeToolRegistry(),
        artifact_store=artifact_store or FakeArtifactStore(),
        source_resolver=source_resolver or FakeSourceResolver(),
        context_size_guard=context_size_guard,
        now=lambda: NOW,
    )


def test_stage_execution_builds_envelope_manifest_messages_and_persists_context_manifest() -> None:
    artifact_store = FakeArtifactStore()

    result = _builder(artifact_store=artifact_store).build_for_stage_call(
        _build_request()
    )

    assert result.envelope.session_id == "session-1"
    assert result.envelope.model_binding_snapshot_ref == (
        "model-binding-snapshot-run-1-code-generation"
    )
    assert result.envelope.runtime_instructions[0].trust_level is (
        ContextTrustLevel.SYSTEM_TRUSTED
    )
    assert result.envelope.stage_contract[0].trust_level is (
        ContextTrustLevel.STAGE_CONTRACT_TRUSTED
    )
    stage_fragment_block = result.envelope.stage_contract[1]
    assert stage_fragment_block.block_id == "prompt-section:stage_prompt_fragment"
    assert stage_fragment_block.trust_level is ContextTrustLevel.STAGE_CONTRACT_TRUSTED
    assert stage_fragment_block.summary.startswith("# Code Generation Stage Prompt")
    assert stage_fragment_block.estimated_chars == len(stage_fragment_block.summary)
    assert stage_fragment_block.prompt_section_refs[0].section_id == (
        "stage_prompt_fragment"
    )
    assert stage_fragment_block.prompt_section_refs[0].prompt_ref.prompt_id == (
        "stage_prompt_fragment.code_generation"
    )
    assert result.envelope.agent_role_prompt[0].trust_level is (
        ContextTrustLevel.AGENT_ROLE_CONFIG
    )
    assert result.envelope.task_objective[0].summary == (
        "Generate the context envelope builder."
    )
    assert result.envelope.specified_action[0].summary == (
        "Return a structured stage decision."
    )
    assert result.rendered_output_ref == (
        "artifact://context-envelopes/run-1/stage-code-generation-1/stage_execution"
    )
    assert result.manifest.rendered_output_ref == result.rendered_output_ref
    assert result.manifest.render_hash == result.render_hash
    assert result.manifest.template_version == "caller-frozen-template-v7"
    assert result.manifest.compression_trigger_token_threshold == 750
    assert [call["process_key"] for call in artifact_store.calls] == [
        "context_manifest"
    ]
    assert artifact_store.calls[0]["artifact_id"] == "artifact-code-generation-1"
    assert artifact_store.calls[0]["process_value"] == result.manifest.model_dump(
        mode="json"
    )
    assert artifact_store.calls[0]["trace_context"] == result.envelope.trace_context
    assert any(
        record.block_id == "prompt-section:stage_prompt_fragment"
        and record.section is ContextEnvelopeSection.STAGE_CONTRACT
        and record.prompt_section_refs[0].prompt_ref.prompt_id
        == "stage_prompt_fragment.code_generation"
        for record in result.manifest.records
    )


def test_stage_prompt_fragment_is_counted_as_pinned_context() -> None:
    from backend.app.context.size_guard import (
        ContextOverflowError,
        ContextSizeGuard,
        ContextTokenEstimator,
    )

    class StageFragmentOnlyEstimator(ContextTokenEstimator):
        def estimate_block(self, block: ContextBlock) -> int:
            if block.block_id == "prompt-section:stage_prompt_fragment":
                return 80
            return 0

        def estimate_text(self, text: str) -> int:
            del text
            return 0

    request = _build_request(
        provider_snapshot=_provider_snapshot().model_copy(
            update={
                "capabilities": _capabilities().model_copy(
                    update={"context_window_tokens": 100}
                )
            }
        ),
        model_binding_snapshot=_model_binding_snapshot().model_copy(
            update={
                "capabilities": _capabilities().model_copy(
                    update={"context_window_tokens": 100}
                )
            }
        ),
        runtime_limit_snapshot=_runtime_limits().model_copy(
            update={
                "context_limits": ContextLimits(compression_threshold_ratio=0.75)
            }
        ),
    )

    with pytest.raises(ContextOverflowError) as exc_info:
        _builder(
            context_size_guard=ContextSizeGuard(
                token_estimator=StageFragmentOnlyEstimator()
            )
        ).build_for_stage_call(request)

    assert exc_info.value.reason == "pinned_context_overflow"
    assert exc_info.value.total_estimated_tokens == 80


def test_structured_output_repair_requires_parse_error_and_uses_repair_prompt_path() -> None:
    with pytest.raises(ValueError, match="parse_error"):
        _builder().build_for_stage_call(
            _build_request(model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR)
        )

    result = _builder().build_for_stage_call(
        _build_request(
            model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR,
            parse_error="Missing required field: decision",
        )
    )

    rendered_text = "\n\n".join(message.content for message in result.rendered_messages)
    assert "Missing required field: decision" in rendered_text
    assert [ref.prompt_id for ref in result.prompt_render_result.metadata.prompt_refs] == [
        "structured_output_repair"
    ]
    assert result.prompt_render_result.metadata.model_call_type is (
        ModelCallType.STRUCTURED_OUTPUT_REPAIR
    )
    assert [
        block.summary for block in result.envelope.runtime_instructions
    ] == [
        (
            "# Structured Output Repair\nRepair only invalid JSON.\nRepair Scope\n"
            "Repair the prior response so it matches the current response_schema.\n"
            "Do not change the stage contract, tool boundary, or structured "
            "output requirement.\nParse error: Missing required field: decision\n"
            "Response schema:\n"
            '{"additionalProperties":false,"properties":{"decision":{"type":"string"}},"required":["decision"],"type":"object"}'
        )
    ]
    assert any(
        record.section is ContextEnvelopeSection.RUNTIME_INSTRUCTIONS
        and record.prompt_section_refs
        and record.prompt_section_refs[0].section_id == "structured_output_repair"
        for record in result.manifest.records
    )


def test_non_prompt_sections_are_appended_in_canonical_order_and_hash_uses_full_messages() -> None:
    result = _builder().build_for_stage_call(_build_request())
    user_message = result.rendered_messages[1].content

    ordered_labels = [
        "Input Artifact Refs",
        "Context References",
        "Working Observations",
        "Reasoning Trace",
        "Recent Observations",
    ]
    offsets = [user_message.index(label) for label in ordered_labels]

    assert offsets == sorted(offsets)
    assert result.render_hash == PromptRenderer.compute_render_hash(
        list(result.rendered_messages)
    )
    assert result.render_hash != result.prompt_render_result.render_hash
    assert result.manifest.render_hash != result.prompt_render_result.render_hash


def test_tool_filtering_honors_stage_contract_allowed_tools_and_registry_ordering() -> None:
    result = _builder().build_for_stage_call(_build_request())

    assert [tool.name for tool in result.envelope.available_tools] == [
        "grep",
        "read_file",
    ]
    assert "write_file" not in "\n\n".join(
        message.content for message in result.rendered_messages
    )


def test_identity_mismatch_fails_early() -> None:
    artifact_store = FakeArtifactStore()
    source_resolver = FakeSourceResolver()
    request = _build_request(trace_context=_trace_context(session_id="session-other"))

    with pytest.raises(ValueError, match="trace_context.session_id"):
        _builder(
            artifact_store=artifact_store,
            source_resolver=source_resolver,
        ).build_for_stage_call(request)

    assert artifact_store.calls == []
    assert source_resolver.stage_inputs_allowed_context_run_ids is None


def test_stage_contract_ref_must_match_graph_definition_contract_ref() -> None:
    with pytest.raises(ValueError, match="stage_contract_ref"):
        _builder().build_for_stage_call(
            _build_request(stage_contract_ref="stage-contract-mismatched")
        )


def test_model_binding_snapshot_must_match_provider_identity() -> None:
    mismatched_binding = _model_binding_snapshot().model_copy(
        update={
            "provider_snapshot_id": "provider-snapshot-run-1-other-model",
            "provider_id": "provider-other",
        }
    )

    with pytest.raises(ValueError, match="model_binding_snapshot.provider_snapshot_id"):
        _builder().build_for_stage_call(
            _build_request(model_binding_snapshot=mismatched_binding)
        )


def test_template_version_is_request_input_and_allowed_context_run_ids_default_to_run_id() -> None:
    source_resolver = FakeSourceResolver()

    result = _builder(source_resolver=source_resolver).build_for_stage_call(
        _build_request(template_version="explicit-template-version-42")
    )

    assert result.manifest.template_version == "explicit-template-version-42"
    assert source_resolver.stage_inputs_allowed_context_run_ids == ("run-1",)
    assert source_resolver.reference_allowed_context_run_ids == ("run-1",)
