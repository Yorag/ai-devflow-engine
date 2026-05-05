from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.context.size_guard import ContextSizeGuard
from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DATABASE_FILE_NAMES, DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    DeliveryChannelModel,
    ProjectModel,
    ProviderModel,
)
from backend.app.db.models.runtime import (
    DeliveryChannelSnapshotModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    ApprovalType,
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    StageType,
    TemplateSource,
)
from backend.app.domain.provider_snapshot import (
    INTERNAL_MODEL_BINDING_TYPES,
    InternalModelBindingSelection,
    ModelBindingSnapshotBuilder,
    ProviderSnapshotBuilder,
)
from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshotBuilder
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import JsonlWriteResult
from backend.app.schemas.configuration_package import ConfigurationPackageExport
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    PlatformRuntimeSettingsRead,
    RuntimeLimitSnapshotRead,
)
from backend.app.services.delivery_channels import DeliveryChannelService
from backend.app.services.delivery_snapshots import DeliverySnapshotService


NOW = datetime(2026, 5, 5, 9, 0, tzinfo=UTC)
SNAPSHOT_AT = datetime(2026, 5, 5, 9, 5, tzinfo=UTC)
LATER = datetime(2026, 5, 5, 9, 10, tzinfo=UTC)
DEFAULT_PROJECT_ID = "project-default"
DEFAULT_DELIVERY_CHANNEL_ID = "delivery-default"
RAW_SECRET_VALUE = "raw-secret-value"
FIXED_STAGES = (
    StageType.REQUIREMENT_ANALYSIS,
    StageType.SOLUTION_DESIGN,
    StageType.CODE_GENERATION,
    StageType.TEST_GENERATION_EXECUTION,
    StageType.CODE_REVIEW,
    StageType.DELIVERY_INTEGRATION,
)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        return object()

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return object()


class RecordingLogWriter:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def write(self, record: Any) -> JsonlWriteResult:
        self.records.append(record)
        return JsonlWriteResult(
            log_id=record.log_id or "log-config-snapshot-regression",
            log_file_ref="logs/app.jsonl",
            line_offset=0,
            line_number=len(self.records),
            log_file_generation="app",
            created_at=record.created_at or NOW,
        )

    def write_run_log(self, record: Any) -> object:
        self.records.append(record)
        return object()


class ProviderConfigStub:
    def __init__(
        self,
        *,
        provider_id: str = "provider-alpha",
        display_name: str = "Alpha Provider",
        default_model_id: str = "alpha-chat",
        runtime_capabilities: list[dict[str, Any]] | None = None,
        updated_at: datetime = NOW,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.provider_source = ProviderSource.CUSTOM
        self.protocol_type = ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
        self.base_url = "https://alpha.example.test/v1"
        self.api_key_ref = "env:AI_DEVFLOW_CREDENTIAL_ALPHA"
        self.default_model_id = default_model_id
        self.supported_model_ids = [default_model_id]
        self.runtime_capabilities = runtime_capabilities or [
            model_capability(model_id=default_model_id)
        ]
        self.created_at = NOW
        self.updated_at = updated_at


def model_capability(
    *,
    model_id: str = "alpha-chat",
    context_window_tokens: int = 128000,
    max_output_tokens: int = 4096,
    supports_tool_calling: bool = True,
    supports_structured_output: bool = False,
    supports_native_reasoning: bool = True,
) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "context_window_tokens": context_window_tokens,
        "max_output_tokens": max_output_tokens,
        "supports_tool_calling": supports_tool_calling,
        "supports_structured_output": supports_structured_output,
        "supports_native_reasoning": supports_native_reasoning,
    }


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    return manager


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-config-snapshot-regression",
        trace_id="trace-config-snapshot-regression",
        correlation_id="correlation-config-snapshot-regression",
        span_id="span-config-snapshot-regression",
        created_at=NOW,
    )


