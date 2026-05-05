from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    DeliveryChannelModel,
    PipelineTemplateModel,
    ProjectModel,
    ProviderModel,
)
from backend.app.db.models.runtime import DeliveryChannelSnapshotModel, RuntimeBase
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    ScmProviderType,
    TemplateSource,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import JsonlWriteResult
from backend.app.schemas.configuration_package import ConfigurationPackageImportRequest
from backend.app.schemas.configuration_package import (
    ConfigurationPackageModelRuntimeCapabilities,
)
from backend.app.schemas.observability import AuditActorType, AuditResult, LogCategory
from backend.app.schemas.template import (
    FIXED_APPROVAL_CHECKPOINTS,
    FIXED_STAGE_SEQUENCE,
    PipelineTemplateWriteRequest,
)


NOW = datetime(2026, 5, 2, 16, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 2, 16, 15, 0, tzinfo=UTC)
DEFAULT_PROJECT_ID = "project-default"
DEFAULT_DELIVERY_CHANNEL_ID = "delivery-default"
SAFE_DELIVERY_CREDENTIAL_REF = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
RAW_SECRET_VALUE = "raw-secret-value"
PROVIDER_BASE_URL = "https://api.deepseek.example/v1"
PROMPT_BODY = "# Prompt body for stage runtime config"


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append(
            {"method": "record_rejected_command", "result": AuditResult.REJECTED, **kwargs}
        )
        return object()


class FailingAuditService:
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")

    def record_rejected_command(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


class RecordingLogWriter:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def write(self, record: Any) -> JsonlWriteResult:
        self.records.append(record)
        return JsonlWriteResult(
            log_id=record.log_id or "log-configuration-package",
            log_file_ref="logs/app.jsonl",
            line_offset=0,
            line_number=len(self.records),
            log_file_generation="app",
            created_at=record.created_at or LATER,
        )


class FailingLogWriter:
    def write(self, record: Any) -> JsonlWriteResult:
        raise OSError("log path unavailable")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-configuration-package",
        trace_id="trace-configuration-package",
        correlation_id="correlation-configuration-package",
        span_id="span-configuration-package",
        parent_span_id=None,
        created_at=NOW,
    )


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


def action_records(audit: RecordingAuditService, action: str) -> list[dict[str, Any]]:
    return [record for record in audit.records if record["action"] == action]


def seed_project_with_channel(
    session: Any,
    *,
    delivery_mode: DeliveryMode = DeliveryMode.DEMO_DELIVERY,
    credential_ref: str | None = None,
) -> ProjectModel:
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
        project_id=project.project_id,
        delivery_mode=delivery_mode,
        scm_provider_type=(
            ScmProviderType.GITHUB
            if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
            else None
        ),
        repository_identifier=(
            "owner/repo" if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY else None
        ),
        default_branch="main" if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY else None,
        code_review_request_type=(
            CodeReviewRequestType.PULL_REQUEST
            if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
            else None
        ),
        credential_ref=credential_ref,
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
    return project


def configure_builtin_providers(
    session: Any,
    provider_ids: tuple[str, ...] = ("provider-volcengine", "provider-deepseek"),
) -> None:
    providers = (
        session.query(ProviderModel)
        .filter(ProviderModel.provider_id.in_(provider_ids))
        .all()
    )
    assert {provider.provider_id for provider in providers} == set(provider_ids)
    for provider in providers:
        provider.is_configured = True
        provider.is_enabled = True
        session.add(provider)
    session.commit()


def template_write_request(
    *,
    name: str = "Team feature flow",
    provider_id: str = "provider-deepseek",
    auto_regression_enabled: bool = True,
    max_auto_regression_retries: int = 2,
) -> PipelineTemplateWriteRequest:
    return PipelineTemplateWriteRequest(
        name=name,
        description="Team-owned runtime template",
        fixed_stage_sequence=list(FIXED_STAGE_SEQUENCE),
        stage_role_bindings=[
            {
                "stage_type": stage_type.value,
                "role_id": role_id,
                "system_prompt": PROMPT_BODY,
                "provider_id": provider_id,
            }
            for stage_type, role_id in [
                (FIXED_STAGE_SEQUENCE[0], "role-requirement-analyst"),
                (FIXED_STAGE_SEQUENCE[1], "role-solution-designer"),
                (FIXED_STAGE_SEQUENCE[2], "role-code-generator"),
                (FIXED_STAGE_SEQUENCE[3], "role-test-runner"),
                (FIXED_STAGE_SEQUENCE[4], "role-code-reviewer"),
                (FIXED_STAGE_SEQUENCE[5], "role-code-reviewer"),
            ]
        ],
        approval_checkpoints=list(FIXED_APPROVAL_CHECKPOINTS),
        auto_regression_enabled=auto_regression_enabled,
        max_auto_regression_retries=max_auto_regression_retries,
    )


