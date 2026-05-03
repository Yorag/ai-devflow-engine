from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    PlatformRuntimeSettingsModel,
    ProjectModel,
    SessionModel,
)
from backend.app.db.models.event import EventBase
from backend.app.db.models.log import LogBase, LogPayloadModel, RunLogEntryModel
from backend.app.db.models.runtime import (
    ClarificationRecordModel,
    RunControlRecordModel,
    RuntimeBase,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.repositories.runtime_settings import RUNTIME_SETTINGS_ID
from backend.app.schemas.common import RunControlRecordType, StageType
from backend.app.main import create_app
from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus
from backend.tests.projections.test_workspace_projection import (
    _default_internal_model_bindings,
    _seed_workspace,
)


NOW = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)


def build_query_api_app(tmp_path: Path):
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
    _seed_workspace(app.state.database_manager)
    return app


def _seed_control_item_projection(app) -> None:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                ClarificationRecordModel(
                    clarification_id="clarification-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    question="Should the change affect backend only?",
                    answer=None,
                    payload_ref="clarification-payload-1",
                    graph_interrupt_ref="interrupt-clarification-1",
                    requested_at=NOW.replace(minute=8),
                    answered_at=None,
                    created_at=NOW.replace(minute=8),
                    updated_at=NOW.replace(minute=8),
                ),
                RunControlRecordModel(
                    control_record_id="control-clarification-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    control_type=RunControlRecordType.CLARIFICATION_WAIT,
                    source_stage_type=StageType.CODE_GENERATION,
                    target_stage_type=StageType.CODE_GENERATION,
                    payload_ref="clarification-1",
                    graph_interrupt_ref="interrupt-clarification-1",
                    occurred_at=NOW.replace(minute=8),
                    created_at=NOW.replace(minute=8),
                ),
                StageArtifactModel(
                    artifact_id="artifact-control-clarification-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    artifact_type="control_item_trace",
                    payload_ref="payload-control-clarification-1",
                    process={
                        "control_record_id": "control-clarification-1",
                        "trigger_reason": "Need the user to clarify file scope.",
                        "context_refs": ["requirement-clarification-1"],
                        "control_process_trace_ref": "control-trace-clarification-1",
                        "history_attempt_refs": ["run-active:attempt-2"],
                        "output_snapshot": {"result_status": "waiting_clarification"},
                        "log_refs": ["log-control-clarification-1"],
                    },
                    metrics={"retry_index": 0, "source_attempt_index": 1},
                    created_at=NOW.replace(minute=8, second=5),
                ),
            ]
        )
        session.commit()


def _seed_tool_confirmation_detail_projection(app) -> None:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                RunControlRecordModel(
                    control_record_id="control-tool-confirmation-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    control_type=RunControlRecordType.TOOL_CONFIRMATION,
                    source_stage_type=StageType.CODE_GENERATION,
                    target_stage_type=StageType.CODE_GENERATION,
                    payload_ref="tool-confirmation-1",
                    graph_interrupt_ref="interrupt-tool-1",
                    occurred_at=NOW.replace(minute=7),
                    created_at=NOW.replace(minute=7),
                ),
                StageArtifactModel(
                    artifact_id="artifact-tool-confirmation-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    artifact_type="tool_confirmation_trace",
                    payload_ref="payload-tool-confirmation-1",
                    process={
                        "tool_confirmation_id": "tool-confirmation-1",
                        "confirmation_object_ref": "tool-call-1",
                        "tool_confirmation_trace_ref": "process-tool-confirmation-1",
                        "tool_call_ref": "tool-call-1",
                        "tool_result_ref": "tool-result-1",
                        "audit_ref": "audit-tool-confirmation-1",
                        "side_effect_refs": ["side-effect-package-lock"],
                        "context_refs": ["requirement-tool-confirmation-1"],
                        "result_snapshot": {
                            "result_status": "waiting_tool_confirmation",
                            "follow_up_result": "awaiting user decision",
                            "tool_result_ref": "tool-result-1",
                        },
                        "log_refs": ["log-tool-confirmation-1"],
                    },
                    metrics={"retry_index": 0, "source_attempt_index": 1},
                    created_at=NOW.replace(minute=7, second=5),
                ),
            ]
        )
        session.commit()


