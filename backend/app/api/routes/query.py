from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.schemas.run import RunTimelineProjection
from backend.app.schemas.workspace import SessionWorkspaceProjection
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