def seed_user_visible_config(session: Any, audit: RecordingAuditService) -> str:
    from backend.app.services.providers import ProviderService
    from backend.app.services.templates import TemplateService

    seed_project_with_channel(session)
    ProviderService(session, audit_service=audit, now=lambda: NOW).seed_builtin_providers(
        trace_context=build_trace()
    )
    configure_builtin_providers(session, ("provider-deepseek",))
    TemplateService(session, audit_service=audit, now=lambda: NOW).seed_system_templates(
        trace_context=build_trace()
    )
    user_template = TemplateService(
        session,
        audit_service=audit,
        now=lambda: NOW,
    ).save_as_user_template(
        source_template_id=None,
        body=template_write_request(),
        trace_context=build_trace(),
    )
    return user_template.template_id


def provider_package_entry(
    *,
    provider_id: str = "provider-deepseek",
    display_name: str = "DeepSeek",
    provider_source: str = "builtin",
    protocol_type: str = "openai_completions_compatible",
    base_url: str = PROVIDER_BASE_URL,
    api_key_ref: str | None = "env:DEEPSEEK_ROTATED_API_KEY",
    default_model_id: str = "deepseek-reasoner",
    supported_model_ids: list[str] | None = None,
    runtime_capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model_ids = supported_model_ids or ["deepseek-chat", "deepseek-reasoner"]
    return {
        "provider_id": provider_id,
        "display_name": display_name,
        "provider_source": provider_source,
        "protocol_type": protocol_type,
        "base_url": base_url,
        "api_key_ref": api_key_ref,
        "default_model_id": default_model_id,
        "supported_model_ids": model_ids,
        "runtime_capabilities": runtime_capabilities
        or [
            {"model_id": "deepseek-chat"},
            {"model_id": "deepseek-reasoner", "supports_native_reasoning": True},
        ],
    }


def delivery_package_entry(
    *,
    credential_ref: str | None = SAFE_DELIVERY_CREDENTIAL_REF,
) -> dict[str, Any]:
    return {
        "delivery_mode": "git_auto_delivery",
        "scm_provider_type": "github",
        "repository_identifier": "owner/repo",
        "default_branch": "main",
        "code_review_request_type": "pull_request",
        "credential_ref": credential_ref,
    }


def template_package_entry(
    template_id: str,
    *,
    template_source: str = "user_template",
    provider_id: str = "provider-deepseek",
    auto_regression_enabled: bool = False,
) -> dict[str, Any]:
    return {
        "template_id": template_id,
        "name": "Imported team flow",
        "template_source": template_source,
        "stage_role_bindings": [
            {
                "stage_type": binding.stage_type.value,
                "role_id": binding.role_id,
                "system_prompt": binding.system_prompt,
                "provider_id": provider_id,
            }
            for binding in template_write_request(provider_id=provider_id).stage_role_bindings
        ],
        "auto_regression_enabled": auto_regression_enabled,
        "max_auto_regression_retries": 1,
    }


def package_request(
    template_id: str,
    *,
    package_schema_version: str = "function-one-config-v1",
    scope_project_id: str = DEFAULT_PROJECT_ID,
    providers: list[dict[str, Any]] | None = None,
    delivery_channels: list[dict[str, Any]] | None = None,
    pipeline_templates: list[dict[str, Any]] | None = None,
) -> ConfigurationPackageImportRequest:
    payload: dict[str, Any] = {
        "package_schema_version": package_schema_version,
        "scope": {"scope_type": "project", "project_id": scope_project_id},
        "providers": providers if providers is not None else [provider_package_entry()],
        "delivery_channels": (
            delivery_channels
            if delivery_channels is not None
            else [delivery_package_entry()]
        ),
        "pipeline_templates": (
            pipeline_templates
            if pipeline_templates is not None
            else [template_package_entry(template_id)]
        ),
    }
    return ConfigurationPackageImportRequest(**payload)


def test_export_project_package_contains_user_visible_config_only(tmp_path: Path) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        assert channel is not None
        channel.delivery_mode = DeliveryMode.GIT_AUTO_DELIVERY
        channel.scm_provider_type = ScmProviderType.GITHUB
        channel.repository_identifier = "owner/repo"
        channel.default_branch = "main"
        channel.code_review_request_type = CodeReviewRequestType.PULL_REQUEST
        channel.credential_ref = RAW_SECRET_VALUE
        provider = session.get(ProviderModel, "provider-deepseek")
        assert provider is not None
        provider.api_key_ref = RAW_SECRET_VALUE
        session.add(channel)
        session.add(provider)
        session.commit()

        package = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).export_project_package(DEFAULT_PROJECT_ID, trace_context=build_trace())

    assert package.package_schema_version == "function-one-config-v1"
    assert package.scope.project_id == DEFAULT_PROJECT_ID
    assert [provider.provider_id for provider in package.providers] == [
        "provider-deepseek",
    ]
    exported_deepseek = next(
        provider
        for provider in package.providers
        if provider.provider_id == "provider-deepseek"
    )
    assert exported_deepseek.supported_model_ids == [
        "deepseek-chat",
        "deepseek-reasoner",
    ]
    assert {item.model_id for item in exported_deepseek.runtime_capabilities} == {
        "deepseek-chat",
        "deepseek-reasoner",
    }
    assert exported_deepseek.api_key_ref == "[blocked:api_key_ref]"
    assert len(package.delivery_channels) == 1
    assert package.delivery_channels[0].credential_ref == "[blocked:credential_ref]"
    assert [template.template_id for template in package.pipeline_templates] == [template_id]
    assert package.pipeline_templates[0].template_source is TemplateSource.USER_TEMPLATE
    serialized = package.model_dump_json()
    assert RAW_SECRET_VALUE not in serialized
    assert "template-feature" not in serialized
    assert "platform_runtime_settings" not in serialized
    assert "compression_threshold_ratio" not in serialized
    assert "runtime_snapshot" not in serialized
    assert "audit" not in serialized
    assert "log" not in serialized

    export_audits = action_records(audit, "configuration_package.export")
    assert len(export_audits) == 1
    assert export_audits[0]["actor_type"] is AuditActorType.USER
    assert export_audits[0]["target_id"] == DEFAULT_PROJECT_ID
    assert len(log_writer.records) == 1
    assert log_writer.records[0].category is LogCategory.API
    assert log_writer.records[0].source == "services.configuration_packages"


