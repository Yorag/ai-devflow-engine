from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas import common


JsonObject: TypeAlias = dict[str, Any]


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeedEntry(_StrictBaseModel):
    entry_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    type: common.FeedEntryType
    occurred_at: datetime


class MessageFeedEntry(FeedEntry):
    type: Literal[common.FeedEntryType.USER_MESSAGE] = common.FeedEntryType.USER_MESSAGE
    message_id: str = Field(min_length=1)
    author: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1)
    stage_run_id: str | None = None


class StageItemProjection(_StrictBaseModel):
    item_id: str = Field(min_length=1)
    type: Literal[
        common.StageItemType.DIALOGUE,
        common.StageItemType.CONTEXT,
        common.StageItemType.REASONING,
        common.StageItemType.DECISION,
        common.StageItemType.MODEL_CALL,
        common.StageItemType.TOOL_CALL,
        common.StageItemType.TOOL_CONFIRMATION,
        common.StageItemType.DIFF_PREVIEW,
        common.StageItemType.RESULT,
    ]
    occurred_at: datetime
    title: str = Field(min_length=1)
    summary: str | None = None
    content: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    metrics: JsonObject = Field(default_factory=dict)


class ProviderCallStageItem(_StrictBaseModel):
    item_id: str = Field(min_length=1)
    type: Literal[common.StageItemType.PROVIDER_CALL] = (
        common.StageItemType.PROVIDER_CALL
    )
    occurred_at: datetime
    title: str = Field(min_length=1)
    summary: str | None = None
    content: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    metrics: JsonObject = Field(default_factory=dict)
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    status: Literal[
        "queued",
        "running",
        "retrying",
        "succeeded",
        "failed",
        "circuit_open",
    ]
    retry_attempt: int = Field(ge=0)
    max_retry_attempts: int = Field(ge=0)
    backoff_wait_seconds: int | None = Field(default=None, ge=0)
    circuit_breaker_status: common.ProviderCircuitBreakerStatus
    failure_reason: str | None = None
    process_ref: str | None = None


StageNodeItem: TypeAlias = Annotated[
    StageItemProjection | ProviderCallStageItem,
    Field(discriminator="type"),
]


class ExecutionNodeProjection(FeedEntry):
    type: Literal[common.FeedEntryType.STAGE_NODE] = common.FeedEntryType.STAGE_NODE
    stage_run_id: str = Field(min_length=1)
    stage_type: common.StageType
    status: common.StageStatus
    attempt_index: int = Field(ge=1)
    started_at: datetime
    ended_at: datetime | None = None
    summary: str = Field(min_length=1)
    items: list[StageNodeItem] = Field(default_factory=list)
    metrics: JsonObject = Field(default_factory=dict)


class ApprovalRequestFeedEntry(FeedEntry):
    type: Literal[common.FeedEntryType.APPROVAL_REQUEST] = (
        common.FeedEntryType.APPROVAL_REQUEST
    )
    approval_id: str = Field(min_length=1)
    approval_type: common.ApprovalType
    status: common.ApprovalStatus
    title: str = Field(min_length=1)
    approval_object_excerpt: str
    risk_excerpt: str | None = None
    approval_object_preview: JsonObject = Field(default_factory=dict)
    approve_action: str = Field(min_length=1)
    reject_action: str = Field(min_length=1)
    is_actionable: bool
    requested_at: datetime
    delivery_readiness_status: common.DeliveryReadinessStatus | None = None
    delivery_readiness_message: str | None = None
    open_settings_action: str | None = None
    disabled_reason: str | None = None


