from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProviderModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.domain.enums import ProviderProtocolType, ProviderSource
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


MASKED_API_KEY_REF = "[configured:api_key]"
RAW_PROVIDER_API_KEY = "sk-team-provider-api-key"


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
    api_key_ref: str | None = RAW_PROVIDER_API_KEY,
    default_model_id: str = "team-chat",
    supported_model_ids: list[str] | None = None,
    runtime_capabilities: list[dict] | None = None,
    is_enabled: bool = True,
) -> dict:
    return {
        "display_name": display_name,
        "protocol_type": protocol_type,
        "base_url": base_url,
        "api_key_ref": api_key_ref,
        "default_model_id": default_model_id,
        "supported_model_ids": supported_model_ids or ["team-chat"],
        "runtime_capabilities": runtime_capabilities or [{"model_id": "team-chat"}],
        "is_enabled": is_enabled,
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
    assert created["api_key_ref"] == MASKED_API_KEY_REF
    assert created["is_enabled"] is True
    assert created["runtime_capabilities"][0]["max_output_tokens"] == 4096
    assert "api_key" not in created
    assert get_response.status_code == 200
    assert get_response.json()["provider_id"] == created["provider_id"]
    assert get_response.json()["api_key_ref"] == MASKED_API_KEY_REF
    assert patch_response.status_code == 200
    assert patch_response.json()["display_name"] == "Renamed team provider"
    assert patch_response.json()["api_key_ref"] == MASKED_API_KEY_REF
    assert patch_response.json()["is_enabled"] is True

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        saved = session.get(ProviderModel, created["provider_id"])
    assert saved is not None
    assert saved.api_key_ref == RAW_PROVIDER_API_KEY

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
    assert RAW_PROVIDER_API_KEY not in (
        audits[("provider.create_custom", "req-provider-create")].metadata_excerpt
        or ""
    )
    assert MASKED_API_KEY_REF in (
        audits[("provider.create_custom", "req-provider-create")].metadata_excerpt
        or ""
    )


def test_provider_routes_create_custom_volcengine_provider(tmp_path: Path) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/providers",
            json=provider_payload(
                display_name="Team Volcengine",
                protocol_type="volcengine_native",
                base_url="https://ark.example.test/api/v3",
                api_key_ref="sk-volcengine-team-api-key",
                default_model_id="doubao-team",
                supported_model_ids=["doubao-team"],
                runtime_capabilities=[{"model_id": "doubao-team"}],
            ),
        )

    assert response.status_code == 201
    body = response.json()
    assert body["provider_id"].startswith("provider-custom-")
    assert body["provider_source"] == "custom"
    assert body["display_name"] == "Team Volcengine"
    assert body["protocol_type"] == "volcengine_native"


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
                api_key_ref="sk-deepseek-rotated-api-key",
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
    assert body["is_enabled"] is True
    assert body["base_url"] == "https://api.deepseek.example/v1"
    assert body["api_key_ref"] == MASKED_API_KEY_REF
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
    assert "sk-deepseek-rotated-api-key" not in audit.metadata_excerpt
    assert MASKED_API_KEY_REF in audit.metadata_excerpt
    assert "[blocked:sensitive_field]" in audit.metadata_excerpt
    assert "https://api.deepseek.example/v1" not in audit.metadata_excerpt
    assert "DeepSeek" not in audit.metadata_excerpt


