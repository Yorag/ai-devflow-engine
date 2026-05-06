from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas import common


FIXED_STAGE_SEQUENCE = (
    common.StageType.REQUIREMENT_ANALYSIS,
    common.StageType.SOLUTION_DESIGN,
    common.StageType.CODE_GENERATION,
    common.StageType.TEST_GENERATION_EXECUTION,
    common.StageType.CODE_REVIEW,
    common.StageType.DELIVERY_INTEGRATION,
)

FIXED_APPROVAL_CHECKPOINTS = (
    common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
    common.ApprovalType.CODE_REVIEW_APPROVAL,
)


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentRoleConfig(_StrictBaseModel):
    role_id: str = Field(min_length=1)
    role_name: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)


class StageRoleBinding(_StrictBaseModel):
    stage_type: common.StageType
    role_id: str = Field(min_length=1)
    stage_work_instruction: str = Field(
        min_length=1,
        validation_alias=AliasChoices("stage_work_instruction", "system_prompt"),
    )
    system_prompt: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)


class PipelineTemplateRead(_StrictBaseModel):
    template_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    template_source: common.TemplateSource
    base_template_id: str | None = None
    fixed_stage_sequence: list[common.StageType]
    stage_role_bindings: list[StageRoleBinding]
    approval_checkpoints: list[common.ApprovalType]
    auto_regression_enabled: bool
    max_auto_regression_retries: int = Field(ge=0)
    max_react_iterations_per_stage: int = Field(gt=0)
    max_tool_calls_per_stage: int = Field(gt=0)
    skip_high_risk_tool_confirmations: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("fixed_stage_sequence")
    @classmethod
    def require_fixed_stage_sequence(
        cls,
        value: list[common.StageType],
    ) -> list[common.StageType]:
        if tuple(value) != FIXED_STAGE_SEQUENCE:
            raise ValueError(
                "fixed_stage_sequence must match the Function One V1 stage order"
            )
        return value

    @field_validator("approval_checkpoints")
    @classmethod
    def require_fixed_approval_checkpoints(
        cls,
        value: list[common.ApprovalType],
    ) -> list[common.ApprovalType]:
        if tuple(value) != FIXED_APPROVAL_CHECKPOINTS:
            raise ValueError(
                "approval_checkpoints must contain the two Function One V1 checkpoints"
            )
        return value


class PipelineTemplateWriteRequest(_StrictBaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    fixed_stage_sequence: list[common.StageType] = Field(
        default_factory=lambda: list(FIXED_STAGE_SEQUENCE)
    )
    stage_role_bindings: list[StageRoleBinding] = Field(min_length=1)
    approval_checkpoints: list[common.ApprovalType] = Field(
        default_factory=lambda: list(FIXED_APPROVAL_CHECKPOINTS)
    )
    auto_regression_enabled: bool
    max_auto_regression_retries: int = Field(ge=0)
    max_react_iterations_per_stage: int = Field(gt=0)
    max_tool_calls_per_stage: int = Field(gt=0)
    skip_high_risk_tool_confirmations: bool

    @field_validator("fixed_stage_sequence")
    @classmethod
    def require_fixed_stage_sequence(
        cls,
        value: list[common.StageType],
    ) -> list[common.StageType]:
        if tuple(value) != FIXED_STAGE_SEQUENCE:
            raise ValueError(
                "fixed_stage_sequence must match the Function One V1 stage order"
            )
        return value

    @field_validator("approval_checkpoints")
    @classmethod
    def require_fixed_approval_checkpoints(
        cls,
        value: list[common.ApprovalType],
    ) -> list[common.ApprovalType]:
        if tuple(value) != FIXED_APPROVAL_CHECKPOINTS:
            raise ValueError(
                "approval_checkpoints must contain the two Function One V1 checkpoints"
            )
        return value


__all__ = [
    "AgentRoleConfig",
    "FIXED_APPROVAL_CHECKPOINTS",
    "FIXED_STAGE_SEQUENCE",
    "PipelineTemplateRead",
    "PipelineTemplateWriteRequest",
    "StageRoleBinding",
]
