from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.event import DomainEventModel, EventBase
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    ControlItemType,
    FeedEntryType,
    ProviderCircuitBreakerStatus,
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    StageItemType,
    StageStatus,
    StageType,
    SseEventType,
)
from backend.app.domain.trace_context import TraceContext


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    return manager


def _trace(
    *,
    session_id: str | None = "session-1",
    run_id: str | None = "run-1",
    stage_run_id: str | None = None,
    correlation_id: str = "correlation-1",
) -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id=correlation_id,
        span_id="span-1",
        parent_span_id=None,
        session_id=session_id,
        run_id=run_id,
        stage_run_id=stage_run_id,
        created_at=NOW,
    )


def _run_payload(*, run_id: str = "run-1") -> dict[str, object]:
    return {
        "run": {
            "run_id": run_id,
            "attempt_index": 1,
            "status": RunStatus.RUNNING.value,
            "trigger_source": RunTriggerSource.INITIAL_REQUIREMENT.value,
            "started_at": NOW.isoformat(),
            "ended_at": None,
            "current_stage_type": StageType.REQUIREMENT_ANALYSIS.value,
            "is_active": True,
        }
    }


def _session_status_payload(
    *,
    session_id: str = "session-1",
    current_run_id: str | None = "run-1",
    status: SessionStatus = SessionStatus.COMPLETED,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "status": status.value,
        "current_run_id": current_run_id,
        "current_stage_type": None,
    }


def _stage_payload(
    *,
    run_id: str = "run-1",
    stage_run_id: str = "stage-run-1",
) -> dict[str, object]:
    return {
        "stage_node": {
            "entry_id": f"entry-{stage_run_id}",
            "run_id": run_id,
            "type": FeedEntryType.STAGE_NODE.value,
            "occurred_at": NOW.isoformat(),
            "stage_run_id": stage_run_id,
            "stage_type": StageType.CODE_GENERATION.value,
            "status": StageStatus.RUNNING.value,
            "attempt_index": 1,
            "started_at": NOW.isoformat(),
            "ended_at": None,
            "summary": "Code Generation is retrying a provider call.",
            "items": [
                {
                    "item_id": "item-provider-call",
                    "type": StageItemType.PROVIDER_CALL.value,
                    "occurred_at": NOW.isoformat(),
                    "title": "Provider retry",
                    "summary": "The provider call is waiting before retry.",
                    "content": None,
                    "artifact_refs": [],
                    "metrics": {"latency_ms": 1200},
                    "provider_id": "provider-1",
                    "model_id": "model-1",
                    "status": "retrying",
                    "retry_attempt": 1,
                    "max_retry_attempts": 3,
                    "backoff_wait_seconds": 4,
                    "circuit_breaker_status": ProviderCircuitBreakerStatus.CLOSED.value,
                    "failure_reason": "rate_limited",
                    "process_ref": "provider-call-1",
                }
            ],
            "metrics": {},
        }
    }


def _stage_payload_python_mode(
    *,
    run_id: str = "run-1",
    stage_run_id: str = "stage-run-1",
) -> dict[str, object]:
    return {
        "stage_node": {
            "entry_id": f"entry-{stage_run_id}",
            "run_id": run_id,
            "type": FeedEntryType.STAGE_NODE,
            "occurred_at": NOW,
            "stage_run_id": stage_run_id,
            "stage_type": StageType.CODE_GENERATION,
            "status": StageStatus.RUNNING,
            "attempt_index": 1,
            "started_at": NOW,
            "ended_at": None,
            "summary": "Code Generation is retrying a provider call.",
            "items": [
                {
                    "item_id": "item-provider-call",
                    "type": StageItemType.PROVIDER_CALL,
                    "occurred_at": NOW,
                    "title": "Provider retry",
                    "summary": "The provider call is waiting before retry.",
                    "content": None,
                    "artifact_refs": [],
                    "metrics": {"latency_ms": 1200},
                    "provider_id": "provider-1",
                    "model_id": "model-1",
                    "status": "retrying",
                    "retry_attempt": 1,
                    "max_retry_attempts": 3,
                    "backoff_wait_seconds": 4,
                    "circuit_breaker_status": ProviderCircuitBreakerStatus.CLOSED,
                    "failure_reason": "rate_limited",
                    "process_ref": "provider-call-1",
                }
            ],
            "metrics": {},
        }
    }


