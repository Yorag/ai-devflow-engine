from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pydantic import ValidationError

from backend.app.schemas import common


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _content_hash(markdown: str) -> str:
    body = markdown.split("---\n", 2)[2]
    return sha256(body.encode("utf-8")).hexdigest()


def test_prompt_asset_read_locks_system_prompt_asset_identity_and_hash() -> None:
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAssetRead,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptSectionRead,
        PromptType,
    )

    markdown = (
        "---\n"
        "prompt_id: runtime_instructions\n"
        "prompt_version: 2026-05-01.1\n"
        "---\n"
        "Follow the platform runtime boundaries.\n"
    )
    content_hash = PromptAssetRead.calculate_content_hash(markdown)

    assert {prompt_type.value for prompt_type in PromptType} == {
        "runtime_instructions",
        "stage_prompt_fragment",
        "tool_prompt_fragment",
        "structured_output_repair",
        "compression_prompt",
        "agent_role_seed",
        "tool_usage_template",
    }
    assert {authority.value for authority in PromptAuthorityLevel} == {
        "system_trusted",
        "stage_contract_rendered",
        "user_stage_instruction",
        "agent_role_prompt",
        "tool_description_rendered",
    }
    assert {cache_scope.value for cache_scope in PromptCacheScope} == {
        "global_static",
        "run_static",
        "dynamic_uncached",
    }
    assert {call_type.value for call_type in ModelCallType} == {
        "stage_execution",
        "structured_output_repair",
        "context_compression",
        "tool_call_preparation",
        "validation_pass",
    }

    asset = PromptAssetRead(
        prompt_id="runtime_instructions",
        prompt_version="2026-05-01.1",
        prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
        authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
        model_call_type=ModelCallType.STAGE_EXECUTION,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
        source_ref="backend://prompts/runtime_instructions.md",
        content_hash=content_hash,
        sections=[
            PromptSectionRead(
                section_id="runtime-boundaries",
                title="Runtime Boundaries",
                body="Follow the platform runtime boundaries.",
                cache_scope=PromptCacheScope.GLOBAL_STATIC,
            )
        ],
        applies_to_stage_types=[
            common.StageType.REQUIREMENT_ANALYSIS,
            common.StageType.SOLUTION_DESIGN,
        ],
    )

    assert content_hash == _content_hash(markdown)
    assert content_hash != sha256(markdown.encode("utf-8")).hexdigest()
    dumped = asset.model_dump(mode="json")
    assert dumped["prompt_id"] == "runtime_instructions"
    assert dumped["prompt_version"] == "2026-05-01.1"
    assert dumped["prompt_type"] == "runtime_instructions"
    assert dumped["authority_level"] == "system_trusted"
    assert dumped["model_call_type"] == "stage_execution"
    assert dumped["cache_scope"] == "global_static"
    assert dumped["source_ref"] == "backend://prompts/runtime_instructions.md"
    assert dumped["content_hash"] == content_hash
    assert dumped["sections"][0]["body"] == "Follow the platform runtime boundaries."
    assert dumped["applies_to_stage_types"] == [
        "requirement_analysis",
        "solution_design",
    ]
    assert "front_matter" not in dumped
    assert "compression_prompt" not in dumped


def test_tool_prompt_fragment_asset_uses_static_tool_description_contract() -> None:
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAssetRead,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptSectionRead,
        PromptType,
    )

    valid_section = PromptSectionRead(
        section_id="tool_prompt_fragment.read_file",
        title="Read File Tool Prompt",
        body="Use read_file only for workspace text reads.",
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
    )
    asset = PromptAssetRead(
        prompt_id="tool_prompt_fragment.read_file",
        prompt_version="2026-05-06.1",
        prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
        authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
        model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
        source_ref="backend://prompts/tools/read_file.md",
        content_hash="1" * 64,
        sections=[valid_section],
    )

    dumped = asset.model_dump(mode="json")
    assert dumped["prompt_type"] == "tool_prompt_fragment"
    assert dumped["authority_level"] == "tool_description_rendered"
    assert dumped["model_call_type"] == "tool_call_preparation"
    assert dumped["cache_scope"] == "global_static"

    with pytest.raises(ValidationError):
        PromptAssetRead(
            prompt_id="tool_prompt_fragment.read_file",
            prompt_version="2026-05-06.1",
            prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
            authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
            model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
            cache_scope=PromptCacheScope.RUN_STATIC,
            source_ref="backend://prompts/tools/read_file.md",
            content_hash="2" * 64,
            sections=[valid_section],
        )


