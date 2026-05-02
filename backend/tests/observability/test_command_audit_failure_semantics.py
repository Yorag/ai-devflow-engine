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


def test_require_audit_record_rolls_back_and_raises_clear_error_when_ledger_fails(
    tmp_path,
) -> None:
    from backend.app.observability.audit import AuditService, AuditWriteError
    from backend.app.observability.log_writer import JsonlLogWriter

    class FailingSession:
        rolled_back = False

        def add(self, _value: object) -> None:
            raise SQLAlchemyError("log db unavailable")

        def flush(self) -> None:
            raise AssertionError("flush must not run after add failure")

        def commit(self) -> None:
            raise AssertionError("commit must not run after add failure")

        def rollback(self) -> None:
            self.rolled_back = True

    rollback_calls: list[str] = []
    failing_session = FailingSession()

    with pytest.raises(
        AuditWriteError,
        match=(
            "Required audit record for action 'approval.approve' could not be "
            "written; reject or roll back high-impact action."
        ),
    ):
        AuditService(
            failing_session,
            audit_writer=JsonlLogWriter(make_runtime_settings(tmp_path)),
        ).require_audit_record(
            actor_type=AuditActorType.USER,
            actor_id="user-local",
            action="approval.approve",
            target_type="approval",
            target_id="approval-1",
            result=AuditResult.SUCCEEDED,
            reason="Approved code review.",
            metadata={"approval_id": "approval-1"},
            trace_context=make_trace_context(run_id="run-1", approval_id="approval-1"),
            rollback=lambda: rollback_calls.append("domain-rollback"),
            created_at=NOW,
        )

    assert failing_session.rolled_back is True
    assert rollback_calls == ["domain-rollback"]
    assert not (tmp_path / "runtime" / "logs" / "audit.jsonl").exists()


def test_require_audit_record_contains_rollback_callback_failure(
    tmp_path,
) -> None:
    from backend.app.observability.audit import AuditService, AuditWriteError
    from backend.app.observability.log_writer import JsonlLogWriter

    class FailingSession:
        rolled_back = False

        def add(self, _value: object) -> None:
            raise SQLAlchemyError("log db unavailable")

        def flush(self) -> None:
            raise AssertionError("flush must not run after add failure")

        def commit(self) -> None:
            raise AssertionError("commit must not run after add failure")

        def rollback(self) -> None:
            self.rolled_back = True

    def rollback_callback() -> None:
        raise RuntimeError("domain rollback leaked secret")

    failing_session = FailingSession()

    with pytest.raises(AuditWriteError) as exc_info:
        AuditService(
            failing_session,
            audit_writer=JsonlLogWriter(make_runtime_settings(tmp_path)),
        ).require_audit_record(
            actor_type=AuditActorType.USER,
            actor_id="user-local",
            action="approval.approve",
            target_type="approval",
            target_id="approval-1",
            result=AuditResult.SUCCEEDED,
            reason="Approved code review.",
            metadata={"approval_id": "approval-1"},
            trace_context=make_trace_context(run_id="run-1", approval_id="approval-1"),
            rollback=rollback_callback,
            created_at=NOW,
        )

    assert str(exc_info.value) == (
        "Required audit record for action 'approval.approve' could not be "
        "written; reject or roll back high-impact action."
    )
    assert "domain rollback leaked secret" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, AuditWriteError)
    assert failing_session.rolled_back is True
    assert not (tmp_path / "runtime" / "logs" / "audit.jsonl").exists()


