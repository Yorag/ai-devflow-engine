from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from backend.app.schemas.feed import ApprovalResultFeedEntry, ControlItemFeedEntry


class ApprovalApproveRequest(BaseModel):
    pass


class ApprovalRejectRequest(BaseModel):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reject reason must not be blank.")
        return stripped


class ApprovalCommandResponse(BaseModel):
    approval_result: ApprovalResultFeedEntry
    control_item: ControlItemFeedEntry | None = None


__all__ = [
    "ApprovalApproveRequest",
    "ApprovalCommandResponse",
    "ApprovalRejectRequest",
]
