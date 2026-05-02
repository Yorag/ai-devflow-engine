from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    DeliveryChannelModel,
    PipelineTemplateModel,
    ProviderModel,
)
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult
from backend.app.schemas.template import FIXED_APPROVAL_CHECKPOINTS, FIXED_STAGE_SEQUENCE


def build_configuration_package_api_app(tmp_path: Path):
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    app = create_app(settings=settings)
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    return app


def template_payload(
    template_id: str = "template-user-package",
    *,
    template_source: str = "user_template",
    provider_id: str = "provider-deepseek",
) -> dict:
    return {
        "template_id": template_id,
        "name": "Imported package flow",
        "template_source": template_source,
        "stage_role_bindings": [
            {
                "stage_type": stage_type.value,
                "role_id": role_id,
                "system_prompt": f"# Prompt for {stage_type.value}",
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
        "auto_regression_enabled": False,
        "max_auto_regression_retries": 1,
    }


def package_payload(
    *,
    package_schema_version: str = "function-one-config-v1",
    scope_project_id: str = "project-default",
    providers: list[dict] | None = None,
    delivery_channels: list[dict] | None = None,
    pipeline_templates: list[dict] | None = None,
) -> dict:
    payload = {
        "package_schema_version": package_schema_version,
        "scope": {"scope_type": "project", "project_id": scope_project_id},
        "providers": providers
        if providers is not None
        else [
            {
                "provider_id": "provider-deepseek",
                "display_name": "DeepSeek",
                "provider_source": "builtin",
                "protocol_type": "openai_completions_compatible",
                "base_url": "https://api.deepseek.example/v1",
                "api_key_ref": "env:DEEPSEEK_ROTATED_API_KEY",
                "default_model_id": "deepseek-reasoner",
                "supported_model_ids": ["deepseek-chat", "deepseek-reasoner"],
                "runtime_capabilities": [
                    {"model_id": "deepseek-chat"},
                    {"model_id": "deepseek-reasoner", "supports_native_reasoning": True},
                ],
            }
        ],
        "delivery_channels": delivery_channels
        if delivery_channels is not None
        else [
            {
                "delivery_mode": "git_auto_delivery",
                "scm_provider_type": "github",
                "repository_identifier": "owner/repo",
                "default_branch": "main",
                "code_review_request_type": "pull_request",
                "credential_ref": "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
            }
        ],
        "pipeline_templates": pipeline_templates
        if pipeline_templates is not None
        else [template_payload()],
    }
    return payload


def write_template_payload(name: str = "Exported user flow") -> dict:
    return {
        "name": name,
        "description": "Team-owned feature template",
        "fixed_stage_sequence": [stage.value for stage in FIXED_STAGE_SEQUENCE],
        "stage_role_bindings": [
            {
                "stage_type": stage_type.value,
                "role_id": role_id,
                "system_prompt": f"# Prompt for {stage_type.value}",
                "provider_id": "provider-deepseek",
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
        "approval_checkpoints": [
            checkpoint.value for checkpoint in FIXED_APPROVAL_CHECKPOINTS
        ],
        "auto_regression_enabled": True,
        "max_auto_regression_retries": 2,
    }


def assert_error(
    response,
    *,
    status_code: int,
    error_code: str,
    message: str,
    request_id: str,
    correlation_id: str,
) -> None:
    assert response.status_code == status_code
    assert response.json() == {
        "error_code": error_code,
        "message": message,
        "request_id": request_id,
        "correlation_id": correlation_id,
    }


def test_configuration_package_export_returns_user_visible_scope_and_audits(
    tmp_path: Path,
) -> None:
    app = build_configuration_package_api_app(tmp_path)

    with TestClient(app) as client:
        create_template = client.post(
            "/api/pipeline-templates",
            json=write_template_payload(),
        )
        assert create_template.status_code == 201
        template_id = create_template.json()["template_id"]

        with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
            channel = session.get(DeliveryChannelModel, "delivery-default")
            assert channel is not None
            channel.credential_ref = "raw-secret-value"
            session.add(channel)
            session.commit()

        response = client.get(
            "/api/projects/project-default/configuration-package/export",
            headers={
                "X-Request-ID": "req-config-export",
                "X-Correlation-ID": "corr-config-export",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["package_schema_version"] == "function-one-config-v1"
    assert body["scope"] == {"scope_type": "project", "project_id": "project-default"}
    assert [provider["provider_id"] for provider in body["providers"]] == [
        "provider-volcengine",
        "provider-deepseek",
    ]
    assert body["delivery_channels"][0]["credential_ref"] == "[blocked:credential_ref]"
    assert [template["template_id"] for template in body["pipeline_templates"]] == [
        template_id
    ]
    serialized = str(body)
    for forbidden in [
        "raw-secret-value",
        "platform_runtime_settings",
        "compression_threshold_ratio",
        "runtime_snapshot",
        "audit_logs",
        "database_paths",
    ]:
        assert forbidden not in serialized

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "configuration_package.export",
                AuditLogEntryModel.request_id == "req-config-export",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert "raw-secret-value" not in (audit.metadata_excerpt or "")


def test_configuration_package_import_updates_rows_and_returns_changed_versions(
    tmp_path: Path,
) -> None:
    app = build_configuration_package_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/project-default/configuration-package/import",
            json=package_payload(),
            headers={
                "X-Request-ID": "req-config-import",
                "X-Correlation-ID": "corr-config-import",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["package_id"].startswith("config-import-")
    assert body["summary"] == "Imported 3 configuration objects."
    assert body["field_errors"] == []
    assert {item["object_type"] for item in body["changed_objects"]} == {
        "provider",
        "delivery_channel",
        "pipeline_template",
    }
    assert all(item["config_version"] for item in body["changed_objects"])

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        provider = session.get(ProviderModel, "provider-deepseek")
        channel = session.get(DeliveryChannelModel, "delivery-default")
        template_count = (
            session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_source == "user_template")
            .count()
        )
    assert provider is not None
    assert provider.default_model_id == "deepseek-reasoner"
    assert channel is not None
    assert channel.repository_identifier == "owner/repo"
    assert template_count == 1

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "configuration_package.import",
                AuditLogEntryModel.request_id == "req-config-import",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert "https://api.deepseek.example/v1" not in (audit.metadata_excerpt or "")
    assert "# Prompt for" not in (audit.metadata_excerpt or "")


def test_configuration_package_import_rejected_results_do_not_partially_persist(
    tmp_path: Path,
) -> None:
    app = build_configuration_package_api_app(tmp_path)
    invalid_provider = deepcopy(package_payload())
    invalid_provider["providers"][0]["runtime_capabilities"] = [
        {"model_id": "deepseek-chat"},
        {"model_id": "deepseek-reasoner"},
        {"model_id": "deepseek-reasoner"},
    ]

    with TestClient(app) as client:
        unsupported = client.post(
            "/api/projects/project-default/configuration-package/import",
            json=package_payload(package_schema_version="function-one-v0"),
        )
        scope_mismatch = client.post(
            "/api/projects/project-default/configuration-package/import",
            json=package_payload(scope_project_id="project-other"),
        )
        invalid = client.post(
            "/api/projects/project-default/configuration-package/import",
            json=invalid_provider,
        )
        invalid_model = deepcopy(package_payload())
        invalid_model["providers"][0]["default_model_id"] = "deepseek-missing"
        invalid_model["providers"][0]["supported_model_ids"] = ["deepseek-chat"]
        invalid_model["providers"][0]["runtime_capabilities"] = [
            {"model_id": "deepseek-chat"}
        ]
        invalid_model_response = client.post(
            "/api/projects/project-default/configuration-package/import",
            json=invalid_model,
        )
        invalid_git_channel = deepcopy(package_payload())
        invalid_git_channel["delivery_channels"][0]["credential_ref"] = None
        invalid_git_response = client.post(
            "/api/projects/project-default/configuration-package/import",
            json=invalid_git_channel,
        )
        system_template = client.post(
            "/api/projects/project-default/configuration-package/import",
            json=package_payload(
                pipeline_templates=[
                    template_payload("template-feature", template_source="system_template")
                ]
            ),
        )

    assert unsupported.status_code == 200
    assert unsupported.json()["field_errors"][0]["field"] == "package_schema_version"
    assert scope_mismatch.status_code == 200
    assert scope_mismatch.json()["field_errors"][0]["field"] == "scope.project_id"
    assert invalid.status_code == 200
    assert invalid.json()["field_errors"][0] == {
        "field": "providers[0].runtime_capabilities",
        "message": "Provider runtime_capabilities must not contain duplicate model ids.",
    }
    assert invalid_model_response.status_code == 200
    assert invalid_model_response.json()["field_errors"][0] == {
        "field": "providers[0].default_model_id",
        "message": "Provider default_model_id must be in supported_model_ids.",
    }
    assert invalid_git_response.status_code == 200
    assert invalid_git_response.json()["field_errors"][0] == {
        "field": "delivery_channels[0].credential_ref",
        "message": "git_auto_delivery requires credential_ref",
    }
    assert system_template.status_code == 200
    assert system_template.json()["field_errors"][0] == {
        "field": "pipeline_templates[0].template_source",
        "message": (
            "System templates cannot be overwritten by configuration package import."
        ),
    }

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        provider = session.get(ProviderModel, "provider-deepseek")
        channel = session.get(DeliveryChannelModel, "delivery-default")
        system = session.get(PipelineTemplateModel, "template-feature")
        user_count = (
            session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_source == "user_template")
            .count()
        )
    assert provider is not None
    assert provider.default_model_id == "deepseek-chat"
    assert channel is not None
    assert channel.delivery_mode.value == "demo_delivery"
    assert system is not None
    assert system.name != "Imported package flow"
    assert user_count == 0


def test_configuration_package_import_missing_project_returns_unified_404(
    tmp_path: Path,
) -> None:
    app = build_configuration_package_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/project-missing/configuration-package/import",
            json=package_payload(scope_project_id="project-missing"),
            headers={
                "X-Request-ID": "req-config-missing",
                "X-Correlation-ID": "corr-config-missing",
            },
        )

    assert_error(
        response,
        status_code=404,
        error_code="not_found",
        message="Project was not found.",
        request_id="req-config-missing",
        correlation_id="corr-config-missing",
    )

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "configuration_package.import.rejected",
                AuditLogEntryModel.request_id == "req-config-missing",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.REJECTED


def test_configuration_package_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_configuration_package_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    export_route = paths["/api/projects/{projectId}/configuration-package/export"]["get"]
    import_route = paths["/api/projects/{projectId}/configuration-package/import"]["post"]

    assert "requestBody" not in export_route
    assert (
        export_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ConfigurationPackageExport"
    )
    assert (
        import_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ConfigurationPackageImportRequest"
    )
    assert (
        import_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ConfigurationPackageImportResult"
    )
    for operation in [export_route, import_route]:
        assert operation["parameters"] == [
            {
                "name": "projectId",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "title": "Projectid"},
            }
        ]
        assert set(operation["responses"]) == {"200", "404", "422", "500"}
        for status_code in ["404", "422", "500"]:
            assert (
                operation["responses"][status_code]["content"]["application/json"][
                    "schema"
                ]["$ref"]
                == "#/components/schemas/ErrorResponse"
            )

    assert "ConfigurationPackageImportResult" in schemas
    result_properties = schemas["ConfigurationPackageImportResult"]["properties"]
    assert set(result_properties) == {
        "package_id",
        "package_schema_version",
        "summary",
        "changed_objects",
        "field_errors",
    }
    assert "ConfigurationPackageChangedObject" in schemas
    assert "ConfigurationPackageFieldError" in schemas
    changed_properties = schemas["ConfigurationPackageChangedObject"]["properties"]
    assert "config_version" in changed_properties
    assert "package_id" not in schemas["ConfigurationPackageImportRequest"]["properties"]
    assert "package_id" in schemas["ConfigurationPackageImportResult"]["properties"]
    forbidden_names = {
        "platform_runtime_settings",
        "compression_threshold_ratio",
        "system_prompt_assets",
        "runtime_snapshots",
        "audit_logs",
        "database_paths",
        "api_key",
    }
    for schema_name in [
        "ConfigurationPackageExport",
        "ConfigurationPackageImportRequest",
        "ConfigurationPackageImportResult",
    ]:
        schema_text = str(schemas[schema_name])
        for forbidden in forbidden_names:
            assert forbidden not in schema_text
