from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas import common


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_platform_runtime_settings_groups_versions_and_forbidden_prompt_boundary() -> None:
    from backend.app.schemas.runtime_settings import (
        AgentRuntimeLimits,
        ContextLimits,
        LogPolicy,
        PlatformHardLimits,
        PlatformRuntimeSettingsRead,
        PlatformRuntimeSettingsUpdate,
        PlatformRuntimeSettingsVersion,
        ProviderCallPolicy,
    )

    settings = PlatformRuntimeSettingsRead(
        settings_id="platform-runtime-settings",
        version=PlatformRuntimeSettingsVersion(
            config_version="runtime-settings-v1",
            schema_version="runtime-settings-schema-v1",
            hard_limits_version="platform-hard-limits-v1",
            updated_at=NOW,
        ),
        agent_limits=AgentRuntimeLimits(),
        provider_call_policy=ProviderCallPolicy(),
        context_limits=ContextLimits(),
        log_policy=LogPolicy(),
        hard_limits=PlatformHardLimits(),
    )

    dumped = settings.model_dump(mode="json")
    assert dumped["agent_limits"] == {
        "max_react_iterations_per_stage": 30,
        "max_tool_calls_per_stage": 80,
        "max_file_edit_count": 20,
        "max_patch_attempts_per_file": 3,
        "max_structured_output_repair_attempts": 3,
        "max_auto_regression_retries": 2,
        "max_clarification_rounds": 5,
        "max_no_progress_iterations": 5,
    }
    assert dumped["provider_call_policy"] == {
        "request_timeout_seconds": 60,
        "network_error_max_retries": 3,
        "rate_limit_max_retries": 3,
        "backoff_base_seconds": 1.0,
        "backoff_max_seconds": 30.0,
        "circuit_breaker_failure_threshold": 5,
        "circuit_breaker_recovery_seconds": 60,
    }
    assert dumped["context_limits"]["compression_threshold_ratio"] == 0.8
    assert dumped["log_policy"]["log_query_default_limit"] == 100
    assert dumped["log_policy"]["log_query_max_limit"] == 500
    assert dumped["hard_limits"]["agent_limits"]["max_react_iterations_per_stage"] == 50
    assert "compression_prompt" not in PlatformRuntimeSettingsRead.model_fields
    assert "compression_prompt" not in PlatformRuntimeSettingsUpdate.model_fields

    update = PlatformRuntimeSettingsUpdate(
        expected_config_version="runtime-settings-v1",
        agent_limits=AgentRuntimeLimits(max_tool_calls_per_stage=70),
        context_limits=ContextLimits(compression_threshold_ratio=0.75),
    )
    assert update.expected_config_version == "runtime-settings-v1"
    assert update.agent_limits is not None
    assert update.context_limits is not None

    with pytest.raises(ValidationError):
        ContextLimits(compression_threshold_ratio=1.0)

    with pytest.raises(ValidationError):
        ContextLimits(compression_threshold_ratio=0)

    with pytest.raises(ValidationError):
        PlatformRuntimeSettingsUpdate(
            expected_config_version="runtime-settings-v1",
            compression_prompt="Summarize context.",
        )

    with pytest.raises(ValidationError):
        LogPolicy(log_query_default_limit=600, log_query_max_limit=500)

    with pytest.raises(ValidationError):
        ProviderCallPolicy(backoff_base_seconds=10, backoff_max_seconds=5)


def test_runtime_settings_error_codes_reuse_unified_error_dictionary() -> None:
    from backend.app.api.error_codes import ErrorCode, RuntimeSettingsErrorCode

    assert {code.value for code in RuntimeSettingsErrorCode} == {
        "config_invalid_value",
        "config_hard_limit_exceeded",
        "config_version_conflict",
        "config_storage_unavailable",
        "config_snapshot_unavailable",
    }
    assert {ErrorCode(code.value) for code in RuntimeSettingsErrorCode} == {
        ErrorCode.CONFIG_INVALID_VALUE,
        ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED,
        ErrorCode.CONFIG_VERSION_CONFLICT,
        ErrorCode.CONFIG_STORAGE_UNAVAILABLE,
        ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
    }


