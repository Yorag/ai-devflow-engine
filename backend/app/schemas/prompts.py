from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas import common


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PromptContractEnum(StrEnum):
    """Base class for stable string-backed prompt contract enums."""


class PromptType(_PromptContractEnum):
    RUNTIME_INSTRUCTIONS = "runtime_instructions"
    STAGE_PROMPT_FRAGMENT = "stage_prompt_fragment"
    TOOL_PROMPT_FRAGMENT = "tool_prompt_fragment"
    STRUCTURED_OUTPUT_REPAIR = "structured_output_repair"
    COMPRESSION_PROMPT = "compression_prompt"
    AGENT_ROLE_SEED = "agent_role_seed"
    TOOL_USAGE_TEMPLATE = "tool_usage_template"


class PromptAuthorityLevel(_PromptContractEnum):
    SYSTEM_TRUSTED = "system_trusted"
    STAGE_CONTRACT_RENDERED = "stage_contract_rendered"
    USER_STAGE_INSTRUCTION = "user_stage_instruction"
    AGENT_ROLE_PROMPT = "agent_role_prompt"
    TOOL_DESCRIPTION_RENDERED = "tool_description_rendered"


class PromptCacheScope(_PromptContractEnum):
    GLOBAL_STATIC = "global_static"
    RUN_STATIC = "run_static"
    DYNAMIC_UNCACHED = "dynamic_uncached"


class ModelCallType(_PromptContractEnum):
    STAGE_EXECUTION = "stage_execution"
    STRUCTURED_OUTPUT_REPAIR = "structured_output_repair"
    CONTEXT_COMPRESSION = "context_compression"
    TOOL_CALL_PREPARATION = "tool_call_preparation"
    VALIDATION_PASS = "validation_pass"


class PromptAssetRef(_StrictBaseModel):
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)


class PromptVersionRef(PromptAssetRef):
    prompt_type: PromptType
    authority_level: PromptAuthorityLevel
    cache_scope: PromptCacheScope
    source_ref: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PromptSectionRead(_StrictBaseModel):
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    cache_scope: PromptCacheScope
    depends_on_prompt_refs: list[PromptAssetRef] = Field(default_factory=list)
    dynamic_source_refs: list[str] = Field(default_factory=list)


class PromptRenderMetadata(_StrictBaseModel):
    render_id: str = Field(min_length=1)
    model_call_type: ModelCallType
    prompt_refs: list[PromptVersionRef] = Field(min_length=1)
    rendered_prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    section_order: list[str] = Field(min_length=1)
    template_snapshot_ref: str | None = None
    stage_contract_ref: str | None = None
    tool_schema_version: str | None = None
    context_manifest_ref: str | None = None
    compressed_context_block_ref: str | None = None
    created_at: datetime