def _clarification_payload(
    *,
    run_id: str = "run-1",
    stage_run_id: str = "stage-run-1",
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "stage_run_id": stage_run_id,
        "control_item": {
            "entry_id": "entry-clarification",
            "run_id": run_id,
            "type": FeedEntryType.CONTROL_ITEM.value,
            "occurred_at": NOW.isoformat(),
            "control_record_id": "control-clarification-1",
            "control_type": ControlItemType.CLARIFICATION_WAIT.value,
            "source_stage_type": StageType.REQUIREMENT_ANALYSIS.value,
            "target_stage_type": StageType.REQUIREMENT_ANALYSIS.value,
            "title": "Clarification needed",
            "summary": "Requirement Analysis is waiting for user input.",
            "payload_ref": "clarification-record-1",
        },
    }


def test_event_projection_matrix_fixes_required_e3_1_mappings() -> None:
    from backend.app.services.events import (
        DomainEventType,
        EventProjectionTarget,
        resolve_feed_entry_type,
        resolve_projection_targets,
        resolve_sse_event_type,
    )

    assert resolve_sse_event_type(DomainEventType.PIPELINE_RUN_CREATED) is (
        SseEventType.PIPELINE_RUN_CREATED
    )
    assert resolve_feed_entry_type(DomainEventType.PIPELINE_RUN_CREATED) is None
    assert EventProjectionTarget.RUN_SUMMARY in resolve_projection_targets(
        DomainEventType.PIPELINE_RUN_CREATED
    )

    for event_type in (
        DomainEventType.APPROVAL_APPROVED,
        DomainEventType.APPROVAL_REJECTED,
    ):
        assert resolve_sse_event_type(event_type) is SseEventType.APPROVAL_RESULT
        assert resolve_feed_entry_type(event_type) is FeedEntryType.APPROVAL_RESULT

    assert resolve_sse_event_type(DomainEventType.TOOL_CONFIRMATION_REQUESTED) is (
        SseEventType.TOOL_CONFIRMATION_REQUESTED
    )
    assert resolve_feed_entry_type(DomainEventType.TOOL_CONFIRMATION_REQUESTED) is (
        FeedEntryType.TOOL_CONFIRMATION
    )

    for event_type in (
        DomainEventType.TOOL_CONFIRMATION_ALLOWED,
        DomainEventType.TOOL_CONFIRMATION_DENIED,
    ):
        assert resolve_sse_event_type(event_type) is (
            SseEventType.TOOL_CONFIRMATION_RESULT
        )
        assert resolve_feed_entry_type(event_type) is FeedEntryType.TOOL_CONFIRMATION

    for event_type in (
        DomainEventType.PROVIDER_CALL_RETRIED,
        DomainEventType.PROVIDER_CIRCUIT_BREAKER_OPENED,
        DomainEventType.PROVIDER_CIRCUIT_BREAKER_RECOVERED,
    ):
        assert resolve_sse_event_type(event_type) is SseEventType.STAGE_UPDATED
        assert resolve_feed_entry_type(event_type) is FeedEntryType.STAGE_NODE
        assert EventProjectionTarget.PROVIDER_CALL in resolve_projection_targets(
            event_type
        )

    assert resolve_sse_event_type(DomainEventType.DELIVERY_PREPARED) is (
        SseEventType.DELIVERY_RESULT
    )
    assert resolve_feed_entry_type(DomainEventType.DELIVERY_PREPARED) is (
        FeedEntryType.DELIVERY_RESULT
    )

    assert resolve_sse_event_type(DomainEventType.RUN_COMPLETED) is (
        SseEventType.SESSION_STATUS_CHANGED
    )
    assert resolve_feed_entry_type(DomainEventType.RUN_COMPLETED) is None

    for event_type in (
        DomainEventType.RUN_FAILED,
        DomainEventType.RUN_TERMINATED,
    ):
        assert resolve_sse_event_type(event_type) is SseEventType.SYSTEM_STATUS
        assert resolve_feed_entry_type(event_type) is FeedEntryType.SYSTEM_STATUS


