from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.project import ProjectCreateRequest, ProjectRead
from backend.app.services.projects import ProjectService, ProjectServiceError


router = APIRouter(tags=["projects"])


def _project_read(project: Any) -> ProjectRead:
    return ProjectRead.model_validate(
        {
            "project_id": project.project_id,
            "name": project.name,
            "root_path": project.root_path,
            "default_delivery_channel_id": project.default_delivery_channel_id,
            "is_default": project.is_default,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
    )


def get_control_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.CONTROL)
    try:
        yield session
    finally:
        session.close()


def get_project_service(
    request: Request,
    session: Session = Depends(get_control_session),
) -> Iterator[ProjectService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield ProjectService(
            session,
            settings=settings,
            audit_service=audit_service,
        )
    finally:
        log_session.close()


@router.get(
    "/projects",
    response_model=list[ProjectRead],
    responses={500: {"model": ErrorResponse}},
)
def list_projects(service: ProjectService = Depends(get_project_service)) -> list[ProjectRead]:
    projects = service.list_projects(trace_context=get_trace_context())
    return [_project_read(project) for project in projects]


@router.post(
    "/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def create_project(
    body: ProjectCreateRequest,
    service: ProjectService = Depends(get_project_service),
) -> ProjectRead:
    try:
        project = service.create_project(
            root_path=body.root_path,
            trace_context=get_trace_context(),
        )
    except ProjectServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
        ) from exc
    return _project_read(project)
