from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import StageType
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeCommandResult,
    RuntimeCommandType,
    RuntimeResumePayload,
)
from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import PipelineRunModel
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.run import RunCommandResponse, RunSummaryProjection
from backend.app.schemas.session import (
    SessionMessageAppendRequest,
    SessionMessageAppendResponse,
    SessionRead,
    SessionRenameRequest,
    SessionRerunRequest,
    SessionTemplateUpdateRequest,
)
from backend.app.services.clarifications import (
    ClarificationService,
    ClarificationServiceError,
)
from backend.app.services.runs import RunLifecycleService, RunLifecycleServiceError
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
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


def _raise_run_api_error(exc: RunLifecycleServiceError) -> None:
    raise ApiError(
        error_code=exc.error_code,
        message=str(exc),
        status_code=exc.status_code,
        detail_ref=exc.detail_ref,
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


def get_event_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.EVENT)
    try:
        yield session
    finally:
        session.close()


def get_graph_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.GRAPH)
    try:
        yield session
    finally:
        session.close()


def get_session_service(
    request: Request,
    session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    event_session: Session = Depends(get_event_session),
    graph_session: Session = Depends(get_graph_session),
) -> Iterator[SessionService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    log_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = getattr(
        request.app.state,
        "h43_audit_service",
        AuditService(log_session, audit_writer=log_writer),
    )
    try:
        yield SessionService(
            session,
            runtime_session=runtime_session,
            event_session=event_session,
            graph_session=graph_session,
            audit_service=audit_service,
            log_writer=log_writer,
            environment_settings=settings,
        )
    finally:
        log_session.close()


class InMemoryCheckpointPort:
    def save_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        purpose: CheckpointPurpose,
        trace_context,
        stage_run_id: str | None = None,
        stage_type: StageType | None = None,
        workspace_snapshot_ref: str | None = None,
        payload_ref: str | None = None,
    ) -> CheckpointRef:
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{purpose.value}-{thread.thread_id}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            purpose=purpose,
            workspace_snapshot_ref=workspace_snapshot_ref,
            payload_ref=payload_ref,
        )

    def load_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context,
    ) -> CheckpointRef:
        return checkpoint


class InMemoryRuntimeCommandPort:
    def create_interrupt(
        self,
        *,
        thread: GraphThreadRef,
        interrupt_type: GraphInterruptType,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        payload_ref: str,
        checkpoint: CheckpointRef,
        trace_context,
        clarification_id: str | None = None,
        approval_id: str | None = None,
        tool_confirmation_id: str | None = None,
        tool_action_ref: str | None = None,
    ) -> GraphInterruptRef:
        return GraphInterruptRef(
            interrupt_id=(
                f"interrupt-{clarification_id or approval_id or tool_confirmation_id}"
            ),
            thread=thread.model_copy(
                update={"status": _waiting_status(interrupt_type)}
            ),
            interrupt_type=interrupt_type,
            status=GraphInterruptStatus.PENDING,
            run_id=run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            payload_ref=payload_ref,
            clarification_id=clarification_id,
            approval_id=approval_id,
            tool_confirmation_id=tool_confirmation_id,
            tool_action_ref=tool_action_ref,
            checkpoint_ref=checkpoint,
        )

    def resume_interrupt(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_INTERRUPT,
            thread=interrupt.thread.model_copy(
                update={"status": GraphThreadStatus.RUNNING}
            ),
            interrupt_ref=interrupt.model_copy(
                update={"status": GraphInterruptStatus.RESUMED}
            ),
            payload_ref=resume_payload.payload_ref,
            trace_context=trace_context,
        )

    def resume_tool_confirmation(
        self,
        *,
        interrupt: GraphInterruptRef,
        resume_payload: RuntimeResumePayload,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_TOOL_CONFIRMATION,
            thread=interrupt.thread.model_copy(
                update={"status": GraphThreadStatus.RUNNING}
            ),
            interrupt_ref=interrupt.model_copy(
                update={"status": GraphInterruptStatus.RESUMED}
            ),
            payload_ref=resume_payload.payload_ref,
            trace_context=trace_context,
        )

    def pause_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.PAUSE_THREAD,
            thread=thread.model_copy(update={"status": GraphThreadStatus.PAUSED}),
            checkpoint_ref=checkpoint,
            trace_context=trace_context,
        )

    def resume_thread(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_THREAD,
            thread=thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            checkpoint_ref=checkpoint,
            trace_context=trace_context,
        )

    def terminate_thread(
        self,
        *,
        thread: GraphThreadRef,
        trace_context,
    ) -> RuntimeCommandResult:
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.TERMINATE_THREAD,
            thread=thread.model_copy(update={"status": GraphThreadStatus.TERMINATED}),
            trace_context=trace_context,
        )

    def assert_thread_terminal(
        self,
        *,
        thread: GraphThreadRef,
        trace_context,
    ) -> GraphThreadRef:
        return thread


