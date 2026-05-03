from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import (
    ClarificationRecordModel,
    PipelineRunModel,
    RunControlRecordModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    ControlItemType,
    RunControlRecordType,
    StageType,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.feed import ControlItemFeedEntry, MessageFeedEntry
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.runs import RunLifecycleService, RunLifecycleServiceError
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


CLARIFICATION_REPLY_INVALID_MESSAGE = (
    "clarification_reply is valid only when the current Session, run, and "
    "requirement_analysis stage are waiting_clarification."
)
CLARIFICATION_REPLY_RESUME_FAILED_MESSAGE = "runtime resume failed for clarification_reply."
SESSION_NOT_FOUND_MESSAGE = "Session was not found."


@dataclass(frozen=True)
class ClarificationRequestResult:
    clarification_id: str
    control_record_id: str
    graph_interrupt_ref: str
    control_item: ControlItemFeedEntry


@dataclass(frozen=True)
class ClarificationAnswerResult:
    clarification_id: str
    message_item: MessageFeedEntry


class ClarificationServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ClarificationService:
    def __init__(
        self,
        *,
        control_session: Session,
        runtime_session: Session,
        event_session: Session,
        audit_service: Any,
        runtime_orchestration: RuntimeOrchestrationService,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._audit_service = audit_service
        self._runtime_orchestration = runtime_orchestration
        self._now = now or (lambda: datetime.now(UTC))
        self._runs = RunLifecycleService(
            control_session,
            runtime_session,
            now=self._now,
        )
        self._events = EventStore(event_session, now=self._now)

    def request_clarification(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        question: str,
        payload_ref: str,
        trace_context: TraceContext,
    ) -> ClarificationRequestResult:
        request_trace = self._trace(
            trace_context,
            span_id="clarification-request",
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
        )
        try:
            session = self._load_visible_session(session_id)
            run = self._runtime_session.get(PipelineRunModel, run_id)
            stage = self._runtime_session.get(StageRunModel, stage_run_id)
            if session is None or run is None or stage is None:
                raise RunLifecycleServiceError("Clarification target was not found.")
            self._runs.assert_can_request_clarification(
                session=session,
                run=run,
                stage=stage,
            )

            clarification_id = f"clarification-{uuid4().hex}"
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.SYSTEM,
                actor_id="runtime",
                action="clarification.request.accepted",
                target_type="clarification",
                target_id=clarification_id,
                result=AuditResult.ACCEPTED,
                reason=None,
                metadata={
                    "session_id": session.session_id,
                    "session_status": session.status.value,
                    "run_id": run.run_id,
                    "run_status": run.status.value,
                    "stage_run_id": stage.stage_run_id,
                    "stage_status": stage.status.value,
                    "stage_type": stage.stage_type.value,
                    "payload_ref": payload_ref,
                },
                trace_context=request_trace,
                rollback=self._rollback_sessions,
                created_at=self._now(),
            )
            thread = GraphThreadRef(
                thread_id=run.graph_thread_ref,
                run_id=run.run_id,
                status=GraphThreadStatus.RUNNING,
                current_stage_run_id=stage.stage_run_id,
                current_stage_type=stage.stage_type,
            )
            interrupt = self._runtime_orchestration.create_interrupt(
                thread=thread,
                interrupt_type=GraphInterruptType.CLARIFICATION_REQUEST,
                run_id=run.run_id,
                stage_run_id=stage.stage_run_id,
                stage_type=stage.stage_type,
                payload_ref=payload_ref,
                trace_context=request_trace,
                clarification_id=clarification_id,
            )

            timestamp = self._now()
            clarification = ClarificationRecordModel(
                clarification_id=clarification_id,
                run_id=run.run_id,
                stage_run_id=stage.stage_run_id,
                question=question,
                answer=None,
                payload_ref=payload_ref,
                graph_interrupt_ref=interrupt.interrupt_id,
                requested_at=timestamp,
                answered_at=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
            control_record_id = f"control-{uuid4().hex}"
            control_record = RunControlRecordModel(
                control_record_id=control_record_id,
                run_id=run.run_id,
                stage_run_id=stage.stage_run_id,
                control_type=RunControlRecordType.CLARIFICATION_WAIT,
                source_stage_type=StageType.REQUIREMENT_ANALYSIS,
                target_stage_type=StageType.REQUIREMENT_ANALYSIS,
                payload_ref=clarification.clarification_id,
                graph_interrupt_ref=interrupt.interrupt_id,
                occurred_at=timestamp,
                created_at=timestamp,
            )
            self._runtime_session.add_all([clarification, control_record])
            self._runs.mark_waiting_clarification(
                session=session,
                run=run,
                stage=stage,
            )
            control_item = self._control_item(
                control_record=control_record,
                run_id=run.run_id,
                occurred_at=timestamp,
            )
            self._events.append(
                DomainEventType.CLARIFICATION_REQUESTED,
                payload={
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "control_item": control_item.model_dump(mode="json"),
                },
                trace_context=request_trace,
            )
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.SYSTEM,
                actor_id="runtime",
                action="clarification.request",
                target_type="clarification",
                target_id=clarification.clarification_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "stage_type": stage.stage_type.value,
                    "clarification_id": clarification.clarification_id,
                    "control_record_id": control_record.control_record_id,
                    "graph_interrupt_ref": interrupt.interrupt_id,
                    "session_status": session.status.value,
                    "run_status": run.status.value,
                    "stage_status": stage.status.value,
                },
                trace_context=request_trace,
                rollback=self._rollback_sessions,
                created_at=timestamp,
            )
            self._commit_all()
            return ClarificationRequestResult(
                clarification_id=clarification.clarification_id,
                control_record_id=control_record.control_record_id,
                graph_interrupt_ref=interrupt.interrupt_id,
                control_item=control_item,
            )
        except RunLifecycleServiceError as exc:
            self._rollback_sessions()
            self._audit_service.record_rejected_command(
                actor_type=AuditActorType.SYSTEM,
                actor_id="runtime",
                action="clarification.request.rejected",
                target_type="clarification",
                target_id=session_id,
                reason=str(exc),
                metadata={
                    "session_id": session_id,
                    "run_id": run_id,
                    "stage_run_id": stage_run_id,
                },
                trace_context=request_trace,
                created_at=self._now(),
            )
            raise ClarificationServiceError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                409,
            ) from exc
        except Exception:
            self._rollback_sessions()
            raise

    def answer_clarification(
        self,
        *,
        session_id: str,
        answer: str,
        trace_context: TraceContext,
    ) -> ClarificationAnswerResult:
        timestamp = self._now()
        session = self._load_visible_session(session_id)
        if session is None:
            raise ClarificationServiceError(
                ErrorCode.NOT_FOUND,
                SESSION_NOT_FOUND_MESSAGE,
                404,
            )

        run = (
            self._runtime_session.get(PipelineRunModel, session.current_run_id)
            if session.current_run_id is not None
            else None
        )
        stage = (
            self._runtime_session.get(StageRunModel, run.current_stage_run_id)
            if run is not None and run.current_stage_run_id is not None
            else None
        )
        if run is None or stage is None:
            self._reject_reply(
                session_id=session_id,
                reason=CLARIFICATION_REPLY_INVALID_MESSAGE,
                trace_context=trace_context,
            )

        reply_trace = self._trace(
            trace_context,
            span_id="clarification-reply",
            session_id=session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
        )
        clarification = self._pending_clarification(run.run_id, stage.stage_run_id)
        try:
            if clarification is None:
                raise RunLifecycleServiceError(CLARIFICATION_REPLY_INVALID_MESSAGE)
            self._runs.mark_running_after_clarification_reply(
                session=session,
                run=run,
                stage=stage,
            )
        except RunLifecycleServiceError:
            self._rollback_sessions()
            self._reject_reply(
                session_id=session_id,
                reason=CLARIFICATION_REPLY_INVALID_MESSAGE,
                trace_context=reply_trace,
            )

        self._audit_service.require_audit_record(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action="session.message.clarification_reply.accepted",
            target_type="session",
            target_id=session_id,
            result=AuditResult.ACCEPTED,
            reason=None,
            metadata={
                "session_id": session_id,
                "session_status": session.status.value,
                "run_id": run.run_id,
                "run_status": run.status.value,
                "stage_run_id": stage.stage_run_id,
                "stage_status": stage.status.value,
                "stage_type": stage.stage_type.value,
                "clarification_id": clarification.clarification_id,
                "graph_interrupt_ref": clarification.graph_interrupt_ref,
                "answer_length": len(answer),
            },
            trace_context=reply_trace,
            rollback=self._rollback_sessions,
            created_at=timestamp,
        )
        clarification.answer = answer
        clarification.answered_at = timestamp
        clarification.updated_at = timestamp
        self._runtime_session.add(clarification)
        message_item = self._message_item(
            clarification=clarification,
            answer=answer,
            occurred_at=timestamp,
        )
        self._events.append(
            DomainEventType.CLARIFICATION_ANSWERED,
            payload={
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id,
                "message_item": message_item.model_dump(mode="json"),
            },
            trace_context=reply_trace,
        )

        interrupt = self._interrupt_from_record(run, stage, clarification)
        resume_payload = RuntimeResumePayload(
            resume_id=f"resume-{clarification.clarification_id}",
            payload_ref=f"clarification-answer-{clarification.clarification_id}",
            values={
                "clarification_id": clarification.clarification_id,
                "answer": answer,
            },
        )
        try:
            self._runtime_orchestration.resume_interrupt(
                interrupt=interrupt,
                resume_payload=resume_payload,
                trace_context=reply_trace,
            )
        except Exception as exc:
            self._rollback_sessions()
            self._audit_service.record_failed_command(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action="session.message.clarification_reply.resume_failed",
                target_type="clarification",
                target_id=clarification.clarification_id,
                reason=str(exc),
                metadata={
                    "session_id": session_id,
                    "session_status": session.status.value,
                    "run_status": run.status.value,
                    "stage_status": stage.status.value,
                    "stage_type": stage.stage_type.value,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "clarification_id": clarification.clarification_id,
                    "graph_interrupt_ref": clarification.graph_interrupt_ref,
                    "answer_length": len(answer),
                },
                trace_context=reply_trace,
                created_at=timestamp,
            )
            raise ClarificationServiceError(
                ErrorCode.INTERNAL_ERROR,
                CLARIFICATION_REPLY_RESUME_FAILED_MESSAGE,
                500,
            ) from exc

        try:
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action="session.message.clarification_reply",
                target_type="session",
                target_id=session_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata={
                    "session_id": session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "stage_type": stage.stage_type.value,
                    "clarification_id": clarification.clarification_id,
                    "graph_interrupt_ref": clarification.graph_interrupt_ref,
                    "session_status": session.status.value,
                    "run_status": run.status.value,
                    "stage_status": stage.status.value,
                    "answer_length": len(answer),
                },
                trace_context=reply_trace,
                rollback=self._rollback_sessions,
                created_at=timestamp,
            )
            self._commit_all()
        except Exception:
            self._rollback_sessions()
            raise
        return ClarificationAnswerResult(
            clarification_id=clarification.clarification_id,
            message_item=message_item,
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

    def _pending_clarification(
        self,
        run_id: str,
        stage_run_id: str,
    ) -> ClarificationRecordModel | None:
        return (
            self._runtime_session.query(ClarificationRecordModel)
            .filter(
                ClarificationRecordModel.run_id == run_id,
                ClarificationRecordModel.stage_run_id == stage_run_id,
                ClarificationRecordModel.answer.is_(None),
                ClarificationRecordModel.answered_at.is_(None),
            )
            .order_by(ClarificationRecordModel.requested_at.desc())
            .first()
        )

    def _interrupt_from_record(
        self,
        run: PipelineRunModel,
        stage: StageRunModel,
        clarification: ClarificationRecordModel,
    ) -> GraphInterruptRef:
        thread = GraphThreadRef(
            thread_id=run.graph_thread_ref,
            run_id=run.run_id,
            status=GraphThreadStatus.WAITING_CLARIFICATION,
            current_stage_run_id=stage.stage_run_id,
            current_stage_type=stage.stage_type,
        )
        checkpoint = CheckpointRef(
            checkpoint_id=f"checkpoint-{clarification.graph_interrupt_ref}",
            thread_id=thread.thread_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            purpose=CheckpointPurpose.WAITING_CLARIFICATION,
            payload_ref=clarification.payload_ref or clarification.clarification_id,
        )
        return GraphInterruptRef(
            interrupt_id=clarification.graph_interrupt_ref,
            thread=thread,
            interrupt_type=GraphInterruptType.CLARIFICATION_REQUEST,
            status=GraphInterruptStatus.PENDING,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            payload_ref=clarification.payload_ref or clarification.clarification_id,
            clarification_id=clarification.clarification_id,
            checkpoint_ref=checkpoint,
        )

    def _reject_reply(
        self,
        *,
        session_id: str,
        reason: str,
        trace_context: TraceContext,
    ) -> None:
        metadata: dict[str, Any] = {"session_id": session_id}
        session = self._load_visible_session(session_id)
        if session is not None:
            metadata["session_status"] = session.status.value
            if session.current_run_id is not None:
                metadata["run_id"] = session.current_run_id
                run = self._runtime_session.get(PipelineRunModel, session.current_run_id)
                if run is not None:
                    metadata["run_status"] = run.status.value
                    if run.current_stage_run_id is not None:
                        metadata["stage_run_id"] = run.current_stage_run_id
                        stage = self._runtime_session.get(
                            StageRunModel,
                            run.current_stage_run_id,
                        )
                        if stage is not None:
                            metadata["stage_status"] = stage.status.value
                            metadata["stage_type"] = stage.stage_type.value
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action="session.message.clarification_reply.rejected",
            target_type="session",
            target_id=session_id,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
            created_at=self._now(),
        )
        raise ClarificationServiceError(ErrorCode.VALIDATION_ERROR, reason, 409)

    def _trace(
        self,
        trace_context: TraceContext,
        *,
        span_id: str,
        session_id: str,
        run_id: str | None,
        stage_run_id: str | None,
    ) -> TraceContext:
        return trace_context.child_span(
            span_id=span_id,
            created_at=self._now(),
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
        )

    def _control_item(
        self,
        *,
        control_record: RunControlRecordModel,
        run_id: str,
        occurred_at: datetime,
    ) -> ControlItemFeedEntry:
        return ControlItemFeedEntry(
            entry_id=f"entry-{control_record.control_record_id}",
            run_id=run_id,
            occurred_at=occurred_at,
            control_record_id=control_record.control_record_id,
            control_type=ControlItemType.CLARIFICATION_WAIT,
            source_stage_type=control_record.source_stage_type,
            target_stage_type=control_record.target_stage_type,
            title="Clarification needed",
            summary="Requirement Analysis is waiting for user input.",
            payload_ref=control_record.payload_ref,
        )

    @staticmethod
    def _message_item(
        *,
        clarification: ClarificationRecordModel,
        answer: str,
        occurred_at: datetime,
    ) -> MessageFeedEntry:
        return MessageFeedEntry(
            entry_id=f"entry-message-{clarification.clarification_id}",
            run_id=clarification.run_id,
            occurred_at=occurred_at,
            message_id=f"message-{clarification.clarification_id}",
            author="user",
            content=answer,
            stage_run_id=clarification.stage_run_id,
        )

    def _commit_all(self) -> None:
        self._runtime_session.commit()
        self._control_session.commit()
        self._event_session.commit()

    def _rollback_sessions(self) -> None:
        self._runtime_session.rollback()
        self._control_session.rollback()
        self._event_session.rollback()


__all__ = [
    "CLARIFICATION_REPLY_INVALID_MESSAGE",
    "ClarificationAnswerResult",
    "ClarificationRequestResult",
    "ClarificationService",
    "ClarificationServiceError",
]
