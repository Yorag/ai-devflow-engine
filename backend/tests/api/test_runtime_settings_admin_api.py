from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, PlatformRuntimeSettingsModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


def build_runtime_settings_api_app(tmp_path: Path):
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


def assert_error(
    response,
    *,
    status_code: int,
    error_code: str,
    message_contains: str,
    request_id: str,
    correlation_id: str,
) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["error_code"] == error_code
    assert message_contains in body["message"]
    assert body["request_id"] == request_id
    assert body["correlation_id"] == correlation_id


def test_get_runtime_settings_initializes_persisted_defaults_and_audits(
    tmp_path: Path,
) -> None:
    app = build_runtime_settings_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/runtime-settings",
            headers={
                "X-Request-ID": "req-runtime-get",
                "X-Correlation-ID": "corr-runtime-get",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["settings_id"] == "platform-runtime-settings"
    assert body["version"]["config_version"] == "runtime-settings-v1"
    assert body["agent_limits"]["max_react_iterations_per_stage"] == 30
    assert body["internal_model_bindings"]["context_compression"]["model_id"] == (
        "deepseek-chat"
    )
    assert body["context_limits"]["compression_threshold_ratio"] == 0.8
    assert "compression_prompt" not in str(body)

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        row = session.get(PlatformRuntimeSettingsModel, "platform-runtime-settings")
    assert row is not None
    assert row.config_version == "runtime-settings-v1"

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "runtime_settings.initialize",
                AuditLogEntryModel.request_id == "req-runtime-get",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert audit.correlation_id == "corr-runtime-get"


def test_put_runtime_settings_updates_partial_groups_and_records_audit(
    tmp_path: Path,
) -> None:
    app = build_runtime_settings_api_app(tmp_path)

    with TestClient(app) as client:
        current = client.get("/api/runtime-settings").json()
        response = client.put(
            "/api/runtime-settings",
            json={
                "expected_config_version": current["version"]["config_version"],
                "agent_limits": {
                    **current["agent_limits"],
                    "max_tool_calls_per_stage": 70,
                },
                "internal_model_bindings": {
                    **current["internal_model_bindings"],
                    "context_compression": {
                        "provider_id": "provider-deepseek",
                        "model_id": "deepseek-reasoner",
                        "model_parameters": {"temperature": 0},
                        "source_config_version": current["version"]["config_version"],
                    },
                },
                "context_limits": {
                    **current["context_limits"],
                    "compression_threshold_ratio": 0.75,
                },
            },
            headers={
                "X-Request-ID": "req-runtime-put",
                "X-Correlation-ID": "corr-runtime-put",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["version"]["config_version"] == "runtime-settings-v2"
    assert body["agent_limits"]["max_tool_calls_per_stage"] == 70
    assert body["internal_model_bindings"]["context_compression"]["model_id"] == (
        "deepseek-reasoner"
    )
    assert body["context_limits"]["compression_threshold_ratio"] == 0.75

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "runtime_settings.update",
                AuditLogEntryModel.request_id == "req-runtime-put",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert "max_tool_calls_per_stage" in (audit.metadata_excerpt or "")
    assert "compression_prompt" not in (audit.metadata_excerpt or "")


def test_put_runtime_settings_returns_unified_errors_for_conflict_hard_limit_and_invalid_update(
    tmp_path: Path,
) -> None:
    app = build_runtime_settings_api_app(tmp_path)

    with TestClient(app) as client:
        current = client.get("/api/runtime-settings").json()
        conflict = client.put(
            "/api/runtime-settings",
            json={
                "expected_config_version": "runtime-settings-v0",
                "agent_limits": current["agent_limits"],
            },
            headers={
                "X-Request-ID": "req-runtime-conflict",
                "X-Correlation-ID": "corr-runtime-conflict",
            },
        )
        hard_limit_payload = {
            **current["agent_limits"],
            "max_react_iterations_per_stage": 51,
        }
        hard_limit = client.put(
            "/api/runtime-settings",
            json={
                "expected_config_version": current["version"]["config_version"],
                "agent_limits": hard_limit_payload,
            },
            headers={
                "X-Request-ID": "req-runtime-hard-limit",
                "X-Correlation-ID": "corr-runtime-hard-limit",
            },
        )
        empty = client.put(
            "/api/runtime-settings",
            json={
                "expected_config_version": current["version"]["config_version"],
            },
            headers={
                "X-Request-ID": "req-runtime-empty",
                "X-Correlation-ID": "corr-runtime-empty",
            },
        )

    assert_error(
        conflict,
        status_code=409,
        error_code="config_version_conflict",
        message_contains="expected_config_version",
        request_id="req-runtime-conflict",
        correlation_id="corr-runtime-conflict",
    )
    assert_error(
        hard_limit,
        status_code=422,
        error_code="config_hard_limit_exceeded",
        message_contains="agent_limits.max_react_iterations_per_stage",
        request_id="req-runtime-hard-limit",
        correlation_id="corr-runtime-hard-limit",
    )
    assert_error(
        empty,
        status_code=422,
        error_code="config_invalid_value",
        message_contains="must include at least one settings group",
        request_id="req-runtime-empty",
        correlation_id="corr-runtime-empty",
    )

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        rejected_actions = [
            row
            for row in session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "runtime_settings.update.rejected")
            .all()
        ]
    assert len(rejected_actions) == 3
    assert {row.result for row in rejected_actions} == {AuditResult.REJECTED}


def test_put_runtime_settings_maps_schema_invalid_values_to_config_invalid_value(
    tmp_path: Path,
) -> None:
    app = build_runtime_settings_api_app(tmp_path)

    with TestClient(app) as client:
        current = client.get("/api/runtime-settings").json()
        response = client.put(
            "/api/runtime-settings",
            json={
                "expected_config_version": current["version"]["config_version"],
                "context_limits": {
                    **current["context_limits"],
                    "compression_threshold_ratio": 1,
                },
            },
            headers={
                "X-Request-ID": "req-runtime-invalid-ratio",
                "X-Correlation-ID": "corr-runtime-invalid-ratio",
            },
        )

    assert_error(
        response,
        status_code=422,
        error_code="config_invalid_value",
        message_contains="Request validation failed.",
        request_id="req-runtime-invalid-ratio",
        correlation_id="corr-runtime-invalid-ratio",
    )


def test_put_runtime_settings_maps_storage_unavailable_to_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService

    app = build_runtime_settings_api_app(tmp_path)
    original_update = PlatformRuntimeSettingsService.update_settings

    def fail_update(self, body, *, trace_context):
        raise self._storage_error()

    monkeypatch.setattr(PlatformRuntimeSettingsService, "update_settings", fail_update)

    with TestClient(app) as client:
        current = client.get("/api/runtime-settings").json()
        response = client.put(
            "/api/runtime-settings",
            json={
                "expected_config_version": current["version"]["config_version"],
                "agent_limits": {
                    **current["agent_limits"],
                    "max_tool_calls_per_stage": 70,
                },
            },
            headers={
                "X-Request-ID": "req-runtime-storage",
                "X-Correlation-ID": "corr-runtime-storage",
            },
        )

    monkeypatch.setattr(PlatformRuntimeSettingsService, "update_settings", original_update)

    assert_error(
        response,
        status_code=503,
        error_code="config_storage_unavailable",
        message_contains="PlatformRuntimeSettings storage is unavailable.",
        request_id="req-runtime-storage",
        correlation_id="corr-runtime-storage",
    )


def test_runtime_settings_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_runtime_settings_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    assert "/api/runtime-settings" in paths
    get_route = paths["/api/runtime-settings"]["get"]
    put_route = paths["/api/runtime-settings"]["put"]

    assert "requestBody" not in get_route
    assert (
        get_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PlatformRuntimeSettingsRead"
    )
    assert (
        put_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PlatformRuntimeSettingsUpdate"
    )
    assert (
        put_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PlatformRuntimeSettingsRead"
    )
    assert set(get_route["responses"]) == {"200", "422", "500", "503"}
    assert set(put_route["responses"]) == {"200", "409", "422", "500", "503"}
    for operation in [get_route, put_route]:
        for status_code in set(operation["responses"]) - {"200"}:
            assert (
                operation["responses"][status_code]["content"]["application/json"][
                    "schema"
                ]["$ref"]
                == "#/components/schemas/ErrorResponse"
            )

    for schema_name in [
        "PlatformRuntimeSettingsRead",
        "PlatformRuntimeSettingsUpdate",
        "PlatformRuntimeSettingsVersion",
        "PlatformHardLimits",
        "AgentRuntimeLimits",
        "InternalModelBindingSelection",
        "InternalModelBindings",
        "ProviderCallPolicy",
        "ContextLimits",
        "LogPolicy",
    ]:
        assert schema_name in schemas

    forbidden = {
        "compression_prompt",
        "platform_runtime_root",
        "control.db",
        "runtime_snapshot",
        "configuration_package",
        "api_key",
        "token",
        "password",
        "cookie",
    }
    schema_text = str(schemas["PlatformRuntimeSettingsRead"]) + str(
        schemas["PlatformRuntimeSettingsUpdate"]
    )
    assert "internal_model_bindings" in schema_text
    for name in forbidden:
        assert name not in schema_text
