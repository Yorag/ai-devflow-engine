from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogCategory(StrEnum):
    RUNTIME = "runtime"
    AGENT = "agent"
    TOOL = "tool"
    MODEL = "model"
    WORKSPACE = "workspace"
    DELIVERY = "delivery"
    API = "api"
    SECURITY = "security"
    ERROR = "error"


class AuditActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"
    TOOL = "tool"


class AuditResult(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class RedactionStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    REDACTED = "redacted"
    BLOCKED = "blocked"
    UNSERIALIZABLE = "unserializable"


class _TimeRangeQuery(_StrictBaseModel):
    since: datetime | None = None
    until: datetime | None = None
    cursor: str | None = Field(default=None, min_length=1)
    limit: PositiveInt = Field(default=100, le=500)

    @model_validator(mode="after")
    def validate_time_range(self) -> "_TimeRangeQuery":
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("since must be less than or equal to until")
        return self


class RunLogQuery(_TimeRangeQuery):
    run_id: str | None = Field(default=None, min_length=1)
    stage_run_id: str | None = Field(default=None, min_length=1)
    correlation_id: str | None = Field(default=None, min_length=1)
    level: LogLevel | None = None
    category: LogCategory | None = None
    source: str | None = Field(default=None, min_length=1)


class AuditLogQuery(_TimeRangeQuery):
    actor_type: AuditActorType | None = None
    action: str | None = Field(default=None, min_length=1)
    target_type: str | None = Field(default=None, min_length=1)
    target_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    stage_run_id: str | None = Field(default=None, min_length=1)
    correlation_id: str | None = Field(default=None, min_length=1)
    result: AuditResult | None = None


class RunLogEntryProjection(_StrictBaseModel):
    log_id: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    stage_run_id: str | None = Field(default=None, min_length=1)
    approval_id: str | None = Field(default=None, min_length=1)
    tool_confirmation_id: str | None = Field(default=None, min_length=1)
    delivery_record_id: str | None = Field(default=None, min_length=1)
    graph_thread_id: str | None = Field(default=None, min_length=1)
    request_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    category: LogCategory
    level: LogLevel
    message: str = Field(min_length=1)
    log_file_ref: str = Field(min_length=1)
    line_offset: int = Field(ge=0)
    line_number: PositiveInt
    log_file_generation: str | None = Field(default=None, min_length=1)
    payload_ref: str | None = Field(default=None, min_length=1)
    payload_excerpt: str | None = None
    payload_size_bytes: int = Field(default=0, ge=0)
    redaction_status: RedactionStatus
    correlation_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    parent_span_id: str | None = Field(default=None, min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_log_file_ref_is_runtime_relative(self) -> "RunLogEntryProjection":
        normalized = self.log_file_ref.replace("\\", "/")
        parts = normalized.split("/")
        if (
            normalized.startswith("/")
            or ":" in normalized
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("log_file_ref must be relative to platform runtime root")
        return self


class AuditLogEntryProjection(_StrictBaseModel):
    audit_id: str = Field(min_length=1)
    actor_type: AuditActorType
    actor_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    stage_run_id: str | None = Field(default=None, min_length=1)
    approval_id: str | None = Field(default=None, min_length=1)
    tool_confirmation_id: str | None = Field(default=None, min_length=1)
    delivery_record_id: str | None = Field(default=None, min_length=1)
    request_id: str = Field(min_length=1)
    result: AuditResult
    reason: str | None = None
    metadata_ref: str | None = Field(default=None, min_length=1)
    metadata_excerpt: str | None = None
    correlation_id: str = Field(min_length=1)
    trace_id: str | None = Field(default=None, min_length=1)
    span_id: str | None = Field(default=None, min_length=1)
    created_at: datetime


__all__ = [
    "AuditActorType",
    "AuditLogEntryProjection",
    "AuditLogQuery",
    "AuditResult",
    "LogCategory",
    "LogLevel",
    "RedactionStatus",
    "RunLogEntryProjection",
    "RunLogQuery",
]
