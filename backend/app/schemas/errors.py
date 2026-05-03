from __future__ import annotations

from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.api.error_codes import ErrorCode


_SENSITIVE_MESSAGE_PATTERNS = (
    re.compile(r"Traceback"),
    re.compile(r"Authorization:", re.IGNORECASE),
    re.compile(r"Cookie:", re.IGNORECASE),
    re.compile(r"API Key", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])api_key(?![A-Za-z0-9_])", re.IGNORECASE),
    re.compile(r"private key", re.IGNORECASE),
)


def _reject_sensitive_message(value: str) -> str:
    if any(pattern.search(value) for pattern in _SENSITIVE_MESSAGE_PATTERNS):
        raise ValueError("message must not contain sensitive diagnostic details")
    return value


class ErrorCategory(StrEnum):
    API = "api"
    CONFIGURATION = "configuration"
    TOOL = "tool"
    PROVIDER = "provider"
    DELIVERY = "delivery"
    RUNTIME = "runtime"
    AUDIT = "audit"
    LOG = "log"


class ErrorCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    error_code: ErrorCode
    category: ErrorCategory
    default_http_status: int = Field(ge=100, le=599)
    retryable: bool
    user_visible: bool
    default_safe_title: str = Field(min_length=1)
    default_safe_message: str = Field(min_length=1)


class ApiErrorResponse(BaseModel):
    error_code: ErrorCode = Field(
        ...,
        description="Stable machine-readable error code.",
    )
    message: str = Field(..., min_length=1, description="Safe error summary.")
    request_id: str = Field(
        ...,
        min_length=1,
        description="Request correlation identifier.",
    )
    correlation_id: str = Field(
        ...,
        min_length=1,
        description="User action or command correlation identifier.",
    )
    detail_ref: str | None = Field(
        default=None,
        min_length=1,
        description="Optional stable reference to redacted diagnostic detail.",
    )
    trace_id: str | None = Field(
        default=None,
        min_length=1,
        description="Optional trace identifier when exposed by this error surface.",
    )
    span_id: str | None = Field(
        default=None,
        min_length=1,
        description="Optional span identifier when exposed by this error surface.",
    )

    _validate_message = field_validator("message")(_reject_sensitive_message)


__all__ = [
    "ApiErrorResponse",
    "ErrorCatalogEntry",
    "ErrorCategory",
]
