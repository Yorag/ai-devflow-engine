from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, DeliveryChannelModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.domain.enums import DeliveryMode
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


def build_delivery_channel_api_app(tmp_path: Path):
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


def git_payload(
    *,
    credential_ref: str | None = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
    repository_identifier: str | None = "acme/app",
    default_branch: str | None = "main",
) -> dict:
    return {
        "delivery_mode": "git_auto_delivery",
        "scm_provider_type": "github",
        "repository_identifier": repository_identifier,
        "default_branch": default_branch,
        "code_review_request_type": "pull_request",
        "credential_ref": credential_ref,
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


def test_project_delivery_channel_get_and_put_git_auto_delivery_audits(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_api_app(tmp_path)

    with TestClient(app) as client:
        get_default = client.get("/api/projects/project-default/delivery-channel")
        put_response = client.put(
            "/api/projects/project-default/delivery-channel",
            json=git_payload(),
            headers={
                "X-Request-ID": "req-delivery-save",
                "X-Correlation-ID": "corr-delivery-save",
            },
        )
        get_updated = client.get("/api/projects/project-default/delivery-channel")

    assert get_default.status_code == 200
    assert get_default.json()["delivery_mode"] == "demo_delivery"
    assert put_response.status_code == 200
    body = put_response.json()
    assert body["project_id"] == "project-default"
    assert body["delivery_channel_id"] == "delivery-default"
    assert body["delivery_mode"] == "git_auto_delivery"
    assert body["scm_provider_type"] == "github"
    assert body["repository_identifier"] == "acme/app"
    assert body["default_branch"] == "main"
    assert body["code_review_request_type"] == "pull_request"
    assert body["credential_ref"] == "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
    assert body["credential_status"] == "unbound"
    assert body["readiness_status"] == "unconfigured"
    assert body["readiness_message"] == (
        "DeliveryChannel readiness has not been validated."
    )
    assert get_updated.status_code == 200
    assert get_updated.json()["delivery_mode"] == "git_auto_delivery"

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.save",
                AuditLogEntryModel.request_id == "req-delivery-save",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert audit.correlation_id == "corr-delivery-save"
    assert "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN" in (audit.metadata_excerpt or "")
    assert "raw-secret" not in (audit.metadata_excerpt or "")


def test_project_delivery_channel_put_demo_clears_git_fields(tmp_path: Path) -> None:
    app = build_delivery_channel_api_app(tmp_path)

    with TestClient(app) as client:
        client.put("/api/projects/project-default/delivery-channel", json=git_payload())
        response = client.put(
            "/api/projects/project-default/delivery-channel",
            json={"delivery_mode": "demo_delivery"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["delivery_mode"] == "demo_delivery"
    assert body["scm_provider_type"] is None
    assert body["repository_identifier"] is None
    assert body["default_branch"] is None
    assert body["code_review_request_type"] is None
    assert body["credential_ref"] is None
    assert body["credential_status"] == "ready"
    assert body["readiness_status"] == "ready"

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, "delivery-default")
    assert channel is not None
    assert channel.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert channel.repository_identifier is None


def test_project_delivery_channel_put_demo_ignores_invalid_stale_credential(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.put(
            "/api/projects/project-default/delivery-channel",
            json={
                "delivery_mode": "demo_delivery",
                "scm_provider_type": "github",
                "repository_identifier": "acme/app",
                "default_branch": "main",
                "code_review_request_type": "pull_request",
                "credential_ref": "raw-stale-secret",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["delivery_mode"] == "demo_delivery"
    assert body["scm_provider_type"] is None
    assert body["repository_identifier"] is None
    assert body["default_branch"] is None
    assert body["code_review_request_type"] is None
    assert body["credential_ref"] is None


def test_project_delivery_channel_success_audit_blocks_legacy_raw_credential(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_api_app(tmp_path)

    with TestClient(app) as client:
        with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
            channel = session.get(DeliveryChannelModel, "delivery-default")
            assert channel is not None
            channel.credential_ref = "raw-legacy-secret"
            session.add(channel)
            session.commit()

        response = client.put(
            "/api/projects/project-default/delivery-channel",
            json=git_payload(),
            headers={
                "X-Request-ID": "req-delivery-sanitize",
                "X-Correlation-ID": "corr-delivery-sanitize",
            },
        )

    assert response.status_code == 200
    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.save",
                AuditLogEntryModel.request_id == "req-delivery-sanitize",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.metadata_excerpt is not None
    assert "[blocked:credential_ref]" in audit.metadata_excerpt
    assert "raw-legacy-secret" not in audit.metadata_excerpt


def test_project_delivery_channel_get_blocks_legacy_raw_credential(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_api_app(tmp_path)

    with TestClient(app) as client:
        with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
            channel = session.get(DeliveryChannelModel, "delivery-default")
            assert channel is not None
            channel.credential_ref = "raw-legacy-secret"
            session.add(channel)
            session.commit()

        response = client.get("/api/projects/project-default/delivery-channel")

    assert response.status_code == 200
    body = response.json()
    assert body["credential_ref"] == "[blocked:credential_ref]"
    assert "raw-legacy-secret" not in str(body)


def test_project_delivery_channel_routes_return_unified_errors_and_rejected_audit(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_api_app(tmp_path)

    with TestClient(app) as client:
        missing_project = client.get(
            "/api/projects/project-missing/delivery-channel",
            headers={
                "X-Request-ID": "req-delivery-missing",
                "X-Correlation-ID": "corr-delivery-missing",
            },
        )
        raw_key = client.put(
            "/api/projects/project-default/delivery-channel",
            json=git_payload(credential_ref="raw-secret-value"),
            headers={
                "X-Request-ID": "req-delivery-raw-key",
                "X-Correlation-ID": "corr-delivery-raw-key",
            },
        )
        missing_git_field = client.put(
            "/api/projects/project-default/delivery-channel",
            json={
                "delivery_mode": "git_auto_delivery",
                "scm_provider_type": "github",
                "repository_identifier": "acme/app",
                "default_branch": "main",
                "credential_ref": "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
            },
            headers={
                "X-Request-ID": "req-delivery-shape",
                "X-Correlation-ID": "corr-delivery-shape",
            },
        )
        whitespace_git_field = client.put(
            "/api/projects/project-default/delivery-channel",
            json=git_payload(repository_identifier="  ", default_branch=" \t "),
            headers={
                "X-Request-ID": "req-delivery-whitespace",
                "X-Correlation-ID": "corr-delivery-whitespace",
            },
        )

    assert_error(
        missing_project,
        status_code=404,
        error_code="not_found",
        message="Project was not found.",
        request_id="req-delivery-missing",
        correlation_id="corr-delivery-missing",
    )
    assert_error(
        raw_key,
        status_code=422,
        error_code="config_invalid_value",
        message="DeliveryChannel credential_ref must use an env: credential reference.",
        request_id="req-delivery-raw-key",
        correlation_id="corr-delivery-raw-key",
    )
    assert_error(
        missing_git_field,
        status_code=422,
        error_code="config_invalid_value",
        message="git_auto_delivery requires code_review_request_type",
        request_id="req-delivery-shape",
        correlation_id="corr-delivery-shape",
    )
    assert_error(
        whitespace_git_field,
        status_code=422,
        error_code="config_invalid_value",
        message="git_auto_delivery requires default_branch, repository_identifier",
        request_id="req-delivery-whitespace",
        correlation_id="corr-delivery-whitespace",
    )

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        rejected = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.save.rejected",
                AuditLogEntryModel.request_id == "req-delivery-raw-key",
            )
            .one_or_none()
        )
        missing_field_rejected = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.save.rejected",
                AuditLogEntryModel.request_id == "req-delivery-shape",
            )
            .one_or_none()
        )
        whitespace_rejected = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.save.rejected",
                AuditLogEntryModel.request_id == "req-delivery-whitespace",
            )
            .one_or_none()
        )
    assert rejected is not None
    assert rejected.result is AuditResult.REJECTED
    assert "raw-secret-value" not in (rejected.metadata_excerpt or "")
    assert missing_field_rejected is not None
    assert missing_field_rejected.result is AuditResult.REJECTED
    assert "code_review_request_type" in (
        missing_field_rejected.metadata_excerpt or ""
    )
    assert whitespace_rejected is not None
    assert whitespace_rejected.result is AuditResult.REJECTED
    assert "repository_identifier" in (whitespace_rejected.metadata_excerpt or "")
    assert "default_branch" in (whitespace_rejected.metadata_excerpt or "")


def test_project_delivery_channel_routes_are_documented_in_openapi(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]
    route = paths["/api/projects/{projectId}/delivery-channel"]
    get_channel = route["get"]
    put_channel = route["put"]

    assert set(get_channel["responses"]) == {"200", "404", "422", "500"}
    assert set(put_channel["responses"]) == {"200", "404", "422", "500"}
    assert (
        get_channel["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProjectDeliveryChannelDetailProjection"
    )
    assert (
        put_channel["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProjectDeliveryChannelUpdateRequest"
    )
    assert (
        put_channel["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProjectDeliveryChannelDetailProjection"
    )
    for operation in [get_channel, put_channel]:
        assert operation["parameters"] == [
            {
                "name": "projectId",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "title": "Projectid"},
            }
        ]
        assert (
            operation["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
        assert (
            operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    assert "ProjectDeliveryChannelUpdateRequest" in schemas
    update_properties = schemas["ProjectDeliveryChannelUpdateRequest"]["properties"]
    assert "credential_status" not in update_properties
    assert "readiness_status" not in update_properties
    assert "last_validated_at" not in update_properties
    assert "api_key" not in update_properties
    detail_properties = schemas["ProjectDeliveryChannelDetailProjection"]["properties"]
    assert "api_key" not in detail_properties
