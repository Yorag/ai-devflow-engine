from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from pydantic import field_validator

from backend.app.api.error_codes import ErrorCode
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    PlatformRuntimeSettingsRead,
)


RUNTIME_LIMIT_SNAPSHOT_SCHEMA_VERSION = "runtime-limit-snapshot-v1"


class FrozenAgentRuntimeLimits(AgentRuntimeLimits):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FrozenContextLimits(ContextLimits):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeLimitSnapshotBuilderError(ValueError):
    def __init__(self, error_code: ErrorCode, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class RuntimeLimitSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: StrictStr = Field(min_length=1, max_length=80)
    run_id: StrictStr = Field(min_length=1)
    agent_limits: FrozenAgentRuntimeLimits
    context_limits: FrozenContextLimits
    source_config_version: StrictStr = Field(min_length=1)
    hard_limits_version: StrictStr = Field(min_length=1)
    schema_version: Literal["runtime-limit-snapshot-v1"] = (
        RUNTIME_LIMIT_SNAPSHOT_SCHEMA_VERSION
    )
    created_at: datetime

    @field_validator("agent_limits", mode="before")
    @classmethod
    def _validate_agent_limits_input(cls, value: object) -> object:
        if isinstance(value, AgentRuntimeLimits):
            return value.model_dump(mode="python")
        return value

    @field_validator("context_limits", mode="before")
    @classmethod
    def _validate_context_limits_input(cls, value: object) -> object:
        if isinstance(value, ContextLimits):
            return value.model_dump(mode="python")
        return value


class RuntimeLimitSnapshotBuilder:
    @classmethod
    def build_for_run(
        cls,
        settings: object,
        *,
        template_snapshot: object,
        run_id: str,
        created_at: datetime,
    ) -> RuntimeLimitSnapshot:
        current = cls._settings_read(settings)
        if getattr(template_snapshot, "run_id", None) != run_id:
            raise RuntimeLimitSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Template snapshot run_id must match the PipelineRun run_id.",
            )

        template_retries = cls._template_auto_regression_retries(template_snapshot)
        platform_retries = current.agent_limits.max_auto_regression_retries
        hard_retries = current.hard_limits.agent_limits.max_auto_regression_retries
        if template_retries > platform_retries or template_retries > hard_retries:
            raise RuntimeLimitSnapshotBuilderError(
                ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED,
                "template max_auto_regression_retries exceeds the effective "
                "platform runtime limit.",
            )

        agent_limits = current.agent_limits.model_dump(mode="python")
        agent_limits["max_auto_regression_retries"] = template_retries
        try:
            return RuntimeLimitSnapshot(
                snapshot_id=_snapshot_id("runtime-limit-snapshot", run_id),
                run_id=run_id,
                agent_limits=agent_limits,
                context_limits=current.context_limits.model_dump(mode="python"),
                source_config_version=current.version.config_version,
                hard_limits_version=current.version.hard_limits_version,
                created_at=created_at,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise RuntimeLimitSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "RuntimeLimitSnapshot configuration is invalid.",
            ) from exc

    @staticmethod
    def _settings_read(settings: object) -> PlatformRuntimeSettingsRead:
        if not isinstance(settings, PlatformRuntimeSettingsRead):
            raise RuntimeLimitSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Current PlatformRuntimeSettings are unavailable.",
            )
        RuntimeLimitSnapshotBuilder._require_explicit_fields(
            settings.agent_limits,
            set(AgentRuntimeLimits.model_fields),
            "agent_limits",
        )
        RuntimeLimitSnapshotBuilder._require_explicit_fields(
            settings.context_limits,
            set(ContextLimits.model_fields),
            "context_limits",
        )
        return settings

    @staticmethod
    def _require_explicit_fields(
        model: object,
        required_fields: set[str],
        group_name: str,
    ) -> None:
        fields_set = getattr(model, "model_fields_set", set())
        missing = sorted(required_fields - fields_set)
        if missing:
            raise RuntimeLimitSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Current PlatformRuntimeSettings are invalid: "
                f"{group_name} is missing persisted fields.",
            )

    @staticmethod
    def _template_auto_regression_retries(template_snapshot: object) -> int:
        value = getattr(template_snapshot, "max_auto_regression_retries", None)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeLimitSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Template max_auto_regression_retries is unavailable.",
            )
        return value


def _snapshot_id(prefix: str, run_id: str) -> str:
    candidate = f"{prefix}-{run_id}"
    if len(candidate) <= 80:
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


__all__ = [
    "FrozenAgentRuntimeLimits",
    "FrozenContextLimits",
    "RUNTIME_LIMIT_SNAPSHOT_SCHEMA_VERSION",
    "RuntimeLimitSnapshot",
    "RuntimeLimitSnapshotBuilder",
    "RuntimeLimitSnapshotBuilderError",
]
