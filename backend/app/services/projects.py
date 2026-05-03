from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import exists, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.models.control import (
    ProjectModel,
    SessionModel,
    StartupPublicationModel,
)
from backend.app.db.models.runtime import PipelineRunModel
from backend.app.domain.enums import SessionStatus
from backend.app.domain.publication_boundary import PUBLICATION_STATE_PENDING
from backend.app.domain.state_machine import RunStateMachine
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.project import ProjectRemoveResult
from backend.app.services.delivery_channels import (
    DEFAULT_PROJECT_ID,
    DeliveryChannelService,
)


PROJECT_ROOT_INVALID_MESSAGE = "Project root_path must be an existing directory."
PROJECT_NOT_FOUND_MESSAGE = "Project was not found."
PROJECT_REMOVE_BLOCKED_MESSAGE = "Project has an active run."
PROJECT_REMOVE_SUCCESS_MESSAGE = "Project removed from regular product history."
PROJECT_ALREADY_REMOVED_MESSAGE = (
    "Project was already removed from regular product history."
)
DEFAULT_PROJECT_REMOVE_BLOCKED_MESSAGE = "Default Project cannot be removed."
PROJECT_RUNTIME_UNAVAILABLE_MESSAGE = (
    "Runtime session is required to verify current run state before removing a Project."
)
PROJECT_RUNTIME_STATE_UNAVAILABLE_MESSAGE = (
    "Runtime state is unavailable during Project removal."
)
PROJECT_REMOVE_BLOCKED_ERROR_CODE = "project_active_run_blocks_remove"
PROJECT_REMOVE_ACTION = "project.remove"
PROJECT_REMOVE_REJECTED_ACTION = "project.remove.rejected"
PROJECT_REMOVE_GUARD_LOST_MESSAGE = (
    "Project remove state changed before visibility update."
)


class ProjectServiceError(RuntimeError):
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
class CheckedProjectSession:
    session_id: str
    status: SessionStatus
    current_run_id: str | None
    updated_at: datetime


def _resolved_path(root_path: str | Path) -> Path:
    return Path(root_path).expanduser().resolve(strict=False)


def _normalized_path_text(root: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(root)))


