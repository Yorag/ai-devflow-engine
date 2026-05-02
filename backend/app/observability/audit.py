from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from backend.app.db.models.log import AuditLogEntryModel, LogPayloadModel
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import (
    JsonlLogWriter,
    JsonlWriteResult,
    LogPayloadSummary,
    LogRecordInput,
)
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
    RedactionStatus,
)


class _LogSession(Protocol):
    def add(self, instance: object) -> None: ...

    def flush(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class AuditWriteError(RuntimeError):
    def __init__(self, message: str = "Audit log entry write failed.") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class AuditRecordResult:
    audit_id: str
    entry: AuditLogEntryModel
    metadata_payload: LogPayloadModel
    audit_file_write_failed: bool
    audit_file_error_message: str | None = None


@dataclass(frozen=True)
class _AuditCopyResult:
    write_failed: bool
    write_result: JsonlWriteResult | None = None
    error_type: str | None = None


class AuditService:
    def __init__(
        self,
        session: _LogSession,
        *,
        audit_writer: JsonlLogWriter,
        redaction_policy: RedactionPolicy | None = None,
    ) -> None:
        self._session = session
        self._audit_writer = audit_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()

    def record_command_result(
        self,
        *,
        actor_type: AuditActorType,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        result: AuditResult,
        reason: str | None,
        metadata: dict[str, Any] | None,
        trace_context: TraceContext,
        created_at: datetime | None = None,
    ) -> AuditRecordResult:
        created = created_at or datetime.now(UTC)
        audit_id = f"audit-{uuid4().hex}"
        safe_reason = self._summarize_reason(reason)
        payload_summary = self._metadata_summary(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            reason=safe_reason,
            metadata=metadata or {},
        )
        payload = self._payload_model(audit_id, payload_summary, created)
        copy_result = self._try_write_audit_copy(
            audit_id=audit_id,
            result=result,
            trace_context=trace_context,
            payload=payload_summary,
            created_at=created,
        )
        entry = self._entry_model(
            audit_id=audit_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            reason=safe_reason,
            trace_context=trace_context,
            payload=payload,
            metadata_excerpt=payload_summary.excerpt,
            audit_file_ref=(
                copy_result.write_result.log_file_ref
                if copy_result.write_result is not None
                else None
            ),
            audit_file_generation=(
                copy_result.write_result.log_file_generation
                if copy_result.write_result is not None
                else None
            ),
            audit_file_write_failed=copy_result.write_failed,
            created_at=created,
        )
        self._persist_or_raise(payload, entry)

        if copy_result.error_type is not None:
            self._write_audit_copy_failure(
                audit_id=audit_id,
                trace_context=trace_context,
                created_at=created,
                error_type=copy_result.error_type,
            )
        return AuditRecordResult(
            audit_id=audit_id,
            entry=entry,
            metadata_payload=payload,
            audit_file_write_failed=copy_result.write_failed,
            audit_file_error_message=copy_result.error_type,
        )

    def record_rejected_command(
        self,
        *,
        actor_type: AuditActorType,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        reason: str,
        metadata: dict[str, Any] | None,
        trace_context: TraceContext,
        created_at: datetime | None = None,
    ) -> AuditRecordResult:
        return self.record_command_result(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=AuditResult.REJECTED,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
            created_at=created_at,
        )

    def record_failed_command(
        self,
        *,
        actor_type: AuditActorType,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        reason: str,
        metadata: dict[str, Any] | None,
        trace_context: TraceContext,
        created_at: datetime | None = None,
    ) -> AuditRecordResult:
        return self.record_command_result(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=AuditResult.FAILED,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
            created_at=created_at,
        )

    def _summarize_reason(self, reason: str | None) -> str | None:
        if reason is None:
            return None
        redacted = self._redaction_policy.summarize_text(
            reason,
            payload_type="audit_reason",
        )
        if isinstance(redacted.redacted_payload, str):
            return redacted.redacted_payload
        return redacted.excerpt

    def _metadata_summary(
        self,
        *,
        actor_type: AuditActorType,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        result: AuditResult,
        reason: str | None,
        metadata: dict[str, Any],
    ) -> LogPayloadSummary:
        redacted = self._redaction_policy.summarize_payload(
            {
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "result": result.value,
                "reason": reason,
                "metadata": metadata,
            },
            payload_type="audit_metadata_summary",
        )
        return LogPayloadSummary.from_redacted_payload(
            "audit_metadata_summary",
            redacted,
        )

    def _payload_model(
        self,
        audit_id: str,
        payload: LogPayloadSummary,
        created_at: datetime,
    ) -> LogPayloadModel:
        return LogPayloadModel(
            payload_id=f"payload-{audit_id}",
            payload_type="audit_metadata_summary",
            summary=payload.summary,
            storage_ref=None,
            content_hash=payload.content_hash,
            redaction_status=payload.redaction_status,
            payload_size_bytes=payload.payload_size_bytes,
            schema_version="log-payload-v1",
            created_at=created_at,
        )

    def _entry_model(
        self,
        *,
        audit_id: str,
        actor_type: AuditActorType,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        result: AuditResult,
        reason: str | None,
        trace_context: TraceContext,
        payload: LogPayloadModel,
        metadata_excerpt: str | None,
        audit_file_ref: str | None,
        audit_file_generation: str | None,
        audit_file_write_failed: bool,
        created_at: datetime,
    ) -> AuditLogEntryModel:
        return AuditLogEntryModel(
            audit_id=audit_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            session_id=trace_context.session_id,
            run_id=trace_context.run_id,
            stage_run_id=trace_context.stage_run_id,
            approval_id=trace_context.approval_id,
            tool_confirmation_id=trace_context.tool_confirmation_id,
            delivery_record_id=trace_context.delivery_record_id,
            request_id=trace_context.request_id,
            result=result,
            reason=reason,
            metadata_ref=payload.payload_id,
            metadata_excerpt=metadata_excerpt,
            correlation_id=trace_context.correlation_id,
            trace_id=trace_context.trace_id,
            span_id=trace_context.span_id,
            audit_file_ref=audit_file_ref,
            audit_file_generation=audit_file_generation,
            audit_file_write_failed=audit_file_write_failed,
            created_at=created_at,
        )

    def _try_write_audit_copy(
        self,
        *,
        audit_id: str,
        result: AuditResult,
        trace_context: TraceContext,
        payload: LogPayloadSummary,
        created_at: datetime,
    ) -> _AuditCopyResult:
        try:
            write_result = self._audit_writer.write_audit_copy(
                LogRecordInput(
                    source="observability.audit",
                    category=LogCategory.SECURITY,
                    level=self._level_for_result(result),
                    message="Control-plane command audit recorded.",
                    trace_context=trace_context,
                    payload=payload,
                    created_at=created_at,
                    log_id=audit_id,
                    error_code=(
                        "audit_command_failed"
                        if result is AuditResult.FAILED
                        else None
                    ),
                )
            )
            return _AuditCopyResult(write_failed=False, write_result=write_result)
        except OSError as exc:
            return _AuditCopyResult(write_failed=True, error_type=type(exc).__name__)

    def _level_for_result(self, result: AuditResult) -> LogLevel:
        if result is AuditResult.FAILED:
            return LogLevel.ERROR
        if result in {AuditResult.REJECTED, AuditResult.BLOCKED}:
            return LogLevel.WARNING
        return LogLevel.INFO

    def _persist_or_raise(
        self,
        payload: LogPayloadModel,
        entry: AuditLogEntryModel,
    ) -> None:
        try:
            self._session.add(payload)
            self._session.flush()
            self._session.add(entry)
            self._session.commit()
        except SQLAlchemyError as exc:
            try:
                self._session.rollback()
            except Exception:
                pass
            raise AuditWriteError("Audit log entry write failed.") from exc

    def _write_audit_copy_failure(
        self,
        *,
        audit_id: str,
        trace_context: TraceContext,
        created_at: datetime,
        error_type: str,
    ) -> None:
        summary = {
            "failed_audit_id": audit_id,
            "error_type": error_type,
        }
        serialized = json.dumps(summary, sort_keys=True, separators=(",", ":"))
        payload = LogPayloadSummary(
            payload_type="audit_file_write_failure",
            summary=summary,
            excerpt="Audit JSONL copy write failed.",
            payload_size_bytes=len(serialized.encode("utf-8")),
            content_hash=(
                f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"
            ),
            redaction_status=RedactionStatus.NOT_REQUIRED,
        )
        child_trace = trace_context.child_span(
            span_id=f"span-audit-copy-failure-{uuid4().hex}",
            created_at=created_at,
        )
        try:
            self._audit_writer.write(
                LogRecordInput(
                    source="observability.audit",
                    category=LogCategory.ERROR,
                    level=LogLevel.ERROR,
                    message="Audit JSONL copy write failed.",
                    trace_context=child_trace,
                    payload=payload,
                    created_at=created_at,
                    error_code="audit_jsonl_copy_write_failed",
                )
            )
        except OSError:
            pass


__all__ = [
    "AuditRecordResult",
    "AuditService",
    "AuditWriteError",
]
