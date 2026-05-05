from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.api.routes import events
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.log_query import LogQueryService, LogQueryServiceError
from backend.app.schemas.inspector import (
    ControlItemInspectorProjection,
    DeliveryResultDetailProjection,
    StageInspectorProjection,
    ToolConfirmationInspectorProjection,
)
from backend.app.schemas.observability import (
    LogCategory,
    LogLevel,
    RunLogQueryResponse,
)
from backend.app.schemas.run import RunStatusSummaryProjection, RunTimelineProjection
from backend.app.schemas.workspace import SessionWorkspaceProjection
from backend.app.services.projections.inspector import (
    InspectorProjectionService,
    InspectorProjectionServiceError,
)
from backend.app.services.projections.timeline import (
    TimelineProjectionService,
    TimelineProjectionServiceError,
)
from backend.app.services.projections.workspace import (
    WorkspaceProjectionService,
    WorkspaceProjectionServiceError,
)


class LogQueryRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def custom_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                raise ApiError(
                    error_code=ErrorCode.LOG_QUERY_INVALID,
                    message="Log query is invalid.",
                    status_code=422,
                ) from exc

        return custom_handler


router = APIRouter(tags=["query"])
log_query_router = APIRouter(tags=["query"], route_class=LogQueryRoute)
router.include_router(events.router)


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


def get_log_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.LOG)
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


def get_inspector_projection_service(
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    event_session: Session = Depends(get_event_session),
) -> Iterator[InspectorProjectionService]:
    yield InspectorProjectionService(
        control_session,
        runtime_session,
        event_session,
    )


def get_log_query_service(
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    log_session: Session = Depends(get_log_session),
) -> Iterator[LogQueryService]:
    yield LogQueryService(control_session, runtime_session, log_session)


def _raise_api_error(
    exc: (
        WorkspaceProjectionServiceError
        | TimelineProjectionServiceError
        | InspectorProjectionServiceError
        | LogQueryServiceError
    ),
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
    "/runs/{runId}",
    response_model=RunStatusSummaryProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_run_summary(
    runId: str,
    service: TimelineProjectionService = Depends(get_timeline_projection_service),
) -> RunStatusSummaryProjection:
    try:
        return service.get_run_summary(runId)
    except TimelineProjectionServiceError as exc:
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


@log_query_router.get(
    "/runs/{runId}/logs",
    response_model=RunLogQueryResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_run_logs(
    runId: str,
    level: LogLevel | None = None,
    category: LogCategory | None = None,
    source: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = None,
    limit: int | None = Query(default=None),
    service: LogQueryService = Depends(get_log_query_service),
) -> RunLogQueryResponse:
    try:
        return service.list_run_logs(
            runId,
            level=level,
            category=category,
            source=source,
            since=since,
            until=until,
            cursor=cursor,
            limit=limit,
        )
    except LogQueryServiceError as exc:
        _raise_api_error(exc)


@log_query_router.get(
    "/stages/{stageRunId}/logs",
    response_model=RunLogQueryResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_stage_logs(
    stageRunId: str,
    level: LogLevel | None = None,
    category: LogCategory | None = None,
    source: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = None,
    limit: int | None = Query(default=None),
    service: LogQueryService = Depends(get_log_query_service),
) -> RunLogQueryResponse:
    try:
        return service.list_stage_logs(
            stageRunId,
            level=level,
            category=category,
            source=source,
            since=since,
            until=until,
            cursor=cursor,
            limit=limit,
        )
    except LogQueryServiceError as exc:
        _raise_api_error(exc)


router.include_router(log_query_router)


@router.get(
    "/stages/{stageRunId}/inspector",
    response_model=StageInspectorProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_stage_inspector(
    stageRunId: str,
    service: InspectorProjectionService = Depends(get_inspector_projection_service),
) -> StageInspectorProjection:
    try:
        return service.get_stage_inspector(stageRunId)
    except InspectorProjectionServiceError as exc:
        _raise_api_error(exc)


@router.get(
    "/control-records/{controlRecordId}",
    response_model=ControlItemInspectorProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_control_item_detail(
    controlRecordId: str,
    service: InspectorProjectionService = Depends(get_inspector_projection_service),
) -> ControlItemInspectorProjection:
    try:
        return service.get_control_item_detail(controlRecordId)
    except InspectorProjectionServiceError as exc:
        _raise_api_error(exc)


@router.get(
    "/tool-confirmations/{toolConfirmationId}",
    response_model=ToolConfirmationInspectorProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_tool_confirmation_detail(
    toolConfirmationId: str,
    service: InspectorProjectionService = Depends(get_inspector_projection_service),
) -> ToolConfirmationInspectorProjection:
    try:
        return service.get_tool_confirmation_detail(toolConfirmationId)
    except InspectorProjectionServiceError as exc:
        _raise_api_error(exc)


@router.get(
    "/delivery-records/{deliveryRecordId}",
    response_model=DeliveryResultDetailProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_delivery_record_detail(
    deliveryRecordId: str,
    service: InspectorProjectionService = Depends(get_inspector_projection_service),
) -> DeliveryResultDetailProjection:
    try:
        return service.get_delivery_record_detail(deliveryRecordId)
    except InspectorProjectionServiceError as exc:
        _raise_api_error(exc)
