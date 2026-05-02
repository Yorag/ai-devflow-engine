from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, DeliveryChannelModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ScmProviderType,
)
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


SAFE_CREDENTIAL_REF = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
RAW_CREDENTIAL_REF = "raw-secret-value"
SECRET_VALUE = "super-secret-token"
MISSING_ENV_CREDENTIAL_MESSAGE = (
    "DeliveryChannel credential_ref does not resolve to an available credential."
)


def build_delivery_channel_validate_api_app(tmp_path: Path):
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
    credential_ref: str | None = SAFE_CREDENTIAL_REF,
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


def app_log_lines(app) -> list[dict]:
    log_path = app.state.environment_settings.platform_runtime_root / "logs" / "app.jsonl"
    assert log_path.exists()
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_project_delivery_channel_validate_returns_demo_ready_and_observability(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_validate_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/project-default/delivery-channel/validate",
            headers={
                "X-Request-ID": "req-delivery-validate",
                "X-Correlation-ID": "corr-delivery-validate",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["readiness_status"] == "ready"
    assert body["readiness_message"] == "demo_delivery is ready."
    assert body["credential_status"] == "ready"
    assert body["validated_fields"] == ["delivery_mode"]
    assert body["validated_at"]
    assert "credential_ref" not in body
    assert "last_validated_at" not in body

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, "delivery-default")
    assert channel is not None
    assert channel.readiness_status is DeliveryReadinessStatus.READY
    assert channel.credential_status is CredentialStatus.READY
    assert channel.readiness_message == "demo_delivery is ready."
    assert channel.last_validated_at is not None

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.validate",
                AuditLogEntryModel.request_id == "req-delivery-validate",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert audit.correlation_id == "corr-delivery-validate"
    assert "demo_delivery is ready." in (audit.metadata_excerpt or "")
    assert RAW_CREDENTIAL_REF not in (audit.metadata_excerpt or "")

    log_entries = [
        line
        for line in app_log_lines(app)
        if line["message"] == "DeliveryChannel readiness validation result computed."
    ]
    assert len(log_entries) == 1
    log_entry = log_entries[0]
    assert log_entry["category"] == "delivery"
    assert log_entry["source"] == "services.delivery_channels"
    assert log_entry["request_id"] == "req-delivery-validate"
    assert log_entry["correlation_id"] == "corr-delivery-validate"
    assert "demo_delivery is ready." in log_entry["payload_excerpt"]
    assert RAW_CREDENTIAL_REF not in log_entry["payload_excerpt"]


def test_project_delivery_channel_validate_git_auto_delivery_missing_env_not_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN", raising=False)
    app = build_delivery_channel_validate_api_app(tmp_path)

    with TestClient(app) as client:
        put_response = client.put(
            "/api/projects/project-default/delivery-channel",
            json=git_payload(),
        )
        response = client.post(
            "/api/projects/project-default/delivery-channel/validate",
        )

    assert put_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["readiness_status"] == "unconfigured"
    assert body["credential_status"] == "unbound"
    assert body["readiness_message"] == MISSING_ENV_CREDENTIAL_MESSAGE
    assert body["validated_fields"] == [
        "scm_provider_type",
        "repository_identifier",
        "default_branch",
        "code_review_request_type",
        "credential_ref",
    ]

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, "delivery-default")
    assert channel is not None
    assert channel.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert channel.credential_status is CredentialStatus.UNBOUND
    assert channel.last_validated_at is not None


def test_project_delivery_channel_validate_git_auto_delivery_ready_with_existing_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN", SECRET_VALUE)
    app = build_delivery_channel_validate_api_app(tmp_path)

    with TestClient(app) as client:
        put_response = client.put(
            "/api/projects/project-default/delivery-channel",
            json=git_payload(),
        )
        response = client.post(
            "/api/projects/project-default/delivery-channel/validate",
            headers={
                "X-Request-ID": "req-delivery-ready-env",
                "X-Correlation-ID": "corr-delivery-ready-env",
            },
        )

    assert put_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["readiness_status"] == "ready"
    assert body["credential_status"] == "ready"
    assert body["readiness_message"] == "git_auto_delivery is ready."
    assert SECRET_VALUE not in str(body)

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.validate",
                AuditLogEntryModel.request_id == "req-delivery-ready-env",
            )
            .one_or_none()
        )
    assert audit is not None
    assert audit.result is AuditResult.SUCCEEDED
    assert SECRET_VALUE not in (audit.metadata_excerpt or "")
    for log_entry in app_log_lines(app):
        assert SECRET_VALUE not in json.dumps(log_entry, ensure_ascii=False)