def template_snapshot(
    *,
    run_id: str,
    provider_id: str = "provider-alpha",
    max_auto_regression_retries: int = 1,
) -> TemplateSnapshot:
    return TemplateSnapshot(
        snapshot_ref=f"template-snapshot-{run_id}",
        run_id=run_id,
        source_template_id="template-feature-one",
        source_template_name="Feature One",
        source_template=TemplateSource.SYSTEM_TEMPLATE,
        source_template_updated_at=NOW,
        fixed_stage_sequence=FIXED_STAGES,
        stage_role_bindings=tuple(
            StageRoleSnapshot(
                stage_type=stage_type,
                role_id=f"role-{stage_type.value}",
                system_prompt=f"# Prompt for {stage_type.value}",
                provider_id=provider_id,
            )
            for stage_type in FIXED_STAGES
        ),
        approval_checkpoints=(
            ApprovalType.SOLUTION_DESIGN_APPROVAL,
            ApprovalType.CODE_REVIEW_APPROVAL,
        ),
        auto_regression_enabled=True,
        max_auto_regression_retries=max_auto_regression_retries,
        created_at=NOW,
    )


def agent_limits(**overrides: Any) -> AgentRuntimeLimits:
    values = {
        "max_react_iterations_per_stage": 30,
        "max_tool_calls_per_stage": 80,
        "max_file_edit_count": 20,
        "max_patch_attempts_per_file": 3,
        "max_structured_output_repair_attempts": 3,
        "max_auto_regression_retries": 2,
        "max_clarification_rounds": 5,
        "max_no_progress_iterations": 5,
    }
    values.update(overrides)
    return AgentRuntimeLimits(**values)


def context_limits(**overrides: Any) -> ContextLimits:
    values = {
        "tool_output_preview_chars": 4000,
        "bash_stdout_preview_chars": 8000,
        "bash_stderr_preview_chars": 8000,
        "grep_max_results": 100,
        "file_read_max_chars": 50000,
        "model_output_log_preview_chars": 8000,
        "model_output_process_preview_chars": 12000,
        "compression_threshold_ratio": 0.8,
    }
    values.update(overrides)
    return ContextLimits(**values)


def runtime_settings(**overrides: Any) -> PlatformRuntimeSettingsRead:
    from backend.tests.fixtures import runtime_settings_snapshot_fixture

    values = {
        "agent_limits": agent_limits(),
        "context_limits": context_limits(),
        "updated_at": NOW,
    }
    values.update(overrides)
    return runtime_settings_snapshot_fixture(**values)


def internal_model_bindings(
    *,
    provider_id: str = "provider-alpha",
    model_id: str = "alpha-chat",
) -> tuple[InternalModelBindingSelection, ...]:
    return tuple(
        InternalModelBindingSelection(
            binding_type=binding_type,
            provider_id=provider_id,
            model_id=model_id,
            model_parameters={"temperature": 0.0},
        )
        for binding_type in INTERNAL_MODEL_BINDING_TYPES
    )


