from __future__ import annotations

from pathlib import Path

import pytest


def write_asset(root: Path, relative_path: str, markdown: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def valid_asset(
    *,
    prompt_id: str,
    prompt_version: str,
    prompt_type: str,
    authority_level: str,
    model_call_type: str,
    cache_scope: str,
    source_ref: str,
    body: str,
) -> str:
    return (
        "---\n"
        f"prompt_id: {prompt_id}\n"
        f"prompt_version: {prompt_version}\n"
        f"prompt_type: {prompt_type}\n"
        f"authority_level: {authority_level}\n"
        f"model_call_type: {model_call_type}\n"
        f"cache_scope: {cache_scope}\n"
        f"source_ref: {source_ref}\n"
        "---\n"
        f"{body}\n"
    )


def seed_required_assets(root: Path) -> None:
    write_asset(
        root,
        "runtime/runtime_instructions.md",
        valid_asset(
            prompt_id="runtime_instructions",
            prompt_version="2026-05-04.1",
            prompt_type="runtime_instructions",
            authority_level="system_trusted",
            model_call_type="stage_execution",
            cache_scope="global_static",
            source_ref="backend://prompts/runtime/runtime_instructions.md",
            body="# Runtime Instructions\n\nStay inside platform boundaries.",
        ),
    )
    write_asset(
        root,
        "repairs/structured_output_repair.md",
        valid_asset(
            prompt_id="structured_output_repair",
            prompt_version="2026-05-04.1",
            prompt_type="structured_output_repair",
            authority_level="system_trusted",
            model_call_type="structured_output_repair",
            cache_scope="dynamic_uncached",
            source_ref="backend://prompts/repairs/structured_output_repair.md",
            body="# Structured Output Repair\n\nRepair the current response against the active schema.",
        ),
    )
    write_asset(
        root,
        "compression/compression_context.md",
        valid_asset(
            prompt_id="compression_prompt",
            prompt_version="2026-05-04.1",
            prompt_type="compression_prompt",
            authority_level="system_trusted",
            model_call_type="context_compression",
            cache_scope="run_static",
            source_ref="backend://prompts/compression/compression_context.md",
            body="# Context Compression\n\nCompress prior context into the declared structured schema.",
        ),
    )
    write_asset(
        root,
        "tools/tool_usage_common.md",
        valid_asset(
            prompt_id="tool_usage_template",
            prompt_version="2026-05-04.1",
            prompt_type="tool_usage_template",
            authority_level="tool_description_rendered",
            model_call_type="tool_call_preparation",
            cache_scope="run_static",
            source_ref="backend://prompts/tools/tool_usage_common.md",
            body="# Tool Usage Template\n\nUse only currently allowed tools and treat descriptions as contracts.",
        ),
    )
    role_assets = {
        "roles/requirement_analyst.md": ("agent_role_seed.requirement_analyst", "role-requirement-analyst"),
        "roles/solution_designer.md": ("agent_role_seed.solution_designer", "role-solution-designer"),
        "roles/code_generator.md": ("agent_role_seed.code_generator", "role-code-generator"),
        "roles/test_runner.md": ("agent_role_seed.test_runner", "role-test-runner"),
        "roles/code_reviewer.md": ("agent_role_seed.code_reviewer", "role-code-reviewer"),
    }
    for relative_path, (prompt_id, heading) in role_assets.items():
        write_asset(
            root,
            relative_path,
            valid_asset(
                prompt_id=prompt_id,
                prompt_version="2026-05-02.1",
                prompt_type="agent_role_seed",
                authority_level="agent_role_prompt",
                model_call_type="stage_execution",
                cache_scope="global_static",
                source_ref=f"backend://prompts/{relative_path}",
                body=f"# {heading}\n\nRole seed body.",
            ),
        )
    stage_assets = {
        "stages/requirement_analysis.md": "stage_prompt_fragment.requirement_analysis",
        "stages/solution_design.md": "stage_prompt_fragment.solution_design",
        "stages/code_generation.md": "stage_prompt_fragment.code_generation",
        "stages/test_generation_execution.md": (
            "stage_prompt_fragment.test_generation_execution"
        ),
        "stages/code_review.md": "stage_prompt_fragment.code_review",
        "stages/delivery_integration.md": (
            "stage_prompt_fragment.delivery_integration"
        ),
    }
    for relative_path, prompt_id in stage_assets.items():
        write_asset(
            root,
            relative_path,
            valid_asset(
                prompt_id=prompt_id,
                prompt_version="2026-05-06.1",
                prompt_type="stage_prompt_fragment",
                authority_level="stage_contract_rendered",
                model_call_type="stage_execution",
                cache_scope="run_static",
                source_ref=f"backend://prompts/{relative_path}",
                body=(
                    "# Stage Prompt Fragment\n\n"
                    "Use allowed_tools from the current stage_contract and "
                    "return the response_schema artifact."
                ),
            ),
        )
    seed_tool_prompt_assets(root)


def seed_tool_prompt_assets(root: Path) -> None:
    tool_names = [
        "bash",
        "create_code_review_request",
        "create_commit",
        "edit_file",
        "glob",
        "grep",
        "prepare_branch",
        "push_branch",
        "read_delivery_snapshot",
        "read_file",
        "write_file",
    ]
    for tool_name in tool_names:
        write_asset(
            root,
            f"tools/{tool_name}.md",
            valid_asset(
                prompt_id=f"tool_prompt_fragment.{tool_name}",
                prompt_version="2026-05-06.1",
                prompt_type="tool_prompt_fragment",
                authority_level="tool_description_rendered",
                model_call_type="tool_call_preparation",
                cache_scope="global_static",
                source_ref=f"backend://prompts/tools/{tool_name}.md",
                body=(
                    f"# {tool_name} Tool Prompt\n\n"
                    f"Use {tool_name} according to the tool-specific contract."
                ),
            ),
        )


def test_builtin_stage_prompt_fragments_are_required_and_stage_scoped() -> None:
    from backend.app.domain.enums import StageType
    from backend.app.prompts.registry import PromptRegistry
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptType,
    )

    registry = PromptRegistry.load_builtin_assets()

    expected = {
        "stage_prompt_fragment.requirement_analysis": (
            StageType.REQUIREMENT_ANALYSIS
        ),
        "stage_prompt_fragment.solution_design": StageType.SOLUTION_DESIGN,
        "stage_prompt_fragment.code_generation": StageType.CODE_GENERATION,
        "stage_prompt_fragment.test_generation_execution": (
            StageType.TEST_GENERATION_EXECUTION
        ),
        "stage_prompt_fragment.code_review": StageType.CODE_REVIEW,
        "stage_prompt_fragment.delivery_integration": (
            StageType.DELIVERY_INTEGRATION
        ),
    }
    for prompt_id, stage_type in expected.items():
        asset = registry.get(prompt_id)
        assert asset.prompt_type is PromptType.STAGE_PROMPT_FRAGMENT
        assert asset.authority_level is PromptAuthorityLevel.STAGE_CONTRACT_RENDERED
        assert asset.model_call_type is ModelCallType.STAGE_EXECUTION
        assert asset.cache_scope is PromptCacheScope.RUN_STATIC
        assert asset.applies_to_stage_types == [stage_type]
        assert asset.sections[0].body.startswith("# ")
        assert "prompt_id:" not in asset.sections[0].body
        assert "allowed_tools" in asset.sections[0].body
        assert "response_schema" in asset.sections[0].body