def _seed_log_query_rows(app) -> None:
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
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            StageRunModel(
                stage_run_id="stage-other",
                run_id="run-active",
                stage_type=StageType.CODE_REVIEW,
                status="running",
                attempt_index=2,
                graph_node_key="code_review.main",
                stage_contract_ref="stage-contract-code-review",
                input_ref=None,
                output_ref=None,
                summary="Another stage in the same run.",
                started_at=NOW + timedelta(minutes=5),
                ended_at=None,
                created_at=NOW + timedelta(minutes=5),
                updated_at=NOW + timedelta(minutes=5),
            )
        )
        session.commit()
    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        session.add(
            LogPayloadModel(
                payload_id="payload-query-1",
                payload_type="tool_output",
                summary={"stdout_excerpt": "pytest -q"},
                storage_ref=None,
                content_hash="sha256:payload-query-1",
                redaction_status=RedactionStatus.REDACTED,
                payload_size_bytes=128,
                schema_version="log-payload-v1",
                created_at=NOW + timedelta(minutes=3),
            )
        )
        session.add_all(
            [
                _log_query_row(
                    log_id="log-api-1",
                    stage_run_id=None,
                    source="runtime.stage",
                    category=LogCategory.RUNTIME,
                    level=LogLevel.INFO,
                    message="Run started.",
                    created_at=NOW + timedelta(minutes=3),
                    line_number=1,
                ),
                _log_query_row(
                    log_id="log-api-2",
                    stage_run_id="stage-active",
                    source="tool.registry",
                    category=LogCategory.TOOL,
                    level=LogLevel.ERROR,
                    message="Tool call requires confirmation.",
                    created_at=NOW + timedelta(minutes=4),
                    line_number=2,
                    payload_ref="payload-query-1",
                    payload_excerpt="tool=bash risk=high_risk",
                    payload_size_bytes=128,
                    redaction_status=RedactionStatus.REDACTED,
                    error_code="tool_confirmation_required",
                ),
                _log_query_row(
                    log_id="log-api-other-stage",
                    stage_run_id="stage-other",
                    source="provider.deepseek",
                    category=LogCategory.MODEL,
                    level=LogLevel.WARNING,
                    message="Another stage row.",
                    created_at=NOW + timedelta(minutes=5),
                    line_number=3,
                    payload_excerpt="backoff=2s",
                    payload_size_bytes=16,
                ),
            ]
        )
        session.commit()


def _log_query_row(
    *,
    log_id: str,
    stage_run_id: str | None,
    source: str,
    category: LogCategory,
    level: LogLevel,
    message: str,
    created_at: datetime,
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
        run_id="run-active",
        stage_run_id=stage_run_id,
        approval_id=None,
        tool_confirmation_id="tool-confirmation-1" if payload_ref else None,
        delivery_record_id=None,
        graph_thread_id="graph-thread-active",
        request_id=f"request-{line_number}",
        source=source,
        category=category,
        level=level,
        message=message,
        log_file_ref="logs/runs/run-active.jsonl",
        line_offset=(line_number - 1) * 140,
        line_number=line_number,
        log_file_generation="run-active",
        payload_ref=payload_ref,
        payload_excerpt=payload_excerpt,
        payload_size_bytes=payload_size_bytes,
        redaction_status=redaction_status,
        correlation_id=f"correlation-{line_number}",
        trace_id="trace-run-active",
        span_id=f"span-{line_number}",
        parent_span_id=None,
        duration_ms=10 + line_number,
        error_code=error_code,
        created_at=created_at,
    )