def seed_project_with_delivery_channel(session: Any) -> None:
    project = ProjectModel(
        project_id=DEFAULT_PROJECT_ID,
        name="AI DevFlow Engine",
        root_path="C:/repo/ai-devflow-engine",
        default_delivery_channel_id=DEFAULT_DELIVERY_CHANNEL_ID,
        is_default=True,
        is_visible=True,
        visibility_removed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    channel = DeliveryChannelModel(
        delivery_channel_id=DEFAULT_DELIVERY_CHANNEL_ID,
        project_id=DEFAULT_PROJECT_ID,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier="owner/repo",
        default_branch="main",
        code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
        credential_ref=RAW_SECRET_VALUE,
        credential_status=CredentialStatus.UNBOUND,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        readiness_message="DeliveryChannel readiness has not been validated.",
        last_validated_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(project)
    session.flush()
    session.add(channel)
    session.commit()


def seed_runtime_run_for_delivery_snapshot(
    manager: DatabaseManager,
    *,
    run_id: str,
) -> None:
    runtime_limit_snapshot_ref = f"runtime-limits-{run_id}"
    provider_policy_snapshot_ref = f"provider-policy-{run_id}"
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RuntimeLimitSnapshotModel(
                snapshot_id=runtime_limit_snapshot_ref,
                run_id=run_id,
                agent_limits={},
                context_limits={},
                source_config_version="test",
                hard_limits_version="test",
                schema_version="runtime-limit-snapshot-v1",
                created_at=NOW,
            )
        )
        session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id=provider_policy_snapshot_ref,
                run_id=run_id,
                provider_call_policy={},
                source_config_version="test",
                schema_version="provider-call-policy-snapshot-v1",
                created_at=NOW,
            )
        )
        session.commit()
        session.add(
            PipelineRunModel(
                run_id=run_id,
                session_id="session-delivery-freeze",
                project_id=DEFAULT_PROJECT_ID,
                attempt_index=1,
                status=RunStatus.WAITING_APPROVAL,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-delivery-freeze",
                graph_definition_ref="graph-definition-delivery-freeze",
                graph_thread_ref="thread-delivery-freeze",
                workspace_ref="workspace-delivery-freeze",
                runtime_limit_snapshot_ref=runtime_limit_snapshot_ref,
                provider_call_policy_snapshot_ref=provider_policy_snapshot_ref,
                delivery_channel_snapshot_ref=None,
                current_stage_run_id="stage-run-code-review",
                trace_id="trace-config-snapshot-regression",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def export_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "export_id": "config-export-regression",
        "exported_at": NOW,
        "package_schema_version": "function-one-config-v1",
        "scope": {"scope_type": "project", "project_id": DEFAULT_PROJECT_ID},
        "providers": [],
        "delivery_channels": [],
        "pipeline_templates": [],
    }
    payload.update(overrides)
    return payload


def provider_package_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "provider_id": "provider-custom",
        "display_name": "Custom Provider",
        "provider_source": "custom",
        "protocol_type": "openai_completions_compatible",
        "base_url": "https://provider.example.test/v1",
        "api_key_ref": "env:AI_DEVFLOW_CREDENTIAL_CUSTOM",
        "default_model_id": "custom-chat",
        "supported_model_ids": ["custom-chat"],
        "runtime_capabilities": [model_capability(model_id="custom-chat")],
    }
    payload.update(overrides)
    return payload


def delivery_channel_package_payload(**overrides: Any) -> dict[str, Any]:
    payload = {"delivery_mode": "demo_delivery"}
    payload.update(overrides)
    return payload


def pipeline_template_package_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "template_id": "template-user-regression",
        "name": "User regression template",
        "template_source": "user_template",
        "stage_role_bindings": [
            {
                "stage_type": "requirement_analysis",
                "role_id": "role-requirement-analysis",
                "system_prompt": "# User editable stage prompt",
                "provider_id": "provider-custom",
            }
        ],
        "auto_regression_enabled": True,
        "max_auto_regression_retries": 1,
    }
    payload.update(overrides)
    return payload


def test_environment_settings_and_database_paths_remain_startup_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    env_database_root = tmp_path / "env-databases"
    for role in DatabaseRole:
        monkeypatch.setenv(
            f"AI_DEVFLOW_{role.value.upper()}_DATABASE_URL",
            f"sqlite:///{(env_database_root / f'{role.value}.db').as_posix()}",
        )
        monkeypatch.setenv(
            f"AI_DEVFLOW_{role.value.upper()}_DATABASE_PATH",
            str(env_database_root / f"{role.value}.db"),
        )

    forbidden_fields = {
        "provider_id",
        "display_name",
        "provider_base_url",
        "provider_model_id",
        "provider_source",
        "protocol_type",
        "base_url",
        "api_key_ref",
        "default_model_id",
        "supported_model_ids",
        "runtime_capabilities",
        "model_id",
        "context_window_tokens",
        "max_output_tokens",
        "supports_tool_calling",
        "supports_structured_output",
        "supports_native_reasoning",
        "delivery_channel_id",
        "delivery_mode",
        "scm_provider_type",
        "repository_identifier",
        "target_branch",
        "default_branch",
        "code_review_request_type",
        "credential_ref",
        "credential_status",
        "readiness_status",
        "readiness_message",
        "last_validated_at",
        "max_react_iterations_per_stage",
        "max_tool_calls_per_stage",
        "max_file_edit_count",
        "max_patch_attempts_per_file",
        "max_structured_output_repair_attempts",
        "max_auto_regression_retries",
        "max_clarification_rounds",
        "max_no_progress_iterations",
        "request_timeout_seconds",
        "network_error_max_retries",
        "rate_limit_max_retries",
        "backoff_base_seconds",
        "backoff_max_seconds",
        "circuit_breaker_failure_threshold",
        "circuit_breaker_recovery_seconds",
        "run_log_retention_days",
        "audit_log_retention_days",
        "log_rotation_max_bytes",
        "log_query_default_limit",
        "log_query_max_limit",
        "compression_threshold_ratio",
        "prompt_asset_root",
        "prompt_id",
        "prompt_version",
        "system_prompt",
        "runtime_instructions",
        "structured_output_repair_prompt",
        "compression_prompt",
        "deterministic_test_runtime",
        "control_database_url",
        "runtime_database_url",
        "graph_database_url",
        "event_database_url",
        "log_database_url",
        "control_database_path",
        "runtime_database_path",
        "graph_database_path",
        "event_database_path",
        "log_database_path",
    }

    assert forbidden_fields.isdisjoint(EnvironmentSettings.model_fields)

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=runtime_root)
    )

    expected_paths = {
        role: (runtime_root / file_name).resolve(strict=False)
        for role, file_name in DATABASE_FILE_NAMES.items()
    }
    assert set(expected_paths) == set(DatabaseRole)
    assert len(expected_paths) == 5
    assert manager.database_paths() == expected_paths
    assert all(env_database_root not in path.parents for path in expected_paths.values())
    for role, expected_path in expected_paths.items():
        assert manager.database_url(role) == f"sqlite:///{expected_path.as_posix()}"


