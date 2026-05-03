from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.api.routes.query import LogQueryRoute, get_control_session, get_log_session
from backend.app.observability.audit import AuditQueryServiceError, AuditService
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.observability import (
    AuditActorType,
    AuditLogQueryResponse,
    AuditResult,
)


router = APIRouter(tags=["query"], route_class=LogQueryRoute)


def get_audit_query_service(
    request: Request,
    control_session: Session = Depends(get_control_session),
    log_session: Session = Depends(get_log_session),
) -> Iterator[AuditService]:
    audit_writer = JsonlLogWriter(
        RuntimeDataSettings.from_environment_settings(
            request.app.state.environment_settings
        )
    )
    yield AuditService(
        log_session,
        control_session=control_session,
        audit_writer=audit_writer,
    )


@router.get(
    "/audit-logs",
    response_model=AuditLogQueryResponse,
    responses={
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_audit_logs(
    actor_type: AuditActorType | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    run_id: str | None = None,
    stage_run_id: str | None = None,
    correlation_id: str | None = None,
    result: AuditResult | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = None,
    limit: int | None = Query(default=None),
    service: AuditService = Depends(get_audit_query_service),
) -> AuditLogQueryResponse:
    try:
        return service.list_audit_logs(
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            correlation_id=correlation_id,
            result=result,
            since=since,
            until=until,
            cursor=cursor,
            limit=limit,
        )
    except AuditQueryServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
        ) from exc
