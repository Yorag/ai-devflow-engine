from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.errors import ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.provider import ProviderRead
from backend.app.services.providers import ProviderService


router = APIRouter(tags=["providers"])


def _provider_read(provider: Any) -> ProviderRead:
    return ProviderRead.model_validate(
        {
            "provider_id": provider.provider_id,
            "display_name": provider.display_name,
            "provider_source": provider.provider_source,
            "protocol_type": provider.protocol_type,
            "base_url": provider.base_url,
            "api_key_ref": provider.api_key_ref,
            "default_model_id": provider.default_model_id,
            "supported_model_ids": provider.supported_model_ids,
            "runtime_capabilities": provider.runtime_capabilities,
            "created_at": provider.created_at,
            "updated_at": provider.updated_at,
        }
    )


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
    return [_provider_read(provider) for provider in providers]
