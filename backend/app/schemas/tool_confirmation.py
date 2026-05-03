from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from backend.app.schemas.feed import ToolConfirmationFeedEntry


class ToolConfirmationAllowRequest(BaseModel):
    pass


class ToolConfirmationDenyRequest(BaseModel):
    reason: str | None = Field(default=None, min_length=1)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Deny reason must not be blank.")
        return stripped


class ToolConfirmationCommandResponse(BaseModel):
    tool_confirmation: ToolConfirmationFeedEntry


__all__ = [
    "ToolConfirmationAllowRequest",
    "ToolConfirmationCommandResponse",
    "ToolConfirmationDenyRequest",
]