def test_runtime_settings_and_provider_updates_do_not_mutate_started_run_snapshots(
    tmp_path: Path,
) -> None:
    del tmp_path
    settings = runtime_settings(
        context_limits=context_limits(compression_threshold_ratio=0.8)
    )
    runtime_snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
        settings,
        template_snapshot=template_snapshot(run_id="run-freeze"),
        run_id="run-freeze",
        created_at=SNAPSHOT_AT,
    )

    settings.context_limits.compression_threshold_ratio = 0.6

    assert runtime_snapshot.context_limits.compression_threshold_ratio == 0.8

    provider = ProviderConfigStub(
        runtime_capabilities=[
            model_capability(
                context_window_tokens=128000,
                max_output_tokens=4096,
                supports_tool_calling=True,
                supports_structured_output=False,
                supports_native_reasoning=True,
            )
        ]
    )
    provider_snapshots = ProviderSnapshotBuilder.build_for_run(
        [provider],
        run_id="run-freeze",
        required_provider_ids=("provider-alpha",),
        created_at=SNAPSHOT_AT,
        credential_env_prefixes=("AI_DEVFLOW_CREDENTIAL_",),
    )
    model_binding_snapshots = ModelBindingSnapshotBuilder.build_for_run(
        template_snapshot(run_id="run-freeze"),
        provider_snapshots=provider_snapshots,
        internal_bindings=internal_model_bindings(),
        run_id="run-freeze",
        created_at=SNAPSHOT_AT,
    )

    provider.runtime_capabilities = [
        model_capability(
            model_id="alpha-chat",
            context_window_tokens=32000,
            max_output_tokens=512,
            supports_tool_calling=False,
            supports_structured_output=True,
            supports_native_reasoning=False,
        )
    ]
    provider.updated_at = LATER

    provider_capabilities = provider_snapshots[0].capabilities
    binding_capabilities = model_binding_snapshots[0].capabilities
    for frozen_capabilities in (provider_capabilities, binding_capabilities):
        assert frozen_capabilities.context_window_tokens == 128000
        assert frozen_capabilities.max_output_tokens == 4096
        assert frozen_capabilities.supports_tool_calling is True
        assert frozen_capabilities.supports_structured_output is False
        assert frozen_capabilities.supports_native_reasoning is True


