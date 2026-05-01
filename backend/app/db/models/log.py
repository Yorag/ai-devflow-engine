from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON
from sqlalchemy import String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
    RedactionStatus,
)


JsonObject = dict[str, Any]
AUDIT_WRITE_FAILURE_BEHAVIOR = "reject_or_rollback_high_impact_action"
RUN_LOG_INDEX_FAILURE_BEHAVIOR = "diagnostic_error_without_domain_rollback"


def _contract_enum(enum_type: type, name: str) -> SqlEnum:
    return SqlEnum(
        enum_type,
        values_callable=lambda values: [item.value for item in values],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name,
    )


class LogBase(DeclarativeBase):
    metadata = ROLE_METADATA[DatabaseRole.LOG]


class LogPayloadModel(LogBase):
    __tablename__ = "log_payloads"

    payload_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    summary: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    storage_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(160), nullable=False)
    redaction_status: Mapped[RedactionStatus] = mapped_column(
        _contract_enum(RedactionStatus, "log_payload_redaction_status"),
        nullable=False,
    )
    payload_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunLogEntryModel(LogBase):
    __tablename__ = "run_log_entries"

    log_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    stage_run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    approval_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    tool_confirmation_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    delivery_record_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    graph_thread_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category: Mapped[LogCategory] = mapped_column(
        _contract_enum(LogCategory, "log_category"),
        nullable=False,
        index=True,
    )
    level: Mapped[LogLevel] = mapped_column(
        _contract_enum(LogLevel, "log_level"),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    log_file_ref: Mapped[str] = mapped_column(Text, nullable=False)
    line_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    log_file_generation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_ref: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("log_payloads.payload_id"),
        nullable=True,
        index=True,
    )
    payload_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redaction_status: Mapped[RedactionStatus] = mapped_column(
        _contract_enum(RedactionStatus, "run_log_redaction_status"),
        nullable=False,
    )
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    span_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class AuditLogEntryModel(LogBase):
    __tablename__ = "audit_log_entries"

    audit_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    actor_type: Mapped[AuditActorType] = mapped_column(
        _contract_enum(AuditActorType, "audit_actor_type"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    stage_run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    approval_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    tool_confirmation_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    delivery_record_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    result: Mapped[AuditResult] = mapped_column(
        _contract_enum(AuditResult, "audit_result"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_ref: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("log_payloads.payload_id"),
        nullable=True,
        index=True,
    )
    metadata_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    span_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    audit_file_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_file_generation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    audit_file_write_failed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


__all__ = [
    "AUDIT_WRITE_FAILURE_BEHAVIOR",
    "RUN_LOG_INDEX_FAILURE_BEHAVIOR",
    "AuditLogEntryModel",
    "LogBase",
    "LogPayloadModel",
    "RunLogEntryModel",
]
