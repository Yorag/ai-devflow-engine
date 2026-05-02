from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def make_runtime_settings(tmp_path: Path):
    from backend.app.observability.runtime_data import RuntimeDataSettings

    return RuntimeDataSettings.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )


def make_manager(tmp_path: Path) -> DatabaseManager:
    from backend.app.db.models.log import LogBase

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    return manager


def make_trace_context(**updates: str | None) -> TraceContext:
    data = {
        "request_id": "request-1",
        "trace_id": "trace-1",
        "correlation_id": "correlation-1",
        "span_id": "span-1",
        "parent_span_id": "span-parent-1",
        "session_id": "session-1",
        "run_id": None,
        "stage_run_id": None,
        "approval_id": None,
        "tool_confirmation_id": None,
        "delivery_record_id": None,
        "graph_thread_id": None,
        "created_at": NOW,
    }
    data.update(updates)
    return TraceContext.model_validate(data)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_audit_service_records_successful_command_to_log_db_and_audit_jsonl(
    tmp_path,
) -> None:
    from backend.app.db.models.log import AuditLogEntryModel, LogPayloadModel
    from backend.app.observability.audit import AuditService
    from backend.app.observability.log_writer import JsonlLogWriter

    runtime_settings = make_runtime_settings(tmp_path)
    manager = make_manager(tmp_path)
    writer = JsonlLogWriter(runtime_settings)

    with manager.session(DatabaseRole.LOG) as session:
        result = AuditService(session, audit_writer=writer).record_command_result(
            actor_type=AuditActorType.USER,
            actor_id="user-local",
            action="project.load",
            target_type="project",
            target_id="project:sha256-root",
            result=AuditResult.SUCCEEDED,
            reason="Project loaded.",
            metadata={
                "credential_ref": "env:PROJECT_TOKEN",
                "api_key": "raw-secret-value",
                "visible": "kept",
            },
            trace_context=make_trace_context(),
            created_at=NOW,
        )

        saved_audit = session.get(AuditLogEntryModel, result.audit_id)
        saved_payload = session.get(LogPayloadModel, saved_audit.metadata_ref)

    assert saved_audit is not None
    assert saved_payload is not None
    assert saved_audit.actor_type is AuditActorType.USER
    assert saved_audit.actor_id == "user-local"
    assert saved_audit.action == "project.load"
    assert saved_audit.target_type == "project"
    assert saved_audit.target_id == "project:sha256-root"
    assert saved_audit.result is AuditResult.SUCCEEDED
    assert saved_audit.reason == "Project loaded."
    assert saved_audit.request_id == "request-1"
    assert saved_audit.trace_id == "trace-1"
    assert saved_audit.correlation_id == "correlation-1"
    assert saved_audit.span_id == "span-1"
    assert saved_audit.audit_file_ref == "logs/audit.jsonl"
    assert saved_audit.audit_file_generation == "audit"
    assert saved_audit.audit_file_write_failed is False
    assert saved_payload.payload_type == "audit_metadata_summary"
    assert saved_payload.summary["blocked_fields"] == ["metadata.api_key"]
    assert saved_payload.content_hash.startswith("sha256:")
    assert "raw-secret-value" not in json.dumps(saved_payload.summary, ensure_ascii=False)
    assert "raw-secret-value" not in (saved_audit.metadata_excerpt or "")

    rows = read_jsonl(runtime_settings.root / "logs" / "audit.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert row["log_id"] == result.audit_id
    assert row["category"] == "security"
    assert row["level"] == "info"
    assert row["source"] == "observability.audit"
    assert row["message"] == "Control-plane command audit recorded."
    assert row["request_id"] == "request-1"
    assert row["trace_id"] == "trace-1"
    assert row["correlation_id"] == "correlation-1"
    assert row["span_id"] == "span-1"
    assert row["redaction_status"] == "redacted"
    assert "raw-secret-value" not in json.dumps(row, ensure_ascii=False)


def test_audit_service_records_rejected_command_with_request_and_correlation(
    tmp_path,
) -> None:
    from backend.app.db.models.log import AuditLogEntryModel
    from backend.app.observability.audit import AuditService
    from backend.app.observability.log_writer import JsonlLogWriter

    runtime_settings = make_runtime_settings(tmp_path)
    manager = make_manager(tmp_path)

    with manager.session(DatabaseRole.LOG) as session:
        result = AuditService(
            session,
            audit_writer=JsonlLogWriter(runtime_settings),
        ).record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id="user-local",
            action="delivery_channel.save",
            target_type="delivery_channel",
            target_id="delivery-channel:default",
            reason="credential_ref is missing",
            metadata={"field": "credential_ref"},
            trace_context=make_trace_context(),
            created_at=NOW,
        )
        saved_audit = session.get(AuditLogEntryModel, result.audit_id)

    assert saved_audit is not None
    assert saved_audit.result is AuditResult.REJECTED
    assert saved_audit.request_id == "request-1"
    assert saved_audit.correlation_id == "correlation-1"
    assert saved_audit.reason == "credential_ref is missing"
    assert not hasattr(result, "api_error_response")
    assert not hasattr(result, "domain_event")


