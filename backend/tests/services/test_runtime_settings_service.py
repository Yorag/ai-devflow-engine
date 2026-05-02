from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, PlatformRuntimeSettingsModel
from backend.app.db.session import DatabaseManager
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    LogPolicy,
    PlatformRuntimeSettingsUpdate,
    ProviderCallPolicy,
)


NOW = datetime(2026, 5, 2, 9, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 2, 9, 5, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append(
            {
                "method": "record_rejected_command",
                "result": AuditResult.REJECTED,
                **kwargs,
            }
        )
        return object()


class RecordingLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FailingAuditService(RecordingAuditService):
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


class FailingRejectedAuditService(RecordingAuditService):
    def record_rejected_command(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


class FailingLogWriter(RecordingLogWriter):
    def write(self, record: LogRecordInput) -> object:
        raise OSError("jsonl unavailable")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-runtime-settings",
        trace_id="trace-runtime-settings",
        correlation_id="correlation-runtime-settings",
        span_id="span-runtime-settings",
        parent_span_id=None,
        created_at=NOW,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    return manager


def action_records(audit: RecordingAuditService, action: str) -> list[dict[str, Any]]:
    return [record for record in audit.records if record["action"] == action]


def test_get_current_settings_initializes_defaults_once_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = PlatformRuntimeSettingsService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: NOW,
        )
        settings = service.get_current_settings(trace_context=build_trace())
        settings_again = service.get_current_settings(trace_context=build_trace())
        rows = session.query(PlatformRuntimeSettingsModel).all()

    assert len(rows) == 1
    assert settings.settings_id == "platform-runtime-settings"
    assert settings.version.config_version == "runtime-settings-v1"
    assert settings.version.schema_version == "runtime-settings-schema-v1"
    assert settings.version.hard_limits_version == "platform-hard-limits-v1"
    assert settings.agent_limits.max_react_iterations_per_stage == 30
    assert settings.provider_call_policy.request_timeout_seconds == 60
    assert settings.context_limits.compression_threshold_ratio == 0.8
    assert settings.log_policy.log_query_default_limit == 100
    assert settings_again.version.config_version == settings.version.config_version
    assert len(action_records(audit, "runtime_settings.initialize")) == 1
    assert log_writer.records[0].message == "PlatformRuntimeSettings initialized."
    assert log_writer.records[0].payload.payload_type == "runtime_settings_initialize"


def test_get_current_settings_maps_initialization_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        def fail_commit() -> None:
            raise SQLAlchemyError("commit unavailable")

        monkeypatch.setattr(session, "commit", fail_commit)
        service = PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        )
        with pytest.raises(RuntimeSettingsServiceError) as exc_info:
            service.get_current_settings(trace_context=build_trace())

    assert exc_info.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert exc_info.value.status_code == 503


def test_update_settings_merges_partial_groups_increments_version_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = PlatformRuntimeSettingsService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: NOW,
        )
        current = service.get_current_settings(trace_context=build_trace())
        updated = PlatformRuntimeSettingsService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).update_settings(
            PlatformRuntimeSettingsUpdate(
                expected_config_version=current.version.config_version,
                agent_limits=AgentRuntimeLimits(max_tool_calls_per_stage=70),
                context_limits=ContextLimits(compression_threshold_ratio=0.75),
            ),
            trace_context=build_trace(),
        )
        row = session.get(PlatformRuntimeSettingsModel, "platform-runtime-settings")

    assert updated.version.config_version == "runtime-settings-v2"
    assert updated.version.updated_at == LATER
    assert updated.agent_limits.max_tool_calls_per_stage == 70
    assert updated.agent_limits.max_react_iterations_per_stage == 30
    assert updated.context_limits.compression_threshold_ratio == 0.75
    assert updated.provider_call_policy.request_timeout_seconds == 60
    assert row is not None
    assert row.config_version == "runtime-settings-v2"
    assert row.updated_by_actor_id == "api-user"
    update_audit = action_records(audit, "runtime_settings.update")[0]
    assert update_audit["actor_type"] is AuditActorType.USER
    assert update_audit["target_type"] == "platform_runtime_settings"
    assert update_audit["target_id"] == "platform-runtime-settings"
    assert update_audit["metadata"]["previous_config_version"] == "runtime-settings-v1"
    assert update_audit["metadata"]["new_config_version"] == "runtime-settings-v2"
    assert (
        "agent_limits.max_tool_calls_per_stage"
        in update_audit["metadata"]["changed_fields"]
    )
    assert (
        "context_limits.compression_threshold_ratio"
        in update_audit["metadata"]["changed_fields"]
    )
    assert log_writer.records[-1].payload.payload_type == "runtime_settings_update"