def test_export_project_package_omits_unconfigured_builtin_providers(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_with_channel(session)
        ProviderService(session, audit_service=audit, now=lambda: NOW).seed_builtin_providers(
            trace_context=build_trace()
        )
        configure_builtin_providers(session, ("provider-deepseek",))

        package = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=RecordingLogWriter(),
            now=lambda: LATER,
        ).export_project_package(DEFAULT_PROJECT_ID, trace_context=build_trace())

    assert [provider.provider_id for provider in package.providers] == [
        "provider-deepseek"
    ]


def test_import_package_updates_provider_delivery_channel_and_template_runtime_config(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(template_id),
            trace_context=build_trace(),
        )
        saved_provider = session.get(ProviderModel, "provider-deepseek")
        saved_channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        saved_template = session.get(PipelineTemplateModel, template_id)

    assert result.summary == "Imported 3 configuration objects."
    assert result.package_id.startswith("config-import-")
    assert result.field_errors == []
    assert {item.object_type for item in result.changed_objects} == {
        "provider",
        "delivery_channel",
        "pipeline_template",
    }
    assert all(item.config_version for item in result.changed_objects)
    assert {
        item.object_type: item.config_version for item in result.changed_objects
    } == {
        "provider": LATER.isoformat(),
        "delivery_channel": LATER.isoformat(),
        "pipeline_template": LATER.isoformat(),
    }
    assert saved_provider is not None
    assert saved_provider.default_model_id == "deepseek-reasoner"
    assert saved_provider.base_url == PROVIDER_BASE_URL
    by_model = {
        capability["model_id"]: capability
        for capability in saved_provider.runtime_capabilities
    }
    assert by_model["deepseek-reasoner"]["max_output_tokens"] == 4096
    assert saved_channel is not None
    assert saved_channel.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
    assert saved_channel.credential_ref == SAFE_DELIVERY_CREDENTIAL_REF
    assert saved_template is not None
    assert saved_template.auto_regression_enabled is False
    assert action_records(audit, "configuration_package.import")
    assert log_writer.records[0].message == "Configuration package import processed."