def test_audit_service_records_failed_command_with_redacted_reason_and_metadata(
    tmp_path,
) -> None:
    from backend.app.db.models.log import AuditLogEntryModel, LogPayloadModel
    from backend.app.observability.audit import AuditService
    from backend.app.observability.log_writer import JsonlLogWriter

    runtime_settings = make_runtime_settings(tmp_path)
    manager = make_manager(tmp_path)

    with manager.session(DatabaseRole.LOG) as session:
        result = AuditService(
            session,
            audit_writer=JsonlLogWriter(runtime_settings),
        ).record_failed_command(
            actor_type=AuditActorType.SYSTEM,
            actor_id="control-plane",
            action="provider.update",
            target_type="provider",
            target_id="provider:openai",
            reason="Provider rejected Authorization: Bearer raw-token",
            metadata={"authHeader": "Bearer raw-token", "safe": "visible"},
            trace_context=make_trace_context(),
            created_at=NOW,
        )
        saved_audit = session.get(AuditLogEntryModel, result.audit_id)
        saved_payload = session.get(LogPayloadModel, saved_audit.metadata_ref)

    assert saved_audit is not None
    assert saved_payload is not None
    assert saved_audit.result is AuditResult.FAILED
    assert saved_audit.reason == "[blocked:sensitive_text_pattern]"
    assert saved_payload.summary["blocked_fields"] == ["metadata.authHeader"]
    assert "raw-token" not in json.dumps(saved_payload.summary, ensure_ascii=False)
    assert "raw-token" not in (saved_audit.metadata_excerpt or "")


def test_audit_log_db_write_failure_raises_clear_error_without_soft_downgrade(
    tmp_path,
) -> None:
    from backend.app.observability.audit import AuditService, AuditWriteError
    from backend.app.observability.log_writer import JsonlLogWriter

    class FailingSession:
        rolled_back = False

        def add(self, _value: object) -> None:
            raise SQLAlchemyError("log db unavailable")

        def commit(self) -> None:
            raise AssertionError("commit must not run after add failure")

        def rollback(self) -> None:
            self.rolled_back = True

    failing_session = FailingSession()

    with pytest.raises(AuditWriteError, match="Audit log entry write failed"):
        AuditService(
            failing_session,
            audit_writer=JsonlLogWriter(make_runtime_settings(tmp_path)),
        ).record_command_result(
            actor_type=AuditActorType.SYSTEM,
            actor_id="control-plane",
            action="project.load",
            target_type="project",
            target_id="project:sha256-root",
            result=AuditResult.SUCCEEDED,
            reason="Project loaded.",
            metadata={"visible": "kept"},
            trace_context=make_trace_context(),
            created_at=NOW,
        )

    assert failing_session.rolled_back is True
    assert not (tmp_path / "runtime" / "logs" / "app.jsonl").exists()


def test_audit_jsonl_copy_failure_persists_audit_and_writes_service_error(
    tmp_path,
) -> None:
    from backend.app.db.models.log import AuditLogEntryModel
    from backend.app.observability.audit import AuditService
    from backend.app.observability.log_writer import JsonlLogWriter

    class AuditCopyFailingWriter(JsonlLogWriter):
        def write_audit_copy(self, _record):  # noqa: ANN001
            raise OSError("audit jsonl unavailable")

    runtime_settings = make_runtime_settings(tmp_path)
    manager = make_manager(tmp_path)
    writer = AuditCopyFailingWriter(runtime_settings)

    with manager.session(DatabaseRole.LOG) as session:
        result = AuditService(session, audit_writer=writer).record_command_result(
            actor_type=AuditActorType.SYSTEM,
            actor_id="control-plane",
            action="template.delete",
            target_type="template",
            target_id="template:custom",
            result=AuditResult.SUCCEEDED,
            reason="Template deleted.",
            metadata={"template_id": "template:custom"},
            trace_context=make_trace_context(),
            created_at=NOW,
        )
        saved_audit = session.get(AuditLogEntryModel, result.audit_id)

    assert saved_audit is not None
    assert saved_audit.audit_file_ref is None
    assert saved_audit.audit_file_generation is None
    assert saved_audit.audit_file_write_failed is True
    assert result.audit_file_write_failed is True
    assert not (runtime_settings.root / "logs" / "audit.jsonl").exists()

    service_rows = read_jsonl(runtime_settings.root / "logs" / "app.jsonl")
    assert len(service_rows) == 1
    service_row = service_rows[0]
    assert service_row["level"] == "error"
    assert service_row["category"] == "error"
    assert service_row["source"] == "observability.audit"
    assert service_row["message"] == "Audit JSONL copy write failed."
    assert service_row["correlation_id"] == "correlation-1"
    assert service_row["payload_summary"]["failed_audit_id"] == result.audit_id
    assert service_row["payload_summary"]["error_type"] == "OSError"
    assert "audit jsonl unavailable" not in json.dumps(service_row, ensure_ascii=False)


def test_audit_service_persists_ledger_once_with_audit_file_metadata(
    tmp_path,
) -> None:
    from backend.app.observability.audit import AuditService
    from backend.app.observability.log_writer import JsonlLogWriter

    class CountingSession:
        commit_count = 0
        rolled_back = False
        objects: list[object]

        def __init__(self) -> None:
            self.objects = []

        def add(self, value: object) -> None:
            self.objects.append(value)

        def flush(self) -> None:
            pass

        def commit(self) -> None:
            self.commit_count += 1

        def rollback(self) -> None:
            self.rolled_back = True

    runtime_settings = make_runtime_settings(tmp_path)
    session = CountingSession()

    result = AuditService(
        session,
        audit_writer=JsonlLogWriter(runtime_settings),
    ).record_command_result(
        actor_type=AuditActorType.USER,
        actor_id="user-local",
        action="project.load",
        target_type="project",
        target_id="project:sha256-root",
        result=AuditResult.SUCCEEDED,
        reason="Project loaded.",
        metadata={"visible": "kept"},
        trace_context=make_trace_context(),
        created_at=NOW,
    )

    assert session.commit_count == 1
    assert session.rolled_back is False
    assert result.entry.audit_file_ref == "logs/audit.jsonl"
    assert result.entry.audit_file_generation == "audit"
    assert result.entry.audit_file_write_failed is False
    assert result.entry.metadata_excerpt is not None
    assert "project.load" in result.entry.metadata_excerpt
