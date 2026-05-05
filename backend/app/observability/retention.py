from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models.log import AuditLogEntryModel, LogPayloadModel
from backend.app.db.models.log import RunLogEntryModel
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.observability import LogCategory


EXPIRED_LOG_FILE_REF = "logs/expired.jsonl"
EXPIRED_LOG_MESSAGE = "Log content expired by retention policy."


@dataclass(frozen=True)
class LogRotationResult:
    rotated: bool
    original_log_file_ref: str
    rotated_log_file_ref: str | None
    log_file_generation: str | None
    reason: str | None


@dataclass(frozen=True)
class LogCleanupResult:
    cutoff: datetime
    deleted_log_ids: tuple[str, ...]
    deleted_payload_refs: tuple[str, ...]
    deleted_file_refs: tuple[str, ...]
    retained_file_refs: tuple[str, ...]
    protected_log_ids: tuple[str, ...]


class LogRetentionService:
    def __init__(
        self,
        runtime_settings: RuntimeDataSettings,
        log_session: Session | None = None,
    ) -> None:
        self._runtime_root = runtime_settings.root.resolve(strict=False)
        self._logs_dir = runtime_settings.logs_dir.resolve(strict=False)
        self._run_logs_dir = runtime_settings.run_logs_dir.resolve(strict=False)
        self._log_session = log_session

    def rotate_if_needed(
        self,
        log_file_ref: str,
        *,
        max_bytes: int,
        now: datetime | None = None,
    ) -> LogRotationResult:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero")
        current_time = self._utc(now)
        path = self._resolve_runtime_ref(log_file_ref)
        if not self._is_under(path, self._logs_dir):
            raise ValueError("log_file_ref must reference a platform log file")
        if not self._is_under(path, self._run_logs_dir):
            raise ValueError("log_file_ref must reference a run log file")
        if not path.exists():
            return LogRotationResult(
                rotated=False,
                original_log_file_ref=log_file_ref,
                rotated_log_file_ref=None,
                log_file_generation=None,
                reason=None,
            )
        if not path.is_file():
            raise ValueError("log_file_ref must reference a regular log file")

        stat = path.stat()
        reason = self._rotation_reason(stat.st_size, stat.st_mtime, max_bytes, current_time)
        if reason is None:
            return LogRotationResult(
                rotated=False,
                original_log_file_ref=log_file_ref,
                rotated_log_file_ref=None,
                log_file_generation=None,
                reason=None,
            )

        rotated_path = self._rotated_path(path, current_time)
        rotated_ref = self._runtime_relative_ref(rotated_path)
        generation = rotated_path.stem
        rotated_path.parent.mkdir(parents=True, exist_ok=True)
        path.replace(rotated_path)

        try:
            if self._log_session is not None:
                rows = list(
                    self._log_session.scalars(
                        select(RunLogEntryModel).where(
                            RunLogEntryModel.log_file_ref == log_file_ref
                        )
                    )
                )
                for row in rows:
                    row.log_file_ref = rotated_ref
                    row.log_file_generation = generation
                self._log_session.commit()
        except Exception:
            if self._log_session is not None:
                self._log_session.rollback()
            if rotated_path.exists() and not path.exists():
                rotated_path.replace(path)
            raise

        return LogRotationResult(
            rotated=True,
            original_log_file_ref=log_file_ref,
            rotated_log_file_ref=rotated_ref,
            log_file_generation=generation,
            reason=reason,
        )

    def cleanup_run_logs(
        self,
        *,
        retention_days: int,
        run_ids: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> LogCleanupResult:
        if retention_days <= 0:
            raise ValueError("retention_days must be greater than zero")
        session = self._require_log_session()
        current_time = self._utc(now)
        cutoff = current_time - timedelta(days=retention_days)
        run_id_filter = set(run_ids) if run_ids is not None else None

        statement = select(RunLogEntryModel).where(RunLogEntryModel.created_at < cutoff)
        if run_id_filter is not None:
            statement = statement.where(RunLogEntryModel.run_id.in_(run_id_filter))
        expired_rows = list(session.scalars(statement.order_by(RunLogEntryModel.log_id.asc())))

        protected_rows = [row for row in expired_rows if self._is_protected_run_log(row)]
        deletable_rows = [row for row in expired_rows if row not in protected_rows]
        deleted_log_ids = tuple(row.log_id for row in deletable_rows)
        deleted_log_id_set = set(deleted_log_ids)
        protected_log_ids = tuple(row.log_id for row in protected_rows)

        candidate_file_refs = tuple(
            dict.fromkeys(
                row.log_file_ref
                for row in deletable_rows
                if row.log_file_ref and self._is_run_log_ref(row.log_file_ref)
            )
        )
        retained_file_refs: list[str] = []
        deletable_file_refs: list[str] = []
        for file_ref in candidate_file_refs:
            if self._has_retained_rows_for_file(session, file_ref, deleted_log_id_set):
                retained_file_refs.append(file_ref)
                continue
            path = self._resolve_runtime_ref(file_ref)
            if not self._is_under(path, self._run_logs_dir):
                retained_file_refs.append(file_ref)
                continue
            if path.exists():
                deletable_file_refs.append(file_ref)

        payload_refs = tuple(
            ref
            for ref in dict.fromkeys(row.payload_ref for row in deletable_rows)
            if ref is not None
        )
        deleted_file_refs: list[str] = []
        removed_file_backups: list[tuple[Path, bytes]] = []
        try:
            for file_ref in deletable_file_refs:
                path = self._resolve_runtime_ref(file_ref)
                if path.exists():
                    content = path.read_bytes()
                    path.unlink()
                    removed_file_backups.append((path, content))
                    deleted_file_refs.append(file_ref)

            for row in deletable_rows:
                session.delete(row)
            session.flush()

            deleted_payload_refs: list[str] = []
            for payload_ref in payload_refs:
                if self._payload_is_still_referenced(session, payload_ref, set()):
                    continue
                payload = session.get(LogPayloadModel, payload_ref)
                if payload is not None:
                    session.delete(payload)
                    deleted_payload_refs.append(payload_ref)
            session.commit()
        except Exception:
            session.rollback()
            for path, content in removed_file_backups:
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            raise

        return LogCleanupResult(
            cutoff=cutoff,
            deleted_log_ids=deleted_log_ids,
            deleted_payload_refs=tuple(deleted_payload_refs),
            deleted_file_refs=tuple(deleted_file_refs),
            retained_file_refs=tuple(retained_file_refs),
            protected_log_ids=protected_log_ids,
        )

    def mark_log_expired(self, log_id: str) -> bool:
        session = self._require_log_session()
        row = session.get(RunLogEntryModel, log_id)
        if row is None:
            return False
        row.message = EXPIRED_LOG_MESSAGE
        row.log_file_ref = EXPIRED_LOG_FILE_REF
        row.line_offset = 0
        row.line_number = 1
        row.log_file_generation = "expired"
        session.commit()
        return True

    def _require_log_session(self) -> Session:
        if self._log_session is None:
            raise ValueError("log_session is required for retention index updates")
        return self._log_session

    def _rotation_reason(
        self,
        size_bytes: int,
        modified_timestamp: float,
        max_bytes: int,
        now: datetime,
    ) -> str | None:
        if size_bytes >= max_bytes:
            return "size"
        modified_at = datetime.fromtimestamp(modified_timestamp, UTC)
        if modified_at.date() < now.date():
            return "date"
        return None

    def _rotated_path(self, path: Path, now: datetime) -> Path:
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        suffix = path.suffix
        stem = path.stem if suffix else path.name
        candidate = path.with_name(f"{stem}.{timestamp}{suffix}")
        counter = 1
        while candidate.exists():
            candidate = path.with_name(f"{stem}.{timestamp}.{counter}{suffix}")
            counter += 1
        return candidate

    def _is_protected_run_log(self, row: RunLogEntryModel) -> bool:
        return (
            row.category == LogCategory.SECURITY
            or row.approval_id is not None
            or row.tool_confirmation_id is not None
            or row.delivery_record_id is not None
        )

    def _has_retained_rows_for_file(
        self,
        session: Session,
        file_ref: str,
        deleted_log_ids: set[str],
    ) -> bool:
        statement = (
            select(RunLogEntryModel.log_id)
            .where(RunLogEntryModel.log_file_ref == file_ref)
            .where(RunLogEntryModel.log_id.not_in(deleted_log_ids))
            .limit(1)
        )
        return session.scalar(statement) is not None

    def _payload_is_still_referenced(
        self,
        session: Session,
        payload_ref: str,
        deleted_log_ids: set[str],
    ) -> bool:
        run_statement = (
            select(RunLogEntryModel.log_id)
            .where(RunLogEntryModel.payload_ref == payload_ref)
            .where(RunLogEntryModel.log_id.not_in(deleted_log_ids))
            .limit(1)
        )
        if session.scalar(run_statement) is not None:
            return True
        audit_statement = (
            select(AuditLogEntryModel.audit_id)
            .where(AuditLogEntryModel.metadata_ref == payload_ref)
            .limit(1)
        )
        return session.scalar(audit_statement) is not None

    def _resolve_runtime_ref(self, log_file_ref: str) -> Path:
        parts = self._validate_runtime_ref(log_file_ref)
        path = self._runtime_root.joinpath(*parts).resolve(strict=False)
        if not self._is_under(path, self._runtime_root):
            raise ValueError("log_file_ref must resolve under the runtime root")
        return path

    def _runtime_relative_ref(self, path: Path) -> str:
        path_text = self._absolute_path_text(path)
        root_text = self._absolute_path_text(self._runtime_root)
        common_path = os.path.commonpath([path_text, root_text])
        if os.path.normcase(common_path) != os.path.normcase(root_text):
            raise ValueError("log path must be under the runtime root")
        return Path(os.path.relpath(path_text, root_text)).as_posix()

    def _validate_runtime_ref(self, log_file_ref: str) -> tuple[str, ...]:
        normalized = log_file_ref.replace("\\", "/")
        parts = tuple(normalized.split("/"))
        if (
            not normalized
            or normalized.startswith("/")
            or ":" in normalized
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("log_file_ref must be relative to the runtime root")
        return parts

    def _is_run_log_ref(self, log_file_ref: str) -> bool:
        try:
            path = self._resolve_runtime_ref(log_file_ref)
        except ValueError:
            return False
        return self._is_under(path, self._run_logs_dir)

    def _is_under(self, path: Path, root: Path) -> bool:
        path_text = self._absolute_path_text(path)
        root_text = self._absolute_path_text(root)
        common_path = os.path.commonpath([path_text, root_text])
        return os.path.normcase(common_path) == os.path.normcase(root_text)

    def _absolute_path_text(self, path: Path) -> str:
        return os.path.normpath(
            self._without_windows_extended_prefix(os.path.abspath(os.fspath(path)))
        )

    def _without_windows_extended_prefix(self, path: str) -> str:
        if path.startswith("\\\\?\\UNC\\"):
            return "\\\\" + path[8:]
        if path.startswith("\\\\?\\"):
            return path[4:]
        return path

    def _utc(self, value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = [
    "EXPIRED_LOG_FILE_REF",
    "EXPIRED_LOG_MESSAGE",
    "LogCleanupResult",
    "LogRetentionService",
    "LogRotationResult",
]
