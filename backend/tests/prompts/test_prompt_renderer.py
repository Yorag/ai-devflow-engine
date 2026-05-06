from __future__ import annotations

from datetime import UTC, datetime
from math import nan

import pytest
from pydantic import ValidationError

from backend.app.domain.enums import StageType, ToolRiskLevel
from backend.app.prompts.registry import PromptRegistry
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptAssetRead,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptSectionRead,
    PromptType,
)
from backend.app.tools.protocol import ToolBindableDescription


NOW = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)


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
        applies_to_stage_types=[StageType.SOLUTION_DESIGN],
    )


def _registry() -> PromptRegistry:
    return PromptRegistry(
        [
            _asset(
                prompt_id="runtime_instructions",
                prompt_type=PromptType.RUNTIME_INSTRUCTIONS,
                authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
                model_call_type=ModelCallType.STAGE_EXECUTION,
                source_ref="backend://prompts/runtime/runtime_instructions.md",
                body="# Runtime Instructions\n\nStay inside platform boundaries.",
            ),
            _asset(
                prompt_id="structured_output_repair",
                prompt_type=PromptType.STRUCTURED_OUTPUT_REPAIR,
                authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
                model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR,
                source_ref="backend://prompts/repairs/structured_output_repair.md",
                body="# Structured Output Repair\n\nRepair only invalid JSON.",
                cache_scope=PromptCacheScope.DYNAMIC_UNCACHED,
            ),
            _asset(
                prompt_id="tool_usage_template",
                prompt_type=PromptType.TOOL_USAGE_TEMPLATE,
                authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                source_ref="backend://prompts/tools/tool_usage_common.md",
                body="# Tool Usage\n\nUse only listed tools.",
                cache_scope=PromptCacheScope.RUN_STATIC,
            ),
            _asset(
                prompt_id="tool_prompt_fragment.read_file",
                prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
                authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                source_ref="backend://prompts/tools/read_file.md",
                body=(
                    "# read_file Tool Prompt\n\n"
                    "Use read_file for workspace reads only."
                ),
            ),
            _asset(
                prompt_id="stage_prompt_fragment.solution_design",
                prompt_type=PromptType.STAGE_PROMPT_FRAGMENT,
                authority_level=PromptAuthorityLevel.STAGE_CONTRACT_RENDERED,
                model_call_type=ModelCallType.STAGE_EXECUTION,
                source_ref="backend://prompts/stages/solution_design.md",
                body=(
                    "# Solution Design Stage Prompt\n\n"
                    "Use the current stage_contract and response_schema."
                ),
                cache_scope=PromptCacheScope.RUN_STATIC,
            ),
        ]
    )


