from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import PlatformRuntimeSettingsModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase, LogPayloadModel
from backend.app.observability.audit import AuditService
from backend.app.repositories.runtime_settings import RUNTIME_SETTINGS_ID
from backend.app.schemas.observability import AuditActorType, AuditResult, RedactionStatus
from backend.tests.projections.test_workspace_projection import (
    NOW,
    _default_internal_model_bindings,
    _manager,
)


AUDIT_TIMES = [
    NOW + timedelta(minutes=1),
    NOW + timedelta(minutes=2),
    NOW + timedelta(minutes=3),
    NOW + timedelta(minutes=4),
]


def _seed_runtime_settings(
    manager,
    *,
    default_limit: int = 2,
    max_limit: int = 3,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
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
                    "log_query_default_limit": default_limit,
                    "log_query_max_limit": max_limit,
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


def _seed_audit_rows(manager, *, seed_settings: bool = True) -> None:
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    if seed_settings:
        _seed_runtime_settings(manager)
    with manager.session(DatabaseRole.LOG) as session:
        session.add(
            LogPayloadModel(
                payload_id="audit-payload-1",
                payload_type="audit_metadata_summary",
                summary={"secret": "must not be exposed"},
                storage_ref=None,
                content_hash="sha256:audit-payload-1",
                redaction_status=RedactionStatus.REDACTED,
                payload_size_bytes=128,
                schema_version="log-payload-v1",
                created_at=AUDIT_TIMES[0],
            )
        )
        session.flush()
        session.add_all(
            [
                AuditLogEntryModel(
                    audit_id="audit-1",
                    actor_type=AuditActorType.USER,
                    actor_id="user-local",
                    action="tool_confirmation.allow",
                    target_type="tool_confirmation",
                    target_id="tool-confirmation-1",
                    session_id="session-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    approval_id=None,
                    tool_confirmation_id="tool-confirmation-1",
                    delivery_record_id=None,
                    request_id="request-1",
                    result=AuditResult.ACCEPTED,
                    reason="User allowed this high-risk command.",
                    metadata_ref="audit-payload-1",
                    metadata_excerpt="Allowed bash command npm install.",
                    correlation_id="corr-audit-1",
                    trace_id="trace-audit-1",
                    span_id="span-audit-1",
                    audit_file_ref="logs/audit.jsonl",
                    audit_file_generation="audit-20260501",
                    audit_file_write_failed=False,
                    created_at=AUDIT_TIMES[0],
                ),
                AuditLogEntryModel(
                    audit_id="audit-2",
                    actor_type=AuditActorType.SYSTEM,
                    actor_id="system-runtime",
                    action="approval.approve",
                    target_type="approval",
                    target_id="approval-1",
                    session_id="session-1",
                    run_id="run-active",
                    stage_run_id="stage-review",
                    approval_id="approval-1",
                    tool_confirmation_id=None,
                    delivery_record_id=None,
                    request_id="request-2",
                    result=AuditResult.SUCCEEDED,
                    reason="Approval moved the run into delivery integration.",
                    metadata_ref=None,
                    metadata_excerpt="snapshot_ref=delivery-snapshot-1",
                    correlation_id="corr-audit-2",
                    trace_id="trace-audit-2",
                    span_id="span-audit-2",
                    audit_file_ref="logs/audit.jsonl",
                    audit_file_generation="audit-20260501",
                    audit_file_write_failed=False,
                    created_at=AUDIT_TIMES[1],
                ),
                AuditLogEntryModel(
                    audit_id="audit-3",
                    actor_type=AuditActorType.TOOL,
                    actor_id="bash",
                    action="workspace.write",
                    target_type="workspace_file",
                    target_id="frontend/package-lock.json",
                    session_id="session-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    approval_id=None,
                    tool_confirmation_id=None,
                    delivery_record_id=None,
                    request_id="request-3",
                    result=AuditResult.BLOCKED,
                    reason="High-risk command was blocked before execution.",
                    metadata_ref=None,
                    metadata_excerpt="risk=high_risk",
                    correlation_id="corr-audit-3",
                    trace_id="trace-audit-3",
                    span_id="span-audit-3",
                    audit_file_ref="logs/audit.jsonl",
                    audit_file_generation="audit-20260501",
                    audit_file_write_failed=False,
                    created_at=AUDIT_TIMES[2],
                ),
                AuditLogEntryModel(
                    audit_id="audit-older",
                    actor_type=AuditActorType.SYSTEM,
                    actor_id="system-runtime",
                    action="provider.update",
                    target_type="provider",
                    target_id="provider-old",
                    session_id=None,
                    run_id=None,
                    stage_run_id=None,
                    approval_id=None,
                    tool_confirmation_id=None,
                    delivery_record_id=None,
                    request_id="request-old",
                    result=AuditResult.FAILED,
                    reason="Legacy provider validation failed.",
                    metadata_ref=None,
                    metadata_excerpt="provider_id=provider-old",
                    correlation_id="corr-audit-old",
                    trace_id="trace-audit-old",
                    span_id="span-audit-old",
                    audit_file_ref="logs/audit.jsonl",
                    audit_file_generation="audit-20260501",
                    audit_file_write_failed=False,
                    created_at=AUDIT_TIMES[3],
                ),
            ]
        )
        session.commit()


class _UnusedAuditWriter:
    def write_audit_copy(self, _record_input):
        raise AssertionError("audit write path is not expected in audit query tests")

    def write(self, _record_input):
        raise AssertionError("audit write path is not expected in audit query tests")


def _service(manager) -> AuditService:
    return AuditService(
        manager.session(DatabaseRole.LOG),
        control_session=manager.session(DatabaseRole.CONTROL),
        audit_writer=_UnusedAuditWriter(),
    )


def test_list_audit_logs_pages_descending_and_echoes_filters(tmp_path) -> None:
    manager = _manager(tmp_path)
    _seed_audit_rows(manager)
    service = _service(manager)

    first_page = service.list_audit_logs(limit=2)

    assert [entry.audit_id for entry in first_page.entries] == ["audit-older", "audit-3"]
    assert first_page.has_more is True
    assert first_page.next_cursor is not None
    assert first_page.query.limit == 2
    assert first_page.query.cursor is None

    second_page = service.list_audit_logs(cursor=first_page.next_cursor, limit=2)
    assert [entry.audit_id for entry in second_page.entries] == ["audit-2", "audit-1"]
    assert second_page.has_more is False
    assert second_page.next_cursor is None
    assert second_page.query.cursor == first_page.next_cursor


def test_list_audit_logs_filters_without_exposing_payload_summary(tmp_path) -> None:
    manager = _manager(tmp_path)
    _seed_audit_rows(manager)
    service = _service(manager)

    response = service.list_audit_logs(
        actor_type=AuditActorType.USER,
        action="tool_confirmation.allow",
        target_type="tool_confirmation",
        target_id="tool-confirmation-1",
        run_id="run-active",
        stage_run_id="stage-active",
        correlation_id="corr-audit-1",
        result=AuditResult.ACCEPTED,
        since=AUDIT_TIMES[0],
        until=AUDIT_TIMES[0],
    )

    assert [entry.audit_id for entry in response.entries] == ["audit-1"]
    dumped = response.model_dump(mode="json")
    assert dumped["query"]["actor_type"] == "user"
    assert dumped["query"]["stage_run_id"] == "stage-active"
    assert dumped["query"]["limit"] == 2
    assert dumped["entries"][0]["metadata_excerpt"] == "Allowed bash command npm install."
    assert "summary" not in dumped["entries"][0]
    assert "metadata" not in dumped["entries"][0]
    assert "secret" not in str(dumped)


def test_list_audit_logs_returns_empty_collection_for_valid_no_match_filter(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_audit_rows(manager)
    service = _service(manager)

    response = service.list_audit_logs(
        action="missing.action",
        limit=3,
    )

    assert response.entries == []
    assert response.has_more is False
    assert response.next_cursor is None
    assert response.query.action == "missing.action"


def test_list_audit_logs_rejects_invalid_limit_cursor_and_time_range(
    tmp_path,
) -> None:
    from backend.app.observability.audit import AuditQueryServiceError

    manager = _manager(tmp_path)
    _seed_audit_rows(manager)
    service = _service(manager)

    for kwargs in (
        {"limit": 4},
        {"limit": 0},
        {"cursor": "not-a-cursor"},
        {"since": AUDIT_TIMES[1], "until": AUDIT_TIMES[0]},
    ):
        with pytest.raises(AuditQueryServiceError) as exc_info:
            service.list_audit_logs(**kwargs)
        assert exc_info.value.error_code is ErrorCode.LOG_QUERY_INVALID
        assert exc_info.value.message == "Log query is invalid."
        assert exc_info.value.status_code == 422


def test_list_audit_logs_reports_config_snapshot_unavailable(tmp_path) -> None:
    from backend.app.observability.audit import AuditQueryServiceError

    manager = _manager(tmp_path)
    _seed_audit_rows(manager, seed_settings=False)

    with pytest.raises(AuditQueryServiceError) as exc_info:
        _service(manager).list_audit_logs()

    assert exc_info.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert exc_info.value.message == "Configuration snapshot is unavailable."
    assert exc_info.value.status_code == 503