def test_event_projection_matrix_includes_external_domain_events_without_new_sse_semantics() -> None:
    from backend.app.services.events import (
        DomainEventType,
        EventProjectionMatrix,
        EventProjectionTarget,
        resolve_feed_entry_type,
        resolve_projection_targets,
        resolve_sse_event_type,
    )

    expected = {
        DomainEventType.SESSION_CREATED: (SseEventType.SESSION_CREATED, None),
        DomainEventType.SESSION_MESSAGE_APPENDED: (
            SseEventType.SESSION_MESSAGE_APPENDED,
            FeedEntryType.USER_MESSAGE,
        ),
        DomainEventType.STAGE_STARTED: (
            SseEventType.STAGE_STARTED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.STAGE_UPDATED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.REQUIREMENT_PARSED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.SOLUTION_PROPOSED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.SOLUTION_VALIDATION_COMPLETED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.CLARIFICATION_REQUESTED: (
            SseEventType.CLARIFICATION_REQUESTED,
            FeedEntryType.CONTROL_ITEM,
        ),
        DomainEventType.CLARIFICATION_ANSWERED: (
            SseEventType.CLARIFICATION_ANSWERED,
            FeedEntryType.USER_MESSAGE,
        ),
        DomainEventType.CLARIFICATION_RESOLVED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.APPROVAL_REQUESTED: (
            SseEventType.APPROVAL_REQUESTED,
            FeedEntryType.APPROVAL_REQUEST,
        ),
        DomainEventType.ROLLBACK_TRIGGERED: (
            SseEventType.CONTROL_ITEM_CREATED,
            FeedEntryType.CONTROL_ITEM,
        ),
        DomainEventType.RETRY_TRIGGERED: (
            SseEventType.CONTROL_ITEM_CREATED,
            FeedEntryType.CONTROL_ITEM,
        ),
        DomainEventType.CODE_PATCH_GENERATED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.TESTS_GENERATED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.TESTS_EXECUTED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.TEST_GAP_ANALYZED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.REVIEW_COMPLETED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.COMMIT_CREATED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.MERGE_REQUEST_CREATED: (
            SseEventType.STAGE_UPDATED,
            FeedEntryType.STAGE_NODE,
        ),
        DomainEventType.RUN_PAUSED: (SseEventType.SESSION_STATUS_CHANGED, None),
        DomainEventType.RUN_RESUMED: (SseEventType.SESSION_STATUS_CHANGED, None),
    }

    assert set(expected).issubset(EventProjectionMatrix)
    for domain_event_type, (sse_event_type, feed_entry_type) in expected.items():
        assert resolve_sse_event_type(domain_event_type) is sse_event_type
        assert resolve_feed_entry_type(domain_event_type) is feed_entry_type

    assert EventProjectionTarget.NARRATIVE_FEED in resolve_projection_targets(
        DomainEventType.SESSION_MESSAGE_APPENDED
    )
    assert EventProjectionTarget.RUN_CONTROL in resolve_projection_targets(
        DomainEventType.ROLLBACK_TRIGGERED
    )
    for domain_event_type in (
        DomainEventType.REQUIREMENT_PARSED,
        DomainEventType.SOLUTION_PROPOSED,
        DomainEventType.SOLUTION_VALIDATION_COMPLETED,
    ):
        assert resolve_projection_targets(domain_event_type) == (
            EventProjectionTarget.STAGE_NODE,
        )


def test_project_loaded_is_known_but_has_no_session_sse_projection_in_e3_1() -> None:
    from backend.app.services.events import (
        DomainEventType,
        EventProjectionMatrix,
        resolve_feed_entry_type,
        resolve_projection_targets,
        resolve_sse_event_type,
    )

    assert DomainEventType.PROJECT_LOADED.value == "ProjectLoaded"
    assert DomainEventType.PROJECT_LOADED not in EventProjectionMatrix
    for resolver in (
        resolve_sse_event_type,
        resolve_feed_entry_type,
        resolve_projection_targets,
    ):
        with pytest.raises(ValueError, match="no session SSE projection.*E3\\.1"):
            resolver(DomainEventType.PROJECT_LOADED)


def test_matrix_rejects_raw_langgraph_events_as_external_domain_events() -> None:
    from backend.app.services.events import resolve_sse_event_type

    with pytest.raises(ValueError, match="raw graph event"):
        resolve_sse_event_type("GraphNodeStarted")


def test_event_store_append_persists_valid_sse_event_with_trace_correlation(
    tmp_path,
) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: "event-run-1")

        event = store.append(
            DomainEventType.PIPELINE_RUN_CREATED,
            payload=_run_payload(),
            trace_context=_trace(stage_run_id="stage-run-1"),
        )

        saved = session.get(DomainEventModel, "event-run-1")

    assert event.event_id == "event-run-1"
    assert event.session_id == "session-1"
    assert event.run_id == "run-1"
    assert event.stage_run_id == "stage-run-1"
    assert event.event_type is SseEventType.PIPELINE_RUN_CREATED
    assert event.occurred_at == NOW
    assert event.sequence_index == 1
    assert event.correlation_id == "correlation-1"
    assert event.causation_event_id is None
    assert saved is not None
    assert saved.event_type is SseEventType.PIPELINE_RUN_CREATED
    assert saved.correlation_id == "correlation-1"
    assert saved.payload["run"]["run_id"] == "run-1"