def test_require_audit_record_keeps_ledger_and_skips_rollback_when_audit_copy_fails(
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
    rollback_calls: list[str] = []

    with manager.session(DatabaseRole.LOG) as session:
        result = AuditService(
            session,
            audit_writer=AuditCopyFailingWriter(runtime_settings),
        ).require_audit_record(
            actor_type=AuditActorType.USER,
            actor_id="user-local",
            action="runtime.pause",
            target_type="run",
            target_id="run-1",
            result=AuditResult.SUCCEEDED,
            reason="Pause accepted.",
            metadata={"run_id": "run-1"},
            trace_context=make_trace_context(run_id="run-1"),
            rollback=lambda: rollback_calls.append("domain-rollback"),
            created_at=NOW,
        )
        saved_audit = session.get(AuditLogEntryModel, result.audit_id)

    assert saved_audit is not None
    assert saved_audit.audit_file_write_failed is True
    assert result.audit_file_write_failed is True
    assert rollback_calls == []

    service_rows = read_jsonl(runtime_settings.root / "logs" / "app.jsonl")
    assert service_rows[0]["message"] == "Audit JSONL copy write failed."
    assert service_rows[0]["payload_summary"]["failed_audit_id"] == result.audit_id
    assert "audit jsonl unavailable" not in json.dumps(
        service_rows[0], ensure_ascii=False
    )


def test_require_audit_record_applies_to_audit_copy_metadata_persist_failure(
    tmp_path,
) -> None:
    from backend.app.observability.audit import AuditRecordResult, AuditService
    from backend.app.observability.audit import AuditWriteError
    from backend.app.observability.log_writer import JsonlLogWriter

    class CopyMetadataFailingSession:
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
            if self.commit_count == 2:
                raise SQLAlchemyError("audit copy metadata unavailable")

        def rollback(self) -> None:
            self.rolled_back = True

    runtime_settings = make_runtime_settings(tmp_path)
    session = CopyMetadataFailingSession()
    rollback_calls: list[str] = []
    result: AuditRecordResult | None = None

    with pytest.raises(AuditWriteError) as exc_info:
        result = AuditService(
            session,
            audit_writer=JsonlLogWriter(runtime_settings),
        ).require_audit_record(
            actor_type=AuditActorType.USER,
            actor_id="user-local",
            action="runtime.pause",
            target_type="run",
            target_id="run-1",
            result=AuditResult.SUCCEEDED,
            reason="Pause accepted.",
            metadata={"run_id": "run-1"},
            trace_context=make_trace_context(run_id="run-1"),
            rollback=lambda: rollback_calls.append("domain-rollback"),
            created_at=NOW,
        )

    assert str(exc_info.value) == (
        "Required audit record for action 'runtime.pause' could not be "
        "written; reject or roll back high-impact action."
    )
    assert isinstance(exc_info.value.__cause__, AuditWriteError)
    assert session.commit_count == 2
    assert session.rolled_back is True
    assert rollback_calls == ["domain-rollback"]
    assert result is None
    assert not hasattr(exc_info.value, "domain_event")
    assert not hasattr(exc_info.value, "feed_entry")
    assert not hasattr(exc_info.value, "inspector_projection")
    assert (runtime_settings.root / "logs" / "audit.jsonl").exists()


def test_record_blocked_action_records_blocked_result_without_product_side_effects(
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
        ).record_blocked_action(
            actor_type=AuditActorType.SYSTEM,
            actor_id="runtime-tool-gate",
            action="tool.bash.blocked",
            target_type="tool_action",
            target_id="tool-action-1",
            reason="registry_or_audit_bypass",
            metadata={"tool_name": "bash", "command": "rm -rf .runtime"},
            trace_context=make_trace_context(run_id="run-1", stage_run_id="stage-1"),
            created_at=NOW,
        )
        saved_audit = session.get(AuditLogEntryModel, result.audit_id)

    assert saved_audit is not None
    assert saved_audit.result is AuditResult.BLOCKED
    assert saved_audit.action == "tool.bash.blocked"
    assert saved_audit.run_id == "run-1"
    assert saved_audit.stage_run_id == "stage-1"
    assert not hasattr(result, "domain_event")
    assert not hasattr(result, "feed_entry")
    assert not hasattr(result, "inspector_projection")

    audit_rows = read_jsonl(runtime_settings.root / "logs" / "audit.jsonl")
    assert audit_rows[0]["level"] == "warning"
    assert audit_rows[0]["category"] == "security"