def _path_hash(root: Path) -> str:
    digest = hashlib.sha256(_normalized_path_text(root).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _project_id_for_root(root: Path) -> str:
    return f"project-{_path_hash(root).removeprefix('sha256:')[:24]}"


def _audit_target_for_root(root: Path) -> str:
    return f"project_root:{_path_hash(root)}"


class ProjectService:
    def __init__(
        self,
        session: Session,
        *,
        settings: EnvironmentSettings,
        audit_service: Any,
        runtime_session: Session | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._audit_service = audit_service
        self._runtime_session = runtime_session
        self._now = now or (lambda: datetime.now(UTC))
        self._delivery_channels = DeliveryChannelService(session, now=self._now)

    def ensure_default_project(self, *, trace_context: TraceContext) -> ProjectModel:
        default_root = _resolved_path(self._settings.default_project_root)
        existing = self._session.get(ProjectModel, DEFAULT_PROJECT_ID)
        if existing is not None:
            project = self._ensure_project_channel(existing)
            self._session.commit()
            return project

        timestamp = self._now()
        project = ProjectModel(
            project_id=DEFAULT_PROJECT_ID,
            name=default_root.name or "Default Project",
            root_path=str(default_root),
            default_delivery_channel_id=None,
            is_default=True,
            is_visible=True,
            visibility_removed_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._session.add(project)
        self._session.flush()
        self._ensure_project_channel(project)
        try:
            self._record_success(
                action="project.ensure_default",
                project=project,
                root=default_root,
                trace_context=trace_context,
                is_default=True,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return project

    def list_projects(self, *, trace_context: TraceContext) -> list[ProjectModel]:
        self.ensure_default_project(trace_context=trace_context)
        return (
            self._session.query(ProjectModel)
            .filter(ProjectModel.is_visible.is_(True))
            .order_by(
                ProjectModel.is_default.desc(),
                ProjectModel.created_at.asc(),
                ProjectModel.project_id.asc(),
            )
            .all()
        )

    def create_project(
        self,
        *,
        root_path: str | Path,
        trace_context: TraceContext,
    ) -> ProjectModel:
        return self.load_project(root_path=root_path, trace_context=trace_context)

    def load_project(
        self,
        *,
        root_path: str | Path,
        trace_context: TraceContext,
    ) -> ProjectModel:
        root = _resolved_path(root_path)
        if not root.is_dir():
            self._record_rejected_load(root=root, trace_context=trace_context)
            raise ProjectServiceError(
                ErrorCode.VALIDATION_ERROR,
                PROJECT_ROOT_INVALID_MESSAGE,
            )

        project_id = _project_id_for_root(root)
        existing = self._session.get(ProjectModel, project_id)
        if existing is not None:
            if not existing.is_visible:
                existing.is_visible = True
                existing.visibility_removed_at = None
                existing.updated_at = self._now()
                self._session.add(existing)
                self._session.flush()
            project = self._ensure_project_channel(existing)
            try:
                self._record_success(
                    action="project.load",
                    project=project,
                    root=root,
                    trace_context=trace_context,
                    is_default=False,
                )
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise
            return project

        timestamp = self._now()
        project = ProjectModel(
            project_id=project_id,
            name=root.name or "Loaded Project",
            root_path=str(root),
            default_delivery_channel_id=None,
            is_default=False,
            is_visible=True,
            visibility_removed_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._session.add(project)
        self._session.flush()
        self._ensure_project_channel(project)
        try:
            self._record_success(
                action="project.load",
                project=project,
                root=root,
                trace_context=trace_context,
                is_default=False,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return project

    def assert_project_removable(
        self,
        *,
        project_id: str,
        trace_context: TraceContext,
    ) -> tuple[ProjectModel, list[CheckedProjectSession]]:
        model = self._session.get(ProjectModel, project_id)
        if model is None:
            self._record_remove_rejection(
                project_id=project_id,
                root_path=None,
                reason=PROJECT_NOT_FOUND_MESSAGE,
                trace_context=trace_context,
                metadata={"project_id": project_id},
            )
            raise ProjectServiceError(
                ErrorCode.NOT_FOUND,
                PROJECT_NOT_FOUND_MESSAGE,
                404,
            )
        if not model.is_visible:
            self._record_remove_rejection(
                project_id=model.project_id,
                root_path=model.root_path,
                reason=PROJECT_ALREADY_REMOVED_MESSAGE,
                trace_context=trace_context,
                metadata={
                    "project_id": model.project_id,
                    "root_path_hash": _path_hash(_resolved_path(model.root_path)),
                },
            )
            raise ProjectServiceError(
                ErrorCode.VALIDATION_ERROR,
                PROJECT_ALREADY_REMOVED_MESSAGE,
                409,
            )
        if model.is_default:
            self._record_remove_rejection(
                project_id=model.project_id,
                root_path=model.root_path,
                reason=DEFAULT_PROJECT_REMOVE_BLOCKED_MESSAGE,
                trace_context=trace_context,
                metadata={
                    "project_id": model.project_id,
                    "root_path_hash": _path_hash(_resolved_path(model.root_path)),
                    "is_default": True,
                },
            )
            raise ProjectServiceError(
                ErrorCode.VALIDATION_ERROR,
                DEFAULT_PROJECT_REMOVE_BLOCKED_MESSAGE,
                409,
            )

        checked_sessions = [
            CheckedProjectSession(
                session_id=row.session_id,
                status=row.status,
                current_run_id=row.current_run_id,
                updated_at=row.updated_at,
            )
            for row in self._visible_project_sessions(model.project_id)
        ]
        return model, checked_sessions

    def hide_project_sessions(
        self,
        *,
        project_id: str,
        checked_sessions: list[CheckedProjectSession],
        timestamp: datetime,
    ) -> int:
        hidden_count = 0
        for checked in checked_sessions:
            statement = (
                update(SessionModel)
                .where(
                    SessionModel.session_id == checked.session_id,
                    SessionModel.project_id == project_id,
                    SessionModel.is_visible.is_(True),
                    SessionModel.status == checked.status,
                    SessionModel.updated_at == checked.updated_at,
                    self._current_run_matches_checked_state(checked.current_run_id),
                    self._no_pending_startup_publication(checked.session_id),
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
                raise _ProjectRemoveGuardLost
            hidden_count += 1
        return hidden_count

    def remove_project(
        self,
        *,
        project_id: str,
        trace_context: TraceContext,
    ) -> ProjectRemoveResult:
        model, checked_sessions = self.assert_project_removable(
            project_id=project_id,
            trace_context=trace_context,
        )
        with self._runtime_remove_barrier():
            blocking_run_id = self._blocking_run_id(
                project_id=model.project_id,
                checked_sessions=checked_sessions,
            )
            if blocking_run_id is not None:
                return self._blocked_remove_result(
                    model=model,
                    checked_sessions=checked_sessions,
                    blocking_run_id=blocking_run_id,
                    trace_context=trace_context,
                )
            return self._soft_remove_checked_project(
                model=model,
                checked_sessions=checked_sessions,
                trace_context=trace_context,
                retry_on_guard_loss=True,
            )

    def _soft_remove_checked_project(
        self,
        *,
        model: ProjectModel,
        checked_sessions: list[CheckedProjectSession],
        trace_context: TraceContext,
        retry_on_guard_loss: bool,
    ) -> ProjectRemoveResult:
        timestamp = self._now()
        try:
            hidden_count = self.hide_project_sessions(
                project_id=model.project_id,
                checked_sessions=checked_sessions,
                timestamp=timestamp,
            )
            project_result = self._session.execute(
                update(ProjectModel)
                .where(
                    ProjectModel.project_id == model.project_id,
                    ProjectModel.is_visible.is_(True),
                    self._no_visible_project_sessions(model.project_id),
                )
                .values(
                    is_visible=False,
                    visibility_removed_at=timestamp,
                    updated_at=timestamp,
                )
                .execution_options(synchronize_session=False)
            )
            if project_result.rowcount != 1:
                raise _ProjectRemoveGuardLost
            blocking_run_id = self._blocking_run_id(
                project_id=model.project_id,
                checked_sessions=checked_sessions,
            )
            if blocking_run_id is not None:
                self._session.rollback()
                return self._blocked_remove_result(
                    model=model,
                    checked_sessions=checked_sessions,
                    blocking_run_id=blocking_run_id,
                    trace_context=trace_context,
                )
        except _ProjectRemoveGuardLost:
            self._session.rollback()
            fresh_model, fresh_sessions = self.assert_project_removable(
                project_id=model.project_id,
                trace_context=trace_context,
            )
            blocking_run_id = self._blocking_run_id(
                project_id=fresh_model.project_id,
                checked_sessions=fresh_sessions,
            )
            if blocking_run_id is not None:
                return self._blocked_remove_result(
                    model=fresh_model,
                    checked_sessions=fresh_sessions,
                    blocking_run_id=blocking_run_id,
                    trace_context=trace_context,
                )
            if retry_on_guard_loss:
                return self._soft_remove_checked_project(
                    model=fresh_model,
                    checked_sessions=fresh_sessions,
                    trace_context=trace_context,
                    retry_on_guard_loss=False,
                )
            raise ProjectServiceError(
                ErrorCode.VALIDATION_ERROR,
                PROJECT_REMOVE_GUARD_LOST_MESSAGE,
                409,
            ) from None

        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        audit_succeeded = True
        try:
            audit_succeeded = self._record_remove_success_audit(
                model=model,
                hidden_visible_session_count=hidden_count,
                timestamp=timestamp,
                trace_context=trace_context,
            )
        except Exception:
            if self._remove_success_audit_exists(
                model=model,
                timestamp=timestamp,
                trace_context=trace_context,
            ):
                audit_succeeded = False
            else:
                self._restore_project_visibility_after_audit_failure(
                    model=model,
                    checked_sessions=checked_sessions,
                    removed_at=timestamp,
                )
                raise
        if not audit_succeeded:
            self._session.expire_all()
        self._session.expire_all()
        return ProjectRemoveResult(
            project_id=model.project_id,
            visibility_removed=True,
            blocked_by_active_run=False,
            blocking_run_id=None,
            error_code=None,
            message=PROJECT_REMOVE_SUCCESS_MESSAGE,
        )

    def _visible_project_sessions(self, project_id: str) -> list[SessionModel]:
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

    def _blocking_run_id(
        self,
        *,
        project_id: str,
        checked_sessions: list[CheckedProjectSession],
    ) -> str | None:
        if self._runtime_session is None:
            raise ProjectServiceError(
                ErrorCode.INTERNAL_ERROR,
                PROJECT_RUNTIME_UNAVAILABLE_MESSAGE,
                500,
            )
        for checked in checked_sessions:
            pending_publication = self._pending_startup_publication(
                session_id=checked.session_id
            )
            if pending_publication is not None:
                return pending_publication.run_id
            if checked.current_run_id is None:
                continue
            run = self._runtime_session.get(PipelineRunModel, checked.current_run_id)
            if run is not None and RunStateMachine.is_active_run_status(run.status):
                return run.run_id
        return self._active_project_runtime_run_id(project_id=project_id)

    def _active_project_runtime_run_id(self, *, project_id: str) -> str | None:
        runs = (
            self._runtime_session.query(PipelineRunModel)
            .filter(PipelineRunModel.project_id == project_id)
            .order_by(
                PipelineRunModel.updated_at.desc(),
                PipelineRunModel.created_at.desc(),
                PipelineRunModel.run_id.asc(),
            )
            .all()
        )
        for run in runs:
            if RunStateMachine.is_active_run_status(run.status):
                return run.run_id
        return None

    @contextmanager
    def _runtime_remove_barrier(self):
        if self._runtime_session is None:
            raise ProjectServiceError(
                ErrorCode.INTERNAL_ERROR,
                PROJECT_RUNTIME_UNAVAILABLE_MESSAGE,
                500,
            )
        bind = self._runtime_session.get_bind()
        connect = getattr(bind, "connect", None)
        if connect is None:
            bind = bind.engine
            connect = bind.connect
        barrier_connection = connect()
        try:
            barrier_connection.exec_driver_sql("BEGIN IMMEDIATE")
        except SQLAlchemyError as exc:
            barrier_connection.close()
            raise ProjectServiceError(
                ErrorCode.INTERNAL_ERROR,
                PROJECT_RUNTIME_STATE_UNAVAILABLE_MESSAGE,
                500,
            ) from exc
        try:
            yield
        finally:
            try:
                barrier_connection.rollback()
            finally:
                barrier_connection.close()

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

    def _current_run_matches_checked_state(self, current_run_id: str | None):  # noqa: ANN202
        if current_run_id is None:
            return SessionModel.current_run_id.is_(None)
        return SessionModel.current_run_id == current_run_id

    def _no_pending_startup_publication(self, session_id: str):  # noqa: ANN202
        return ~exists().where(
            StartupPublicationModel.pending_session_id == session_id,
            StartupPublicationModel.publication_state == PUBLICATION_STATE_PENDING,
        )

    def _no_visible_project_sessions(self, project_id: str):  # noqa: ANN202
        return ~exists().where(
            SessionModel.project_id == project_id,
            SessionModel.is_visible.is_(True),
        )

    def _blocked_remove_result(
        self,
        *,
        model: ProjectModel,
        checked_sessions: list[CheckedProjectSession],
        blocking_run_id: str,
        trace_context: TraceContext,
    ) -> ProjectRemoveResult:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action=PROJECT_REMOVE_ACTION,
            target_type="project",
            target_id=_audit_target_for_root(_resolved_path(model.root_path)),
            result=AuditResult.BLOCKED,
            reason=PROJECT_REMOVE_BLOCKED_MESSAGE,
            metadata={
                "project_id": model.project_id,
                "project_name": model.name,
                "root_path_hash": _path_hash(_resolved_path(model.root_path)),
                "blocking_run_id": blocking_run_id,
                "hidden_visible_session_count": 0,
                "checked_visible_session_count": len(checked_sessions),
                "visibility_removed": False,
            },
            trace_context=trace_context,
        )
        return ProjectRemoveResult(
            project_id=model.project_id,
            visibility_removed=False,
            blocked_by_active_run=True,
            blocking_run_id=blocking_run_id,
            error_code=PROJECT_REMOVE_BLOCKED_ERROR_CODE,
            message=PROJECT_REMOVE_BLOCKED_MESSAGE,
        )

    def _record_remove_success_audit(
        self,
        *,
        model: ProjectModel,
        hidden_visible_session_count: int,
        timestamp: datetime,
        trace_context: TraceContext,
    ) -> bool:
        root = _resolved_path(model.root_path)
        try:
            self._audit_service.record_command_result(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action=PROJECT_REMOVE_ACTION,
                target_type="project",
                target_id=_audit_target_for_root(root),
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata={
                    "project_id": model.project_id,
                    "project_name": model.name,
                    "root_path_hash": _path_hash(root),
                    "default_delivery_channel_id": model.default_delivery_channel_id,
                    "hidden_visible_session_count": hidden_visible_session_count,
                    "visibility_removed": True,
                    "visibility_removed_at": timestamp.isoformat(),
                },
                trace_context=trace_context,
                created_at=timestamp,
            )
        except TypeError:
            self._audit_service.record_command_result(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action=PROJECT_REMOVE_ACTION,
                target_type="project",
                target_id=_audit_target_for_root(root),
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata={
                    "project_id": model.project_id,
                    "project_name": model.name,
                    "root_path_hash": _path_hash(root),
                    "default_delivery_channel_id": model.default_delivery_channel_id,
                    "hidden_visible_session_count": hidden_visible_session_count,
                    "visibility_removed": True,
                    "visibility_removed_at": timestamp.isoformat(),
                },
                trace_context=trace_context,
            )
        except Exception:
            if self._remove_success_audit_exists(
                model=model,
                timestamp=timestamp,
                trace_context=trace_context,
            ):
                return False
            raise
        return True

    def _remove_success_audit_exists(
        self,
        *,
        model: ProjectModel,
        timestamp: datetime,
        trace_context: TraceContext,
    ) -> bool:
        log_session = getattr(self._audit_service, "_session", None)
        if log_session is None:
            return False
        from backend.app.db.models.log import AuditLogEntryModel

        return (
            log_session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == PROJECT_REMOVE_ACTION,
                AuditLogEntryModel.target_type == "project",
                AuditLogEntryModel.target_id
                == _audit_target_for_root(_resolved_path(model.root_path)),
                AuditLogEntryModel.result == AuditResult.SUCCEEDED,
                AuditLogEntryModel.request_id == trace_context.request_id,
                AuditLogEntryModel.correlation_id == trace_context.correlation_id,
                AuditLogEntryModel.created_at == timestamp,
            )
            .first()
            is not None
        )

    def _restore_project_visibility_after_audit_failure(
        self,
        *,
        model: ProjectModel,
        checked_sessions: list[CheckedProjectSession],
        removed_at: datetime,
    ) -> None:
        self._session.execute(
            update(ProjectModel)
            .where(
                ProjectModel.project_id == model.project_id,
                ProjectModel.is_visible.is_(False),
                ProjectModel.visibility_removed_at == removed_at,
            )
            .values(
                is_visible=True,
                visibility_removed_at=None,
                updated_at=model.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        for checked in checked_sessions:
            self._session.execute(
                update(SessionModel)
                .where(
                    SessionModel.session_id == checked.session_id,
                    SessionModel.project_id == model.project_id,
                    SessionModel.is_visible.is_(False),
                    SessionModel.visibility_removed_at == removed_at,
                )
                .values(
                    is_visible=True,
                    visibility_removed_at=None,
                    updated_at=checked.updated_at,
                )
                .execution_options(synchronize_session=False)
            )
        self._session.commit()

    def _record_remove_rejection(
        self,
        *,
        project_id: str,
        root_path: str | None,
        reason: str,
        trace_context: TraceContext,
        metadata: dict[str, Any],
    ) -> None:
        target_id = (
            project_id
            if root_path is None
            else _audit_target_for_root(_resolved_path(root_path))
        )
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action=PROJECT_REMOVE_REJECTED_ACTION,
            target_type="project",
            target_id=target_id,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
        )

    def _ensure_project_channel(self, project: ProjectModel) -> ProjectModel:
        channel = self._delivery_channels.ensure_default_channel(project.project_id)
        if project.default_delivery_channel_id != channel.delivery_channel_id:
            project.default_delivery_channel_id = channel.delivery_channel_id
            project.updated_at = self._now()
            self._session.add(project)
            self._session.flush()
        return project

    def _record_success(
        self,
        *,
        action: str,
        project: ProjectModel,
        root: Path,
        trace_context: TraceContext,
        is_default: bool,
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action=action,
            target_type="project",
            target_id=_audit_target_for_root(root),
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata={
                "project_id": project.project_id,
                "project_name": project.name,
                "root_path_hash": _path_hash(root),
                "default_delivery_channel_id": project.default_delivery_channel_id,
                "is_default": is_default,
            },
            trace_context=trace_context,
        )

    def _record_rejected_load(self, *, root: Path, trace_context: TraceContext) -> None:
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id="api-user",
            action="project.load.rejected",
            target_type="project",
            target_id=_audit_target_for_root(root),
            reason=PROJECT_ROOT_INVALID_MESSAGE,
            metadata={
                "root_path_hash": _path_hash(root),
                "exists": root.exists(),
                "is_dir": root.is_dir(),
            },
            trace_context=trace_context,
        )


class _ProjectRemoveGuardLost(Exception):
    pass


__all__ = [
    "DEFAULT_PROJECT_REMOVE_BLOCKED_MESSAGE",
    "PROJECT_ALREADY_REMOVED_MESSAGE",
    "PROJECT_NOT_FOUND_MESSAGE",
    "PROJECT_REMOVE_BLOCKED_ERROR_CODE",
    "PROJECT_REMOVE_BLOCKED_MESSAGE",
    "PROJECT_REMOVE_SUCCESS_MESSAGE",
    "PROJECT_ROOT_INVALID_MESSAGE",
    "PROJECT_RUNTIME_UNAVAILABLE_MESSAGE",
    "CheckedProjectSession",
    "ProjectService",
    "ProjectServiceError",
]