def _waiting_status(interrupt_type: GraphInterruptType) -> GraphThreadStatus:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return GraphThreadStatus.WAITING_CLARIFICATION
    if interrupt_type is GraphInterruptType.APPROVAL:
        return GraphThreadStatus.WAITING_APPROVAL
    return GraphThreadStatus.WAITING_TOOL_CONFIRMATION


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


def get_clarification_service(
    request: Request,
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
    event_session: Session = Depends(get_event_session),
) -> Iterator[ClarificationService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield ClarificationService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
            audit_service=audit_service,
            runtime_orchestration=_runtime_orchestration_from_app_state(request),
        )
    finally:
        log_session.close()


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


def _run_summary(
    run: PipelineRunModel,
    *,
    current_stage_type: StageType | None,
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
            "current_stage_type": current_stage_type,
            "is_active": is_active,
        }
    )


def _run_command_response(
    session: SessionModel,
    run: PipelineRunModel,
) -> RunCommandResponse:
    return RunCommandResponse(
        session=_session_read(session),
        run=_run_summary(
            run,
            current_stage_type=session.latest_stage_type,
            is_active=session.current_run_id == run.run_id,
        ),
    )


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


@router.post(
    "/sessions/{sessionId}/messages",
    response_model=SessionMessageAppendResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def append_session_message(
    sessionId: str,
    body: SessionMessageAppendRequest,
    service: SessionService = Depends(get_session_service),
    clarification_service: ClarificationService = Depends(get_clarification_service),
) -> SessionMessageAppendResponse:
    trace_context = get_trace_context()
    try:
        if body.message_type == "clarification_reply":
            answer = service.append_clarification_reply(
                session_id=sessionId,
                content=body.content,
                clarification_service=clarification_service,
                trace_context=trace_context,
            )
            session = service.get_session(sessionId, trace_context=trace_context)
            if session is None:
                raise ApiError(ErrorCode.NOT_FOUND, "Session was not found.", 404)
            return SessionMessageAppendResponse(
                session=_session_read(session),
                message_item=answer.message_item,
            )
        started = service.start_run_from_new_requirement(
            session_id=sessionId,
            content=body.content,
            trace_context=trace_context,
        )
    except ClarificationServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
        ) from exc
    except SessionServiceError as exc:
        _raise_api_error(exc)
    return SessionMessageAppendResponse(
        session=_session_read(started.session),
        message_item=started.message_item,
    )


@router.post(
    "/sessions/{sessionId}/runs",
    response_model=RunCommandResponse,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/SessionRerunRequest"}
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
def create_session_rerun(
    sessionId: str,
    body: SessionRerunRequest | None = None,
    service: RunLifecycleService = Depends(get_run_lifecycle_service),
) -> RunCommandResponse:
    del body
    try:
        result = service.create_rerun(
            session_id=sessionId,
            actor_id="session-user",
            trace_context=get_trace_context(),
        )
    except RunLifecycleServiceError as exc:
        _raise_run_api_error(exc)
    return _run_command_response(result.session, result.run)
