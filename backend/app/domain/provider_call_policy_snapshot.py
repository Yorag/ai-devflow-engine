from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from pydantic import field_validator

from backend.app.api.error_codes import ErrorCode
from backend.app.schemas.runtime_settings import (
    PlatformRuntimeSettingsRead,
    ProviderCallPolicy,
)


PROVIDER_CALL_POLICY_SNAPSHOT_SCHEMA_VERSION = "provider-call-policy-snapshot-v1"


class FrozenProviderCallPolicy(ProviderCallPolicy):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderCallPolicySnapshotBuilderError(ValueError):
    def __init__(self, error_code: ErrorCode, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class ProviderCallPolicySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: StrictStr = Field(min_length=1, max_length=80)
    run_id: StrictStr = Field(min_length=1)
    provider_call_policy: FrozenProviderCallPolicy
    source_config_version: StrictStr = Field(min_length=1)
    schema_version: Literal["provider-call-policy-snapshot-v1"] = (
        PROVIDER_CALL_POLICY_SNAPSHOT_SCHEMA_VERSION
    )
    created_at: datetime

    @field_validator("provider_call_policy", mode="before")
    @classmethod
    def _validate_provider_call_policy_input(cls, value: object) -> object:
        if isinstance(value, ProviderCallPolicy):
            return value.model_dump(mode="python")
        return value


class ProviderCallPolicySnapshotBuilder:
    @classmethod
    def build_for_run(
        cls,
        settings: object,
        *,
        run_id: str,
        created_at: datetime,
    ) -> ProviderCallPolicySnapshot:
        current = cls._settings_read(settings)
        try:
            return ProviderCallPolicySnapshot(
                snapshot_id=_snapshot_id("provider-call-policy-snapshot", run_id),
                run_id=run_id,
                provider_call_policy=current.provider_call_policy.model_dump(
                    mode="python"
                ),
                source_config_version=current.version.config_version,
                created_at=created_at,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProviderCallPolicySnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "ProviderCallPolicySnapshot configuration is invalid.",
            ) from exc

    @staticmethod
    def _settings_read(settings: object) -> PlatformRuntimeSettingsRead:
        if not isinstance(settings, PlatformRuntimeSettingsRead):
            raise ProviderCallPolicySnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Current PlatformRuntimeSettings are unavailable.",
            )
        ProviderCallPolicySnapshotBuilder._require_explicit_fields(
            settings.provider_call_policy,
            set(ProviderCallPolicy.model_fields),
            "provider_call_policy",
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
            raise ProviderCallPolicySnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Current PlatformRuntimeSettings are invalid: "
                f"{group_name} is missing persisted fields.",
            )


def _snapshot_id(prefix: str, run_id: str) -> str:
    candidate = f"{prefix}-{run_id}"
    if len(candidate) <= 80:
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


__all__ = [
    "FrozenProviderCallPolicy",
    "PROVIDER_CALL_POLICY_SNAPSHOT_SCHEMA_VERSION",
    "ProviderCallPolicySnapshot",
    "ProviderCallPolicySnapshotBuilder",
    "ProviderCallPolicySnapshotBuilderError",
]