def test_prompt_version_refs_enter_context_manifest_and_compressed_context_metadata() -> None:
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptRenderMetadata,
        PromptType,
        PromptVersionRef,
    )

    prompt_ref = PromptVersionRef(
        prompt_id="compression_prompt",
        prompt_version="2026-05-01.1",
        prompt_type=PromptType.COMPRESSION_PROMPT,
        authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
        cache_scope=PromptCacheScope.RUN_STATIC,
        source_ref="backend://prompts/compression_prompt.md",
        content_hash="a" * 64,
    )
    metadata = PromptRenderMetadata(
        render_id="render-context-compression-1",
        model_call_type=ModelCallType.CONTEXT_COMPRESSION,
        prompt_refs=[prompt_ref],
        rendered_prompt_hash="b" * 64,
        section_order=["compression-goal", "compression-schema"],
        template_snapshot_ref="template-snapshot-1",
        stage_contract_ref="stage-contract-context-compression",
        tool_schema_version="tool-schema-v1",
        context_manifest_ref="context-manifest-1",
        compressed_context_block_ref="compressed-context-1",
        created_at=NOW,
    )

    dumped = metadata.model_dump(mode="json")
    assert dumped["prompt_refs"][0]["prompt_id"] == "compression_prompt"
    assert dumped["prompt_refs"][0]["prompt_version"] == "2026-05-01.1"
    assert dumped["prompt_refs"][0]["prompt_type"] == "compression_prompt"
    assert dumped["prompt_refs"][0]["cache_scope"] == "run_static"
    assert dumped["context_manifest_ref"] == "context-manifest-1"
    assert dumped["compressed_context_block_ref"] == "compressed-context-1"
    assert dumped["rendered_prompt_hash"] == "b" * 64


def test_prompt_asset_requires_front_matter_version_as_schema_truth() -> None:
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAssetRead,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptSectionRead,
        PromptType,
    )

    with pytest.raises(ValidationError):
        PromptAssetRead(
            prompt_id="runtime_instructions",
            prompt_version="",
            prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
            authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
            model_call_type=ModelCallType.STAGE_EXECUTION,
            cache_scope=PromptCacheScope.GLOBAL_STATIC,
            source_ref="backend://prompts/runtime_instructions.md",
            content_hash="c" * 64,
            sections=[
                PromptSectionRead(
                    section_id="runtime-boundaries",
                    title="Runtime Boundaries",
                    body="Follow the platform runtime boundaries.",
                    cache_scope=PromptCacheScope.GLOBAL_STATIC,
                )
            ],
        )

    with pytest.raises(ValidationError):
        PromptAssetRead(
            prompt_id="runtime_instructions",
            prompt_version="2026-05-01.1",
            prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
            authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
            model_call_type=ModelCallType.STAGE_EXECUTION,
            cache_scope=PromptCacheScope.GLOBAL_STATIC,
            source_ref="backend://prompts/runtime_instructions-2026-05-01.1.md",
            content_hash="d" * 64,
            sections=[
                PromptSectionRead(
                    section_id="runtime-boundaries",
                    title="Runtime Boundaries",
                    body="Follow the platform runtime boundaries.",
                    cache_scope=PromptCacheScope.GLOBAL_STATIC,
                )
            ],
        )


