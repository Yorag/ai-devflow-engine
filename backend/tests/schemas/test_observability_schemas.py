from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas import common


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_run_log_projection_carries_file_location_trace_and_payload_summary() -> None:
    from backend.app.schemas.observability import (
        LogCategory,
        LogLevel,
        RedactionStatus,
        RunLogEntryProjection,
    )

    entry = RunLogEntryProjection(
        log_id="log-1",
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-1",
        approval_id=None,
        tool_confirmation_id="tool-confirmation-1",
        delivery_record_id=None,
        graph_thread_id="graph-thread-1",
        request_id="request-1",
        source="tool.registry",
        category=LogCategory.TOOL,
        level=LogLevel.WARNING,
        message="Tool call requires confirmation.",
        log_file_ref="logs/runs/run-1.jsonl",
        line_offset=128,
        line_number=3,
        log_file_generation="run-1",
        payload_ref="payload-tool-1",
        payload_excerpt="{'tool_name': 'bash', 'risk': 'high_risk'}",
        payload_size_bytes=512,
        redaction_status=RedactionStatus.REDACTED,
        correlation_id="correlation-1",
        trace_id="trace-1",
        span_id="span-tool-1",
        parent_span_id="span-stage-1",
        created_at=NOW,
    )

    dumped = entry.model_dump(mode="json")
    assert dumped["category"] == "tool"
    assert dumped["level"] == "warning"
    assert dumped["redaction_status"] == "redacted"
    assert dumped["log_file_ref"] == "logs/runs/run-1.jsonl"
    assert dumped["line_offset"] == 128
    assert dumped["line_number"] == 3
    assert dumped["request_id"] == "request-1"
    assert dumped["trace_id"] == "trace-1"
    assert dumped["correlation_id"] == "correlation-1"
    assert dumped["span_id"] == "span-tool-1"
    assert dumped["parent_span_id"] == "span-stage-1"
    assert "payload" not in dumped
    assert "raw_payload" not in dumped

    with pytest.raises(ValidationError):
        RunLogEntryProjection(
            **{
                **dumped,
                "payload": {"secret": "must not be accepted"},
            }
        )

    with pytest.raises(ValidationError):
        RunLogEntryProjection(
            **{
                **dumped,
                "log_file_ref": "C:/repo/.runtime/logs/runs/run-1.jsonl",
            }
        )

    with pytest.raises(ValidationError):
        RunLogEntryProjection(
            **{
                **dumped,
                "log_file_ref": "logs/../audit.jsonl",
            }
        )

    with pytest.raises(ValidationError):
        RunLogEntryProjection(
            **{
                **dumped,
                "redaction_status": "truncated",
            }
        )

    with pytest.raises(ValidationError):
        RunLogEntryProjection(
            **{
                **dumped,
                "message": "",
            }
        )


def test_audit_log_projection_records_actor_target_result_and_metadata_excerpt() -> None:
    from backend.app.schemas.observability import (
        AuditActorType,
        AuditLogEntryProjection,
        AuditResult,
    )

    entry = AuditLogEntryProjection(
        audit_id="audit-1",
        actor_type=AuditActorType.USER,
        actor_id="user-local",
        action="tool_confirmation.allow",
        target_type="tool_confirmation",
        target_id="tool-confirmation-1",
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-1",
        approval_id=None,
        tool_confirmation_id="tool-confirmation-1",
        delivery_record_id=None,
        request_id="request-1",
        result=AuditResult.ACCEPTED,
        reason="User allowed this high-risk command.",
        metadata_ref="audit-metadata-1",
        metadata_excerpt="Allowed bash command npm install.",
        correlation_id="correlation-1",
        trace_id="trace-1",
        span_id="span-audit-1",
        created_at=NOW,
    )

    dumped = entry.model_dump(mode="json")
    assert dumped["actor_type"] == "user"
    assert dumped["result"] == "accepted"
    assert dumped["metadata_excerpt"] == "Allowed bash command npm install."
    assert dumped["correlation_id"] == "correlation-1"
    assert "metadata" not in dumped
    assert "raw_metadata" not in dumped

    with pytest.raises(ValidationError):
        AuditLogEntryProjection(
            **{
                **dumped,
                "metadata": {"authorization": "Bearer secret"},
            }
        )

    with pytest.raises(ValidationError):
        AuditLogEntryProjection(
            **{
                **dumped,
                "action": "",
            }
        )


