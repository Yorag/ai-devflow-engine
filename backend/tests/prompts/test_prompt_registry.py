from __future__ import annotations

from backend.app.schemas.prompts import (
    PromptAssetRead,
    PromptType,
    PromptVersionRef,
)


EXPECTED_AGENT_ROLE_SEED_IDS = {
    "agent_role_seed.requirement_analyst",
    "agent_role_seed.solution_designer",
    "agent_role_seed.code_generator",
    "agent_role_seed.test_runner",
    "agent_role_seed.code_reviewer",
}
EXPECTED_TOOL_PROMPT_FRAGMENT_IDS = {
    "tool_prompt_fragment.bash",
    "tool_prompt_fragment.create_code_review_request",
    "tool_prompt_fragment.create_commit",
    "tool_prompt_fragment.edit_file",
    "tool_prompt_fragment.glob",
    "tool_prompt_fragment.grep",
    "tool_prompt_fragment.prepare_branch",
    "tool_prompt_fragment.push_branch",
    "tool_prompt_fragment.read_delivery_snapshot",
    "tool_prompt_fragment.read_file",
    "tool_prompt_fragment.write_file",
}


def test_load_builtin_assets_registers_required_prompt_assets() -> None:
    from backend.app.prompts.registry import PromptRegistry

    registry = PromptRegistry.load_builtin_assets()

    runtime = registry.get("runtime_instructions")
    repair = registry.get("structured_output_repair")
    compression = registry.get("compression_prompt")
    tool_usage = registry.get("tool_usage_template")
    role_assets = registry.list_by_type(PromptType.AGENT_ROLE_SEED)
    tool_prompt_fragments = registry.list_by_type(PromptType.TOOL_PROMPT_FRAGMENT)

    assert runtime.prompt_id == "runtime_instructions"
    assert runtime.prompt_type is PromptType.RUNTIME_INSTRUCTIONS
    assert runtime.source_ref == "backend://prompts/runtime/runtime_instructions.md"
    assert runtime.sections[0].body.startswith("# Runtime Instructions")
    assert "prompt_id:" not in runtime.sections[0].body
    assert repair.prompt_type is PromptType.STRUCTURED_OUTPUT_REPAIR
    assert compression.prompt_type is PromptType.COMPRESSION_PROMPT
    assert tool_usage.prompt_type is PromptType.TOOL_USAGE_TEMPLATE
    assert {asset.prompt_id for asset in role_assets} == EXPECTED_AGENT_ROLE_SEED_IDS
    assert {asset.prompt_id for asset in tool_prompt_fragments} == (
        EXPECTED_TOOL_PROMPT_FRAGMENT_IDS
    )


def test_resolve_version_ref_returns_the_same_registered_asset() -> None:
    from backend.app.prompts.registry import PromptRegistry

    registry = PromptRegistry.load_builtin_assets()
    runtime = registry.get("runtime_instructions")
    resolved = registry.resolve_version_ref(
        PromptVersionRef(
            prompt_id=runtime.prompt_id,
            prompt_version=runtime.prompt_version,
            prompt_type=runtime.prompt_type,
            authority_level=runtime.authority_level,
            cache_scope=runtime.cache_scope,
            source_ref=runtime.source_ref,
            content_hash=runtime.content_hash,
        )
    )

    assert resolved == runtime
    assert [asset.prompt_id for asset in registry.list_by_type(PromptType.RUNTIME_INSTRUCTIONS)] == [
        "runtime_instructions"
    ]


def test_compute_content_hash_matches_prompt_asset_schema_logic() -> None:
    from backend.app.prompts.registry import PromptRegistry

    markdown = (
        "---\n"
        "prompt_id: runtime_instructions\n"
        "prompt_version: 2026-05-04.1\n"
        "---\n"
        "# Runtime Instructions\n\nStay inside platform boundaries.\n"
    )

    assert PromptRegistry.compute_content_hash(markdown) == PromptAssetRead.calculate_content_hash(markdown)
