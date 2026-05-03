from __future__ import annotations

import logging
import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from shutil import rmtree
from typing import Any, Protocol
from uuid import uuid4

from backend.app.core.config import EnvironmentSettings
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactedPayload, RedactionPolicy
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.observability import AuditActorType, LogCategory, LogLevel
from backend.app.tools.execution_gate import ToolWorkspaceBoundaryError


_LOGGER = logging.getLogger(__name__)


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class WorkspaceAuditService(Protocol):
    def record_blocked_action(self, **kwargs: object) -> object: ...


@dataclass(frozen=True, slots=True)
class RunWorkspace:
    run_id: str
    workspace_ref: str
    root: Path
    excluded_relative_paths: tuple[str, ...]


class WorkspaceManagerError(RuntimeError):
    """Workspace lifecycle or lookup failure."""


class WorkspaceManager:
    def __init__(
        self,
        *,
        settings: EnvironmentSettings,
        log_writer: RunLogWriter | None = None,
        audit_service: WorkspaceAuditService | None = None,
        redaction_policy: RedactionPolicy | None = None,
        runtime_data_settings: RuntimeDataSettings | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._workspace_root = settings.resolve_workspace_root()
        self._runtime_data = (
            runtime_data_settings
            or RuntimeDataSettings.from_environment_settings(settings)
        )
        self._log_writer = log_writer
        self._audit_service = audit_service
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))
        self._excluded_relative_paths = self._build_excluded_relative_paths()

    def create_for_run(
        self,
        *,
        run_id: str,
        workspace_ref: str,
        trace_context: TraceContext,
    ) -> RunWorkspace:
        workspace = self._workspace_handle(run_id=run_id, workspace_ref=workspace_ref)
        try:
            self._workspace_root.mkdir(parents=True, exist_ok=True)
            if workspace.root.exists():
                self._remove_managed_workspace_path(workspace.root)
            workspace.root.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            error = WorkspaceManagerError("Run workspace could not be created.")
            self._write_failure_log(
                action="create_for_run",
                workspace=workspace,
                error=error,
                trace_context=trace_context,
                metadata={"path": workspace.root.as_posix()},
            )
            raise error from exc

        self._write_log(
            action="create_for_run",
            workspace=workspace,
            trace_context=trace_context,
            level=LogLevel.INFO,
            message="Run workspace prepared.",
            metadata={
                "path": workspace.root.as_posix(),
                "excluded_relative_paths": list(workspace.excluded_relative_paths),
            },
        )
        return workspace

    def get_run_workspace(
        self,
        *,
        run_id: str,
        workspace_ref: str,
        trace_context: TraceContext,
    ) -> RunWorkspace:
        workspace = self._workspace_handle(run_id=run_id, workspace_ref=workspace_ref)
        if not workspace.root.is_dir():
            error = WorkspaceManagerError("Run workspace was not found.")
            self._write_failure_log(
                action="get_run_workspace",
                workspace=workspace,
                error=error,
                trace_context=trace_context,
                metadata={"path": workspace.root.as_posix()},
            )
            raise error

        self._write_log(
            action="get_run_workspace",
            workspace=workspace,
            trace_context=trace_context,
            level=LogLevel.INFO,
            message="Run workspace located.",
            metadata={"path": workspace.root.as_posix()},
        )
        return workspace

    def cleanup_run_workspace(
        self,
        *,
        workspace: RunWorkspace,
        trace_context: TraceContext,
    ) -> None:
        try:
            self._assert_managed_workspace_path(workspace.root)
        except OSError as exc:
            error = WorkspaceManagerError("Run workspace could not be cleaned.")
            self._write_failure_log(
                action="cleanup_run_workspace",
                workspace=workspace,
                error=error,
                trace_context=trace_context,
                metadata={"path": workspace.root.as_posix()},
            )
            raise error from exc

        if not workspace.root.exists():
            self._write_log(
                action="cleanup_run_workspace",
                workspace=workspace,
                trace_context=trace_context,
                level=LogLevel.INFO,
                message="Run workspace cleanup skipped; path already absent.",
                metadata={"path": workspace.root.as_posix(), "skipped": True},
            )
            return

        try:
            self._remove_managed_workspace_path(workspace.root)
        except OSError as exc:
            error = WorkspaceManagerError("Run workspace could not be cleaned.")
            self._write_failure_log(
                action="cleanup_run_workspace",
                workspace=workspace,
                error=error,
                trace_context=trace_context,
                metadata={"path": workspace.root.as_posix()},
            )
            raise error from exc

        self._write_log(
            action="cleanup_run_workspace",
            workspace=workspace,
            trace_context=trace_context,
            level=LogLevel.INFO,
            message="Run workspace removed.",
            metadata={"path": workspace.root.as_posix()},
        )

    def assert_inside_workspace(
        self,
        target: str,
        *,
        workspace: RunWorkspace,
        trace_context: TraceContext,
    ) -> Path:
        candidate = self._resolve_workspace_target(workspace, target)
        if candidate is None or not candidate.is_relative_to(workspace.root):
            self._block_workspace_target(
                workspace=workspace,
                target=target,
                trace_context=trace_context,
            )

        relative_candidate = candidate.relative_to(workspace.root).as_posix()
        for excluded in workspace.excluded_relative_paths:
            if relative_candidate == excluded or relative_candidate.startswith(
                f"{excluded}/"
            ):
                self._block_workspace_target(
                    workspace=workspace,
                    target=target,
                    trace_context=trace_context,
                )

        self._write_log(
            action="assert_inside_workspace",
            workspace=workspace,
            trace_context=trace_context,
            level=LogLevel.INFO,
            message="Workspace boundary check succeeded.",
            metadata={"target": target, "resolved_target": candidate.as_posix()},
        )
        return candidate

    def _workspace_handle(self, *, run_id: str, workspace_ref: str) -> RunWorkspace:
        self._validate_path_segment(run_id, field_name="run_id")
        self._validate_path_segment(workspace_ref, field_name="workspace_ref")
        return RunWorkspace(
            run_id=run_id,
            workspace_ref=workspace_ref,
            root=(self._workspace_root / workspace_ref).resolve(strict=False),
            excluded_relative_paths=self._excluded_relative_paths,
        )

    def _build_excluded_relative_paths(self) -> tuple[str, ...]:
        default_project_root = self._settings.default_project_root.expanduser().resolve(
            strict=False
        )
        logs_dir = self._runtime_data.logs_dir
        if logs_dir == default_project_root or logs_dir.is_relative_to(
            default_project_root
        ):
            return (logs_dir.relative_to(default_project_root).as_posix(),)
        return ()

    def _remove_managed_workspace_path(self, path: Path) -> None:
        self._assert_managed_workspace_path(path)
        if path.is_dir():
            rmtree(path)
        else:
            path.unlink()

    def _assert_managed_workspace_path(self, path: Path) -> None:
        candidate = path.resolve(strict=False)
        if candidate == self._workspace_root or not candidate.is_relative_to(
            self._workspace_root
        ):
            raise OSError("workspace path is outside the managed workspace root")

    def _resolve_workspace_target(
        self,
        workspace: RunWorkspace,
        target: str,
    ) -> Path | None:
        if "\0" in target or self._is_absolute_or_drive_qualified(target):
            return None
        normalized = posixpath.normpath(target.replace("\\", "/"))
        return (workspace.root / normalized).resolve(strict=False)

    def _is_absolute_or_drive_qualified(self, target: str) -> bool:
        return target.startswith(("/", "\\")) or bool(PureWindowsPath(target).drive)

    def _validate_path_segment(self, value: str, *, field_name: str) -> None:
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or ":" in value
            or "\0" in value
        ):
            raise WorkspaceManagerError(f"{field_name} must be a safe path segment.")

    def _block_workspace_target(
        self,
        *,
        workspace: RunWorkspace,
        target: str,
        trace_context: TraceContext,
    ) -> None:
        self._record_blocked_boundary(
            workspace=workspace,
            target=target,
            trace_context=trace_context,
        )
        raise ToolWorkspaceBoundaryError(
            "Tool target is outside the run workspace.",
            target=target,
        )

    def _record_blocked_boundary(
        self,
        *,
        workspace: RunWorkspace,
        target: str,
        trace_context: TraceContext,
    ) -> None:
        self._write_log(
            action="assert_inside_workspace_failed",
            workspace=workspace,
            trace_context=trace_context,
            level=LogLevel.WARNING,
            message="Workspace boundary rejected target.",
            metadata={"target": target},
        )
        if self._audit_service is None:
            return
        timestamp = self._now()
        audit_trace = self._normalized_trace(
            trace_context=trace_context,
            run_id=workspace.run_id,
            created_at=timestamp,
            action="workspace-boundary-blocked",
        )
        redacted_target = self._redaction_policy.summarize_payload(
            {"target": target},
            payload_type="workspace_boundary_target",
        )
        try:
            self._audit_service.record_blocked_action(
                actor_type=AuditActorType.SYSTEM,
                actor_id="workspace_manager",
                action="workspace.boundary.blocked",
                target_type="workspace_path",
                target_id=workspace.workspace_ref,
                reason="Workspace boundary rejected target path.",
                metadata={
                    "workspace_ref": workspace.workspace_ref,
                    "run_id": workspace.run_id,
                    **self._audit_boundary_metadata(redacted_target),
                },
                trace_context=audit_trace,
                created_at=timestamp,
            )
        except Exception:
            _LOGGER.debug("Workspace audit write failed", exc_info=True)

    def _write_failure_log(
        self,
        *,
        action: str,
        workspace: RunWorkspace,
        error: Exception,
        trace_context: TraceContext,
        metadata: dict[str, Any],
    ) -> None:
        self._write_log(
            action=f"{action}_failed",
            workspace=workspace,
            trace_context=trace_context,
            level=LogLevel.ERROR,
            message="Workspace operation failed.",
            metadata={**metadata, "error_message": str(error)},
        )

    def _write_log(
        self,
        *,
        action: str,
        workspace: RunWorkspace,
        trace_context: TraceContext,
        level: LogLevel,
        message: str,
        metadata: dict[str, Any],
    ) -> None:
        if self._log_writer is None:
            return
        timestamp = self._now()
        log_trace = self._normalized_trace(
            trace_context=trace_context,
            run_id=workspace.run_id,
            created_at=timestamp,
            action=action,
        )
        redacted = self._redaction_policy.summarize_payload(
            {
                "action": action,
                "run_id": workspace.run_id,
                "workspace_ref": workspace.workspace_ref,
                **metadata,
            },
            payload_type="workspace_manager",
        )
        try:
            self._log_writer.write_run_log(
                LogRecordInput(
                    source="workspace.manager",
                    category=LogCategory.WORKSPACE,
                    level=level,
                    message=message,
                    trace_context=log_trace,
                    payload=self._log_payload_summary(redacted),
                    created_at=timestamp,
                )
            )
        except Exception:
            _LOGGER.debug("Workspace log write failed", exc_info=True)

    def _log_payload_summary(self, redacted: object) -> LogPayloadSummary:
        redacted_payload = getattr(redacted, "redacted_payload", None)
        if isinstance(redacted_payload, dict):
            summary = dict(redacted_payload)
            redaction_summary = getattr(redacted, "summary", {})
            if isinstance(redaction_summary, dict):
                summary["blocked_fields"] = redaction_summary.get("blocked_fields", [])
                summary["truncated_fields"] = redaction_summary.get(
                    "truncated_fields",
                    [],
                )
            return LogPayloadSummary(
                payload_type="workspace_manager",
                summary=summary,
                excerpt=getattr(redacted, "excerpt"),
                payload_size_bytes=getattr(redacted, "payload_size_bytes"),
                content_hash=getattr(redacted, "content_hash"),
                redaction_status=getattr(redacted, "redaction_status"),
            )
        return LogPayloadSummary.from_redacted_payload(
            "workspace_manager",
            redacted,  # type: ignore[arg-type]
        )

    def _audit_boundary_metadata(
        self,
        redacted_target: RedactedPayload,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "target_redaction_status": redacted_target.redaction_status.value,
        }
        if isinstance(redacted_target.redacted_payload, dict):
            target_value = redacted_target.redacted_payload.get("target")
            if isinstance(target_value, str):
                summary["target"] = target_value
        else:
            summary["target"] = redacted_target.excerpt
        return summary

    def _normalized_trace(
        self,
        *,
        trace_context: TraceContext,
        run_id: str,
        created_at: datetime,
        action: str,
    ) -> TraceContext:
        return trace_context.child_span(
            span_id=f"workspace-{action}-{uuid4().hex}",
            created_at=created_at,
            run_id=run_id,
        )


__all__ = [
    "RunWorkspace",
    "RunLogWriter",
    "WorkspaceAuditService",
    "WorkspaceManager",
    "WorkspaceManagerError",
]
