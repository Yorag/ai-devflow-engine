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
