from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    PlatformRuntimeSettingsModel,
    ProjectModel,
    SessionModel,
)
from backend.app.db.models.log import LogBase, LogPayloadModel, RunLogEntryModel
from backend.app.db.models.runtime import PipelineRunModel, StageRunModel
from backend.app.domain.enums import StageStatus, StageType
from backend.app.observability.log_query import (
    LogQueryService,
    LogQueryServiceError,
    decode_cursor,
    encode_cursor,
)
from backend.app.repositories.runtime_settings import RUNTIME_SETTINGS_ID
from backend.app.schemas.observability import (
    LogCategory,
    LogLevel,
    RedactionStatus,
)
from backend.tests.projections.test_workspace_projection import (
    NOW,
    _default_internal_model_bindings,
    _manager,
    _seed_workspace,
)


LOG_TIMES = [
    NOW + timedelta(minutes=3),
    NOW + timedelta(minutes=3, seconds=30),
    NOW + timedelta(minutes=4),
    NOW + timedelta(minutes=5),
]


def _seed_runtime_settings(manager, *, default_limit: int = 2, max_limit: int = 3) -> None:
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


def _seed_runtime_settings_with_log_policy(manager, log_policy: dict[str, object]) -> None:
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
                log_policy=log_policy,
                created_by_actor_id=None,
                updated_by_actor_id=None,
                last_audit_log_id=None,
                last_trace_id=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def _seed_log_rows(manager, *, seed_settings: bool = True) -> None:
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    if seed_settings:
        _seed_runtime_settings(manager)
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            StageRunModel(
                stage_run_id="stage-secondary",
                run_id="run-active",
                stage_type=StageType.CODE_REVIEW,
                status=StageStatus.RUNNING,
                attempt_index=2,
                graph_node_key="code_review.main",
                stage_contract_ref="stage-contract-code-review",
                input_ref=None,
                output_ref=None,
                summary="A second stage in the same run.",
                started_at=NOW + timedelta(minutes=4),
                ended_at=None,
                created_at=NOW + timedelta(minutes=4),
                updated_at=NOW + timedelta(minutes=4),
            )
        )
        session.commit()

    with manager.session(DatabaseRole.LOG) as session:
        session.add(
            LogPayloadModel(
                payload_id="payload-1",
                payload_type="tool_output",
                summary={"stdout_excerpt": "pytest -q"},
                storage_ref=None,
                content_hash="sha256:payload-1",
                redaction_status=RedactionStatus.REDACTED,
                payload_size_bytes=256,
                schema_version="log-payload-v1",
                created_at=LOG_TIMES[0],
            )
        )
        session.add_all(
            [
                _log_row(
                    log_id="log-run-1",
                    run_id="run-active",
                    stage_run_id=None,
                    source="runtime.stage",
                    category=LogCategory.RUNTIME,
                    level=LogLevel.INFO,
                    message="Run started.",
                    created_at=LOG_TIMES[0],
                    line_number=1,
                ),
                _log_row(
                    log_id="log-run-2",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    source="tool.registry",
                    category=LogCategory.TOOL,
                    level=LogLevel.ERROR,
                    message="Tool call requires confirmation.",
                    created_at=LOG_TIMES[1],
                    line_number=2,
                    payload_ref="payload-1",
                    payload_excerpt="tool=bash risk=high_risk",
                    payload_size_bytes=256,
                    redaction_status=RedactionStatus.REDACTED,
                    error_code="tool_confirmation_required",
                ),
                _log_row(
                    log_id="log-run-3",
                    run_id="run-active",
                    stage_run_id="stage-secondary",
                    source="provider.deepseek",
                    category=LogCategory.MODEL,
                    level=LogLevel.WARNING,
                    message="Provider call retry scheduled.",
                    created_at=LOG_TIMES[2],
                    line_number=3,
                    payload_excerpt="backoff=2s",
                    payload_size_bytes=16,
                ),
                _log_row(
                    log_id="log-run-4",
                    run_id="run-active",
                    stage_run_id="stage-secondary",
                    source="provider.deepseek",
                    category=LogCategory.MODEL,
                    level=LogLevel.WARNING,
                    message="Provider call retry scheduled again.",
                    created_at=LOG_TIMES[2],
                    line_number=4,
                    payload_excerpt="backoff=4s",
                    payload_size_bytes=16,
                ),
                _log_row(
                    log_id="log-run-old",
                    run_id="run-old",
                    stage_run_id="stage-old",
                    source="runtime.stage",
                    category=LogCategory.RUNTIME,
                    level=LogLevel.ERROR,
                    message="Old run failure.",
                    created_at=LOG_TIMES[3],
                    line_number=5,
                ),
            ]
        )
        session.commit()