class PromptAssetRead(_StrictBaseModel):
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_type: PromptType
    authority_level: PromptAuthorityLevel
    model_call_type: ModelCallType
    cache_scope: PromptCacheScope
    source_ref: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sections: list[PromptSectionRead] = Field(min_length=1)
    applies_to_stage_types: list[common.StageType] = Field(default_factory=list)

    @staticmethod
    def strip_yaml_front_matter(markdown: str) -> str:
        normalized = markdown.replace("\r\n", "\n")
        if not normalized.startswith("---\n"):
            return normalized
        closing_delimiter = "\n---\n"
        closing_index = normalized.find(closing_delimiter, len("---\n"))
        if closing_index == -1:
            return normalized
        return normalized[closing_index + len(closing_delimiter) :]

    @classmethod
    def calculate_content_hash(cls, markdown: str) -> str:
        body = cls.strip_yaml_front_matter(markdown)
        return sha256(body.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_prompt_contract(self) -> "PromptAssetRead":
        self.validate_prompt_identity()
        self.validate_system_asset_boundary()
        return self

    def validate_prompt_identity(self) -> "PromptAssetRead":
        source_filename = self.source_ref.rsplit("/", 1)[-1]
        if self.prompt_version in source_filename:
            raise ValueError(
                "source_ref filename must not carry prompt_version; "
                "prompt_version must come from YAML front matter"
            )
        return self

    def validate_system_asset_boundary(self) -> "PromptAssetRead":
        if not self.source_ref.startswith("backend://prompts/"):
            raise ValueError(
                "system prompt assets must use backend://prompts/ source_ref"
            )

        expected_authority = _EXPECTED_AUTHORITY_BY_PROMPT_TYPE[self.prompt_type]
        if self.authority_level != expected_authority:
            raise ValueError(
                f"{self.prompt_type.value} must use "
                f"{expected_authority.value} authority"
            )

        expected_model_call_type = _EXPECTED_MODEL_CALL_BY_PROMPT_TYPE[
            self.prompt_type
        ]
        if self.model_call_type != expected_model_call_type:
            raise ValueError(
                f"{self.prompt_type.value} must use "
                f"{expected_model_call_type.value} model_call_type"
            )

        expected_cache_scope = _EXPECTED_CACHE_SCOPE_BY_PROMPT_TYPE.get(
            self.prompt_type
        )
        if (
            expected_cache_scope is not None
            and self.cache_scope != expected_cache_scope
        ):
            raise ValueError(
                f"{self.prompt_type.value} must use "
                f"{expected_cache_scope.value} cache_scope"
            )

        return self


_EXPECTED_AUTHORITY_BY_PROMPT_TYPE: dict[PromptType, PromptAuthorityLevel] = {
    PromptType.RUNTIME_INSTRUCTIONS: PromptAuthorityLevel.SYSTEM_TRUSTED,
    PromptType.STAGE_PROMPT_FRAGMENT: PromptAuthorityLevel.STAGE_CONTRACT_RENDERED,
    PromptType.STRUCTURED_OUTPUT_REPAIR: PromptAuthorityLevel.SYSTEM_TRUSTED,
    PromptType.COMPRESSION_PROMPT: PromptAuthorityLevel.SYSTEM_TRUSTED,
    PromptType.AGENT_ROLE_SEED: PromptAuthorityLevel.AGENT_ROLE_PROMPT,
    PromptType.TOOL_USAGE_TEMPLATE: PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
    PromptType.TOOL_PROMPT_FRAGMENT: PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
}

_EXPECTED_MODEL_CALL_BY_PROMPT_TYPE: dict[PromptType, ModelCallType] = {
    PromptType.RUNTIME_INSTRUCTIONS: ModelCallType.STAGE_EXECUTION,
    PromptType.STAGE_PROMPT_FRAGMENT: ModelCallType.STAGE_EXECUTION,
    PromptType.STRUCTURED_OUTPUT_REPAIR: ModelCallType.STRUCTURED_OUTPUT_REPAIR,
    PromptType.COMPRESSION_PROMPT: ModelCallType.CONTEXT_COMPRESSION,
    PromptType.AGENT_ROLE_SEED: ModelCallType.STAGE_EXECUTION,
    PromptType.TOOL_USAGE_TEMPLATE: ModelCallType.TOOL_CALL_PREPARATION,
    PromptType.TOOL_PROMPT_FRAGMENT: ModelCallType.TOOL_CALL_PREPARATION,
}

_EXPECTED_CACHE_SCOPE_BY_PROMPT_TYPE: dict[PromptType, PromptCacheScope] = {
    PromptType.RUNTIME_INSTRUCTIONS: PromptCacheScope.GLOBAL_STATIC,
    PromptType.STAGE_PROMPT_FRAGMENT: PromptCacheScope.RUN_STATIC,
    PromptType.STRUCTURED_OUTPUT_REPAIR: PromptCacheScope.DYNAMIC_UNCACHED,
    PromptType.COMPRESSION_PROMPT: PromptCacheScope.RUN_STATIC,
    PromptType.AGENT_ROLE_SEED: PromptCacheScope.GLOBAL_STATIC,
    PromptType.TOOL_USAGE_TEMPLATE: PromptCacheScope.RUN_STATIC,
    PromptType.TOOL_PROMPT_FRAGMENT: PromptCacheScope.GLOBAL_STATIC,
}


__all__ = [
    "ModelCallType",
    "PromptAssetRead",
    "PromptAssetRef",
    "PromptAuthorityLevel",
    "PromptCacheScope",
    "PromptRenderMetadata",
    "PromptSectionRead",
    "PromptType",
    "PromptVersionRef",
]
