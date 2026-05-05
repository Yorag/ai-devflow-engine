from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.log import AuditLogEntryModel, LogBase, LogPayloadModel
from backend.app.db.models.log import RunLogEntryModel
from backend.app.db.models.runtime import PipelineRunModel
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.observability import AuditActorType, AuditResult, LogCategory
from backend.app.schemas.observability import LogLevel, RedactionStatus
from backend.tests.projections.test_workspace_projection import (
    NOW,
    _manager,
    _seed_workspace,
)


OLD_LOG_TIME = NOW - timedelta(days=31)


def _runtime_settings(tmp_path: Path) -> RuntimeDataSettings:
    return RuntimeDataSettings.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )


def _write_runtime_file(
    runtime_settings: RuntimeDataSettings,
    log_file_ref: str,
    lines: list[str],
) -> Path:
    path = runtime_settings.root / log_file_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _run_log_row(
    *,
    log_id: str,
    run_id: str,
    log_file_ref: str,
    line_offset: int = 0,
    line_number: int = 1,
    category: LogCategory = LogCategory.RUNTIME,
    level: LogLevel = LogLevel.DEBUG,
    payload_ref: str | None = None,
    approval_id: str | None = None,
    tool_confirmation_id: str | None = None,
    delivery_record_id: str | None = None,
):
    return RunLogEntryModel(
        log_id=log_id,
        session_id="session-1",
        run_id=run_id,
        stage_run_id=f"stage-{run_id}",
        approval_id=approval_id,
        tool_confirmation_id=tool_confirmation_id,
        delivery_record_id=delivery_record_id,
        graph_thread_id=f"graph-thread-{run_id}",
        request_id=f"request-{log_id}",
        source="runtime.stage",
        category=category,
        level=level,
        message=f"Runtime log {log_id}.",
        log_file_ref=log_file_ref,
        line_offset=line_offset,
        line_number=line_number,
        log_file_generation=Path(log_file_ref).stem,
        payload_ref=payload_ref,
        payload_excerpt=None,
        payload_size_bytes=0,
        redaction_status=RedactionStatus.NOT_REQUIRED,
        correlation_id=f"correlation-{log_id}",
        trace_id=f"trace-{run_id}",
        span_id=f"span-{log_id}",
        parent_span_id=None,
        duration_ms=None,
        error_code=None,
        created_at=OLD_LOG_TIME,
    )


def _payload(payload_id: str) -> LogPayloadModel:
    return LogPayloadModel(
        payload_id=payload_id,
        payload_type="debug_summary",
        summary={"message": payload_id},
        storage_ref=None,
        content_hash=f"sha256:{payload_id}",
        redaction_status=RedactionStatus.NOT_REQUIRED,
        payload_size_bytes=16,
        schema_version="log-payload-v1",
        created_at=OLD_LOG_TIME,
    )


def _audit_row(audit_id: str, *, metadata_ref: str | None = None) -> AuditLogEntryModel:
    return AuditLogEntryModel(
        audit_id=audit_id,
        actor_type=AuditActorType.SYSTEM,
        actor_id="system-runtime",
        action="tool_confirmation.allow",
        target_type="tool_confirmation",
        target_id="tool-confirmation-old",
        session_id="session-1",
        run_id="run-old",
        stage_run_id="stage-old",
        approval_id=None,
        tool_confirmation_id="tool-confirmation-old",
        delivery_record_id=None,
        request_id=f"request-{audit_id}",
        result=AuditResult.SUCCEEDED,
        reason="Audit rows use a separate retention threshold.",
        metadata_ref=metadata_ref,
        metadata_excerpt="audit excerpt",
        correlation_id=f"correlation-{audit_id}",
        trace_id=f"trace-{audit_id}",
        span_id=f"span-{audit_id}",
        audit_file_ref="logs/audit.jsonl",
        audit_file_generation="audit",
        audit_file_write_failed=False,
        created_at=OLD_LOG_TIME,
    )