def test_provider_routes_patch_builtin_display_name(tmp_path: Path) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.patch(
            "/api/providers/provider-deepseek",
            json=provider_payload(
                display_name="Team DeepSeek Gateway",
                base_url="https://api.deepseek.example/v1",
                api_key_ref="sk-deepseek-display-name-api-key",
                default_model_id="deepseek-chat",
                supported_model_ids=["deepseek-chat"],
                runtime_capabilities=[{"model_id": "deepseek-chat"}],
            ),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_id"] == "provider-deepseek"
    assert body["display_name"] == "Team DeepSeek Gateway"
    assert body["protocol_type"] == "openai_completions_compatible"


def test_provider_routes_list_only_configured_providers_and_toggle_enabled(
    tmp_path: Path,
) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        initial_list = client.get("/api/providers")
        activate_response = client.patch(
            "/api/providers/provider-deepseek",
            json=provider_payload(
                display_name=None,
                base_url="https://api.deepseek.com",
                api_key_ref="sk-deepseek-provider-api-key",
                default_model_id="deepseek-chat",
                supported_model_ids=["deepseek-chat", "deepseek-reasoner"],
                runtime_capabilities=[
                    {"model_id": "deepseek-chat"},
                    {"model_id": "deepseek-reasoner", "supports_native_reasoning": True},
                ],
            ),
        )
        configured_list = client.get("/api/providers")
        disable_response = client.patch(
            "/api/providers/provider-deepseek",
            json=provider_payload(
                display_name=None,
                base_url="https://api.deepseek.com",
                api_key_ref="sk-deepseek-provider-api-key",
                default_model_id="deepseek-chat",
                supported_model_ids=["deepseek-chat", "deepseek-reasoner"],
                runtime_capabilities=[
                    {"model_id": "deepseek-chat"},
                    {"model_id": "deepseek-reasoner", "supports_native_reasoning": True},
                ],
                is_enabled=False,
            ),
        )

    assert initial_list.status_code == 200
    assert initial_list.json() == []
    assert activate_response.status_code == 200
    assert activate_response.json()["is_enabled"] is True
    assert [provider["provider_id"] for provider in configured_list.json()] == [
        "provider-deepseek"
    ]
    assert disable_response.status_code == 200
    assert disable_response.json()["is_enabled"] is False


def test_provider_routes_delete_custom_and_deconfigure_builtin(tmp_path: Path) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        created_response = client.post(
            "/api/providers",
            json=provider_payload(),
            headers={
                "X-Request-ID": "req-provider-create-delete",
                "X-Correlation-ID": "corr-provider-create-delete",
            },
        )
        created = created_response.json()
        delete_custom_response = client.delete(
            f"/api/providers/{created['provider_id']}",
            headers={
                "X-Request-ID": "req-provider-delete-custom",
                "X-Correlation-ID": "corr-provider-delete-custom",
            },
        )
        get_deleted_custom_response = client.get(
            f"/api/providers/{created['provider_id']}",
        )

        activate_builtin_response = client.patch(
            "/api/providers/provider-deepseek",
            json=provider_payload(
                display_name=None,
                base_url="https://api.deepseek.com",
                api_key_ref="sk-deepseek-provider-api-key",
                default_model_id="deepseek-chat",
                supported_model_ids=["deepseek-chat"],
                runtime_capabilities=[{"model_id": "deepseek-chat"}],
            ),
        )
        delete_builtin_response = client.delete(
            "/api/providers/provider-deepseek",
            headers={
                "X-Request-ID": "req-provider-delete-builtin",
                "X-Correlation-ID": "corr-provider-delete-builtin",
            },
        )
        list_after_builtin_delete = client.get("/api/providers")
        get_deconfigured_builtin = client.get("/api/providers/provider-deepseek")

    assert created_response.status_code == 201
    assert delete_custom_response.status_code == 204
    assert delete_custom_response.text == ""
    assert get_deleted_custom_response.status_code == 404
    assert activate_builtin_response.status_code == 200
    assert delete_builtin_response.status_code == 204
    assert list_after_builtin_delete.status_code == 200
    assert [
        provider["provider_id"] for provider in list_after_builtin_delete.json()
    ] == []
    assert get_deconfigured_builtin.status_code == 200
    assert get_deconfigured_builtin.json()["provider_id"] == "provider-deepseek"
    assert get_deconfigured_builtin.json()["is_enabled"] is False

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audits = {
            (row.action, row.request_id): row
            for row in session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action.in_(
                    ["provider.delete_custom", "provider.deconfigure_builtin"]
                )
            )
            .all()
        }

    assert audits[("provider.delete_custom", "req-provider-delete-custom")].result is (
        AuditResult.SUCCEEDED
    )
    assert audits[
        ("provider.deconfigure_builtin", "req-provider-delete-builtin")
    ].result is AuditResult.SUCCEEDED


