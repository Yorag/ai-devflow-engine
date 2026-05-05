from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.db.base import DatabaseRole
from backend.app.schemas import common
from backend.app.schemas.feed import ApprovalRequestFeedEntry, ApprovalResultFeedEntry
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.projections.timeline import TimelineProjectionService
from backend.app.services.projections.workspace import WorkspaceProjectionService
from backend.tests.api.test_query_api import build_query_api_app
from backend.tests.api.test_sse_stream import _read_sse_frames
from backend.tests.projections.test_workspace_projection import NOW, _trace


def assertProjectionDoesNotDuplicateEntries(entries: list[dict[str, Any]]) -> None:
    identities = [_feed_identity(entry) for entry in entries]
    duplicates = sorted(
        identity for identity in set(identities) if identities.count(identity) > 1
    )
    assert duplicates == []


def test_workspace_timeline_and_sse_do_not_duplicate_replayed_approval_or_tool_entries(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _append_duplicate_approval_events(app)

    with (
        app.state.database_manager.session(DatabaseRole.CONTROL) as control_session,
        app.state.database_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        app.state.database_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        workspace = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_session_workspace("session-1")
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    workspace_entries = [
        entry.model_dump(mode="json") for entry in workspace.narrative_feed
    ]
    timeline_entries = [entry.model_dump(mode="json") for entry in timeline.entries]
    assertProjectionDoesNotDuplicateEntries(workspace_entries)
    assertProjectionDoesNotDuplicateEntries(timeline_entries)

    workspace_approval_request = next(
        entry for entry in workspace_entries if entry["type"] == "approval_request"
    )
    timeline_approval_request = next(
        entry for entry in timeline_entries if entry["type"] == "approval_request"
    )
    assert workspace_approval_request["status"] == "approved"
    assert workspace_approval_request["is_actionable"] is False
    assert timeline_approval_request["status"] == "approved"
    assert timeline_approval_request["is_actionable"] is False
    assert [
        entry["approval_id"]
        for entry in workspace_entries
        if entry["type"] == "approval_result"
    ] == ["approval-v67"]
    assert [
        entry["approval_id"]
        for entry in timeline_entries
        if entry["type"] == "approval_result"
    ] == ["approval-v67"]

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/sessions/session-1/events/stream",
            params={"after": 3, "limit": 3},
            headers={
                "X-Request-ID": "req-v67-sse-replay",
                "X-Correlation-ID": "corr-v67-sse-replay",
            },
        ) as response:
            assert response.status_code == 200
            frames = _read_sse_frames(response)

    assert [int(frame["id"]) for frame in frames] == sorted(
        int(frame["id"]) for frame in frames
    )
    assert [frame["event"] for frame in frames] == [
        "approval_requested",
        "approval_result",
        "approval_result",
    ]
    for frame in frames:
        assert set(frame["data"]["payload"]) <= {"approval_request", "approval_result"}


def test_projection_status_never_regresses_when_duplicate_result_events_replay(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    _append_duplicate_approval_events(app)

    with (
        app.state.database_manager.session(DatabaseRole.CONTROL) as control_session,
        app.state.database_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        app.state.database_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        workspace = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_session_workspace("session-1")
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    workspace_entries = [
        entry.model_dump(mode="json") for entry in workspace.narrative_feed
    ]
    timeline_entries = [entry.model_dump(mode="json") for entry in timeline.entries]
    assertProjectionDoesNotDuplicateEntries(workspace_entries)
    assertProjectionDoesNotDuplicateEntries(timeline_entries)

    workspace_approval_request = next(
        entry for entry in workspace_entries if entry["type"] == "approval_request"
    )
    timeline_approval_request = next(
        entry for entry in timeline_entries if entry["type"] == "approval_request"
    )
    assert workspace_approval_request["approval_id"] == "approval-v67"
    assert workspace_approval_request["status"] == "approved"
    assert workspace_approval_request["is_actionable"] is False
    assert timeline_approval_request["approval_id"] == "approval-v67"
    assert timeline_approval_request["status"] == "approved"
    assert timeline_approval_request["is_actionable"] is False

    _append_duplicate_approval_result(app, "event-v67-approval-result-third")

    with (
        app.state.database_manager.session(DatabaseRole.CONTROL) as control_session,
        app.state.database_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        app.state.database_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        replayed_workspace = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_session_workspace("session-1")
        replayed_timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    replayed_workspace_entries = [
        entry.model_dump(mode="json") for entry in replayed_workspace.narrative_feed
    ]
    replayed_timeline_entries = [
        entry.model_dump(mode="json") for entry in replayed_timeline.entries
    ]
    assertProjectionDoesNotDuplicateEntries(replayed_workspace_entries)
    assertProjectionDoesNotDuplicateEntries(replayed_timeline_entries)
    assert next(
        entry
        for entry in replayed_workspace_entries
        if entry["type"] == "approval_request"
    )["status"] == "approved"
    assert next(
        entry
        for entry in replayed_timeline_entries
        if entry["type"] == "approval_request"
    )["status"] == "approved"


def _append_duplicate_approval_events(app) -> None:
    with app.state.database_manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(
                [
                    "event-v67-approval-request",
                    "event-v67-approval-result",
                    "event-v67-approval-result-duplicate",
                ]
            ).__next__,
        )
        approval_request = ApprovalRequestFeedEntry(
            entry_id="entry-v67-approval-request",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=8),
            approval_id="approval-v67",
            approval_type=common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            status=common.ApprovalStatus.PENDING,
            title="Review release candidate projection",
            approval_object_excerpt="Review the release candidate projection.",
            risk_excerpt=None,
            approval_object_preview={},
            approve_action="approve",
            reject_action="reject",
            is_actionable=True,
            requested_at=NOW + timedelta(minutes=8),
            delivery_readiness_status=None,
            delivery_readiness_message=None,
            open_settings_action=None,
            disabled_reason=None,
        )
        approval_result = ApprovalResultFeedEntry(
            entry_id="entry-v67-approval-result",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=9),
            approval_id="approval-v67",
            approval_type=common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            decision=common.ApprovalStatus.APPROVED,
            reason=None,
            created_at=NOW + timedelta(minutes=9),
            next_stage_type=common.StageType.CODE_GENERATION,
        )
        store.append(
            DomainEventType.APPROVAL_REQUESTED,
            payload={"approval_request": approval_request.model_dump(mode="json")},
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        store.append(
            DomainEventType.APPROVAL_APPROVED,
            payload={"approval_result": approval_result.model_dump(mode="json")},
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        store.append(
            DomainEventType.APPROVAL_APPROVED,
            payload={"approval_result": approval_result.model_dump(mode="json")},
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()


def _append_duplicate_approval_result(app, event_id: str) -> None:
    with app.state.database_manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter([event_id]).__next__,
        )
        duplicate_result = ApprovalResultFeedEntry(
            entry_id=f"entry-{event_id}",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=10),
            approval_id="approval-v67",
            approval_type=common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            decision=common.ApprovalStatus.APPROVED,
            reason=None,
            created_at=NOW + timedelta(minutes=10),
            next_stage_type=common.StageType.CODE_GENERATION,
        )
        store.append(
            DomainEventType.APPROVAL_APPROVED,
            payload={"approval_result": duplicate_result.model_dump(mode="json")},
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()


def _feed_identity(entry: dict[str, Any]) -> tuple[str, str]:
    entry_type = entry["type"]
    if entry_type == "user_message":
        return entry_type, entry["message_id"]
    if entry_type == "stage_node":
        return entry_type, entry["stage_run_id"]
    if entry_type == "approval_request":
        return entry_type, entry["approval_id"]
    if entry_type == "approval_result":
        return entry_type, entry["approval_id"]
    if entry_type == "tool_confirmation":
        return entry_type, entry["tool_confirmation_id"]
    if entry_type == "control_item":
        return entry_type, entry["control_record_id"]
    if entry_type == "delivery_result":
        return entry_type, entry["delivery_record_id"]
    return entry_type, f"{entry['run_id']}:{entry.get('status', '')}"