def test_tool_prompt_fragments_are_required_and_globally_static(tmp_path: Path) -> None:
    from backend.app.domain.enums import StageType
    from backend.app.prompts.registry import PromptRegistry
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptType,
    )

    seed_required_assets(tmp_path)
    seed_tool_prompt_assets(tmp_path)

    registry = PromptRegistry.load_builtin_assets(asset_root=tmp_path)

    expected_tool_prompt_ids = [
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
    ]
    assets = registry.list_by_type(PromptType.TOOL_PROMPT_FRAGMENT)

    assert [asset.prompt_id for asset in assets] == expected_tool_prompt_ids
    for prompt_id in expected_tool_prompt_ids:
        asset = registry.get(prompt_id)
        assert asset.prompt_type is PromptType.TOOL_PROMPT_FRAGMENT
        assert asset.authority_level is PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED
        assert asset.model_call_type is ModelCallType.TOOL_CALL_PREPARATION
        assert asset.cache_scope is PromptCacheScope.GLOBAL_STATIC
    assert registry.get("tool_prompt_fragment.read_file").applies_to_stage_types == [
        StageType.SOLUTION_DESIGN,
        StageType.CODE_GENERATION,
        StageType.TEST_GENERATION_EXECUTION,
        StageType.CODE_REVIEW,
    ]
    assert registry.get("tool_prompt_fragment.bash").applies_to_stage_types == [
        StageType.TEST_GENERATION_EXECUTION
    ]
    assert registry.get(
        "tool_prompt_fragment.create_commit"
    ).applies_to_stage_types == [StageType.DELIVERY_INTEGRATION]