def test_import_package_configures_builtin_provider_when_values_match_seed(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    matching_seed_provider = provider_package_entry(
        base_url="https://api.deepseek.com",
        api_key_ref="env:DEEPSEEK_API_KEY",
        default_model_id="deepseek-chat",
        runtime_capabilities=[
            {
                "model_id": "deepseek-chat",
                "context_window_tokens": 128000,
                "max_output_tokens": 8192,
                "supports_tool_calling": True,
                "supports_structured_output": False,
                "supports_native_reasoning": False,
            },
            {
                "model_id": "deepseek-reasoner",
                "context_window_tokens": 128000,
                "max_output_tokens": 8192,
                "supports_tool_calling": False,
                "supports_structured_output": False,
                "supports_native_reasoning": True,
            },
        ],
    )

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_with_channel(session)
        ProviderService(session, audit_service=audit, now=lambda: NOW).seed_builtin_providers(
            trace_context=build_trace()
        )

        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=RecordingLogWriter(),
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                "template-unused",
                providers=[matching_seed_provider],
                delivery_channels=[],
                pipeline_templates=[],
            ),
            trace_context=build_trace(),
        )
        provider = session.get(ProviderModel, "provider-deepseek")

    assert result.field_errors == []
    assert [
        (item.object_type, item.object_id, item.action)
        for item in result.changed_objects
    ] == [("provider", "provider-deepseek", "updated")]
    assert provider is not None
    assert provider.is_configured is True
    assert provider.is_enabled is True


def test_import_package_preserves_new_custom_provider_ids_in_templates(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_user_visible_config(session, audit)
        custom_provider = provider_package_entry(
            provider_id="provider-custom-package",
            display_name="Imported custom provider",
            provider_source="custom",
            base_url="https://custom-provider.example/v1",
            api_key_ref="env:AI_DEVFLOW_CREDENTIAL_CUSTOM_PROVIDER",
            default_model_id="custom-chat",
            supported_model_ids=["custom-chat"],
            runtime_capabilities=[{"model_id": "custom-chat"}],
        )
        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                "template-custom-package",
                providers=[custom_provider],
                delivery_channels=[],
                pipeline_templates=[
                    template_package_entry(
                        "template-custom-package",
                        provider_id="provider-custom-package",
                    )
                ],
            ),
            trace_context=build_trace(),
        )
        saved_custom = (
            session.query(ProviderModel)
            .filter(ProviderModel.provider_source == ProviderSource.CUSTOM)
            .one()
        )
        saved_template = (
            session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_source == TemplateSource.USER_TEMPLATE)
            .filter(PipelineTemplateModel.name == "Imported team flow")
            .one()
        )

    assert result.field_errors == []
    assert saved_custom.provider_id == "provider-custom-package"
    assert {
        binding["provider_id"] for binding in saved_template.stage_role_bindings
    } == {"provider-custom-package"}


def test_import_package_rejects_template_referencing_unconfigured_provider(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_with_channel(session)
        ProviderService(session, audit_service=audit, now=lambda: NOW).seed_builtin_providers(
            trace_context=build_trace()
        )

        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=RecordingLogWriter(),
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                "template-unconfigured-provider",
                providers=[],
                delivery_channels=[],
                pipeline_templates=[
                    template_package_entry("template-unconfigured-provider")
                ],
            ),
            trace_context=build_trace(),
        )

    assert result.changed_objects == []
    assert result.field_errors[0].field == "pipeline_templates[0].stage_role_bindings"
    assert result.field_errors[0].message == (
        "Pipeline template references an unknown Provider."
    )


def test_import_package_returns_field_errors_and_rolls_back_invalid_provider(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        invalid_package = package_request(template_id)
        invalid_package.providers[0].default_model_id = "deepseek-missing"
        invalid_package.providers[0].supported_model_ids = ["deepseek-chat"]
        invalid_package.providers[0].runtime_capabilities = [
            ConfigurationPackageModelRuntimeCapabilities(model_id="deepseek-chat")
        ]
        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            invalid_package,
            trace_context=build_trace(),
        )
        provider = session.get(ProviderModel, "provider-deepseek")

    assert result.changed_objects == []
    assert result.package_id.startswith("config-import-")
    assert [error.model_dump() for error in result.field_errors] == [
        {
            "field": "providers[0].default_model_id",
            "message": "Provider default_model_id must be in supported_model_ids.",
        }
    ]
    assert provider is not None
    assert provider.default_model_id == "deepseek-chat"
    assert action_records(audit, "configuration_package.import.rejected")


