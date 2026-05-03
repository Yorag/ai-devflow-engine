from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models.event import DomainEventModel
from backend.app.domain.enums import FeedEntryType, SseEventType
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.events import SessionEvent


JsonObject = dict[str, Any]


class DomainEventType(StrEnum):
    SESSION_CREATED = "SessionCreated"
    SESSION_MESSAGE_APPENDED = "SessionMessageAppended"
    PIPELINE_RUN_CREATED = "PipelineRunCreated"
    PROJECT_LOADED = "ProjectLoaded"
    REQUIREMENT_PARSED = "RequirementParsed"
    STAGE_STARTED = "StageStarted"
    STAGE_UPDATED = "StageUpdated"
    CLARIFICATION_REQUESTED = "ClarificationRequested"
    CLARIFICATION_ANSWERED = "ClarificationAnswered"
    CLARIFICATION_RESOLVED = "ClarificationResolved"
    APPROVAL_REQUESTED = "ApprovalRequested"
    APPROVAL_APPROVED = "ApprovalApproved"
    APPROVAL_REJECTED = "ApprovalRejected"
    SOLUTION_PROPOSED = "SolutionProposed"
    SOLUTION_VALIDATION_COMPLETED = "SolutionValidationCompleted"
    TOOL_CONFIRMATION_REQUESTED = "ToolConfirmationRequested"
    TOOL_CONFIRMATION_ALLOWED = "ToolConfirmationAllowed"
    TOOL_CONFIRMATION_DENIED = "ToolConfirmationDenied"
    PROVIDER_CALL_RETRIED = "ProviderCallRetried"
    PROVIDER_CIRCUIT_BREAKER_OPENED = "ProviderCircuitBreakerOpened"
    PROVIDER_CIRCUIT_BREAKER_RECOVERED = "ProviderCircuitBreakerRecovered"
    ROLLBACK_TRIGGERED = "RollbackTriggered"
    RETRY_TRIGGERED = "RetryTriggered"
    CODE_PATCH_GENERATED = "CodePatchGenerated"
    TESTS_GENERATED = "TestsGenerated"
    TESTS_EXECUTED = "TestsExecuted"
    TEST_GAP_ANALYZED = "TestGapAnalyzed"
    REVIEW_COMPLETED = "ReviewCompleted"
    DELIVERY_PREPARED = "DeliveryPrepared"
    COMMIT_CREATED = "CommitCreated"
    MERGE_REQUEST_CREATED = "MergeRequestCreated"
    RUN_PAUSED = "RunPaused"
    RUN_RESUMED = "RunResumed"
    RUN_COMPLETED = "RunCompleted"
    RUN_FAILED = "RunFailed"
    RUN_TERMINATED = "RunTerminated"


class EventProjectionTarget(StrEnum):
    NARRATIVE_FEED = "narrative_feed"
    SESSION_STATUS = "session_status"
    RUN_SUMMARY = "run_summary"
    STAGE_NODE = "stage_node"
    RUN_CONTROL = "run_control"
    APPROVAL = "approval"
    TOOL_CONFIRMATION = "tool_confirmation"
    PROVIDER_CALL = "provider_call"
    DELIVERY_RESULT = "delivery_result"


@dataclass(frozen=True)
class EventProjectionRule:
    domain_event_type: DomainEventType
    sse_event_type: SseEventType
    feed_entry_type: FeedEntryType | None
    projection_targets: tuple[EventProjectionTarget, ...]


RAW_GRAPH_EVENT_TYPES = frozenset(
    {
        "GraphCompiled",
        "GraphThreadStarted",
        "GraphNodeStarted",
        "GraphNodeCompleted",
        "GraphCheckpointSaved",
        "GraphInterrupted",
        "GraphResumed",
        "GraphFailed",
    }
)

KNOWN_UNMAPPED_SESSION_EVENTS = frozenset({DomainEventType.PROJECT_LOADED})

# E3.1 keeps the DB model unchanged; this only serializes same-process sequence
# allocation around max(sequence_index)+1 and flush.
_SEQUENCE_LOCKS_GUARD = Lock()
_SequenceKey = tuple[str, str]
_SEQUENCE_LOCKS: dict[_SequenceKey, Lock] = {}
_SEQUENCE_HIGH_WATER: dict[_SequenceKey, int] = {}