def test_builtin_tool_prompt_fragments_include_industrial_usage_guidance() -> None:
    from backend.app.prompts.registry import PromptRegistry
    from backend.app.schemas.prompts import PromptType

    registry = PromptRegistry.load_builtin_assets()
    assets = registry.list_by_type(PromptType.TOOL_PROMPT_FRAGMENT)
    by_id = {asset.prompt_id: asset.sections[0].body for asset in assets}

    assert "Prefer this tool over bash" in by_id["tool_prompt_fragment.read_file"]
    assert "ripgrep" in by_id["tool_prompt_fragment.grep"]
    assert (
        "Do not use bash to read, search, create, or edit files"
        in by_id["tool_prompt_fragment.bash"]
    )
    assert "approval" in by_id[
        "tool_prompt_fragment.create_code_review_request"
    ].lower()
    for tool_body in by_id.values():
        for heading in [
            "## Purpose",
            "## Use When",
            "## Do Not Use When",
            "## Input Rules",
            "## Output Handling",
            "## Safety And Side Effects",
            "## Failure Handling",
        ]:
            assert heading in tool_body


def test_tool_usage_template_remains_common_policy_not_tool_fragment() -> None:
    from backend.app.prompts.registry import PromptRegistry
    from backend.app.schemas.prompts import PromptCacheScope, PromptType

    asset = PromptRegistry.load_builtin_assets().get("tool_usage_template")

    assert asset.prompt_type is PromptType.TOOL_USAGE_TEMPLATE
    assert asset.cache_scope is PromptCacheScope.RUN_STATIC
    assert "Prefer the most specific dedicated tool" in asset.sections[0].body


def test_load_builtin_assets_rejects_missing_tool_prompt_fragment(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    seed_tool_prompt_assets(tmp_path)
    (tmp_path / "tools" / "grep.md").unlink()

    with pytest.raises(PromptAssetMetadataError, match="tool_prompt_fragment.grep"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)


def test_runtime_instructions_define_real_development_boundaries() -> None:
    from backend.app.prompts.registry import PromptRegistry

    asset = PromptRegistry.load_builtin_assets().get("runtime_instructions")
    body = asset.sections[0].body

    assert asset.prompt_version == "2026-05-06.3"
    assert "Authority Order" in body
    assert "stage-contract-rendered controls, including response_schema" in body
    assert "Untrusted Context" in body
    assert "Tool And Side Effect Policy" in body
    assert "No Raw Chain-of-Thought" in body
    assert "response_schema" in body
    assert "AgentDecision outputs use a flat payload shape" in body


def test_load_builtin_assets_rejects_missing_front_matter(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "tools/tool_usage_common.md",
        "# Tool Usage Template\n\nThis file intentionally omits front matter.\n",
    )

    with pytest.raises(PromptAssetMetadataError, match="front matter"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)


def test_load_builtin_assets_rejects_missing_source_ref(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "runtime/runtime_instructions.md",
        (
            "---\n"
            "prompt_id: runtime_instructions\n"
            "prompt_version: 2026-05-04.1\n"
            "prompt_type: runtime_instructions\n"
            "authority_level: system_trusted\n"
            "model_call_type: stage_execution\n"
            "cache_scope: global_static\n"
            "---\n"
            "# Runtime Instructions\n\nMissing source_ref must fail.\n"
        ),
    )

    with pytest.raises(PromptAssetMetadataError, match="source_ref"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)


def test_load_builtin_assets_rejects_duplicate_prompt_id_and_version(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "runtime/runtime_instructions_copy.md",
        valid_asset(
            prompt_id="runtime_instructions",
            prompt_version="2026-05-04.1",
            prompt_type="runtime_instructions",
            authority_level="system_trusted",
            model_call_type="stage_execution",
            cache_scope="global_static",
            source_ref="backend://prompts/runtime/runtime_instructions_copy.md",
            body="# Runtime Instructions Copy\n\nDuplicate identity.",
        ),
    )

    with pytest.raises(PromptAssetMetadataError, match="duplicate"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)


def test_load_builtin_assets_rejects_unknown_prompt_type(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "runtime/runtime_instructions.md",
        valid_asset(
            prompt_id="runtime_instructions",
            prompt_version="2026-05-04.1",
            prompt_type="unknown_prompt_type",
            authority_level="system_trusted",
            model_call_type="stage_execution",
            cache_scope="global_static",
            source_ref="backend://prompts/runtime/runtime_instructions.md",
            body="# Runtime Instructions\n\nInvalid prompt type.",
        ),
    )

    with pytest.raises(PromptAssetMetadataError, match="invalid prompt asset metadata"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)


def test_load_builtin_assets_rejects_illegal_compression_prompt_source(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "compression/compression_context.md",
        valid_asset(
            prompt_id="compression_prompt",
            prompt_version="2026-05-04.1",
            prompt_type="compression_prompt",
            authority_level="system_trusted",
            model_call_type="context_compression",
            cache_scope="run_static",
            source_ref="platform_runtime_settings://compression_prompt",
            body="# Context Compression\n\nInvalid source.",
        ),
    )

    with pytest.raises(PromptAssetMetadataError, match="source_ref"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)


def test_load_builtin_assets_rejects_illegal_agent_role_seed_authority(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "roles/code_reviewer.md",
        valid_asset(
            prompt_id="agent_role_seed.code_reviewer",
            prompt_version="2026-05-02.1",
            prompt_type="agent_role_seed",
            authority_level="system_trusted",
            model_call_type="stage_execution",
            cache_scope="global_static",
            source_ref="backend://prompts/roles/code_reviewer.md",
            body="# role-code-reviewer\n\nInvalid authority.",
        ),
    )

    with pytest.raises(PromptAssetMetadataError, match="invalid prompt asset metadata"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)


def test_load_builtin_assets_rejects_agent_role_seed_missing_explicit_builtin_metadata(
    tmp_path: Path,
) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "roles/requirement_analyst.md",
        (
            "---\n"
            "prompt_id: agent_role_seed.requirement_analyst\n"
            "prompt_version: 2026-05-02.1\n"
            "role_id: role-requirement-analyst\n"
            "role_name: Requirement Analyst\n"
            "---\n"
            "# Requirement Analyst\n\nMissing builtin metadata must fail.\n"
        ),
    )

    with pytest.raises(PromptAssetMetadataError, match="missing keys"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)


