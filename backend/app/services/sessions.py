from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import exists, update
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import (
    PipelineTemplateModel,
    ProjectModel,
    SessionModel,
    StartupPublicationModel,
)
from backend.app.db.models.runtime import PipelineRunModel
from backend.app.domain.enums import SessionStatus
from backend.app.domain.publication_boundary import PUBLICATION_STATE_PENDING
from backend.app.domain.state_machine import InvalidRunStateTransition, RunStateMachine
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.redaction import RedactionPolicy
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.runtime.prompt_validation import (
    PromptValidationError,
    PromptValidationService,
)
from backend.app.schemas.feed import MessageFeedEntry
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.session import SessionDeleteResult
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
SESSION_AUTO_TITLE_MAX_LENGTH = 32
PROJECT_NOT_FOUND_MESSAGE = "Project was not found."
SESSION_NOT_FOUND_MESSAGE = "Session was not found."
TEMPLATE_NOT_FOUND_MESSAGE = "Pipeline template was not found."
TEMPLATE_UPDATE_BLOCKED_MESSAGE = (
    "Only draft Sessions without a run can change templates."
)
SESSION_DELETE_BLOCKED_MESSAGE = "Session has an active run."
SESSION_DELETE_SUCCESS_MESSAGE = "Session removed from regular product history."
SESSION_ALREADY_REMOVED_MESSAGE = "Session was already removed from product history."
SESSION_RUNTIME_UNAVAILABLE_MESSAGE = (
    "Runtime session is required to verify current run state before deleting a Session."
)
SESSION_DELETE_BLOCKED_ERROR_CODE = "session_active_run_blocks_delete"
SESSION_DELETE_ACTION = "session.delete"
SESSION_DELETE_REJECTED_ACTION = "session.delete.rejected"


