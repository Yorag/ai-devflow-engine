from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.api.routes.sessions import (
    get_control_session,
    get_event_session,
    get_graph_session,
    get_runtime_session,
)
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.tool_confirmation import (
    ToolConfirmationAllowRequest,
    ToolConfirmationCommandResponse,
    ToolConfirmationDenyRequest,
)
from backend.app.services.tool_confirmations import (
    ToolConfirmationService,
    ToolConfirmationServiceError,
)
from backend.app.services.graph_runtime import GraphCheckpointPort, GraphRuntimeCommandPort
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


router = APIRouter(tags=["tool-confirmations"])


def _tool_confirmation_runtime_orchestration_from_app_state(
    request: Request,
    graph_session: Session,
) -> RuntimeOrchestrationService:
    runtime_port = getattr(request.app.state, "h44a_runtime_port", None)
    if runtime_port is None:
        runtime_port = getattr(request.app.state, "h44_runtime_port", None)
    if runtime_port is None:
        runtime_port = getattr(request.app.state, "h41_runtime_port", None)
    if runtime_port is None:
        runtime_port = GraphRuntimeCommandPort(graph_session)
    checkpoint_port = getattr(request.app.state, "h41_checkpoint_port", None)
    if checkpoint_port is None:
        checkpoint_port = GraphCheckpointPort(graph_session)
    return RuntimeOrchestrationService(
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )


def get_tool_confirmation_service(
    request: Request,
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    event_session: Session = Depends(get_event_session),
    graph_session: Session = Depends(get_graph_session),
) -> Iterator[ToolConfirmationService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    log_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = getattr(
        request.app.state,
        "h44a_audit_service",
        getattr(
            request.app.state,
            "h44_tool_confirmation_audit_service",
            getattr(
                request.app.state,
                "h44_audit_service",
                AuditService(log_session, audit_writer=log_writer),
            ),
        ),
    )
    try:
        yield ToolConfirmationService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
            runtime_orchestration=_tool_confirmation_runtime_orchestration_from_app_state(
                request,
                graph_session,
            ),
            graph_session=graph_session,
            audit_service=audit_service,
            log_writer=log_writer,
        )
    finally:
        log_session.close()


@router.post(
    "/tool-confirmations/{toolConfirmationId}/allow",
    response_model=ToolConfirmationCommandResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def allow_tool_confirmation(
    toolConfirmationId: str,
    body: ToolConfirmationAllowRequest,
    service: ToolConfirmationService = Depends(get_tool_confirmation_service),
) -> ToolConfirmationCommandResponse:
    del body
    try:
        result = service.allow(
            tool_confirmation_id=toolConfirmationId,
            actor_id="session-user",
            trace_context=get_trace_context(),
        )
    except ToolConfirmationServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
            detail_ref=exc.detail_ref,
        ) from exc
    return ToolConfirmationCommandResponse(
        tool_confirmation=result.tool_confirmation,
    )


@router.post(
    "/tool-confirmations/{toolConfirmationId}/deny",
    response_model=ToolConfirmationCommandResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def deny_tool_confirmation(
    toolConfirmationId: str,
    body: ToolConfirmationDenyRequest,
    service: ToolConfirmationService = Depends(get_tool_confirmation_service),
) -> ToolConfirmationCommandResponse:
    try:
        result = service.deny(
            tool_confirmation_id=toolConfirmationId,
            reason=body.reason,
            actor_id="session-user",
            trace_context=get_trace_context(),
        )
    except ToolConfirmationServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
            detail_ref=exc.detail_ref,
        ) from exc
    return ToolConfirmationCommandResponse(
        tool_confirmation=result.tool_confirmation,
    )


__all__ = ["router"]