def test_rotate_if_needed_moves_oversized_run_log_and_repoints_index(tmp_path) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    log_file_ref = "logs/runs/run-1.jsonl"
    first_line = '{"log_id":"log-1"}\n'
    second_line = '{"log_id":"log-2"}\n'
    original_path = _write_runtime_file(
        runtime_settings,
        log_file_ref,
        [first_line, second_line],
    )

    with manager.session(DatabaseRole.LOG) as session:
        session.add_all(
            [
                _run_log_row(
                    log_id="log-1",
                    run_id="run-1",
                    log_file_ref=log_file_ref,
                    line_offset=0,
                    line_number=1,
                ),
                _run_log_row(
                    log_id="log-2",
                    run_id="run-1",
                    log_file_ref=log_file_ref,
                    line_offset=len(first_line.encode("utf-8")),
                    line_number=2,
                ),
            ]
        )
        session.commit()

        result = LogRetentionService(runtime_settings, session).rotate_if_needed(
            log_file_ref,
            max_bytes=10,
            now=NOW,
        )

        first_saved = session.get(RunLogEntryModel, "log-1")
        second_saved = session.get(RunLogEntryModel, "log-2")

    assert result.rotated is True
    assert result.reason == "size"
    assert result.original_log_file_ref == log_file_ref
    assert result.rotated_log_file_ref == "logs/runs/run-1.20260501T090000Z.jsonl"
    assert result.log_file_generation == "run-1.20260501T090000Z"
    assert not original_path.exists()
    assert (runtime_settings.root / result.rotated_log_file_ref).read_text(
        encoding="utf-8"
    ) == first_line + second_line
    assert first_saved is not None
    assert first_saved.log_file_ref == result.rotated_log_file_ref
    assert first_saved.line_offset == 0
    assert first_saved.line_number == 1
    assert first_saved.log_file_generation == result.log_file_generation
    assert second_saved is not None
    assert second_saved.line_offset == len(first_line.encode("utf-8"))
    assert second_saved.line_number == 2


def test_rotate_if_needed_uses_date_boundary_when_file_is_from_previous_day(
    tmp_path,
) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    log_file_ref = "logs/runs/run-date.jsonl"
    original_path = _write_runtime_file(
        runtime_settings,
        log_file_ref,
        ['{"log_id":"log-date"}\n'],
    )
    previous_day = NOW - timedelta(days=1)
    os.utime(original_path, (previous_day.timestamp(), previous_day.timestamp()))

    result = LogRetentionService(runtime_settings).rotate_if_needed(
        log_file_ref,
        max_bytes=1024 * 1024,
        now=NOW,
    )

    assert result.rotated is True
    assert result.reason == "date"
    assert result.rotated_log_file_ref == (
        "logs/runs/run-date.20260501T090000Z.jsonl"
    )
    assert not original_path.exists()
    assert (runtime_settings.root / result.rotated_log_file_ref).exists()


def test_rotate_if_needed_rejects_non_log_runtime_refs_without_moving_file(
    tmp_path,
) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    workspace_ref = "workspace/cache.jsonl"
    workspace_path = _write_runtime_file(
        runtime_settings,
        workspace_ref,
        ['{"not":"a platform log"}\n'],
    )

    with pytest.raises(ValueError, match="platform log file"):
        LogRetentionService(runtime_settings).rotate_if_needed(
            workspace_ref,
            max_bytes=10,
            now=NOW,
        )

    assert workspace_path.exists()
    assert not (
        runtime_settings.root / "workspace/cache.20260501T090000Z.jsonl"
    ).exists()


def test_rotate_if_needed_rejects_audit_log_refs_without_stale_audit_index(
    tmp_path,
) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    audit_log_ref = "logs/audit.jsonl"
    audit_log_path = _write_runtime_file(
        runtime_settings,
        audit_log_ref,
        ['{"audit_id":"audit-1"}\n'],
    )

    with pytest.raises(ValueError, match="run log file"):
        LogRetentionService(runtime_settings).rotate_if_needed(
            audit_log_ref,
            max_bytes=1,
            now=NOW,
        )

    assert audit_log_path.exists()
    assert not (runtime_settings.logs_dir / "audit.20260501T090000Z.jsonl").exists()


