from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import PipelineTemplateModel, ProjectModel, SessionModel
from backend.app.domain.enums import SessionStatus
from backend.app.domain.state_machine import InvalidRunStateTransition
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.redaction import RedactionPolicy
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.feed import MessageFeedEntry
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.services.clarifications import (
    ClarificationAnswerResult,
    ClarificationService,
)
from backend.app.services.runs import (
    RunLifecycleService,
    RunLifecycleServiceError,
    RunPromptValidationError,
)
from backend.app.services.runtime_settings import (
    PlatformRuntimeSettingsService,
    RuntimeSettingsServiceError,
)
from backend.app.services.templates import TemplateService, TemplateServiceError


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


@dataclass(frozen=True)
class SessionStartRunResult:
    session: SessionModel
    run: Any
    stage: Any
    message_item: MessageFeedEntry


class SessionService:
    def __init__(
        self,
        session: Session,
        *,
        audit_service: Any,
        runtime_session: Session | None = None,
        event_session: Session | None = None,
        graph_session: Session | None = None,
        log_writer: Any | None = None,
        environment_settings: Any | None = None,
        prompt_validation_service: Any | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._audit_service = audit_service
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._graph_session = graph_session
        self._log_writer = log_writer
        self._environment_settings = environment_settings
        self._prompt_validation_service = prompt_validation_service
        self._redaction_policy = redaction_policy or RedactionPolicy()
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

    def append_clarification_reply(
        self,
        *,
        session_id: str,
        content: str,
        clarification_service: ClarificationService,
        trace_context: TraceContext,
    ) -> ClarificationAnswerResult:
        return clarification_service.answer_clarification(
            session_id=session_id,
            answer=content,
            trace_context=trace_context,
        )

    def start_run_from_new_requirement(
        self,
        *,
        session_id: str,
        content: str,
        trace_context: TraceContext,
    ) -> SessionStartRunResult:
        model = self.get_session(session_id, trace_context=trace_context)
        if model is None:
            raise SessionServiceError(
                ErrorCode.NOT_FOUND,
                SESSION_NOT_FOUND_MESSAGE,
                404,
            )
        if (
            self._runtime_session is None
            or self._event_session is None
            or self._graph_session is None
        ):
            raise SessionServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Run startup dependencies are unavailable.",
                500,
            )
        template = self._session.get(PipelineTemplateModel, model.selected_template_id)
        if template is None:
            raise SessionServiceError(
                ErrorCode.VALIDATION_ERROR,
                TEMPLATE_NOT_FOUND_MESSAGE,
                422,
            )
        try:
            result = RunLifecycleService(
                control_session=self._session,
                runtime_session=self._runtime_session,
                event_session=self._event_session,
                graph_session=self._graph_session,
                audit_service=self._audit_service,
                log_writer=self._run_log_writer(),
                prompt_validation_service=self._run_prompt_validation_service(),
                credential_env_prefixes=self._credential_env_prefixes(),
                redaction_policy=self._redaction_policy,
                now=self._now,
            ).start_first_run(
                session=model,
                template=template,
                content=content,
                trace_context=trace_context,
                runtime_settings_service=self._runtime_settings_service(),
            )
        except RunLifecycleServiceError as exc:
            raise SessionServiceError(
                exc.error_code,
                str(exc),
                exc.status_code,
            ) from exc
        except RuntimeSettingsServiceError as exc:
            raise SessionServiceError(
                exc.error_code,
                exc.message,
                exc.status_code,
            ) from exc
        except InvalidRunStateTransition as exc:
            raise SessionServiceError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                409,
            ) from exc
        return SessionStartRunResult(
            session=result.session,
            run=result.run,
            stage=result.stage,
            message_item=result.message_item,
        )

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

    def _runtime_settings_service(self) -> PlatformRuntimeSettingsService:
        if self._runtime_session is None:
            raise SessionServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Run startup dependencies are unavailable.",
                500,
            )
        return PlatformRuntimeSettingsService(
            self._session,
            audit_service=self._audit_service,
            log_writer=self._settings_log_writer(),
            redaction_policy=self._redaction_policy,
            now=self._now,
        )

    def _run_log_writer(self):
        if self._log_writer is not None:
            return self._log_writer
        return _NoopSessionLogWriter()

    def _settings_log_writer(self):
        if self._log_writer is not None:
            return self._log_writer
        if self._environment_settings is None:
            return _NoopSettingsLogWriter()
        return JsonlLogWriter(
            RuntimeDataSettings.from_environment_settings(self._environment_settings)
        )

    def _credential_env_prefixes(self) -> tuple[str, ...] | None:
        if self._environment_settings is None:
            return None
        return tuple(self._environment_settings.credential_env_prefixes)

    def _run_prompt_validation_service(self):
        if self._prompt_validation_service is not None:
            return self._prompt_validation_service
        return _TemplatePromptValidationAdapter(self._templates)


class _NoopSessionLogWriter:
    def write_run_log(self, record) -> object:  # noqa: ANN001
        return object()


class _NoopSettingsLogWriter:
    def write(self, record) -> object:  # noqa: ANN001
        return object()


class _TemplatePromptValidationAdapter:
    def __init__(self, templates: TemplateService) -> None:
        self._templates = templates

    def validate_run_prompt_snapshots(
        self,
        *,
        template_snapshot,
        trace_context,  # noqa: ANN001
    ) -> None:
        bindings = [
            {
                "stage_type": binding.stage_type.value,
                "role_id": binding.role_id,
                "system_prompt": binding.system_prompt,
                "provider_id": binding.provider_id,
            }
            for binding in template_snapshot.stage_role_bindings
        ]
        try:
            self._templates.validate_template_prompts_before_save(bindings)
        except TemplateServiceError as exc:
            raise RunPromptValidationError(
                exc.message,
                error_code=exc.error_code,
            ) from exc


__all__ = [
    "DEFAULT_SESSION_DISPLAY_NAME",
    "PROJECT_NOT_FOUND_MESSAGE",
    "SESSION_NOT_FOUND_MESSAGE",
    "TEMPLATE_NOT_FOUND_MESSAGE",
    "TEMPLATE_UPDATE_BLOCKED_MESSAGE",
    "SessionService",
    "SessionStartRunResult",
    "SessionServiceError",
]
