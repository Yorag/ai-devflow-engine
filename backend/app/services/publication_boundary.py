from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import SessionModel, StartupPublicationModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.graph import GraphDefinitionModel, GraphThreadModel
from backend.app.db.models.runtime import (
    ModelBindingSnapshotModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    ProviderSnapshotModel,
    RuntimeLimitSnapshotModel,
    StageRunModel,
)
from backend.app.domain.enums import SessionStatus, StageType
from backend.app.domain.publication_boundary import (
    PUBLICATION_STATE_ABORTED,
    PUBLICATION_STATE_PENDING,
    PUBLICATION_STATE_PUBLISHED,
    PublishedStartupVisibility,
)
from backend.app.domain.trace_context import TraceContext


class PublicationBoundaryServiceError(RuntimeError):
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


class PublicationBoundaryService:
    def __init__(
        self,
        *,
        control_session: Session,
        runtime_session: Session,
        graph_session: Session | None = None,
        event_session: Session | None = None,
        audit_service=None,
        log_writer=None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        del audit_service, log_writer
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._graph_session = graph_session
        self._event_session = event_session
        self._now = now or (lambda: datetime.now(UTC))

    def begin_startup_publication(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        trace_context: TraceContext,
    ) -> StartupPublicationModel:
        del trace_context
        session = self._control_session.get(SessionModel, session_id)
        if session is None or not session.is_visible:
            raise PublicationBoundaryServiceError(
                ErrorCode.NOT_FOUND,
                "Session was not found.",
                404,
            )
        if session.status is not SessionStatus.DRAFT or session.current_run_id is not None:
            raise PublicationBoundaryServiceError(
                ErrorCode.VALIDATION_ERROR,
                "First run startup claim could not be acquired.",
                409,
            )

        publication = StartupPublicationModel(
            publication_id=f"startup-publication-{uuid4().hex}",
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            publication_state=PUBLICATION_STATE_PENDING,
            pending_session_id=session_id,
            published_at=None,
            aborted_at=None,
            abort_reason=None,
            created_at=self._now(),
            updated_at=self._now(),
        )
        self._control_session.add(publication)
        try:
            self._control_session.commit()
        except IntegrityError as exc:
            self._control_session.rollback()
            raise PublicationBoundaryServiceError(
                ErrorCode.VALIDATION_ERROR,
                "First run startup claim could not be acquired.",
                409,
            ) from exc
        except SQLAlchemyError as exc:
            self._control_session.rollback()
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup publication state is unavailable.",
                500,
            ) from exc
        return publication

    def publish_startup_visibility(
        self,
        *,
        publication_id: str,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        trace_context: TraceContext,
        published_at: datetime,
    ) -> PublishedStartupVisibility:
        del trace_context
        publication = self._require_publication(
            publication_id=publication_id,
            session_id=session_id,
            run_id=run_id,
        )
        if publication.publication_state != PUBLICATION_STATE_PENDING:
            raise PublicationBoundaryServiceError(
                ErrorCode.VALIDATION_ERROR,
                "Startup publication is not pending.",
                409,
            )

        self._assert_startup_product_set(run_id=run_id, stage_run_id=stage_run_id)

        session = self._control_session.get(SessionModel, session_id)
        if session is None or not session.is_visible:
            raise PublicationBoundaryServiceError(
                ErrorCode.NOT_FOUND,
                "Session was not found.",
                404,
            )

        session.status = SessionStatus.RUNNING
        session.current_run_id = run_id
        session.latest_stage_type = StageType.REQUIREMENT_ANALYSIS
        session.updated_at = published_at
        publication.publication_state = PUBLICATION_STATE_PUBLISHED
        publication.pending_session_id = None
        publication.published_at = published_at
        publication.updated_at = published_at
        self._control_session.add(session)
        self._control_session.add(publication)
        try:
            self._control_session.commit()
        except SQLAlchemyError as exc:
            self._control_session.rollback()
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup publication state is unavailable.",
                500,
            ) from exc

        return PublishedStartupVisibility(
            publication_id=publication.publication_id,
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
        )

    def abort_startup_publication(
        self,
        *,
        publication_id: str,
        session_id: str,
        run_id: str,
        reason: str,
        trace_context: TraceContext,
        aborted_at: datetime,
    ) -> None:
        del trace_context
        self._rollback_all()
        self._delete_staged_runtime_rows(run_id=run_id)
        self._delete_staged_graph_rows(run_id=run_id)
        self._delete_staged_event_rows(run_id=run_id)
        self._commit_cleanup()

        self._control_session.rollback()
        session = self._control_session.get(SessionModel, session_id)
        if session is not None and session.current_run_id == run_id:
            session.status = SessionStatus.DRAFT
            session.current_run_id = None
            session.latest_stage_type = None
            session.updated_at = aborted_at
            self._control_session.add(session)

        publication = self._control_session.get(StartupPublicationModel, publication_id)
        if publication is None:
            raise PublicationBoundaryServiceError(
                ErrorCode.NOT_FOUND,
                "Startup publication was not found.",
                404,
            )
        publication.publication_state = PUBLICATION_STATE_ABORTED
        publication.pending_session_id = None
        publication.aborted_at = aborted_at
        publication.abort_reason = reason
        publication.updated_at = aborted_at
        self._control_session.add(publication)
        try:
            self._control_session.commit()
        except SQLAlchemyError as exc:
            self._control_session.rollback()
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup publication cleanup is unavailable.",
                500,
            ) from exc

    def visible_run_ids_for_session(
        self,
        *,
        session_id: str,
    ) -> set[str]:
        all_run_ids = set(
            self._runtime_session.execute(
                select(PipelineRunModel.run_id).where(
                    PipelineRunModel.session_id == session_id
                )
            ).scalars()
        )
        return all_run_ids - self.hidden_run_ids_for_session(session_id=session_id)

    def hidden_run_ids_for_session(
        self,
        *,
        session_id: str,
    ) -> set[str]:
        statement = select(StartupPublicationModel.run_id).where(
            StartupPublicationModel.session_id == session_id,
            StartupPublicationModel.publication_state != PUBLICATION_STATE_PUBLISHED,
        )
        return set(self._control_session.execute(statement).scalars())

    def is_run_hidden(
        self,
        *,
        session_id: str,
        run_id: str | None,
    ) -> bool:
        if run_id is None:
            return False
        return run_id in self.hidden_run_ids_for_session(session_id=session_id)

    def assert_run_visible(
        self,
        *,
        run_id: str,
    ) -> str:
        publication = self._control_session.execute(
            select(StartupPublicationModel).where(StartupPublicationModel.run_id == run_id)
        ).scalar_one_or_none()
        if publication is not None and publication.publication_state != PUBLICATION_STATE_PUBLISHED:
            raise PublicationBoundaryServiceError(
                ErrorCode.NOT_FOUND,
                "Run timeline was not found.",
                404,
            )

        run = self._runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise PublicationBoundaryServiceError(
                ErrorCode.NOT_FOUND,
                "Run timeline was not found.",
                404,
            )
        return run.session_id

    def _require_publication(
        self,
        *,
        publication_id: str,
        session_id: str,
        run_id: str,
    ) -> StartupPublicationModel:
        publication = self._control_session.get(StartupPublicationModel, publication_id)
        if (
            publication is None
            or publication.session_id != session_id
            or publication.run_id != run_id
        ):
            raise PublicationBoundaryServiceError(
                ErrorCode.NOT_FOUND,
                "Startup publication was not found.",
                404,
            )
        return publication

    def _assert_startup_product_set(
        self,
        *,
        run_id: str,
        stage_run_id: str,
    ) -> None:
        run = self._runtime_session.get(PipelineRunModel, run_id)
        stage = self._runtime_session.get(StageRunModel, stage_run_id)
        if run is None or stage is None or stage.run_id != run_id:
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup product set is incomplete.",
                500,
            )
        if self._graph_session is None or self._event_session is None:
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup publication dependencies are unavailable.",
                500,
            )
        if (
            self._graph_session.execute(
                select(GraphDefinitionModel.graph_definition_id).where(
                    GraphDefinitionModel.run_id == run_id
                )
            ).scalar_one_or_none()
            is None
        ):
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup product set is incomplete.",
                500,
            )
        if (
            self._graph_session.execute(
                select(GraphThreadModel.graph_thread_id).where(
                    GraphThreadModel.run_id == run_id
                )
            ).scalar_one_or_none()
            is None
        ):
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup product set is incomplete.",
                500,
            )
        if (
            self._event_session.execute(
                select(DomainEventModel.event_id).where(DomainEventModel.run_id == run_id)
            ).scalars().first()
            is None
        ):
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup product set is incomplete.",
                500,
            )

    def _rollback_all(self) -> None:
        self._runtime_session.rollback()
        self._control_session.rollback()
        if self._graph_session is not None:
            self._graph_session.rollback()
        if self._event_session is not None:
            self._event_session.rollback()

    def _delete_staged_runtime_rows(self, *, run_id: str) -> None:
        self._runtime_session.execute(
            delete(ModelBindingSnapshotModel).where(ModelBindingSnapshotModel.run_id == run_id)
        )
        self._runtime_session.execute(
            delete(ProviderSnapshotModel).where(ProviderSnapshotModel.run_id == run_id)
        )
        self._runtime_session.execute(
            delete(StageRunModel).where(StageRunModel.run_id == run_id)
        )
        self._runtime_session.execute(
            delete(PipelineRunModel).where(PipelineRunModel.run_id == run_id)
        )
        self._runtime_session.execute(
            delete(RuntimeLimitSnapshotModel).where(
                RuntimeLimitSnapshotModel.run_id == run_id
            )
        )
        self._runtime_session.execute(
            delete(ProviderCallPolicySnapshotModel).where(
                ProviderCallPolicySnapshotModel.run_id == run_id
            )
        )

    def _delete_staged_graph_rows(self, *, run_id: str) -> None:
        if self._graph_session is None:
            return
        self._graph_session.execute(
            delete(GraphThreadModel).where(GraphThreadModel.run_id == run_id)
        )
        self._graph_session.execute(
            delete(GraphDefinitionModel).where(GraphDefinitionModel.run_id == run_id)
        )

    def _delete_staged_event_rows(self, *, run_id: str) -> None:
        if self._event_session is None:
            return
        self._event_session.execute(
            delete(DomainEventModel).where(DomainEventModel.run_id == run_id)
        )

    def _commit_cleanup(self) -> None:
        try:
            self._runtime_session.commit()
            if self._graph_session is not None:
                self._graph_session.commit()
            if self._event_session is not None:
                self._event_session.commit()
        except SQLAlchemyError as exc:
            self._rollback_all()
            raise PublicationBoundaryServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Startup publication cleanup is unavailable.",
                500,
            ) from exc


__all__ = [
    "PublicationBoundaryService",
    "PublicationBoundaryServiceError",
]
