from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON
from sqlalchemy import String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    ScmProviderType,
    SessionStatus,
    StageType,
    TemplateSource,
)


JsonObject = dict[str, Any]


def _contract_enum(enum_type: type, name: str) -> SqlEnum:
    return SqlEnum(
        enum_type,
        values_callable=lambda values: [item.value for item in values],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name,
    )


class ControlBase(DeclarativeBase):
    metadata = ROLE_METADATA[DatabaseRole.CONTROL]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectModel(ControlBase, TimestampMixin):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    default_delivery_channel_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    visibility_removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class PipelineTemplateModel(ControlBase, TimestampMixin):
    __tablename__ = "pipeline_templates"

    template_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_source: Mapped[TemplateSource] = mapped_column(
        _contract_enum(TemplateSource, "template_source"),
        nullable=False,
    )
    base_template_id: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("pipeline_templates.template_id"),
        nullable=True,
    )
    fixed_stage_sequence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    stage_role_bindings: Mapped[list[JsonObject]] = mapped_column(JSON, nullable=False)
    approval_checkpoints: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    auto_regression_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_auto_regression_retries: Mapped[int] = mapped_column(Integer, nullable=False)


class SessionModel(ControlBase, TimestampMixin):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("projects.project_id"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        _contract_enum(SessionStatus, "session_status"),
        nullable=False,
        default=SessionStatus.DRAFT,
    )
    selected_template_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_templates.template_id"),
        nullable=False,
    )
    current_run_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latest_stage_type: Mapped[StageType | None] = mapped_column(
        _contract_enum(StageType, "stage_type"),
        nullable=True,
    )
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    visibility_removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class StartupPublicationModel(ControlBase, TimestampMixin):
    __tablename__ = "startup_publications"

    publication_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("sessions.session_id"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage_run_id: Mapped[str] = mapped_column(String(80), nullable=False)
    publication_state: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    pending_session_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        unique=True,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    aborted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    abort_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProviderModel(ControlBase, TimestampMixin):
    __tablename__ = "providers"

    provider_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_source: Mapped[ProviderSource] = mapped_column(
        _contract_enum(ProviderSource, "provider_source"),
        nullable=False,
    )
    protocol_type: Mapped[ProviderProtocolType] = mapped_column(
        _contract_enum(ProviderProtocolType, "provider_protocol_type"),
        nullable=False,
    )
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    default_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    supported_model_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    runtime_capabilities: Mapped[list[JsonObject]] = mapped_column(JSON, nullable=False)


class DeliveryChannelModel(ControlBase, TimestampMixin):
    __tablename__ = "delivery_channels"

    delivery_channel_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("projects.project_id"),
        nullable=False,
        index=True,
    )
    delivery_mode: Mapped[DeliveryMode] = mapped_column(
        _contract_enum(DeliveryMode, "delivery_mode"),
        nullable=False,
    )
    scm_provider_type: Mapped[ScmProviderType | None] = mapped_column(
        _contract_enum(ScmProviderType, "scm_provider_type"),
        nullable=True,
    )
    repository_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    code_review_request_type: Mapped[CodeReviewRequestType | None] = mapped_column(
        _contract_enum(CodeReviewRequestType, "code_review_request_type"),
        nullable=True,
    )
    credential_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    credential_status: Mapped[CredentialStatus] = mapped_column(
        _contract_enum(CredentialStatus, "credential_status"),
        nullable=False,
        default=CredentialStatus.UNBOUND,
    )
    readiness_status: Mapped[DeliveryReadinessStatus] = mapped_column(
        _contract_enum(DeliveryReadinessStatus, "delivery_readiness_status"),
        nullable=False,
        default=DeliveryReadinessStatus.UNCONFIGURED,
    )
    readiness_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class PlatformRuntimeSettingsModel(ControlBase, TimestampMixin):
    __tablename__ = "platform_runtime_settings"

    settings_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    config_version: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    hard_limits_version: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_limits: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    provider_call_policy: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    internal_model_bindings: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    context_limits: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    log_policy: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    created_by_actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_by_actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_audit_log_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_trace_id: Mapped[str | None] = mapped_column(String(120), nullable=True)


__all__ = [
    "ControlBase",
    "DeliveryChannelModel",
    "PipelineTemplateModel",
    "PlatformRuntimeSettingsModel",
    "ProjectModel",
    "ProviderModel",
    "SessionModel",
    "StartupPublicationModel",
]