def test_get_session_workspace_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/sessions/session-1/workspace",
            headers={
                "X-Request-ID": "req-workspace",
                "X-Correlation-ID": "corr-workspace",
            },
        )
        missing_response = client.get(
            "/api/sessions/session-missing/workspace",
            headers={
                "X-Request-ID": "req-workspace-missing",
                "X-Correlation-ID": "corr-workspace-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["session"]["session_id"] == "session-1"
    assert payload["project"]["project_id"] == "project-1"
    assert payload["current_run_id"] == "run-active"
    assert payload["composer_state"]["bound_run_id"] == "run-active"
    assert payload["composer_state"]["is_input_enabled"] is False
    assert payload["composer_state"]["primary_action"] == "pause"
    assert any(entry["type"] == "tool_confirmation" for entry in payload["narrative_feed"])

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Session workspace was not found.",
        "request_id": "req-workspace-missing",
        "correlation_id": "corr-workspace-missing",
    }


def test_get_run_timeline_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/runs/run-active/timeline",
            headers={
                "X-Request-ID": "req-timeline",
                "X-Correlation-ID": "corr-timeline",
            },
        )
        missing_response = client.get(
            "/api/runs/run-missing/timeline",
            headers={
                "X-Request-ID": "req-timeline-missing",
                "X-Correlation-ID": "corr-timeline-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["run_id"] == "run-active"
    assert payload["session_id"] == "session-1"
    assert payload["attempt_index"] == 2
    assert payload["trigger_source"] == "retry"
    assert payload["status"] == "waiting_tool_confirmation"
    assert payload["current_stage_type"] == "code_generation"
    assert [entry["run_id"] for entry in payload["entries"]] == [
        "run-active",
        "run-active",
        "run-active",
    ]
    assert [entry["type"] for entry in payload["entries"]] == [
        "user_message",
        "stage_node",
        "tool_confirmation",
    ]
    assert any(entry["type"] == "tool_confirmation" for entry in payload["entries"])

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Run timeline was not found.",
        "request_id": "req-timeline-missing",
        "correlation_id": "corr-timeline-missing",
    }


def test_get_run_logs_returns_paginated_filtered_entries_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _seed_log_query_rows(app)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/runs/run-active/logs",
            params={"limit": "2"},
            headers={
                "X-Request-ID": "req-run-logs",
                "X-Correlation-ID": "corr-run-logs",
            },
        )
        filtered_response = client.get(
            "/api/runs/run-active/logs",
            params={
                "level": "error",
                "category": "tool",
                "source": "tool.registry",
                "limit": "3",
            },
            headers={
                "X-Request-ID": "req-run-logs-filtered",
                "X-Correlation-ID": "corr-run-logs-filtered",
            },
        )
        missing_response = client.get(
            "/api/runs/run-missing/logs",
            headers={
                "X-Request-ID": "req-run-logs-missing",
                "X-Correlation-ID": "corr-run-logs-missing",
            },
        )

    assert ok_response.status_code == 200
    ok_payload = ok_response.json()
    assert [entry["log_id"] for entry in ok_payload["entries"]] == [
        "log-api-1",
        "log-api-2",
    ]
    assert ok_payload["has_more"] is True
    assert ok_payload["next_cursor"]
    assert ok_payload["query"]["run_id"] == "run-active"
    assert ok_payload["query"]["stage_run_id"] is None
    assert ok_payload["query"]["limit"] == 2

    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.json()
    assert [entry["log_id"] for entry in filtered_payload["entries"]] == ["log-api-2"]
    assert filtered_payload["has_more"] is False
    assert filtered_payload["query"]["level"] == "error"
    assert filtered_payload["query"]["category"] == "tool"
    assert filtered_payload["query"]["source"] == "tool.registry"

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Run logs were not found.",
        "request_id": "req-run-logs-missing",
        "correlation_id": "corr-run-logs-missing",
    }


