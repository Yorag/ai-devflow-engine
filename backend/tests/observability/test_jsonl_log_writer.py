from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.redaction import RedactionPolicy
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def make_runtime_settings(tmp_path: Path) -> RuntimeDataSettings:
    return RuntimeDataSettings.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )


def make_trace_context(**updates: str | None) -> TraceContext:
    data = {
        "request_id": "request-1",
        "trace_id": "trace-1",
        "correlation_id": "correlation-1",
        "span_id": "span-1",
        "parent_span_id": "span-parent-1",
        "session_id": "session-1",
        "run_id": "run-1",
        "stage_run_id": "stage-1",
        "approval_id": None,
        "tool_confirmation_id": None,
        "delivery_record_id": None,
        "graph_thread_id": "graph-thread-1",
        "created_at": NOW,
    }
    data.update(updates)
    return TraceContext.model_validate(data)


def make_payload_summary(payload: object, payload_type: str = "api_response"):
    from backend.app.observability.log_writer import LogPayloadSummary

    redacted = RedactionPolicy(max_text_length=48, excerpt_length=160).summarize_payload(
        payload,
        payload_type=payload_type,
    )
    return LogPayloadSummary.from_redacted_payload(payload_type, redacted)


def make_record(*, message: str = "Request completed."):
    from backend.app.observability.log_writer import LogRecordInput

    return LogRecordInput(
        source="api.projects",
        category=LogCategory.API,
        level=LogLevel.INFO,
        message=message,
        trace_context=make_trace_context(),
        payload=make_payload_summary(
            {
                "status": "ok",
                "api_key": "raw-secret-value",
                "output": "visible output",
            }
        ),
        created_at=NOW,
        duration_ms=12,
    )


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_jsonl_writer_appends_service_log_lines_with_trace_and_sanitized_payload(
    tmp_path,
) -> None:
    from backend.app.observability.log_writer import JsonlLogWriter

    runtime_settings = make_runtime_settings(tmp_path)
    writer = JsonlLogWriter(runtime_settings)

    first = writer.write(make_record())
    second = writer.write(make_record(message="Second request completed."))

    app_log_path = runtime_settings.root / "logs" / "app.jsonl"
    rows = read_jsonl(app_log_path)

    assert first.log_file_ref == "logs/app.jsonl"
    assert first.line_offset == 0
    assert first.line_number == 1
    assert first.log_file_generation == "app"
    assert second.log_file_ref == "logs/app.jsonl"
    assert second.line_offset > first.line_offset
    assert second.line_number == 2
    assert len(rows) == 2

    row = rows[0]
    assert row["schema_version"] == 1
    assert row["log_id"] == first.log_id
    assert row["created_at"] == NOW.isoformat()
    assert row["level"] == "info"
    assert row["category"] == "api"
    assert row["source"] == "api.projects"
    assert row["message"] == "Request completed."
    assert row["request_id"] == "request-1"
    assert row["trace_id"] == "trace-1"
    assert row["correlation_id"] == "correlation-1"
    assert row["span_id"] == "span-1"
    assert row["parent_span_id"] == "span-parent-1"
    assert row["session_id"] == "session-1"
    assert row["run_id"] == "run-1"
    assert row["stage_run_id"] == "stage-1"
    assert row["graph_thread_id"] == "graph-thread-1"
    assert row["redaction_status"] == "redacted"
    assert row["payload_size_bytes"] > 0
    assert row["payload_content_hash"].startswith("sha256:")
    assert row["payload_summary"]["blocked_fields"] == ["api_key"]
    assert "raw-secret-value" not in json.dumps(row, ensure_ascii=False)
    assert "raw_payload" not in row
    assert "domain_event_id" not in row
    assert "feed_entry_id" not in row
    assert "inspector_projection_id" not in row


