from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import PipelineRunModel, StageRunModel
from backend.app.domain.enums import RunStatus, SessionStatus, StageStatus, StageType
from backend.app.domain.provider_call_policy_snapshot import ProviderCallPolicySnapshot
from backend.app.domain.provider_snapshot import ModelBindingSnapshot, ProviderSnapshot
from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshot
from backend.app.domain.template_snapshot import TemplateSnapshot
from backend.app.repositories.runtime import RuntimeSnapshotRepository


class RunLifecycleServiceError(ValueError):
    pass


class RunLifecycleService:
    def __init__(
        self,
        session: Session,
        runtime_session: Session | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._control_session = session if runtime_session is not None else None
        self._runtime_session = runtime_session or session
        self._now = now or (lambda: datetime.now(UTC))

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


__all__ = [
    "RunLifecycleService",
    "RunLifecycleServiceError",
]
