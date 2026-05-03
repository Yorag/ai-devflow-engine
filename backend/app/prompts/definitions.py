from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.schemas import common


PROMPT_ASSET_ROOT = Path(__file__).resolve().parent / "assets"

RUNTIME_INSTRUCTIONS_PROMPT_ID = "runtime_instructions"
STRUCTURED_OUTPUT_REPAIR_PROMPT_ID = "structured_output_repair"
COMPRESSION_PROMPT_ID = "compression_prompt"
TOOL_USAGE_TEMPLATE_PROMPT_ID = "tool_usage_template"

AGENT_ROLE_SEED_PROMPT_IDS = frozenset(
    {
        "agent_role_seed.requirement_analyst",
        "agent_role_seed.solution_designer",
        "agent_role_seed.code_generator",
        "agent_role_seed.test_runner",
        "agent_role_seed.code_reviewer",
    }
)

REQUIRED_BUILTIN_PROMPT_IDS = frozenset(
    {
        RUNTIME_INSTRUCTIONS_PROMPT_ID,
        STRUCTURED_OUTPUT_REPAIR_PROMPT_ID,
        COMPRESSION_PROMPT_ID,
        TOOL_USAGE_TEMPLATE_PROMPT_ID,
        *AGENT_ROLE_SEED_PROMPT_IDS,
    }
)


@dataclass(frozen=True, slots=True)
class BuiltinPromptDefinition:
    prompt_id: str
    relative_path: str
    applies_to_stage_types: tuple[common.StageType, ...]


ROLE_STAGE_TYPES: dict[str, tuple[common.StageType, ...]] = {
    "agent_role_seed.requirement_analyst": (common.StageType.REQUIREMENT_ANALYSIS,),
    "agent_role_seed.solution_designer": (common.StageType.SOLUTION_DESIGN,),
    "agent_role_seed.code_generator": (common.StageType.CODE_GENERATION,),
    "agent_role_seed.test_runner": (common.StageType.TEST_GENERATION_EXECUTION,),
    "agent_role_seed.code_reviewer": (
        common.StageType.CODE_REVIEW,
        common.StageType.DELIVERY_INTEGRATION,
    ),
}

ALL_STAGE_TYPES = (
    common.StageType.REQUIREMENT_ANALYSIS,
    common.StageType.SOLUTION_DESIGN,
    common.StageType.CODE_GENERATION,
    common.StageType.TEST_GENERATION_EXECUTION,
    common.StageType.CODE_REVIEW,
    common.StageType.DELIVERY_INTEGRATION,
)

BUILTIN_PROMPT_DEFINITIONS = (
    BuiltinPromptDefinition(
        prompt_id=RUNTIME_INSTRUCTIONS_PROMPT_ID,
        relative_path="runtime/runtime_instructions.md",
        applies_to_stage_types=ALL_STAGE_TYPES,
    ),
    BuiltinPromptDefinition(
        prompt_id=STRUCTURED_OUTPUT_REPAIR_PROMPT_ID,
        relative_path="repairs/structured_output_repair.md",
        applies_to_stage_types=ALL_STAGE_TYPES,
    ),
    BuiltinPromptDefinition(
        prompt_id=COMPRESSION_PROMPT_ID,
        relative_path="compression/compression_context.md",
        applies_to_stage_types=ALL_STAGE_TYPES,
    ),
    BuiltinPromptDefinition(
        prompt_id=TOOL_USAGE_TEMPLATE_PROMPT_ID,
        relative_path="tools/tool_usage_common.md",
        applies_to_stage_types=ALL_STAGE_TYPES,
    ),
)


def applies_to_stage_types_for_prompt_id(prompt_id: str) -> tuple[common.StageType, ...]:
    if prompt_id in ROLE_STAGE_TYPES:
        return ROLE_STAGE_TYPES[prompt_id]
    return ALL_STAGE_TYPES


def expected_source_ref(asset_root: Path, asset_path: Path) -> str:
    relative_path = asset_path.relative_to(asset_root).as_posix()
    return f"backend://prompts/{relative_path}"
