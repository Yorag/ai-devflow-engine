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
    ApprovalRequestModel,
    PipelineRunModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    RunStatus,
    SessionStatus,
    StageStatus,
    StageType,
)
from backend.app.domain.runtime_refs import (
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.feed import ApprovalRequestFeedEntry
from backend.app.schemas.observability import LogCategory, LogLevel
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


_LOGGER = logging.getLogger(__name__)

APPROVAL_TARGET_NOT_FOUND_MESSAGE = "Approval target was not found."
APPROVAL_INTERRUPT_FAILED_MESSAGE = "runtime interrupt failed for approval request."
PENDING_APPROVAL_EXISTS_MESSAGE = (
    "A pending approval already exists for this run and stage."
)


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


@dataclass(frozen=True)
class ApprovalCreationResult:
    approval_id: str
    graph_interrupt_ref: str
    approval_request: ApprovalRequestFeedEntry


class ApprovalServiceError(RuntimeError):
    def __init__(self, error_code: ErrorCode, message: str, status_code: int) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ApprovalService:
    def __init__(
        self,
        *,
        control_session: Session,
        runtime_session: Session,
        event_session: Session,
        runtime_orchestration: RuntimeOrchestrationService,
        log_writer: RunLogWriter,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._runtime_orchestration = runtime_orchestration
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))
        self._events = EventStore(event_session, now=self._now)

    def create_solution_design_approval(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        payload_ref: str,
        approval_object_excerpt: str,
        risk_excerpt: str | None,
        approval_object_preview: dict[str, Any],
        trace_context: TraceContext,
    ) -> ApprovalCreationResult:
        return self._create_approval(
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
            expected_stage_type=StageType.SOLUTION_DESIGN,
            payload_ref=payload_ref,
            approval_object_excerpt=approval_object_excerpt,
            risk_excerpt=risk_excerpt,
            approval_object_preview=approval_object_preview,
            trace_context=trace_context,
        )

    def create_code_review_approval(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        payload_ref: str,
        approval_object_excerpt: str,
        risk_excerpt: str | None,
        approval_object_preview: dict[str, Any],
        trace_context: TraceContext,
    ) -> ApprovalCreationResult:
        return self._create_approval(
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            expected_stage_type=StageType.CODE_REVIEW,
            payload_ref=payload_ref,
            approval_object_excerpt=approval_object_excerpt,
            risk_excerpt=risk_excerpt,
            approval_object_preview=approval_object_preview,
            trace_context=trace_context,
        )

    def build_approval_request_projection(
        self,
        *,
        approval: ApprovalRequestModel,
        run: PipelineRunModel,
        approval_object_excerpt: str,
        risk_excerpt: str | None,
        approval_object_preview: dict[str, Any],
        occurred_at: datetime | None = None,
    ) -> ApprovalRequestFeedEntry:
        timestamp = occurred_at or self._now()
        is_actionable, disabled_reason = self._actionable_state(
            approval=approval,
            run=run,
        )
        return ApprovalRequestFeedEntry(
            entry_id=f"entry-{approval.approval_id}",
            run_id=approval.run_id,
            occurred_at=timestamp,
            approval_id=approval.approval_id,
            approval_type=approval.approval_type,
            status=approval.status,
            title=self._approval_title(approval.approval_type),
            approval_object_excerpt=approval_object_excerpt,
            risk_excerpt=risk_excerpt,
            approval_object_preview=approval_object_preview,
            approve_action="approve",
            reject_action="reject",
            is_actionable=is_actionable,
            requested_at=approval.requested_at,
            delivery_readiness_status=None,
            delivery_readiness_message=None,
            open_settings_action=None,
            disabled_reason=disabled_reason,
        )

    def _create_approval(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        approval_type: ApprovalType,
        expected_stage_type: StageType,
        payload_ref: str,
        approval_object_excerpt: str,
        risk_excerpt: str | None,
        approval_object_preview: dict[str, Any],
        trace_context: TraceContext,
    ) -> ApprovalCreationResult:
        if approval_type not in {
            ApprovalType.SOLUTION_DESIGN_APPROVAL,
            ApprovalType.CODE_REVIEW_APPROVAL,
        }:
            raise ApprovalServiceError(
                ErrorCode.VALIDATION_ERROR,
                f"Unsupported approval type: {approval_type.value}",
                409,
            )

        timestamp = self._now()
        approval_id = f"approval-{uuid4().hex}"
        try:
            control_session, run, stage = self._load_and_validate_target(
                session_id=session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                expected_stage_type=expected_stage_type,
            )
            self._assert_no_pending_approval(
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
                span_id=f"approval-create-{approval_id}",
                session_id=session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                approval_id=approval_id,
                graph_thread_id=run.graph_thread_ref,
            )
            thread = GraphThreadRef(
                thread_id=run.graph_thread_ref,
                run_id=run.run_id,
                status=GraphThreadStatus.RUNNING,
                current_stage_run_id=stage.stage_run_id,
                current_stage_type=stage.stage_type,
            )
            try:
                interrupt = self._runtime_orchestration.create_interrupt(
                    thread=thread,
                    interrupt_type=GraphInterruptType.APPROVAL,
                    run_id=run.run_id,
                    stage_run_id=stage.stage_run_id,
                    stage_type=stage.stage_type,
                    payload_ref=payload_ref,
                    trace_context=request_trace,
                    approval_id=approval_id,
                )
            except Exception as exc:
                self._record_run_log(
                    payload_type="approval_interrupt_failure",
                    message="Approval interrupt creation failed.",
                    metadata={
                        "session_id": session_id,
                        "run_id": run_id,
                        "stage_run_id": stage_run_id,
                        "approval_id": approval_id,
                        "approval_type": approval_type.value,
                        "stage_type": expected_stage_type.value,
                        "payload_ref": payload_ref,
                        "graph_thread_id": run.graph_thread_ref,
                        "error": str(exc),
                    },
                    trace_context=request_trace,
                    created_at=timestamp,
                    level=LogLevel.ERROR,
                    error_code=ErrorCode.INTERNAL_ERROR.value,
                )
                self._rollback_sessions()
                raise ApprovalServiceError(
                    ErrorCode.INTERNAL_ERROR,
                    APPROVAL_INTERRUPT_FAILED_MESSAGE,
                    500,
                ) from exc

            approval = ApprovalRequestModel(
                approval_id=approval_id,
                run_id=run.run_id,
                stage_run_id=stage.stage_run_id,
                approval_type=approval_type,
                status=ApprovalStatus.PENDING,
                payload_ref=payload_ref,
                graph_interrupt_ref=interrupt.interrupt_id,
                requested_at=timestamp,
                resolved_at=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._runtime_session.add(approval)
            self._mark_waiting_approval(
                control_session=control_session,
                run=run,
                stage=stage,
                timestamp=timestamp,
            )
            self._record_run_log(
                payload_type="approval_interrupt_created",
                message="Approval interrupt created.",
                metadata={
                    "session_id": session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "approval_id": approval.approval_id,
                    "approval_type": approval.approval_type.value,
                    "graph_interrupt_ref": interrupt.interrupt_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "payload_ref": payload_ref,
                },
                trace_context=request_trace,
                created_at=timestamp,
                level=LogLevel.INFO,
            )
            self._record_run_log(
                payload_type="approval_request_created",
                message="Approval request object created.",
                metadata={
                    "session_id": session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "approval_id": approval.approval_id,
                    "approval_type": approval.approval_type.value,
                    "approval_status": approval.status.value,
                    "run_status": run.status.value,
                    "stage_status": stage.status.value,
                    "session_status": control_session.status.value,
                    "graph_thread_id": run.graph_thread_ref,
                    "payload_ref": payload_ref,
                },
                trace_context=request_trace,
                created_at=timestamp,
                level=LogLevel.INFO,
            )
            projection = self.build_approval_request_projection(
                approval=approval,
                run=run,
                approval_object_excerpt=approval_object_excerpt,
                risk_excerpt=risk_excerpt,
                approval_object_preview=approval_object_preview,
                occurred_at=timestamp,
            )
            self._events.append(
                DomainEventType.APPROVAL_REQUESTED,
                payload={"approval_request": projection.model_dump(mode="json")},
                trace_context=request_trace,
            )
            self._commit_all()
            return ApprovalCreationResult(
                approval_id=approval.approval_id,
                graph_interrupt_ref=interrupt.interrupt_id,
                approval_request=projection,
            )
        except ApprovalServiceError:
            raise
        except Exception:
            self._rollback_sessions()
            raise

    def _load_and_validate_target(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        expected_stage_type: StageType,
    ) -> tuple[SessionModel, PipelineRunModel, StageRunModel]:
        session = self._load_visible_session(session_id)
        run = self._runtime_session.get(PipelineRunModel, run_id)
        stage = self._runtime_session.get(StageRunModel, stage_run_id)
        if session is None or run is None or stage is None:
            raise ApprovalServiceError(
                ErrorCode.NOT_FOUND,
                APPROVAL_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        if session.current_run_id != run.run_id:
            self._raise_target_conflict("Session current_run_id does not match run.")
        if run.session_id != session.session_id:
            self._raise_target_conflict("Run does not belong to the Session.")
        if run.current_stage_run_id != stage.stage_run_id:
            self._raise_target_conflict(
                "PipelineRun current_stage_run_id does not match stage."
            )
        if stage.run_id != run.run_id:
            self._raise_target_conflict("StageRun does not belong to the run.")
        if stage.stage_type is not expected_stage_type:
            self._raise_target_conflict(
                f"Expected source stage {expected_stage_type.value}."
            )
        return session, run, stage

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
            self._raise_target_conflict(
                "Approval target Session, run, and stage must be running."
            )

    def _assert_no_pending_approval(
        self,
        *,
        run_id: str,
        stage_run_id: str,
    ) -> None:
        existing = (
            self._runtime_session.query(ApprovalRequestModel)
            .filter(
                ApprovalRequestModel.run_id == run_id,
                ApprovalRequestModel.stage_run_id == stage_run_id,
                ApprovalRequestModel.status == ApprovalStatus.PENDING,
            )
            .first()
        )
        if existing is not None:
            raise ApprovalServiceError(
                ErrorCode.VALIDATION_ERROR,
                PENDING_APPROVAL_EXISTS_MESSAGE,
                409,
            )

    def _load_visible_session(self, session_id: str) -> SessionModel | None:
        return (
            self._control_session.query(SessionModel)
            .filter(
                SessionModel.session_id == session_id,
                SessionModel.is_visible.is_(True),
            )
            .one_or_none()
        )

    def _mark_waiting_approval(
        self,
        *,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        timestamp: datetime,
    ) -> None:
        control_session.status = SessionStatus.WAITING_APPROVAL
        control_session.latest_stage_type = stage.stage_type
        control_session.updated_at = timestamp
        run.status = RunStatus.WAITING_APPROVAL
        run.updated_at = timestamp
        stage.status = StageStatus.WAITING_APPROVAL
        stage.updated_at = timestamp

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
    ) -> None:
        redacted_payload = self._redaction_policy.summarize_payload(
            metadata,
            payload_type=payload_type,
        )
        try:
            self._log_writer.write_run_log(
                LogRecordInput(
                    source="services.approvals",
                    category=LogCategory.RUNTIME,
                    level=level,
                    message=message,
                    trace_context=trace_context,
                    payload=LogPayloadSummary.from_redacted_payload(
                        payload_type,
                        redacted_payload,
                    ),
                    created_at=created_at,
                    error_code=error_code,
                )
            )
        except Exception:
            _LOGGER.exception(
                "Approval run log write failed for approval_id=%s",
                trace_context.approval_id,
            )

    def _trace(
        self,
        trace_context: TraceContext,
        *,
        span_id: str,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        approval_id: str,
        graph_thread_id: str,
    ) -> TraceContext:
        return trace_context.child_span(
            span_id=span_id,
            created_at=self._now(),
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            approval_id=approval_id,
            graph_thread_id=graph_thread_id,
        )

    @staticmethod
    def _approval_title(approval_type: ApprovalType) -> str:
        if approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL:
            return "Review solution design"
        if approval_type is ApprovalType.CODE_REVIEW_APPROVAL:
            return "Review code review result"
        raise ApprovalServiceError(
            ErrorCode.VALIDATION_ERROR,
            f"Unsupported approval type: {approval_type.value}",
            409,
        )

    @staticmethod
    def _actionable_state(
        *,
        approval: ApprovalRequestModel,
        run: PipelineRunModel,
    ) -> tuple[bool, str | None]:
        if approval.status is not ApprovalStatus.PENDING:
            return False, "Approval is no longer pending."
        if run.status is RunStatus.WAITING_APPROVAL:
            return True, None
        if run.status is RunStatus.PAUSED:
            return False, "Current run is paused; resume it to continue approval."
        return False, "Current run is not waiting for approval."

    @staticmethod
    def _raise_target_conflict(message: str) -> None:
        raise ApprovalServiceError(ErrorCode.VALIDATION_ERROR, message, 409)

    def _commit_all(self) -> None:
        self._runtime_session.commit()
        self._control_session.commit()
        self._event_session.commit()

    def _rollback_sessions(self) -> None:
        self._runtime_session.rollback()
        self._control_session.rollback()
        self._event_session.rollback()


__all__ = [
    "APPROVAL_INTERRUPT_FAILED_MESSAGE",
    "APPROVAL_TARGET_NOT_FOUND_MESSAGE",
    "ApprovalCreationResult",
    "ApprovalService",
    "ApprovalServiceError",
    "RunLogWriter",
]
