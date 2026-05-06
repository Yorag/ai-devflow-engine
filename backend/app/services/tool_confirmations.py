from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import (
    PipelineRunModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    RunStatus,
    SessionStatus,
    StageStatus,
    ToolConfirmationStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.feed import ToolConfirmationFeedEntry
from backend.app.schemas.observability import AuditActorType, AuditResult, LogCategory, LogLevel
from backend.app.services.control_records import ControlRecordService
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.graph_interrupt_refs import build_persisted_graph_interrupt_ref
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


_LOGGER = logging.getLogger(__name__)

TOOL_CONFIRMATION_TARGET_NOT_FOUND_MESSAGE = "Tool confirmation target was not found."
TOOL_CONFIRMATION_NOT_ACTIONABLE_MESSAGE = "Tool confirmation is not actionable."
TOOL_CONFIRMATION_PAUSED_MESSAGE = (
    "Current run is paused; resume it to continue tool confirmation."
)
TOOL_CONFIRMATION_COMMAND_FAILED_MESSAGE = "tool confirmation command failed."
TOOL_CONFIRMATION_DENY_SOURCE_VALUES = frozenset(
    {
        "continue_current_stage",
        "run_failed",
        "awaiting_run_control",
    }
)


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


@dataclass(frozen=True)
class ToolConfirmationCreationResult:
    tool_confirmation_id: str
    graph_interrupt_ref: str
    tool_confirmation: ToolConfirmationFeedEntry


@dataclass(frozen=True)
class ToolConfirmationCommandResult:
    tool_confirmation: ToolConfirmationFeedEntry


@dataclass(frozen=True)
class ToolConfirmationCancellationResult:
    cancelled_confirmations: list[ToolConfirmationFeedEntry]


class ToolConfirmationServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
        *,
        detail_ref: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.detail_ref = detail_ref
        super().__init__(message)


class ToolConfirmationService:
    def __init__(
        self,
        *,
        control_session: Session,
        runtime_session: Session,
        event_session: Session,
        runtime_orchestration: RuntimeOrchestrationService,
        graph_session: Session | None = None,
        audit_service: Any | None = None,
        log_writer: RunLogWriter,
        redaction_policy: RedactionPolicy | None = None,
        control_record_service: ControlRecordService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._graph_session = graph_session
        self._runtime_orchestration = runtime_orchestration
        self._audit_service = audit_service or _NoopAuditService()
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))
        self._events = EventStore(event_session, now=self._now)
        self._control_records = control_record_service or ControlRecordService(
            runtime_session=runtime_session,
            event_session=event_session,
            now=self._now,
        )

    def create_request(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        confirmation_object_ref: str,
        tool_name: str,
        command_preview: str | None,
        target_summary: str,
        risk_level: ToolRiskLevel,
        risk_categories: list[ToolRiskCategory],
        reason: str,
        expected_side_effects: list[str],
        alternative_path_summary: str | None,
        planned_deny_followup_action: str | None = None,
        planned_deny_followup_summary: str | None = None,
        trace_context: TraceContext,
    ) -> ToolConfirmationCreationResult:
        timestamp = self._now()
        tool_confirmation_id = f"tool-confirmation-{uuid4().hex}"
        try:
            control_session, run, stage = self._load_and_validate_target(
                session_id=session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
            )
            self._assert_running_target(
                control_session=control_session,
                run=run,
                stage=stage,
            )
            request_trace = self._trace(
                trace_context,
                span_id=f"tool-confirmation-create-{tool_confirmation_id}",
                session_id=session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                tool_confirmation_id=tool_confirmation_id,
                graph_thread_id=run.graph_thread_ref,
            )
            interrupt = self._runtime_orchestration.create_tool_confirmation_interrupt(
                thread=GraphThreadRef(
                    thread_id=run.graph_thread_ref,
                    run_id=run.run_id,
                    status=GraphThreadStatus.RUNNING,
                    current_stage_run_id=stage.stage_run_id,
                    current_stage_type=stage.stage_type,
                ),
                run_id=run.run_id,
                stage_run_id=stage.stage_run_id,
                stage_type=stage.stage_type,
                tool_confirmation_id=tool_confirmation_id,
                tool_action_ref=confirmation_object_ref,
                trace_context=request_trace,
            )
            request = ToolConfirmationRequestModel(
                tool_confirmation_id=tool_confirmation_id,
                run_id=run.run_id,
                stage_run_id=stage.stage_run_id,
                confirmation_object_ref=confirmation_object_ref,
                tool_name=tool_name,
                command_preview=command_preview,
                target_summary=target_summary,
                risk_level=risk_level,
                risk_categories=[category.value for category in risk_categories],
                reason=reason,
                expected_side_effects=expected_side_effects,
                alternative_path_summary=alternative_path_summary,
                planned_deny_followup_action=planned_deny_followup_action,
                planned_deny_followup_summary=planned_deny_followup_summary,
                deny_followup_action=None,
                deny_followup_summary=None,
                user_decision=None,
                status=ToolConfirmationStatus.PENDING,
                graph_interrupt_ref=interrupt.interrupt_id,
                audit_log_ref=None,
                process_ref=None,
                requested_at=timestamp,
                responded_at=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._runtime_session.add(request)
            self._mark_waiting_tool_confirmation(
                control_session=control_session,
                run=run,
                stage=stage,
                timestamp=timestamp,
            )
            self._control_records.append_tool_confirmation_control_record(
                run_id=run.run_id,
                stage_run_id=stage.stage_run_id,
                source_stage_type=stage.stage_type,
                payload_ref=tool_confirmation_id,
                graph_interrupt_ref=interrupt.interrupt_id,
                occurred_at=timestamp,
            )
            projection = self.build_tool_confirmation_projection(
                request=request,
                run=run,
                occurred_at=timestamp,
            )
            self._events.append(
                DomainEventType.TOOL_CONFIRMATION_REQUESTED,
                payload={"tool_confirmation": projection.model_dump(mode="json")},
                trace_context=request_trace,
            )
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.SYSTEM,
                actor_id="runtime",
                action="tool_confirmation.request",
                target_type="tool_confirmation_request",
                target_id=tool_confirmation_id,
                result=AuditResult.ACCEPTED,
                reason=reason,
                metadata={
                    "tool_confirmation_id": tool_confirmation_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "tool_name": tool_name,
                    "risk_level": risk_level.value,
                    "result_status": "created",
                },
                trace_context=request_trace,
                rollback=self._rollback_sessions,
                created_at=timestamp,
            )
            self._record_run_log(
                payload_type="tool_confirmation_request_created",
                message="Tool confirmation request created.",
                metadata={
                    "tool_confirmation_id": tool_confirmation_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "tool_name": tool_name,
                    "result_status": "created",
                },
                trace_context=request_trace,
                created_at=timestamp,
                level=LogLevel.INFO,
            )
            self._commit_all()
            return ToolConfirmationCreationResult(
                tool_confirmation_id=tool_confirmation_id,
                graph_interrupt_ref=interrupt.interrupt_id,
                tool_confirmation=projection,
            )
        except ToolConfirmationServiceError:
            raise
        except Exception:
            self._rollback_sessions()
            raise

    def allow(
        self,
        *,
        tool_confirmation_id: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> ToolConfirmationCommandResult:
        return self._execute_command(
            tool_confirmation_id=tool_confirmation_id,
            actor_id=actor_id,
            trace_context=trace_context,
            decision=ToolConfirmationStatus.ALLOWED,
        )

    def deny(
        self,
        *,
        tool_confirmation_id: str,
        reason: str | None = None,
        actor_id: str,
        trace_context: TraceContext,
    ) -> ToolConfirmationCommandResult:
        return self._execute_command(
            tool_confirmation_id=tool_confirmation_id,
            actor_id=actor_id,
            trace_context=trace_context,
            decision=ToolConfirmationStatus.DENIED,
            reason=reason,
        )

    def cancel_for_terminal_run(
        self,
        *,
        run_id: str,
        trace_context: TraceContext,
        commit: bool = True,
    ) -> ToolConfirmationCancellationResult:
        timestamp = self._now()
        requests = (
            self._runtime_session.query(ToolConfirmationRequestModel)
            .filter(
                ToolConfirmationRequestModel.run_id == run_id,
                ToolConfirmationRequestModel.status == ToolConfirmationStatus.PENDING,
            )
            .all()
        )
        if not requests:
            return ToolConfirmationCancellationResult(cancelled_confirmations=[])

        run = self._runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise ToolConfirmationServiceError(
                ErrorCode.NOT_FOUND,
                TOOL_CONFIRMATION_TARGET_NOT_FOUND_MESSAGE,
                404,
            )

        try:
            cancelled_confirmations: list[ToolConfirmationFeedEntry] = []
            for request in requests:
                request.status = ToolConfirmationStatus.CANCELLED
                request.user_decision = None
                request.responded_at = timestamp
                request.updated_at = timestamp
                cancel_trace = trace_context.child_span(
                    span_id=f"tool-confirmation-cancel-{request.tool_confirmation_id}",
                    created_at=timestamp,
                    run_id=run.run_id,
                    stage_run_id=request.stage_run_id,
                    tool_confirmation_id=request.tool_confirmation_id,
                    graph_thread_id=run.graph_thread_ref,
                )
                self._audit_service.require_audit_record(
                    actor_type=AuditActorType.SYSTEM,
                    actor_id="runtime",
                    action="tool_confirmation.cancel",
                    target_type="tool_confirmation_request",
                    target_id=request.tool_confirmation_id,
                    result=AuditResult.ACCEPTED,
                    reason="Terminal run cancelled pending tool confirmation.",
                    metadata={
                        "tool_confirmation_id": request.tool_confirmation_id,
                        "run_id": run.run_id,
                        "stage_run_id": request.stage_run_id,
                        "tool_name": request.tool_name,
                        "result_status": "cancelled",
                    },
                    trace_context=cancel_trace,
                    rollback=self._rollback_sessions,
                    created_at=timestamp,
                )
                self._record_run_log(
                    payload_type="tool_confirmation_cancelled",
                    message="Tool confirmation cancelled for terminal run.",
                    metadata={
                        "tool_confirmation_id": request.tool_confirmation_id,
                        "run_id": run.run_id,
                        "stage_run_id": request.stage_run_id,
                        "tool_name": request.tool_name,
                        "result_status": "cancelled",
                    },
                    trace_context=cancel_trace,
                    created_at=timestamp,
                    level=LogLevel.INFO,
                )
                cancelled_confirmations.append(
                    self.build_tool_confirmation_projection(
                        request=request,
                        run=run,
                        occurred_at=timestamp,
                    )
                )
            if commit:
                self._runtime_session.commit()
            return ToolConfirmationCancellationResult(
                cancelled_confirmations=cancelled_confirmations
            )
        except Exception:
            if commit:
                self._rollback_sessions()
            raise

    def build_tool_confirmation_projection(
        self,
        *,
        request: ToolConfirmationRequestModel,
        run: PipelineRunModel,
        occurred_at: datetime | None = None,
    ) -> ToolConfirmationFeedEntry:
        timestamp = occurred_at or self._now()
        is_actionable, disabled_reason = self._actionable_state(
            request=request,
            run=run,
        )
        return ToolConfirmationFeedEntry(
            entry_id=f"entry-{request.tool_confirmation_id}",
            run_id=request.run_id,
            occurred_at=timestamp,
            stage_run_id=request.stage_run_id,
            tool_confirmation_id=request.tool_confirmation_id,
            status=request.status,
            title=f"Confirm {request.tool_name} tool action",
            tool_name=request.tool_name,
            command_preview=request.command_preview,
            target_summary=request.target_summary,
            risk_level=request.risk_level,
            risk_categories=[
                ToolRiskCategory(category) for category in request.risk_categories
            ],
            reason=request.reason,
            expected_side_effects=list(request.expected_side_effects),
            allow_action=f"allow:{request.tool_confirmation_id}",
            deny_action=f"deny:{request.tool_confirmation_id}",
            is_actionable=is_actionable,
            requested_at=request.requested_at,
            responded_at=request.responded_at,
            decision=(
                request.user_decision
                if request.user_decision
                in {
                    ToolConfirmationStatus.ALLOWED,
                    ToolConfirmationStatus.DENIED,
                }
                else None
            ),
            deny_followup_action=(
                request.deny_followup_action
                if request.user_decision is ToolConfirmationStatus.DENIED
                else None
            ),
            deny_followup_summary=(
                request.deny_followup_summary
                if request.user_decision is ToolConfirmationStatus.DENIED
                else None
            ),
            disabled_reason=disabled_reason,
        )

    def _execute_command(
        self,
        *,
        tool_confirmation_id: str,
        actor_id: str,
        trace_context: TraceContext,
        decision: ToolConfirmationStatus,
        reason: str | None = None,
    ) -> ToolConfirmationCommandResult:
        started_at = self._now()
        request = self._runtime_session.get(
            ToolConfirmationRequestModel,
            tool_confirmation_id,
        )
        if request is None:
            raise ToolConfirmationServiceError(
                ErrorCode.NOT_FOUND,
                TOOL_CONFIRMATION_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        run = self._runtime_session.get(PipelineRunModel, request.run_id)
        stage = self._runtime_session.get(StageRunModel, request.stage_run_id)
        control_session = self._load_visible_session(
            run.session_id if run is not None else ""
        )
        if run is None or stage is None or control_session is None:
            raise ToolConfirmationServiceError(
                ErrorCode.NOT_FOUND,
                TOOL_CONFIRMATION_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        command_trace = self._trace(
            trace_context,
            span_id=f"tool-confirmation-{decision.value}-{tool_confirmation_id}",
            session_id=control_session.session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            tool_confirmation_id=tool_confirmation_id,
            graph_thread_id=run.graph_thread_ref,
        )
        try:
            self._assert_command_target_consistency(
                request=request,
                control_session=control_session,
                run=run,
                stage=stage,
            )
            self._assert_actionable(
                request=request,
                control_session=control_session,
                run=run,
                stage=stage,
            )
        except ToolConfirmationServiceError as exc:
            if exc.error_code is ErrorCode.TOOL_CONFIRMATION_NOT_ACTIONABLE:
                self._record_rejected_command(
                    request=request,
                    run=run,
                    stage=stage,
                    actor_id=actor_id,
                    trace_context=command_trace,
                    action=self._command_action(decision, rejected=True),
                    reason=exc.message,
                    started_at=started_at,
                )
            raise

        timestamp = started_at
        try:
            deny_followup_action, deny_followup_summary = (
                self._resolve_deny_followup_source(
                    request=request,
                    decision=decision,
                )
            )
            request.status = decision
            request.user_decision = decision
            request.responded_at = timestamp
            request.updated_at = timestamp
            request.deny_followup_action = deny_followup_action
            request.deny_followup_summary = deny_followup_summary
            self._mark_running_after_command(
                control_session=control_session,
                run=run,
                stage=stage,
                timestamp=timestamp,
            )
            projection = self.build_tool_confirmation_projection(
                request=request,
                run=run,
                occurred_at=timestamp,
            )
            self._events.append(
                (
                    DomainEventType.TOOL_CONFIRMATION_ALLOWED
                    if decision is ToolConfirmationStatus.ALLOWED
                    else DomainEventType.TOOL_CONFIRMATION_DENIED
                ),
                payload={"tool_confirmation": projection.model_dump(mode="json")},
                trace_context=command_trace,
            )
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action=self._command_action(decision),
                target_type="tool_confirmation_request",
                target_id=tool_confirmation_id,
                result=AuditResult.ACCEPTED,
                reason=reason,
                metadata={
                    "tool_confirmation_id": tool_confirmation_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "tool_name": request.tool_name,
                    "decision": decision.value,
                    "reason": reason,
                    "deny_followup_action": deny_followup_action,
                    "deny_followup_summary": deny_followup_summary,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                rollback=self._rollback_sessions,
                created_at=timestamp,
            )
            self._record_run_log(
                payload_type="tool_confirmation_command_accepted",
                message="Tool confirmation command accepted.",
                metadata={
                    "tool_confirmation_id": tool_confirmation_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "decision": decision.value,
                    "reason": reason,
                    "deny_followup_action": deny_followup_action,
                    "deny_followup_summary": deny_followup_summary,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=timestamp,
                level=LogLevel.INFO,
                duration_ms=self._duration_ms(started_at, timestamp),
            )
            self._runtime_orchestration.resume_tool_confirmation(
                interrupt=self._build_interrupt(request=request, run=run, stage=stage),
                resume_payload=RuntimeResumePayload(
                    resume_id=f"resume-{tool_confirmation_id}",
                    payload_ref=tool_confirmation_id,
                    values={
                        "decision": decision.value,
                        "tool_confirmation_id": tool_confirmation_id,
                        "confirmation_object_ref": request.confirmation_object_ref,
                        **(
                            {
                                "deny_followup_action": deny_followup_action,
                                "deny_followup_summary": deny_followup_summary,
                            }
                            if decision is ToolConfirmationStatus.DENIED
                            else {}
                        ),
                        **({"reason": reason} if reason is not None else {}),
                    },
                ),
                trace_context=command_trace,
            )
            self._commit_all()
            return ToolConfirmationCommandResult(tool_confirmation=projection)
        except Exception as exc:
            self._rollback_sessions()
            self._record_failed_command(
                request=request,
                run=run,
                stage=stage,
                actor_id=actor_id,
                trace_context=command_trace,
                action=self._command_action(decision, failed=True),
                reason=str(exc),
                started_at=started_at,
            )
            raise ToolConfirmationServiceError(
                ErrorCode.INTERNAL_ERROR,
                TOOL_CONFIRMATION_COMMAND_FAILED_MESSAGE,
                500,
                detail_ref=tool_confirmation_id,
            ) from exc

    def _load_and_validate_target(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
    ) -> tuple[SessionModel, PipelineRunModel, StageRunModel]:
        control_session = self._control_session.get(SessionModel, session_id)
        run = self._runtime_session.get(PipelineRunModel, run_id)
        stage = self._runtime_session.get(StageRunModel, stage_run_id)
        if control_session is None or run is None or stage is None:
            raise ToolConfirmationServiceError(
                ErrorCode.NOT_FOUND,
                TOOL_CONFIRMATION_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        if not control_session.is_visible:
            raise ToolConfirmationServiceError(
                ErrorCode.NOT_FOUND,
                TOOL_CONFIRMATION_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        if control_session.current_run_id != run.run_id:
            self._raise_validation_conflict("Session current_run_id does not match run.")
        if run.session_id != control_session.session_id:
            self._raise_validation_conflict("Run does not belong to the Session.")
        if run.current_stage_run_id != stage.stage_run_id:
            self._raise_validation_conflict(
                "PipelineRun current_stage_run_id does not match stage."
            )
        if stage.run_id != run.run_id:
            self._raise_validation_conflict("StageRun does not belong to the run.")
        return control_session, run, stage

    def _load_visible_session(self, session_id: str) -> SessionModel | None:
        return (
            self._control_session.query(SessionModel)
            .filter(
                SessionModel.session_id == session_id,
                SessionModel.is_visible.is_(True),
            )
            .one_or_none()
        )

    def _assert_running_target(
        self,
        *,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        if (
            control_session.status is not SessionStatus.RUNNING
            or run.status is not RunStatus.RUNNING
            or stage.status is not StageStatus.RUNNING
        ):
            self._raise_validation_conflict(
                "Tool confirmation target Session, run, and stage must be running."
            )

    def _assert_command_target_consistency(
        self,
        *,
        request: ToolConfirmationRequestModel,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        if control_session.current_run_id != run.run_id:
            self._raise_validation_conflict("Session current_run_id does not match run.")
        if run.session_id != control_session.session_id:
            self._raise_validation_conflict("Run does not belong to the Session.")
        if run.current_stage_run_id != stage.stage_run_id:
            self._raise_validation_conflict(
                "PipelineRun current_stage_run_id does not match stage."
            )
        if stage.run_id != run.run_id:
            self._raise_validation_conflict("StageRun does not belong to the run.")
        if request.run_id != run.run_id:
            self._raise_validation_conflict(
                "ToolConfirmationRequest does not belong to the run."
            )
        if request.stage_run_id != stage.stage_run_id:
            self._raise_validation_conflict(
                "ToolConfirmationRequest does not belong to the stage."
            )

    def _assert_actionable(
        self,
        *,
        request: ToolConfirmationRequestModel,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        if request.status is not ToolConfirmationStatus.PENDING:
            self._raise_not_actionable("Tool confirmation is no longer pending.")
        if request.user_decision is not None or request.responded_at is not None:
            self._raise_not_actionable("Tool confirmation is already resolved.")
        if (
            control_session.status is SessionStatus.PAUSED
            or run.status is RunStatus.PAUSED
        ):
            self._raise_not_actionable(TOOL_CONFIRMATION_PAUSED_MESSAGE)
        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TERMINATED}:
            self._raise_not_actionable("Run is terminal.")
        if stage.status in {StageStatus.COMPLETED, StageStatus.FAILED, StageStatus.TERMINATED}:
            self._raise_not_actionable("Stage is terminal.")
        if (
            control_session.status is not SessionStatus.WAITING_TOOL_CONFIRMATION
            or run.status is not RunStatus.WAITING_TOOL_CONFIRMATION
            or stage.status is not StageStatus.WAITING_TOOL_CONFIRMATION
        ):
            self._raise_not_actionable(
                "Current run is not waiting for tool confirmation."
            )

    def _mark_waiting_tool_confirmation(
        self,
        *,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        timestamp: datetime,
    ) -> None:
        control_session.status = SessionStatus.WAITING_TOOL_CONFIRMATION
        control_session.latest_stage_type = stage.stage_type
        control_session.updated_at = timestamp
        run.status = RunStatus.WAITING_TOOL_CONFIRMATION
        run.updated_at = timestamp
        stage.status = StageStatus.WAITING_TOOL_CONFIRMATION
        stage.updated_at = timestamp

    def _mark_running_after_command(
        self,
        *,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        timestamp: datetime,
    ) -> None:
        control_session.status = SessionStatus.RUNNING
        control_session.updated_at = timestamp
        run.status = RunStatus.RUNNING
        run.updated_at = timestamp
        stage.status = StageStatus.RUNNING
        stage.updated_at = timestamp

    def _build_interrupt(
        self,
        *,
        request: ToolConfirmationRequestModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> GraphInterruptRef:
        if self._graph_session is None:
            raise RuntimeError("Tool confirmation resume requires graph_session.")
        return build_persisted_graph_interrupt_ref(
            graph_session=self._graph_session,
            run=run,
            stage=stage,
            interrupt_id=request.graph_interrupt_ref,
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            payload_ref=request.tool_confirmation_id,
            checkpoint_purpose=CheckpointPurpose.WAITING_TOOL_CONFIRMATION,
            thread_status=GraphThreadStatus.WAITING_TOOL_CONFIRMATION,
            tool_confirmation_id=request.tool_confirmation_id,
            tool_action_ref=request.confirmation_object_ref,
        )

    @staticmethod
    def _actionable_state(
        *,
        request: ToolConfirmationRequestModel,
        run: PipelineRunModel,
    ) -> tuple[bool, str | None]:
        if request.status is not ToolConfirmationStatus.PENDING:
            return False, "Tool confirmation is no longer pending."
        if run.status is RunStatus.WAITING_TOOL_CONFIRMATION:
            return True, None
        if run.status is RunStatus.PAUSED:
            return False, TOOL_CONFIRMATION_PAUSED_MESSAGE
        return False, "Current run is not waiting for tool confirmation."

    @staticmethod
    def _resolve_deny_followup_source(
        *,
        request: ToolConfirmationRequestModel,
        decision: ToolConfirmationStatus,
    ) -> tuple[str | None, str | None]:
        if decision is not ToolConfirmationStatus.DENIED:
            return None, None
        action = request.planned_deny_followup_action
        summary = request.planned_deny_followup_summary
        if action is None or summary is None:
            raise RuntimeError("deny follow-up source is missing")
        normalized_action = action.strip()
        normalized_summary = summary.strip()
        if not normalized_action or not normalized_summary:
            raise RuntimeError("deny follow-up source is missing")
        if normalized_action not in TOOL_CONFIRMATION_DENY_SOURCE_VALUES:
            raise RuntimeError("deny follow-up action is invalid")
        return normalized_action, normalized_summary

    def _record_failed_command(
        self,
        *,
        request: ToolConfirmationRequestModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        actor_id: str,
        trace_context: TraceContext,
        action: str,
        reason: str,
        started_at: datetime | None = None,
    ) -> None:
        recorded_at = self._now()
        try:
            self._audit_service.record_failed_command(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action=action,
                target_type="tool_confirmation_request",
                target_id=request.tool_confirmation_id,
                reason=reason,
                metadata={
                    "tool_confirmation_id": request.tool_confirmation_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "tool_name": request.tool_name,
                    "result_status": "failed",
                },
                trace_context=trace_context,
                created_at=recorded_at,
            )
        except Exception:
            pass
        try:
            self._record_run_log(
                payload_type="tool_confirmation_command_failed",
                message="Tool confirmation command failed.",
                metadata={
                    "tool_confirmation_id": request.tool_confirmation_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "tool_name": request.tool_name,
                    "reason": reason,
                    "result_status": "failed",
                },
                trace_context=trace_context,
                created_at=recorded_at,
                level=LogLevel.ERROR,
                error_code=ErrorCode.INTERNAL_ERROR.value,
                duration_ms=self._duration_ms(started_at, recorded_at),
            )
        except Exception:
            pass

    def _record_rejected_command(
        self,
        *,
        request: ToolConfirmationRequestModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        actor_id: str,
        trace_context: TraceContext,
        action: str,
        reason: str,
        started_at: datetime | None = None,
    ) -> None:
        recorded_at = self._now()
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            action=action,
            target_type="tool_confirmation_request",
            target_id=request.tool_confirmation_id,
            reason=reason,
            metadata={
                "tool_confirmation_id": request.tool_confirmation_id,
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id,
                "tool_name": request.tool_name,
                "result_status": "rejected",
                "rejected_reason": reason,
            },
            trace_context=trace_context,
            created_at=recorded_at,
        )
        self._record_run_log(
            payload_type="tool_confirmation_command_rejected",
            message="Tool confirmation command rejected.",
            metadata={
                "tool_confirmation_id": request.tool_confirmation_id,
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id,
                "tool_name": request.tool_name,
                "reason": reason,
                "result_status": "rejected",
            },
            trace_context=trace_context,
            created_at=recorded_at,
            level=LogLevel.WARNING,
            error_code=ErrorCode.TOOL_CONFIRMATION_NOT_ACTIONABLE.value,
            duration_ms=self._duration_ms(started_at, recorded_at),
        )

    def _record_run_log(
        self,
        *,
        payload_type: str,
        message: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
        level: LogLevel,
        error_code: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        redacted_payload = self._redaction_policy.summarize_payload(
            metadata,
            payload_type=payload_type,
        )
        try:
            self._log_writer.write_run_log(
                LogRecordInput(
                    source="services.tool_confirmations",
                    category=LogCategory.RUNTIME,
                    level=level,
                    message=message,
                    trace_context=trace_context,
                    payload=LogPayloadSummary.from_redacted_payload(
                        payload_type,
                        redacted_payload,
                    ),
                    created_at=created_at,
                    duration_ms=duration_ms,
                    error_code=error_code,
                )
            )
        except Exception:
            _LOGGER.exception(
                "Tool confirmation run log write failed for tool_confirmation_id=%s",
                trace_context.tool_confirmation_id,
            )

    def _trace(
        self,
        trace_context: TraceContext,
        *,
        span_id: str,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        tool_confirmation_id: str,
        graph_thread_id: str,
    ) -> TraceContext:
        return trace_context.child_span(
            span_id=span_id,
            created_at=self._now(),
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            tool_confirmation_id=tool_confirmation_id,
            graph_thread_id=graph_thread_id,
        )

    @staticmethod
    def _command_action(
        decision: ToolConfirmationStatus,
        *,
        rejected: bool = False,
        failed: bool = False,
    ) -> str:
        base = (
            "tool_confirmation.allow"
            if decision is ToolConfirmationStatus.ALLOWED
            else "tool_confirmation.deny"
        )
        if rejected:
            return f"{base}.rejected"
        return f"{base}.failed" if failed else base

    @staticmethod
    def _duration_ms(started_at: datetime | None, ended_at: datetime) -> int | None:
        if started_at is None:
            return None
        return max(0, int((ended_at - started_at).total_seconds() * 1000))

    @staticmethod
    def _raise_validation_conflict(message: str) -> None:
        raise ToolConfirmationServiceError(ErrorCode.VALIDATION_ERROR, message, 409)

    @staticmethod
    def _raise_not_actionable(message: str) -> None:
        raise ToolConfirmationServiceError(
            ErrorCode.TOOL_CONFIRMATION_NOT_ACTIONABLE,
            message or TOOL_CONFIRMATION_NOT_ACTIONABLE_MESSAGE,
            409,
        )

    def _commit_all(self) -> None:
        self._runtime_session.commit()
        self._control_session.commit()
        self._event_session.commit()
        if self._graph_session is not None:
            self._graph_session.commit()

    def _rollback_sessions(self) -> None:
        self._runtime_session.rollback()
        self._control_session.rollback()
        self._event_session.rollback()
        if self._graph_session is not None:
            self._graph_session.rollback()


class _NoopAuditService:
    def require_audit_record(self, **kwargs: Any) -> object:
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        return object()


__all__ = [
    "TOOL_CONFIRMATION_COMMAND_FAILED_MESSAGE",
    "TOOL_CONFIRMATION_NOT_ACTIONABLE_MESSAGE",
    "TOOL_CONFIRMATION_PAUSED_MESSAGE",
    "TOOL_CONFIRMATION_TARGET_NOT_FOUND_MESSAGE",
    "RunLogWriter",
    "ToolConfirmationCommandResult",
    "ToolConfirmationCancellationResult",
    "ToolConfirmationCreationResult",
    "ToolConfirmationService",
    "ToolConfirmationServiceError",
]