def test_runtime_limit_and_provider_call_policy_snapshots_freeze_effective_values() -> None:
    from backend.app.schemas.runtime_settings import (
        AgentRuntimeLimits,
        ContextLimits,
        ProviderCallPolicy,
        ProviderCallPolicySnapshotRead,
        RuntimeLimitSnapshotRead,
    )

    runtime_snapshot = RuntimeLimitSnapshotRead(
        snapshot_id="runtime-limit-snapshot-1",
        run_id="run-1",
        agent_limits=AgentRuntimeLimits(max_auto_regression_retries=1),
        context_limits=ContextLimits(compression_threshold_ratio=0.75),
        source_config_version="runtime-settings-v1",
        hard_limits_version="platform-hard-limits-v1",
        schema_version="runtime-limit-snapshot-v1",
        created_at=NOW,
    )
    provider_policy_snapshot = ProviderCallPolicySnapshotRead(
        snapshot_id="provider-call-policy-snapshot-1",
        run_id="run-1",
        provider_call_policy=ProviderCallPolicy(
            request_timeout_seconds=45,
            network_error_max_retries=2,
        ),
        source_config_version="runtime-settings-v1",
        schema_version="provider-call-policy-snapshot-v1",
        created_at=NOW,
    )

    runtime_dump = runtime_snapshot.model_dump(mode="json")
    policy_dump = provider_policy_snapshot.model_dump(mode="json")
    assert runtime_dump["agent_limits"]["max_auto_regression_retries"] == 1
    assert runtime_dump["context_limits"]["compression_threshold_ratio"] == 0.75
    assert runtime_dump["source_config_version"] == "runtime-settings-v1"
    assert policy_dump["provider_call_policy"]["request_timeout_seconds"] == 45
    assert policy_dump["provider_call_policy"]["network_error_max_retries"] == 2
    assert "compression_prompt" not in runtime_dump
    assert "compression_prompt" not in policy_dump

    with pytest.raises(ValidationError):
        RuntimeLimitSnapshotRead(
            **runtime_snapshot.model_dump(mode="python"),
            compression_prompt="Summarize context.",
        )


def test_provider_and_model_binding_snapshots_keep_credentials_as_refs_and_capabilities_by_model() -> None:
    from backend.app.schemas.runtime_settings import (
        ModelBindingSnapshotRead,
        ProviderSnapshotRead,
        SnapshotModelRuntimeCapabilities,
    )

    capabilities = SnapshotModelRuntimeCapabilities(
        model_id="deepseek-chat",
        context_window_tokens=128000,
        max_output_tokens=8192,
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_native_reasoning=False,
    )
    provider_snapshot = ProviderSnapshotRead(
        snapshot_id="provider-snapshot-1",
        run_id="run-1",
        provider_id="provider-deepseek",
        display_name="DeepSeek",
        provider_source=common.ProviderSource.BUILTIN,
        protocol_type=common.ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url="https://api.deepseek.com",
        api_key_ref="env:DEEPSEEK_API_KEY",
        model_id="deepseek-chat",
        capabilities=capabilities,
        source_config_version="provider-config-v1",
        schema_version="provider-snapshot-v1",
        created_at=NOW,
    )
    model_binding = ModelBindingSnapshotRead(
        snapshot_id="model-binding-snapshot-1",
        run_id="run-1",
        binding_id="binding-requirement-analysis",
        binding_type="agent_role",
        stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        role_id="role-requirement-analyst",
        provider_snapshot_id=provider_snapshot.snapshot_id,
        provider_id=provider_snapshot.provider_id,
        model_id="deepseek-chat",
        capabilities=capabilities,
        model_parameters={"temperature": 0.2, "max_output_tokens": 4096},
        source_config_version="template-binding-v1",
        schema_version="model-binding-snapshot-v1",
        created_at=NOW,
    )

    provider_dump = provider_snapshot.model_dump(mode="json")
    binding_dump = model_binding.model_dump(mode="json")
    assert provider_dump["capabilities"] == {
        "model_id": "deepseek-chat",
        "context_window_tokens": 128000,
        "max_output_tokens": 8192,
        "supports_tool_calling": True,
        "supports_structured_output": True,
        "supports_native_reasoning": False,
    }
    assert binding_dump["binding_type"] == "agent_role"
    assert binding_dump["stage_type"] == "requirement_analysis"
    assert binding_dump["capabilities"]["supports_tool_calling"] is True
    assert "api_key" not in provider_dump
    assert "secret" not in provider_dump
    assert "credential_value" not in provider_dump
    assert "compression_prompt" not in provider_dump
    assert "compression_prompt" not in binding_dump

    with pytest.raises(ValidationError):
        ProviderSnapshotRead(
            **provider_snapshot.model_dump(mode="python"),
            api_key="plain-secret",
        )

    with pytest.raises(ValidationError):
        ModelBindingSnapshotRead(
            **model_binding.model_dump(mode="python"),
            compression_prompt="Summarize context.",
        )


