from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.db.base import DatabaseRole
from backend.app.db.models.runtime import ToolConfirmationRequestModel
from backend.app.domain.enums import SseEventType
from backend.app.schemas import common
from backend.app.schemas.feed import (
    ExecutionNodeProjection,
    ProviderCallStageItem,
    ToolConfirmationFeedEntry,
)
from backend.app.services.events import DomainEvent, DomainEventType, EventStore
from backend.tests.api.test_query_api import build_query_api_app
from backend.tests.projections.test_workspace_projection import NOW, _trace
from backend.tests.projections.test_workspace_projection import (
    _append_denied_tool_confirmation_event_without_followup,
    _mark_tool_confirmation_denied_with_followup,
)


def test_sse_event_encoder_serializes_tool_confirmation_result_with_correlation_id() -> None:
    from backend.app.services.events import SseEventEncoder

    event = DomainEvent(
        event_id="event-tool-denied",
        session_id="session-1",
        run_id="run-active",
        event_type=SseEventType.TOOL_CONFIRMATION_RESULT,
        occurred_at=NOW + timedelta(minutes=8),
        payload={
            "tool_confirmation": _denied_tool_confirmation_payload(
                entry_id="entry-tool-denied"
            )
        },
        stage_run_id="stage-active",
        sequence_index=5,
        correlation_id="correlation-1",
        causation_event_id="event-tool-requested",
    )

    frame = SseEventEncoder().encode(event)

    assert frame.startswith("id: 5\nevent: tool_confirmation_result\ndata: ")
    assert frame.endswith("\n\n")
    envelope = json.loads(
        frame.removeprefix("id: 5\nevent: tool_confirmation_result\ndata: ").strip()
    )
    assert envelope["event_id"] == "event-tool-denied"
    assert envelope["session_id"] == "session-1"
    assert envelope["run_id"] == "run-active"
    assert envelope["event_type"] == "tool_confirmation_result"
    assert envelope["occurred_at"] == (NOW + timedelta(minutes=8)).isoformat()
    assert envelope["correlation_id"] == "correlation-1"
    assert envelope["payload"]["tool_confirmation"]["decision"] == "denied"
    assert envelope["payload"]["tool_confirmation"]["is_actionable"] is False


def test_session_event_stream_replays_after_last_event_id_with_provider_and_denied_result(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _append_reconnect_replay_events(app)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/sessions/session-1/events/stream",
            headers={
                "Last-Event-ID": "2",
                "X-Request-ID": "req-event-stream-reconnect",
                "X-Correlation-ID": "corr-event-stream-reconnect",
            },
            params={"after": 0, "limit": 3},
        ) as response:
            assert response.status_code == 200
            frames = _read_sse_frames(response)

    assert [frame["id"] for frame in frames] == ["3", "4", "5"]
    assert [frame["event"] for frame in frames] == [
        "tool_confirmation_requested",
        "stage_updated",
        "tool_confirmation_result",
    ]

    tool_request = frames[0]["data"]["payload"]["tool_confirmation"]
    assert tool_request["tool_confirmation_id"] == "tool-confirmation-1"
    assert tool_request["status"] == "pending"
    assert tool_request["tool_name"] == "bash"
    assert tool_request["risk_level"] == "high_risk"
    assert tool_request["target_summary"] == "frontend/package-lock.json"
    assert tool_request["is_actionable"] is True

    stage_payload = frames[1]["data"]["payload"]["stage_node"]
    provider_item = next(
        item for item in stage_payload["items"] if item["type"] == "provider_call"
    )
    assert provider_item["status"] == "retrying"
    assert provider_item["backoff_wait_seconds"] == 8
    assert provider_item["circuit_breaker_status"] == "closed"

    tool_result = frames[2]["data"]["payload"]["tool_confirmation"]
    assert tool_result["status"] == "denied"
    assert tool_result["decision"] == "denied"
    assert tool_result["is_actionable"] is False
    assert tool_result["disabled_reason"] == "Denied by user."


def test_session_event_stream_hydrates_tool_confirmation_deny_followup_from_runtime_model(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _mark_tool_confirmation_denied_with_followup(app.state.database_manager)
    _append_denied_tool_confirmation_event_without_followup(app.state.database_manager)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/sessions/session-1/events/stream",
            headers={
                "Last-Event-ID": "3",
                "X-Request-ID": "req-event-stream-deny-followup",
                "X-Correlation-ID": "corr-event-stream-deny-followup",
            },
            params={"after": 0, "limit": 1},
        ) as response:
            assert response.status_code == 200
            frames = _read_sse_frames(response)

    assert [frame["event"] for frame in frames] == ["tool_confirmation_result"]
    tool_result = frames[0]["data"]["payload"]["tool_confirmation"]
    assert tool_result["decision"] == "denied"
    assert tool_result["deny_followup_action"] == "continue_current_stage"
    assert tool_result["deny_followup_summary"] == (
        "Code Generation will continue with a low-risk fallback."
    )


