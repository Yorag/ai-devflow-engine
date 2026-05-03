from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt
from pydantic import model_validator

from backend.app.schemas import common


JsonObject = dict[str, object]


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentRuntimeLimits(_StrictBaseModel):
    max_react_iterations_per_stage: PositiveInt = 30
    max_tool_calls_per_stage: PositiveInt = 80
    max_file_edit_count: PositiveInt = 20
    max_patch_attempts_per_file: PositiveInt = 3
    max_structured_output_repair_attempts: PositiveInt = 3
    max_auto_regression_retries: int = Field(default=2, ge=0)
    max_clarification_rounds: PositiveInt = 5
    max_no_progress_iterations: PositiveInt = 5


class ProviderCallPolicy(_StrictBaseModel):
    request_timeout_seconds: PositiveInt = 60
    network_error_max_retries: int = Field(default=3, ge=0)
    rate_limit_max_retries: int = Field(default=3, ge=0)
    backoff_base_seconds: PositiveFloat = 1.0
    backoff_max_seconds: PositiveFloat = 30.0
    circuit_breaker_failure_threshold: PositiveInt = 5
    circuit_breaker_recovery_seconds: PositiveInt = 60

    @model_validator(mode="after")
    def validate_backoff_window(self) -> "ProviderCallPolicy":
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise ValueError(
                "backoff_max_seconds must be greater than or equal to "
                "backoff_base_seconds"
            )
        return self


class ContextLimits(_StrictBaseModel):
    tool_output_preview_chars: PositiveInt = 4000
    bash_stdout_preview_chars: PositiveInt = 8000
    bash_stderr_preview_chars: PositiveInt = 8000
    grep_max_results: PositiveInt = 100
    file_read_max_chars: PositiveInt = 50000
    model_output_log_preview_chars: PositiveInt = 8000
    model_output_process_preview_chars: PositiveInt = 12000
    compression_threshold_ratio: float = Field(default=0.8, gt=0, lt=1)


class LogPolicy(_StrictBaseModel):
    run_log_retention_days: PositiveInt = 30
    audit_log_retention_days: PositiveInt = 180
    log_rotation_max_bytes: PositiveInt = 10 * 1024 * 1024
    log_query_default_limit: PositiveInt = 100
    log_query_max_limit: PositiveInt = 500

    @model_validator(mode="after")
    def validate_query_window(self) -> "LogPolicy":
        if self.log_query_default_limit > self.log_query_max_limit:
            raise ValueError(
                "log_query_default_limit must be less than or equal to "
                "log_query_max_limit"
            )
        return self


class AgentRuntimeHardLimits(_StrictBaseModel):
    max_react_iterations_per_stage: PositiveInt = 50
    max_tool_calls_per_stage: PositiveInt = 150
    max_file_edit_count: PositiveInt = 40
    max_patch_attempts_per_file: PositiveInt = 5
    max_structured_output_repair_attempts: PositiveInt = 5
    max_auto_regression_retries: PositiveInt = 3
    max_clarification_rounds: PositiveInt = 8
    max_no_progress_iterations: PositiveInt = 8


class ProviderCallPolicyHardLimits(_StrictBaseModel):
    request_timeout_seconds: PositiveInt = 300
    network_error_max_retries: PositiveInt = 10
    rate_limit_max_retries: PositiveInt = 10
    backoff_base_seconds: PositiveFloat = 10.0
    backoff_max_seconds: PositiveFloat = 120.0
    circuit_breaker_failure_threshold: PositiveInt = 20
    circuit_breaker_recovery_seconds: PositiveInt = 600


class ContextHardLimits(_StrictBaseModel):
    tool_output_preview_chars: PositiveInt = 20000
    bash_stdout_preview_chars: PositiveInt = 40000
    bash_stderr_preview_chars: PositiveInt = 40000
    grep_max_results: PositiveInt = 1000
    file_read_max_chars: PositiveInt = 500000
    model_output_log_preview_chars: PositiveInt = 40000
    model_output_process_preview_chars: PositiveInt = 60000


class LogPolicyHardLimits(_StrictBaseModel):
    run_log_retention_days: PositiveInt = 365
    audit_log_retention_days: PositiveInt = 2555
    log_rotation_max_bytes: PositiveInt = 100 * 1024 * 1024
    log_query_max_limit: PositiveInt = 5000