class ToolConfirmationFeedEntry(FeedEntry):
    type: Literal[common.FeedEntryType.TOOL_CONFIRMATION] = (
        common.FeedEntryType.TOOL_CONFIRMATION
    )
    stage_run_id: str = Field(min_length=1)
    tool_confirmation_id: str = Field(min_length=1)
    status: common.ToolConfirmationStatus
    title: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    command_preview: str | None = None
    target_summary: str = Field(min_length=1)
    risk_level: common.ToolRiskLevel
    risk_categories: list[common.ToolRiskCategory] = Field(min_length=1)
    reason: str = Field(min_length=1)
    expected_side_effects: list[str] = Field(default_factory=list)
    allow_action: str = Field(min_length=1)
    deny_action: str = Field(min_length=1)
    is_actionable: bool
    requested_at: datetime
    responded_at: datetime | None = None
    decision: (
        Literal[
            common.ToolConfirmationStatus.ALLOWED,
            common.ToolConfirmationStatus.DENIED,
        ]
        | None
    ) = None
    disabled_reason: str | None = None

    @model_validator(mode="after")
    def require_high_risk_tool_confirmation(self) -> "ToolConfirmationFeedEntry":
        if self.risk_level is not common.ToolRiskLevel.HIGH_RISK:
            raise ValueError("tool_confirmation risk_level must be high_risk")
        return self


class ControlItemFeedEntry(FeedEntry):
    type: Literal[common.FeedEntryType.CONTROL_ITEM] = common.FeedEntryType.CONTROL_ITEM
    control_record_id: str = Field(min_length=1)
    control_type: common.ControlItemType
    source_stage_type: common.StageType
    target_stage_type: common.StageType | None = None
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    payload_ref: str | None = None


class ApprovalResultFeedEntry(FeedEntry):
    type: Literal[common.FeedEntryType.APPROVAL_RESULT] = (
        common.FeedEntryType.APPROVAL_RESULT
    )
    approval_id: str = Field(min_length=1)
    approval_type: common.ApprovalType
    decision: Literal[
        common.ApprovalStatus.APPROVED,
        common.ApprovalStatus.REJECTED,
    ]
    reason: str | None = None
    created_at: datetime
    next_stage_type: common.StageType

    @model_validator(mode="after")
    def require_reject_reason(self) -> "ApprovalResultFeedEntry":
        if self.decision is common.ApprovalStatus.REJECTED and not self.reason:
            raise ValueError("approval_result rejected decision requires reason")
        return self


class DeliveryResultFeedEntry(FeedEntry):
    type: Literal[common.FeedEntryType.DELIVERY_RESULT] = (
        common.FeedEntryType.DELIVERY_RESULT
    )
    delivery_record_id: str = Field(min_length=1)
    delivery_mode: common.DeliveryMode
    status: Literal["succeeded"]
    summary: str = Field(min_length=1)
    branch_name: str | None = None
    commit_sha: str | None = None
    code_review_url: str | None = None
    test_summary: str | None = None
    result_ref: str | None = None


class SystemStatusFeedEntry(FeedEntry):
    type: Literal[common.FeedEntryType.SYSTEM_STATUS] = (
        common.FeedEntryType.SYSTEM_STATUS
    )
    status: Literal[common.RunStatus.FAILED, common.RunStatus.TERMINATED]
    title: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    retry_action: str | None = None


TopLevelFeedEntry: TypeAlias = Annotated[
    MessageFeedEntry
    | ExecutionNodeProjection
    | ApprovalRequestFeedEntry
    | ToolConfirmationFeedEntry
    | ControlItemFeedEntry
    | ApprovalResultFeedEntry
    | DeliveryResultFeedEntry
    | SystemStatusFeedEntry,
    Field(discriminator="type"),
]


__all__ = [
    "ApprovalRequestFeedEntry",
    "ApprovalResultFeedEntry",
    "ControlItemFeedEntry",
    "DeliveryResultFeedEntry",
    "ExecutionNodeProjection",
    "FeedEntry",
    "MessageFeedEntry",
    "ProviderCallStageItem",
    "StageItemProjection",
    "StageNodeItem",
    "SystemStatusFeedEntry",
    "ToolConfirmationFeedEntry",
    "TopLevelFeedEntry",
]