def test_delivery_channel_updates_do_not_mutate_started_run_snapshot_or_run_ref(
    tmp_path: Path,
) -> None:
    run_id = "run-delivery-freeze"
    credential_ref = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()
    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_with_delivery_channel(session)
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        assert channel is not None
        channel.credential_ref = credential_ref
        channel.credential_status = CredentialStatus.READY
        channel.readiness_status = DeliveryReadinessStatus.READY
        channel.readiness_message = "git_auto_delivery is ready."
        channel.last_validated_at = SNAPSHOT_AT
        channel.updated_at = SNAPSHOT_AT
        session.add(channel)
        session.commit()
    seed_runtime_run_for_delivery_snapshot(manager, run_id=run_id)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        service = DeliverySnapshotService(
            control_session=control_session,
            runtime_session=runtime_session,
            delivery_channel_service=DeliveryChannelService(control_session),
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: SNAPSHOT_AT,
        )
        snapshot = service.prepare_delivery_snapshot(
            run_id=run_id,
            project_id=DEFAULT_PROJECT_ID,
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )
        snapshot_id = snapshot.delivery_channel_snapshot_id

    with manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        assert channel is not None
        channel.repository_identifier = "owner/renamed-repo"
        channel.default_branch = "release/v2"
        channel.credential_ref = "env:AI_DEVFLOW_CREDENTIAL_ROTATED"
        channel.credential_status = CredentialStatus.INVALID
        channel.readiness_status = DeliveryReadinessStatus.INVALID
        channel.readiness_message = "rotated credential is invalid."
        channel.last_validated_at = LATER
        channel.updated_at = LATER
        session.add(channel)
        session.commit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, run_id)
        saved_snapshot = session.get(DeliveryChannelSnapshotModel, snapshot_id)

    assert run is not None
    assert saved_snapshot is not None
    assert run.delivery_channel_snapshot_ref == snapshot_id
    assert saved_snapshot.source_delivery_channel_id == DEFAULT_DELIVERY_CHANNEL_ID
    assert saved_snapshot.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
    assert saved_snapshot.scm_provider_type is ScmProviderType.GITHUB
    assert saved_snapshot.repository_identifier == "owner/repo"
    assert saved_snapshot.default_branch == "main"
    assert saved_snapshot.code_review_request_type is CodeReviewRequestType.PULL_REQUEST
    assert saved_snapshot.credential_ref == credential_ref
    assert saved_snapshot.credential_status is CredentialStatus.READY
    assert saved_snapshot.readiness_status is DeliveryReadinessStatus.READY
    assert saved_snapshot.readiness_message == "git_auto_delivery is ready."
    assert saved_snapshot.last_validated_at == SNAPSHOT_AT.replace(tzinfo=None)
    assert audit.records[0]["action"] == "delivery_snapshot.prepare"
    assert log_writer.records[0].message == "Delivery snapshot prepared."


