from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.domain.enums import SseEventType
from backend.app.schemas import common
from backend.app.schemas.feed import (
    ApprovalRequestFeedEntry,
    ApprovalResultFeedEntry,
    ExecutionNodeProjection,
    MessageFeedEntry,
    ProviderCallStageItem,
)
from backend.app.services.events import DomainEventType, EventStore
from backend.tests.projections.test_workspace_projection import (
    NOW,
    _append_denied_tool_confirmation_event_without_followup,
    _mark_tool_confirmation_denied_with_followup,
    _manager,
    _seed_workspace,
    _trace,
)


def test_timeline_projection_returns_only_target_run_entries_in_time_order(
    tmp_path,
) -> None:
    from backend.app.services.projections.timeline import TimelineProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(["event-old-run-message", "event-provider-update"]).__next__,
        )
        store.append(
            DomainEventType.SESSION_MESSAGE_APPENDED,
            payload={
                "message_item": MessageFeedEntry(
                    entry_id="entry-old-message",
                    run_id="run-old",
                    occurred_at=NOW - timedelta(minutes=7),
                    message_id="message-old",
                    author="user",
                    content="Retry from the old run.",
                    stage_run_id=None,
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-old", stage_run_id=None),
        )
        store.append(
            DomainEventType.PROVIDER_CALL_RETRIED,
            payload={
                "stage_node": ExecutionNodeProjection(
                    entry_id="entry-stage-active",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=6, seconds=30),
                    stage_run_id="stage-active",
                    stage_type=common.StageType.CODE_GENERATION,
                    status=common.StageStatus.WAITING_TOOL_CONFIRMATION,
                    attempt_index=1,
                    started_at=NOW + timedelta(minutes=2),
                    ended_at=None,
                    summary="Code Generation is retrying before tool confirmation.",
                    items=[
                        ProviderCallStageItem(
                            item_id="provider-call-1",
                            type=common.StageItemType.PROVIDER_CALL,
                            occurred_at=NOW + timedelta(minutes=6, seconds=30),
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
                            backoff_wait_seconds=5,
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
        )
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    dumped = timeline.model_dump(mode="json")
    assert dumped["run_id"] == "run-active"
    assert dumped["session_id"] == "session-1"
    assert dumped["attempt_index"] == 2
    assert dumped["trigger_source"] == "retry"
    assert dumped["status"] == "waiting_tool_confirmation"
    assert dumped["current_stage_type"] == "code_generation"
    assert [entry["run_id"] for entry in dumped["entries"]] == [
        "run-active",
        "run-active",
        "run-active",
    ]
    assert [entry["type"] for entry in dumped["entries"]] == [
        "user_message",
        "stage_node",
        "tool_confirmation",
    ]
    stage_node = next(
        entry for entry in dumped["entries"] if entry["type"] == "stage_node"
    )
    assert [item["type"] for item in stage_node["items"]] == ["provider_call"]
    assert not any(entry["type"] == "approval_request" for entry in dumped["entries"])
    assert "run-old" not in str(dumped)
    assert "graph_thread_ref" not in dumped


def test_timeline_projection_matches_workspace_feed_for_target_run(tmp_path) -> None:
    from backend.app.services.projections.timeline import TimelineProjectionService
    from backend.app.services.projections.workspace import WorkspaceProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        workspace_service = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        timeline_service = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        workspace = workspace_service.get_session_workspace("session-1")
        timeline = timeline_service.get_run_timeline("run-active")

    workspace_entries = [
        entry.model_dump(mode="json")
        for entry in workspace.narrative_feed
        if entry.run_id == "run-active"
    ]
    timeline_entries = [entry.model_dump(mode="json") for entry in timeline.entries]
    assert timeline_entries == workspace_entries


def test_timeline_projection_hydrates_denied_tool_confirmation_deny_followup_from_runtime_model(
    tmp_path,
) -> None:
    from backend.app.services.projections.timeline import TimelineProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _mark_tool_confirmation_denied_with_followup(manager)
    _append_denied_tool_confirmation_event_without_followup(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    dumped = timeline.model_dump(mode="json")
    tool_confirmation = next(
        entry for entry in dumped["entries"] if entry["type"] == "tool_confirmation"
    )
    assert tool_confirmation["decision"] == "denied"
    assert tool_confirmation["deny_followup_action"] == "continue_current_stage"
    assert tool_confirmation["deny_followup_summary"] == (
        "Code Generation will continue with a low-risk fallback."
    )
    assert "alternative_path_summary" not in tool_confirmation


def test_timeline_projection_replays_approval_result_without_losing_result_entry(
    tmp_path,
) -> None:
    from backend.app.services.projections.timeline import TimelineProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(
                ["event-approval-request", "event-approval-result"]
            ).__next__,
        )
        approval_request = ApprovalRequestFeedEntry(
            entry_id="entry-approval-request",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=8),
            approval_id="approval-1",
            approval_type=common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            status=common.ApprovalStatus.PENDING,
            title="Review solution design",
            approval_object_excerpt="Review the proposed design.",
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
            entry_id="entry-approval-result",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=9),
            approval_id="approval-1",
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
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    dumped = timeline.model_dump(mode="json")
    approval_request_entry = next(
        entry for entry in dumped["entries"] if entry["type"] == "approval_request"
    )
    assert approval_request_entry["status"] == "approved"
    assert approval_request_entry["is_actionable"] is False
    assert [
        entry["approval_id"]
        for entry in dumped["entries"]
        if entry["type"] == "approval_result"
    ] == ["approval-1"]


def test_timeline_projection_preserves_replay_order_for_same_timestamp_approval_entries(
    tmp_path,
) -> None:
    from backend.app.services.projections.timeline import TimelineProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(
                ["event-approval-request-same-time", "event-approval-result-same-time"]
            ).__next__,
        )
        approval_request = ApprovalRequestFeedEntry(
            entry_id="entry-z-approval-request",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=8),
            approval_id="approval-same-time",
            approval_type=common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            status=common.ApprovalStatus.PENDING,
            title="Review solution design",
            approval_object_excerpt="Review the proposed design.",
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
            entry_id="entry-a-approval-result",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=8),
            approval_id="approval-same-time",
            approval_type=common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            decision=common.ApprovalStatus.APPROVED,
            reason=None,
            created_at=NOW + timedelta(minutes=8),
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
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    approval_entries = [
        entry.model_dump(mode="json")
        for entry in timeline.entries
        if entry.type in {"approval_request", "approval_result"}
    ]
    assert [entry["type"] for entry in approval_entries] == [
        "approval_request",
        "approval_result",
    ]


def test_timeline_projection_does_not_leak_current_stage_from_another_run(
    tmp_path,
) -> None:
    from backend.app.db.models.runtime import PipelineRunModel
    from backend.app.services.projections.timeline import TimelineProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-active")
        assert run is not None
        run.current_stage_run_id = "stage-old"
        session.add(run)
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    assert timeline.current_stage_type is None


def test_timeline_projection_uses_session_latest_stage_for_active_run_without_stage_row(
    tmp_path,
) -> None:
    from backend.app.db.models.runtime import PipelineRunModel
    from backend.app.domain.enums import RunStatus, SessionStatus, StageType
    from backend.app.services.projections.timeline import TimelineProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        control_session.status = SessionStatus.RUNNING
        control_session.latest_stage_type = StageType.REQUIREMENT_ANALYSIS
        session.add(control_session)
        session.commit()
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-active")
        assert run is not None
        run.status = RunStatus.RUNNING
        run.current_stage_run_id = None
        session.add(run)
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    assert timeline.current_stage_type is StageType.REQUIREMENT_ANALYSIS


def test_timeline_projection_skips_off_target_malformed_payload_before_parsing(
    tmp_path,
) -> None:
    from backend.app.services.projections.timeline import TimelineProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.EVENT) as session:
        session.add(
            DomainEventModel(
                event_id="event-off-target-malformed",
                session_id="session-1",
                run_id="run-old",
                stage_run_id=None,
                event_type=SseEventType.SESSION_MESSAGE_APPENDED,
                sequence_index=999,
                occurred_at=NOW + timedelta(minutes=3),
                payload={
                    "message_item": {
                        "entry_id": "entry-off-target-malformed",
                        "run_id": "run-old",
                        "type": "user_message",
                        "occurred_at": (NOW + timedelta(minutes=3)).isoformat(),
                        "message_id": "message-off-target-malformed",
                        "author": "user",
                    }
                },
                correlation_id="correlation-1",
                causation_event_id=None,
                created_at=NOW + timedelta(minutes=3),
            )
        )
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        timeline = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_run_timeline("run-active")

    assert [entry.run_id for entry in timeline.entries] == [
        "run-active",
        "run-active",
        "run-active",
    ]


@pytest.mark.parametrize(
    ("removed_model", "removed_id"),
    [(SessionModel, "session-1"), (ProjectModel, "project-1")],
)
def test_timeline_projection_rejects_hidden_run_context(
    tmp_path,
    removed_model,
    removed_id,
) -> None:
    from backend.app.services.projections.timeline import (
        TimelineProjectionService,
        TimelineProjectionServiceError,
    )

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.CONTROL) as session:
        removed = session.get(removed_model, removed_id)
        assert removed is not None
        removed.is_visible = False
        removed.visibility_removed_at = NOW
        session.add(removed)
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(TimelineProjectionServiceError) as exc_info:
            service.get_run_timeline("run-active")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Run timeline was not found."


def test_timeline_projection_rejects_missing_run(tmp_path) -> None:
    from backend.app.services.projections.timeline import (
        TimelineProjectionService,
        TimelineProjectionServiceError,
    )

    manager = _manager(tmp_path)
    _seed_workspace(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = TimelineProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(TimelineProjectionServiceError) as exc_info:
            service.get_run_timeline("run-missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Run timeline was not found."
