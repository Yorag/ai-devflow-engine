from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.models.control import ProjectModel
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.services.delivery_channels import (
    DEFAULT_PROJECT_ID,
    DeliveryChannelService,
)


PROJECT_ROOT_INVALID_MESSAGE = "Project root_path must be an existing directory."


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
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._audit_service = audit_service
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


__all__ = ["PROJECT_ROOT_INVALID_MESSAGE", "ProjectService", "ProjectServiceError"]