def test_import_rejects_non_ascii_provider_api_key_ref_without_changes(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        invalid_package = package_request(template_id)
        invalid_package.providers[0].api_key_ref = "env:AI_DEVFLOW_CREDENTIAL_密钥"
        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            invalid_package,
            trace_context=build_trace(),
        )
        provider = session.get(ProviderModel, "provider-deepseek")

    assert result.changed_objects == []
    assert [error.model_dump() for error in result.field_errors] == [
        {
            "field": "providers[0].api_key_ref",
            "message": "Provider api_key_ref must use an env: credential reference.",
        }
    ]
    assert provider is not None
    assert provider.api_key_ref == "env:DEEPSEEK_API_KEY"
    assert action_records(audit, "configuration_package.import.rejected")


def test_import_rejects_unsupported_version_and_scope_mismatch_without_changes(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        service = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        )
        unsupported = service.import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                template_id,
                package_schema_version="function-one-v0",
            ),
            trace_context=build_trace(),
        )
        generated_unsupported = service.import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                template_id,
                package_schema_version="function-one-v0",
            ),
            trace_context=build_trace(),
        )
        generated_unsupported_again = service.import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                template_id,
                package_schema_version="function-one-v0",
            ),
            trace_context=build_trace(),
        )
        scope_mismatch = service.import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(template_id, scope_project_id="project-other"),
            trace_context=build_trace(),
        )
        provider = session.get(ProviderModel, "provider-deepseek")

    assert unsupported.package_id.startswith("config-import-")
    assert generated_unsupported.package_id.startswith("config-import-")
    assert generated_unsupported_again.package_id.startswith("config-import-")
    assert generated_unsupported.package_id != generated_unsupported_again.package_id
    assert [error.model_dump() for error in unsupported.field_errors] == [
        {
            "field": "package_schema_version",
            "message": "Unsupported configuration package schema version.",
        }
    ]
    assert [error.model_dump() for error in scope_mismatch.field_errors] == [
        {
            "field": "scope.project_id",
            "message": "Configuration package scope does not match the target Project.",
        }
    ]
    assert provider is not None
    assert provider.default_model_id == "deepseek-chat"


def test_import_rejects_multiple_delivery_channels_and_system_template_entries(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        service = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        )
        too_many_channels = service.import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                template_id,
                delivery_channels=[delivery_package_entry(), delivery_package_entry()],
            ),
            trace_context=build_trace(),
        )
        system_template = service.import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                template_id,
                pipeline_templates=[
                    template_package_entry(
                        "template-feature",
                        template_source="system_template",
                    )
                ],
            ),
            trace_context=build_trace(),
        )
        saved_system_template = session.get(PipelineTemplateModel, "template-feature")

    assert [error.model_dump() for error in too_many_channels.field_errors] == [
        {
            "field": "delivery_channels",
            "message": (
                "Configuration package must contain at most one project DeliveryChannel."
            ),
        }
    ]
    assert [error.model_dump() for error in system_template.field_errors] == [
        {
            "field": "pipeline_templates[0].template_source",
            "message": (
                "System templates cannot be overwritten by configuration package import."
            ),
        }
    ]
    assert saved_system_template is not None
    assert saved_system_template.template_source is TemplateSource.SYSTEM_TEMPLATE
    assert saved_system_template.name != "Imported team flow"


def test_import_rolls_back_prior_provider_and_delivery_changes_on_template_error(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        invalid_template = template_package_entry(
            template_id,
            provider_id="provider-missing",
        )
        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(template_id, pipeline_templates=[invalid_template]),
            trace_context=build_trace(),
        )
        provider = session.get(ProviderModel, "provider-deepseek")
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        template = session.get(PipelineTemplateModel, template_id)

    assert result.changed_objects == []
    assert result.field_errors[0].field == "pipeline_templates[0].stage_role_bindings"
    assert provider is not None
    assert provider.default_model_id == "deepseek-chat"
    assert channel is not None
    assert channel.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert template is not None
    assert template.auto_regression_enabled is True


def test_import_validation_failure_logs_rejected_command_without_product_state(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(
                template_id,
                package_schema_version="function-one-v0",
            ),
            trace_context=build_trace(),
        )
        provider = session.get(ProviderModel, "provider-deepseek")

    assert result.field_errors[0].field == "package_schema_version"
    assert provider is not None
    assert provider.default_model_id == "deepseek-chat"
    assert action_records(audit, "configuration_package.import.rejected")
    assert len(log_writer.records) == 1
    assert log_writer.records[0].message == "Configuration package import processed."
    log_text = str(log_writer.records[0].payload.summary) + (
        log_writer.records[0].payload.excerpt or ""
    )
    assert "package_schema_version" in log_text
    assert PROVIDER_BASE_URL not in log_text
    assert PROMPT_BODY not in log_text


