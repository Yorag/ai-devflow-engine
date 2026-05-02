from datetime import UTC, datetime

import pytest

from backend.app.schemas import common
from backend.app.schemas.runtime_settings import (
    ModelBindingSnapshotRead,
    ProviderSnapshotRead,
    SnapshotModelRuntimeCapabilities,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def capabilities(
    model_id: str = "deepseek-chat",
    *,
    context_window_tokens: int = 128000,
    max_output_tokens: int = 8192,
    supports_tool_calling: bool = True,
    supports_structured_output: bool = True,
    supports_native_reasoning: bool = False,
) -> SnapshotModelRuntimeCapabilities:
    return SnapshotModelRuntimeCapabilities(
        model_id=model_id,
        context_window_tokens=context_window_tokens,
        max_output_tokens=max_output_tokens,
        supports_tool_calling=supports_tool_calling,
        supports_structured_output=supports_structured_output,
        supports_native_reasoning=supports_native_reasoning,
    )


def provider_snapshot(
    *,
    snapshot_id: str = "provider-snapshot-1",
    run_id: str = "run-1",
    provider_id: str = "provider-deepseek",
    display_name: str = "DeepSeek",
    provider_source: common.ProviderSource = common.ProviderSource.BUILTIN,
    protocol_type: common.ProviderProtocolType = (
        common.ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
    ),
    base_url: str = "https://api.deepseek.com",
    api_key_ref: str | None = "env:DEEPSEEK_API_KEY",
    model_id: str = "deepseek-chat",
    capability_set: SnapshotModelRuntimeCapabilities | None = None,
) -> ProviderSnapshotRead:
    return ProviderSnapshotRead(
        snapshot_id=snapshot_id,
        run_id=run_id,
        provider_id=provider_id,
        display_name=display_name,
        provider_source=provider_source,
        protocol_type=protocol_type,
        base_url=base_url,
        api_key_ref=api_key_ref,
        model_id=model_id,
        capabilities=capability_set or capabilities(model_id=model_id),
        source_config_version="provider-config-v1",
        schema_version="provider-snapshot-v1",
        created_at=NOW,
    )


def model_binding_snapshot(
    *,
    snapshot_id: str = "model-binding-snapshot-1",
    run_id: str = "run-1",
    binding_id: str = "binding-requirement-analysis",
    binding_type: str = "agent_role",
    stage_type: common.StageType | None = common.StageType.REQUIREMENT_ANALYSIS,
    role_id: str | None = "role-requirement-analyst",
    provider_snapshot_id: str = "provider-snapshot-1",
    provider_id: str = "provider-deepseek",
    model_id: str = "deepseek-chat",
    capability_set: SnapshotModelRuntimeCapabilities | None = None,
) -> ModelBindingSnapshotRead:
    return ModelBindingSnapshotRead(
        snapshot_id=snapshot_id,
        run_id=run_id,
        binding_id=binding_id,
        binding_type=binding_type,
        stage_type=stage_type,
        role_id=role_id,
        provider_snapshot_id=provider_snapshot_id,
        provider_id=provider_id,
        model_id=model_id,
        capabilities=capability_set or capabilities(model_id=model_id),
        model_parameters={"temperature": 0.2},
        source_config_version="template-binding-v1",
        schema_version="model-binding-snapshot-v1",
        created_at=NOW,
    )


def test_resolve_uses_frozen_model_binding_capabilities_for_builtin_provider() -> None:
    from backend.app.providers.provider_registry import ProviderRegistry

    binding_capabilities = capabilities(
        context_window_tokens=64000,
        max_output_tokens=4096,
        supports_tool_calling=True,
        supports_structured_output=False,
        supports_native_reasoning=True,
    )
    registry = ProviderRegistry(
        provider_snapshots=[provider_snapshot()],
        model_binding_snapshots=[
            model_binding_snapshot(capability_set=binding_capabilities)
        ],
    )

    config = registry.resolve("model-binding-snapshot-1", requires_tool_calling=True)

    assert config.provider_snapshot_id == "provider-snapshot-1"
    assert config.model_binding_snapshot_id == "model-binding-snapshot-1"
    assert config.provider_id == "provider-deepseek"
    assert config.provider_source is common.ProviderSource.BUILTIN
    assert config.protocol_type is common.ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
    assert config.model_id == "deepseek-chat"
    assert config.context_window_tokens == 64000
    assert config.max_output_tokens == 4096
    assert config.supports_tool_calling is True
    assert config.supports_structured_output is False
    assert config.supports_native_reasoning is True
    assert config.model_parameters == {"temperature": 0.2}


def test_custom_provider_uses_same_resolution_path() -> None:
    from backend.app.providers.provider_registry import ProviderRegistry

    custom_provider = provider_snapshot(
        provider_id="provider-custom",
        display_name="Team Gateway",
        provider_source=common.ProviderSource.CUSTOM,
        base_url="https://gateway.example/v1",
        api_key_ref="env:TEAM_GATEWAY_KEY",
    )
    custom_binding = model_binding_snapshot(provider_id="provider-custom")

    config = ProviderRegistry(
        provider_snapshots=[custom_provider],
        model_binding_snapshots=[custom_binding],
    ).resolve_from_model_binding_snapshot(custom_binding)

    assert config.provider_source is common.ProviderSource.CUSTOM
    assert config.display_name == "Team Gateway"
    assert config.base_url == "https://gateway.example/v1"


def test_registry_does_not_read_latest_provider_configuration() -> None:
    from backend.app.providers.provider_registry import ProviderRegistry

    frozen_provider = provider_snapshot(base_url="https://frozen.example/v1")
    frozen_binding = model_binding_snapshot(
        capability_set=capabilities(context_window_tokens=32000)
    )
    latest_provider_config = {
        "base_url": "https://latest.example/v1",
        "context_window_tokens": 999999,
    }

    config = ProviderRegistry(
        provider_snapshots=[frozen_provider],
        model_binding_snapshots=[frozen_binding],
    ).resolve("model-binding-snapshot-1")

    assert latest_provider_config["base_url"] != config.base_url
    assert latest_provider_config["context_window_tokens"] != config.context_window_tokens
    assert config.base_url == "https://frozen.example/v1"
    assert config.context_window_tokens == 32000


def test_requires_tool_calling_rejects_incompatible_snapshot() -> None:
    from backend.app.providers.provider_registry import (
        ProviderCapabilityError,
        ProviderRegistry,
    )

    registry = ProviderRegistry(
        provider_snapshots=[provider_snapshot()],
        model_binding_snapshots=[
            model_binding_snapshot(
                capability_set=capabilities(supports_tool_calling=False)
            )
        ],
    )

    with pytest.raises(ProviderCapabilityError) as error:
        registry.resolve("model-binding-snapshot-1", requires_tool_calling=True)

    assert error.value.error_code == "provider_capability_unsupported"
    assert "supports_tool_calling" in str(error.value)


def test_missing_provider_snapshot_raises_structured_error() -> None:
    from backend.app.providers.provider_registry import (
        ProviderRegistry,
        ProviderSnapshotNotFoundError,
    )

    registry = ProviderRegistry(
        provider_snapshots=[],
        model_binding_snapshots=[model_binding_snapshot()],
    )

    with pytest.raises(ProviderSnapshotNotFoundError) as error:
        registry.resolve("model-binding-snapshot-1")

    assert error.value.error_code == "provider_snapshot_not_found"
    assert error.value.provider_snapshot_id == "provider-snapshot-1"


def test_resolution_events_are_sanitized_and_include_credential_unavailable() -> None:
    from backend.app.providers.provider_registry import ProviderRegistry

    events = []
    registry = ProviderRegistry(
        provider_snapshots=[provider_snapshot(api_key_ref=None)],
        model_binding_snapshots=[model_binding_snapshot()],
        event_recorder=events.append,
    )

    config = registry.resolve("model-binding-snapshot-1")

    assert config.api_key_ref is None
    assert [event.event_type for event in events] == [
        "provider_credential_unavailable",
        "provider_resolution_succeeded",
    ]
    for event in events:
        dumped = event.to_record()
        assert "DEEPSEEK_API_KEY" not in str(dumped)
        assert "api_key" not in dumped
        assert dumped["provider_snapshot_id"] == "provider-snapshot-1"


def test_resolve_from_template_snapshot_selects_agent_role_binding() -> None:
    from backend.app.providers.provider_registry import ProviderRegistry

    class FrozenRunSnapshot:
        provider_snapshots = [provider_snapshot()]
        model_binding_snapshots = [model_binding_snapshot()]

    config = ProviderRegistry.resolve_from_template_snapshot(
        FrozenRunSnapshot(),
        stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        role_id="role-requirement-analyst",
    )

    assert config.binding_id == "binding-requirement-analysis"
    assert config.stage_type is common.StageType.REQUIREMENT_ANALYSIS
    assert config.role_id == "role-requirement-analyst"
