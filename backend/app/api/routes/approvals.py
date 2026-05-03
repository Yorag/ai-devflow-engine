from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.api.routes.sessions import (
    _runtime_orchestration_from_app_state,
    get_control_session,
    get_event_session,
    get_runtime_session,
)
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.services.delivery_channels import DeliveryChannelService
from backend.app.services.delivery_snapshots import DeliverySnapshotService
from backend.app.schemas.approval import (
    ApprovalApproveRequest,
    ApprovalCommandResponse,
    ApprovalRejectRequest,
)
from backend.app.services.approvals import ApprovalService, ApprovalServiceError


router = APIRouter(tags=["approvals"])


class _NullDeliverySnapshotService:
    def prepare_delivery_snapshot(self, **kwargs):
        return None


def get_approval_service(
    request: Request,
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    event_session: Session = Depends(get_event_session),
) -> Iterator[ApprovalService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = getattr(
        request.app.state,
        "h44_audit_service",
        AuditService(log_session, audit_writer=audit_writer),
    )
    delivery_snapshot_service = getattr(
        request.app.state,
        "h44_delivery_snapshot_service",
        DeliverySnapshotService(
            control_session=control_session,
            runtime_session=runtime_session,
            delivery_channel_service=DeliveryChannelService(
                control_session,
                audit_service=audit_service,
                log_writer=audit_writer,
                credential_env_prefixes=settings.credential_env_prefixes,
            ),
            audit_service=audit_service,
            log_writer=JsonlLogWriter(
                RuntimeDataSettings.from_environment_settings(settings)
            ),
            auto_commit=False,
        ),
    )
    try:
        yield ApprovalService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
            runtime_orchestration=_runtime_orchestration_from_app_state(request),
            audit_service=audit_service,
            delivery_snapshot_service=delivery_snapshot_service,
            log_writer=JsonlLogWriter(
                RuntimeDataSettings.from_environment_settings(settings)
            ),
        )
    finally:
        log_session.close()


@router.post(
    "/approvals/{approvalId}/approve",
    response_model=ApprovalCommandResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def approve_approval(
    approvalId: str,
    body: ApprovalApproveRequest,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalCommandResponse:
    del body
    try:
        result = service.approve(
            approval_id=approvalId,
            actor_id="session-user",
            trace_context=get_trace_context(),
        )
    except ApprovalServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
            detail_ref=exc.detail_ref,
        ) from exc
    return ApprovalCommandResponse(
        approval_result=result.approval_result,
        control_item=result.control_item,
    )


@router.post(
    "/approvals/{approvalId}/reject",
    response_model=ApprovalCommandResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def reject_approval(
    approvalId: str,
    body: ApprovalRejectRequest,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalCommandResponse:
    try:
        result = service.reject(
            approval_id=approvalId,
            reason=body.reason,
            actor_id="session-user",
            trace_context=get_trace_context(),
        )
    except ApprovalServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
            detail_ref=exc.detail_ref,
        ) from exc
    return ApprovalCommandResponse(
        approval_result=result.approval_result,
        control_item=result.control_item,
    )


__all__ = ["router"]