def test_import_does_not_mutate_delivery_channel_snapshots(tmp_path: Path) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        runtime_session.add(
            DeliveryChannelSnapshotModel(
                delivery_channel_snapshot_id="delivery-snapshot-1",
                run_id="run-1",
                source_delivery_channel_id=DEFAULT_DELIVERY_CHANNEL_ID,
                delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
                scm_provider_type=ScmProviderType.GITHUB,
                repository_identifier="old/repo",
                default_branch="old-main",
                code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
                credential_ref="env:AI_DEVFLOW_CREDENTIAL_OLD",
                credential_status=CredentialStatus.UNBOUND,
                readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
                readiness_message="snapshot stays frozen",
                last_validated_at=None,
                schema_version="delivery-channel-snapshot-v1",
                created_at=NOW,
            )
        )
        runtime_session.commit()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            package_request(template_id),
            trace_context=build_trace(),
        )

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        snapshot = runtime_session.get(
            DeliveryChannelSnapshotModel,
            "delivery-snapshot-1",
        )

    assert snapshot is not None
    assert snapshot.repository_identifier == "old/repo"
    assert snapshot.default_branch == "old-main"
    assert snapshot.readiness_message == "snapshot stays frozen"


def test_import_missing_project_raises_not_found_and_writes_rejected_audit(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import (
        ConfigurationPackageService,
        ConfigurationPackageServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        with pytest.raises(ConfigurationPackageServiceError) as error:
            ConfigurationPackageService(
                session,
                audit_service=audit,
                log_writer=log_writer,
                now=lambda: LATER,
            ).import_project_package(
                "project-missing",
                package_request("template-user-missing"),
                trace_context=build_trace(),
            )

    assert error.value.error_code is ErrorCode.NOT_FOUND
    assert error.value.status_code == 404
    assert error.value.message == "Project was not found."
    rejected = action_records(audit, "configuration_package.import.rejected")
    assert len(rejected) == 1
    assert rejected[0]["target_id"] == "project-missing"


def test_log_write_failure_rolls_back_and_audits_failed_result(tmp_path: Path) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        with pytest.raises(OSError, match="log path unavailable"):
            ConfigurationPackageService(
                session,
                audit_service=audit,
                log_writer=FailingLogWriter(),
                now=lambda: LATER,
            ).import_project_package(
                DEFAULT_PROJECT_ID,
                package_request(template_id),
                trace_context=build_trace(),
            )
        provider = session.get(ProviderModel, "provider-deepseek")
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert provider is not None
    assert provider.default_model_id == "deepseek-chat"
    assert channel is not None
    assert channel.delivery_mode is DeliveryMode.DEMO_DELIVERY
    failed = action_records(audit, "configuration_package.import.failed")
    assert len(failed) == 1
    assert failed[0]["reason"] == "log path unavailable"


def test_audit_failure_rolls_back_and_propagates(tmp_path: Path) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, RecordingAuditService())
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            ConfigurationPackageService(
                session,
                audit_service=FailingAuditService(),
                log_writer=RecordingLogWriter(),
                now=lambda: LATER,
            ).import_project_package(
                DEFAULT_PROJECT_ID,
                package_request(template_id),
                trace_context=build_trace(),
            )
        provider = session.get(ProviderModel, "provider-deepseek")

    assert provider is not None
    assert provider.default_model_id == "deepseek-chat"


def test_audit_and_log_metadata_exclude_secret_base_url_and_prompt_bodies(
    tmp_path: Path,
) -> None:
    from backend.app.services.configuration_packages import ConfigurationPackageService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        template_id = seed_user_visible_config(session, audit)
        package = package_request(template_id)
        result = ConfigurationPackageService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).import_project_package(
            DEFAULT_PROJECT_ID,
            package,
            trace_context=build_trace(),
        )

    assert result.field_errors == []
    metadata_text = str(action_records(audit, "configuration_package.import")[0]["metadata"])
    log_text = str(log_writer.records[0].payload.summary) + (
        log_writer.records[0].payload.excerpt or ""
    )
    for forbidden in [RAW_SECRET_VALUE, PROVIDER_BASE_URL, PROMPT_BODY, "system_prompt"]:
        assert forbidden not in metadata_text
        assert forbidden not in log_text
