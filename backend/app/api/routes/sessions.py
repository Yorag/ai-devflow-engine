from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.session import (
    SessionRead,
    SessionRenameRequest,
    SessionTemplateUpdateRequest,
)
from backend.app.services.sessions import SessionService, SessionServiceError


router = APIRouter(tags=["sessions"])


def _session_read(session: Any) -> SessionRead:
    return SessionRead.model_validate(
        {
            "session_id": session.session_id,
            "project_id": session.project_id,
            "display_name": session.display_name,
            "status": session.status,
            "selected_template_id": session.selected_template_id,
            "current_run_id": session.current_run_id,
            "latest_stage_type": session.latest_stage_type,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
    )


def _raise_api_error(exc: SessionServiceError) -> None:
    raise ApiError(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
    ) from exc


def get_control_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.CONTROL)
    try:
        yield session
    finally:
        session.close()


def get_session_service(
    request: Request,
    session: Session = Depends(get_control_session),
) -> Iterator[SessionService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield SessionService(session, audit_service=audit_service)
    finally:
        log_session.close()


@router.post(
    "/projects/{projectId}/sessions",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def create_project_session(
    projectId: str,
    service: SessionService = Depends(get_session_service),
) -> SessionRead:
    try:
        session = service.create_session(
            project_id=projectId,
            trace_context=get_trace_context(),
        )
    except SessionServiceError as exc:
        _raise_api_error(exc)
    return _session_read(session)


@router.get(
    "/projects/{projectId}/sessions",
    response_model=list[SessionRead],
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def list_project_sessions(
    projectId: str,
    service: SessionService = Depends(get_session_service),
) -> list[SessionRead]:
    try:
        sessions = service.list_project_sessions(
            project_id=projectId,
            trace_context=get_trace_context(),
        )
    except SessionServiceError as exc:
        _raise_api_error(exc)
    return [_session_read(session) for session in sessions]


@router.get(
    "/sessions/{sessionId}",
    response_model=SessionRead,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_session(
    sessionId: str,
    service: SessionService = Depends(get_session_service),
) -> SessionRead:
    session = service.get_session(
        sessionId,
        trace_context=get_trace_context(),
    )
    if session is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Session was not found.",
            404,
        )
    return _session_read(session)


@router.patch(
    "/sessions/{sessionId}",
    response_model=SessionRead,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def rename_session(
    sessionId: str,
    body: SessionRenameRequest,
    service: SessionService = Depends(get_session_service),
) -> SessionRead:
    try:
        session = service.rename_session(
            session_id=sessionId,
            display_name=body.display_name,
            trace_context=get_trace_context(),
        )
    except SessionServiceError as exc:
        _raise_api_error(exc)
    return _session_read(session)


@router.put(
    "/sessions/{sessionId}/template",
    response_model=SessionRead,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def update_session_template(
    sessionId: str,
    body: SessionTemplateUpdateRequest,
    service: SessionService = Depends(get_session_service),
) -> SessionRead:
    try:
        session = service.update_selected_template(
            session_id=sessionId,
            template_id=body.template_id,
            trace_context=get_trace_context(),
        )
    except SessionServiceError as exc:
        _raise_api_error(exc)
    return _session_read(session)