def session_auto_title_from_requirement(content: str) -> str:
    normalized = " ".join(content.split())
    if not normalized:
        return DEFAULT_SESSION_DISPLAY_NAME
    if len(normalized) <= SESSION_AUTO_TITLE_MAX_LENGTH:
        return normalized
    return f"{normalized[: SESSION_AUTO_TITLE_MAX_LENGTH - 3].rstrip()}..."


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

    def list_visible_sessions(
        self,
        *,
        project_id: str,
        trace_context: TraceContext,
    ) -> list[SessionModel]:
        return self.list_project_sessions(
            project_id=project_id,
            trace_context=trace_context,
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

    def assert_session_deletable(
        self,
        *,
        session_id: str,
        trace_context: TraceContext,
    ) -> tuple[SessionModel, PipelineRunModel | None]:
        model = self._load_session_any_visibility(session_id)
        if model is None:
            self._record_delete_rejection(
                session_id=session_id,
                reason=SESSION_NOT_FOUND_MESSAGE,
                trace_context=trace_context,
                metadata={"session_id": session_id},
            )
            raise SessionServiceError(
                ErrorCode.NOT_FOUND,
                SESSION_NOT_FOUND_MESSAGE,
                404,
            )
        if not model.is_visible:
            self._record_delete_rejection(
                session_id=session_id,
                reason=SESSION_ALREADY_REMOVED_MESSAGE,
                trace_context=trace_context,
                metadata={
                    "session_id": model.session_id,
                    "project_id": model.project_id,
                },
            )
            raise SessionServiceError(
                ErrorCode.VALIDATION_ERROR,
                SESSION_ALREADY_REMOVED_MESSAGE,
                409,
            )
        if model.current_run_id is None:
            return model, None
        if self._runtime_session is None:
            raise SessionServiceError(
                ErrorCode.INTERNAL_ERROR,
                SESSION_RUNTIME_UNAVAILABLE_MESSAGE,
                500,
            )
        run = self._runtime_session.get(PipelineRunModel, model.current_run_id)
        return model, run

    def delete_session(
        self,
        *,
        session_id: str,
        trace_context: TraceContext,
    ) -> SessionDeleteResult:
        model, run = self.assert_session_deletable(
            session_id=session_id,
            trace_context=trace_context,
        )
        pending_publication = self._pending_startup_publication(
            session_id=model.session_id
        )
        if pending_publication is not None:
            return self._blocked_delete_result(
                model=model,
                blocking_run_id=pending_publication.run_id,
                trace_context=trace_context,
            )
        if run is not None and RunStateMachine.is_active_run_status(run.status):
            return self._blocked_delete_result(
                model=model,
                run=run,
                trace_context=trace_context,
            )
        return self._soft_delete_checked_session(
            model=model,
            trace_context=trace_context,
            retry_on_guard_loss=True,
        )

    def _soft_delete_checked_session(
        self,
        *,
        model: SessionModel,
        trace_context: TraceContext,
        retry_on_guard_loss: bool,
    ) -> SessionDeleteResult:
        original_updated_at = model.updated_at
        timestamp = self._now()
        statement = (
            update(SessionModel)
            .where(
                SessionModel.session_id == model.session_id,
                SessionModel.is_visible.is_(True),
                SessionModel.status == model.status,
                self._current_run_matches_checked_state(model.current_run_id),
                self._no_pending_startup_publication(model.session_id),
            )
            .values(
                is_visible=False,
                visibility_removed_at=timestamp,
                updated_at=timestamp,
            )
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(statement)
        if result.rowcount != 1:
            self._session.rollback()
            fresh_model, fresh_run = self.assert_session_deletable(
                session_id=model.session_id,
                trace_context=trace_context,
            )
            pending_publication = self._pending_startup_publication(
                session_id=fresh_model.session_id
            )
            if pending_publication is not None:
                return self._blocked_delete_result(
                    model=fresh_model,
                    blocking_run_id=pending_publication.run_id,
                    trace_context=trace_context,
                )
            if fresh_run is not None and RunStateMachine.is_active_run_status(
                fresh_run.status
            ):
                return self._blocked_delete_result(
                    model=fresh_model,
                    run=fresh_run,
                    trace_context=trace_context,
                )
            if retry_on_guard_loss:
                return self._soft_delete_checked_session(
                    model=fresh_model,
                    trace_context=trace_context,
                    retry_on_guard_loss=False,
                )
            raise SessionServiceError(
                ErrorCode.VALIDATION_ERROR,
                "Session delete state changed before visibility update.",
                409,
        )

        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(model)

        audit_succeeded = True
        try:
            audit_succeeded = self._record_delete_success_audit(
                model=model,
                timestamp=timestamp,
                trace_context=trace_context,
            )
        except Exception:
            self._restore_session_visibility_after_audit_failure(
                model=model,
                deleted_at=timestamp,
                restored_updated_at=original_updated_at,
            )
            raise
        if not audit_succeeded:
            self._session.refresh(model)
        return SessionDeleteResult(
            session_id=model.session_id,
            project_id=model.project_id,
            visibility_removed=True,
            blocked_by_active_run=False,
            blocking_run_id=None,
            error_code=None,
            message=SESSION_DELETE_SUCCESS_MESSAGE,
        )

    def _record_delete_success_audit(
        self,
        *,
        model: SessionModel,
        timestamp: datetime,
        trace_context: TraceContext,
    ) -> bool:
        metadata = {
            "session_id": model.session_id,
            "project_id": model.project_id,
            "status": model.status.value,
            "current_run_id": model.current_run_id,
            "visibility_removed": True,
            "visibility_removed_at": timestamp.isoformat(),
        }
        try:
            self._audit_service.record_command_result(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action=SESSION_DELETE_ACTION,
                target_type="session",
                target_id=model.session_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata=metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
        except TypeError:
            self._audit_service.record_command_result(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action=SESSION_DELETE_ACTION,
                target_type="session",
                target_id=model.session_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata=metadata,
                trace_context=trace_context,
            )
        except Exception:
            if self._delete_success_audit_exists(
                model=model,
                timestamp=timestamp,
                trace_context=trace_context,
            ):
                return False
            raise
        return True

    def _delete_success_audit_exists(
        self,
        *,
        model: SessionModel,
        timestamp: datetime,
        trace_context: TraceContext,
    ) -> bool:
        scalars = getattr(self._audit_service, "_session", None)
        if scalars is None:
            return False
        from backend.app.db.models.log import AuditLogEntryModel

        return (
            scalars.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == SESSION_DELETE_ACTION,
                AuditLogEntryModel.target_type == "session",
                AuditLogEntryModel.target_id == model.session_id,
                AuditLogEntryModel.result == AuditResult.SUCCEEDED,
                AuditLogEntryModel.request_id == trace_context.request_id,
                AuditLogEntryModel.correlation_id == trace_context.correlation_id,
                AuditLogEntryModel.created_at == timestamp,
            )
            .first()
            is not None
        )

    def _restore_session_visibility_after_audit_failure(
        self,
        *,
        model: SessionModel,
        deleted_at: datetime,
        restored_updated_at: datetime,
    ) -> None:
        self._session.execute(
            update(SessionModel)
            .where(
                SessionModel.session_id == model.session_id,
                SessionModel.is_visible.is_(False),
                SessionModel.visibility_removed_at == deleted_at,
            )
            .values(
                is_visible=True,
                visibility_removed_at=None,
                updated_at=restored_updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        self._session.commit()

    def _current_run_matches_checked_state(self, current_run_id: str | None):  # noqa: ANN202
        if current_run_id is None:
            return SessionModel.current_run_id.is_(None)
        return SessionModel.current_run_id == current_run_id

    def _no_pending_startup_publication(self, session_id: str):  # noqa: ANN202
        return ~exists().where(
            StartupPublicationModel.pending_session_id == session_id,
            StartupPublicationModel.publication_state == PUBLICATION_STATE_PENDING,
        )

    def _pending_startup_publication(
        self,
        *,
        session_id: str,
    ) -> StartupPublicationModel | None:
        return (
            self._session.query(StartupPublicationModel)
            .filter(
                StartupPublicationModel.pending_session_id == session_id,
                StartupPublicationModel.publication_state == PUBLICATION_STATE_PENDING,
            )
            .one_or_none()
        )

    def _blocked_delete_result(
        self,
        *,
        model: SessionModel,
        run: PipelineRunModel | None = None,
        blocking_run_id: str | None = None,
        trace_context: TraceContext,
    ) -> SessionDeleteResult:
        blocking_run_id = run.run_id if run is not None else blocking_run_id
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action=SESSION_DELETE_ACTION,
            target_type="session",
            target_id=model.session_id,
            result=AuditResult.BLOCKED,
            reason=SESSION_DELETE_BLOCKED_MESSAGE,
            metadata={
                "session_id": model.session_id,
                "project_id": model.project_id,
                "status": model.status.value,
                "current_run_id": model.current_run_id,
                "blocking_run_id": blocking_run_id,
                "visibility_removed": False,
            },
            trace_context=trace_context,
        )
        return SessionDeleteResult(
            session_id=model.session_id,
            project_id=model.project_id,
            visibility_removed=False,
            blocked_by_active_run=True,
            blocking_run_id=blocking_run_id,
            error_code=SESSION_DELETE_BLOCKED_ERROR_CODE,
            message=SESSION_DELETE_BLOCKED_MESSAGE,
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
        auto_display_name = (
            session_auto_title_from_requirement(content)
            if model.display_name == DEFAULT_SESSION_DISPLAY_NAME
            else None
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
                session_display_name=auto_display_name,
                session_display_name_expected_current=DEFAULT_SESSION_DISPLAY_NAME,
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

    def _load_session_any_visibility(self, session_id: str) -> SessionModel | None:
        return self._session.get(SessionModel, session_id)

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

    def _record_delete_rejection(
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
            action=SESSION_DELETE_REJECTED_ACTION,
            target_type="session",
            target_id=session_id,
            reason=reason,
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
        return _TemplatePromptValidationAdapter(
            settings_service=self._runtime_settings_service(),
        )


class _NoopSessionLogWriter:
    def write_run_log(self, record) -> object:  # noqa: ANN001
        return object()


class _NoopSettingsLogWriter:
    def write(self, record) -> object:  # noqa: ANN001
        return object()


class _TemplatePromptValidationAdapter:
    def __init__(
        self,
        *,
        settings_service: PlatformRuntimeSettingsService,
    ) -> None:
        self._settings_service = settings_service

    def validate_run_prompt_snapshots(
        self,
        *,
        template_snapshot,
        trace_context,  # noqa: ANN001
    ) -> None:
        try:
            validator = PromptValidationService(
                settings_read=self._settings_service.get_current_settings(
                    trace_context=trace_context,
                )
            )
            validator.validate_run_prompt_snapshots(
                template_snapshot=template_snapshot,
            )
        except PromptValidationError as exc:
            raise RunPromptValidationError(
                exc.message,
                error_code=exc.error_code,
            ) from exc


__all__ = [
    "DEFAULT_SESSION_DISPLAY_NAME",
    "SESSION_AUTO_TITLE_MAX_LENGTH",
    "PROJECT_NOT_FOUND_MESSAGE",
    "SESSION_NOT_FOUND_MESSAGE",
    "SESSION_ALREADY_REMOVED_MESSAGE",
    "SESSION_DELETE_BLOCKED_ERROR_CODE",
    "SESSION_DELETE_BLOCKED_MESSAGE",
    "SESSION_DELETE_SUCCESS_MESSAGE",
    "SESSION_RUNTIME_UNAVAILABLE_MESSAGE",
    "TEMPLATE_NOT_FOUND_MESSAGE",
    "TEMPLATE_UPDATE_BLOCKED_MESSAGE",
    "SessionService",
    "SessionStartRunResult",
    "SessionServiceError",
    "session_auto_title_from_requirement",
]
