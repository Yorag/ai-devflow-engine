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
from backend.app.schemas.configuration_package import (
    ConfigurationPackageExport,
    ConfigurationPackageImportRequest,
    ConfigurationPackageImportResult,
)
from backend.app.schemas.delivery_channel import (
    ProjectDeliveryChannelDetailProjection,
    ProjectDeliveryChannelUpdateRequest,
    ProjectDeliveryChannelValidationResult,
)
from backend.app.schemas.project import (
    ProjectCreateRequest,
    ProjectRead,
    ProjectRemoveResult,
)
from backend.app.services.delivery_channels import (
    DeliveryChannelService,
    DeliveryChannelServiceError,
)
from backend.app.services.projects import ProjectService, ProjectServiceError
from backend.app.services.configuration_packages import (
    ConfigurationPackageService,
    ConfigurationPackageServiceError,
)


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


def _delivery_channel_read(
    channel: Any,
    *,
    service: DeliveryChannelService,
) -> ProjectDeliveryChannelDetailProjection:
    return ProjectDeliveryChannelDetailProjection.model_validate(
        {
            "project_id": channel.project_id,
            "delivery_channel_id": channel.delivery_channel_id,
            "delivery_mode": channel.delivery_mode,
            "scm_provider_type": channel.scm_provider_type,
            "repository_identifier": channel.repository_identifier,
            "default_branch": channel.default_branch,
            "code_review_request_type": channel.code_review_request_type,
            "credential_ref": service.credential_ref_for_projection(
                channel.credential_ref,
            ),
            "credential_status": channel.credential_status,
            "readiness_status": channel.readiness_status,
            "readiness_message": channel.readiness_message,
            "last_validated_at": channel.last_validated_at,
            "updated_at": channel.updated_at,
        }
    )


def _delivery_channel_validation_read(
    validation: Any,
) -> ProjectDeliveryChannelValidationResult:
    return ProjectDeliveryChannelValidationResult.model_validate(
        {
            "readiness_status": validation.readiness_status,
            "readiness_message": validation.readiness_message,
            "credential_status": validation.credential_status,
            "validated_fields": list(validation.validated_fields),
            "validated_at": validation.validated_at,
        }
    )


def _raise_delivery_channel_api_error(exc: DeliveryChannelServiceError) -> None:
    raise ApiError(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
    ) from exc


def _raise_configuration_package_api_error(
    exc: ConfigurationPackageServiceError,
) -> None:
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


def get_runtime_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.RUNTIME)
    try:
        yield session
    finally:
        session.close()


def get_project_service(
    request: Request,
    session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
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
            runtime_session=runtime_session,
        )
    finally:
        log_session.close()


def get_delivery_channel_service(
    request: Request,
    session: Session = Depends(get_control_session),
) -> Iterator[DeliveryChannelService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield DeliveryChannelService(
            session,
            audit_service=audit_service,
            log_writer=audit_writer,
            credential_env_prefixes=settings.credential_env_prefixes,
        )
    finally:
        log_session.close()


def get_configuration_package_service(
    request: Request,
    session: Session = Depends(get_control_session),
) -> Iterator[ConfigurationPackageService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield ConfigurationPackageService(
            session,
            audit_service=audit_service,
            log_writer=audit_writer,
            credential_env_prefixes=settings.credential_env_prefixes,
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


@router.delete(
    "/projects/{projectId}",
    response_model=ProjectRemoveResult,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def delete_project(
    projectId: str,
    service: ProjectService = Depends(get_project_service),
) -> ProjectRemoveResult:
    try:
        return service.remove_project(
            project_id=projectId,
            trace_context=get_trace_context(),
        )
    except ProjectServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
        ) from exc


@router.get(
    "/projects/{projectId}/delivery-channel",
    response_model=ProjectDeliveryChannelDetailProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_project_delivery_channel(
    projectId: str,
    service: DeliveryChannelService = Depends(get_delivery_channel_service),
) -> ProjectDeliveryChannelDetailProjection:
    try:
        channel = service.get_project_channel(
            projectId,
            trace_context=get_trace_context(),
        )
    except DeliveryChannelServiceError as exc:
        _raise_delivery_channel_api_error(exc)
    return _delivery_channel_read(channel, service=service)


@router.put(
    "/projects/{projectId}/delivery-channel",
    response_model=ProjectDeliveryChannelDetailProjection,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def update_project_delivery_channel(
    projectId: str,
    body: ProjectDeliveryChannelUpdateRequest,
    service: DeliveryChannelService = Depends(get_delivery_channel_service),
) -> ProjectDeliveryChannelDetailProjection:
    try:
        channel = service.update_project_channel(
            projectId,
            body,
            trace_context=get_trace_context(),
        )
    except DeliveryChannelServiceError as exc:
        _raise_delivery_channel_api_error(exc)
    return _delivery_channel_read(channel, service=service)


@router.post(
    "/projects/{projectId}/delivery-channel/validate",
    response_model=ProjectDeliveryChannelValidationResult,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def validate_project_delivery_channel(
    projectId: str,
    service: DeliveryChannelService = Depends(get_delivery_channel_service),
) -> ProjectDeliveryChannelValidationResult:
    try:
        validation = service.validate_project_channel(
            projectId,
            trace_context=get_trace_context(),
        )
    except DeliveryChannelServiceError as exc:
        _raise_delivery_channel_api_error(exc)
    return _delivery_channel_validation_read(validation)


@router.get(
    "/projects/{projectId}/configuration-package/export",
    response_model=ConfigurationPackageExport,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def export_project_configuration_package(
    projectId: str,
    service: ConfigurationPackageService = Depends(get_configuration_package_service),
) -> ConfigurationPackageExport:
    try:
        return service.export_project_package(
            projectId,
            trace_context=get_trace_context(),
        )
    except ConfigurationPackageServiceError as exc:
        _raise_configuration_package_api_error(exc)


@router.post(
    "/projects/{projectId}/configuration-package/import",
    response_model=ConfigurationPackageImportResult,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def import_project_configuration_package(
    projectId: str,
    body: ConfigurationPackageImportRequest,
    service: ConfigurationPackageService = Depends(get_configuration_package_service),
) -> ConfigurationPackageImportResult:
    try:
        return service.import_project_package(
            projectId,
            body,
            trace_context=get_trace_context(),
        )
    except ConfigurationPackageServiceError as exc:
        _raise_configuration_package_api_error(exc)
