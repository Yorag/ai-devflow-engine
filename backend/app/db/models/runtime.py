from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    RunControlRecordType,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
    ToolRiskLevel,
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


class RuntimeBase(DeclarativeBase):
    metadata = ROLE_METADATA[DatabaseRole.RUNTIME]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PipelineRunModel(RuntimeBase, TimestampMixin):
    __tablename__ = "pipeline_runs"

    run_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        _contract_enum(RunStatus, "run_status"),
        nullable=False,
    )
    trigger_source: Mapped[RunTriggerSource] = mapped_column(
        _contract_enum(RunTriggerSource, "run_trigger_source"),
        nullable=False,
    )
    template_snapshot_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    graph_definition_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    graph_thread_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    workspace_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    runtime_limit_snapshot_ref: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("runtime_limit_snapshots.snapshot_id"),
        nullable=False,
        index=True,
    )
    provider_call_policy_snapshot_ref: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("provider_call_policy_snapshots.snapshot_id"),
        nullable=False,
        index=True,
    )
    delivery_channel_snapshot_ref: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("delivery_channel_snapshots.delivery_channel_snapshot_id"),
        nullable=True,
        index=True,
    )
    current_stage_run_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    trace_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuntimeLimitSnapshotModel(RuntimeBase):
    __tablename__ = "runtime_limit_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        index=True,
    )
    agent_limits: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    context_limits: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    source_config_version: Mapped[str] = mapped_column(String(120), nullable=False)
    hard_limits_version: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderCallPolicySnapshotModel(RuntimeBase):
    __tablename__ = "provider_call_policy_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        index=True,
    )
    provider_call_policy: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    source_config_version: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderSnapshotModel(RuntimeBase):
    __tablename__ = "provider_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
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
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    capabilities: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    source_config_version: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelBindingSnapshotModel(RuntimeBase):
    __tablename__ = "model_binding_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    binding_id: Mapped[str] = mapped_column(String(120), nullable=False)
    binding_type: Mapped[str] = mapped_column(String(80), nullable=False)
    stage_type: Mapped[StageType | None] = mapped_column(
        _contract_enum(StageType, "model_binding_snapshot_stage_type"),
        nullable=True,
    )
    role_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_snapshot_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("provider_snapshots.snapshot_id"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    capabilities: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    model_parameters: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    source_config_version: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StageRunModel(RuntimeBase, TimestampMixin):
    __tablename__ = "stage_runs"

    stage_run_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    stage_type: Mapped[StageType] = mapped_column(
        _contract_enum(StageType, "stage_run_stage_type"),
        nullable=False,
    )
    status: Mapped[StageStatus] = mapped_column(
        _contract_enum(StageStatus, "stage_status"),
        nullable=False,
    )
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_node_key: Mapped[str] = mapped_column(String(160), nullable=False)
    stage_contract_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    input_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    output_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StageArtifactModel(RuntimeBase):
    __tablename__ = "stage_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    stage_run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("stage_runs.stage_run_id"),
        nullable=False,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    process: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    metrics: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClarificationRecordModel(RuntimeBase, TimestampMixin):
    __tablename__ = "clarification_records"

    clarification_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    stage_run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("stage_runs.stage_run_id"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    graph_interrupt_ref: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRequestModel(RuntimeBase, TimestampMixin):
    __tablename__ = "approval_requests"

    approval_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    stage_run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("stage_runs.stage_run_id"),
        nullable=False,
        index=True,
    )
    approval_type: Mapped[ApprovalType] = mapped_column(
        _contract_enum(ApprovalType, "approval_type"),
        nullable=False,
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        _contract_enum(ApprovalStatus, "approval_status"),
        nullable=False,
    )
    payload_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    graph_interrupt_ref: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalDecisionModel(RuntimeBase):
    __tablename__ = "approval_decisions"

    decision_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    approval_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("approval_requests.approval_id"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    decision: Mapped[ApprovalStatus] = mapped_column(
        _contract_enum(ApprovalStatus, "approval_status"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolConfirmationRequestModel(RuntimeBase, TimestampMixin):
    __tablename__ = "tool_confirmation_requests"

    tool_confirmation_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    stage_run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("stage_runs.stage_run_id"),
        nullable=False,
        index=True,
    )
    confirmation_object_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    command_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[ToolRiskLevel] = mapped_column(
        _contract_enum(ToolRiskLevel, "tool_risk_level"),
        nullable=False,
    )
    risk_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expected_side_effects: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    alternative_path_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_decision: Mapped[ToolConfirmationStatus | None] = mapped_column(
        _contract_enum(ToolConfirmationStatus, "tool_confirmation_user_decision"),
        nullable=True,
    )
    status: Mapped[ToolConfirmationStatus] = mapped_column(
        _contract_enum(ToolConfirmationStatus, "tool_confirmation_request_status"),
        nullable=False,
    )
    graph_interrupt_ref: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    audit_log_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    process_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunControlRecordModel(RuntimeBase):
    __tablename__ = "run_control_records"

    control_record_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    stage_run_id: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("stage_runs.stage_run_id"),
        nullable=True,
        index=True,
    )
    control_type: Mapped[RunControlRecordType] = mapped_column(
        _contract_enum(RunControlRecordType, "run_control_record_type"),
        nullable=False,
    )
    source_stage_type: Mapped[StageType] = mapped_column(
        _contract_enum(StageType, "run_control_source_stage_type"),
        nullable=False,
    )
    target_stage_type: Mapped[StageType | None] = mapped_column(
        _contract_enum(StageType, "run_control_target_stage_type"),
        nullable=True,
    )
    payload_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    graph_interrupt_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DeliveryChannelSnapshotModel(RuntimeBase):
    __tablename__ = "delivery_channel_snapshots"

    delivery_channel_snapshot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        index=True,
    )
    source_delivery_channel_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
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
    )
    readiness_status: Mapped[DeliveryReadinessStatus] = mapped_column(
        _contract_enum(DeliveryReadinessStatus, "delivery_readiness_status"),
        nullable=False,
    )
    readiness_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DeliveryRecordModel(RuntimeBase):
    __tablename__ = "delivery_records"

    delivery_record_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("pipeline_runs.run_id"),
        nullable=False,
        index=True,
    )
    stage_run_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("stage_runs.stage_run_id"),
        nullable=False,
        index=True,
    )
    delivery_channel_snapshot_ref: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("delivery_channel_snapshots.delivery_channel_snapshot_id"),
        nullable=False,
        index=True,
    )
    delivery_mode: Mapped[DeliveryMode] = mapped_column(
        _contract_enum(DeliveryMode, "delivery_mode"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    branch_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(120), nullable=True)
    code_review_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    process_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "ApprovalDecisionModel",
    "ApprovalRequestModel",
    "ClarificationRecordModel",
    "DeliveryChannelSnapshotModel",
    "DeliveryRecordModel",
    "ModelBindingSnapshotModel",
    "PipelineRunModel",
    "ProviderCallPolicySnapshotModel",
    "ProviderSnapshotModel",
    "RunControlRecordModel",
    "RuntimeBase",
    "RuntimeLimitSnapshotModel",
    "StageArtifactModel",
    "StageRunModel",
    "ToolConfirmationRequestModel",
]
