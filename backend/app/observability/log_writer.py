from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import ClassVar
from uuid import uuid4

from backend.app.domain.trace_context import TraceContext
from backend.app.observability.redaction import RedactedPayload
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus


@dataclass(frozen=True)
class LogPayloadSummary:
    payload_type: str
    summary: dict[str, object]
    excerpt: str | None
    payload_size_bytes: int
    content_hash: str
    redaction_status: RedactionStatus

    @classmethod
    def from_redacted_payload(
        cls,
        payload_type: str,
        payload: RedactedPayload,
    ) -> "LogPayloadSummary":
        return cls(
            payload_type=payload_type,
            summary=dict(payload.summary),
            excerpt=payload.excerpt,
            payload_size_bytes=payload.payload_size_bytes,
            content_hash=payload.content_hash,
            redaction_status=payload.redaction_status,
        )


@dataclass(frozen=True)
class LogRecordInput:
    source: str
    category: LogCategory
    level: LogLevel
    message: str
    trace_context: TraceContext
    payload: LogPayloadSummary
    created_at: datetime | None = None
    log_id: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class JsonlWriteResult:
    log_id: str
    log_file_ref: str
    line_offset: int
    line_number: int
    log_file_generation: str
    created_at: datetime


class JsonlLogWriter:
    _write_locks_guard: ClassVar[Lock] = Lock()
    _write_locks: ClassVar[dict[str, Lock]] = {}

    def __init__(self, runtime_settings: RuntimeDataSettings) -> None:
        self._runtime_root = runtime_settings.root.resolve(strict=False)
        self._logs_dir = runtime_settings.logs_dir.resolve(strict=False)
        self._run_logs_dir = runtime_settings.run_logs_dir.resolve(strict=False)

    def write(self, record: LogRecordInput) -> JsonlWriteResult:
        return self._write_to_path(self._logs_dir / "app.jsonl", "app", record)

    def write_run_log(self, record: LogRecordInput) -> JsonlWriteResult:
        run_id = record.trace_context.run_id
        if run_id is None:
            raise ValueError("run_id is required for run log writes")
        self._validate_run_id_segment(run_id)
        return self._write_to_path(
            self._run_logs_dir / f"{run_id}.jsonl",
            run_id,
            record,
        )

    def write_audit_copy(self, record: LogRecordInput) -> JsonlWriteResult:
        return self._write_to_path(self._logs_dir / "audit.jsonl", "audit", record)

    def _write_to_path(
        self,
        path: Path,
        generation: str,
        record: LogRecordInput,
    ) -> JsonlWriteResult:
        log_file_ref = self._runtime_relative_ref(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        log_id = record.log_id or f"log-{uuid4().hex}"
        created_at = record.created_at or datetime.now(UTC)
        payload = self._json_payload(
            record=record,
            log_id=log_id,
            created_at=created_at,
        )
        encoded = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        with self._write_lock_for_path(path):
            line_offset = path.stat().st_size if path.exists() else 0
            line_number = self._next_line_number(path)
            with path.open("ab") as file:
                file.write(encoded)
        return JsonlWriteResult(
            log_id=log_id,
            log_file_ref=log_file_ref,
            line_offset=line_offset,
            line_number=line_number,
            log_file_generation=generation,
            created_at=created_at,
        )

    def _json_payload(
        self,
        *,
        record: LogRecordInput,
        log_id: str,
        created_at: datetime,
    ) -> dict[str, object]:
        trace = record.trace_context
        payload = record.payload
        return {
            "schema_version": 1,
            "log_id": log_id,
            "created_at": created_at.isoformat(),
            "level": record.level.value,
            "category": record.category.value,
            "source": record.source,
            "message": record.message,
            "request_id": trace.request_id,
            "trace_id": trace.trace_id,
            "correlation_id": trace.correlation_id,
            "span_id": trace.span_id,
            "parent_span_id": trace.parent_span_id,
            "session_id": trace.session_id,
            "run_id": trace.run_id,
            "stage_run_id": trace.stage_run_id,
            "approval_id": trace.approval_id,
            "tool_confirmation_id": trace.tool_confirmation_id,
            "delivery_record_id": trace.delivery_record_id,
            "graph_thread_id": trace.graph_thread_id,
            "duration_ms": record.duration_ms,
            "error_code": record.error_code,
            "redaction_status": payload.redaction_status.value,
            "payload_type": payload.payload_type,
            "payload_summary": payload.summary,
            "payload_excerpt": payload.excerpt,
            "payload_size_bytes": payload.payload_size_bytes,
            "payload_content_hash": payload.content_hash,
        }

    def _runtime_relative_ref(self, path: Path) -> str:
        path_text = self._absolute_path_text(path)
        runtime_root_text = self._absolute_path_text(self._runtime_root)
        common_path = os.path.commonpath([path_text, runtime_root_text])
        if os.path.normcase(common_path) != os.path.normcase(runtime_root_text):
            raise ValueError(f"{path!s} is not under {self._runtime_root!s}")
        return Path(os.path.relpath(path_text, runtime_root_text)).as_posix()

    def _validate_run_id_segment(self, run_id: str) -> None:
        if (
            run_id in {".", ".."}
            or "/" in run_id
            or "\\" in run_id
            or ":" in run_id
            or "\0" in run_id
        ):
            raise ValueError("run_id must be a safe path segment")

    def _write_lock_for_path(self, path: Path) -> Lock:
        lock_key = os.path.normcase(self._absolute_path_text(path))
        with self._write_locks_guard:
            lock = self._write_locks.get(lock_key)
            if lock is None:
                lock = Lock()
                self._write_locks[lock_key] = lock
            return lock

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

    def _next_line_number(self, path: Path) -> int:
        if not path.exists():
            return 1
        with path.open("rb") as file:
            return sum(1 for _line in file) + 1


__all__ = [
    "JsonlLogWriter",
    "JsonlWriteResult",
    "LogPayloadSummary",
    "LogRecordInput",
]