def test_configuration_package_and_settings_override_do_not_cross_runtime_snapshot_boundary(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService
    from backend.app.services.providers import ProviderService
    from backend.tests.fixtures import settings_override_fixture

    forbidden_top_level_fields = {
        "compression_threshold_ratio": 0.8,
        "runtime_limit_snapshot": {"snapshot_id": "runtime-limit-snapshot-1"},
        "runtime_snapshots": [{"snapshot_id": "runtime-limit-snapshot-1"}],
        "audit_records": [{"body": "audit body"}],
        "log_records": [{"body": "log body"}],
        "platform_runtime_root": "C:/runtime",
        "workspace_root": "C:/runtime/workspaces",
        "control_database_path": "C:/runtime/control.db",
        "runtime_database_path": "C:/runtime/runtime.db",
        "graph_database_path": "C:/runtime/graph.db",
        "event_database_path": "C:/runtime/event.db",
        "log_database_path": "C:/runtime/log.db",
    }
    for field_name, value in forbidden_top_level_fields.items():
        with pytest.raises(ValidationError) as error:
            ConfigurationPackageExport(**export_payload(**{field_name: value}))
        assert field_name in str(error.value)

    nested_forbidden_payloads = [
        export_payload(
            providers=[
                provider_package_payload(
                    compression_threshold_ratio=0.8,
                )
            ]
        ),
        export_payload(
            delivery_channels=[
                delivery_channel_package_payload(log_body="full log body")
            ]
        ),
        export_payload(
            pipeline_templates=[
                pipeline_template_package_payload(
                    runtime_snapshot_ref="runtime-limit-snapshot-1",
                    audit_body="full audit body",
                )
            ]
        ),
    ]
    for payload in nested_forbidden_payloads:
        with pytest.raises(ValidationError):
            ConfigurationPackageExport(**payload)

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()
    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_with_delivery_channel(session)
        ProviderService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).seed_builtin_providers(trace_context=build_trace())
        deepseek = session.get(ProviderModel, "provider-deepseek")
        assert deepseek is not None
        deepseek.api_key_ref = RAW_SECRET_VALUE
        deepseek.is_configured = True
        session.add(deepseek)
        session.commit()

        package = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).export_project_package(DEFAULT_PROJECT_ID, trace_context=build_trace())

    serialized = package.model_dump_json()
    assert RAW_SECRET_VALUE not in serialized
    assert '"api_key_ref":null' in serialized
    assert "[blocked:credential_ref]" in serialized
    assert "compression_threshold_ratio" not in serialized
    assert "runtime_snapshot" not in serialized
    assert "platform_runtime_root" not in serialized
    assert "workspace_root" not in serialized
    assert "control_database_path" not in serialized
    assert "runtime_database_path" not in serialized
    assert "graph_database_path" not in serialized
    assert "event_database_path" not in serialized
    assert "log_database_path" not in serialized
    assert "audit_records" not in serialized
    assert "log_records" not in serialized

    settings = settings_override_fixture(
        tmp_path,
        platform_runtime_root=tmp_path / ".runtime",
        workspace_root=tmp_path / "workspaces",
        credential_env_prefixes=("TEAM_", "OPENAI_"),
    )
    assert settings.resolve_platform_runtime_root() == (tmp_path / ".runtime").resolve()
    assert settings.resolve_workspace_root() == (tmp_path / "workspaces").resolve()
    assert settings.is_allowed_credential_env_name("TEAM_TOKEN")
    assert not settings.is_allowed_credential_env_name("OTHER_TOKEN")

    with pytest.raises(ValueError, match="frontend_api_base_url"):
        settings_override_fixture(
            tmp_path,
            frontend_api_base_url="http://localhost:9000/api",
        )
    with pytest.raises(ValueError, match="tmp_path"):
        settings_override_fixture(
            tmp_path,
            platform_runtime_root=tmp_path.parent / "outside-runtime",
        )
    with pytest.raises(ValueError, match="tmp_path"):
        settings_override_fixture(
            tmp_path,
            workspace_root=tmp_path.parent / "outside-workspaces",
        )


def test_context_size_guard_uses_frozen_model_capabilities_and_runtime_threshold() -> None:
    provider = ProviderConfigStub(
        runtime_capabilities=[
            model_capability(
                context_window_tokens=128000,
                max_output_tokens=8192,
                supports_tool_calling=True,
                supports_structured_output=True,
                supports_native_reasoning=True,
            )
        ]
    )
    provider_snapshot = ProviderSnapshotBuilder.build_for_run(
        [provider],
        run_id="run-context-size",
        required_provider_ids=("provider-alpha",),
        created_at=SNAPSHOT_AT,
        credential_env_prefixes=("AI_DEVFLOW_CREDENTIAL_",),
    )[0]
    runtime_snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
        runtime_settings(context_limits=context_limits(compression_threshold_ratio=0.8)),
        template_snapshot=template_snapshot(run_id="run-context-size"),
        run_id="run-context-size",
        created_at=SNAPSHOT_AT,
    )
    runtime_snapshot_read = RuntimeLimitSnapshotRead.model_validate(
        runtime_snapshot.model_dump(mode="python")
    )
    guard = ContextSizeGuard()

    trigger = guard.compression_trigger_tokens(
        provider_snapshot=provider_snapshot,
        runtime_limit_snapshot=runtime_snapshot_read,
    )
    reserved_trigger = guard.compression_trigger_tokens(
        provider_snapshot=provider_snapshot,
        runtime_limit_snapshot=runtime_snapshot_read,
        reserved_output_tokens=8000,
    )

    assert trigger == 102400
    assert reserved_trigger == 96000
    assert reserved_trigger < trigger
    assert provider_snapshot.capabilities.context_window_tokens == 128000
    assert provider_snapshot.capabilities.max_output_tokens == 8192
    assert provider_snapshot.capabilities.supports_tool_calling is True
    assert provider_snapshot.capabilities.supports_structured_output is True
    assert provider_snapshot.capabilities.supports_native_reasoning is True
    with pytest.raises(ValidationError):
        provider_snapshot.capabilities.supports_tool_calling = False