class PlatformHardLimits(_StrictBaseModel):
    hard_limits_version: str = Field(default="platform-hard-limits-v1", min_length=1)
    agent_limits: AgentRuntimeHardLimits = Field(default_factory=AgentRuntimeHardLimits)
    provider_call_policy: ProviderCallPolicyHardLimits = Field(
        default_factory=ProviderCallPolicyHardLimits
    )
    context_limits: ContextHardLimits = Field(default_factory=ContextHardLimits)
    log_policy: LogPolicyHardLimits = Field(default_factory=LogPolicyHardLimits)


class PlatformRuntimeSettingsVersion(_StrictBaseModel):
    config_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    hard_limits_version: str = Field(min_length=1)
    updated_at: datetime


class InternalModelBindingSelection(_StrictBaseModel):
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_parameters: JsonObject = Field(default_factory=dict)
    source_config_version: str = Field(min_length=1)


class InternalModelBindings(_StrictBaseModel):
    context_compression: InternalModelBindingSelection
    structured_output_repair: InternalModelBindingSelection
    validation_pass: InternalModelBindingSelection


class PlatformRuntimeSettingsRead(_StrictBaseModel):
    settings_id: str = Field(min_length=1)
    version: PlatformRuntimeSettingsVersion
    agent_limits: AgentRuntimeLimits
    provider_call_policy: ProviderCallPolicy
    internal_model_bindings: InternalModelBindings
    context_limits: ContextLimits
    log_policy: LogPolicy
    hard_limits: PlatformHardLimits


class PlatformRuntimeSettingsUpdate(_StrictBaseModel):
    expected_config_version: str = Field(min_length=1)
    agent_limits: AgentRuntimeLimits | None = None
    provider_call_policy: ProviderCallPolicy | None = None
    internal_model_bindings: InternalModelBindings | None = None
    context_limits: ContextLimits | None = None
    log_policy: LogPolicy | None = None


class RuntimeLimitSnapshotRead(_StrictBaseModel):
    snapshot_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    agent_limits: AgentRuntimeLimits
    context_limits: ContextLimits
    source_config_version: str = Field(min_length=1)
    hard_limits_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    created_at: datetime


class ProviderCallPolicySnapshotRead(_StrictBaseModel):
    snapshot_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    provider_call_policy: ProviderCallPolicy
    source_config_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    created_at: datetime


class SnapshotModelRuntimeCapabilities(_StrictBaseModel):
    model_id: str = Field(min_length=1)
    context_window_tokens: PositiveInt = 128000
    max_output_tokens: PositiveInt
    supports_tool_calling: bool = False
    supports_structured_output: bool = False
    supports_native_reasoning: bool = False


class ProviderSnapshotRead(_StrictBaseModel):
    snapshot_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider_source: common.ProviderSource
    protocol_type: common.ProviderProtocolType
    base_url: str = Field(min_length=1)
    api_key_ref: str | None = None
    model_id: str = Field(min_length=1)
    capabilities: SnapshotModelRuntimeCapabilities
    source_config_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    created_at: datetime


class ModelBindingSnapshotRead(_StrictBaseModel):
    snapshot_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    binding_type: Literal[
        "agent_role",
        "context_compression",
        "structured_output_repair",
        "validation_pass",
    ]
    stage_type: common.StageType | None = None
    role_id: str | None = None
    provider_snapshot_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    capabilities: SnapshotModelRuntimeCapabilities
    model_parameters: JsonObject = Field(default_factory=dict)
    source_config_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    created_at: datetime


__all__ = [
    "AgentRuntimeHardLimits",
    "AgentRuntimeLimits",
    "ContextHardLimits",
    "ContextLimits",
    "InternalModelBindingSelection",
    "InternalModelBindings",
    "LogPolicy",
    "LogPolicyHardLimits",
    "ModelBindingSnapshotRead",
    "PlatformHardLimits",
    "PlatformRuntimeSettingsRead",
    "PlatformRuntimeSettingsUpdate",
    "PlatformRuntimeSettingsVersion",
    "ProviderCallPolicy",
    "ProviderCallPolicyHardLimits",
    "ProviderCallPolicySnapshotRead",
    "ProviderSnapshotRead",
    "RuntimeLimitSnapshotRead",
    "SnapshotModelRuntimeCapabilities",
]
