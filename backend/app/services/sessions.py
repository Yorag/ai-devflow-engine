from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import PipelineTemplateModel, ProjectModel, SessionModel
from backend.app.domain.enums import SessionStatus
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.services.templates import TemplateService


DEFAULT_SESSION_DISPLAY_NAME = "Untitled requirement"
PROJECT_NOT_FOUND_MESSAGE = "Project was not found."
SESSION_NOT_FOUND_MESSAGE = "Session was not found."
TEMPLATE_NOT_FOUND_MESSAGE = "Pipeline template was not found."
TEMPLATE_UPDATE_BLOCKED_MESSAGE = (
    "Only draft Sessions without a run can change templates."
)


class SessionServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int = 422,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class SessionService:
    def __init__(
        self,
        session: Session,
        *,
        audit_service: Any,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._audit_service = audit_service
        self._now = now or (lambda: datetime.now(UTC))
        self._templates = TemplateService(
            session,
            audit_service=audit_service,
            now=self._now,
        )

    def create_session(
        self,
        *,
        project_id: str,
        trace_context: TraceContext,
    ) -> SessionModel:
        project = self._visible_project(project_id)
        if project is None:
            raise SessionServiceError(
                ErrorCode.NOT_FOUND,
                PROJECT_NOT_FOUND_MESSAGE,
                404,
            )

        template = self._templates.get_default_template(trace_context=trace_context)
        timestamp = self._now()
        model = SessionModel(
            session_id=f"session-{uuid4().hex}",
            project_id=project.project_id,
            display_name=DEFAULT_SESSION_DISPLAY_NAME,
            status=SessionStatus.DRAFT,
            selected_template_id=template.template_id,
            current_run_id=None,
            latest_stage_type=None,
            is_visible=True,
            visibility_removed_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._session.add(model)
        self._session.flush()
        try:
            self._record_success(
                action="session.create",
                model=model,
                trace_context=trace_context,
                metadata={
                    "session_id": model.session_id,
                    "project_id": model.project_id,
                    "display_name": model.display_name,
                    "selected_template_id": model.selected_template_id,
                    "status": model.status.value,
                    "current_run_id": model.current_run_id,
                },
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return model

    def list_project_sessions(
        self,
        *,
        project_id: str,
        trace_context: TraceContext,
    ) -> list[SessionModel]:
        if self._visible_project(project_id) is None:
            raise SessionServiceError(
                ErrorCode.NOT_FOUND,
                PROJECT_NOT_FOUND_MESSAGE,
                404,
            )
        return (
            self._session.query(SessionModel)
            .filter(
                SessionModel.project_id == project_id,
                SessionModel.is_visible.is_(True),
            )
            .order_by(
                SessionModel.updated_at.desc(),
                SessionModel.created_at.desc(),
                SessionModel.session_id.asc(),
            )
            .all()
        )

    def get_session(
        self,
        session_id: str,
        *,
        trace_context: TraceContext,
    ) -> SessionModel | None:
        return (
            self._session.query(SessionModel)
            .filter(
                SessionModel.session_id == session_id,
                SessionModel.is_visible.is_(True),
            )
            .one_or_none()
        )

    def rename_session(
        self,
        *,
        session_id: str,
        display_name: str,
        trace_context: TraceContext,
    ) -> SessionModel:
        model = self.get_session(session_id, trace_context=trace_context)
        if model is None:
            raise SessionServiceError(
                ErrorCode.NOT_FOUND,
                SESSION_NOT_FOUND_MESSAGE,
                404,
            )

        old_display_name = model.display_name
        model.display_name = display_name
        model.updated_at = self._now()
        self._session.add(model)
        self._session.flush()
        try:
            self._record_success(
                action="session.rename",
                model=model,
                trace_context=trace_context,
                metadata={
                    "session_id": model.session_id,
                    "project_id": model.project_id,
                    "old_display_name": old_display_name,
                    "display_name": model.display_name,
                    "status": model.status.value,
                    "current_run_id": model.current_run_id,
                },
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return model

    def update_selected_template(
        self,
        *,
        session_id: str,
        template_id: str,
        trace_context: TraceContext,
    ) -> SessionModel:
        model = self.get_session(session_id, trace_context=trace_context)
        if model is None:
            self._record_template_rejection(
                session_id=session_id,
                reason=SESSION_NOT_FOUND_MESSAGE,
                trace_context=trace_context,
                metadata={
                    "session_id": session_id,
                    "template_id": template_id,
                },
            )
            raise SessionServiceError(
                ErrorCode.NOT_FOUND,
                SESSION_NOT_FOUND_MESSAGE,
                404,
            )

        if model.status is not SessionStatus.DRAFT or model.current_run_id is not None:
            self._record_template_rejection(
                session_id=session_id,
                reason=TEMPLATE_UPDATE_BLOCKED_MESSAGE,
                trace_context=trace_context,
                metadata={
                    "session_id": model.session_id,
                    "project_id": model.project_id,
                    "template_id": template_id,
                    "status": model.status.value,
                    "current_run_id": model.current_run_id,
                },
            )
            raise SessionServiceError(
                ErrorCode.VALIDATION_ERROR,
                TEMPLATE_UPDATE_BLOCKED_MESSAGE,
                409,
            )

        template = self._session.get(PipelineTemplateModel, template_id)
        if template is None:
            self._record_template_rejection(
                session_id=session_id,
                reason=TEMPLATE_NOT_FOUND_MESSAGE,
                trace_context=trace_context,
                metadata={
                    "session_id": model.session_id,
                    "project_id": model.project_id,
                    "template_id": template_id,
                },
            )
            raise SessionServiceError(
                ErrorCode.VALIDATION_ERROR,
                TEMPLATE_NOT_FOUND_MESSAGE,
                422,
            )

        old_template_id = model.selected_template_id
        model.selected_template_id = template.template_id
        model.updated_at = self._now()
        self._session.add(model)
        self._session.flush()
        try:
            self._record_success(
                action="session.template.update",
                model=model,
                trace_context=trace_context,
                metadata={
                    "session_id": model.session_id,
                    "project_id": model.project_id,
                    "old_template_id": old_template_id,
                    "new_template_id": model.selected_template_id,
                    "status": model.status.value,
                    "current_run_id": model.current_run_id,
                },
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return model

    def _visible_project(self, project_id: str) -> ProjectModel | None:
        return (
            self._session.query(ProjectModel)
            .filter(
                ProjectModel.project_id == project_id,
                ProjectModel.is_visible.is_(True),
            )
            .one_or_none()
        )

    def _record_success(
        self,
        *,
        action: str,
        model: SessionModel,
        trace_context: TraceContext,
        metadata: dict[str, Any],
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action=action,
            target_type="session",
            target_id=model.session_id,
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata=metadata,
            trace_context=trace_context,
        )

    def _record_template_rejection(
        self,
        *,
        session_id: str,
        reason: str,
        trace_context: TraceContext,
        metadata: dict[str, Any],
    ) -> None:
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action="session.template.update.rejected",
            target_type="session",
            target_id=session_id,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
        )


__all__ = [
    "DEFAULT_SESSION_DISPLAY_NAME",
    "PROJECT_NOT_FOUND_MESSAGE",
    "SESSION_NOT_FOUND_MESSAGE",
    "TEMPLATE_NOT_FOUND_MESSAGE",
    "TEMPLATE_UPDATE_BLOCKED_MESSAGE",
    "SessionService",
    "SessionServiceError",
]