def test_jsonl_writer_writes_run_log_and_audit_copy_to_expected_runtime_refs(
    tmp_path,
) -> None:
    from backend.app.observability.log_writer import JsonlLogWriter, LogRecordInput

    runtime_settings = make_runtime_settings(tmp_path)
    writer = JsonlLogWriter(runtime_settings)
    trace_context = make_trace_context(tool_confirmation_id="tool-confirmation-1")
    record = LogRecordInput(
        source="runtime.tool_registry",
        category=LogCategory.SECURITY,
        level=LogLevel.WARNING,
        message="Tool confirmation required.",
        trace_context=trace_context,
        payload=make_payload_summary(
            {"tool_name": "bash", "credential_ref": "env:GITHUB_TOKEN"},
            payload_type="tool_confirmation_summary",
        ),
        created_at=NOW,
    )

    run_result = writer.write_run_log(record)
    audit_result = writer.write_audit_copy(record)

    assert run_result.log_file_ref == "logs/runs/run-1.jsonl"
    assert run_result.log_file_generation == "run-1"
    assert audit_result.log_file_ref == "logs/audit.jsonl"
    assert audit_result.log_file_generation == "audit"

    run_row = read_jsonl(runtime_settings.root / run_result.log_file_ref)[0]
    audit_row = read_jsonl(runtime_settings.root / audit_result.log_file_ref)[0]
    assert run_row["run_id"] == "run-1"
    assert run_row["stage_run_id"] == "stage-1"
    assert run_row["tool_confirmation_id"] == "tool-confirmation-1"
    assert run_row["category"] == "security"
    assert run_row["redaction_status"] == "not_required"
    assert audit_row["log_id"] == audit_result.log_id
    assert audit_row["message"] == "Tool confirmation required."


def test_jsonl_writer_requires_run_id_for_run_log_path(tmp_path) -> None:
    from backend.app.observability.log_writer import JsonlLogWriter, LogRecordInput

    runtime_settings = make_runtime_settings(tmp_path)
    writer = JsonlLogWriter(runtime_settings)
    record = LogRecordInput(
        source="runtime",
        category=LogCategory.RUNTIME,
        level=LogLevel.INFO,
        message="Cannot resolve run log path.",
        trace_context=make_trace_context(run_id=None),
        payload=make_payload_summary({"status": "ok"}),
        created_at=NOW,
    )

    try:
        writer.write_run_log(record)
    except ValueError as exc:
        assert "run_id is required" in str(exc)
    else:
        raise AssertionError("write_run_log must reject records without run_id")


@pytest.mark.parametrize("unsafe_run_id", ["../escape", "nested/run", "nested\\run"])
def test_jsonl_writer_rejects_unsafe_run_id_before_filesystem_side_effects(
    tmp_path,
    unsafe_run_id: str,
) -> None:
    from backend.app.observability.log_writer import JsonlLogWriter, LogRecordInput

    runtime_settings = make_runtime_settings(tmp_path)
    writer = JsonlLogWriter(runtime_settings)
    record = LogRecordInput(
        source="runtime",
        category=LogCategory.RUNTIME,
        level=LogLevel.INFO,
        message="Unsafe run id must not become a path.",
        trace_context=make_trace_context(run_id=unsafe_run_id),
        payload=make_payload_summary({"status": "ok"}),
        created_at=NOW,
    )

    with pytest.raises(ValueError, match="run_id must be a safe path segment"):
        writer.write_run_log(record)

    assert not (runtime_settings.root / "logs").exists()
    assert not (runtime_settings.root / "escape.jsonl").exists()


