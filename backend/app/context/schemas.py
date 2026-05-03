from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from backend.app.domain.enums import StageType
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptCacheScope,
    PromptVersionRef,
)
from backend.app.tools.protocol import ToolBindableDescription


JsonObject = dict[str, Any]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


def _canonical_section_order() -> tuple[str, ...]:
    return tuple(section.value for section in ContextEnvelopeSection)


def _dedupe_prompt_refs(
    prompt_refs: list[PromptVersionRef] | tuple[PromptVersionRef, ...],
) -> tuple[PromptVersionRef, ...]:
    seen: set[tuple[str, str, str]] = set()
    ordered: list[PromptVersionRef] = []
    for prompt_ref in prompt_refs:
        key = (
            prompt_ref.prompt_id,
            prompt_ref.prompt_version,
            prompt_ref.source_ref,
        )
        if key in seen:
            continue
        seen.add(key)
        ordered.append(prompt_ref)
    return tuple(ordered)


class ContextEnvelopeSection(StrEnum):
    RUNTIME_INSTRUCTIONS = "runtime_instructions"
    STAGE_CONTRACT = "stage_contract"
    AGENT_ROLE_PROMPT = "agent_role_prompt"
    TASK_OBJECTIVE = "task_objective"
    SPECIFIED_ACTION = "specified_action"
    INPUT_ARTIFACT_REFS = "input_artifact_refs"
    CONTEXT_REFERENCES = "context_references"
    WORKING_OBSERVATIONS = "working_observations"
    REASONING_TRACE = "reasoning_trace"
    AVAILABLE_TOOLS = "available_tools"
    RECENT_OBSERVATIONS = "recent_observations"
    RESPONSE_SCHEMA = "response_schema"
    TRACE_CONTEXT = "trace_context"


class ContextTrustLevel(StrEnum):
    SYSTEM_TRUSTED = "system_trusted"
    STAGE_CONTRACT_TRUSTED = "stage_contract_trusted"
    AGENT_ROLE_CONFIG = "agent_role_config"
    TRUSTED_REFERENCE = "trusted_reference"
    UNTRUSTED_OBSERVATION = "untrusted_observation"


