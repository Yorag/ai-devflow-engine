from __future__ import annotations

from datetime import UTC, datetime
from shutil import copytree
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
    ProviderProtocolType,
    ProviderSource,
    StageType,
)
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.prompts.definitions import PROMPT_ASSET_ROOT
from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry
from backend.app.prompts.renderer import PromptRenderRequest, PromptRenderer
from backend.app.providers.langchain_adapter import (
    ModelCallResult,
    ModelCallTraceSummary,
    ModelCallUsage,
)
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptType,
)
from backend.app.schemas.runtime_settings import SnapshotModelRuntimeCapabilities


NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


class RecordingArtifactStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def append_process_record(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


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


def _provider_snapshot() -> ProviderSnapshot:
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
            context_window_tokens=128000,
            max_output_tokens=4096,
            supports_tool_calling=True,
            supports_structured_output=True,
            supports_native_reasoning=True,
        ),
        source_config_version="provider-config-v1",
        created_at=NOW,
    )


def _working_observation() -> ContextBlock:
    return ContextBlock(
        block_id="working-observation-1",
        section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
        trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
        boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
        summary="Earlier stage chose the frozen provider snapshot path.",
        content_ref="artifact://process/run-1/working-observation-1",
        sources=(
            ContextSourceRef(
                source_kind="process_ref",
                source_ref="artifact://process/run-1/working-observation-1",
                source_label="working-observation-1",
            ),
        ),
        estimated_chars=64,
    )


def _envelope() -> ContextEnvelope:
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
        working_observations=(_working_observation(),),
        response_schema={"type": "object"},
        trace_context=_trace_context(),
        built_at=NOW,
    )


def _manifest(envelope: ContextEnvelope) -> ContextManifest:
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
        compression_trigger_token_threshold=96000,
    )


