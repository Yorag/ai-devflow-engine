from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.provider import ProviderRead, ProviderWriteRequest
from backend.app.services.providers import ProviderService, ProviderServiceError
from backend.app.services.templates import TemplateService


router = APIRouter(tags=["providers"])


def _provider_read(provider: Any, *, service: ProviderService) -> ProviderRead:
    return ProviderRead.model_validate(
        {
            "provider_id": provider.provider_id,
            "display_name": provider.display_name,
            "provider_source": provider.provider_source,
            "protocol_type": provider.protocol_type,
            "base_url": provider.base_url,
            "api_key_ref": service.api_key_ref_for_projection(provider.api_key_ref),
            "default_model_id": provider.default_model_id,
            "supported_model_ids": provider.supported_model_ids,
            "is_enabled": provider.is_enabled,
            "runtime_capabilities": provider.runtime_capabilities,
            "created_at": provider.created_at,
            "updated_at": provider.updated_at,
        }
    )


def _raise_api_error(exc: ProviderServiceError) -> None:
    raise ApiError(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
    ) from exc


def _refresh_system_templates_after_provider_change(
    service: TemplateService,
) -> None:
    service.seed_system_templates(trace_context=get_trace_context())


def get_control_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.CONTROL)
    try:
        yield session
    finally:
        session.close()


def get_provider_service(
    request: Request,
    session: Session = Depends(get_control_session),
) -> Iterator[ProviderService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield ProviderService(
            session,
            audit_service=audit_service,
            credential_env_prefixes=settings.credential_env_prefixes,
        )
    finally:
        log_session.close()


def get_template_service(
    request: Request,
    session: Session = Depends(get_control_session),
) -> Iterator[TemplateService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield TemplateService(
            session,
            audit_service=audit_service,
        )
    finally:
        log_session.close()


@router.get(
    "/providers",
    response_model=list[ProviderRead],
    responses={500: {"model": ErrorResponse}},
)
def list_providers(
    service: ProviderService = Depends(get_provider_service),
) -> list[ProviderRead]:
    providers = service.list_providers(trace_context=get_trace_context())
    return [_provider_read(provider, service=service) for provider in providers]


@router.post(
    "/providers",
    response_model=ProviderRead,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def create_provider(
    body: ProviderWriteRequest,
    service: ProviderService = Depends(get_provider_service),
    template_service: TemplateService = Depends(get_template_service),
) -> ProviderRead:
    try:
        provider = service.create_custom_provider(
            body,
            trace_context=get_trace_context(),
        )
        _refresh_system_templates_after_provider_change(template_service)
    except ProviderServiceError as exc:
        _raise_api_error(exc)
    return _provider_read(provider, service=service)


@router.get(
    "/providers/{providerId}",
    response_model=ProviderRead,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_provider(
    providerId: str,
    service: ProviderService = Depends(get_provider_service),
) -> ProviderRead:
    provider = service.get_provider(providerId, trace_context=get_trace_context())
    if provider is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Provider was not found.", 404)
    return _provider_read(provider, service=service)


@router.patch(
    "/providers/{providerId}",
    response_model=ProviderRead,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def patch_provider(
    providerId: str,
    body: ProviderWriteRequest,
    service: ProviderService = Depends(get_provider_service),
    template_service: TemplateService = Depends(get_template_service),
) -> ProviderRead:
    try:
        provider = service.patch_provider(
            providerId,
            body,
            trace_context=get_trace_context(),
        )
        _refresh_system_templates_after_provider_change(template_service)
    except ProviderServiceError as exc:
        _raise_api_error(exc)
    return _provider_read(provider, service=service)


@router.delete(
    "/providers/{providerId}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def delete_provider(
    providerId: str,
    service: ProviderService = Depends(get_provider_service),
    template_service: TemplateService = Depends(get_template_service),
) -> Response:
    try:
        service.delete_provider(providerId, trace_context=get_trace_context())
        _refresh_system_templates_after_provider_change(template_service)
    except ProviderServiceError as exc:
        _raise_api_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