def test_get_stage_logs_scopes_to_stage_and_rejects_invalid_limit(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _seed_log_query_rows(app)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/stages/stage-active/logs",
            headers={
                "X-Request-ID": "req-stage-logs",
                "X-Correlation-ID": "corr-stage-logs",
            },
        )
        invalid_limit_response = client.get(
            "/api/stages/stage-active/logs",
            params={"limit": "999"},
            headers={
                "X-Request-ID": "req-stage-logs-invalid",
                "X-Correlation-ID": "corr-stage-logs-invalid",
            },
        )
        missing_stage_response = client.get(
            "/api/stages/stage-missing/logs",
            headers={
                "X-Request-ID": "req-stage-logs-missing",
                "X-Correlation-ID": "corr-stage-logs-missing",
            },
        )
        malformed_limit_response = client.get(
            "/api/runs/run-active/logs",
            params={"limit": "not-an-int"},
            headers={
                "X-Request-ID": "req-run-logs-malformed-limit",
                "X-Correlation-ID": "corr-run-logs-malformed-limit",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert [entry["log_id"] for entry in payload["entries"]] == ["log-api-2"]
    assert payload["query"]["stage_run_id"] == "stage-active"
    assert all(entry["stage_run_id"] == "stage-active" for entry in payload["entries"])

    assert invalid_limit_response.status_code == 422
    assert invalid_limit_response.json() == {
        "error_code": "log_query_invalid",
        "message": "Log query is invalid.",
        "request_id": "req-stage-logs-invalid",
        "correlation_id": "corr-stage-logs-invalid",
    }
    assert missing_stage_response.status_code == 404
    assert missing_stage_response.json() == {
        "error_code": "not_found",
        "message": "Stage logs were not found.",
        "request_id": "req-stage-logs-missing",
        "correlation_id": "corr-stage-logs-missing",
    }
    assert malformed_limit_response.status_code == 422
    assert malformed_limit_response.json() == {
        "error_code": "log_query_invalid",
        "message": "Log query is invalid.",
        "request_id": "req-run-logs-malformed-limit",
        "correlation_id": "corr-run-logs-malformed-limit",
    }


def test_get_run_logs_returns_config_unavailable_when_runtime_settings_missing(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/runs/run-active/logs",
            headers={
                "X-Request-ID": "req-run-logs-config-missing",
                "X-Correlation-ID": "corr-run-logs-config-missing",
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "error_code": "config_snapshot_unavailable",
        "message": "Configuration snapshot is unavailable.",
        "request_id": "req-run-logs-config-missing",
        "correlation_id": "corr-run-logs-config-missing",
    }


def test_session_event_stream_returns_event_store_frames(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/sessions/session-1/events/stream",
            params={"after": 0, "limit": 1},
            headers={
                "X-Request-ID": "req-event-stream",
                "X-Correlation-ID": "corr-event-stream",
            },
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = []
            for line in response.iter_lines():
                lines.append(line)
                if line == "":
                    break

    assert "event: session_message_appended" in lines
    data_line = next(line for line in lines if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["session_id"] == "session-1"
    assert payload["run_id"] == "run-active"
    assert payload["event_type"] == "session_message_appended"
    assert payload["payload"]["message_item"]["content"] == "Add workspace projection."


def test_session_event_stream_resumes_after_last_event_id(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/sessions/session-1/events/stream",
            headers={
                "Last-Event-ID": "1",
                "X-Request-ID": "req-event-stream-replay",
                "X-Correlation-ID": "corr-event-stream-replay",
            },
            params={"limit": 1},
        ) as response:
            assert response.status_code == 200
            lines = []
            for line in response.iter_lines():
                lines.append(line)
                if line == "":
                    break

    assert "id: 1" not in lines
    assert "id: 2" in lines
    data_line = next(line for line in lines if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["event_type"] == "stage_updated"


def test_get_stage_inspector_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/stages/stage-active/inspector",
            headers={
                "X-Request-ID": "req-inspector",
                "X-Correlation-ID": "corr-inspector",
            },
        )
        missing_response = client.get(
            "/api/stages/stage-missing/inspector",
            headers={
                "X-Request-ID": "req-inspector-missing",
                "X-Correlation-ID": "corr-inspector-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["stage_run_id"] == "stage-active"
    assert payload["run_id"] == "run-active"
    assert payload["stage_type"] == "code_generation"
    assert payload["status"] == "waiting_tool_confirmation"
    assert {
        "identity",
        "input",
        "process",
        "output",
        "artifacts",
        "metrics",
    }.issubset(payload)
    assert "process-tool-confirmation-1" in payload["tool_confirmation_trace_refs"]

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Stage inspector was not found.",
        "request_id": "req-inspector-missing",
        "correlation_id": "corr-inspector-missing",
    }


def test_get_control_item_detail_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _seed_control_item_projection(app)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/control-records/control-clarification-1",
            headers={
                "X-Request-ID": "req-control-clarification",
                "X-Correlation-ID": "corr-control-clarification",
            },
        )
        missing_response = client.get(
            "/api/control-records/control-missing",
            headers={
                "X-Request-ID": "req-control-missing",
                "X-Correlation-ID": "corr-control-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["control_record_id"] == "control-clarification-1"
    assert payload["run_id"] == "run-active"
    assert payload["control_type"] == "clarification_wait"
    assert payload["source_stage_type"] == "code_generation"
    assert (
        payload["input"]["records"]["clarification_question"]
        == "Should the change affect backend only?"
    )
    assert payload["output"]["records"]["result_status"] == "waiting_clarification"
    assert payload["artifacts"]["records"]["clarification_id"] == "clarification-1"
    assert payload["artifacts"]["log_refs"] == ["log-control-clarification-1"]

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Control item inspector was not found.",
        "request_id": "req-control-missing",
        "correlation_id": "corr-control-missing",
    }


def test_get_tool_confirmation_detail_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _seed_tool_confirmation_detail_projection(app)

    with TestClient(app) as client:
        ok_response = client.get(
            "/api/tool-confirmations/tool-confirmation-1",
            headers={
                "X-Request-ID": "req-tool-confirmation",
                "X-Correlation-ID": "corr-tool-confirmation",
            },
        )
        missing_response = client.get(
            "/api/tool-confirmations/tool-confirmation-missing",
            headers={
                "X-Request-ID": "req-tool-confirmation-missing",
                "X-Correlation-ID": "corr-tool-confirmation-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["tool_confirmation_id"] == "tool-confirmation-1"
    assert payload["run_id"] == "run-active"
    assert payload["stage_run_id"] == "stage-active"
    assert payload["status"] == "pending"
    assert payload["tool_name"] == "bash"
    assert payload["risk_level"] == "high_risk"
    assert payload["decision"] is None
    assert payload["process"]["records"]["control_record_id"] == (
        "control-tool-confirmation-1"
    )
    assert payload["process"]["records"]["process_ref"] == (
        "process-tool-confirmation-1"
    )
    assert payload["process"]["records"]["confirmation_object_ref"] == "tool-call-1"
    assert payload["process"]["records"]["tool_result_refs"] == ["tool-result-1"]
    assert payload["process"]["records"]["audit_refs"] == [
        "audit-tool-confirmation-1"
    ]
    assert payload["output"]["records"]["result_status"] == (
        "waiting_tool_confirmation"
    )
    assert payload["output"]["records"]["follow_up_result"] == (
        "awaiting user decision"
    )
    assert payload["output"]["records"]["tool_result_ref"] == "tool-result-1"
    assert payload["artifacts"]["records"]["artifact_refs"] == [
        "artifact-tool-confirmation-1"
    ]
    assert payload["artifacts"]["records"]["confirmation_object_ref"] == "tool-call-1"
    assert payload["artifacts"]["records"]["tool_result_refs"] == ["tool-result-1"]
    assert payload["artifacts"]["log_refs"] == ["log-tool-confirmation-1"]

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Tool confirmation inspector was not found.",
        "request_id": "req-tool-confirmation-missing",
        "correlation_id": "corr-tool-confirmation-missing",
    }


def test_get_session_workspace_rejects_removed_session(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        row = session.get(SessionModel, "session-1")
        assert row is not None
        row.is_visible = False
        row.visibility_removed_at = NOW
        session.add(row)
        session.commit()

    with TestClient(app) as client:
        response = client.get(
            "/api/sessions/session-1/workspace",
            headers={
                "X-Request-ID": "req-workspace-removed",
                "X-Correlation-ID": "corr-workspace-removed",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Session workspace was not found.",
        "request_id": "req-workspace-removed",
        "correlation_id": "corr-workspace-removed",
    }


def test_get_session_workspace_rejects_removed_project(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        row = session.get(ProjectModel, "project-1")
        assert row is not None
        row.is_visible = False
        row.visibility_removed_at = NOW
        session.add(row)
        session.commit()

    with TestClient(app) as client:
        response = client.get(
            "/api/sessions/session-1/workspace",
            headers={
                "X-Request-ID": "req-project-removed",
                "X-Correlation-ID": "corr-project-removed",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Session workspace was not found.",
        "request_id": "req-project-removed",
        "correlation_id": "corr-project-removed",
    }


def test_query_workspace_route_is_documented_in_openapi(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]
    route = paths["/api/sessions/{sessionId}/workspace"]["get"]

    assert set(route["responses"]) == {"200", "404", "422", "500"}
    assert (
        route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionWorkspaceProjection"
    )
    for status_code in ("404", "422", "500"):
        assert (
            route["responses"][status_code]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )

    assert "SessionWorkspaceProjection" in schemas
    assert "ComposerStateProjection" in schemas
    assert "RunSummaryProjection" in schemas

    timeline_route = paths["/api/runs/{runId}/timeline"]["get"]
    assert set(timeline_route["responses"]) == {"200", "404", "422", "500"}
    assert (
        timeline_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RunTimelineProjection"
    )
    run_id_parameter = next(
        parameter
        for parameter in timeline_route["parameters"]
        if parameter["name"] == "runId"
    )
    assert run_id_parameter["in"] == "path"
    assert run_id_parameter["required"] is True
    assert run_id_parameter["schema"]["type"] == "string"
    for status_code in ("404", "422", "500"):
        assert (
            timeline_route["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    assert "RunTimelineProjection" in schemas

    stream_route = paths["/api/sessions/{sessionId}/events/stream"]["get"]
    assert set(stream_route["responses"]) == {"200", "422"}
    assert (
        stream_route["responses"]["200"]["content"]["text/event-stream"]["schema"][
            "type"
        ]
        == "string"
    )
    session_id_parameter = next(
        parameter
        for parameter in stream_route["parameters"]
        if parameter["name"] == "sessionId"
    )
    assert session_id_parameter["in"] == "path"
    assert session_id_parameter["required"] is True
    assert session_id_parameter["schema"]["type"] == "string"
    assert (
        stream_route["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )


    inspector_route = paths["/api/stages/{stageRunId}/inspector"]["get"]
    assert set(inspector_route["responses"]) == {"200", "404", "422", "500"}
    assert (
        inspector_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/StageInspectorProjection"
    )
    stage_run_id_parameter = next(
        parameter
        for parameter in inspector_route["parameters"]
        if parameter["name"] == "stageRunId"
    )
    assert stage_run_id_parameter["in"] == "path"
    assert stage_run_id_parameter["required"] is True
    assert stage_run_id_parameter["schema"]["type"] == "string"
    for status_code in ("404", "422", "500"):
        assert (
            inspector_route["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    control_record_route = paths["/api/control-records/{controlRecordId}"]["get"]
    assert set(control_record_route["responses"]) == {"200", "404", "422", "500"}
    assert (
        control_record_route["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/ControlItemInspectorProjection"
    )
    control_record_id_parameter = next(
        parameter
        for parameter in control_record_route["parameters"]
        if parameter["name"] == "controlRecordId"
    )
    assert control_record_id_parameter["in"] == "path"
    assert control_record_id_parameter["required"] is True
    assert control_record_id_parameter["schema"]["type"] == "string"
    for status_code in ("404", "422", "500"):
        assert (
            control_record_route["responses"][status_code]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    tool_confirmation_route = paths[
        "/api/tool-confirmations/{toolConfirmationId}"
    ]["get"]
    assert set(tool_confirmation_route["responses"]) == {"200", "404", "422", "500"}
    assert (
        tool_confirmation_route["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/ToolConfirmationInspectorProjection"
    )
    tool_confirmation_id_parameter = next(
        parameter
        for parameter in tool_confirmation_route["parameters"]
        if parameter["name"] == "toolConfirmationId"
    )
    assert tool_confirmation_id_parameter["in"] == "path"
    assert tool_confirmation_id_parameter["required"] is True
    assert tool_confirmation_id_parameter["schema"]["type"] == "string"
    for status_code in ("404", "422", "500"):
        assert (
            tool_confirmation_route["responses"][status_code]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    assert "StageInspectorProjection" in schemas
    assert "ControlItemInspectorProjection" in schemas
    assert "ToolConfirmationInspectorProjection" in schemas
    assert "ErrorResponse" in schemas


def test_query_log_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    run_logs_route = paths["/api/runs/{runId}/logs"]["get"]
    stage_logs_route = paths["/api/stages/{stageRunId}/logs"]["get"]

    assert set(run_logs_route["responses"]) == {"200", "404", "422", "503"}
    assert set(stage_logs_route["responses"]) == {"200", "404", "422", "503"}
    assert (
        run_logs_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RunLogQueryResponse"
    )
    assert (
        stage_logs_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RunLogQueryResponse"
    )

    run_param_names = {parameter["name"] for parameter in run_logs_route["parameters"]}
    stage_param_names = {
        parameter["name"] for parameter in stage_logs_route["parameters"]
    }
    assert {
        "runId",
        "level",
        "category",
        "source",
        "since",
        "until",
        "cursor",
        "limit",
    } <= run_param_names
    assert {
        "stageRunId",
        "level",
        "category",
        "source",
        "since",
        "until",
        "cursor",
        "limit",
    } <= stage_param_names

    run_limit_parameter = next(
        parameter for parameter in run_logs_route["parameters"] if parameter["name"] == "limit"
    )
    stage_limit_parameter = next(
        parameter
        for parameter in stage_logs_route["parameters"]
        if parameter["name"] == "limit"
    )
    assert {schema["type"] for schema in run_limit_parameter["schema"]["anyOf"]} == {
        "integer",
        "null",
    }
    assert {schema["type"] for schema in stage_limit_parameter["schema"]["anyOf"]} == {
        "integer",
        "null",
    }

    for status_code in ("404", "422", "503"):
        assert (
            run_logs_route["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
        assert (
            stage_logs_route["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )

    assert "RunLogQueryResponse" in schemas
    assert "RunLogEntryProjection" in schemas
    assert "RunLogQuery" in schemas
    assert "ErrorResponse" in schemas