def test_log_index_repository_persists_run_log_entry_and_bounded_payload(
    tmp_path,
) -> None:
    from backend.app.db.models.log import LogBase, LogPayloadModel, RunLogEntryModel
    from backend.app.observability.log_index import LogIndexRepository
    from backend.app.observability.log_writer import JsonlLogWriter

    runtime_settings = make_runtime_settings(tmp_path)
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=runtime_settings.root)
    )
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    writer = JsonlLogWriter(runtime_settings)
    record = make_record()
    write_result = writer.write_run_log(record)

    with manager.session(DatabaseRole.LOG) as session:
        result = LogIndexRepository(session).append_run_log_index(record, write_result)
        assert result.index_written is True
        assert result.error_message is None

        saved_entry = session.get(RunLogEntryModel, write_result.log_id)
        assert saved_entry is not None
        saved_payload = session.get(LogPayloadModel, saved_entry.payload_ref)

    assert saved_payload is not None
    assert saved_entry.log_file_ref == "logs/runs/run-1.jsonl"
    assert saved_entry.line_offset == write_result.line_offset
    assert saved_entry.line_number == write_result.line_number
    assert saved_entry.category is LogCategory.API
    assert saved_entry.level is LogLevel.INFO
    assert saved_entry.request_id == "request-1"
    assert saved_entry.correlation_id == "correlation-1"
    assert saved_entry.trace_id == "trace-1"
    assert saved_entry.run_id == "run-1"
    assert saved_entry.stage_run_id == "stage-1"
    assert saved_entry.redaction_status is RedactionStatus.REDACTED
    assert saved_payload.payload_type == "api_response"
    assert saved_payload.summary["blocked_fields"] == ["api_key"]
    assert saved_payload.storage_ref is None
    assert saved_payload.content_hash.startswith("sha256:")
    assert "raw-secret-value" not in json.dumps(saved_payload.summary, ensure_ascii=False)

    with manager.session(DatabaseRole.LOG) as session:
        log_tables = set(inspect(session.bind).get_table_names())
    assert "run_log_entries" in log_tables
    assert "log_payloads" in log_tables
    assert "domain_events" not in log_tables
    assert "feed_entries" not in log_tables
    assert "inspector_projections" not in log_tables


def test_log_index_failure_writes_service_error_without_raising(tmp_path) -> None:
    from backend.app.observability.log_index import LogIndexRepository
    from backend.app.observability.log_writer import JsonlLogWriter

    class FailingSession:
        rolled_back = False

        def add(self, _value: object) -> None:
            raise SQLAlchemyError("log db unavailable")

        def commit(self) -> None:
            raise AssertionError("commit must not run after add failure")

        def rollback(self) -> None:
            self.rolled_back = True

    runtime_settings = make_runtime_settings(tmp_path)
    writer = JsonlLogWriter(runtime_settings)
    record = make_record()
    write_result = writer.write_run_log(record)
    failing_session = FailingSession()

    result = LogIndexRepository(
        failing_session,
        failure_writer=writer,
    ).append_run_log_index(record, write_result)

    assert result.index_written is False
    assert "Run log index write failed" in result.error_message
    assert failing_session.rolled_back is True

    service_rows = read_jsonl(runtime_settings.root / "logs" / "app.jsonl")
    assert len(service_rows) == 1
    service_row = service_rows[0]
    assert service_row["level"] == "error"
    assert service_row["category"] == "error"
    assert service_row["source"] == "observability.log_index"
    assert service_row["message"] == "Run log index write failed."
    assert service_row["correlation_id"] == "correlation-1"
    assert service_row["payload_summary"]["failed_log_id"] == write_result.log_id
    assert service_row["payload_summary"]["error_type"] == "SQLAlchemyError"
    assert "log db unavailable" not in json.dumps(service_row, ensure_ascii=False)


def test_log_index_failure_contains_rollback_and_diagnostic_writer_failures(
    tmp_path,
) -> None:
    from backend.app.observability.log_index import LogIndexRepository
    from backend.app.observability.log_writer import JsonlLogWriter

    class RollbackFailingSession:
        def add(self, _value: object) -> None:
            raise SQLAlchemyError("log db unavailable")

        def commit(self) -> None:
            raise AssertionError("commit must not run after add failure")

        def rollback(self) -> None:
            raise RuntimeError("rollback failed")

    class DiagnosticFailingWriter(JsonlLogWriter):
        def write(self, _record):  # noqa: ANN001
            raise OSError("app log unavailable")

    runtime_settings = make_runtime_settings(tmp_path)
    writer = JsonlLogWriter(runtime_settings)
    record = make_record()
    write_result = writer.write_run_log(record)

    result = LogIndexRepository(
        RollbackFailingSession(),
        failure_writer=DiagnosticFailingWriter(runtime_settings),
    ).append_run_log_index(record, write_result)

    assert result.index_written is False
    assert result.error_message == "Run log index write failed."