def _log_row(
    *,
    log_id: str,
    run_id: str,
    stage_run_id: str | None,
    source: str,
    category: LogCategory,
    level: LogLevel,
    message: str,
    created_at,
    line_number: int,
    payload_ref: str | None = None,
    payload_excerpt: str | None = None,
    payload_size_bytes: int = 0,
    redaction_status: RedactionStatus = RedactionStatus.NOT_REQUIRED,
    error_code: str | None = None,
) -> RunLogEntryModel:
    return RunLogEntryModel(
        log_id=log_id,
        session_id="session-1",
        run_id=run_id,
        stage_run_id=stage_run_id,
        approval_id=None,
        tool_confirmation_id="tool-confirmation-1" if payload_ref else None,
        delivery_record_id=None,
        graph_thread_id=f"graph-thread-{run_id}",
        request_id=f"request-{line_number}",
        source=source,
        category=category,
        level=level,
        message=message,
        log_file_ref=f"logs/runs/{run_id}.jsonl",
        line_offset=(line_number - 1) * 120,
        line_number=line_number,
        log_file_generation=run_id,
        payload_ref=payload_ref,
        payload_excerpt=payload_excerpt,
        payload_size_bytes=payload_size_bytes,
        redaction_status=redaction_status,
        correlation_id=f"correlation-{line_number}",
        trace_id=f"trace-{run_id}",
        span_id=f"span-{line_number}",
        parent_span_id=None,
        duration_ms=10 + line_number,
        error_code=error_code,
        created_at=created_at,
    )


def _service(manager) -> LogQueryService:
    return LogQueryService(
        manager.session(DatabaseRole.CONTROL),
        manager.session(DatabaseRole.RUNTIME),
        manager.session(DatabaseRole.LOG),
    )


class SettingsReadFailingSession(Session):
    def get(self, entity, ident, **kwargs):
        if entity is PlatformRuntimeSettingsModel:
            raise SQLAlchemyError("settings storage unavailable")
        return super().get(entity, ident, **kwargs)


def _service_with_settings_read_failure(manager) -> LogQueryService:
    control_session = SettingsReadFailingSession(bind=manager.engine(DatabaseRole.CONTROL))
    return LogQueryService(
        control_session,
        manager.session(DatabaseRole.RUNTIME),
        manager.session(DatabaseRole.LOG),
    )


def test_list_run_logs_pages_visible_run_with_stable_cursor_and_query_echo(tmp_path) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_log_rows(manager)
    service = _service(manager)

    first_page = service.list_run_logs("run-active")

    assert [entry.log_id for entry in first_page.entries] == ["log-run-1", "log-run-2"]
    assert first_page.has_more is True
    assert first_page.next_cursor is not None
    assert first_page.query.run_id == "run-active"
    assert first_page.query.stage_run_id is None
    assert first_page.query.limit == 2
    assert all(entry.run_id == "run-active" for entry in first_page.entries)

    second_page = service.list_run_logs("run-active", cursor=first_page.next_cursor)
    assert [entry.log_id for entry in second_page.entries] == ["log-run-3", "log-run-4"]
    assert second_page.has_more is False
    assert second_page.next_cursor is None


def test_cursor_helpers_round_trip_stable_order_key_and_reject_invalid_value() -> None:
    cursor = encode_cursor(LOG_TIMES[0], "log-run-1")

    assert decode_cursor(cursor) == (LOG_TIMES[0], "log-run-1")

    with pytest.raises(LogQueryServiceError) as exc_info:
        decode_cursor("not-a-cursor")
    assert exc_info.value.error_code == ErrorCode.LOG_QUERY_INVALID
    assert exc_info.value.status_code == 422


def test_list_stage_logs_scopes_to_visible_stage_and_supports_filters(tmp_path) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_log_rows(manager)
    service = _service(manager)

    response = service.list_stage_logs(
        "stage-active",
        level=LogLevel.ERROR,
        category=LogCategory.TOOL,
        source="tool.registry",
        since=LOG_TIMES[1],
        until=LOG_TIMES[1],
        limit=3,
    )

    assert [entry.log_id for entry in response.entries] == ["log-run-2"]
    assert response.has_more is False
    assert response.next_cursor is None
    assert response.query.run_id == "run-active"
    assert response.query.stage_run_id == "stage-active"
    assert response.query.level == LogLevel.ERROR
    assert response.query.category == LogCategory.TOOL
    assert response.query.source == "tool.registry"
    assert response.query.since == LOG_TIMES[1]
    assert response.query.until == LOG_TIMES[1]
    assert response.query.limit == 3
    assert all(entry.stage_run_id == "stage-active" for entry in response.entries)


