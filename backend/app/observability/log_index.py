from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from backend.app.db.models.log import LogPayloadModel, RunLogEntryModel
from backend.app.observability.log_writer import (
    JsonlLogWriter,
    JsonlWriteResult,
    LogPayloadSummary,
    LogRecordInput,
)
from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus


class _LogSession(Protocol):
    def add(self, instance: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True)
class LogIndexAppendResult:
    index_written: bool
    entry: RunLogEntryModel | None = None
    error_message: str | None = None


class LogIndexRepository:
    def __init__(
        self,
        session: _LogSession,
        *,
        failure_writer: JsonlLogWriter | None = None,
    ) -> None:
        self._session = session
        self._failure_writer = failure_writer

    def append_run_log_index(
        self,
        record: LogRecordInput,
        write_result: JsonlWriteResult,
    ) -> LogIndexAppendResult:
        try:
            payload = self._payload_model(record, write_result)
            entry = self._entry_model(record, write_result, payload.payload_id)
            self._session.add(payload)
            self._session.add(entry)
            self._session.commit()
            return LogIndexAppendResult(index_written=True, entry=entry)
        except SQLAlchemyError as exc:
            try:
                self._session.rollback()
            except Exception:
                pass
            self._write_index_failure(record, write_result, exc)
            return LogIndexAppendResult(
                index_written=False,
                error_message="Run log index write failed.",
            )

    def _payload_model(
        self,
        record: LogRecordInput,
        write_result: JsonlWriteResult,
    ) -> LogPayloadModel:
        payload = record.payload
        return LogPayloadModel(
            payload_id=f"payload-{write_result.log_id}",
            payload_type=payload.payload_type,
            summary=payload.summary,
            storage_ref=None,
            content_hash=payload.content_hash,
            redaction_status=payload.redaction_status,
            payload_size_bytes=payload.payload_size_bytes,
            schema_version="log-payload-v1",
            created_at=write_result.created_at,
        )

    def _entry_model(
        self,
        record: LogRecordInput,
        write_result: JsonlWriteResult,
        payload_id: str,
    ) -> RunLogEntryModel:
        trace = record.trace_context
        payload = record.payload
        return RunLogEntryModel(
            log_id=write_result.log_id,
            session_id=trace.session_id,
            run_id=trace.run_id,
            stage_run_id=trace.stage_run_id,
            approval_id=trace.approval_id,
            tool_confirmation_id=trace.tool_confirmation_id,
            delivery_record_id=trace.delivery_record_id,
            graph_thread_id=trace.graph_thread_id,
            request_id=trace.request_id,
            source=record.source,
            category=record.category,
            level=record.level,
            message=record.message,
            log_file_ref=write_result.log_file_ref,
            line_offset=write_result.line_offset,
            line_number=write_result.line_number,
            log_file_generation=write_result.log_file_generation,
            payload_ref=payload_id,
            payload_excerpt=payload.excerpt,
            payload_size_bytes=payload.payload_size_bytes,
            redaction_status=payload.redaction_status,
            correlation_id=trace.correlation_id,
            trace_id=trace.trace_id,
            span_id=trace.span_id,
            parent_span_id=trace.parent_span_id,
            duration_ms=record.duration_ms,
            error_code=record.error_code,
            created_at=write_result.created_at,
        )

    def _write_index_failure(
        self,
        record: LogRecordInput,
        write_result: JsonlWriteResult,
        exc: SQLAlchemyError,
    ) -> None:
        if self._failure_writer is None:
            return

        summary = {
            "failed_log_id": write_result.log_id,
            "failed_log_file_ref": write_result.log_file_ref,
            "error_type": type(exc).__name__,
        }
        serialized = json.dumps(summary, sort_keys=True, separators=(",", ":"))
        failure_payload = LogPayloadSummary(
            payload_type="log_index_failure",
            summary=summary,
            excerpt="Run log index write failed.",
            payload_size_bytes=len(serialized.encode("utf-8")),
            content_hash=f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}",
            redaction_status=RedactionStatus.NOT_REQUIRED,
        )
        child_trace = record.trace_context.child_span(
            span_id=f"span-log-index-failure-{uuid4().hex}",
            created_at=datetime.now(UTC),
        )
        try:
            self._failure_writer.write(
                LogRecordInput(
                    source="observability.log_index",
                    category=LogCategory.ERROR,
                    level=LogLevel.ERROR,
                    message="Run log index write failed.",
                    trace_context=child_trace,
                    payload=failure_payload,
                    created_at=datetime.now(UTC),
                    error_code="log_index_write_failed",
                )
            )
        except OSError:
            pass


__all__ = ["LogIndexAppendResult", "LogIndexRepository"]