def _tool(name: str) -> ToolBindableDescription:
    return ToolBindableDescription(
        name=name,
        description=f"{name} description.",
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


def _stage_contracts() -> dict[str, dict[str, object]]:
    return {
        StageType.SOLUTION_DESIGN.value: {
            "stage_type": StageType.SOLUTION_DESIGN.value,
            "stage_contract_ref": "stage-contract-solution-design",
            "responsibilities": ["Design the solution from accepted requirements."],
            "input_contract": {"requires": ["requirements_summary"]},
            "output_contract": {"produces": ["solution_design"]},
            "structured_artifacts": ["solution_design_document"],
            "allowed_tools": ["read_file"],
        }
    }


def _request() -> object:
    from backend.app.prompts.renderer import PromptRenderRequest

    return PromptRenderRequest(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        model_call_type=ModelCallType.STAGE_EXECUTION,
        template_snapshot_ref="template-snapshot-run-1",
        system_prompt_ref="template-snapshot://run-1/agent-role/system-prompt",
        stage_contracts=_stage_contracts(),
        agent_role_prompt="You may choose a concise tone, but do not override runtime rules.",
        task_objective="Create a solution design.",
        specified_action="Return the structured solution design result.",
        available_tools=[_tool("read_file")],
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


def test_render_stage_execution_messages_with_metadata_without_prompt_metadata_in_text() -> None:
    from backend.app.prompts.renderer import PromptRenderer

    renderer = PromptRenderer(_registry())
    result = renderer.render_messages(_request())
    second_result = renderer.render_messages(_request())

    message_text = "\n\n".join(message.content for message in result.messages)
    assert [message.role for message in result.messages] == ["system", "user"]
    assert "# Runtime Instructions" in result.messages[0].content
    assert "Solution Design Stage Prompt" in result.messages[0].content
    assert "Use the current stage_contract" in result.messages[0].content
    assert "read_file description." in result.messages[0].content
    assert "Use read_file for workspace reads only." in result.messages[0].content
    assert '"solution"' in result.messages[0].content
    assert "You may choose a concise tone" in result.messages[1].content
    assert "Create a solution design." in result.messages[1].content
    assert "Return the structured solution design result." in result.messages[1].content
    assert "Design the solution from accepted requirements." in message_text
    assert "write_file" not in message_text
    assert "prompt_version" not in message_text
    assert "backend://prompts/" not in message_text
    assert result.metadata.rendered_prompt_hash == second_result.metadata.rendered_prompt_hash
    assert result.render_hash == result.metadata.rendered_prompt_hash
    assert result.rendered_output_ref == "artifact://prompt-renders/run-1/stage-run-1/stage_execution"
    assert result.system_prompt_ref == "template-snapshot://run-1/agent-role/system-prompt"
    assert result.section_order == [
        "runtime_instructions",
        "stage_contract",
        "stage_prompt_fragment",
        "agent_role_prompt",
        "task_objective",
        "specified_action",
        "available_tools",
        "response_schema",
    ]
    assert [ref.prompt_id for ref in result.metadata.prompt_refs] == [
        "runtime_instructions",
        "stage_prompt_fragment.solution_design",
        "tool_usage_template",
        "tool_prompt_fragment.read_file",
    ]
    agent_section = next(
        section for section in result.sections if section.section_id == "agent_role_prompt"
    )
    assert agent_section.prompt_ref is None
    assert agent_section.authority_level is PromptAuthorityLevel.AGENT_ROLE_PROMPT


def test_render_structured_output_repair_uses_repair_asset_and_current_schema() -> None:
    from backend.app.prompts.renderer import PromptRenderRequest, PromptRenderer

    request = PromptRenderRequest(
        **{
            **_request().model_dump(mode="python"),
            "model_call_type": ModelCallType.STRUCTURED_OUTPUT_REPAIR,
            "parse_error": "Missing required field: solution",
        }
    )

    result = PromptRenderer(_registry()).render_structured_output_repair(request)
    text = "\n\n".join(message.content for message in result.messages)

    assert "# Structured Output Repair" in text
    assert "Missing required field: solution" in text
    assert '"solution"' in text
    assert "Do not change the stage contract" in text
    assert [ref.prompt_id for ref in result.metadata.prompt_refs] == [
        "structured_output_repair"
    ]
    assert result.metadata.model_call_type is ModelCallType.STRUCTURED_OUTPUT_REPAIR


def test_missing_prompt_asset_returns_structured_renderer_error() -> None:
    from backend.app.prompts.renderer import PromptRenderException, PromptRenderer

    registry = PromptRegistry([])
    renderer = PromptRenderer(registry)

    with pytest.raises(PromptRenderException) as exc_info:
        renderer.render_messages(_request())

    assert exc_info.value.error.code == "prompt_asset_missing"
    assert exc_info.value.error.prompt_id == "runtime_instructions"


def test_missing_stage_prompt_fragment_returns_structured_renderer_error() -> None:
    from backend.app.prompts.renderer import PromptRenderException, PromptRenderer

    registry = PromptRegistry(
        [
            asset
            for asset in _registry().list_by_type(PromptType.RUNTIME_INSTRUCTIONS)
        ]
    )

    with pytest.raises(PromptRenderException) as exc_info:
        PromptRenderer(registry).render_messages(_request())

    assert exc_info.value.error.code == "prompt_asset_missing"
    assert exc_info.value.error.prompt_id == "stage_prompt_fragment.solution_design"


def test_tool_descriptions_must_not_exceed_stage_contract_allowed_tools() -> None:
    from backend.app.prompts.renderer import PromptRenderException, PromptRenderer

    request = _request().model_copy(update={"available_tools": [_tool("write_file")]})

    with pytest.raises(PromptRenderException) as exc_info:
        PromptRenderer(_registry()).render_messages(request)

    assert exc_info.value.error.code == "tool_contract_conflict"
    assert "write_file" in exc_info.value.error.message


def test_tool_usage_renders_only_available_tool_prompt_fragments_in_name_order() -> None:
    from backend.app.prompts.renderer import PromptRenderer

    registry = PromptRegistry(
        [
            *_registry().list_by_type(PromptType.RUNTIME_INSTRUCTIONS),
            *_registry().list_by_type(PromptType.STRUCTURED_OUTPUT_REPAIR),
            *_registry().list_by_type(PromptType.TOOL_USAGE_TEMPLATE),
            *_registry().list_by_type(PromptType.STAGE_PROMPT_FRAGMENT),
            _asset(
                prompt_id="tool_prompt_fragment.grep",
                prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
                authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                source_ref="backend://prompts/tools/grep.md",
                body="# grep Tool Prompt\n\nUse grep for text search.",
            ),
            _asset(
                prompt_id="tool_prompt_fragment.read_file",
                prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
                authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                source_ref="backend://prompts/tools/read_file.md",
                body="# read_file Tool Prompt\n\nUse read_file for text reads.",
            ),
            _asset(
                prompt_id="tool_prompt_fragment.write_file",
                prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
                authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                source_ref="backend://prompts/tools/write_file.md",
                body="# write_file Tool Prompt\n\nUse write_file for edits.",
            ),
        ]
    )
    request = _request().model_copy(
        update={
            "stage_contracts": {
                StageType.SOLUTION_DESIGN.value: {
                    **_stage_contracts()[StageType.SOLUTION_DESIGN.value],
                    "allowed_tools": ["write_file", "read_file", "grep"],
                }
            },
            "available_tools": [_tool("read_file"), _tool("grep")],
        }
    )

    result = PromptRenderer(registry).render_messages(request)
    tool_section = next(
        section for section in result.sections if section.section_id == "available_tools"
    )

    assert tool_section.body.index("grep Tool Prompt") < tool_section.body.index(
        "read_file Tool Prompt"
    )
    assert "write_file Tool Prompt" not in tool_section.body
    assert [ref.prompt_id for ref in result.metadata.prompt_refs] == [
        "runtime_instructions",
        "stage_prompt_fragment.solution_design",
        "tool_usage_template",
        "tool_prompt_fragment.grep",
        "tool_prompt_fragment.read_file",
    ]


def test_tool_usage_requires_prompt_fragment_for_every_available_tool() -> None:
    from backend.app.prompts.renderer import PromptRenderException, PromptRenderer

    request = _request().model_copy(
        update={
            "stage_contracts": {
                StageType.SOLUTION_DESIGN.value: {
                    **_stage_contracts()[StageType.SOLUTION_DESIGN.value],
                    "allowed_tools": ["custom_tool"],
                }
            },
            "available_tools": [_tool("custom_tool")],
        }
    )

    with pytest.raises(PromptRenderException) as exc_info:
        PromptRenderer(_registry()).render_messages(request)

    assert exc_info.value.error.code == "tool_prompt_fragment_missing"
    assert "custom_tool" in exc_info.value.error.message


def test_tool_usage_rejects_duplicate_available_tool_names() -> None:
    from backend.app.prompts.renderer import PromptRenderException, PromptRenderer

    request = _request().model_copy(
        update={"available_tools": [_tool("read_file"), _tool("read_file")]}
    )

    with pytest.raises(PromptRenderException) as exc_info:
        PromptRenderer(_registry()).render_messages(request)

    assert exc_info.value.error.code == "duplicate_available_tool"
    assert "read_file" in exc_info.value.error.message


def test_unsupported_model_call_type_returns_structured_renderer_error() -> None:
    from backend.app.prompts.renderer import PromptRenderException, PromptRenderer

    request = _request().model_copy(
        update={"model_call_type": ModelCallType.CONTEXT_COMPRESSION}
    )

    with pytest.raises(PromptRenderException) as exc_info:
        PromptRenderer(_registry()).render_messages(request)

    assert exc_info.value.error.code == "unsupported_model_call_type"
    assert "context_compression" in exc_info.value.error.message


def test_render_request_rejects_non_finite_stage_contract_json() -> None:
    from backend.app.prompts.renderer import PromptRenderRequest

    with pytest.raises(ValidationError) as exc_info:
        PromptRenderRequest(
            **{
                **_request().model_dump(mode="python"),
                "stage_contracts": {
                    StageType.SOLUTION_DESIGN.value: {
                        **_stage_contracts()[StageType.SOLUTION_DESIGN.value],
                        "temperature": nan,
                    }
                },
            }
        )

    assert "finite JSON number" in str(exc_info.value)


def test_render_request_rejects_non_json_response_schema_value() -> None:
    from backend.app.prompts.renderer import PromptRenderRequest

    with pytest.raises(ValidationError) as exc_info:
        PromptRenderRequest(
            **{
                **_request().model_dump(mode="python"),
                "response_schema": {"type": "object", "not_json": object()},
            }
        )

    assert "JSON-serializable" in str(exc_info.value)