def test_prompt_asset_rejects_user_prompt_authority_upgrade_and_config_sources() -> None:
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAssetRead,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptSectionRead,
        PromptType,
    )

    valid_section = PromptSectionRead(
        section_id="seed",
        title="Seed",
        body="Analyze requirements.",
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
    )

    with pytest.raises(ValidationError):
        PromptAssetRead(
            prompt_id="agent_role_seed",
            prompt_version="2026-05-01.1",
            prompt_type=PromptType.AGENT_ROLE_SEED,
            authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
            model_call_type=ModelCallType.STAGE_EXECUTION,
            cache_scope=PromptCacheScope.GLOBAL_STATIC,
            source_ref="backend://prompts/agent_role_seed.md",
            content_hash="e" * 64,
            sections=[valid_section],
        )

    with pytest.raises(ValidationError):
        PromptAssetRead(
            prompt_id="runtime_instructions",
            prompt_version="2026-05-01.1",
            prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
            authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
            model_call_type=ModelCallType.STAGE_EXECUTION,
            cache_scope=PromptCacheScope.GLOBAL_STATIC,
            source_ref="user_template://template-feature/system_prompt",
            content_hash="f" * 64,
            sections=[valid_section],
        )


def test_compression_prompt_is_only_a_system_asset_reference() -> None:
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAssetRead,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptSectionRead,
        PromptType,
    )

    valid_section = PromptSectionRead(
        section_id="compression",
        title="Compression",
        body="Compress context into the required schema.",
        cache_scope=PromptCacheScope.RUN_STATIC,
    )

    compression_prompt = PromptAssetRead(
        prompt_id="compression_prompt",
        prompt_version="2026-05-01.1",
        prompt_type=PromptType.COMPRESSION_PROMPT,
        authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
        model_call_type=ModelCallType.CONTEXT_COMPRESSION,
        cache_scope=PromptCacheScope.RUN_STATIC,
        source_ref="backend://prompts/compression_prompt.md",
        content_hash="1" * 64,
        sections=[valid_section],
    )

    assert compression_prompt.prompt_id == "compression_prompt"
    assert compression_prompt.prompt_version == "2026-05-01.1"

    with pytest.raises(ValidationError):
        PromptAssetRead(
            prompt_id="compression_prompt",
            prompt_version="2026-05-01.1",
            prompt_type=PromptType.COMPRESSION_PROMPT,
            authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
            model_call_type=ModelCallType.CONTEXT_COMPRESSION,
            cache_scope=PromptCacheScope.RUN_STATIC,
            source_ref="platform_runtime_settings://compression_prompt",
            content_hash="2" * 64,
            sections=[valid_section],
        )

    with pytest.raises(ValidationError):
        PromptAssetRead(
            **{
                **compression_prompt.model_dump(mode="python"),
                "compression_prompt": "Summarize this run.",
            }
        )


def test_prompt_section_ref_keeps_prompt_version_metadata_out_of_model_visible_content() -> None:
    from backend.app.context.schemas import PromptSectionRef
    from backend.app.schemas.prompts import (
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptType,
        PromptVersionRef,
    )

    prompt_ref = PromptVersionRef(
        prompt_id="runtime_instructions",
        prompt_version="2026-05-04.1",
        prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
        authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
        source_ref="backend://prompts/runtime/runtime_instructions.md",
        content_hash="e" * 64,
    )
    section = PromptSectionRef(
        section_id="runtime-boundaries",
        title="Runtime Boundaries",
        prompt_ref=prompt_ref,
        rendered_content_ref="artifact://prompt-sections/runtime-boundaries",
        rendered_content_hash="f" * 64,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
    )

    dumped = section.model_dump(mode="json")
    assert dumped["prompt_ref"]["prompt_id"] == "runtime_instructions"
    assert dumped["rendered_content_ref"] == "artifact://prompt-sections/runtime-boundaries"
    assert "body" not in dumped