def test_get_without_version_selects_latest_numeric_prompt_version(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "runtime/runtime_instructions.md",
        valid_asset(
            prompt_id="runtime_instructions",
            prompt_version="2026-05-04.9",
            prompt_type="runtime_instructions",
            authority_level="system_trusted",
            model_call_type="stage_execution",
            cache_scope="global_static",
            source_ref="backend://prompts/runtime/runtime_instructions.md",
            body="# Runtime Instructions\n\nOlder numeric suffix.",
        ),
    )
    write_asset(
        tmp_path,
        "runtime/runtime_instructions_next.md",
        valid_asset(
            prompt_id="runtime_instructions",
            prompt_version="2026-05-04.10",
            prompt_type="runtime_instructions",
            authority_level="system_trusted",
            model_call_type="stage_execution",
            cache_scope="global_static",
            source_ref="backend://prompts/runtime/runtime_instructions_next.md",
            body="# Runtime Instructions\n\nNewer numeric suffix.",
        ),
    )

    registry = PromptRegistry.load_builtin_assets(asset_root=tmp_path)

    assert registry.get("runtime_instructions").prompt_version == "2026-05-04.10"


def test_get_unknown_asset_raises_structured_lookup_error() -> None:
    from backend.app.prompts.registry import PromptAssetNotFoundError, PromptRegistry

    registry = PromptRegistry.load_builtin_assets()

    with pytest.raises(PromptAssetNotFoundError, match="unknown_prompt"):
        registry.get("unknown_prompt")

    with pytest.raises(PromptAssetNotFoundError, match="1900-01-01.1"):
        registry.get("runtime_instructions", "1900-01-01.1")


def test_load_builtin_assets_rejects_invalid_prompt_version_format(tmp_path: Path) -> None:
    from backend.app.prompts.registry import PromptAssetMetadataError, PromptRegistry

    seed_required_assets(tmp_path)
    write_asset(
        tmp_path,
        "runtime/runtime_instructions.md",
        valid_asset(
            prompt_id="runtime_instructions",
            prompt_version="not-a-version",
            prompt_type="runtime_instructions",
            authority_level="system_trusted",
            model_call_type="stage_execution",
            cache_scope="global_static",
            source_ref="backend://prompts/runtime/runtime_instructions.md",
            body="# Runtime Instructions\n\nInvalid prompt version format.",
        ),
    )

    with pytest.raises(PromptAssetMetadataError, match="invalid prompt_version format"):
        PromptRegistry.load_builtin_assets(asset_root=tmp_path)