def test_event_store_append_requires_session_id_from_argument_or_trace(tmp_path) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: "event-run-1")

        with pytest.raises(ValueError, match="session_id"):
            store.append(
                DomainEventType.PIPELINE_RUN_CREATED,
                payload=_run_payload(),
                trace_context=_trace(session_id=None),
            )

        event = store.append(
            DomainEventType.PIPELINE_RUN_CREATED,
            payload=_run_payload(),
            trace_context=_trace(session_id=None),
            session_id="session-explicit",
        )

    assert event.session_id == "session-explicit"


def test_event_store_rejects_explicit_identity_mismatches_before_persisting(
    tmp_path,
) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: "event-invalid")

        with pytest.raises(ValueError, match="session_id.*TraceContext"):
            store.append(
                DomainEventType.PIPELINE_RUN_CREATED,
                payload=_run_payload(),
                trace_context=_trace(session_id="session-trace"),
                session_id="session-explicit",
            )

        with pytest.raises(ValueError, match="run_id.*TraceContext"):
            store.append(
                DomainEventType.PIPELINE_RUN_CREATED,
                payload=_run_payload(run_id="run-explicit"),
                trace_context=_trace(run_id="run-trace"),
                run_id="run-explicit",
            )

        with pytest.raises(ValueError, match="stage_run_id.*TraceContext"):
            store.append(
                DomainEventType.STAGE_UPDATED,
                payload=_stage_payload(stage_run_id="stage-run-explicit"),
                trace_context=_trace(stage_run_id="stage-run-trace"),
                stage_run_id="stage-run-explicit",
            )

        assert session.query(DomainEventModel).count() == 0


def test_event_store_allows_explicit_ids_to_fill_missing_trace_identity(tmp_path) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: "event-stage-1")

        event = store.append(
            DomainEventType.STAGE_UPDATED,
            payload=_stage_payload(run_id="run-explicit", stage_run_id="stage-explicit"),
            trace_context=_trace(session_id=None, run_id=None, stage_run_id=None),
            session_id="session-explicit",
            run_id="run-explicit",
            stage_run_id="stage-explicit",
        )

        saved = session.get(DomainEventModel, "event-stage-1")

    assert event.session_id == "session-explicit"
    assert event.run_id == "run-explicit"
    assert event.stage_run_id == "stage-explicit"
    assert saved is not None
    assert saved.session_id == "session-explicit"