class ContextBoundaryAction(StrEnum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"
    TRUNCATE = "truncate"
    SUMMARIZE = "summarize"
    REFERENCE_ONLY = "reference_only"
    BLOCK = "block"


class RenderedOutputKind(StrEnum):
    MESSAGE_SEQUENCE = "message_sequence"
    PROMPT_TEXT = "prompt_text"


class ContextSourceRef(_StrictFrozenModel):
    source_kind: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    version_ref: str | None = Field(default=None, min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    file_path: str | None = Field(default=None, min_length=1)


class PromptSectionRef(_StrictFrozenModel):
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    prompt_ref: PromptVersionRef
    rendered_content_ref: str = Field(min_length=1)
    rendered_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_scope: PromptCacheScope


class ContextBlock(_StrictFrozenModel):
    block_id: str = Field(min_length=1)
    section: ContextEnvelopeSection
    trust_level: ContextTrustLevel
    boundary_action: ContextBoundaryAction
    summary: str = Field(min_length=1)
    content_ref: str = Field(min_length=1)
    sources: tuple[ContextSourceRef, ...] = Field(default_factory=tuple)
    prompt_section_refs: tuple[PromptSectionRef, ...] = Field(default_factory=tuple)
    estimated_tokens: int | None = Field(default=None, ge=0)
    estimated_chars: int | None = Field(default=None, ge=0)
    truncated: bool = False
    compressed: bool = False
    blocked_reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_trust_boundary(self) -> Self:
        if self.section is ContextEnvelopeSection.RUNTIME_INSTRUCTIONS:
            if self.trust_level is not ContextTrustLevel.SYSTEM_TRUSTED:
                raise ValueError(
                    "runtime_instructions blocks must use system_trusted trust level"
                )
        if self.section is ContextEnvelopeSection.STAGE_CONTRACT:
            if self.trust_level is not ContextTrustLevel.STAGE_CONTRACT_TRUSTED:
                raise ValueError(
                    "stage_contract blocks must use stage_contract_trusted trust level"
                )
        if self.section is ContextEnvelopeSection.AGENT_ROLE_PROMPT:
            if self.trust_level is not ContextTrustLevel.AGENT_ROLE_CONFIG:
                raise ValueError(
                    "agent_role_prompt blocks must use agent_role_config trust level"
                )
        return self


class ContextManifestRecord(_StrictFrozenModel):
    block_id: str = Field(min_length=1)
    section: ContextEnvelopeSection
    trust_level: ContextTrustLevel
    boundary_action: ContextBoundaryAction
    source_kind: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    content_ref: str = Field(min_length=1)
    sources: tuple[ContextSourceRef, ...] = Field(default_factory=tuple)
    prompt_section_refs: tuple[PromptSectionRef, ...] = Field(default_factory=tuple)
    estimated_tokens: int | None = Field(default=None, ge=0)
    estimated_chars: int | None = Field(default=None, ge=0)
    truncated: bool = False
    compressed: bool = False
    blocked_reason: str | None = Field(default=None, min_length=1)


class ContextEnvelope(_StrictFrozenModel):
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    template_snapshot_ref: str = Field(min_length=1)
    stage_contract_ref: str = Field(min_length=1)
    provider_snapshot_ref: str = Field(min_length=1)
    model_binding_snapshot_ref: str = Field(min_length=1)
    model_call_type: ModelCallType
    runtime_instructions: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    stage_contract: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    agent_role_prompt: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    task_objective: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    specified_action: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    input_artifact_refs: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    context_references: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    working_observations: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    reasoning_trace: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    available_tools: tuple[ToolBindableDescription, ...] = Field(default_factory=tuple)
    recent_observations: tuple[ContextBlock, ...] = Field(default_factory=tuple)
    response_schema: JsonObject
    trace_context: TraceContext
    built_at: datetime
    section_order: tuple[str, ...] = Field(default_factory=_canonical_section_order)

    @field_validator(
        "runtime_instructions",
        "stage_contract",
        "agent_role_prompt",
        "task_objective",
        "specified_action",
        "input_artifact_refs",
        "context_references",
        "working_observations",
        "reasoning_trace",
        "recent_observations",
        mode="after",
    )
    @classmethod
    def validate_block_sections(
        cls,
        value: tuple[ContextBlock, ...],
        info: ValidationInfo,
    ) -> tuple[ContextBlock, ...]:
        expected_section = ContextEnvelopeSection(info.field_name)
        for block in value:
            if block.section is not expected_section:
                raise ValueError(
                    f"{info.field_name} blocks must declare section "
                    f"{expected_section.value}"
                )
        return value

    @field_validator("response_schema")
    @classmethod
    def validate_response_schema(cls, value: JsonObject) -> JsonObject:
        return _validate_json_object(value)

    @model_validator(mode="after")
    def validate_section_order(self) -> Self:
        if self.section_order != _canonical_section_order():
            raise ValueError(
                "section_order must match the canonical ContextEnvelope section order"
            )
        return self


class ContextManifest(_StrictFrozenModel):
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    built_at: datetime
    template_snapshot_ref: str = Field(min_length=1)
    stage_contract_ref: str = Field(min_length=1)
    provider_snapshot_ref: str = Field(min_length=1)
    model_binding_snapshot_ref: str = Field(min_length=1)
    provider_binding_model_id: str = Field(min_length=1)
    system_prompt_ref: str | None = Field(default=None, min_length=1)
    prompt_refs: tuple[PromptVersionRef, ...] = Field(default_factory=tuple)
    prompt_asset_sources: tuple[str, ...] = Field(default_factory=tuple)
    prompt_cache_scopes: tuple[PromptCacheScope, ...] = Field(default_factory=tuple)
    rendered_output_ref: str = Field(min_length=1)
    rendered_output_kind: RenderedOutputKind
    render_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_version: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)
    output_schema: JsonObject
    tool_schema_version: str = Field(min_length=1)
    available_tools: tuple[ToolBindableDescription, ...] = Field(default_factory=tuple)
    records: tuple[ContextManifestRecord, ...] = Field(default_factory=tuple)
    total_estimated_tokens: int | None = Field(default=None, ge=0)
    total_estimated_chars: int | None = Field(default=None, ge=0)
    context_window_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    supports_tool_calling: bool | None = None
    supports_structured_output: bool | None = None
    supports_native_reasoning: bool | None = None
    runtime_limit_snapshot_ref: str | None = Field(default=None, min_length=1)
    compression_threshold_ratio: float | None = Field(default=None, gt=0, lt=1)
    compression_trigger_token_threshold: int | None = Field(default=None, gt=0)

    @field_validator("output_schema")
    @classmethod
    def validate_output_schema(cls, value: JsonObject) -> JsonObject:
        return _validate_json_object(value)

    @classmethod
    def from_envelope(
        cls,
        envelope: ContextEnvelope,
        *,
        provider_snapshot: ProviderSnapshot,
        prompt_refs: list[PromptVersionRef] | None = None,
        render_hash: str,
        rendered_output_ref: str,
        rendered_output_kind: str | RenderedOutputKind,
        template_version: str,
        output_schema_ref: str,
        tool_schema_version: str,
        system_prompt_ref: str | None = None,
        runtime_limit_snapshot_ref: str | None = None,
        compression_threshold_ratio: float | None = None,
        compression_trigger_token_threshold: int | None = None,
    ) -> "ContextManifest":
        if provider_snapshot.run_id != envelope.run_id:
            raise ValueError("provider_snapshot.run_id must match ContextEnvelope.run_id")
        if provider_snapshot.snapshot_id != envelope.provider_snapshot_ref:
            raise ValueError(
                "provider_snapshot.snapshot_id must match ContextEnvelope.provider_snapshot_ref"
            )

        blocks = [
            *envelope.runtime_instructions,
            *envelope.stage_contract,
            *envelope.agent_role_prompt,
            *envelope.task_objective,
            *envelope.specified_action,
            *envelope.input_artifact_refs,
            *envelope.context_references,
            *envelope.working_observations,
            *envelope.reasoning_trace,
            *envelope.recent_observations,
        ]
        resolved_prompt_refs = (
            prompt_refs
            if prompt_refs is not None
            else [
                prompt_section.prompt_ref
                for block in blocks
                for prompt_section in block.prompt_section_refs
            ]
        )
        unique_prompt_refs = _dedupe_prompt_refs(resolved_prompt_refs)

        records: list[ContextManifestRecord] = []
        for block in blocks:
            source = block.sources[0] if block.sources else ContextSourceRef(
                source_kind="unknown",
                source_ref=block.content_ref,
                source_label=block.block_id,
            )
            records.append(
                ContextManifestRecord(
                    block_id=block.block_id,
                    section=block.section,
                    trust_level=block.trust_level,
                    boundary_action=block.boundary_action,
                    source_kind=source.source_kind,
                    source_ref=source.source_ref,
                    source_label=source.source_label,
                    content_ref=block.content_ref,
                    sources=block.sources,
                    prompt_section_refs=block.prompt_section_refs,
                    estimated_tokens=block.estimated_tokens,
                    estimated_chars=block.estimated_chars,
                    truncated=block.truncated,
                    compressed=block.compressed,
                    blocked_reason=block.blocked_reason,
                )
            )

        estimated_tokens = [
            record.estimated_tokens
            for record in records
            if record.estimated_tokens is not None
        ]
        estimated_chars = [
            record.estimated_chars
            for record in records
            if record.estimated_chars is not None
        ]
        resolved_system_prompt_ref = (
            system_prompt_ref
            if system_prompt_ref is not None
            else unique_prompt_refs[0].source_ref
            if unique_prompt_refs
            else None
        )

        return cls(
            session_id=envelope.session_id,
            run_id=envelope.run_id,
            stage_run_id=envelope.stage_run_id,
            trace_id=envelope.trace_context.trace_id,
            correlation_id=envelope.trace_context.correlation_id,
            span_id=envelope.trace_context.span_id,
            built_at=envelope.built_at,
            template_snapshot_ref=envelope.template_snapshot_ref,
            stage_contract_ref=envelope.stage_contract_ref,
            provider_snapshot_ref=provider_snapshot.snapshot_id,
            model_binding_snapshot_ref=envelope.model_binding_snapshot_ref,
            provider_binding_model_id=provider_snapshot.model_id,
            system_prompt_ref=resolved_system_prompt_ref,
            prompt_refs=unique_prompt_refs,
            prompt_asset_sources=tuple(
                prompt_ref.source_ref for prompt_ref in unique_prompt_refs
            ),
            prompt_cache_scopes=tuple(
                prompt_ref.cache_scope for prompt_ref in unique_prompt_refs
            ),
            rendered_output_ref=rendered_output_ref,
            rendered_output_kind=RenderedOutputKind(rendered_output_kind),
            render_hash=render_hash,
            template_version=template_version,
            output_schema_ref=output_schema_ref,
            output_schema=dict(envelope.response_schema),
            tool_schema_version=tool_schema_version,
            available_tools=envelope.available_tools,
            records=tuple(records),
            total_estimated_tokens=(
                sum(estimated_tokens) if estimated_tokens else None
            ),
            total_estimated_chars=(sum(estimated_chars) if estimated_chars else None),
            context_window_tokens=provider_snapshot.capabilities.context_window_tokens,
            max_output_tokens=provider_snapshot.capabilities.max_output_tokens,
            supports_tool_calling=provider_snapshot.capabilities.supports_tool_calling,
            supports_structured_output=provider_snapshot.capabilities.supports_structured_output,
            supports_native_reasoning=provider_snapshot.capabilities.supports_native_reasoning,
            runtime_limit_snapshot_ref=runtime_limit_snapshot_ref,
            compression_threshold_ratio=compression_threshold_ratio,
            compression_trigger_token_threshold=compression_trigger_token_threshold,
        )


__all__ = [
    "ContextBlock",
    "ContextBoundaryAction",
    "ContextEnvelope",
    "ContextEnvelopeSection",
    "ContextManifest",
    "ContextManifestRecord",
    "ContextSourceRef",
    "ContextTrustLevel",
    "PromptSectionRef",
    "RenderedOutputKind",
]