def test_rotate_if_needed_rejects_log_directories_without_renaming_them(
    tmp_path,
) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    runtime_settings.run_logs_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="regular log file"):
        LogRetentionService(runtime_settings).rotate_if_needed(
            "logs/runs",
            max_bytes=1,
            now=NOW,
        )

    assert runtime_settings.run_logs_dir.is_dir()
    assert not (runtime_settings.logs_dir / "runs.20260501T090000Z").exists()


def test_rotate_if_needed_restores_file_when_index_commit_fails(
    tmp_path,
    monkeypatch,
) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    log_file_ref = "logs/runs/run-commit-fail.jsonl"
    original_path = _write_runtime_file(
        runtime_settings,
        log_file_ref,
        ['{"log_id":"log-commit-fail"}\n'],
    )

    with manager.session(DatabaseRole.LOG) as session:
        session.add(
            _run_log_row(
                log_id="log-commit-fail",
                run_id="run-commit-fail",
                log_file_ref=log_file_ref,
            )
        )
        session.commit()

        def fail_commit() -> None:
            raise RuntimeError("simulated log index commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)

        with pytest.raises(RuntimeError, match="simulated log index commit failure"):
            LogRetentionService(runtime_settings, session).rotate_if_needed(
                log_file_ref,
                max_bytes=10,
                now=NOW,
            )

        saved_entry = session.get(RunLogEntryModel, "log-commit-fail")

    assert original_path.exists()
    assert not (
        runtime_settings.root / "logs/runs/run-commit-fail.20260501T090000Z.jsonl"
    ).exists()
    assert saved_entry is not None
    assert saved_entry.log_file_ref == log_file_ref


def test_cleanup_run_logs_deletes_expired_ordinary_logs_without_touching_domain_or_audit(
    tmp_path,
) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    old_log_ref = "logs/runs/run-old.jsonl"
    audit_log_ref = "logs/audit.jsonl"
    old_log_path = _write_runtime_file(
        runtime_settings,
        old_log_ref,
        ['{"log_id":"log-old-debug"}\n'],
    )
    audit_log_path = _write_runtime_file(
        runtime_settings,
        audit_log_ref,
        ['{"audit_id":"audit-old"}\n'],
    )

    with manager.session(DatabaseRole.LOG) as session:
        session.add_all([_payload("payload-old"), _payload("payload-audit")])
        session.flush()
        session.add(
            _run_log_row(
                log_id="log-old-debug",
                run_id="run-old",
                log_file_ref=old_log_ref,
                payload_ref="payload-old",
            )
        )
        session.add(_audit_row("audit-old", metadata_ref="payload-audit"))
        session.commit()

        result = LogRetentionService(runtime_settings, session).cleanup_run_logs(
            retention_days=30,
            now=NOW,
        )

        deleted_log = session.get(RunLogEntryModel, "log-old-debug")
        deleted_payload = session.get(LogPayloadModel, "payload-old")
        retained_audit = session.get(AuditLogEntryModel, "audit-old")
        retained_audit_payload = session.get(LogPayloadModel, "payload-audit")

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        retained_run = runtime_session.get(PipelineRunModel, "run-old")

    assert result.deleted_log_ids == ("log-old-debug",)
    assert result.deleted_payload_refs == ("payload-old",)
    assert result.deleted_file_refs == (old_log_ref,)
    assert deleted_log is None
    assert deleted_payload is None
    assert not old_log_path.exists()
    assert retained_audit is not None
    assert retained_audit_payload is not None
    assert audit_log_path.exists()
    assert retained_run is not None


def test_cleanup_run_logs_preserves_high_impact_rows_and_their_files(tmp_path) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    shared_log_ref = "logs/runs/run-old.jsonl"
    shared_log_path = _write_runtime_file(
        runtime_settings,
        shared_log_ref,
        [
            '{"log_id":"log-old-debug"}\n',
            '{"log_id":"log-old-security"}\n',
        ],
    )

    with manager.session(DatabaseRole.LOG) as session:
        session.add(
            _run_log_row(
                log_id="log-old-debug",
                run_id="run-old",
                log_file_ref=shared_log_ref,
            )
        )
        session.add(
            _run_log_row(
                log_id="log-old-security",
                run_id="run-old",
                log_file_ref=shared_log_ref,
                line_offset=len('{"log_id":"log-old-debug"}\n'.encode("utf-8")),
                line_number=2,
                category=LogCategory.SECURITY,
                level=LogLevel.WARNING,
                tool_confirmation_id="tool-confirmation-old",
            )
        )
        session.commit()

        result = LogRetentionService(runtime_settings, session).cleanup_run_logs(
            retention_days=30,
            now=NOW,
        )

        deleted_debug = session.get(RunLogEntryModel, "log-old-debug")
        retained_security = session.get(RunLogEntryModel, "log-old-security")

    assert result.deleted_log_ids == ("log-old-debug",)
    assert result.deleted_file_refs == ()
    assert result.retained_file_refs == (shared_log_ref,)
    assert result.protected_log_ids == ("log-old-security",)
    assert deleted_debug is None
    assert retained_security is not None
    assert retained_security.line_offset == len(
        '{"log_id":"log-old-debug"}\n'.encode("utf-8")
    )
    assert retained_security.line_number == 2
    assert shared_log_path.exists()


def test_cleanup_run_logs_rolls_back_index_when_file_unlink_fails(
    tmp_path,
    monkeypatch,
) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    old_log_ref = "logs/runs/run-locked.jsonl"
    old_log_path = _write_runtime_file(
        runtime_settings,
        old_log_ref,
        ['{"log_id":"log-locked"}\n'],
    )

    with manager.session(DatabaseRole.LOG) as session:
        session.add(_payload("payload-locked"))
        session.flush()
        session.add(
            _run_log_row(
                log_id="log-locked",
                run_id="run-locked",
                log_file_ref=old_log_ref,
                payload_ref="payload-locked",
            )
        )
        session.commit()

        original_unlink = Path.unlink

        def fail_locked_unlink(self: Path, missing_ok: bool = False) -> None:
            if self == old_log_path:
                raise PermissionError("simulated locked log file")
            original_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", fail_locked_unlink)

        with pytest.raises(PermissionError, match="simulated locked log file"):
            LogRetentionService(runtime_settings, session).cleanup_run_logs(
                retention_days=30,
                now=NOW,
            )

        retained_log = session.get(RunLogEntryModel, "log-locked")
        retained_payload = session.get(LogPayloadModel, "payload-locked")

    assert old_log_path.exists()
    assert retained_log is not None
    assert retained_log.log_file_ref == old_log_ref
    assert retained_payload is not None


def test_cleanup_run_logs_restores_file_when_index_commit_fails(
    tmp_path,
    monkeypatch,
) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    old_log_ref = "logs/runs/run-commit-fail.jsonl"
    old_log_path = _write_runtime_file(
        runtime_settings,
        old_log_ref,
        ['{"log_id":"log-cleanup-commit-fail"}\n'],
    )

    with manager.session(DatabaseRole.LOG) as session:
        session.add(_payload("payload-cleanup-commit-fail"))
        session.flush()
        session.add(
            _run_log_row(
                log_id="log-cleanup-commit-fail",
                run_id="run-cleanup-commit-fail",
                log_file_ref=old_log_ref,
                payload_ref="payload-cleanup-commit-fail",
            )
        )
        session.commit()

        def fail_commit() -> None:
            raise RuntimeError("simulated cleanup index commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)

        with pytest.raises(RuntimeError, match="simulated cleanup index commit failure"):
            LogRetentionService(runtime_settings, session).cleanup_run_logs(
                retention_days=30,
                now=NOW,
            )

        retained_log = session.get(RunLogEntryModel, "log-cleanup-commit-fail")
        retained_payload = session.get(LogPayloadModel, "payload-cleanup-commit-fail")

    assert old_log_path.exists()
    assert retained_log is not None
    assert retained_log.log_file_ref == old_log_ref
    assert retained_payload is not None


def test_cleanup_run_logs_filters_expired_rows_by_run_dimension(tmp_path) -> None:
    from backend.app.observability.retention import LogRetentionService

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    run_one_ref = "logs/runs/run-old.jsonl"
    run_two_ref = "logs/runs/run-other.jsonl"
    run_one_path = _write_runtime_file(
        runtime_settings,
        run_one_ref,
        ['{"log_id":"log-run-old"}\n'],
    )
    run_two_path = _write_runtime_file(
        runtime_settings,
        run_two_ref,
        ['{"log_id":"log-run-other"}\n'],
    )

    with manager.session(DatabaseRole.LOG) as session:
        session.add(
            _run_log_row(
                log_id="log-run-old",
                run_id="run-old",
                log_file_ref=run_one_ref,
            )
        )
        session.add(
            _run_log_row(
                log_id="log-run-other",
                run_id="run-other",
                log_file_ref=run_two_ref,
            )
        )
        session.commit()

        result = LogRetentionService(runtime_settings, session).cleanup_run_logs(
            retention_days=30,
            run_ids={"run-old"},
            now=NOW,
        )

        deleted_run_old = session.get(RunLogEntryModel, "log-run-old")
        retained_run_other = session.get(RunLogEntryModel, "log-run-other")

    assert result.deleted_log_ids == ("log-run-old",)
    assert result.deleted_file_refs == (run_one_ref,)
    assert deleted_run_old is None
    assert retained_run_other is not None
    assert not run_one_path.exists()
    assert run_two_path.exists()


def test_mark_log_expired_keeps_projection_row_with_stable_expired_status(
    tmp_path,
) -> None:
    from backend.app.observability.retention import (
        EXPIRED_LOG_FILE_REF,
        EXPIRED_LOG_MESSAGE,
        LogRetentionService,
    )

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    with manager.session(DatabaseRole.LOG) as session:
        session.add(
            _run_log_row(
                log_id="log-stale",
                run_id="run-active",
                log_file_ref="logs/runs/run-active.jsonl",
            )
        )
        session.commit()

        marked = LogRetentionService(runtime_settings, session).mark_log_expired(
            "log-stale"
        )

        saved_entry = session.get(RunLogEntryModel, "log-stale")

    assert marked is True
    assert saved_entry is not None
    assert saved_entry.message == EXPIRED_LOG_MESSAGE
    assert saved_entry.log_file_ref == EXPIRED_LOG_FILE_REF
    assert saved_entry.line_offset == 0
    assert saved_entry.line_number == 1
    assert saved_entry.log_file_generation == "expired"


def test_mark_log_expired_preserves_domain_linkage_for_retained_delivery_logs(
    tmp_path,
) -> None:
    from backend.app.observability.retention import (
        EXPIRED_LOG_FILE_REF,
        EXPIRED_LOG_MESSAGE,
        LogRetentionService,
    )

    runtime_settings = _runtime_settings(tmp_path)
    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    with manager.session(DatabaseRole.LOG) as session:
        session.add(
            _run_log_row(
                log_id="log-delivery-retained",
                run_id="run-delivery",
                log_file_ref="logs/runs/run-delivery.jsonl",
                delivery_record_id="delivery-retained",
            )
        )
        session.commit()

        marked = LogRetentionService(runtime_settings, session).mark_log_expired(
            "log-delivery-retained"
        )

        saved_entry = session.get(RunLogEntryModel, "log-delivery-retained")

    assert marked is True
    assert saved_entry is not None
    assert saved_entry.delivery_record_id == "delivery-retained"
    assert saved_entry.run_id == "run-delivery"
    assert saved_entry.message == EXPIRED_LOG_MESSAGE
    assert saved_entry.log_file_ref == EXPIRED_LOG_FILE_REF
