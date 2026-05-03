from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, PlatformRuntimeSettingsModel
from backend.app.db.models.event import EventBase
from backend.app.db.models.log import AuditLogEntryModel, LogBase, LogPayloadModel
from backend.app.db.models.runtime import RuntimeBase
from backend.app.main import create_app
from backend.app.repositories.runtime_settings import RUNTIME_SETTINGS_ID
from backend.app.schemas.observability import AuditActorType, AuditResult, RedactionStatus
from backend.tests.projections.test_workspace_projection import (
    _default_internal_model_bindings,
)


NOW = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)


def build_audit_log_api_app(tmp_path: Path):
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    app = create_app(settings=settings)
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.RUNTIME))
    EventBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.EVENT))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    return app


def _seed_runtime_settings(app) -> None:
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            PlatformRuntimeSettingsModel(
                settings_id=RUNTIME_SETTINGS_ID,
                config_version="platform-runtime-settings-config-v1",
                schema_version="platform-runtime-settings-v1",
                hard_limits_version="platform-hard-limits-v1",
                agent_limits={"max_react_iterations_per_stage": 30},
                provider_call_policy={"network_error_max_retries": 3},
                internal_model_bindings=_default_internal_model_bindings(
                    "platform-runtime-settings-config-v1"
                ),
                context_limits={"grep_max_results": 100},
                log_policy={
                    "run_log_retention_days": 30,
                    "audit_log_retention_days": 180,
                    "log_rotation_max_bytes": 10485760,
                    "log_query_default_limit": 2,
                    "log_query_max_limit": 3,
                },
                created_by_actor_id=None,
                updated_by_actor_id=None,
                last_audit_log_id=None,
                last_trace_id=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def _seed_audit_rows(app) -> None:
    _seed_runtime_settings(app)
    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        session.add(
            LogPayloadModel(
                payload_id="audit-api-payload-1",
                payload_type="audit_metadata_summary",
                summary={"action": "audit-query-test.tool_confirmation.allow"},
                storage_ref=None,
                content_hash="sha256:audit-api-payload-1",
                redaction_status=RedactionStatus.REDACTED,
                payload_size_bytes=128,
                schema_version="log-payload-v1",
                created_at=NOW + timedelta(minutes=1),
            )
        )
        session.flush()
        session.add_all(
            [
                AuditLogEntryModel(
                    audit_id="audit-api-1",
                    actor_type=AuditActorType.USER,
                    actor_id="user-local",
                    action="audit-query-test.tool_confirmation.allow",
                    target_type="tool_confirmation",
                    target_id="tool-confirmation-1",
                    session_id="session-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    approval_id=None,
                    tool_confirmation_id="tool-confirmation-1",
                    delivery_record_id=None,
                    request_id="request-audit-api-1",
                    result=AuditResult.ACCEPTED,
                    reason="User allowed this high-risk command.",
                    metadata_ref="audit-api-payload-1",
                    metadata_excerpt="Allowed bash command npm install.",
                    correlation_id="corr-audit-api-1",
                    trace_id="trace-audit-api-1",
                    span_id="span-audit-api-1",
                    audit_file_ref="logs/audit.jsonl",
                    audit_file_generation="audit-20260501",
                    audit_file_write_failed=False,
                    created_at=NOW + timedelta(minutes=1),
                ),
                AuditLogEntryModel(
                    audit_id="audit-api-2",
                    actor_type=AuditActorType.SYSTEM,
                    actor_id="system-runtime",
                    action="audit-query-test.approval.approve",
                    target_type="approval",
                    target_id="approval-1",
                    session_id="session-1",
                    run_id="run-active",
                    stage_run_id="stage-review",
                    approval_id="approval-1",
                    tool_confirmation_id=None,
                    delivery_record_id=None,
                    request_id="request-audit-api-2",
                    result=AuditResult.SUCCEEDED,
                    reason="Approval moved the run into delivery integration.",
                    metadata_ref=None,
                    metadata_excerpt="snapshot_ref=delivery-snapshot-1",
                    correlation_id="corr-audit-api-2",
                    trace_id="trace-audit-api-2",
                    span_id="span-audit-api-2",
                    audit_file_ref="logs/audit.jsonl",
                    audit_file_generation="audit-20260501",
                    audit_file_write_failed=False,
                    created_at=NOW + timedelta(minutes=2),
                ),
                AuditLogEntryModel(
                    audit_id="audit-api-3",
                    actor_type=AuditActorType.SYSTEM,
                    actor_id="system-runtime",
                    action="audit-query-test.approval.approve",
                    target_type="approval",
                    target_id="approval-2",
                    session_id="session-1",
                    run_id="run-active",
                    stage_run_id="stage-review",
                    approval_id="approval-2",
                    tool_confirmation_id=None,
                    delivery_record_id=None,
                    request_id="request-audit-api-3",
                    result=AuditResult.SUCCEEDED,
                    reason="Second approval record for pagination.",
                    metadata_ref=None,
                    metadata_excerpt="snapshot_ref=delivery-snapshot-2",
                    correlation_id="corr-audit-api-3",
                    trace_id="trace-audit-api-3",
                    span_id="span-audit-api-3",
                    audit_file_ref="logs/audit.jsonl",
                    audit_file_generation="audit-20260501",
                    audit_file_write_failed=False,
                    created_at=NOW + timedelta(minutes=3),
                ),
            ]
        )
        session.commit()


def test_get_audit_logs_returns_paginated_filtered_entries(tmp_path: Path) -> None:
    app = build_audit_log_api_app(tmp_path)
    _seed_audit_rows(app)

    with TestClient(app) as client:
        filtered = client.get(
            "/api/audit-logs",
            params={
                "actor_type": "user",
                "action": "audit-query-test.tool_confirmation.allow",
                "target_type": "tool_confirmation",
                "target_id": "tool-confirmation-1",
                "run_id": "run-active",
                "stage_run_id": "stage-active",
                "correlation_id": "corr-audit-api-1",
                "result": "accepted",
                "limit": "3",
            },
            headers={
                "X-Request-ID": "req-audit-logs",
                "X-Correlation-ID": "corr-audit-logs",
            },
        )
        paged = client.get(
            "/api/audit-logs",
            params={"action": "audit-query-test.approval.approve", "limit": "1"},
            headers={
                "X-Request-ID": "req-audit-logs-paged",
                "X-Correlation-ID": "corr-audit-logs-paged",
            },
        )

    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert [entry["audit_id"] for entry in filtered_payload["entries"]] == ["audit-api-1"]
    assert (
        filtered_payload["entries"][0]["metadata_excerpt"]
        == "Allowed bash command npm install."
    )
    assert filtered_payload["has_more"] is False
    assert filtered_payload["query"]["actor_type"] == "user"
    assert filtered_payload["query"]["stage_run_id"] == "stage-active"

    assert paged.status_code == 200
    paged_payload = paged.json()
    assert [entry["audit_id"] for entry in paged_payload["entries"]] == ["audit-api-3"]
    assert paged_payload["has_more"] is True
    assert paged_payload["next_cursor"]


def test_get_audit_logs_returns_empty_page_and_unified_errors(tmp_path: Path) -> None:
    app = build_audit_log_api_app(tmp_path)
    _seed_audit_rows(app)

    with TestClient(app) as client:
        empty = client.get(
            "/api/audit-logs",
            params={"action": "audit-query-test.missing", "limit": "3"},
            headers={
                "X-Request-ID": "req-audit-empty",
                "X-Correlation-ID": "corr-audit-empty",
            },
        )
        invalid = client.get(
            "/api/audit-logs",
            params={"limit": "999"},
            headers={
                "X-Request-ID": "req-audit-invalid",
                "X-Correlation-ID": "corr-audit-invalid",
            },
        )
        malformed = client.get(
            "/api/audit-logs",
            params={"limit": "not-an-int"},
            headers={
                "X-Request-ID": "req-audit-malformed",
                "X-Correlation-ID": "corr-audit-malformed",
            },
        )

    assert empty.status_code == 200
    assert empty.json()["entries"] == []
    assert empty.json()["has_more"] is False
    assert empty.json()["next_cursor"] is None

    for response, request_id, correlation_id in (
        (invalid, "req-audit-invalid", "corr-audit-invalid"),
        (malformed, "req-audit-malformed", "corr-audit-malformed"),
    ):
        assert response.status_code == 422
        assert response.json() == {
            "error_code": "log_query_invalid",
            "message": "Log query is invalid.",
            "request_id": request_id,
            "correlation_id": correlation_id,
        }


def test_get_audit_logs_returns_config_unavailable_when_runtime_settings_missing(
    tmp_path: Path,
) -> None:
    app = build_audit_log_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/audit-logs",
            headers={
                "X-Request-ID": "req-audit-config-missing",
                "X-Correlation-ID": "corr-audit-config-missing",
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "error_code": "config_snapshot_unavailable",
        "message": "Configuration snapshot is unavailable.",
        "request_id": "req-audit-config-missing",
        "correlation_id": "corr-audit-config-missing",
    }


def test_audit_log_route_is_documented_in_openapi(tmp_path: Path) -> None:
    app = build_audit_log_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    route = document["paths"]["/api/audit-logs"]["get"]
    schemas = document["components"]["schemas"]

    assert set(route["responses"]) == {"200", "422", "503"}
    assert (
        route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/AuditLogQueryResponse"
    )
    param_names = {parameter["name"] for parameter in route["parameters"]}
    assert {
        "actor_type",
        "action",
        "target_type",
        "target_id",
        "run_id",
        "stage_run_id",
        "correlation_id",
        "result",
        "since",
        "until",
        "cursor",
        "limit",
    } <= param_names
    for status_code in ("422", "503"):
        assert (
            route["responses"][status_code]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    assert "AuditLogQueryResponse" in schemas
    assert "AuditLogEntryProjection" in schemas
    assert "AuditLogQuery" in schemas
    assert "ErrorResponse" in schemas
