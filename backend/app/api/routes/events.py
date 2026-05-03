from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from time import monotonic

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.db.base import DatabaseRole
from backend.app.api.errors import ErrorResponse
from backend.app.db.models.runtime import ToolConfirmationRequestModel
from backend.app.db.session import DatabaseManager
from backend.app.schemas.feed import ToolConfirmationFeedEntry
from backend.app.services.events import DomainEvent, EventStore, SseEventEncoder
from backend.app.services.publication_boundary import PublicationBoundaryService


router = APIRouter(tags=["query"])


def get_event_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.EVENT)
    try:
        yield session
    finally:
        session.close()


def get_control_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.CONTROL)
    try:
        yield session
    finally:
        session.close()


@router.get(
    "/sessions/{sessionId}/events/stream",
    responses={
        200: {
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
            "description": "Session event stream.",
        },
        422: {"model": ErrorResponse},
    },
)
def stream_session_events(
    request: Request,
    sessionId: str,
    after: int = 0,
    limit: int | None = None,
    control_session: Session = Depends(get_control_session),
    event_session: Session = Depends(get_event_session),
) -> StreamingResponse:
    bounded_limit = min(max(limit if limit is not None else 100, 1), 500)
    event_store = EventStore(event_session)
    manager: DatabaseManager = request.app.state.database_manager
    runtime_session = manager.session(DatabaseRole.RUNTIME)
    encoder = SseEventEncoder()
    cursor = _resolve_after_cursor(request, after)
    close_after_batch = limit is not None
    publication_boundary = PublicationBoundaryService(
        control_session=control_session,
        runtime_session=runtime_session,
        event_session=event_session,
    )

    async def event_frames() -> AsyncIterator[str]:
        nonlocal cursor
        last_keepalive_at = monotonic()
        try:
            while True:
                event_session.rollback()
                control_session.rollback()
                runtime_session.rollback()
                hidden_run_ids = publication_boundary.hidden_run_ids_for_session(
                    session_id=sessionId
                )
                events = event_store.list_after(
                    sessionId,
                    after_sequence_index=cursor,
                    limit=bounded_limit,
                )
                if events:
                    for event in events:
                        cursor = event.sequence_index
                        if event.run_id is not None and event.run_id in hidden_run_ids:
                            continue
                        last_keepalive_at = monotonic()
                        yield encoder.encode(
                            _hydrate_tool_confirmation_event(event, runtime_session)
                        )
                    if close_after_batch:
                        break
                    continue

                if close_after_batch:
                    break

                if await request.is_disconnected():
                    break

                if monotonic() - last_keepalive_at >= 15:
                    last_keepalive_at = monotonic()
                    yield ": keep-alive\n\n"

                await asyncio.sleep(0.5)
        finally:
            runtime_session.close()

    return StreamingResponse(
        event_frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _resolve_after_cursor(request: Request, after: int) -> int:
    last_event_id = request.headers.get("last-event-id")
    try:
        replay_cursor = int(last_event_id) if last_event_id is not None else 0
    except ValueError:
        replay_cursor = 0
    return max(after, replay_cursor, 0)


def _hydrate_tool_confirmation_event(
    event: DomainEvent,
    runtime_session: Session,
) -> DomainEvent:
    tool_confirmation = event.payload.get("tool_confirmation")
    if not isinstance(tool_confirmation, dict):
        return event
    hydrated = _hydrate_tool_confirmation_payload(tool_confirmation, runtime_session)
    if hydrated == tool_confirmation:
        return event
    return DomainEvent(
        event_id=event.event_id,
        session_id=event.session_id,
        run_id=event.run_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        payload={**event.payload, "tool_confirmation": hydrated},
        stage_run_id=event.stage_run_id,
        sequence_index=event.sequence_index,
        correlation_id=event.correlation_id,
        causation_event_id=event.causation_event_id,
    )


def _hydrate_tool_confirmation_payload(
    value: dict[str, object],
    runtime_session: Session,
) -> dict[str, object]:
    tool_confirmation_id = value.get("tool_confirmation_id")
    if not isinstance(tool_confirmation_id, str):
        return value
    if value.get("decision") != "denied":
        hydrated = {
            **value,
            "deny_followup_action": None,
            "deny_followup_summary": None,
        }
        return ToolConfirmationFeedEntry.model_validate(hydrated).model_dump(
            mode="json"
        )
    request = runtime_session.get(ToolConfirmationRequestModel, tool_confirmation_id)
    hydrated = {
        **value,
        "deny_followup_action": (
            request.deny_followup_action if request is not None else None
        ),
        "deny_followup_summary": (
            request.deny_followup_summary if request is not None else None
        ),
    }
    return ToolConfirmationFeedEntry.model_validate(hydrated).model_dump(mode="json")