def test_provider_routes_mask_direct_api_key_in_read_projection(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime

    app = build_provider_api_app(tmp_path)
    now = datetime(2026, 5, 2, 13, 0, 0, tzinfo=UTC)
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProviderModel(
                provider_id="provider-custom-legacy",
                display_name="Legacy custom provider",
                provider_source=ProviderSource.CUSTOM,
                protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
                base_url="https://provider.example.test/v1",
                api_key_ref="sk-legacy-provider-secret",
                default_model_id="legacy-chat",
                supported_model_ids=["legacy-chat"],
                runtime_capabilities=[
                    {
                        "model_id": "legacy-chat",
                        "context_window_tokens": 128000,
                        "max_output_tokens": 4096,
                        "supports_tool_calling": False,
                        "supports_structured_output": False,
                        "supports_native_reasoning": False,
                    }
                ],
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    with TestClient(app) as client:
        detail_response = client.get("/api/providers/provider-custom-legacy")
        list_response = client.get("/api/providers")

    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["api_key_ref"] == MASKED_API_KEY_REF
    assert "sk-legacy-provider-secret" not in str(detail_body)

    assert list_response.status_code == 200
    legacy_provider = next(
        item
        for item in list_response.json()
        if item["provider_id"] == "provider-custom-legacy"
    )
    assert legacy_provider["api_key_ref"] == MASKED_API_KEY_REF
    assert "sk-legacy-provider-secret" not in str(list_response.json())


def test_provider_routes_preserve_existing_api_key_when_projection_mask_is_submitted(
    tmp_path: Path,
) -> None:
    app = build_provider_api_app(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/providers",
            json=provider_payload(api_key_ref="sk-existing-provider-secret"),
        )
        created = create_response.json()
        patch_response = client.patch(
            f"/api/providers/{created['provider_id']}",
            json=provider_payload(
                display_name="Provider renamed without key edit",
                base_url="https://provider.example.test/renamed",
                api_key_ref=created["api_key_ref"],
            ),
        )

    assert create_response.status_code == 201
    assert created["api_key_ref"] == MASKED_API_KEY_REF
    assert patch_response.status_code == 200
    assert patch_response.json()["api_key_ref"] == MASKED_API_KEY_REF
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        saved = session.get(ProviderModel, created["provider_id"])
    assert saved is not None
    assert saved.api_key_ref == "sk-existing-provider-secret"


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
                protocol_type="volcengine_native",
            ),
            headers={
                "X-Request-ID": "req-provider-identity",
                "X-Correlation-ID": "corr-provider-identity",
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
        message="Built-in Provider protocol_type cannot be modified.",
        request_id="req-provider-identity",
        correlation_id="corr-provider-identity",
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
    delete_provider = paths["/api/providers/{providerId}"]["delete"]

    assert set(create_provider["responses"]) == {"201", "422", "500"}
    assert set(get_provider["responses"]) == {"200", "404", "422", "500"}
    assert set(patch_provider["responses"]) == {"200", "404", "409", "422", "500"}
    assert set(delete_provider["responses"]) == {"204", "404", "422", "500"}
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
    assert delete_provider["responses"]["204"]["description"] == "Successful Response"
    for operation in [create_provider, get_provider, patch_provider, delete_provider]:
        assert (
            operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    for operation in [get_provider, patch_provider, delete_provider]:
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
    assert "is_enabled" in schemas["ProviderWriteRequest"]["properties"]
    assert "is_enabled" in schemas["ProviderRead"]["properties"]