def _rule(
    domain_event_type: DomainEventType,
    sse_event_type: SseEventType,
    feed_entry_type: FeedEntryType | None,
    *projection_targets: EventProjectionTarget,
) -> EventProjectionRule:
    return EventProjectionRule(
        domain_event_type=domain_event_type,
        sse_event_type=sse_event_type,
        feed_entry_type=feed_entry_type,
        projection_targets=tuple(projection_targets),
    )


EventProjectionMatrix: dict[DomainEventType, EventProjectionRule] = {
    DomainEventType.SESSION_CREATED: _rule(
        DomainEventType.SESSION_CREATED,
        SseEventType.SESSION_CREATED,
        None,
        EventProjectionTarget.SESSION_STATUS,
    ),
    DomainEventType.SESSION_MESSAGE_APPENDED: _rule(
        DomainEventType.SESSION_MESSAGE_APPENDED,
        SseEventType.SESSION_MESSAGE_APPENDED,
        FeedEntryType.USER_MESSAGE,
        EventProjectionTarget.NARRATIVE_FEED,
    ),
    DomainEventType.PIPELINE_RUN_CREATED: _rule(
        DomainEventType.PIPELINE_RUN_CREATED,
        SseEventType.PIPELINE_RUN_CREATED,
        None,
        EventProjectionTarget.RUN_SUMMARY,
        EventProjectionTarget.SESSION_STATUS,
    ),
    DomainEventType.REQUIREMENT_PARSED: _rule(
        DomainEventType.REQUIREMENT_PARSED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.STAGE_STARTED: _rule(
        DomainEventType.STAGE_STARTED,
        SseEventType.STAGE_STARTED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.STAGE_UPDATED: _rule(
        DomainEventType.STAGE_UPDATED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.CLARIFICATION_REQUESTED: _rule(
        DomainEventType.CLARIFICATION_REQUESTED,
        SseEventType.CLARIFICATION_REQUESTED,
        FeedEntryType.CONTROL_ITEM,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.RUN_CONTROL,
    ),
    DomainEventType.CLARIFICATION_ANSWERED: _rule(
        DomainEventType.CLARIFICATION_ANSWERED,
        SseEventType.CLARIFICATION_ANSWERED,
        FeedEntryType.USER_MESSAGE,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.RUN_CONTROL,
    ),
    DomainEventType.CLARIFICATION_RESOLVED: _rule(
        DomainEventType.CLARIFICATION_RESOLVED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.APPROVAL_REQUESTED: _rule(
        DomainEventType.APPROVAL_REQUESTED,
        SseEventType.APPROVAL_REQUESTED,
        FeedEntryType.APPROVAL_REQUEST,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.APPROVAL,
    ),
    DomainEventType.APPROVAL_APPROVED: _rule(
        DomainEventType.APPROVAL_APPROVED,
        SseEventType.APPROVAL_RESULT,
        FeedEntryType.APPROVAL_RESULT,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.APPROVAL,
    ),
    DomainEventType.APPROVAL_REJECTED: _rule(
        DomainEventType.APPROVAL_REJECTED,
        SseEventType.APPROVAL_RESULT,
        FeedEntryType.APPROVAL_RESULT,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.APPROVAL,
    ),
    DomainEventType.SOLUTION_PROPOSED: _rule(
        DomainEventType.SOLUTION_PROPOSED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.SOLUTION_VALIDATION_COMPLETED: _rule(
        DomainEventType.SOLUTION_VALIDATION_COMPLETED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.TOOL_CONFIRMATION_REQUESTED: _rule(
        DomainEventType.TOOL_CONFIRMATION_REQUESTED,
        SseEventType.TOOL_CONFIRMATION_REQUESTED,
        FeedEntryType.TOOL_CONFIRMATION,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.TOOL_CONFIRMATION,
    ),
    DomainEventType.TOOL_CONFIRMATION_ALLOWED: _rule(
        DomainEventType.TOOL_CONFIRMATION_ALLOWED,
        SseEventType.TOOL_CONFIRMATION_RESULT,
        FeedEntryType.TOOL_CONFIRMATION,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.TOOL_CONFIRMATION,
    ),
    DomainEventType.TOOL_CONFIRMATION_DENIED: _rule(
        DomainEventType.TOOL_CONFIRMATION_DENIED,
        SseEventType.TOOL_CONFIRMATION_RESULT,
        FeedEntryType.TOOL_CONFIRMATION,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.TOOL_CONFIRMATION,
    ),
    DomainEventType.PROVIDER_CALL_RETRIED: _rule(
        DomainEventType.PROVIDER_CALL_RETRIED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
        EventProjectionTarget.PROVIDER_CALL,
    ),
    DomainEventType.PROVIDER_CIRCUIT_BREAKER_OPENED: _rule(
        DomainEventType.PROVIDER_CIRCUIT_BREAKER_OPENED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
        EventProjectionTarget.PROVIDER_CALL,
    ),
    DomainEventType.PROVIDER_CIRCUIT_BREAKER_RECOVERED: _rule(
        DomainEventType.PROVIDER_CIRCUIT_BREAKER_RECOVERED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
        EventProjectionTarget.PROVIDER_CALL,
    ),
    DomainEventType.ROLLBACK_TRIGGERED: _rule(
        DomainEventType.ROLLBACK_TRIGGERED,
        SseEventType.CONTROL_ITEM_CREATED,
        FeedEntryType.CONTROL_ITEM,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.RUN_CONTROL,
    ),
    DomainEventType.RETRY_TRIGGERED: _rule(
        DomainEventType.RETRY_TRIGGERED,
        SseEventType.CONTROL_ITEM_CREATED,
        FeedEntryType.CONTROL_ITEM,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.RUN_CONTROL,
    ),
    DomainEventType.CODE_PATCH_GENERATED: _rule(
        DomainEventType.CODE_PATCH_GENERATED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.TESTS_GENERATED: _rule(
        DomainEventType.TESTS_GENERATED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.TESTS_EXECUTED: _rule(
        DomainEventType.TESTS_EXECUTED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.TEST_GAP_ANALYZED: _rule(
        DomainEventType.TEST_GAP_ANALYZED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.REVIEW_COMPLETED: _rule(
        DomainEventType.REVIEW_COMPLETED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.DELIVERY_PREPARED: _rule(
        DomainEventType.DELIVERY_PREPARED,
        SseEventType.DELIVERY_RESULT,
        FeedEntryType.DELIVERY_RESULT,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.DELIVERY_RESULT,
    ),
    DomainEventType.COMMIT_CREATED: _rule(
        DomainEventType.COMMIT_CREATED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.MERGE_REQUEST_CREATED: _rule(
        DomainEventType.MERGE_REQUEST_CREATED,
        SseEventType.STAGE_UPDATED,
        FeedEntryType.STAGE_NODE,
        EventProjectionTarget.STAGE_NODE,
    ),
    DomainEventType.RUN_PAUSED: _rule(
        DomainEventType.RUN_PAUSED,
        SseEventType.SESSION_STATUS_CHANGED,
        None,
        EventProjectionTarget.SESSION_STATUS,
        EventProjectionTarget.RUN_SUMMARY,
    ),
    DomainEventType.RUN_RESUMED: _rule(
        DomainEventType.RUN_RESUMED,
        SseEventType.SESSION_STATUS_CHANGED,
        None,
        EventProjectionTarget.SESSION_STATUS,
        EventProjectionTarget.RUN_SUMMARY,
    ),
    DomainEventType.RUN_COMPLETED: _rule(
        DomainEventType.RUN_COMPLETED,
        SseEventType.SESSION_STATUS_CHANGED,
        None,
        EventProjectionTarget.SESSION_STATUS,
        EventProjectionTarget.RUN_SUMMARY,
    ),
    DomainEventType.RUN_FAILED: _rule(
        DomainEventType.RUN_FAILED,
        SseEventType.SYSTEM_STATUS,
        FeedEntryType.SYSTEM_STATUS,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.SESSION_STATUS,
        EventProjectionTarget.RUN_SUMMARY,
    ),
    DomainEventType.RUN_TERMINATED: _rule(
        DomainEventType.RUN_TERMINATED,
        SseEventType.SYSTEM_STATUS,
        FeedEntryType.SYSTEM_STATUS,
        EventProjectionTarget.NARRATIVE_FEED,
        EventProjectionTarget.SESSION_STATUS,
        EventProjectionTarget.RUN_SUMMARY,
    ),
}


def _coerce_domain_event_type(
    domain_event_type: DomainEventType | str,
) -> DomainEventType:
    if isinstance(domain_event_type, DomainEventType):
        return domain_event_type
    if domain_event_type in RAW_GRAPH_EVENT_TYPES:
        raise ValueError(f"raw graph event cannot be externalized: {domain_event_type}")
    try:
        return DomainEventType(domain_event_type)
    except ValueError as exc:
        raise ValueError(f"unknown domain event type: {domain_event_type}") from exc


def event_projection_rule(
    domain_event_type: DomainEventType | str,
) -> EventProjectionRule:
    resolved_domain_event_type = _coerce_domain_event_type(domain_event_type)
    if resolved_domain_event_type in KNOWN_UNMAPPED_SESSION_EVENTS:
        raise ValueError(
            f"{resolved_domain_event_type.value} has no session SSE projection in E3.1"
        )
    return EventProjectionMatrix[resolved_domain_event_type]


def resolve_sse_event_type(
    domain_event_type: DomainEventType | str,
) -> SseEventType:
    return event_projection_rule(domain_event_type).sse_event_type


def resolve_feed_entry_type(
    domain_event_type: DomainEventType | str,
) -> FeedEntryType | None:
    return event_projection_rule(domain_event_type).feed_entry_type


def resolve_projection_targets(
    domain_event_type: DomainEventType | str,
) -> tuple[EventProjectionTarget, ...]:
    return event_projection_rule(domain_event_type).projection_targets


def _resolve_trace_identity(
    *,
    field_name: str,
    explicit_value: str | None,
    trace_value: str | None,
    required: bool = False,
) -> str | None:
    if explicit_value is not None and trace_value is not None:
        if explicit_value != trace_value:
            raise ValueError(
                f"{field_name} does not match TraceContext {field_name}"
            )
        return explicit_value
    resolved_value = explicit_value if explicit_value is not None else trace_value
    if required and resolved_value is None:
        raise ValueError(f"{field_name} is required when TraceContext has no {field_name}")
    return resolved_value


def _validate_payload_stage_identity(
    *,
    payload: Mapping[str, Any],
    stage_run_id: str | None,
) -> None:
    if stage_run_id is None:
        return

    stage_node = payload.get("stage_node")
    if isinstance(stage_node, Mapping):
        payload_stage_run_id = stage_node.get("stage_run_id")
        if payload_stage_run_id is not None and payload_stage_run_id != stage_run_id:
            raise ValueError("stage_node.stage_run_id must match stage_run_id")

    if "stage_run_id" not in payload:
        return
    payload_stage_run_id = payload["stage_run_id"]
    if payload_stage_run_id != stage_run_id:
        raise ValueError("payload.stage_run_id must match stage_run_id")


def _sequence_lock_for(sequence_key: _SequenceKey) -> Lock:
    with _SEQUENCE_LOCKS_GUARD:
        if sequence_key not in _SEQUENCE_LOCKS:
            _SEQUENCE_LOCKS[sequence_key] = Lock()
        return _SEQUENCE_LOCKS[sequence_key]


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    session_id: str
    run_id: str | None
    event_type: SseEventType
    occurred_at: datetime
    payload: JsonObject
    stage_run_id: str | None
    sequence_index: int
    correlation_id: str | None
    causation_event_id: str | None

    @classmethod
    def from_model(cls, model: DomainEventModel) -> DomainEvent:
        return cls(
            event_id=model.event_id,
            session_id=model.session_id,
            run_id=model.run_id,
            stage_run_id=model.stage_run_id,
            event_type=model.event_type,
            sequence_index=model.sequence_index,
            occurred_at=model.occurred_at,
            payload=dict(model.payload),
            correlation_id=model.correlation_id,
            causation_event_id=model.causation_event_id,
        )


class SseEventEncoder:
    def encode(self, event: DomainEvent) -> str:
        envelope: JsonObject = {
            "event_id": event.event_id,
            "session_id": event.session_id,
            "run_id": event.run_id,
            "event_type": event.event_type.value,
            "occurred_at": event.occurred_at.isoformat(),
            "payload": event.payload,
        }
        if event.correlation_id is not None:
            envelope["correlation_id"] = event.correlation_id
        return (
            f"id: {event.sequence_index}\n"
            f"event: {event.event_type.value}\n"
            f"data: {json.dumps(envelope, separators=(',', ':'))}\n\n"
        )


class EventStore:
    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: f"event-{uuid4().hex}")

    def append(
        self,
        domain_event_type: DomainEventType | str,
        *,
        payload: JsonObject,
        trace_context: TraceContext,
        session_id: str | None = None,
        run_id: str | None = None,
        stage_run_id: str | None = None,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
        causation_event_id: str | None = None,
    ) -> DomainEvent:
        resolved_session_id = _resolve_trace_identity(
            field_name="session_id",
            explicit_value=session_id,
            trace_value=trace_context.session_id,
            required=True,
        )
        resolved_run_id = _resolve_trace_identity(
            field_name="run_id",
            explicit_value=run_id,
            trace_value=trace_context.run_id,
        )
        resolved_stage_run_id = _resolve_trace_identity(
            field_name="stage_run_id",
            explicit_value=stage_run_id,
            trace_value=trace_context.stage_run_id,
        )
        resolved_event_type = resolve_sse_event_type(domain_event_type)
        resolved_occurred_at = occurred_at or self._now()
        resolved_event_id = event_id or self._id_factory()

        validated_event = SessionEvent(
            event_id=resolved_event_id,
            session_id=resolved_session_id,
            run_id=resolved_run_id,
            event_type=resolved_event_type,
            occurred_at=resolved_occurred_at,
            payload=payload,
        )
        validated_payload = json.loads(validated_event.model_dump_json())["payload"]
        _validate_payload_stage_identity(
            payload=validated_payload,
            stage_run_id=resolved_stage_run_id,
        )

        sequence_key = self._sequence_key(resolved_session_id)
        with _sequence_lock_for(sequence_key):
            sequence_index = self._next_sequence_index(
                resolved_session_id,
                sequence_key=sequence_key,
            )
            _SEQUENCE_HIGH_WATER[sequence_key] = sequence_index
            model = DomainEventModel(
                event_id=resolved_event_id,
                session_id=resolved_session_id,
                run_id=resolved_run_id,
                stage_run_id=resolved_stage_run_id,
                event_type=resolved_event_type,
                sequence_index=sequence_index,
                occurred_at=resolved_occurred_at,
                payload=validated_payload,
                correlation_id=trace_context.correlation_id,
                causation_event_id=causation_event_id,
                created_at=self._now(),
            )
            self._session.add(model)
            self._session.flush()
        return DomainEvent.from_model(model)

    def list_after(
        self,
        session_id: str,
        *,
        after_sequence_index: int,
        limit: int | None = None,
    ) -> list[DomainEvent]:
        statement = (
            select(DomainEventModel)
            .where(
                DomainEventModel.session_id == session_id,
                DomainEventModel.sequence_index > after_sequence_index,
            )
            .order_by(
                DomainEventModel.sequence_index.asc(),
                DomainEventModel.event_id.asc(),
            )
        )
        if limit is not None:
            statement = statement.limit(limit)
        return [
            DomainEvent.from_model(model)
            for model in self._session.execute(statement).scalars().all()
        ]

    def list_for_session(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[DomainEvent]:
        statement = (
            select(DomainEventModel)
            .where(DomainEventModel.session_id == session_id)
            .order_by(
                DomainEventModel.sequence_index.asc(),
                DomainEventModel.event_id.asc(),
            )
        )
        if limit is not None:
            statement = statement.limit(limit)
        return [
            DomainEvent.from_model(model)
            for model in self._session.execute(statement).scalars().all()
        ]

    def _sequence_key(self, session_id: str) -> _SequenceKey:
        bind = self._session.get_bind()
        return (str(bind.url), session_id)

    def _next_sequence_index(
        self,
        session_id: str,
        *,
        sequence_key: _SequenceKey,
    ) -> int:
        current_sequence_index = self._session.execute(
            select(func.max(DomainEventModel.sequence_index)).where(
                DomainEventModel.session_id == session_id
            )
        ).scalar_one()
        db_high_water = int(current_sequence_index or 0)
        process_high_water = _SEQUENCE_HIGH_WATER.get(sequence_key, 0)
        return max(db_high_water, process_high_water) + 1


__all__ = [
    "DomainEvent",
    "DomainEventType",
    "EventProjectionMatrix",
    "EventProjectionRule",
    "EventProjectionTarget",
    "EventStore",
    "SseEventEncoder",
    "event_projection_rule",
    "resolve_feed_entry_type",
    "resolve_projection_targets",
    "resolve_sse_event_type",
]