def test_run_configuration_snapshot_groups_run_start_contracts() -> None:
    from backend.app.schemas.run import RunConfigurationSnapshotRead
    from backend.app.schemas.runtime_settings import (
        AgentRuntimeLimits,
        ContextLimits,
        ModelBindingSnapshotRead,
        ProviderCallPolicy,
        ProviderCallPolicySnapshotRead,
        ProviderSnapshotRead,
        RuntimeLimitSnapshotRead,
        SnapshotModelRuntimeCapabilities,
    )

    capabilities = SnapshotModelRuntimeCapabilities(
        model_id="deepseek-chat",
        max_output_tokens=8192,
        supports_tool_calling=True,
    )
    runtime_snapshot = RuntimeLimitSnapshotRead(
        snapshot_id="runtime-limit-snapshot-1",
        run_id="run-1",
        agent_limits=AgentRuntimeLimits(),
        context_limits=ContextLimits(),
        source_config_version="runtime-settings-v1",
        hard_limits_version="platform-hard-limits-v1",
        schema_version="runtime-limit-snapshot-v1",
        created_at=NOW,
    )
    policy_snapshot = ProviderCallPolicySnapshotRead(
        snapshot_id="provider-call-policy-snapshot-1",
        run_id="run-1",
        provider_call_policy=ProviderCallPolicy(),
        source_config_version="runtime-settings-v1",
        schema_version="provider-call-policy-snapshot-v1",
        created_at=NOW,
    )
    provider_snapshot = ProviderSnapshotRead(
        snapshot_id="provider-snapshot-1",
        run_id="run-1",
        provider_id="provider-deepseek",
        display_name="DeepSeek",
        provider_source=common.ProviderSource.BUILTIN,
        protocol_type=common.ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url="https://api.deepseek.com",
        api_key_ref="env:DEEPSEEK_API_KEY",
        model_id="deepseek-chat",
        capabilities=capabilities,
        source_config_version="provider-config-v1",
        schema_version="provider-snapshot-v1",
        created_at=NOW,
    )
    model_binding = ModelBindingSnapshotRead(
        snapshot_id="model-binding-snapshot-1",
        run_id="run-1",
        binding_id="binding-requirement-analysis",
        binding_type="agent_role",
        stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        role_id="role-requirement-analyst",
        provider_snapshot_id="provider-snapshot-1",
        provider_id="provider-deepseek",
        model_id="deepseek-chat",
        capabilities=capabilities,
        model_parameters={},
        source_config_version="template-binding-v1",
        schema_version="model-binding-snapshot-v1",
        created_at=NOW,
    )

    run_snapshot = RunConfigurationSnapshotRead(
        run_id="run-1",
        template_snapshot_ref="template-snapshot-1",
        graph_definition_ref="graph-definition-1",
        runtime_limit_snapshot=runtime_snapshot,
        provider_call_policy_snapshot=policy_snapshot,
        provider_snapshots=[provider_snapshot],
        model_binding_snapshots=[model_binding],
        created_at=NOW,
    )

    dumped = run_snapshot.model_dump(mode="json")
    assert dumped["runtime_limit_snapshot"]["snapshot_id"] == "runtime-limit-snapshot-1"
    assert dumped["provider_call_policy_snapshot"]["snapshot_id"] == (
        "provider-call-policy-snapshot-1"
    )
    assert dumped["provider_snapshots"][0]["provider_id"] == "provider-deepseek"
    assert dumped["model_binding_snapshots"][0]["binding_type"] == "agent_role"
    assert "compression_prompt" not in dumped

    with pytest.raises(ValidationError):
        RunConfigurationSnapshotRead(
            **run_snapshot.model_dump(mode="python"),
            compression_prompt="Summarize context.",
        )
