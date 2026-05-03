from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.core.config import EnvironmentSettings
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    LogPolicy,
    PlatformHardLimits,
    PlatformRuntimeSettingsRead,
    PlatformRuntimeSettingsVersion,
    ProviderCallPolicy,
)
from backend.tests.support.settings import override_environment_settings


FIXTURE_NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
_ALLOWED_SETTING_OVERRIDES = frozenset(
    {
        "credential_env_prefixes",
        "platform_runtime_root",
        "workspace_root",
    }
)


def settings_override_fixture(
    tmp_path: Path,
    **overrides: Any,
) -> EnvironmentSettings:
    unexpected = sorted(set(overrides) - _ALLOWED_SETTING_OVERRIDES)
    if unexpected:
        names = ", ".join(unexpected)
        raise ValueError(
            "settings_override_fixture only supports test-local overrides for "
            f"platform_runtime_root, workspace_root, and credential_env_prefixes; "
            f"got {names}."
        )

    values = {
        "platform_runtime_root": overrides.pop(
            "platform_runtime_root",
            tmp_path / ".runtime",
        ),
    }
    values.update(overrides)
    return override_environment_settings(**values)


def runtime_settings_snapshot_fixture(
    *,
    settings_id: str = "platform-runtime-settings",
    config_version: str = "platform-runtime-settings-config-v1",
    schema_version: str = "platform-runtime-settings-v1",
    hard_limits_version: str = "platform-hard-limits-v1",
    updated_at: datetime | None = None,
    agent_limits: AgentRuntimeLimits | None = None,
    provider_call_policy: ProviderCallPolicy | None = None,
    context_limits: ContextLimits | None = None,
    log_policy: LogPolicy | None = None,
    hard_limits: PlatformHardLimits | None = None,
) -> PlatformRuntimeSettingsRead:
    resolved_updated_at = updated_at or FIXTURE_NOW
    return PlatformRuntimeSettingsRead(
        settings_id=settings_id,
        version=PlatformRuntimeSettingsVersion(
            config_version=config_version,
            schema_version=schema_version,
            hard_limits_version=hard_limits_version,
            updated_at=resolved_updated_at,
        ),
        agent_limits=agent_limits or AgentRuntimeLimits(),
        provider_call_policy=provider_call_policy or ProviderCallPolicy(),
        context_limits=context_limits or ContextLimits(),
        log_policy=log_policy or LogPolicy(),
        hard_limits=hard_limits or PlatformHardLimits(),
    )