def _render_request(
    *,
    agent_role_prompt: str | None = "User-editable role text must stay outside compression assets.",
) -> PromptRenderRequest:
    return PromptRenderRequest(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        model_call_type=ModelCallType.CONTEXT_COMPRESSION,
        template_snapshot_ref="template-snapshot-run-1",
        system_prompt_ref="template-snapshot://run-1/agent-role/system-prompt",
        stage_contracts={
            StageType.CODE_GENERATION.value: {
                "stage_type": StageType.CODE_GENERATION.value,
                "stage_contract_ref": "stage-contract-code-generation",
                "allowed_tools": [],
            }
        },
        agent_role_prompt=agent_role_prompt,
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


def _model_call_result() -> ModelCallResult:
    return ModelCallResult(
        provider_snapshot_id="provider-snapshot-run-1",
        model_binding_snapshot_id="model-binding-compression-run-1",
        model_call_type=ModelCallType.CONTEXT_COMPRESSION,
        structured_output={
            "summary": "Compressed context keeps durable decisions.",
            "decisions_made": ["Use the built-in compression prompt asset."],
            "files_observed": ["backend/app/prompts/renderer.py"],
            "files_modified": [],
            "failed_attempts": [],
            "open_issues": [],
            "evidence_refs": ["stage-process://stage-run-1/full"],
        },
        provider_error_code=None,
        provider_error_message=None,
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


def _renderer() -> PromptRenderer:
    return PromptRenderer(PromptRegistry.load_builtin_assets())


def test_compression_prompt_is_builtin_asset_not_user_or_environment_configuration() -> None:
    registry = PromptRegistry.load_builtin_assets()
    compression = registry.get("compression_prompt")

    assert compression.prompt_type is PromptType.COMPRESSION_PROMPT
    assert compression.authority_level is PromptAuthorityLevel.SYSTEM_TRUSTED
    assert compression.cache_scope is PromptCacheScope.RUN_STATIC
    assert compression.source_ref.startswith("backend://prompts/compression/")
    assert "prompt_id:" not in compression.sections[0].body
    assert "source_ref:" not in compression.sections[0].body
    assert "environment" not in compression.source_ref
    assert "template" not in compression.source_ref
    assert "frontend" not in compression.source_ref

    compression_assets = registry.list_by_type(PromptType.COMPRESSION_PROMPT)
    assert [asset.prompt_id for asset in compression_assets] == ["compression_prompt"]
    assert all(
        "User-editable role text" not in section.body
        for asset in compression_assets
        for section in asset.sections
    )


def test_prompt_renderer_records_compression_prompt_version_and_hash_without_template_field() -> None:
    renderer = _renderer()
    result = renderer.render_messages(_render_request())
    second_result = renderer.render_messages(_render_request())
    metadata = result.metadata.model_dump(mode="json")

    assert [ref.prompt_id for ref in result.metadata.prompt_refs] == [
        "compression_prompt"
    ]
    prompt_ref = result.metadata.prompt_refs[0]
    assert prompt_ref.prompt_version
    assert prompt_ref.source_ref.startswith("backend://prompts/compression/")
    assert result.metadata.rendered_prompt_hash == second_result.metadata.rendered_prompt_hash
    assert result.render_hash == result.metadata.rendered_prompt_hash
    assert result.metadata.model_call_type is ModelCallType.CONTEXT_COMPRESSION
    assert result.system_prompt_ref == "template-snapshot://run-1/agent-role/system-prompt"
    assert "User-editable role text" not in "\n\n".join(
        message.content for message in result.messages
    )
    assert "agent_role_prompt" not in result.section_order
    assert "agent_role_prompt" not in metadata["section_order"]
    assert "system_prompt_ref" not in metadata


def test_compression_process_record_references_prompt_version_and_render_hash() -> None:
    from backend.app.context.compression import (
        ContextCompressionRequest,
        ContextCompressionRunner,
    )

    artifact_store = RecordingArtifactStore()
    provider_adapter = FakeProviderAdapter(_model_call_result())
    envelope = _envelope()

    result = ContextCompressionRunner(
        prompt_renderer=_renderer(),
        artifact_store=artifact_store,  # type: ignore[arg-type]
        now=lambda: NOW,
    ).compress(
        ContextCompressionRequest(
            envelope=envelope,
            manifest=_manifest(envelope),
            stage_artifact_id="artifact-stage-1",
            trace_context=_trace_context(),
            full_trace_ref="stage-process://stage-run-1/full",
            covered_step_range="1-8",
            compression_trigger_reason="compression_threshold_exceeded",
            provider_adapter=provider_adapter,
        )
    )

    assert result.compressed_context_block is not None
    compressed_block = result.compressed_context_block
    compression_asset = PromptRegistry.load_builtin_assets().get("compression_prompt")
    assert compressed_block.compression_prompt_id == "compression_prompt"
    assert compressed_block.compression_prompt_version == compression_asset.prompt_version
    assert len(compressed_block.compression_render_hash) == 64
    assert all(character in "0123456789abcdef" for character in compressed_block.compression_render_hash)
    assert provider_adapter.calls[0]["model_call_type"] is ModelCallType.CONTEXT_COMPRESSION
    records_by_key = {
        call["process_key"]: call["process_value"] for call in artifact_store.calls
    }
    assert set(records_by_key) == {
        "compressed_context_block",
        "context_compression_model_call_trace",
    }

    compressed_records = records_by_key["compressed_context_block"]
    trace_records = records_by_key["context_compression_model_call_trace"]
    assert isinstance(compressed_records, list)
    assert isinstance(trace_records, list)
    assert compressed_records[0]["compression_prompt_id"] == "compression_prompt"
    assert compressed_records[0]["compression_prompt_version"] == (
        compressed_block.compression_prompt_version
    )
    assert compressed_records[0]["compression_render_hash"] == (
        compressed_block.compression_render_hash
    )
    assert trace_records[0]["model_call_type"] == "context_compression"


def test_prompt_registry_rejects_user_config_sources_for_builtin_prompt_assets(tmp_path) -> None:
    forbidden_source_refs = [
        "env:COMPRESSION_PROMPT",
        "frontend://settings/prompts/compression_prompt",
        "template-snapshot://run-1/agent-role/system-prompt",
    ]

    for index, source_ref in enumerate(forbidden_source_refs, start=1):
        asset_root = tmp_path / f"asset-root-{index}"
        copytree(PROMPT_ASSET_ROOT, asset_root)
        asset_path = asset_root / "compression" / "compression_context.md"
        asset_path.write_text(
            "\n".join(
                [
                    "---",
                    "prompt_id: compression_prompt",
                    "prompt_version: 2026-05-04.1",
                    "prompt_type: compression_prompt",
                    "authority_level: system_trusted",
                    "model_call_type: context_compression",
                    "cache_scope: run_static",
                    f"source_ref: {source_ref}",
                    "---",
                    "# Context Compression",
                    "",
                    "Compress prior context without reading user configuration.",
                ]
            ),
            encoding="utf-8",
        )

        with pytest.raises(PromptAssetMetadataError):
            PromptRegistry.load_builtin_assets(asset_root=asset_root)
