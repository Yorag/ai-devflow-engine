from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import DeliveryChannelModel, ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ApprovalRequestModel,
    PipelineRunModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    SessionStatus,
    StageStatus,
    StageType,
    SseEventType,
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
from backend.app.schemas.feed import (
    ApprovalRequestFeedEntry,
    ApprovalResultFeedEntry,
    ControlItemFeedEntry,
)
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.observability import LogCategory, LogLevel
from backend.app.services.control_records import ControlRecordService
from backend.app.services.delivery_snapshots import DeliverySnapshotServiceError
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.graph_interrupt_refs import build_persisted_graph_interrupt_ref
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


_LOGGER = logging.getLogger(__name__)

APPROVAL_TARGET_NOT_FOUND_MESSAGE = "Approval target was not found."
APPROVAL_INTERRUPT_FAILED_MESSAGE = "runtime interrupt failed for approval request."
PENDING_APPROVAL_EXISTS_MESSAGE = (
    "A pending approval already exists for this run and stage."
)
APPROVAL_PAUSED_MESSAGE = "Current run is paused; resume it to continue approval."
APPROVAL_NOT_PENDING_MESSAGE = "Approval is no longer pending."
APPROVAL_DELIVERY_BLOCKED_MESSAGE = "DeliveryChannel is not ready for approval."
APPROVAL_COMMAND_FAILED_MESSAGE = "approval command failed."
APPROVAL_REJECT_REASON_BLANK_MESSAGE = "Reject reason must not be blank."


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


@dataclass(frozen=True)
class ApprovalCreationResult:
    approval_id: str
    graph_interrupt_ref: str
    approval_request: ApprovalRequestFeedEntry


@dataclass(frozen=True)
class ApprovalCommandResult:
    approval_result: ApprovalResultFeedEntry
    control_item: ControlItemFeedEntry | None = None


class ApprovalServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
        *,
        detail_ref: str | None = None,
        readiness_status: Any | None = None,
        readiness_message: str | None = None,
        open_settings_action: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.detail_ref = detail_ref
        self.readiness_status = readiness_status
        self.readiness_message = readiness_message
        self.open_settings_action = open_settings_action
        super().__init__(message)


