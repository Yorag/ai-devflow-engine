from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from pydantic import field_validator

from backend.app.domain.enums import ApprovalType, StageType, TemplateSource
from backend.app.schemas.template import (
    FIXED_APPROVAL_CHECKPOINTS,
    FIXED_STAGE_SEQUENCE,
)


TEMPLATE_SNAPSHOT_SCHEMA_VERSION = "template-snapshot-v1"


class StageRoleSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_type: StageType
    role_id: StrictStr = Field(min_length=1)
    system_prompt: StrictStr = Field(min_length=1)
    provider_id: StrictStr = Field(min_length=1)


class TemplateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_ref: StrictStr = Field(min_length=1)
    run_id: StrictStr = Field(min_length=1)
    source_template_id: StrictStr = Field(min_length=1)
    source_template_name: StrictStr = Field(min_length=1)
    source_template: TemplateSource
    source_template_updated_at: datetime
    fixed_stage_sequence: tuple[StageType, ...]
    stage_role_bindings: tuple[StageRoleSnapshot, ...]
    approval_checkpoints: tuple[ApprovalType, ...]
    auto_regression_enabled: StrictBool
    max_auto_regression_retries: StrictInt = Field(ge=0)
    max_react_iterations_per_stage: StrictInt = Field(gt=0)
    max_tool_calls_per_stage: StrictInt = Field(gt=0)
    skip_high_risk_tool_confirmations: StrictBool
    schema_version: Literal["template-snapshot-v1"] = TEMPLATE_SNAPSHOT_SCHEMA_VERSION
    created_at: datetime

    @field_validator("fixed_stage_sequence")
    @classmethod
    def require_fixed_stage_sequence(
        cls,
        value: tuple[StageType, ...],
    ) -> tuple[StageType, ...]:
        if value != tuple(FIXED_STAGE_SEQUENCE):
            raise ValueError(
                "fixed_stage_sequence must match the Function One stage order"
            )
        return value

    @field_validator("stage_role_bindings")
    @classmethod
    def require_one_binding_per_stage(
        cls,
        value: tuple[StageRoleSnapshot, ...],
    ) -> tuple[StageRoleSnapshot, ...]:
        expected = tuple(FIXED_STAGE_SEQUENCE)
        actual = tuple(binding.stage_type for binding in value)
        if actual != expected:
            raise ValueError("stage_role_bindings must match fixed_stage_sequence")
        return value

    @field_validator("approval_checkpoints")
    @classmethod
    def require_fixed_approval_checkpoints(
        cls,
        value: tuple[ApprovalType, ...],
    ) -> tuple[ApprovalType, ...]:
        if value != tuple(FIXED_APPROVAL_CHECKPOINTS):
            raise ValueError(
                "approval_checkpoints must match the Function One checkpoints"
            )
        return value


class TemplateSnapshotBuilder:
    @staticmethod
    def _require_binding(
        binding: Any,
        *,
        index: int,
    ) -> dict[str, Any]:
        if not isinstance(binding, dict):
            raise ValueError(f"stage_role_bindings[{index}] must be an object")
        return binding

    @staticmethod
    def _require_stage_type(
        binding: dict[str, Any],
        *,
        index: int,
    ) -> StageType:
        value = binding.get("stage_type")
        if value is None:
            raise ValueError(f"stage_role_bindings[{index}].stage_type is required")
        return StageType(value)

    @staticmethod
    def _require_string(
        binding: dict[str, Any],
        *,
        key: str,
        index: int,
    ) -> str:
        value = binding.get(key)
        if not isinstance(value, str):
            raise ValueError(f"stage_role_bindings[{index}].{key} must be a string")
        return value

    @staticmethod
    def _require_bool(template: Any, field_name: str) -> bool:
        value = getattr(template, field_name)
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} must be a boolean")
        return value

    @staticmethod
    def _require_int(template: Any, field_name: str) -> int:
        value = getattr(template, field_name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{field_name} must be an integer")
        return value

    @staticmethod
    def build_for_run(
        template: Any,
        *,
        run_id: str,
        created_at: datetime,
    ) -> TemplateSnapshot:
        bindings = tuple(
            StageRoleSnapshot(
                stage_type=TemplateSnapshotBuilder._require_stage_type(
                    TemplateSnapshotBuilder._require_binding(binding, index=index),
                    index=index,
                ),
                role_id=TemplateSnapshotBuilder._require_string(
                    TemplateSnapshotBuilder._require_binding(binding, index=index),
                    key="role_id",
                    index=index,
                ),
                system_prompt=TemplateSnapshotBuilder._require_string(
                    TemplateSnapshotBuilder._require_binding(binding, index=index),
                    key="system_prompt",
                    index=index,
                ).strip(),
                provider_id=TemplateSnapshotBuilder._require_string(
                    TemplateSnapshotBuilder._require_binding(binding, index=index),
                    key="provider_id",
                    index=index,
                ),
            )
            for index, binding in enumerate(list(template.stage_role_bindings))
        )
        return TemplateSnapshot(
            snapshot_ref=f"template-snapshot-{run_id}",
            run_id=run_id,
            source_template_id=template.template_id,
            source_template_name=template.name,
            source_template=template.template_source,
            source_template_updated_at=template.updated_at,
            fixed_stage_sequence=tuple(
                StageType(stage) for stage in list(template.fixed_stage_sequence)
            ),
            stage_role_bindings=bindings,
            approval_checkpoints=tuple(
                ApprovalType(checkpoint)
                for checkpoint in list(template.approval_checkpoints)
            ),
            auto_regression_enabled=TemplateSnapshotBuilder._require_bool(
                template,
                "auto_regression_enabled",
            ),
            max_auto_regression_retries=TemplateSnapshotBuilder._require_int(
                template,
                "max_auto_regression_retries",
            ),
            max_react_iterations_per_stage=TemplateSnapshotBuilder._require_int(
                template,
                "max_react_iterations_per_stage",
            ),
            max_tool_calls_per_stage=TemplateSnapshotBuilder._require_int(
                template,
                "max_tool_calls_per_stage",
            ),
            skip_high_risk_tool_confirmations=TemplateSnapshotBuilder._require_bool(
                template,
                "skip_high_risk_tool_confirmations",
            ),
            created_at=created_at,
        )


__all__ = [
    "TEMPLATE_SNAPSHOT_SCHEMA_VERSION",
    "StageRoleSnapshot",
    "TemplateSnapshot",
    "TemplateSnapshotBuilder",
]
