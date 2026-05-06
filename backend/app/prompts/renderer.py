from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.enums import StageType
from backend.app.prompts.definitions import (
    COMPRESSION_PROMPT_ID,
    RUNTIME_INSTRUCTIONS_PROMPT_ID,
    STAGE_PROMPT_FRAGMENT_PROMPT_IDS_BY_STAGE,
    STRUCTURED_OUTPUT_REPAIR_PROMPT_ID,
    TOOL_PROMPT_FRAGMENT_PROMPT_IDS_BY_TOOL,
    TOOL_USAGE_TEMPLATE_PROMPT_ID,
)
from backend.app.prompts.registry import PromptAssetNotFoundError, PromptRegistry
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptRenderMetadata,
    PromptVersionRef,
)
from backend.app.tools.protocol import ToolBindableDescription


JsonObject = dict[str, Any]
MessageRole = Literal["system", "user", "assistant", "tool"]


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _validate_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if isfinite(value):
            return
        raise ValueError(f"{path} must be a finite JSON number")
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} must be JSON-serializable")


def _validate_json_object(value: JsonObject) -> JsonObject:
    _validate_json_value(value, path="$")
    return value


class PromptRenderError(_StrictBaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    prompt_id: str | None = Field(default=None, min_length=1)
    stage_type: StageType | None = None


class PromptRenderException(RuntimeError):
    def __init__(self, error: PromptRenderError) -> None:
        self.error = error
        super().__init__(error.message)


class PromptRenderedMessage(_StrictBaseModel):
    role: MessageRole
    content: str = Field(min_length=1)


class PromptRenderedSection(_StrictBaseModel):
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    authority_level: PromptAuthorityLevel
    cache_scope: PromptCacheScope
    rendered_content_ref: str = Field(min_length=1)
    rendered_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_ref: PromptVersionRef | None = None
    depends_on_prompt_refs: list[PromptVersionRef] = Field(default_factory=list)


class PromptRenderRequest(_StrictBaseModel):
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    model_call_type: ModelCallType
    template_snapshot_ref: str = Field(min_length=1)
    system_prompt_ref: str | None = Field(default=None, min_length=1)
    stage_work_instruction_ref: str | None = Field(default=None, min_length=1)
    stage_contracts: dict[str, JsonObject]
    user_stage_instruction: str | None = Field(default=None, min_length=1)
    agent_role_prompt: str | None = Field(default=None, min_length=1)
    task_objective: str = Field(min_length=1)
    specified_action: str = Field(min_length=1)
    available_tools: list[ToolBindableDescription] = Field(default_factory=list)
    response_schema: JsonObject
    output_schema_ref: str = Field(min_length=1)
    tool_schema_version: str = Field(min_length=1)
    parse_error: str | None = Field(default=None, min_length=1)
    compression_source_context: str | None = Field(default=None, min_length=1)
    compression_trigger_reason: str | None = Field(default=None, min_length=1)
    full_trace_ref: str | None = Field(default=None, min_length=1)
    created_at: datetime

    @field_validator("stage_contracts")
    @classmethod
    def _require_stage_contracts(cls, value: dict[str, JsonObject]) -> dict[str, JsonObject]:
        if not value:
            raise ValueError("stage_contracts must not be empty")
        _validate_json_object(value)
        return value

    @field_validator("response_schema")
    @classmethod
    def _validate_response_schema(cls, value: JsonObject) -> JsonObject:
        return _validate_json_object(value)


class PromptRenderResult(_StrictBaseModel):
    messages: list[PromptRenderedMessage] = Field(min_length=1)
    sections: list[PromptRenderedSection] = Field(min_length=1)
    metadata: PromptRenderMetadata
    render_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendered_output_ref: str = Field(min_length=1)
    system_prompt_ref: str | None = Field(default=None, min_length=1)
    section_order: list[str] = Field(min_length=1)


class PromptRenderer:
    def __init__(self, registry: PromptRegistry) -> None:
        self._registry = registry

    def render_runtime_instructions(
        self,
        request: PromptRenderRequest,
    ) -> PromptRenderedSection:
        asset = self._get_asset(RUNTIME_INSTRUCTIONS_PROMPT_ID)
        return self._asset_section(
            request=request,
            section_id="runtime_instructions",
            title=asset.sections[0].title,
            body="\n\n".join(section.body for section in asset.sections),
            prompt_ref=self._prompt_ref(asset),
            authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
            cache_scope=asset.cache_scope,
        )

    def render_stage_contract(
        self,
        request: PromptRenderRequest,
    ) -> PromptRenderedSection:
        contract = self._stage_contract(request)
        return self._dynamic_section(
            request=request,
            section_id="stage_contract",
            title="Stage Contract",
            body=_stable_json(contract),
            authority_level=PromptAuthorityLevel.STAGE_CONTRACT_RENDERED,
        )

    def render_stage_prompt_fragment(
        self,
        request: PromptRenderRequest,
    ) -> PromptRenderedSection:
        prompt_id = STAGE_PROMPT_FRAGMENT_PROMPT_IDS_BY_STAGE[request.stage_type]
        asset = self._get_asset(prompt_id)
        return self._asset_section(
            request=request,
            section_id="stage_prompt_fragment",
            title=asset.sections[0].title,
            body="\n\n".join(section.body for section in asset.sections),
            prompt_ref=self._prompt_ref(asset),
            authority_level=PromptAuthorityLevel.STAGE_CONTRACT_RENDERED,
            cache_scope=asset.cache_scope,
        )

    def render_tool_usage(
        self,
        request: PromptRenderRequest,
    ) -> PromptRenderedSection | None:
        if not request.available_tools:
            return None
        self._validate_tool_contract(request)
        asset = self._get_asset(TOOL_USAGE_TEMPLATE_PROMPT_ID)
        sorted_tools = sorted(request.available_tools, key=lambda tool: tool.name)
        duplicate_tool_names = sorted(
            {
                tool.name
                for index, tool in enumerate(sorted_tools)
                if any(previous.name == tool.name for previous in sorted_tools[:index])
            }
        )
        if duplicate_tool_names:
            raise PromptRenderException(
                PromptRenderError(
                    code="duplicate_available_tool",
                    message=(
                        "available_tools contains duplicate tool names: "
                        f"{', '.join(duplicate_tool_names)}"
                    ),
                    stage_type=request.stage_type,
                )
            )
        tool_prompt_bodies: list[str] = []
        tool_prompt_refs: list[PromptVersionRef] = []
        for tool in sorted_tools:
            prompt_id = TOOL_PROMPT_FRAGMENT_PROMPT_IDS_BY_TOOL.get(tool.name)
            if prompt_id is None:
                raise PromptRenderException(
                    PromptRenderError(
                        code="tool_prompt_fragment_missing",
                        message=(
                            "No rich prompt fragment is registered for available "
                            f"tool: {tool.name}"
                        ),
                        stage_type=request.stage_type,
                    )
                )
            tool_asset = self._get_asset(prompt_id)
            tool_prompt_bodies.append(
                "\n\n".join(section.body for section in tool_asset.sections)
            )
            tool_prompt_refs.append(self._prompt_ref(tool_asset))
        tools_payload = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "result_schema": tool.result_schema,
                "risk_level": tool.risk_level.value,
                "risk_categories": [
                    category.value for category in tool.risk_categories
                ],
                "schema_version": tool.schema_version,
            }
            for tool in sorted_tools
        ]
        body_parts = [
            "\n\n".join(section.body for section in asset.sections),
            "Available tools are limited to the stage contract allowed_tools list.",
        ]
        if tool_prompt_bodies:
            body_parts.extend(["## Tool Guidance", *tool_prompt_bodies])
        body_parts.extend(["## Tool Schemas", _stable_json(tools_payload)])
        body = "\n\n".join(body_parts)
        return self._asset_section(
            request=request,
            section_id="available_tools",
            title="Available Tools",
            body=body,
            prompt_ref=self._prompt_ref(asset),
            authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
            cache_scope=asset.cache_scope,
            depends_on_prompt_refs=tool_prompt_refs,
        )

    def render_structured_output_repair(
        self,
        request: PromptRenderRequest,
    ) -> PromptRenderResult:
        if request.model_call_type is not ModelCallType.STRUCTURED_OUTPUT_REPAIR:
            self._raise_unsupported_model_call_type(request)
        asset = self._get_asset(STRUCTURED_OUTPUT_REPAIR_PROMPT_ID)
        repair_body = "\n\n".join(section.body for section in asset.sections)
        lines = [
            repair_body,
            "Repair Scope",
            "Repair the prior response so it matches the current response_schema.",
            "Do not change the stage contract, tool boundary, or structured output requirement.",
            f"Parse error: {request.parse_error or 'Unknown parse error.'}",
            "Response schema:",
            _stable_json(request.response_schema),
        ]
        section = self._asset_section(
            request=request,
            section_id="structured_output_repair",
            title="Structured Output Repair",
            body="\n".join(lines),
            prompt_ref=self._prompt_ref(asset),
            authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
            cache_scope=asset.cache_scope,
        )
        messages = [
            PromptRenderedMessage(role="system", content=section.body),
            PromptRenderedMessage(
                role="user",
                content="Return only a response that conforms to the response_schema.",
            ),
        ]
        return self._result(
            request=request,
            messages=messages,
            sections=[section],
            model_call_type=ModelCallType.STRUCTURED_OUTPUT_REPAIR,
        )

    def render_context_compression(
        self,
        request: PromptRenderRequest,
    ) -> PromptRenderResult:
        if request.model_call_type is not ModelCallType.CONTEXT_COMPRESSION:
            self._raise_unsupported_model_call_type(request)
        if not request.compression_source_context:
            raise PromptRenderException(
                PromptRenderError(
                    code="compression_context_missing",
                    message=(
                        "compression_source_context is required for context "
                        "compression."
                    ),
                    stage_type=request.stage_type,
                )
            )
        asset = self._get_asset(COMPRESSION_PROMPT_ID)
        prompt_body = "\n\n".join(section.body for section in asset.sections)
        section = self._asset_section(
            request=request,
            section_id="compression_prompt",
            title="Context Compression",
            body="\n".join(
                [
                    prompt_body,
                    "Compression Trigger",
                    request.compression_trigger_reason
                    or "compression_threshold_exceeded",
                    "Full trace ref:",
                    request.full_trace_ref or "unavailable",
                    "Response schema:",
                    _stable_json(request.response_schema),
                ]
            ),
            prompt_ref=self._prompt_ref(asset),
            authority_level=PromptAuthorityLevel.SYSTEM_TRUSTED,
            cache_scope=asset.cache_scope,
        )
        messages = [
            PromptRenderedMessage(role="system", content=section.body),
            PromptRenderedMessage(
                role="user",
                content=request.compression_source_context,
            ),
        ]
        return self._result(
            request=request,
            messages=messages,
            sections=[section],
            model_call_type=ModelCallType.CONTEXT_COMPRESSION,
        )

    def render_messages(self, request: PromptRenderRequest) -> PromptRenderResult:
        if request.model_call_type is ModelCallType.STRUCTURED_OUTPUT_REPAIR:
            return self.render_structured_output_repair(request)
        if request.model_call_type is ModelCallType.CONTEXT_COMPRESSION:
            if not self._has_asset(COMPRESSION_PROMPT_ID):
                self._raise_unsupported_model_call_type(request)
            return self.render_context_compression(request)
        if request.model_call_type is not ModelCallType.STAGE_EXECUTION:
            self._raise_unsupported_model_call_type(request)

        runtime = self.render_runtime_instructions(request)
        stage_contract = self.render_stage_contract(request)
        user_stage_instruction = self._user_stage_instruction_section(request)
        agent_role = self._agent_role_section(request)
        task_objective = self._dynamic_section(
            request=request,
            section_id="task_objective",
            title="Task Objective",
            body=request.task_objective,
            authority_level=PromptAuthorityLevel.STAGE_CONTRACT_RENDERED,
        )
        specified_action = self._dynamic_section(
            request=request,
            section_id="specified_action",
            title="Specified Action",
            body=request.specified_action,
            authority_level=PromptAuthorityLevel.STAGE_CONTRACT_RENDERED,
        )
        tool_usage = self.render_tool_usage(request)
        response_schema = self._dynamic_section(
            request=request,
            section_id="response_schema",
            title="Response Schema",
            body=_stable_json(request.response_schema),
            authority_level=PromptAuthorityLevel.STAGE_CONTRACT_RENDERED,
        )

        sections = [
            runtime,
            stage_contract,
            user_stage_instruction,
            agent_role,
            task_objective,
            specified_action,
            response_schema,
        ]
        if tool_usage is not None:
            sections.insert(len(sections) - 1, tool_usage)
        system_sections = [
            section
            for section in sections
            if section.section_id
            in {
                "runtime_instructions",
                "stage_contract",
                "available_tools",
                "response_schema",
            }
        ]
        user_sections = [
            section
            for section in sections
            if section.section_id
            in {
                "agent_role_prompt",
                "user_stage_instruction",
                "task_objective",
                "specified_action",
            }
        ]
        messages = [
            PromptRenderedMessage(
                role="system",
                content="\n\n".join(
                    self._format_section(section) for section in system_sections
                ),
            ),
            PromptRenderedMessage(
                role="user",
                content="\n\n".join(
                    self._format_section(section) for section in user_sections
                ),
            ),
        ]
        return self._result(
            request=request,
            messages=messages,
            sections=sections,
            model_call_type=ModelCallType.STAGE_EXECUTION,
        )

    @staticmethod
    def compute_render_hash(messages: list[PromptRenderedMessage]) -> str:
        return _hash_text(
            _stable_json(
                [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ]
            )
        )

    def _result(
        self,
        *,
        request: PromptRenderRequest,
        messages: list[PromptRenderedMessage],
        sections: list[PromptRenderedSection],
        model_call_type: ModelCallType,
    ) -> PromptRenderResult:
        render_hash = self.compute_render_hash(messages)
        rendered_output_ref = (
            f"artifact://prompt-renders/{request.run_id}/"
            f"{request.stage_run_id}/{model_call_type.value}"
        )
        prompt_refs: list[PromptVersionRef] = []
        for section in sections:
            if section.prompt_ref is not None:
                prompt_refs.append(section.prompt_ref)
            prompt_refs.extend(section.depends_on_prompt_refs)
        metadata = PromptRenderMetadata(
            render_id=(
                f"prompt-render:{request.run_id}:"
                f"{request.stage_run_id}:{model_call_type.value}"
            ),
            model_call_type=model_call_type,
            prompt_refs=prompt_refs,
            rendered_prompt_hash=render_hash,
            section_order=[section.section_id for section in sections],
            template_snapshot_ref=request.template_snapshot_ref,
            stage_contract_ref=self._stage_contract_ref(request),
            tool_schema_version=request.tool_schema_version,
            created_at=request.created_at,
        )
        return PromptRenderResult(
            messages=messages,
            sections=sections,
            metadata=metadata,
            render_hash=render_hash,
            rendered_output_ref=rendered_output_ref,
            system_prompt_ref=request.system_prompt_ref,
            section_order=[section.section_id for section in sections],
        )

    @staticmethod
    def _raise_unsupported_model_call_type(request: PromptRenderRequest) -> None:
        raise PromptRenderException(
            PromptRenderError(
                code="unsupported_model_call_type",
                message=(
                    "PromptRenderer supports stage_execution, "
                    "structured_output_repair, and context_compression; received "
                    f"{request.model_call_type.value}"
                ),
                stage_type=request.stage_type,
            )
        )

    def _get_asset(self, prompt_id: str) -> Any:
        try:
            return self._registry.get(prompt_id)
        except PromptAssetNotFoundError as exc:
            raise PromptRenderException(
                PromptRenderError(
                    code="prompt_asset_missing",
                    message=str(exc),
                    prompt_id=prompt_id,
                )
            ) from exc

    def _has_asset(self, prompt_id: str) -> bool:
        try:
            self._registry.get(prompt_id)
        except PromptAssetNotFoundError:
            return False
        return True

    def _asset_section(
        self,
        *,
        request: PromptRenderRequest,
        section_id: str,
        title: str,
        body: str,
        prompt_ref: PromptVersionRef,
        authority_level: PromptAuthorityLevel,
        cache_scope: PromptCacheScope,
        depends_on_prompt_refs: list[PromptVersionRef] | None = None,
    ) -> PromptRenderedSection:
        return PromptRenderedSection(
            section_id=section_id,
            title=title,
            body=body,
            authority_level=authority_level,
            cache_scope=cache_scope,
            rendered_content_ref=self._content_ref(request, section_id),
            rendered_content_hash=_hash_text(body),
            prompt_ref=prompt_ref,
            depends_on_prompt_refs=depends_on_prompt_refs or [],
        )

    def _dynamic_section(
        self,
        *,
        request: PromptRenderRequest,
        section_id: str,
        title: str,
        body: str,
        authority_level: PromptAuthorityLevel,
    ) -> PromptRenderedSection:
        return PromptRenderedSection(
            section_id=section_id,
            title=title,
            body=body,
            authority_level=authority_level,
            cache_scope=PromptCacheScope.DYNAMIC_UNCACHED,
            rendered_content_ref=self._content_ref(request, section_id),
            rendered_content_hash=_hash_text(body),
            prompt_ref=None,
        )

    def _agent_role_section(self, request: PromptRenderRequest) -> PromptRenderedSection:
        body = request.agent_role_prompt or "No user-configured agent role prompt."
        return self._dynamic_section(
            request=request,
            section_id="agent_role_prompt",
            title="Agent Role Prompt",
            body=body,
            authority_level=PromptAuthorityLevel.AGENT_ROLE_PROMPT,
        )

    def _user_stage_instruction_section(
        self,
        request: PromptRenderRequest,
    ) -> PromptRenderedSection:
        body = (
            request.user_stage_instruction
            or "No user-configured stage work instruction."
        )
        return self._dynamic_section(
            request=request,
            section_id="user_stage_instruction",
            title="User Stage Work Instruction",
            body=body,
            authority_level=PromptAuthorityLevel.USER_STAGE_INSTRUCTION,
        )

    def _stage_contract(self, request: PromptRenderRequest) -> JsonObject:
        contract = request.stage_contracts.get(request.stage_type.value)
        if contract is None:
            raise PromptRenderException(
                PromptRenderError(
                    code="stage_contract_missing",
                    message=(
                        "stage_contracts does not contain a contract for "
                        f"{request.stage_type.value}"
                    ),
                    stage_type=request.stage_type,
                )
            )
        return contract

    def _stage_contract_ref(self, request: PromptRenderRequest) -> str | None:
        ref = self._stage_contract(request).get("stage_contract_ref")
        return ref if isinstance(ref, str) and ref else None

    def _validate_tool_contract(self, request: PromptRenderRequest) -> None:
        contract = self._stage_contract(request)
        raw_allowed_tools = contract.get("allowed_tools", [])
        if not isinstance(raw_allowed_tools, list) or not all(
            isinstance(tool_name, str) for tool_name in raw_allowed_tools
        ):
            raise PromptRenderException(
                PromptRenderError(
                    code="stage_contract_invalid",
                    message="stage contract allowed_tools must be a list of tool names",
                    stage_type=request.stage_type,
                )
            )
        allowed_tools = set(raw_allowed_tools)
        requested_tools = {tool.name for tool in request.available_tools}
        unallowed_tools = sorted(requested_tools - allowed_tools)
        if unallowed_tools:
            raise PromptRenderException(
                PromptRenderError(
                    code="tool_contract_conflict",
                    message=(
                        "available_tools contains tools not allowed by the "
                        f"stage contract: {', '.join(unallowed_tools)}"
                    ),
                    stage_type=request.stage_type,
                )
            )

    @staticmethod
    def _prompt_ref(asset: Any) -> PromptVersionRef:
        return PromptVersionRef(
            prompt_id=asset.prompt_id,
            prompt_version=asset.prompt_version,
            prompt_type=asset.prompt_type,
            authority_level=asset.authority_level,
            cache_scope=asset.cache_scope,
            source_ref=asset.source_ref,
            content_hash=asset.content_hash,
        )

    @staticmethod
    def _format_section(section: PromptRenderedSection) -> str:
        if section.section_id == "stage_contract":
            return section.body
        return f"{section.title}\n{section.body}"

    @staticmethod
    def _content_ref(request: PromptRenderRequest, section_id: str) -> str:
        return (
            f"artifact://prompt-renders/{request.run_id}/"
            f"{request.stage_run_id}/sections/{section_id}"
        )


__all__ = [
    "PromptRenderError",
    "PromptRenderException",
    "PromptRenderedMessage",
    "PromptRenderedSection",
    "PromptRenderRequest",
    "PromptRenderResult",
    "PromptRenderer",
]
