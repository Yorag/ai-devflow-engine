from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.api.routes.sessions import (
    InMemoryCheckpointPort,
    InMemoryRuntimeCommandPort,
    get_control_session,
    get_event_session,
    get_runtime_session,
)
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import PipelineRunModel, StageRunModel
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import RunStatus
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.run import (
    RunCommandResponse,
    RunPauseRequest,
    RunResumeRequest,
    RunSummaryProjection,
)
from backend.app.schemas.session import SessionRead
from backend.app.services.runs import RunLifecycleService, RunLifecycleServiceError
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


router = APIRouter(tags=["runs"])


def _runtime_orchestration_from_app_state(
    request: Request,
) -> RuntimeOrchestrationService:
    runtime_port = getattr(request.app.state, "h45_runtime_port", None)
    if runtime_port is None:
        runtime_port = getattr(request.app.state, "h41_runtime_port", None)
    if runtime_port is None:
        runtime_port = InMemoryRuntimeCommandPort()
    checkpoint_port = getattr(request.app.state, "h45_checkpoint_port", None)
    if checkpoint_port is None:
        checkpoint_port = getattr(request.app.state, "h41_checkpoint_port", None)
    if checkpoint_port is None:
        checkpoint_port = InMemoryCheckpointPort()
    return RuntimeOrchestrationService(
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )


def get_run_lifecycle_service(
    request: Request,
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    event_session: Session = Depends(get_event_session),
) -> Iterator[RunLifecycleService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    log_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = getattr(
        request.app.state,
        "h45_audit_service",
        AuditService(log_session, audit_writer=log_writer),
    )
    try:
        yield RunLifecycleService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
            runtime_orchestration=_runtime_orchestration_from_app_state(request),
            audit_service=audit_service,
            log_writer=log_writer,
        )
    finally:
        log_session.close()


def _session_read(session: SessionModel) -> SessionRead:
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


def _run_summary(
    run: PipelineRunModel,
    stage: StageRunModel | None,
    *,
    is_active: bool,
) -> RunSummaryProjection:
    return RunSummaryProjection.model_validate(
        {
            "run_id": run.run_id,
            "attempt_index": run.attempt_index,
            "status": run.status,
            "trigger_source": run.trigger_source,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "current_stage_type": stage.stage_type if stage is not None else None,
            "is_active": is_active,
        }
    )


def _command_response(
    result,
) -> RunCommandResponse:
    terminal = result.run.status in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.TERMINATED,
    }
    return RunCommandResponse(
        session=_session_read(result.session),
        run=_run_summary(
            result.run,
            result.stage,
            is_active=(
                result.session.current_run_id == result.run.run_id and not terminal
            ),
        ),
    )


def _raise_api_error(exc: RunLifecycleServiceError) -> None:
    raise ApiError(
        error_code=exc.error_code,
        message=str(exc),
        status_code=exc.status_code,
        detail_ref=exc.detail_ref,
    ) from exc


@router.post(
    "/runs/{runId}/pause",
    response_model=RunCommandResponse,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/RunPauseRequest"}
                }
            },
            "required": False,
        }
    },
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def pause_run(
    runId: str,
    body: Annotated[RunPauseRequest | None, Body()] = None,
    service: RunLifecycleService = Depends(get_run_lifecycle_service),
) -> RunCommandResponse:
    del body
    try:
        result = service.pause_run(
            run_id=runId,
            actor_id="session-user",
            trace_context=get_trace_context(),
        )
    except RunLifecycleServiceError as exc:
        _raise_api_error(exc)
    return _command_response(result)


@router.post(
    "/runs/{runId}/resume",
    response_model=RunCommandResponse,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/RunResumeRequest"}
                }
            },
            "required": False,
        }
    },
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def resume_run(
    runId: str,
    body: Annotated[RunResumeRequest | None, Body()] = None,
    service: RunLifecycleService = Depends(get_run_lifecycle_service),
) -> RunCommandResponse:
    del body
    try:
        result = service.resume_run(
            run_id=runId,
            actor_id="session-user",
            trace_context=get_trace_context(),
        )
    except RunLifecycleServiceError as exc:
        _raise_api_error(exc)
    return _command_response(result)


__all__ = ["router"]