def test_update_settings_rejects_stale_expected_version_without_overwrite(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = PlatformRuntimeSettingsService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: NOW,
        )
        service.get_current_settings(trace_context=build_trace())
        with pytest.raises(RuntimeSettingsServiceError) as exc_info:
            service.update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version="runtime-settings-v0",
                    agent_limits=AgentRuntimeLimits(max_tool_calls_per_stage=70),
                ),
                trace_context=build_trace(),
            )
        row = session.get(PlatformRuntimeSettingsModel, "platform-runtime-settings")

    assert exc_info.value.error_code is ErrorCode.CONFIG_VERSION_CONFLICT
    assert exc_info.value.status_code == 409
    assert row is not None
    assert row.config_version == "runtime-settings-v1"
    assert row.agent_limits["max_tool_calls_per_stage"] == 80
    rejected = action_records(audit, "runtime_settings.update.rejected")[0]
    assert rejected["metadata"]["error_code"] == "config_version_conflict"


def test_update_settings_rejects_concurrent_stale_session_without_overwrite(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)
    audit_a = RecordingAuditService()
    audit_b = RecordingAuditService()

    session_a = manager.session(DatabaseRole.CONTROL)
    session_b = manager.session(DatabaseRole.CONTROL)
    try:
        service_a = PlatformRuntimeSettingsService(
            session_a,
            audit_service=audit_a,
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        )
        initial = service_a.get_current_settings(trace_context=build_trace())

        service_b = PlatformRuntimeSettingsService(
            session_b,
            audit_service=audit_b,
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        )
        stale = service_b.get_current_settings(trace_context=build_trace())

        service_a.update_settings(
            PlatformRuntimeSettingsUpdate(
                expected_config_version=initial.version.config_version,
                agent_limits=AgentRuntimeLimits(max_tool_calls_per_stage=70),
            ),
            trace_context=build_trace(),
        )

        with pytest.raises(RuntimeSettingsServiceError) as exc_info:
            service_b.update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version=stale.version.config_version,
                    context_limits=ContextLimits(compression_threshold_ratio=0.75),
                ),
                trace_context=build_trace(),
            )
    finally:
        session_a.close()
        session_b.close()

    assert exc_info.value.error_code is ErrorCode.CONFIG_VERSION_CONFLICT
    with manager.session(DatabaseRole.CONTROL) as session:
        row = session.get(PlatformRuntimeSettingsModel, "platform-runtime-settings")
    assert row is not None
    assert row.config_version == "runtime-settings-v2"
    assert row.agent_limits["max_tool_calls_per_stage"] == 70
    assert row.context_limits["compression_threshold_ratio"] == 0.8
    rejected = action_records(audit_b, "runtime_settings.update.rejected")[0]
    assert rejected["metadata"]["error_code"] == "config_version_conflict"


def test_update_settings_rejects_hard_limit_violation_and_empty_update(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = PlatformRuntimeSettingsService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: NOW,
        )
        current = service.get_current_settings(trace_context=build_trace())
        with pytest.raises(RuntimeSettingsServiceError) as hard_limit:
            service.update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version=current.version.config_version,
                    agent_limits=AgentRuntimeLimits(
                        max_react_iterations_per_stage=51,
                    ),
                ),
                trace_context=build_trace(),
            )
        with pytest.raises(RuntimeSettingsServiceError) as empty:
            service.update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version=current.version.config_version,
                ),
                trace_context=build_trace(),
            )
        row = session.get(PlatformRuntimeSettingsModel, "platform-runtime-settings")

    assert hard_limit.value.error_code is ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED
    assert hard_limit.value.status_code == 422
    assert "agent_limits.max_react_iterations_per_stage" in hard_limit.value.message
    assert empty.value.error_code is ErrorCode.CONFIG_INVALID_VALUE
    assert row is not None
    assert row.config_version == "runtime-settings-v1"
    rejected_metadata = [
        record["metadata"]
        for record in action_records(audit, "runtime_settings.update.rejected")
    ]
    assert any(
        item["error_code"] == "config_hard_limit_exceeded"
        for item in rejected_metadata
    )
    assert any(item["error_code"] == "config_invalid_value" for item in rejected_metadata)


def test_rejected_update_observability_failures_map_to_storage_unavailable(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        initial = PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        ).get_current_settings(trace_context=build_trace())

        with pytest.raises(RuntimeSettingsServiceError) as log_failure:
            PlatformRuntimeSettingsService(
                session,
                audit_service=RecordingAuditService(),
                log_writer=FailingLogWriter(),
                now=lambda: LATER,
            ).update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version="runtime-settings-v0",
                    agent_limits=AgentRuntimeLimits(max_tool_calls_per_stage=70),
                ),
                trace_context=build_trace(),
            )
        with pytest.raises(RuntimeSettingsServiceError) as audit_failure:
            PlatformRuntimeSettingsService(
                session,
                audit_service=FailingRejectedAuditService(),
                log_writer=RecordingLogWriter(),
                now=lambda: LATER,
            ).update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version="runtime-settings-v0",
                    context_limits=ContextLimits(compression_threshold_ratio=0.75),
                ),
                trace_context=build_trace(),
            )
        row = session.get(PlatformRuntimeSettingsModel, "platform-runtime-settings")

    assert log_failure.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert log_failure.value.status_code == 503
    assert audit_failure.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert audit_failure.value.status_code == 503
    assert row is not None
    assert row.config_version == initial.version.config_version
    assert row.agent_limits["max_tool_calls_per_stage"] == 80
    assert row.context_limits["compression_threshold_ratio"] == 0.8