def test_event_store_lists_session_events_after_sequence_in_stable_order(
    tmp_path,
) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    ids = iter(["event-1", "event-2", "event-other"])
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: next(ids))
        store.append(
            DomainEventType.PIPELINE_RUN_CREATED,
            payload=_run_payload(),
            trace_context=_trace(),
        )
        store.append(
            DomainEventType.RUN_COMPLETED,
            payload=_session_status_payload(),
            trace_context=_trace(),
        )
        store.append(
            DomainEventType.RUN_COMPLETED,
            payload=_session_status_payload(session_id="session-2", current_run_id=None),
            trace_context=_trace(session_id="session-2", run_id=None),
        )

        after_first = store.list_after("session-1", after_sequence_index=1)
        whole_session = store.list_for_session("session-1")
        limited = store.list_for_session("session-1", limit=1)

    assert [event.event_id for event in after_first] == ["event-2"]
    assert [event.event_id for event in whole_session] == ["event-1", "event-2"]
    assert [event.sequence_index for event in whole_session] == [1, 2]
    assert [event.event_id for event in limited] == ["event-1"]


def test_event_store_sequential_appends_allocate_session_sequence_indexes(
    tmp_path,
) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    ids = iter(["event-1", "event-2"])
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: next(ids))

        first = store.append(
            DomainEventType.PIPELINE_RUN_CREATED,
            payload=_run_payload(),
            trace_context=_trace(),
        )
        second = store.append(
            DomainEventType.RUN_COMPLETED,
            payload=_session_status_payload(),
            trace_context=_trace(),
        )

    assert [first.sequence_index, second.sequence_index] == [1, 2]


def test_event_store_uses_process_high_water_when_db_max_is_stale_across_sessions(
    tmp_path,
) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    first_session = manager.session(DatabaseRole.EVENT)
    second_session = manager.session(DatabaseRole.EVENT)
    try:
        first_store = EventStore(
            first_session,
            now=lambda: NOW,
            id_factory=lambda: "event-1",
        )
        second_store = EventStore(
            second_session,
            now=lambda: NOW,
            id_factory=lambda: "event-2",
        )

        first = first_store.append(
            DomainEventType.PIPELINE_RUN_CREATED,
            payload=_run_payload(),
            trace_context=_trace(),
        )
        first_session.rollback()
        second = second_store.append(
            DomainEventType.RUN_COMPLETED,
            payload=_session_status_payload(),
            trace_context=_trace(),
        )
    finally:
        first_session.close()
        second_session.close()

    assert [first.sequence_index, second.sequence_index] == [1, 2]


def test_event_store_list_after_orders_same_sequence_by_event_id(tmp_path) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW)
        session.add_all(
            [
                DomainEventModel(
                    event_id="event-b",
                    session_id="session-1",
                    run_id="run-1",
                    stage_run_id="stage-run-1",
                    event_type=SseEventType.STAGE_UPDATED,
                    sequence_index=2,
                    occurred_at=NOW,
                    payload=_stage_payload(),
                    correlation_id="correlation-1",
                    causation_event_id=None,
                    created_at=NOW,
                ),
                DomainEventModel(
                    event_id="event-a",
                    session_id="session-1",
                    run_id="run-1",
                    stage_run_id="stage-run-1",
                    event_type=SseEventType.STAGE_UPDATED,
                    sequence_index=2,
                    occurred_at=NOW,
                    payload=_stage_payload(),
                    correlation_id="correlation-1",
                    causation_event_id=None,
                    created_at=NOW,
                ),
                DomainEventModel(
                    event_id="event-c",
                    session_id="session-2",
                    run_id="run-1",
                    stage_run_id="stage-run-1",
                    event_type=SseEventType.STAGE_UPDATED,
                    sequence_index=2,
                    occurred_at=NOW,
                    payload=_stage_payload(),
                    correlation_id="correlation-1",
                    causation_event_id=None,
                    created_at=NOW,
                ),
            ]
        )
        session.flush()

        events = store.list_after("session-1", after_sequence_index=1)

    assert [event.event_id for event in events] == ["event-a", "event-b"]