def test_log_and_audit_queries_are_focused_readonly_and_bounded() -> None:
    from backend.app.schemas.observability import (
        AuditActorType,
        AuditLogQuery,
        AuditResult,
        LogCategory,
        LogLevel,
        RunLogQuery,
    )

    run_query = RunLogQuery(
        run_id="run-1",
        stage_run_id="stage-1",
        correlation_id="correlation-1",
        level=LogLevel.ERROR,
        category=LogCategory.MODEL,
        source="provider.deepseek",
        since=NOW,
        until=NOW,
        cursor="cursor-1",
        limit=50,
    )
    audit_query = AuditLogQuery(
        actor_type=AuditActorType.SYSTEM,
        action="configuration.update",
        target_type="platform_runtime_settings",
        target_id="settings-1",
        run_id="run-1",
        stage_run_id=None,
        correlation_id="correlation-1",
        result=AuditResult.SUCCEEDED,
        since=NOW,
        until=NOW,
        cursor="cursor-2",
        limit=25,
    )

    assert run_query.model_dump(mode="json")["limit"] == 50
    assert run_query.model_dump(mode="json")["correlation_id"] == "correlation-1"
    assert audit_query.model_dump(mode="json")["actor_type"] == "system"
    assert audit_query.model_dump(mode="json")["correlation_id"] == "correlation-1"

    with pytest.raises(ValidationError):
        RunLogQuery(limit=501)

    with pytest.raises(ValidationError):
        AuditLogQuery(limit=501)

    with pytest.raises(ValidationError):
        RunLogQuery(since=datetime(2026, 1, 3, tzinfo=UTC), until=NOW)

    with pytest.raises(ValidationError):
        AuditLogQuery(replay=True)

    with pytest.raises(ValidationError):
        RunLogQuery(delete_after=NOW)


def test_trace_context_inherits_correlation_and_records_parent_span() -> None:
    from backend.app.domain.trace_context import TraceContext

    root = TraceContext(
        request_id="request-1",
        trace_id="trace-run-1",
        correlation_id="correlation-user-action-1",
        span_id="span-stage-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-1",
        approval_id=None,
        tool_confirmation_id=None,
        delivery_record_id=None,
        graph_thread_id="graph-thread-1",
        created_at=NOW,
    )
    child = root.child_span(
        span_id="span-tool-1",
        tool_confirmation_id="tool-confirmation-1",
        created_at=NOW,
    )

    assert child.request_id == root.request_id
    assert child.trace_id == root.trace_id
    assert child.correlation_id == root.correlation_id
    assert child.parent_span_id == root.span_id
    assert child.stage_run_id == root.stage_run_id
    assert child.tool_confirmation_id == "tool-confirmation-1"
    assert child.model_dump(mode="json")["created_at"] == "2026-01-02T03:04:05Z"

    with pytest.raises(ValueError):
        root.child_span(
            span_id="span-invalid",
            request_id="request-2",
            trace_id="trace-run-2",
            correlation_id="correlation-user-action-2",
            created_at=NOW,
        )

    with pytest.raises(ValidationError):
        TraceContext(
            request_id="request-1",
            trace_id="",
            correlation_id="correlation-user-action-1",
            span_id="span-stage-1",
            created_at=NOW,
        )


def test_observability_contracts_do_not_replace_product_feed_inspector_or_events() -> None:
    from backend.app.schemas.events import SessionEvent
    from backend.app.schemas.feed import MessageFeedEntry
    from backend.app.schemas.inspector import InspectorSection
    from backend.app.schemas.observability import (
        LogCategory,
        LogLevel,
        RedactionStatus,
        RunLogEntryProjection,
    )

    log_entry = RunLogEntryProjection(
        log_id="log-1",
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-1",
        approval_id=None,
        tool_confirmation_id=None,
        delivery_record_id=None,
        graph_thread_id=None,
        request_id="request-1",
        source="runtime.stage",
        category=LogCategory.RUNTIME,
        level=LogLevel.INFO,
        message="Stage started.",
        log_file_ref="logs/runs/run-1.jsonl",
        line_offset=0,
        line_number=1,
        log_file_generation="run-1",
        payload_ref=None,
        payload_excerpt="stage_run_id=stage-1",
        payload_size_bytes=64,
        redaction_status=RedactionStatus.NOT_REQUIRED,
        correlation_id="correlation-1",
        trace_id="trace-1",
        span_id="span-1",
        parent_span_id=None,
        created_at=NOW,
    )

    dumped_log = log_entry.model_dump(mode="json")
    assert dumped_log["category"] == "runtime"
    assert dumped_log["redaction_status"] == "not_required"
    assert "type" not in dumped_log
    assert "entry_id" not in dumped_log
    assert "identity" not in dumped_log

    with pytest.raises(ValidationError):
        MessageFeedEntry(**dumped_log)

    with pytest.raises(ValidationError):
        InspectorSection(**dumped_log)

    with pytest.raises(ValidationError):
        SessionEvent(
            event_id="event-log",
            session_id="session-1",
            run_id="run-1",
            event_type=common.SseEventType.STAGE_UPDATED,
            occurred_at=NOW,
            payload={"stage_node": dumped_log},
        )
