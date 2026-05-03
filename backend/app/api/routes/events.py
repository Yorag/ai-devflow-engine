from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from time import monotonic

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.api.errors import ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.services.events import EventStore, SseEventEncoder


router = APIRouter(tags=["query"])


def get_event_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.EVENT)
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
    event_session: Session = Depends(get_event_session),
) -> StreamingResponse:
    bounded_limit = min(max(limit if limit is not None else 100, 1), 500)
    event_store = EventStore(event_session)
    encoder = SseEventEncoder()
    cursor = _resolve_after_cursor(request, after)
    close_after_batch = limit is not None

    async def event_frames() -> AsyncIterator[str]:
        nonlocal cursor
        last_keepalive_at = monotonic()
        while True:
            event_session.rollback()
            events = event_store.list_after(
                sessionId,
                after_sequence_index=cursor,
                limit=bounded_limit,
            )
            if events:
                for event in events:
                    cursor = event.sequence_index
                    last_keepalive_at = monotonic()
                    yield encoder.encode(event)
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