def test_log_query_rejects_invalid_limits_and_cursors(tmp_path) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_log_rows(manager)
    service = _service(manager)

    for call in (
        lambda: service.list_run_logs("run-active", limit=0),
        lambda: service.list_run_logs("run-active", limit=4),
        lambda: service.list_run_logs("run-active", cursor="not-a-cursor"),
        lambda: service.list_run_logs(
            "run-active",
            since=LOG_TIMES[2],
            until=LOG_TIMES[1],
        ),
    ):
        with pytest.raises(LogQueryServiceError) as exc_info:
            call()
        assert exc_info.value.error_code == ErrorCode.LOG_QUERY_INVALID
        assert exc_info.value.status_code == 422


def test_log_query_reports_cross_project_run_ownership_mismatch_as_not_found(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_log_rows(manager)
    service = _service(manager)

    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-2",
                name="Other Project",
                root_path="C:/work/other-project",
                default_delivery_channel_id=None,
                is_default=False,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-active")
        assert run is not None
        run.project_id = "project-2"
        session.commit()

    with pytest.raises(LogQueryServiceError) as run_exc:
        service.list_run_logs("run-active")
    assert run_exc.value.error_code == ErrorCode.NOT_FOUND
    assert run_exc.value.status_code == 404
    assert run_exc.value.message == "Run logs were not found."

    with pytest.raises(LogQueryServiceError) as stage_exc:
        service.list_stage_logs("stage-active")
    assert stage_exc.value.error_code == ErrorCode.NOT_FOUND
    assert stage_exc.value.status_code == 404
    assert stage_exc.value.message == "Stage logs were not found."


def test_log_query_reports_hidden_or_missing_targets_as_not_found(tmp_path) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_log_rows(manager)
    service = _service(manager)

    for call, message in (
        (lambda: service.list_run_logs("run-missing"), "Run logs were not found."),
        (lambda: service.list_stage_logs("stage-missing"), "Stage logs were not found."),
    ):
        with pytest.raises(LogQueryServiceError) as exc_info:
            call()
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert exc_info.value.status_code == 404
        assert exc_info.value.message == message

    with manager.session(DatabaseRole.CONTROL) as session:
        visible_session = session.get(SessionModel, "session-1")
        assert visible_session is not None
        visible_session.is_visible = False
        visible_session.visibility_removed_at = NOW
        session.commit()

    for call, message in (
        (lambda: service.list_run_logs("run-active"), "Run logs were not found."),
        (lambda: service.list_stage_logs("stage-active"), "Stage logs were not found."),
    ):
        with pytest.raises(LogQueryServiceError) as exc_info:
            call()
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert exc_info.value.status_code == 404
        assert exc_info.value.message == message


def test_log_query_requires_canonical_valid_runtime_settings(tmp_path) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_log_rows(manager, seed_settings=False)
    service = _service(manager)

    with pytest.raises(LogQueryServiceError) as missing_exc:
        service.list_run_logs("run-active")
    assert missing_exc.value.error_code == ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert missing_exc.value.status_code == 503

    _seed_runtime_settings(manager, default_limit=4, max_limit=3)

    with pytest.raises(LogQueryServiceError) as invalid_exc:
        service.list_run_logs("run-active")
    assert invalid_exc.value.error_code == ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert invalid_exc.value.status_code == 503


def test_log_query_normalizes_settings_read_failure_as_config_unavailable(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_log_rows(manager)
    service = _service_with_settings_read_failure(manager)

    with pytest.raises(LogQueryServiceError) as exc_info:
        service.list_run_logs("run-active")
    assert exc_info.value.error_code == ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert exc_info.value.status_code == 503


def test_log_query_rejects_settings_without_dynamic_query_limit_fields(tmp_path) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_log_rows(manager, seed_settings=False)
    _seed_runtime_settings_with_log_policy(
        manager,
        {
            "run_log_retention_days": 30,
            "audit_log_retention_days": 180,
            "log_rotation_max_bytes": 10485760,
            "log_query_default_limit": 2,
        },
    )
    service = _service(manager)

    with pytest.raises(LogQueryServiceError) as exc_info:
        service.list_run_logs("run-active")
    assert exc_info.value.error_code == ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert exc_info.value.status_code == 503
