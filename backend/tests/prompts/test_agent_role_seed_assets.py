from __future__ import annotations

from pathlib import Path
import re

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
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    LogPolicy,
    ProviderCallPolicy,
)
from backend.tests.fixtures.settings import runtime_settings_snapshot_fixture


FORBIDDEN_ROLE_CONTROL_PATTERNS = (
    r"\bruntime[_\s-]+instructions?\b",
    r"\bstage[_\s-]+contracts?\b",
    r"\bresponse[_\s-]+schemas?\b",
    r"\bstage\s+prompts?\b",
    r"\bschema-defined\b",
    r"\bstructured\s+output\b",
    r"\boutput\s+(?:contracts?|formats?|schemas?|shapes?)\b",
    r"\bpermissions?\b",
    r"\bapprovals?\b",
    r"\baudit\b",
    r"\bdelivery\s+controls?\b",
    r"\bruntime\s+states?\b",
    r"\bconfirmation\s+boundar(?:y|ies)\b",
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
        assert asset.prompt_version == "2026-05-06.2"
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
        body = asset.sections[0].body
        assert "## Mission" in body
        assert "## Workflow" in body
        assert "## Quality Gates" in body
        assert "## Failure And Escalation" in body
        assert "runtime_instructions" not in body
        assert "stage_contract" not in body
        assert "response_schema" not in body
        assert "stage prompt" not in body.lower()
        for pattern in FORBIDDEN_ROLE_CONTROL_PATTERNS:
            assert re.search(pattern, body, flags=re.IGNORECASE) is None
        assert "prompt_id:" not in body
        assert "prompt_version:" not in body
        assert "---" not in asset.sections[0].body
        assert asset.applies_to_stage_types


def test_agent_role_seed_assets_pass_runtime_prompt_validation() -> None:
    from backend.app.runtime.prompt_validation import PromptValidationService
    from backend.app.services.templates import load_default_agent_role_seed_assets

    validator = PromptValidationService(
        settings_read=runtime_settings_snapshot_fixture(
            agent_limits=AgentRuntimeLimits.model_validate(
                AgentRuntimeLimits().model_dump(mode="python")
            ),
            provider_call_policy=ProviderCallPolicy.model_validate(
                ProviderCallPolicy().model_dump(mode="python")
            ),
            context_limits=ContextLimits.model_validate(
                ContextLimits().model_dump(mode="python")
            ),
            log_policy=LogPolicy.model_validate(LogPolicy().model_dump(mode="python")),
        )
    )

    for asset in load_default_agent_role_seed_assets().values():
        for stage_type in asset.applies_to_stage_types:
            result = validator.validate_system_prompt(
                prompt_text=asset.sections[0].body,
                stage_type=stage_type,
            )

            assert result.accepted is True
            assert result.rule_ids == []


def test_agent_role_seed_assets_declare_full_builtin_metadata() -> None:
    from backend.app.services.templates import ROLE_ASSET_DIR, parse_front_matter

    for _role_id, (file_name, prompt_id) in EXPECTED_ASSETS.items():
        metadata, _body = parse_front_matter(
            (ROLE_ASSET_DIR / file_name).read_text(encoding="utf-8")
        )

        assert metadata["prompt_id"] == prompt_id
        assert metadata["prompt_type"] == "agent_role_seed"
        assert metadata["authority_level"] == "agent_role_prompt"
        assert metadata["model_call_type"] == "stage_execution"
        assert metadata["cache_scope"] == "global_static"
        assert metadata["source_ref"] == f"backend://prompts/roles/{file_name}"


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
        "prompt_type: agent_role_seed\n"
        "authority_level: agent_role_prompt\n"
        "model_call_type: stage_execution\n"
        "cache_scope: global_static\n"
        "source_ref: backend://prompts/roles/bad-2026-05-02.1.md\n"
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
