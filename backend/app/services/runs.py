from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import PipelineRunModel, StageRunModel
from backend.app.domain.enums import RunStatus, SessionStatus, StageStatus, StageType
from backend.app.domain.template_snapshot import TemplateSnapshot


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
