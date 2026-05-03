from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from time import monotonic

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.schemas.run import RunTimelineProjection
from backend.app.schemas.workspace import SessionWorkspaceProjection
from backend.app.services.events import EventStore
from backend.app.services.projections.timeline import (
    TimelineProjectionService,
    TimelineProjectionServiceError,
)
from backend.app.services.projections.workspace import (
    WorkspaceProjectionService,
    WorkspaceProjectionServiceError,
)


router = APIRouter(tags=["query"])


def get_control_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.CONTROL)
    try:
        yield session
    finally:
        session.close()


def get_runtime_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.RUNTIME)
    try:
        yield session
    finally:
        session.close()


def get_event_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.EVENT)
    try:
        yield session
    finally:
        session.close()


def get_workspace_projection_service(
    request: Request,
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    event_session: Session = Depends(get_event_session),
) -> Iterator[WorkspaceProjectionService]:
    settings = request.app.state.environment_settings
    yield WorkspaceProjectionService(
        control_session,
        runtime_session,
        event_session,
        credential_env_prefixes=settings.credential_env_prefixes,
    )


def get_timeline_projection_service(
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    event_session: Session = Depends(get_event_session),
) -> Iterator[TimelineProjectionService]:
    yield TimelineProjectionService(
        control_session,
        runtime_session,
        event_session,
    )


def _raise_api_error(
    exc: WorkspaceProjectionServiceError | TimelineProjectionServiceError,
) -> None:
    raise ApiError(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
    ) from exc


@router.get(
    "/sessions/{sessionId}/workspace",
    response_model=SessionWorkspaceProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_session_workspace(
    sessionId: str,
    service: WorkspaceProjectionService = Depends(get_workspace_projection_service),
) -> SessionWorkspaceProjection:
    try:
        return service.get_session_workspace(sessionId)
    except WorkspaceProjectionServiceError as exc:
        _raise_api_error(exc)


@router.get(
    "/runs/{runId}/timeline",
    response_model=RunTimelineProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_run_timeline(
    runId: str,
    service: TimelineProjectionService = Depends(get_timeline_projection_service),
) -> RunTimelineProjection:
    try:
        return service.get_run_timeline(runId)
    except TimelineProjectionServiceError as exc:
        _raise_api_error(exc)


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
                    payload = {
                        "event_id": event.event_id,
                        "session_id": event.session_id,
                        "run_id": event.run_id,
                        "event_type": event.event_type.value,
                        "occurred_at": event.occurred_at.isoformat(),
                        "payload": event.payload,
                    }
                    yield (
                        f"id: {event.sequence_index}\n"
                        f"event: {event.event_type.value}\n"
                        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
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
