from __future__ import annotations

from collections.abc import Callable, Coroutine
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.runtime_settings import (
    PlatformRuntimeSettingsRead,
    PlatformRuntimeSettingsUpdate,
)
from backend.app.services.runtime_settings import (
    PlatformRuntimeSettingsService,
    RuntimeSettingsServiceError,
)


class RuntimeSettingsRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def custom_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                raise ApiError(
                    ErrorCode.CONFIG_INVALID_VALUE,
                    "Request validation failed.",
                    422,
                ) from exc

        return custom_handler


router = APIRouter(tags=["runtime-settings"], route_class=RuntimeSettingsRoute)


def get_control_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.CONTROL)
    try:
        yield session
    finally:
        session.close()


def get_runtime_settings_service(
    request: Request,
    session: Session = Depends(get_control_session),
) -> Iterator[PlatformRuntimeSettingsService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield PlatformRuntimeSettingsService(
            session,
            audit_service=audit_service,
            log_writer=audit_writer,
        )
    finally:
        log_session.close()


def _raise_api_error(exc: RuntimeSettingsServiceError) -> None:
    raise ApiError(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
    ) from exc


@router.get(
    "/runtime-settings",
    response_model=PlatformRuntimeSettingsRead,
    responses={
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_platform_runtime_settings(
    service: PlatformRuntimeSettingsService = Depends(get_runtime_settings_service),
) -> PlatformRuntimeSettingsRead:
    try:
        return service.get_current_settings(trace_context=get_trace_context())
    except RuntimeSettingsServiceError as exc:
        _raise_api_error(exc)


@router.put(
    "/runtime-settings",
    response_model=PlatformRuntimeSettingsRead,
    responses={
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def update_platform_runtime_settings(
    body: PlatformRuntimeSettingsUpdate,
    service: PlatformRuntimeSettingsService = Depends(get_runtime_settings_service),
) -> PlatformRuntimeSettingsRead:
    try:
        return service.update_settings(body, trace_context=get_trace_context())
    except RuntimeSettingsServiceError as exc:
        _raise_api_error(exc)