def test_update_settings_maps_audit_write_failure_after_control_commit(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        initial = PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        ).get_current_settings(trace_context=build_trace())

        with pytest.raises(RuntimeSettingsServiceError) as audit_failure:
            PlatformRuntimeSettingsService(
                session,
                audit_service=FailingAuditService(),
                log_writer=RecordingLogWriter(),
                now=lambda: LATER,
            ).update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version=initial.version.config_version,
                    log_policy=LogPolicy(log_query_max_limit=300),
                ),
                trace_context=build_trace(),
            )
        row_after_audit_failure = session.get(
            PlatformRuntimeSettingsModel,
            "platform-runtime-settings",
        )

    assert audit_failure.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert audit_failure.value.status_code == 503
    assert row_after_audit_failure is not None
    assert row_after_audit_failure.config_version == "runtime-settings-v2"
    assert row_after_audit_failure.log_policy["log_query_max_limit"] == 300


def test_update_settings_maps_log_write_failure_after_control_commit(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)
    log_failure_audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        initial = PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        ).get_current_settings(trace_context=build_trace())

        with pytest.raises(RuntimeSettingsServiceError) as log_failure:
            PlatformRuntimeSettingsService(
                session,
                audit_service=log_failure_audit,
                log_writer=FailingLogWriter(),
                now=lambda: LATER,
            ).update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version=initial.version.config_version,
                    provider_call_policy=ProviderCallPolicy(
                        request_timeout_seconds=45,
                    ),
                ),
                trace_context=build_trace(),
            )

    with manager.session(DatabaseRole.CONTROL) as verify_session:
        row_after_log_failure = verify_session.get(
            PlatformRuntimeSettingsModel,
            "platform-runtime-settings",
        )

    assert log_failure.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert log_failure.value.status_code == 503
    assert row_after_log_failure is not None
    assert row_after_log_failure.config_version == "runtime-settings-v2"
    assert row_after_log_failure.provider_call_policy["request_timeout_seconds"] == 45
    failed = action_records(log_failure_audit, "runtime_settings.update.failed")[0]
    assert failed["result"] is AuditResult.FAILED
    assert failed["metadata"]["error_code"] == "config_storage_unavailable"


def test_update_settings_commit_failure_does_not_record_success_audit_or_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        initial = PlatformRuntimeSettingsService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: NOW,
        ).get_current_settings(trace_context=build_trace())
        audit.records.clear()
        log_writer.records.clear()

        def fail_commit() -> None:
            raise SQLAlchemyError("commit unavailable")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeSettingsServiceError) as exc_info:
            PlatformRuntimeSettingsService(
                session,
                audit_service=audit,
                log_writer=log_writer,
                now=lambda: LATER,
            ).update_settings(
                PlatformRuntimeSettingsUpdate(
                    expected_config_version=initial.version.config_version,
                    agent_limits=AgentRuntimeLimits(max_tool_calls_per_stage=70),
                ),
                trace_context=build_trace(),
            )

    assert exc_info.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert not action_records(audit, "runtime_settings.update")
    assert all(
        record.message != "PlatformRuntimeSettings updated."
        for record in log_writer.records
    )


def test_validate_against_hard_limits_covers_provider_context_and_log_policy(
    tmp_path: Path,
) -> None:
    from backend.app.services.runtime_settings import (
        PlatformRuntimeSettingsService,
        RuntimeSettingsServiceError,
    )

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        service = PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        )
        current = service.get_current_settings(trace_context=build_trace())
        cases = [
            PlatformRuntimeSettingsUpdate(
                expected_config_version=current.version.config_version,
                provider_call_policy=ProviderCallPolicy(request_timeout_seconds=301),
            ),
            PlatformRuntimeSettingsUpdate(
                expected_config_version=current.version.config_version,
                context_limits=ContextLimits(file_read_max_chars=500001),
            ),
            PlatformRuntimeSettingsUpdate(
                expected_config_version=current.version.config_version,
                log_policy=LogPolicy(log_query_max_limit=5001),
            ),
        ]
        for body in cases:
            with pytest.raises(RuntimeSettingsServiceError) as exc_info:
                service.update_settings(body, trace_context=build_trace())
            assert exc_info.value.error_code is ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED
