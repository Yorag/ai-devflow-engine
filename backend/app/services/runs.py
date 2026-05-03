from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    PipelineRunModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    RunStatus,
    SessionStatus,
    SseEventType,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
)
from backend.app.domain.provider_call_policy_snapshot import ProviderCallPolicySnapshot
from backend.app.domain.provider_snapshot import ModelBindingSnapshot, ProviderSnapshot
from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshot
from backend.app.domain.runtime_refs import CheckpointRef, GraphThreadRef, GraphThreadStatus
from backend.app.domain.state_machine import RunStateMachine
from backend.app.domain.template_snapshot import TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.feed import ApprovalRequestFeedEntry, ToolConfirmationFeedEntry
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
)
from backend.app.repositories.runtime import RuntimeSnapshotRepository
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class RunLifecycleServiceError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        status_code: int = 409,
        detail_ref: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.status_code = status_code
        self.detail_ref = detail_ref
        super().__init__(message)


@dataclass(frozen=True)
class RunCommandResult:
    session: SessionModel
    run: PipelineRunModel
    stage: StageRunModel
    checkpoint_ref: CheckpointRef | None = None


class RunLifecycleService:
    def __init__(
        self,
        session: Session | None = None,
        runtime_session: Session | None = None,
        *,
        control_session: Session | None = None,
        event_session: Session | None = None,
        runtime_orchestration: RuntimeOrchestrationService | None = None,
        audit_service: Any | None = None,
        log_writer: RunLogWriter | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if control_session is None:
            control_session = session if runtime_session is not None else None
        if runtime_session is None:
            runtime_session = session
        if runtime_session is None:
            raise TypeError("runtime_session or session is required")
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._runtime_orchestration = runtime_orchestration
        self._audit_service = audit_service or _NoopAuditService()
        self._log_writer = log_writer or _NoopRunLogWriter()
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))
        self._events = (
            EventStore(event_session, now=self._now)
            if event_session is not None
            else None
        )

    def pause_run(
        self,
        *,
        run_id: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> RunCommandResult:
        started_at = self._now()
        session, run, stage = self._load_active_run_context(run_id)
        command_trace = self._command_trace(
            trace_context,
            span_id=f"runtime-pause-{run.run_id}",
            session=session,
            run=run,
            stage=stage,
        )
        try:
            self._assert_can_pause(session=session, run=run)
        except RunLifecycleServiceError as exc:
            self._record_rejected_command(
                action="runtime.pause.rejected",
                message="Run pause command rejected.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            raise

        status_before = run.status
        try:
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action="runtime.pause",
                target_type="run",
                target_id=run.run_id,
                result=AuditResult.ACCEPTED,
                reason="Pause accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "status_before": status_before.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                rollback=self._rollback_all,
                created_at=started_at,
            )
            self._record_run_log(
                payload_type="runtime_pause_accepted",
                message="Run pause command accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "status_before": status_before.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            runtime_result = self._require_runtime_orchestration().pause_thread(
                thread=self._build_thread_ref(run=run, stage=stage),
                stage_run_id=stage.stage_run_id,
                stage_type=stage.stage_type,
                workspace_snapshot_ref=run.workspace_ref,
                trace_context=command_trace,
            )
            checkpoint = runtime_result.checkpoint_ref
            self._persist_recovery_checkpoint(
                control_session=session,
                run=run,
                stage=stage,
                checkpoint=checkpoint,
                saved_at=started_at,
            )
            run.status = RunStatus.PAUSED
            run.updated_at = started_at
            session.status = SessionStatus.PAUSED
            session.updated_at = started_at
            self._runtime_session.add(run)
            self._require_control_session().add(session)
            self._append_run_status_event(
                DomainEventType.RUN_PAUSED,
                session=session,
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._refresh_pending_wait_entry_for_pause(
                pre_pause_status=status_before,
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._commit_all()
            self._record_run_log(
                payload_type="runtime_pause_completed",
                message="Run pause completed.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "checkpoint_id": checkpoint.checkpoint_id if checkpoint else None,
                    "status_before": status_before.value,
                    "status_after": run.status.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            return RunCommandResult(
                session=session,
                run=run,
                stage=stage,
                checkpoint_ref=checkpoint,
            )
        except Exception as exc:
            self._rollback_all()
            self._record_failed_command(
                action="runtime.pause.failed",
                message="Run pause failed.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            if isinstance(exc, RunLifecycleServiceError):
                raise
            raise RunLifecycleServiceError(
                "runtime pause command failed.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run.run_id,
            ) from exc

    def resume_run(
        self,
        *,
        run_id: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> RunCommandResult:
        started_at = self._now()
        session, run, stage = self._load_active_run_context(run_id)
        command_trace = self._command_trace(
            trace_context,
            span_id=f"runtime-resume-{run.run_id}",
            session=session,
            run=run,
            stage=stage,
        )
        try:
            self._assert_can_resume(session=session, run=run)
        except RunLifecycleServiceError as exc:
            self._record_rejected_command(
                action="runtime.resume.rejected",
                message="Run resume command rejected.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            raise

        try:
            checkpoint_artifact = self._latest_recovery_checkpoint(run_id=run.run_id)
            checkpoint = CheckpointRef.model_validate(
                checkpoint_artifact.process["checkpoint"]
            )
            self._validate_recovery_checkpoint(
                artifact=checkpoint_artifact,
                checkpoint=checkpoint,
                run=run,
                stage=stage,
            )
            pre_pause_status = RunStatus(
                checkpoint_artifact.process["run_status_before_pause"]
            )
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action="runtime.resume",
                target_type="run",
                target_id=run.run_id,
                result=AuditResult.ACCEPTED,
                reason="Resume accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "status_before": run.status.value,
                    "status_after": pre_pause_status.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                rollback=self._rollback_all,
                created_at=started_at,
            )
            self._record_run_log(
                payload_type="runtime_resume_accepted",
                message="Run resume command accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "status_before": run.status.value,
                    "status_after": pre_pause_status.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            self._require_runtime_orchestration().resume_thread(
                thread=self._build_thread_ref(run=run, stage=stage, paused=True),
                checkpoint=checkpoint,
                trace_context=command_trace,
            )
            run.status = pre_pause_status
            run.updated_at = started_at
            session.status = RunStateMachine.project_session_status(pre_pause_status)
            session.updated_at = started_at
            self._runtime_session.add(run)
            self._require_control_session().add(session)
            self._append_run_status_event(
                DomainEventType.RUN_RESUMED,
                session=session,
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._refresh_pending_wait_entry_for_resume(
                pre_pause_status=pre_pause_status,
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._commit_all()
            self._record_run_log(
                payload_type="runtime_resume_completed",
                message="Run resume completed.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "status_before": RunStatus.PAUSED.value,
                    "status_after": run.status.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            return RunCommandResult(
                session=session,
                run=run,
                stage=stage,
                checkpoint_ref=checkpoint,
            )
        except Exception as exc:
            self._rollback_all()
            self._record_failed_command(
                action="runtime.resume.failed",
                message="Run resume failed.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            if isinstance(exc, RunLifecycleServiceError):
                raise
            raise RunLifecycleServiceError(
                "runtime resume command failed.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run.run_id,
            ) from exc

    def attach_template_snapshot(
        self,
        run: PipelineRunModel,
        snapshot: TemplateSnapshot,
    ) -> PipelineRunModel:
        if run.run_id != snapshot.run_id:
            raise ValueError("template snapshot run_id must match PipelineRun.run_id")
        run.template_snapshot_ref = snapshot.snapshot_ref
        run.updated_at = self._now()
        self._runtime_session.add(run)
        return run

    def attach_provider_snapshots(
        self,
        run: PipelineRunModel,
        *,
        provider_snapshots: tuple[ProviderSnapshot, ...],
        model_binding_snapshots: tuple[ModelBindingSnapshot, ...],
    ) -> PipelineRunModel:
        if not provider_snapshots:
            raise ValueError("provider_snapshots must not be empty")
        if not model_binding_snapshots:
            raise ValueError("model_binding_snapshots must not be empty")
        for snapshot in provider_snapshots:
            if run.run_id != snapshot.run_id:
                raise ValueError(
                    "provider snapshot run_id must match PipelineRun.run_id"
                )
        provider_snapshot_ids = {
            snapshot.snapshot_id for snapshot in provider_snapshots
        }
        for snapshot in model_binding_snapshots:
            if run.run_id != snapshot.run_id:
                raise ValueError(
                    "model binding snapshot run_id must match PipelineRun.run_id"
                )
            if snapshot.provider_snapshot_id not in provider_snapshot_ids:
                raise ValueError(
                    "model binding snapshot provider_snapshot_id must reference "
                    "attached provider_snapshots"
                )

        repository = RuntimeSnapshotRepository(self._runtime_session)
        for snapshot in provider_snapshots:
            repository.save_provider_snapshot(snapshot)
        for snapshot in model_binding_snapshots:
            repository.save_model_binding_snapshot(snapshot)

        run.updated_at = self._now()
        self._runtime_session.add(run)
        return run

    def attach_runtime_limit_snapshot(
        self,
        run: PipelineRunModel,
        snapshot: RuntimeLimitSnapshot,
    ) -> PipelineRunModel:
        if run.run_id != snapshot.run_id:
            raise ValueError(
                "runtime limit snapshot run_id must match PipelineRun.run_id"
            )
        RuntimeSnapshotRepository(self._runtime_session).save_runtime_limit_snapshot(
            snapshot
        )
        run.runtime_limit_snapshot_ref = snapshot.snapshot_id
        run.updated_at = self._now()
        self._runtime_session.add(run)
        return run

    def attach_provider_call_policy_snapshot(
        self,
        run: PipelineRunModel,
        snapshot: ProviderCallPolicySnapshot,
    ) -> PipelineRunModel:
        if run.run_id != snapshot.run_id:
            raise ValueError(
                "provider call policy snapshot run_id must match PipelineRun.run_id"
            )
        RuntimeSnapshotRepository(
            self._runtime_session
        ).save_provider_call_policy_snapshot(snapshot)
        run.provider_call_policy_snapshot_ref = snapshot.snapshot_id
        run.updated_at = self._now()
        self._runtime_session.add(run)
        return run

    def mark_waiting_clarification(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        self.assert_can_request_clarification(session=session, run=run, stage=stage)

        timestamp = self._now()
        run.status = RunStatus.WAITING_CLARIFICATION
        run.updated_at = timestamp
        stage.status = StageStatus.WAITING_CLARIFICATION
        stage.updated_at = timestamp
        session.status = SessionStatus.WAITING_CLARIFICATION
        session.updated_at = timestamp
        self._runtime_session.add_all([run, stage])
        self._require_control_session().add(session)

    def assert_can_request_clarification(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        self._assert_requirement_analysis_tail(session=session, run=run, stage=stage)
        if run.status is not RunStatus.RUNNING:
            raise RunLifecycleServiceError(
                "Clarification can be requested only from a running run."
            )
        if stage.status is not StageStatus.RUNNING:
            raise RunLifecycleServiceError(
                "Clarification can be requested only from a running stage."
            )
        if session.status is not SessionStatus.RUNNING:
            raise RunLifecycleServiceError(
                "Clarification can be requested only from a running Session."
            )

    def mark_running_after_clarification_reply(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        self._assert_requirement_analysis_tail(session=session, run=run, stage=stage)
        if run.status is not RunStatus.WAITING_CLARIFICATION:
            raise RunLifecycleServiceError(
                "clarification_reply requires a run in waiting_clarification."
            )
        if stage.status is not StageStatus.WAITING_CLARIFICATION:
            raise RunLifecycleServiceError(
                "clarification_reply requires a stage in waiting_clarification."
            )
        if session.status is not SessionStatus.WAITING_CLARIFICATION:
            raise RunLifecycleServiceError(
                "clarification_reply requires a Session in waiting_clarification."
            )

        timestamp = self._now()
        run.status = RunStatus.RUNNING
        run.updated_at = timestamp
        stage.status = StageStatus.RUNNING
        stage.updated_at = timestamp
        session.status = SessionStatus.RUNNING
        session.updated_at = timestamp
        self._runtime_session.add_all([run, stage])
        self._require_control_session().add(session)

    def _require_control_session(self) -> Session:
        if self._control_session is None:
            raise RunLifecycleServiceError(
                "control_session is required for Session state changes."
            )
        return self._control_session

    @staticmethod
    def _assert_requirement_analysis_tail(
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        if session.current_run_id != run.run_id:
            raise RunLifecycleServiceError("Session current_run_id must match the run.")
        if run.session_id != session.session_id:
            raise RunLifecycleServiceError("Run session_id must match the Session.")
        if run.current_stage_run_id != stage.stage_run_id:
            raise RunLifecycleServiceError(
                "Run current_stage_run_id must match the stage."
            )
        if stage.run_id != run.run_id:
            raise RunLifecycleServiceError("Stage run_id must match the run.")
        if stage.stage_type is not StageType.REQUIREMENT_ANALYSIS:
            raise RunLifecycleServiceError(
                "Clarification is only valid in requirement_analysis."
            )
        if session.latest_stage_type is not StageType.REQUIREMENT_ANALYSIS:
            raise RunLifecycleServiceError(
                "Session latest_stage_type must be requirement_analysis."
            )

    def _load_active_run_context(
        self,
        run_id: str,
    ) -> tuple[SessionModel, PipelineRunModel, StageRunModel]:
        run = self._runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise RunLifecycleServiceError(
                "PipelineRun was not found.",
                error_code=ErrorCode.NOT_FOUND,
                status_code=404,
                detail_ref=run_id,
            )
        control_session = self._require_control_session().get(
            SessionModel,
            run.session_id,
        )
        stage = (
            self._runtime_session.get(StageRunModel, run.current_stage_run_id)
            if run.current_stage_run_id is not None
            else None
        )
        if control_session is None or stage is None or not control_session.is_visible:
            raise RunLifecycleServiceError(
                "Active run context was not found.",
                error_code=ErrorCode.NOT_FOUND,
                status_code=404,
                detail_ref=run_id,
            )
        if control_session.current_run_id != run.run_id:
            self._raise_validation("Pause/resume target must be the current active run.")
        if run.session_id != control_session.session_id:
            self._raise_validation("Run does not belong to the Session.")
        if run.current_stage_run_id != stage.stage_run_id:
            self._raise_validation("Run current_stage_run_id must match the stage.")
        if stage.run_id != run.run_id:
            self._raise_validation("StageRun does not belong to the run.")
        return control_session, run, stage

    def _assert_can_pause(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
    ) -> None:
        if run.status not in {
            RunStatus.RUNNING,
            RunStatus.WAITING_CLARIFICATION,
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_TOOL_CONFIRMATION,
        }:
            self._raise_validation("Run cannot be paused from its current status.")
        if session.status is not RunStateMachine.project_session_status(run.status):
            self._raise_validation("Session status must match run status before pause.")

    def _assert_can_resume(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
    ) -> None:
        if run.status is not RunStatus.PAUSED or session.status is not SessionStatus.PAUSED:
            self._raise_validation("Run can be resumed only when it is paused.")

    def _persist_recovery_checkpoint(
        self,
        *,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        checkpoint: CheckpointRef | None,
        saved_at: datetime,
    ) -> StageArtifactModel:
        if checkpoint is None:
            raise RunLifecycleServiceError(
                "pause checkpoint is required before persisting recovery state.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run.run_id,
            )
        artifact = StageArtifactModel(
            artifact_id=f"artifact-recovery-{uuid4().hex}",
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            artifact_type="recovery_checkpoint",
            payload_ref=checkpoint.checkpoint_id,
            process={
                "checkpoint": checkpoint.model_dump(mode="json"),
                "graph_thread_ref": run.graph_thread_ref,
                "workspace_snapshot_ref": checkpoint.workspace_snapshot_ref,
                "run_status_before_pause": run.status.value,
                "session_status_before_pause": control_session.status.value,
                "stage_status_before_pause": stage.status.value,
            },
            metrics={},
            created_at=saved_at,
        )
        self._runtime_session.add(artifact)
        return artifact

    def _latest_recovery_checkpoint(self, *, run_id: str) -> StageArtifactModel:
        artifact = (
            self._runtime_session.execute(
                select(StageArtifactModel)
                .where(
                    StageArtifactModel.run_id == run_id,
                    StageArtifactModel.artifact_type == "recovery_checkpoint",
                )
                .order_by(
                    StageArtifactModel.created_at.desc(),
                    StageArtifactModel.artifact_id.desc(),
                )
                .execution_options(populate_existing=True)
            )
            .scalars()
            .first()
        )
        if artifact is None:
            raise RunLifecycleServiceError(
                "recovery checkpoint was not found.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run_id,
            )
        return artifact

    def _validate_recovery_checkpoint(
        self,
        *,
        artifact: StageArtifactModel,
        checkpoint: CheckpointRef,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        process = artifact.process
        if artifact.artifact_type != "recovery_checkpoint":
            self._raise_checkpoint_error(run.run_id)
        if artifact.run_id != run.run_id or artifact.stage_run_id != stage.stage_run_id:
            self._raise_checkpoint_error(run.run_id)
        if artifact.payload_ref != checkpoint.checkpoint_id:
            self._raise_checkpoint_error(run.run_id)
        if process.get("graph_thread_ref") != run.graph_thread_ref:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.run_id != run.run_id:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.thread_id != run.graph_thread_ref:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.stage_run_id != stage.stage_run_id:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.stage_type is not stage.stage_type:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.purpose.value != "pause":
            self._raise_checkpoint_error(run.run_id)
        pre_pause_status = RunStatus(process.get("run_status_before_pause"))
        if pre_pause_status not in {
            RunStatus.RUNNING,
            RunStatus.WAITING_CLARIFICATION,
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_TOOL_CONFIRMATION,
        }:
            self._raise_checkpoint_error(run.run_id)
        if process.get("session_status_before_pause") != (
            RunStateMachine.project_session_status(pre_pause_status).value
        ):
            self._raise_checkpoint_error(run.run_id)
        if process.get("stage_status_before_pause") != stage.status.value:
            self._raise_checkpoint_error(run.run_id)

    @staticmethod
    def _raise_checkpoint_error(run_id: str) -> None:
        raise RunLifecycleServiceError(
            "recovery checkpoint metadata is invalid for this run.",
            error_code=ErrorCode.INTERNAL_ERROR,
            status_code=500,
            detail_ref=run_id,
        )

    def _append_run_status_event(
        self,
        domain_event_type: DomainEventType,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        self._require_events().append(
            domain_event_type,
            payload={
                "session_id": session.session_id,
                "status": session.status.value,
                "current_run_id": run.run_id,
                "current_stage_type": session.latest_stage_type.value
                if session.latest_stage_type is not None
                else None,
            },
            trace_context=trace_context,
            occurred_at=occurred_at,
        )

    def _refresh_pending_wait_entry_for_pause(
        self,
        *,
        pre_pause_status: RunStatus,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        if pre_pause_status is RunStatus.WAITING_APPROVAL:
            projection = self._latest_approval_request_projection(run_id=run.run_id)
            if projection is None:
                return
            paused = projection.model_copy(
                update={
                    "occurred_at": occurred_at,
                    "is_actionable": False,
                    "disabled_reason": (
                        "Current run is paused; resume it to continue approval."
                    ),
                }
            )
            self._require_events().append(
                DomainEventType.APPROVAL_REQUESTED,
                payload={"approval_request": paused.model_dump(mode="json")},
                trace_context=trace_context,
                occurred_at=occurred_at,
            )
        if pre_pause_status is RunStatus.WAITING_TOOL_CONFIRMATION:
            projection = self._latest_tool_confirmation_projection(run_id=run.run_id)
            if projection is None:
                return
            paused = projection.model_copy(
                update={
                    "occurred_at": occurred_at,
                    "is_actionable": False,
                    "disabled_reason": (
                        "Current run is paused; resume it to continue tool confirmation."
                    ),
                }
            )
            self._require_events().append(
                DomainEventType.TOOL_CONFIRMATION_REQUESTED,
                payload={"tool_confirmation": paused.model_dump(mode="json")},
                trace_context=trace_context,
                occurred_at=occurred_at,
            )

    def _refresh_pending_wait_entry_for_resume(
        self,
        *,
        pre_pause_status: RunStatus,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        if pre_pause_status is RunStatus.WAITING_APPROVAL:
            projection = self._latest_approval_request_projection(run_id=run.run_id)
            if projection is None:
                return
            resumed = projection.model_copy(
                update={
                    "occurred_at": occurred_at,
                    "is_actionable": True,
                    "disabled_reason": None,
                }
            )
            self._require_events().append(
                DomainEventType.APPROVAL_REQUESTED,
                payload={"approval_request": resumed.model_dump(mode="json")},
                trace_context=trace_context,
                occurred_at=occurred_at,
            )
        if pre_pause_status is RunStatus.WAITING_TOOL_CONFIRMATION:
            projection = self._latest_tool_confirmation_projection(run_id=run.run_id)
            if projection is None:
                return
            resumed = projection.model_copy(
                update={
                    "occurred_at": occurred_at,
                    "is_actionable": True,
                    "disabled_reason": None,
                }
            )
            self._require_events().append(
                DomainEventType.TOOL_CONFIRMATION_REQUESTED,
                payload={"tool_confirmation": resumed.model_dump(mode="json")},
                trace_context=trace_context,
                occurred_at=occurred_at,
            )

    def _latest_approval_request_projection(
        self,
        *,
        run_id: str,
    ) -> ApprovalRequestFeedEntry | None:
        pending_ids = {
            approval.approval_id
            for approval in self._runtime_session.execute(
                select(ApprovalRequestModel).where(
                    ApprovalRequestModel.run_id == run_id,
                    ApprovalRequestModel.status == ApprovalStatus.PENDING,
                )
            )
            .scalars()
            .all()
        }
        if not pending_ids:
            return None
        events = (
            self._require_event_session()
            .query(DomainEventModel)
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
            if isinstance(payload, dict) and payload.get("approval_id") in pending_ids:
                return ApprovalRequestFeedEntry.model_validate(payload)
        return None

    def _latest_tool_confirmation_projection(
        self,
        *,
        run_id: str,
    ) -> ToolConfirmationFeedEntry | None:
        pending_ids = {
            request.tool_confirmation_id
            for request in self._runtime_session.execute(
                select(ToolConfirmationRequestModel).where(
                    ToolConfirmationRequestModel.run_id == run_id,
                    ToolConfirmationRequestModel.status == ToolConfirmationStatus.PENDING,
                )
            )
            .scalars()
            .all()
        }
        if not pending_ids:
            return None
        events = (
            self._require_event_session()
            .query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == run_id,
                DomainEventModel.event_type == SseEventType.TOOL_CONFIRMATION_REQUESTED,
            )
            .order_by(
                DomainEventModel.sequence_index.desc(),
                DomainEventModel.event_id.desc(),
            )
            .all()
        )
        for event in events:
            payload = event.payload.get("tool_confirmation")
            if (
                isinstance(payload, dict)
                and payload.get("tool_confirmation_id") in pending_ids
            ):
                return ToolConfirmationFeedEntry.model_validate(payload)
        return None

    def _build_thread_ref(
        self,
        *,
        run: PipelineRunModel,
        stage: StageRunModel,
        paused: bool = False,
    ) -> GraphThreadRef:
        return GraphThreadRef(
            thread_id=run.graph_thread_ref,
            run_id=run.run_id,
            status=GraphThreadStatus.PAUSED if paused else GraphThreadStatus(run.status.value),
            current_stage_run_id=stage.stage_run_id,
            current_stage_type=stage.stage_type,
        )

    def _command_trace(
        self,
        trace_context: TraceContext,
        *,
        span_id: str,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> TraceContext:
        return trace_context.child_span(
            span_id=span_id,
            created_at=self._now(),
            session_id=session.session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            graph_thread_id=run.graph_thread_ref,
        )

    def _record_rejected_command(
        self,
        *,
        action: str,
        message: str,
        actor_id: str,
        run: PipelineRunModel,
        stage: StageRunModel,
        reason: str,
        trace_context: TraceContext,
        started_at: datetime | None = None,
    ) -> None:
        recorded_at = self._now()
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            action=action,
            target_type="run",
            target_id=run.run_id,
            reason=reason,
            metadata={
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id,
                "result_status": "rejected",
                "rejected_reason": reason,
            },
            trace_context=trace_context,
            created_at=recorded_at,
        )
        self._record_run_log(
            payload_type="runtime_command_rejected",
            message=message,
            metadata={
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id,
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
        action: str,
        message: str,
        actor_id: str,
        run: PipelineRunModel,
        stage: StageRunModel,
        reason: str,
        trace_context: TraceContext,
        started_at: datetime | None = None,
    ) -> None:
        recorded_at = self._now()
        try:
            self._audit_service.record_failed_command(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action=action,
                target_type="run",
                target_id=run.run_id,
                reason=reason,
                metadata={
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "result_status": "failed",
                },
                trace_context=trace_context,
                created_at=recorded_at,
            )
        except Exception:
            pass
        self._record_run_log(
            payload_type="runtime_command_failed",
            message=message,
            metadata={
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id,
                "reason": reason,
                "result_status": "failed",
            },
            trace_context=trace_context,
            created_at=recorded_at,
            level=LogLevel.ERROR,
            error_code=ErrorCode.INTERNAL_ERROR.value,
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
                    source="services.runs",
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
            pass

    @staticmethod
    def _duration_ms(started_at: datetime | None, ended_at: datetime) -> int | None:
        if started_at is None:
            return None
        return max(0, int((ended_at - started_at).total_seconds() * 1000))

    def _commit_all(self) -> None:
        self._runtime_session.commit()
        self._require_control_session().commit()
        self._require_event_session().commit()

    def _rollback_all(self) -> None:
        self._runtime_session.rollback()
        if self._control_session is not None:
            self._control_session.rollback()
        if self._event_session is not None:
            self._event_session.rollback()

    def _require_event_session(self) -> Session:
        if self._event_session is None:
            raise RunLifecycleServiceError(
                "event_session is required for run lifecycle events.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
            )
        return self._event_session

    def _require_events(self) -> EventStore:
        if self._events is None:
            raise RunLifecycleServiceError(
                "event_session is required for run lifecycle events.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
            )
        return self._events

    def _require_runtime_orchestration(self) -> RuntimeOrchestrationService:
        if self._runtime_orchestration is None:
            raise RunLifecycleServiceError(
                "runtime_orchestration is required for pause/resume commands.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
            )
        return self._runtime_orchestration

    @staticmethod
    def _raise_validation(message: str) -> None:
        raise RunLifecycleServiceError(
            message,
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=409,
        )


class _NoopAuditService:
    def require_audit_record(self, **kwargs: Any) -> object:
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        return object()


class _NoopRunLogWriter:
    def write_run_log(self, record: LogRecordInput) -> object:
        return object()


__all__ = [
    "RunCommandResult",
    "RunLifecycleService",
    "RunLifecycleServiceError",
]