def test_session_event_stream_rejects_invalid_hydrated_tool_confirmation_contract(
    tmp_path: Path,
) -> None:
    from pydantic import ValidationError

    from backend.app.api.routes.events import _hydrate_tool_confirmation_event

    app = build_query_api_app(tmp_path)
    _mark_tool_confirmation_denied_with_followup(app.state.database_manager)
    _append_denied_tool_confirmation_event_without_followup(app.state.database_manager)
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as runtime_session:
        request = runtime_session.get(
            ToolConfirmationRequestModel,
            "tool-confirmation-1",
        )
        assert request is not None
        request.deny_followup_action = "retry_current_stage"
        runtime_session.add(request)
        runtime_session.commit()
        event = DomainEvent(
            event_id="event-tool-denied",
            session_id="session-1",
            run_id="run-active",
            event_type=SseEventType.TOOL_CONFIRMATION_RESULT,
            occurred_at=NOW + timedelta(minutes=8),
            payload={
                "tool_confirmation": {
                    **_denied_tool_confirmation_payload(
                        entry_id="entry-tool-denied"
                    ),
                    "deny_followup_action": None,
                    "deny_followup_summary": None,
                }
            },
            stage_run_id="stage-active",
            sequence_index=5,
            correlation_id="correlation-1",
            causation_event_id="event-tool-requested",
        )

        with pytest.raises(ValidationError):
            _hydrate_tool_confirmation_event(event, runtime_session)


def test_session_event_stream_openapi_documents_route_parameters_and_error(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    stream_route = response.json()["paths"]["/api/sessions/{sessionId}/events/stream"][
        "get"
    ]
    parameters = {
        parameter["name"]: parameter for parameter in stream_route["parameters"]
    }

    assert "200" in stream_route["responses"]
    assert (
        stream_route["responses"]["200"]["content"]["text/event-stream"]["schema"][
            "type"
        ]
        == "string"
    )
    assert parameters["sessionId"]["in"] == "path"
    assert parameters["sessionId"]["required"] is True
    assert parameters["after"]["in"] == "query"
    assert parameters["after"]["required"] is False
    assert parameters["limit"]["in"] == "query"
    assert parameters["limit"]["required"] is False
    assert (
        stream_route["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )


def _append_reconnect_replay_events(app) -> None:
    _mark_tool_confirmation_denied_with_followup(app.state.database_manager)
    with app.state.database_manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(["event-provider-retry", "event-tool-denied"]).__next__,
        )
        store.append(
            DomainEventType.PROVIDER_CALL_RETRIED,
            payload={
                "stage_node": ExecutionNodeProjection(
                    entry_id="entry-stage-provider-retry",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7, seconds=30),
                    stage_run_id="stage-active",
                    stage_type=common.StageType.CODE_GENERATION,
                    status=common.StageStatus.WAITING_TOOL_CONFIRMATION,
                    attempt_index=1,
                    started_at=NOW + timedelta(minutes=2),
                    ended_at=None,
                    summary="Code Generation is retrying a provider call.",
                    items=[
                        ProviderCallStageItem(
                            item_id="provider-call-retry",
                            type=common.StageItemType.PROVIDER_CALL,
                            occurred_at=NOW + timedelta(minutes=7, seconds=30),
                            title="Provider retry",
                            summary="Network retry scheduled.",
                            content=None,
                            artifact_refs=["provider-retry-trace-1"],
                            metrics={},
                            provider_id="provider-deepseek",
                            model_id="deepseek-chat",
                            status="retrying",
                            retry_attempt=1,
                            max_retry_attempts=2,
                            backoff_wait_seconds=8,
                            circuit_breaker_status=(
                                common.ProviderCircuitBreakerStatus.CLOSED
                            ),
                            failure_reason="network_error",
                            process_ref="provider-retry-trace-1",
                        )
                    ],
                    metrics={},
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
            causation_event_id="event-tool",
        )
        store.append(
            DomainEventType.TOOL_CONFIRMATION_DENIED,
            payload={
                "tool_confirmation": _denied_tool_confirmation_payload(
                    entry_id="entry-tool-denied"
                )
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
            causation_event_id="event-tool",
        )
        session.commit()


def _denied_tool_confirmation_payload(*, entry_id: str) -> dict[str, object]:
    return ToolConfirmationFeedEntry(
        entry_id=entry_id,
        run_id="run-active",
        occurred_at=NOW + timedelta(minutes=8),
        stage_run_id="stage-active",
        tool_confirmation_id="tool-confirmation-1",
        status=common.ToolConfirmationStatus.DENIED,
        title="Allow dependency install",
        tool_name="bash",
        command_preview="npm install",
        target_summary="frontend/package-lock.json",
        risk_level=common.ToolRiskLevel.HIGH_RISK,
        risk_categories=[
            common.ToolRiskCategory.DEPENDENCY_CHANGE,
            common.ToolRiskCategory.NETWORK_DOWNLOAD,
        ],
        reason="Installing dependencies changes lock files.",
        expected_side_effects=["package-lock update"],
        allow_action="allow_once",
        deny_action="deny_once",
        is_actionable=False,
        requested_at=NOW + timedelta(minutes=7),
        responded_at=NOW + timedelta(minutes=8),
        decision=common.ToolConfirmationStatus.DENIED,
        deny_followup_action="continue_current_stage",
        deny_followup_summary=(
            "Code Generation will continue with a low-risk fallback."
        ),
        disabled_reason="Denied by user.",
    ).model_dump(mode="json")


def _read_sse_frames(response) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    current: dict[str, str] = {}
    for line in response.iter_lines():
        if line == "":
            if current:
                frames.append(
                    {
                        "id": current["id"],
                        "event": current["event"],
                        "data": json.loads(current["data"]),
                    }
                )
                current = {}
            continue
        key, value = line.split(": ", 1)
        current[key] = value
    return frames
