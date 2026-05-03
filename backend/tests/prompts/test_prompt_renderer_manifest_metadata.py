from __future__ import annotations

from datetime import UTC, datetime

from backend.app.domain.enums import StageType, ToolRiskLevel
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.prompts.registry import PromptRegistry
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptAssetRead,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptVersionRef,
    PromptSectionRead,
    PromptType,
)
from backend.app.schemas.runtime_settings import SnapshotModelRuntimeCapabilities
from backend.app.tools.protocol import ToolBindableDescription


NOW = datetime(2026, 5, 4, 10, 30, tzinfo=UTC)


def _runtime_asset() -> PromptAssetRead:
    body = "# Runtime Instructions\n\nStay inside platform boundaries."
    return PromptAssetRead(
        prompt_id="runtime_instructions",
        prompt_version="2026-05-04.1",
        prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
        authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
        model_call_type=ModelCallType.STAGE_EXECUTION,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
        source_ref="backend://prompts/runtime/runtime_instructions.md",
        content_hash=PromptAssetRead.calculate_content_hash(body),
        sections=[
            PromptSectionRead(
                section_id="runtime_instructions",
                title="Runtime Instructions",
                body=body,
                cache_scope=PromptCacheScope.GLOBAL_STATIC,
            )
        ],
        applies_to_stage_types=[StageType.SOLUTION_DESIGN],
    )


def _tool_asset() -> PromptAssetRead:
    body = "# Tool Usage\n\nUse only listed tools."
    return PromptAssetRead(
        prompt_id="tool_usage_template",
        prompt_version="2026-05-04.1",
        prompt_type=PromptType.TOOL_USAGE_TEMPLATE,
        authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
        model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
        source_ref="backend://prompts/tools/tool_usage_common.md",
        content_hash=PromptAssetRead.calculate_content_hash(body),
        sections=[
            PromptSectionRead(
                section_id="tool_usage_template",
                title="Tool Usage",
                body=body,
                cache_scope=PromptCacheScope.GLOBAL_STATIC,
            )
        ],
        applies_to_stage_types=[StageType.SOLUTION_DESIGN],
    )


