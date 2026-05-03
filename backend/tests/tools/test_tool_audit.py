from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.db.session import DatabaseManager
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.audit import AuditService
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.observability import AuditResult


NOW = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


def _trace() -> TraceContext:
    return TraceContext(
        request_id="request-tool-audit-1",
        trace_id="trace-tool-audit-1",
        correlation_id="correlation-tool-audit-1",
        span_id="span-tool-audit-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def _build_manager(tmp_path: Path) -> tuple[DatabaseManager, RuntimeDataSettings]:
    settings = EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    manager = DatabaseManager.from_environment_settings(settings)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    return manager, RuntimeDataSettings.from_environment_settings(settings)


def test_record_tool_call_persists_bash_success_audit_entry(tmp_path: Path) -> None:
    manager, runtime_settings = _build_manager(tmp_path)

    with manager.session(DatabaseRole.LOG) as session:
        service = AuditService(
            session,
            audit_writer=JsonlLogWriter(runtime_settings),
        )
        result = service.record_tool_call(
            tool_name="bash",
            command="uv run pytest backend/tests -q",
            exit_code=0,
            duration_ms=321,
            changed_files=["frontend/dist/app.js"],
            stdout_excerpt="tests passed",
            stderr_excerpt="",
            trace_context=_trace(),
            created_at=NOW,
        )

    with manager.session(DatabaseRole.LOG) as session:
        saved = session.get(AuditLogEntryModel, result.audit_id)

    assert saved is not None
    assert saved.action == "tool.bash.succeeded"
    assert saved.result is AuditResult.SUCCEEDED
    assert saved.run_id == "run-1"


def test_record_tool_error_persists_blocked_bash_error_without_secret_leak(
    tmp_path: Path,
) -> None:
    manager, runtime_settings = _build_manager(tmp_path)

    with manager.session(DatabaseRole.LOG) as session:
        service = AuditService(
            session,
            audit_writer=JsonlLogWriter(runtime_settings),
        )
        result = service.record_tool_error(
            tool_name="bash",
            command="echo hacked",
            error_code="bash_command_not_allowed",
            result=AuditResult.BLOCKED,
            reason="Command is not allowlisted.",
            metadata={"stderr_excerpt": "Authorization: Bearer secret-token"},
            trace_context=_trace(),
            created_at=NOW,
        )

    with manager.session(DatabaseRole.LOG) as session:
        saved = session.get(AuditLogEntryModel, result.audit_id)

    assert saved is not None
    assert saved.action == "tool.bash.blocked"
    assert saved.result is AuditResult.BLOCKED
    assert "secret-token" not in (saved.metadata_excerpt or "")
