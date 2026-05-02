from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas import common
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptAssetRead,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptType,
)


EXPECTED_ASSETS = {
    "role-requirement-analyst": (
        "requirement_analyst.md",
        "agent_role_seed.requirement_analyst",
    ),
    "role-solution-designer": (
        "solution_designer.md",
        "agent_role_seed.solution_designer",
    ),
    "role-code-generator": (
        "code_generator.md",
        "agent_role_seed.code_generator",
    ),
    "role-test-runner": ("test_runner.md", "agent_role_seed.test_runner"),
    "role-code-reviewer": ("code_reviewer.md", "agent_role_seed.code_reviewer"),
}


def test_agent_role_seed_assets_parse_front_matter_and_hash_body() -> None:
    from backend.app.services.templates import ROLE_ASSET_DIR, load_agent_role_seed_asset

    for role_id, (file_name, prompt_id) in EXPECTED_ASSETS.items():
        path = ROLE_ASSET_DIR / file_name
        markdown = path.read_text(encoding="utf-8")
        asset = load_agent_role_seed_asset(path)

        assert asset.prompt_id == prompt_id
        assert asset.prompt_version == "2026-05-02.1"
        assert asset.prompt_type is PromptType.AGENT_ROLE_SEED
        assert asset.authority_level is PromptAuthorityLevel.AGENT_ROLE_PROMPT
        assert asset.model_call_type is ModelCallType.STAGE_EXECUTION
        assert asset.cache_scope is PromptCacheScope.GLOBAL_STATIC
        assert asset.source_ref == f"backend://prompts/roles/{file_name}"
        assert asset.content_hash == PromptAssetRead.calculate_content_hash(markdown)
        assert asset.sections[0].section_id == role_id
        assert asset.sections[0].cache_scope is PromptCacheScope.GLOBAL_STATIC
        assert asset.sections[0].body == PromptAssetRead.strip_yaml_front_matter(
            markdown
        ).strip()
        assert asset.sections[0].body
        assert "---" not in asset.sections[0].body
        assert asset.applies_to_stage_types


def test_role_assets_cover_model_driven_stage_prompts() -> None:
    from backend.app.services.templates import load_default_agent_role_seed_assets

    assets = load_default_agent_role_seed_assets()
    covered_stage_types = {
        stage_type
        for asset in assets.values()
        for stage_type in asset.applies_to_stage_types
    }

    assert set(assets) == set(EXPECTED_ASSETS)
    assert {
        common.StageType.REQUIREMENT_ANALYSIS,
        common.StageType.SOLUTION_DESIGN,
        common.StageType.CODE_GENERATION,
        common.StageType.TEST_GENERATION_EXECUTION,
        common.StageType.CODE_REVIEW,
        common.StageType.DELIVERY_INTEGRATION,
    }.issubset(covered_stage_types)


def test_agent_role_seed_asset_rejects_version_in_filename(tmp_path: Path) -> None:
    from backend.app.services.templates import build_agent_role_seed_asset

    body = (
        "---\n"
        "prompt_id: agent_role_seed.bad\n"
        "prompt_version: 2026-05-02.1\n"
        "role_id: role-bad\n"
        "role_name: Bad Role\n"
        "---\n"
        "Bad role body.\n"
    )
    with pytest.raises(ValidationError):
        build_agent_role_seed_asset(
            markdown=body,
            source_file_name="bad-2026-05-02.1.md",
            applies_to_stage_types=[common.StageType.REQUIREMENT_ANALYSIS],
        )
