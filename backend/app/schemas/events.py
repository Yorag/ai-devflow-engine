from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas import common
from backend.app.schemas.feed import (
    ApprovalRequestFeedEntry,
    ApprovalResultFeedEntry,
    ControlItemFeedEntry,
    DeliveryResultFeedEntry,
    ExecutionNodeProjection,
    MessageFeedEntry,
    SystemStatusFeedEntry,
    ToolConfirmationFeedEntry,
)
from backend.app.schemas.run import RunSummaryProjection
from backend.app.schemas.session import SessionRead


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PayloadModel = type[BaseModel]


class SessionEvent(_StrictBaseModel):
    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    run_id: str | None = None
    event_type: common.SseEventType
    occurred_at: datetime
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_payload_contract(self) -> "SessionEvent":
        required_key = _EVENT_REQUIRED_KEYS[self.event_type]
        if required_key not in self.payload:
            raise ValueError(
                f"{self.event_type.value} payload must include {required_key}"
            )
        allowed_keys = _EVENT_ALLOWED_KEYS[self.event_type]
        extra_keys = set(self.payload) - allowed_keys
        if extra_keys:
            raise ValueError(
                f"{self.event_type.value} payload contains unsupported keys: "
                f"{', '.join(sorted(extra_keys))}"
            )

        payload_model = _EVENT_PAYLOAD_MODELS.get(self.event_type)
        if payload_model is not None:
            payload_model.model_validate(self.payload[required_key])

        if self.event_type is common.SseEventType.CLARIFICATION_REQUESTED:
            _require_keys(self.payload, "run_id", "stage_run_id", "control_item")
            ControlItemFeedEntry.model_validate(self.payload["control_item"])
        elif self.event_type is common.SseEventType.CLARIFICATION_ANSWERED:
            _require_keys(self.payload, "run_id", "stage_run_id", "message_item")
            MessageFeedEntry.model_validate(self.payload["message_item"])
        elif self.event_type is common.SseEventType.SESSION_STATUS_CHANGED:
            _require_keys(
                self.payload,
                "session_id",
                "status",
                "current_run_id",
                "current_stage_type",
            )
            common.SessionStatus(self.payload["status"])
            if self.payload["current_stage_type"] is not None:
                common.StageType(self.payload["current_stage_type"])

        return self


def _require_keys(payload: dict[str, Any], *keys: str) -> None:
    missing_keys = [key for key in keys if key not in payload]
    if missing_keys:
        raise ValueError(f"payload missing required keys: {', '.join(missing_keys)}")


_EVENT_REQUIRED_KEYS: dict[common.SseEventType, str] = {
    common.SseEventType.SESSION_CREATED: "session",
    common.SseEventType.SESSION_MESSAGE_APPENDED: "message_item",
    common.SseEventType.PIPELINE_RUN_CREATED: "run",
    common.SseEventType.STAGE_STARTED: "stage_node",
    common.SseEventType.STAGE_UPDATED: "stage_node",
    common.SseEventType.CLARIFICATION_REQUESTED: "control_item",
    common.SseEventType.CLARIFICATION_ANSWERED: "message_item",
    common.SseEventType.APPROVAL_REQUESTED: "approval_request",
    common.SseEventType.APPROVAL_RESULT: "approval_result",
    common.SseEventType.TOOL_CONFIRMATION_REQUESTED: "tool_confirmation",
    common.SseEventType.TOOL_CONFIRMATION_RESULT: "tool_confirmation",
    common.SseEventType.CONTROL_ITEM_CREATED: "control_item",
    common.SseEventType.DELIVERY_RESULT: "delivery_result",
    common.SseEventType.SYSTEM_STATUS: "system_status",
    common.SseEventType.SESSION_STATUS_CHANGED: "session_id",
}

_EVENT_ALLOWED_KEYS: dict[common.SseEventType, set[str]] = {
    common.SseEventType.SESSION_CREATED: {"session"},
    common.SseEventType.SESSION_MESSAGE_APPENDED: {"message_item"},
    common.SseEventType.PIPELINE_RUN_CREATED: {"run"},
    common.SseEventType.STAGE_STARTED: {"stage_node"},
    common.SseEventType.STAGE_UPDATED: {"stage_node"},
    common.SseEventType.CLARIFICATION_REQUESTED: {
        "run_id",
        "stage_run_id",
        "control_item",
    },
    common.SseEventType.CLARIFICATION_ANSWERED: {
        "run_id",
        "stage_run_id",
        "message_item",
    },
    common.SseEventType.APPROVAL_REQUESTED: {"approval_request"},
    common.SseEventType.APPROVAL_RESULT: {"approval_result"},
    common.SseEventType.TOOL_CONFIRMATION_REQUESTED: {"tool_confirmation"},
    common.SseEventType.TOOL_CONFIRMATION_RESULT: {"tool_confirmation"},
    common.SseEventType.CONTROL_ITEM_CREATED: {"control_item"},
    common.SseEventType.DELIVERY_RESULT: {"delivery_result"},
    common.SseEventType.SYSTEM_STATUS: {"system_status"},
    common.SseEventType.SESSION_STATUS_CHANGED: {
        "session_id",
        "status",
        "current_run_id",
        "current_stage_type",
    },
}

_EVENT_PAYLOAD_MODELS: dict[common.SseEventType, PayloadModel] = {
    common.SseEventType.SESSION_CREATED: SessionRead,
    common.SseEventType.SESSION_MESSAGE_APPENDED: MessageFeedEntry,
    common.SseEventType.PIPELINE_RUN_CREATED: RunSummaryProjection,
    common.SseEventType.STAGE_STARTED: ExecutionNodeProjection,
    common.SseEventType.STAGE_UPDATED: ExecutionNodeProjection,
    common.SseEventType.CLARIFICATION_ANSWERED: MessageFeedEntry,
    common.SseEventType.APPROVAL_REQUESTED: ApprovalRequestFeedEntry,
    common.SseEventType.APPROVAL_RESULT: ApprovalResultFeedEntry,
    common.SseEventType.TOOL_CONFIRMATION_REQUESTED: ToolConfirmationFeedEntry,
    common.SseEventType.TOOL_CONFIRMATION_RESULT: ToolConfirmationFeedEntry,
    common.SseEventType.CONTROL_ITEM_CREATED: ControlItemFeedEntry,
    common.SseEventType.DELIVERY_RESULT: DeliveryResultFeedEntry,
    common.SseEventType.SYSTEM_STATUS: SystemStatusFeedEntry,
}


__all__ = [
    "SessionEvent",
]