def _tool() -> ToolBindableDescription:
    return ToolBindableDescription(
        name="read_file",
        description="Read a file inside the workspace.",
        input_schema={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.READ_ONLY,
        risk_categories=[],
        schema_version="tool-schema-v1",
    )


def _provider_snapshot() -> ProviderSnapshot:
    return ProviderSnapshot(
        snapshot_id="provider-snapshot-run-1-openai:gpt-5",
        run_id="run-1",
        provider_id="provider-openai",
        display_name="OpenAI",
        provider_source="custom",
        protocol_type="openai_completions_compatible",
        base_url="https://api.openai.test",
        api_key_ref="env:OPENAI_API_KEY",
        model_id="gpt-5",
        is_default_model=True,
        capabilities=SnapshotModelRuntimeCapabilities(
            model_id="gpt-5",
            context_window_tokens=128000,
            max_output_tokens=16000,
            supports_tool_calling=True,
            supports_structured_output=True,
            supports_native_reasoning=True,
        ),
        source_config_version="provider-config-v1",
        created_at=NOW,
    )


def _trace_context() -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="span-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def test_renderer_metadata_round_trips_into_context_manifest_system_prompt_override() -> None:
    from backend.app.context.schemas import (
        ContextEnvelope,
        ContextManifest,
        RenderedOutputKind,
    )
    from backend.app.prompts.renderer import PromptRenderRequest, PromptRenderer

    request = PromptRenderRequest(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        model_call_type=ModelCallType.STAGE_EXECUTION,
        template_snapshot_ref="template-snapshot-run-1",
        system_prompt_ref="template-snapshot://run-1/agent-role/system-prompt",
        stage_contracts={
            StageType.SOLUTION_DESIGN.value: {
                "stage_contract_ref": "stage-contract-solution-design",
                "responsibilities": ["Design the solution."],
                "input_contract": {"requires": ["requirements_summary"]},
                "output_contract": {"produces": ["solution_design"]},
                "structured_artifacts": ["solution_design_document"],
                "allowed_tools": ["read_file"],
            }
        },
        agent_role_prompt="Use the configured solution designer voice.",
        task_objective="Create a solution design.",
        specified_action="Return the structured solution design result.",
        available_tools=[_tool()],
        response_schema={
            "type": "object",
            "properties": {"solution": {"type": "string"}},
            "required": ["solution"],
            "additionalProperties": False,
        },
        output_schema_ref="schema://stage-results/solution-design",
        tool_schema_version="tool-schema-v1",
        created_at=NOW,
    )
    rendered = PromptRenderer(PromptRegistry([_runtime_asset(), _tool_asset()])).render_messages(
        request
    )
    envelope = ContextEnvelope(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        template_snapshot_ref="template-snapshot-run-1",
        stage_contract_ref="stage-contract-solution-design",
        provider_snapshot_ref="provider-snapshot-run-1-openai:gpt-5",
        model_binding_snapshot_ref="model-binding-snapshot-run-1-agent-role",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        available_tools=[_tool()],
        response_schema=request.response_schema,
        trace_context=_trace_context(),
        built_at=NOW,
    )

    manifest = ContextManifest.from_envelope(
        envelope,
        provider_snapshot=_provider_snapshot(),
        prompt_refs=rendered.metadata.prompt_refs,
        render_hash=rendered.render_hash,
        rendered_output_ref=rendered.rendered_output_ref,
        rendered_output_kind=RenderedOutputKind.MESSAGE_SEQUENCE,
        template_version="template-version-7",
        output_schema_ref=request.output_schema_ref,
        tool_schema_version=request.tool_schema_version,
        system_prompt_ref=rendered.system_prompt_ref,
    )

    dumped = manifest.model_dump(mode="json")
    assert dumped["system_prompt_ref"] == rendered.system_prompt_ref
    assert dumped["system_prompt_ref"] == "template-snapshot://run-1/agent-role/system-prompt"
    assert dumped["prompt_refs"][0]["prompt_id"] == "runtime_instructions"
    assert dumped["prompt_asset_sources"] == [
        "backend://prompts/runtime/runtime_instructions.md",
        "backend://prompts/tools/tool_usage_common.md",
    ]
    assert dumped["rendered_output_ref"] == rendered.rendered_output_ref
    assert dumped["render_hash"] == rendered.render_hash
    assert dumped["output_schema"] == request.response_schema


def test_context_manifest_preserves_explicit_empty_prompt_refs() -> None:
    from backend.app.context.schemas import (
        ContextBlock,
        ContextBoundaryAction,
        ContextEnvelope,
        ContextEnvelopeSection,
        ContextManifest,
        ContextSourceRef,
        ContextTrustLevel,
        PromptSectionRef,
        RenderedOutputKind,
    )

    prompt_ref = PromptVersionRef(
        prompt_id="runtime_instructions",
        prompt_version="2026-05-04.1",
        prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
        authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
        source_ref="backend://prompts/runtime/runtime_instructions.md",
        content_hash="a" * 64,
    )
    runtime_block = ContextBlock(
        block_id="runtime-instructions",
        section=ContextEnvelopeSection.RUNTIME_INSTRUCTIONS,
        trust_level=ContextTrustLevel.SYSTEM_TRUSTED,
        boundary_action=ContextBoundaryAction.ALLOW,
        summary="Follow runtime boundaries.",
        content_ref="artifact://context/runtime-instructions",
        sources=[
            ContextSourceRef(
                source_kind="prompt_asset",
                source_ref="backend://prompts/runtime/runtime_instructions.md",
                source_label="runtime_instructions",
            )
        ],
        prompt_section_refs=[
            PromptSectionRef(
                section_id="runtime_instructions",
                title="Runtime Instructions",
                prompt_ref=prompt_ref,
                rendered_content_ref="artifact://prompt-sections/runtime",
                rendered_content_hash="b" * 64,
                cache_scope=PromptCacheScope.GLOBAL_STATIC,
            )
        ],
    )
    envelope = ContextEnvelope(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        template_snapshot_ref="template-snapshot-run-1",
        stage_contract_ref="stage-contract-solution-design",
        provider_snapshot_ref="provider-snapshot-run-1-openai:gpt-5",
        model_binding_snapshot_ref="model-binding-snapshot-run-1-agent-role",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        runtime_instructions=[runtime_block],
        available_tools=[_tool()],
        response_schema={
            "type": "object",
            "properties": {"solution": {"type": "string"}},
            "required": ["solution"],
            "additionalProperties": False,
        },
        trace_context=_trace_context(),
        built_at=NOW,
    )

    manifest = ContextManifest.from_envelope(
        envelope,
        provider_snapshot=_provider_snapshot(),
        prompt_refs=[],
        render_hash="c" * 64,
        rendered_output_ref="artifact://prompt-renders/run-1/stage-run-1/stage_execution",
        rendered_output_kind=RenderedOutputKind.MESSAGE_SEQUENCE,
        template_version="template-version-7",
        output_schema_ref="schema://stage-results/solution-design",
        tool_schema_version="tool-schema-v1",
    )

    assert manifest.prompt_refs == ()
    assert manifest.prompt_asset_sources == ()
    assert manifest.system_prompt_ref is None