def test_project_delivery_channel_validate_blocks_unsafe_ref_everywhere(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_validate_api_app(tmp_path)

    with TestClient(app) as client:
        with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
            channel = session.get(DeliveryChannelModel, "delivery-default")
            assert channel is not None
            channel.delivery_mode = DeliveryMode.GIT_AUTO_DELIVERY
            channel.scm_provider_type = ScmProviderType.GITHUB
            channel.repository_identifier = "acme/app"
            channel.default_branch = "main"
            channel.code_review_request_type = CodeReviewRequestType.PULL_REQUEST
            channel.credential_ref = RAW_CREDENTIAL_REF
            channel.credential_status = CredentialStatus.UNBOUND
            channel.readiness_status = DeliveryReadinessStatus.UNCONFIGURED
            session.add(channel)
            session.commit()

        response = client.post(
            "/api/projects/project-default/delivery-channel/validate",
            headers={
                "X-Request-ID": "req-delivery-invalid-ref",
                "X-Correlation-ID": "corr-delivery-invalid-ref",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["readiness_status"] == "invalid"
    assert body["credential_status"] == "invalid"
    assert body["readiness_message"] == (
        "DeliveryChannel credential_ref must use an allowed env: credential reference."
    )
    assert RAW_CREDENTIAL_REF not in str(body)

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.validate",
                AuditLogEntryModel.request_id == "req-delivery-invalid-ref",
            )
            .one_or_none()
        )
    assert audit is not None
    assert "[blocked:credential_ref]" in (audit.metadata_excerpt or "")
    assert RAW_CREDENTIAL_REF not in (audit.metadata_excerpt or "")
    for log_entry in app_log_lines(app):
        assert RAW_CREDENTIAL_REF not in json.dumps(log_entry, ensure_ascii=False)


def test_project_delivery_channel_validate_missing_project_unified_404_and_audit(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_validate_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/project-missing/delivery-channel/validate",
            headers={
                "X-Request-ID": "req-delivery-validate-missing",
                "X-Correlation-ID": "corr-delivery-validate-missing",
            },
        )

    assert_error(
        response,
        status_code=404,
        error_code="not_found",
        message="Project was not found.",
        request_id="req-delivery-validate-missing",
        correlation_id="corr-delivery-validate-missing",
    )

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        rejected = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "delivery_channel.validate.rejected",
                AuditLogEntryModel.request_id == "req-delivery-validate-missing",
            )
            .one_or_none()
        )
    assert rejected is not None
    assert rejected.result is AuditResult.REJECTED
    assert rejected.target_id == "project:project-missing"
    assert rejected.correlation_id == "corr-delivery-validate-missing"


def test_project_delivery_channel_validate_route_is_documented_in_openapi(
    tmp_path: Path,
) -> None:
    app = build_delivery_channel_validate_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    route = document["paths"]["/api/projects/{projectId}/delivery-channel/validate"]
    validate_channel = route["post"]
    schemas = document["components"]["schemas"]

    assert "requestBody" not in validate_channel
    assert validate_channel["parameters"] == [
        {
            "name": "projectId",
            "in": "path",
            "required": True,
            "schema": {"type": "string", "title": "Projectid"},
        }
    ]
    assert set(validate_channel["responses"]) == {"200", "404", "422", "500"}
    assert (
        validate_channel["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ProjectDeliveryChannelValidationResult"
    )
    for status_code in ["404", "422", "500"]:
        assert (
            validate_channel["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    assert "ProjectDeliveryChannelValidationResult" in schemas
    properties = schemas["ProjectDeliveryChannelValidationResult"]["properties"]
    assert set(properties) == {
        "readiness_status",
        "readiness_message",
        "credential_status",
        "validated_fields",
        "validated_at",
    }
    assert "credential_ref" not in properties
    assert "api_key" not in properties
    assert "last_validated_at" not in properties
    assert "snapshot_ref" not in properties