class ApprovalService:
    def __init__(
        self,
        *,
        control_session: Session,
        runtime_session: Session,
        event_session: Session,
        runtime_orchestration: RuntimeOrchestrationService,
        graph_session: Session | None = None,
        audit_service: Any | None = None,
        delivery_snapshot_service: Any | None = None,
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
        self._delivery_snapshot_service = (
            delivery_snapshot_service or _NoopDeliverySnapshotService()
        )
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))
        self._events = EventStore(event_session, now=self._now)
        self._control_records = control_record_service or ControlRecordService(
            runtime_session=runtime_session,
            event_session=event_session,
            now=self._now,
        )

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

    def approve(
        self,
        *,
        approval_id: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> ApprovalCommandResult:
        return self._execute_command(
            approval_id=approval_id,
            actor_id=actor_id,
            trace_context=trace_context,
            decision=ApprovalStatus.APPROVED,
            reason=None,
        )

    def reject(
        self,
        *,
        approval_id: str,
        reason: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> ApprovalCommandResult:
        return self._execute_command(
            approval_id=approval_id,
            actor_id=actor_id,
            trace_context=trace_context,
            decision=ApprovalStatus.REJECTED,
            reason=reason,
        )

    def assert_delivery_readiness_for_code_review(
        self,
        *,
        approval: ApprovalRequestModel,
        run: PipelineRunModel,
        actor_id: str,
        trace_context: TraceContext,
        started_at: datetime | None = None,
    ) -> None:
        if approval.approval_type is not ApprovalType.CODE_REVIEW_APPROVAL:
            return
        channel = self._load_delivery_channel(run.project_id)
        if channel is None or channel.delivery_mode is not DeliveryMode.GIT_AUTO_DELIVERY:
            return
        if (
            channel.readiness_status is DeliveryReadinessStatus.READY
            and channel.credential_status is CredentialStatus.READY
        ):
            return
        updated_projection = self._refresh_blocked_approval_request_projection(
            approval=approval,
            run=run,
            channel=channel,
            trace_context=trace_context,
        )
        metadata = {
            "approval_id": approval.approval_id,
            "run_id": run.run_id,
            "stage_run_id": approval.stage_run_id,
            "approval_type": approval.approval_type.value,
            "delivery_mode": channel.delivery_mode.value if channel is not None else None,
            "readiness_status": (
                channel.readiness_status.value if channel is not None else None
            ),
            "readiness_message": channel.readiness_message if channel is not None else None,
            "open_settings_action": updated_projection.open_settings_action,
            "result_status": "blocked",
            "blocked_reason": APPROVAL_DELIVERY_BLOCKED_MESSAGE,
        }
        recorded_at = self._now()
        self._audit_service.record_blocked_action(
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            action="approval.approve.blocked",
            target_type="approval_request",
            target_id=approval.approval_id,
            reason=APPROVAL_DELIVERY_BLOCKED_MESSAGE,
            metadata=metadata,
            trace_context=trace_context,
            created_at=recorded_at,
        )
        self._record_run_log(
            payload_type="approval_command_blocked",
            message="Approval command blocked by delivery readiness.",
            metadata=metadata,
            trace_context=trace_context,
            created_at=recorded_at,
            level=LogLevel.WARNING,
            error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY.value,
            duration_ms=self._duration_ms(started_at, recorded_at),
        )
        self._event_session.commit()
        raise ApprovalServiceError(
            ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
            APPROVAL_DELIVERY_BLOCKED_MESSAGE,
            409,
            detail_ref=approval.approval_id,
            readiness_status=channel.readiness_status if channel is not None else None,
            readiness_message=channel.readiness_message if channel is not None else None,
            open_settings_action="open_delivery_settings",
        )

    def resolve_reject_target_stage(
        self,
        approval_type: ApprovalType,
    ) -> StageType:
        if approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL:
            return StageType.SOLUTION_DESIGN
        if approval_type is ApprovalType.CODE_REVIEW_APPROVAL:
            return StageType.CODE_GENERATION
        raise ApprovalServiceError(
            ErrorCode.VALIDATION_ERROR,
            f"Unsupported approval type: {approval_type.value}",
            409,
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

    def _execute_command(
        self,
        *,
        approval_id: str,
        actor_id: str,
        trace_context: TraceContext,
        decision: ApprovalStatus,
        reason: str | None,
    ) -> ApprovalCommandResult:
        started_at = self._now()
        timestamp = started_at
        approval = self._runtime_session.get(ApprovalRequestModel, approval_id)
        if approval is None:
            raise ApprovalServiceError(
                ErrorCode.NOT_FOUND,
                APPROVAL_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        run = self._runtime_session.get(PipelineRunModel, approval.run_id)
        stage = self._runtime_session.get(StageRunModel, approval.stage_run_id)
        control_session = self._load_visible_session(run.session_id if run is not None else "")
        if run is None or stage is None or control_session is None:
            raise ApprovalServiceError(
                ErrorCode.NOT_FOUND,
                APPROVAL_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        self._assert_command_target_consistency(
            approval=approval,
            control_session=control_session,
            run=run,
            stage=stage,
        )
        if approval.status is not ApprovalStatus.PENDING:
            self._record_rejected_submission(
                approval=approval,
                run=run,
                actor_id=actor_id,
                trace_context=trace_context,
                reason=APPROVAL_NOT_PENDING_MESSAGE,
                action=self._command_action(decision, rejected=True),
                started_at=started_at,
            )
            raise ApprovalServiceError(
                ErrorCode.APPROVAL_NOT_ACTIONABLE,
                APPROVAL_NOT_PENDING_MESSAGE,
                409,
            )
        if run.status is RunStatus.PAUSED or control_session.status is SessionStatus.PAUSED:
            self._record_rejected_submission(
                approval=approval,
                run=run,
                actor_id=actor_id,
                trace_context=trace_context,
                reason=APPROVAL_PAUSED_MESSAGE,
                action=self._command_action(decision, rejected=True),
                started_at=started_at,
            )
            raise ApprovalServiceError(
                ErrorCode.APPROVAL_NOT_ACTIONABLE,
                APPROVAL_PAUSED_MESSAGE,
                409,
            )
        if decision is ApprovalStatus.REJECTED:
            reason = self._normalize_reject_reason(reason)
        if run.status is not RunStatus.WAITING_APPROVAL or control_session.status is not SessionStatus.WAITING_APPROVAL:
            message = "Current run is not waiting for approval."
            self._record_rejected_submission(
                approval=approval,
                run=run,
                actor_id=actor_id,
                trace_context=trace_context,
                reason=message,
                action=self._command_action(decision, rejected=True),
                started_at=started_at,
            )
            raise ApprovalServiceError(
                ErrorCode.APPROVAL_NOT_ACTIONABLE,
                message,
                409,
            )

        child_trace = self._trace(
            trace_context,
            span_id=(
                f"approval-approve-{approval_id}"
                if decision is ApprovalStatus.APPROVED
                else f"approval-reject-{approval_id}"
            ),
            session_id=run.session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            approval_id=approval.approval_id,
            graph_thread_id=run.graph_thread_ref,
        )

        if (
            decision is ApprovalStatus.APPROVED
            and approval.approval_type is ApprovalType.CODE_REVIEW_APPROVAL
        ):
            self.assert_delivery_readiness_for_code_review(
                approval=approval,
                run=run,
                actor_id=actor_id,
                trace_context=child_trace,
                started_at=started_at,
            )

        try:
            next_stage_type = self._resolve_next_stage_type(
                approval_type=approval.approval_type,
                decision=decision,
            )
            if (
                decision is ApprovalStatus.APPROVED
                and approval.approval_type is ApprovalType.CODE_REVIEW_APPROVAL
            ):
                self._delivery_snapshot_service.prepare_delivery_snapshot(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    approval_type=approval.approval_type,
                    target_stage_type=next_stage_type,
                    trace_context=child_trace,
                )

            decision_model = ApprovalDecisionModel(
                decision_id=f"approval-decision-{uuid4().hex}",
                approval_id=approval.approval_id,
                run_id=run.run_id,
                decision=decision,
                reason=reason,
                decided_by_actor_id=actor_id,
                decided_at=timestamp,
                created_at=timestamp,
            )
            self._runtime_session.add(decision_model)
            approval.status = decision
            approval.resolved_at = timestamp
            approval.updated_at = timestamp
            self._mark_running_after_approval_command(
                control_session=control_session,
                run=run,
                stage=stage,
                timestamp=timestamp,
            )

            approval_result = ApprovalResultFeedEntry(
                entry_id=f"entry-{approval.approval_id}-result",
                run_id=run.run_id,
                occurred_at=timestamp,
                approval_id=approval.approval_id,
                approval_type=approval.approval_type,
                decision=decision,
                reason=reason,
                created_at=timestamp,
                next_stage_type=next_stage_type,
            )
            self._events.append(
                (
                    DomainEventType.APPROVAL_APPROVED
                    if decision is ApprovalStatus.APPROVED
                    else DomainEventType.APPROVAL_REJECTED
                ),
                payload={"approval_result": approval_result.model_dump(mode="json")},
                trace_context=child_trace,
            )

            control_item: ControlItemFeedEntry | None = None
            if decision is ApprovalStatus.REJECTED:
                rollback = self._control_records.append_rollback_control_item(
                    run_id=run.run_id,
                    stage_run_id=stage.stage_run_id,
                    source_stage_type=stage.stage_type,
                    target_stage_type=next_stage_type,
                    payload_ref=f"approval-decision:{decision_model.decision_id}",
                    summary=(
                        f"Rejected approval: {reason.rstrip('.!?')}."  # normalize punctuation
                        " "
                        f"Continue in {next_stage_type.value}."
                    ),
                    trace_context=child_trace,
                    occurred_at=timestamp,
                )
                control_item = rollback.control_item

            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action=self._command_action(decision),
                target_type="approval_request",
                target_id=approval.approval_id,
                result=AuditResult.SUCCEEDED,
                reason=reason,
                metadata={
                    "approval_id": approval.approval_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "approval_type": approval.approval_type.value,
                    "decision": decision.value,
                    "next_stage_type": next_stage_type.value,
                },
                trace_context=child_trace,
                rollback=self._rollback_sessions,
                created_at=timestamp,
            )
            self._record_run_log(
                payload_type="approval_command_accepted",
                message=(
                    "Approval approve command accepted."
                    if decision is ApprovalStatus.APPROVED
                    else "Approval reject command accepted."
                ),
                metadata={
                    "approval_id": approval.approval_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "decision_id": decision_model.decision_id,
                    "approval_type": approval.approval_type.value,
                    "decision": decision.value,
                    "next_stage_type": next_stage_type.value,
                    "result_status": "accepted",
                },
                trace_context=child_trace,
                created_at=timestamp,
                level=LogLevel.INFO,
                duration_ms=self._duration_ms(started_at, timestamp),
            )
            interrupt = self._build_interrupt(approval=approval, run=run, stage=stage)
            self._runtime_orchestration.resume_interrupt(
                interrupt=interrupt,
                resume_payload=RuntimeResumePayload(
                    resume_id=f"resume-{decision_model.decision_id}",
                    payload_ref=decision_model.decision_id,
                    values={
                        "decision": decision.value,
                        "reason": reason,
                        "approval_id": approval.approval_id,
                        "next_stage_type": next_stage_type.value,
                    },
                ),
                trace_context=child_trace,
            )
            self._commit_all()
            return ApprovalCommandResult(
                approval_result=approval_result,
                control_item=control_item,
            )
        except DeliverySnapshotServiceError as exc:
            self._rollback_sessions()
            raise ApprovalServiceError(
                exc.error_code,
                exc.message,
                exc.status_code,
            ) from exc
        except ApprovalServiceError:
            self._rollback_sessions()
            raise
        except Exception as exc:
            self._rollback_sessions()
            self._record_failed_command(
                approval=approval,
                run=run,
                stage=stage,
                actor_id=actor_id,
                trace_context=child_trace,
                action=self._command_action(decision, failed=True),
                reason=str(exc) or type(exc).__name__,
                started_at=started_at,
            )
            raise ApprovalServiceError(
                ErrorCode.INTERNAL_ERROR,
                APPROVAL_COMMAND_FAILED_MESSAGE,
                500,
            ) from exc

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

    def _assert_command_target_consistency(
        self,
        *,
        approval: ApprovalRequestModel,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        if control_session.current_run_id != run.run_id:
            self._raise_target_conflict(
                "Session current_run_id does not match run.",
                error_code=ErrorCode.APPROVAL_NOT_ACTIONABLE,
            )
        if run.session_id != control_session.session_id:
            self._raise_target_conflict(
                "Run does not belong to the Session.",
                error_code=ErrorCode.APPROVAL_NOT_ACTIONABLE,
            )
        if run.current_stage_run_id != stage.stage_run_id:
            self._raise_target_conflict(
                "PipelineRun current_stage_run_id does not match stage.",
                error_code=ErrorCode.APPROVAL_NOT_ACTIONABLE,
            )
        if stage.run_id != run.run_id:
            self._raise_target_conflict(
                "StageRun does not belong to the run.",
                error_code=ErrorCode.APPROVAL_NOT_ACTIONABLE,
            )
        if approval.run_id != run.run_id:
            self._raise_target_conflict(
                "ApprovalRequest does not belong to the run.",
                error_code=ErrorCode.APPROVAL_NOT_ACTIONABLE,
            )
        if approval.stage_run_id != stage.stage_run_id:
            self._raise_target_conflict(
                "ApprovalRequest does not belong to the stage.",
                error_code=ErrorCode.APPROVAL_NOT_ACTIONABLE,
            )
        expected_stage_type = self._source_stage_type_for_approval(approval.approval_type)
        if stage.stage_type is not expected_stage_type:
            self._raise_target_conflict(
                f"Expected source stage {expected_stage_type.value}.",
                error_code=ErrorCode.APPROVAL_NOT_ACTIONABLE,
            )

    def _mark_running_after_approval_command(
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

    def _load_delivery_channel(self, project_id: str) -> DeliveryChannelModel | None:
        project = self._control_session.get(
            ProjectModel,
            project_id,
            populate_existing=True,
        )
        if project is None or not project.is_visible or not project.default_delivery_channel_id:
            return None
        channel = self._control_session.get(
            DeliveryChannelModel,
            project.default_delivery_channel_id,
            populate_existing=True,
        )
        if channel is None or channel.project_id != project.project_id:
            return None
        return channel

    def _latest_approval_request_projection(
        self,
        *,
        approval_id: str,
        run_id: str,
    ) -> ApprovalRequestFeedEntry | None:
        events = (
            self._event_session.query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == run_id,
                DomainEventModel.event_type == SseEventType.APPROVAL_REQUESTED,
            )
            .order_by(
                DomainEventModel.sequence_index.desc(),
                DomainEventModel.event_id.desc(),
            )
            .all()
        )
        for event in events:
            payload = event.payload.get("approval_request")
            if not isinstance(payload, dict):
                continue
            if payload.get("approval_id") != approval_id:
                continue
            return ApprovalRequestFeedEntry.model_validate(payload)
        return None

    def _refresh_blocked_approval_request_projection(
        self,
        *,
        approval: ApprovalRequestModel,
        run: PipelineRunModel,
        channel: DeliveryChannelModel | None,
        trace_context: TraceContext,
    ) -> ApprovalRequestFeedEntry:
        current_projection = self._latest_approval_request_projection(
            approval_id=approval.approval_id,
            run_id=run.run_id,
        )
        if current_projection is None:
            current_projection = self.build_approval_request_projection(
                approval=approval,
                run=run,
                approval_object_excerpt="Review the approval object.",
                risk_excerpt=None,
                approval_object_preview={"payload_ref": approval.payload_ref},
                occurred_at=self._now(),
            )
        projection = current_projection.model_copy(
            update={
                "occurred_at": self._now(),
                "delivery_readiness_status": (
                    channel.readiness_status if channel is not None else None
                ),
                "delivery_readiness_message": (
                    channel.readiness_message if channel is not None else None
                ),
                "open_settings_action": "open_delivery_settings",
            }
        )
        self._events.append(
            DomainEventType.APPROVAL_REQUESTED,
            payload={"approval_request": projection.model_dump(mode="json")},
            trace_context=trace_context,
        )
        return projection

    @staticmethod
    def _source_stage_type_for_approval(approval_type: ApprovalType) -> StageType:
        if approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL:
            return StageType.SOLUTION_DESIGN
        if approval_type is ApprovalType.CODE_REVIEW_APPROVAL:
            return StageType.CODE_REVIEW
        raise ApprovalServiceError(
            ErrorCode.VALIDATION_ERROR,
            f"Unsupported approval type: {approval_type.value}",
            409,
        )

    @staticmethod
    def _normalize_reject_reason(reason: str | None) -> str:
        if reason is None:
            raise ApprovalServiceError(
                ErrorCode.VALIDATION_ERROR,
                APPROVAL_REJECT_REASON_BLANK_MESSAGE,
                409,
            )
        stripped = reason.strip()
        if not stripped:
            raise ApprovalServiceError(
                ErrorCode.VALIDATION_ERROR,
                APPROVAL_REJECT_REASON_BLANK_MESSAGE,
                409,
            )
        return stripped

    def _resolve_next_stage_type(
        self,
        *,
        approval_type: ApprovalType,
        decision: ApprovalStatus,
    ) -> StageType:
        if decision is ApprovalStatus.REJECTED:
            return self.resolve_reject_target_stage(approval_type)
        if approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL:
            return StageType.CODE_GENERATION
        if approval_type is ApprovalType.CODE_REVIEW_APPROVAL:
            return StageType.DELIVERY_INTEGRATION
        raise ApprovalServiceError(
            ErrorCode.VALIDATION_ERROR,
            f"Unsupported approval type: {approval_type.value}",
            409,
        )

    def _build_interrupt(
        self,
        *,
        approval: ApprovalRequestModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> GraphInterruptRef:
        if self._graph_session is None:
            raise RuntimeError("Approval resume requires graph_session.")
        return build_persisted_graph_interrupt_ref(
            graph_session=self._graph_session,
            run=run,
            stage=stage,
            interrupt_id=approval.graph_interrupt_ref,
            interrupt_type=GraphInterruptType.APPROVAL,
            payload_ref=approval.payload_ref,
            checkpoint_purpose=CheckpointPurpose.WAITING_APPROVAL,
            thread_status=GraphThreadStatus.WAITING_APPROVAL,
            approval_id=approval.approval_id,
        )

    def _record_rejected_submission(
        self,
        *,
        approval: ApprovalRequestModel,
        run: PipelineRunModel,
        actor_id: str,
        trace_context: TraceContext,
        reason: str,
        action: str,
        started_at: datetime | None = None,
    ) -> None:
        recorded_at = self._now()
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            action=action,
            target_type="approval_request",
            target_id=approval.approval_id,
            reason=reason,
            metadata={
                "approval_id": approval.approval_id,
                "run_id": run.run_id,
                "stage_run_id": approval.stage_run_id,
                "approval_type": approval.approval_type.value,
                "result_status": "rejected",
                "rejected_reason": reason,
            },
            trace_context=trace_context,
            created_at=recorded_at,
        )
        self._record_run_log(
            payload_type="approval_command_rejected",
            message="Approval command rejected.",
            metadata={
                "approval_id": approval.approval_id,
                "run_id": run.run_id,
                "stage_run_id": approval.stage_run_id,
                "approval_type": approval.approval_type.value,
                "reason": reason,
                "result_status": "rejected",
            },
            trace_context=trace_context,
            created_at=recorded_at,
            level=LogLevel.WARNING,
            error_code=ErrorCode.VALIDATION_ERROR.value,
            duration_ms=self._duration_ms(started_at, recorded_at),
        )

    def _record_failed_command(
        self,
        *,
        approval: ApprovalRequestModel,
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
                target_type="approval_request",
                target_id=approval.approval_id,
                reason=reason,
                metadata={
                    "approval_id": approval.approval_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "approval_type": approval.approval_type.value,
                    "result_status": "failed",
                },
                trace_context=trace_context,
                created_at=recorded_at,
            )
        except Exception:
            pass
        try:
            self._record_run_log(
                payload_type="approval_command_failed",
                message="Approval command failed.",
                metadata={
                    "approval_id": approval.approval_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "approval_type": approval.approval_type.value,
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

    @staticmethod
    def _command_action(
        decision: ApprovalStatus,
        *,
        rejected: bool = False,
        failed: bool = False,
    ) -> str:
        base = "approval.approve" if decision is ApprovalStatus.APPROVED else "approval.reject"
        if rejected:
            return f"{base}.rejected"
        if failed:
            return f"{base}.failed"
        return base

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
                    duration_ms=duration_ms,
                    error_code=error_code,
                )
            )
        except Exception:
            _LOGGER.exception(
                "Approval run log write failed for approval_id=%s",
                trace_context.approval_id,
            )

    @staticmethod
    def _duration_ms(started_at: datetime | None, ended_at: datetime) -> int | None:
        if started_at is None:
            return None
        return max(0, int((ended_at - started_at).total_seconds() * 1000))

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
    def _raise_target_conflict(
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
    ) -> None:
        raise ApprovalServiceError(error_code, message, 409)

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

    def record_blocked_action(self, **kwargs: Any) -> object:
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        return object()


class _NoopDeliverySnapshotService:
    def prepare_delivery_snapshot(self, **kwargs: Any) -> object:
        return object()


__all__ = [
    "APPROVAL_COMMAND_FAILED_MESSAGE",
    "APPROVAL_DELIVERY_BLOCKED_MESSAGE",
    "APPROVAL_INTERRUPT_FAILED_MESSAGE",
    "APPROVAL_NOT_PENDING_MESSAGE",
    "APPROVAL_PAUSED_MESSAGE",
    "APPROVAL_TARGET_NOT_FOUND_MESSAGE",
    "ApprovalCommandResult",
    "ApprovalCreationResult",
    "ApprovalService",
    "ApprovalServiceError",
    "RunLogWriter",
]