def test_event_store_validates_payload_against_resolved_sse_contract(tmp_path) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: "event-invalid")

        with pytest.raises(ValidationError, match="pipeline_run_created payload"):
            store.append(
                DomainEventType.PIPELINE_RUN_CREATED,
                payload={"stage_node": {}},
                trace_context=_trace(),
            )

        assert session.query(DomainEventModel).count() == 0


def test_event_store_rejects_payload_stage_identity_mismatches_before_persisting(
    tmp_path,
) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: "event-invalid")

        with pytest.raises(ValueError, match="stage_node.stage_run_id"):
            store.append(
                DomainEventType.STAGE_UPDATED,
                payload=_stage_payload(stage_run_id="stage-payload"),
                trace_context=_trace(stage_run_id="stage-trace"),
            )

        with pytest.raises(ValueError, match="payload.stage_run_id"):
            store.append(
                DomainEventType.CLARIFICATION_REQUESTED,
                payload=_clarification_payload(stage_run_id="stage-payload"),
                trace_context=_trace(stage_run_id="stage-trace"),
            )

        with pytest.raises(ValueError, match="payload.stage_run_id"):
            store.append(
                DomainEventType.CLARIFICATION_REQUESTED,
                payload=_clarification_payload(stage_run_id=None),
                trace_context=_trace(stage_run_id="stage-trace"),
            )

        assert session.query(DomainEventModel).count() == 0


def test_event_store_persists_canonical_validated_json_payload(tmp_path) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: "event-stage-1")

        event = store.append(
            DomainEventType.STAGE_UPDATED,
            payload=_stage_payload_python_mode(),
            trace_context=_trace(stage_run_id="stage-run-1"),
        )

        saved = session.get(DomainEventModel, "event-stage-1")

    assert saved is not None
    assert saved.payload == event.payload
    assert saved.payload["stage_node"]["type"] == FeedEntryType.STAGE_NODE.value
    assert isinstance(saved.payload["stage_node"]["occurred_at"], str)
    assert isinstance(saved.payload["stage_node"]["started_at"], str)
    assert saved.payload["stage_node"]["stage_type"] == StageType.CODE_GENERATION.value
    assert saved.payload["stage_node"]["status"] == StageStatus.RUNNING.value
    provider_item = saved.payload["stage_node"]["items"][0]
    assert provider_item["type"] == StageItemType.PROVIDER_CALL.value
    assert isinstance(provider_item["occurred_at"], str)
    assert provider_item["circuit_breaker_status"] == (
        ProviderCircuitBreakerStatus.CLOSED.value
    )


def test_event_store_rejects_payload_run_id_mismatch_before_persisting(tmp_path) -> None:
    from backend.app.services.events import DomainEventType, EventStore

    manager = _manager(tmp_path)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=lambda: "event-invalid")

        with pytest.raises(ValidationError, match="run.run_id must match run_id"):
            store.append(
                DomainEventType.PIPELINE_RUN_CREATED,
                payload=_run_payload(run_id="run-2"),
                trace_context=_trace(run_id="run-1"),
            )

        assert session.query(DomainEventModel).count() == 0


def test_run_completed_uses_session_status_event_without_system_status_feed() -> None:
    from backend.app.services.events import (
        DomainEventType,
        resolve_feed_entry_type,
        resolve_sse_event_type,
    )

    assert resolve_sse_event_type(DomainEventType.RUN_COMPLETED) is (
        SseEventType.SESSION_STATUS_CHANGED
    )
    assert resolve_feed_entry_type(DomainEventType.RUN_COMPLETED) is None
    assert resolve_sse_event_type(DomainEventType.RUN_FAILED) is (
        SseEventType.SYSTEM_STATUS
    )
    assert resolve_feed_entry_type(DomainEventType.RUN_FAILED) is (
        FeedEntryType.SYSTEM_STATUS
    )
    assert resolve_sse_event_type(DomainEventType.RUN_TERMINATED) is (
        SseEventType.SYSTEM_STATUS
    )
    assert resolve_feed_entry_type(DomainEventType.RUN_TERMINATED) is (
        FeedEntryType.SYSTEM_STATUS
    )
