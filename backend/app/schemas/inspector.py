from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas import common
from backend.app.schemas.metrics import MetricSet
from backend.app.schemas.run import SolutionImplementationPlanRead


JsonObject = dict[str, Any]


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectorSection(_StrictBaseModel):
    title: str = Field(min_length=1)
    records: JsonObject = Field(default_factory=dict)
    stable_refs: list[str] = Field(default_factory=list)
    log_refs: list[str] = Field(default_factory=list)
    truncated: bool = False
    redaction_status: Literal["none", "redacted", "blocked"] = "none"


class _InspectorProjectionBase(_StrictBaseModel):
    identity: InspectorSection
    input: InspectorSection
    process: InspectorSection
    output: InspectorSection
    artifacts: InspectorSection
    metrics: MetricSet


class StageInspectorProjection(_InspectorProjectionBase):
    stage_run_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_type: common.StageType
    status: common.StageStatus
    attempt_index: int = Field(ge=1)
    started_at: datetime
    ended_at: datetime | None = None
    implementation_plan: SolutionImplementationPlanRead | None = None
    tool_confirmation_trace_refs: list[str] = Field(default_factory=list)
    provider_retry_trace_refs: list[str] = Field(default_factory=list)
    provider_circuit_breaker_trace_refs: list[str] = Field(default_factory=list)
    approval_result_refs: list[str] = Field(default_factory=list)


class ControlItemInspectorProjection(_InspectorProjectionBase):
    control_record_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    control_type: common.ControlItemType
    source_stage_type: common.StageType
    target_stage_type: common.StageType | None = None
    occurred_at: datetime


class ToolConfirmationInspectorProjection(_InspectorProjectionBase):
    tool_confirmation_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    status: common.ToolConfirmationStatus
    requested_at: datetime
    responded_at: datetime | None = None
    tool_name: str = Field(min_length=1)
    command_preview: str | None = None
    target_summary: str = Field(min_length=1)
    risk_level: Literal[common.ToolRiskLevel.HIGH_RISK] = common.ToolRiskLevel.HIGH_RISK
    risk_categories: list[common.ToolRiskCategory] = Field(min_length=1)
    reason: str = Field(min_length=1)
    expected_side_effects: list[str] = Field(default_factory=list)
    decision: (
        Literal[
            common.ToolConfirmationStatus.ALLOWED,
            common.ToolConfirmationStatus.DENIED,
        ]
        | None
    ) = None


class DeliveryResultDetailProjection(_InspectorProjectionBase):
    delivery_record_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    delivery_mode: common.DeliveryMode
    status: Literal["succeeded"]
    created_at: datetime


__all__ = [
    "ControlItemInspectorProjection",
    "DeliveryResultDetailProjection",
    "InspectorSection",
    "StageInspectorProjection",
    "ToolConfirmationInspectorProjection",
]
