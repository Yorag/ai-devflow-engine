from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


def build_provider_api_app(tmp_path: Path):
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


def provider_payload(
    *,
    display_name: str | None = "Team compatible model",
    protocol_type: str | None = None,
    base_url: str = "https://provider.example.test/v1",
    api_key_ref: str | None = "env:AI_DEVFLOW_CREDENTIAL_TEAM_PROVIDER_API_KEY",
    default_model_id: str = "team-chat",
    supported_model_ids: list[str] | None = None,
    runtime_capabilities: list[dict] | None = None,
) -> dict:
    return {
        "display_name": display_name,
        "protocol_type": protocol_type,
        "base_url": base_url,
        "api_key_ref": api_key_ref,
        "default_model_id": default_model_id,
        "supported_model_ids": supported_model_ids or ["team-chat"],
        "runtime_capabilities": runtime_capabilities or [{"model_id": "team-chat"}],
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


def test_provider_routes_create_get_patch_custom_and_audit(tmp_path: Path) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/providers",
            json=provider_payload(),
            headers={
                "X-Request-ID": "req-provider-create",
                "X-Correlation-ID": "corr-provider-create",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()

        get_response = client.get(f"/api/providers/{created['provider_id']}")
        patch_response = client.patch(
            f"/api/providers/{created['provider_id']}",
            json=provider_payload(
                display_name="Renamed team provider",
                base_url="https://provider.example.test/renamed",
            ),
            headers={
                "X-Request-ID": "req-provider-patch-custom",
                "X-Correlation-ID": "corr-provider-patch-custom",
            },
        )

    assert created["provider_id"].startswith("provider-custom-")
    assert created["provider_source"] == "custom"
    assert created["protocol_type"] == "openai_completions_compatible"
    assert created["runtime_capabilities"][0]["max_output_tokens"] == 4096
    assert "api_key" not in created
    assert get_response.status_code == 200
    assert get_response.json()["provider_id"] == created["provider_id"]
    assert patch_response.status_code == 200
    assert patch_response.json()["display_name"] == "Renamed team provider"

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audits = {
            (row.action, row.request_id): row
            for row in session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action.in_(
                    ["provider.create_custom", "provider.patch_custom"]
                )
            )
            .all()
        }

    assert audits[("provider.create_custom", "req-provider-create")].result is (
        AuditResult.SUCCEEDED
    )
    assert audits[("provider.patch_custom", "req-provider-patch-custom")].result is (
        AuditResult.SUCCEEDED
    )
    assert audits[
        ("provider.patch_custom", "req-provider-patch-custom")
    ].correlation_id == "corr-provider-patch-custom"
    assert "raw-secret" not in (
        audits[("provider.create_custom", "req-provider-create")].metadata_excerpt
        or ""
    )


def test_provider_routes_patch_builtin_runtime_config_and_preserve_identity(
    tmp_path: Path,
) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.patch(
            "/api/providers/provider-deepseek",
            json=provider_payload(
                display_name=None,
                base_url="https://api.deepseek.example/v1",
                api_key_ref="env:DEEPSEEK_ROTATED_API_KEY",
                default_model_id="deepseek-reasoner",
                supported_model_ids=["deepseek-chat", "deepseek-reasoner"],
                runtime_capabilities=[
                    {"model_id": "deepseek-chat"},
                    {"model_id": "deepseek-reasoner", "supports_native_reasoning": True},
                ],
            ),
            headers={
                "X-Request-ID": "req-provider-patch-builtin",
                "X-Correlation-ID": "corr-provider-patch-builtin",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_id"] == "provider-deepseek"
    assert body["display_name"] == "DeepSeek"
    assert body["provider_source"] == "builtin"
    assert body["protocol_type"] == "openai_completions_compatible"
    assert body["base_url"] == "https://api.deepseek.example/v1"
    assert body["api_key_ref"] == "env:DEEPSEEK_ROTATED_API_KEY"
    assert body["default_model_id"] == "deepseek-reasoner"

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "provider.patch_builtin_runtime_config",
                AuditLogEntryModel.request_id == "req-provider-patch-builtin",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert audit.metadata_excerpt is not None
    assert "env:DEEPSEEK_ROTATED_API_KEY" in audit.metadata_excerpt
    assert "blocked:sensitive_field" not in audit.metadata_excerpt
    assert "https://api.deepseek.example/v1" not in audit.metadata_excerpt
    assert "DeepSeek" not in audit.metadata_excerpt


def test_provider_routes_return_unified_errors_for_invalid_commands(
    tmp_path: Path,
) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        missing = client.get(
            "/api/providers/provider-missing",
            headers={
                "X-Request-ID": "req-provider-missing",
                "X-Correlation-ID": "corr-provider-missing",
            },
        )
        identity_change = client.patch(
            "/api/providers/provider-deepseek",
            json=provider_payload(
                display_name="Renamed DeepSeek",
                protocol_type="volcengine_native",
            ),
            headers={
                "X-Request-ID": "req-provider-identity",
                "X-Correlation-ID": "corr-provider-identity",
            },
        )
        raw_key = client.post(
            "/api/providers",
            json=provider_payload(api_key_ref="raw-secret-value"),
            headers={
                "X-Request-ID": "req-provider-raw-key",
                "X-Correlation-ID": "corr-provider-raw-key",
            },
        )
        disallowed_env = client.post(
            "/api/providers",
            json=provider_payload(api_key_ref="env:PATH"),
            headers={
                "X-Request-ID": "req-provider-path-key",
                "X-Correlation-ID": "corr-provider-path-key",
            },
        )
        strict_bool = client.post(
            "/api/providers",
            json=provider_payload(
                runtime_capabilities=[
                    {
                        "model_id": "team-chat",
                        "supports_tool_calling": "true",
                    }
                ]
            ),
            headers={
                "X-Request-ID": "req-provider-strict-bool",
                "X-Correlation-ID": "corr-provider-strict-bool",
            },
        )

    assert_error(
        missing,
        status_code=404,
        error_code="not_found",
        message="Provider was not found.",
        request_id="req-provider-missing",
        correlation_id="corr-provider-missing",
    )
    assert_error(
        identity_change,
        status_code=409,
        error_code="validation_error",
        message="Built-in Provider identity fields cannot be modified.",
        request_id="req-provider-identity",
        correlation_id="corr-provider-identity",
    )
    assert_error(
        raw_key,
        status_code=422,
        error_code="config_invalid_value",
        message="Provider api_key_ref must use an env: credential reference.",
        request_id="req-provider-raw-key",
        correlation_id="corr-provider-raw-key",
    )
    assert_error(
        disallowed_env,
        status_code=422,
        error_code="config_invalid_value",
        message="Provider api_key_ref must use an env: credential reference.",
        request_id="req-provider-path-key",
        correlation_id="corr-provider-path-key",
    )
    assert_error(
        strict_bool,
        status_code=422,
        error_code="validation_error",
        message="Request validation failed.",
        request_id="req-provider-strict-bool",
        correlation_id="corr-provider-strict-bool",
    )

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        rejected = [
            row
            for row in session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.result == AuditResult.REJECTED)
            .all()
        ]
    actions = {row.action for row in rejected}
    assert "provider.patch_builtin_runtime_config.rejected" in actions
    assert "provider.create_custom.rejected" in actions
    assert all("raw-secret-value" not in (row.metadata_excerpt or "") for row in rejected)


def test_provider_command_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    assert "/api/providers" in paths
    assert "/api/providers/{providerId}" in paths
    create_provider = paths["/api/providers"]["post"]
    get_provider = paths["/api/providers/{providerId}"]["get"]
    patch_provider = paths["/api/providers/{providerId}"]["patch"]

    assert set(create_provider["responses"]) == {"201", "422", "500"}
    assert set(get_provider["responses"]) == {"200", "404", "422", "500"}
    assert set(patch_provider["responses"]) == {"200", "404", "409", "422", "500"}
    assert get_provider["parameters"] == [
        {
            "name": "providerId",
            "in": "path",
            "required": True,
            "schema": {"type": "string", "title": "Providerid"},
        }
    ]
    assert (
        create_provider["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProviderWriteRequest"
    )
    assert (
        create_provider["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProviderRead"
    )
    assert (
        get_provider["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProviderRead"
    )
    assert (
        patch_provider["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProviderWriteRequest"
    )
    assert (
        patch_provider["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProviderRead"
    )
    for operation in [create_provider, get_provider, patch_provider]:
        assert (
            operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    for operation in [get_provider, patch_provider]:
        assert (
            operation["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    assert (
        patch_provider["responses"]["409"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )
    assert "ProviderWriteRequest" in schemas
    assert "provider_id" not in schemas["ProviderWriteRequest"]["properties"]
    assert "provider_source" not in schemas["ProviderWriteRequest"]["properties"]
    assert "api_key" not in schemas["ProviderWriteRequest"]["properties"]
    assert "api_key" not in schemas["ProviderRead"]["properties"]
