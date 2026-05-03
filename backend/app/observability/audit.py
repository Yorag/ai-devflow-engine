from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import PlatformRuntimeSettingsModel
from backend.app.db.models.log import AuditLogEntryModel, LogPayloadModel
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import (
    JsonlLogWriter,
    JsonlWriteResult,
    LogPayloadSummary,
    LogRecordInput,
)
from backend.app.observability.redaction import RedactionPolicy
from backend.app.repositories.runtime_settings import RUNTIME_SETTINGS_ID
from backend.app.schemas.observability import (
    AuditActorType,
    AuditLogEntryProjection,
    AuditLogQuery,
    AuditLogQueryResponse,
    AuditResult,
    LogCategory,
    LogLevel,
    RedactionStatus,
)
from backend.app.schemas.runtime_settings import LogPolicy, PlatformHardLimits


INVALID_LOG_QUERY_MESSAGE = "Log query is invalid."
CONFIG_SNAPSHOT_UNAVAILABLE_MESSAGE = "Configuration snapshot is unavailable."


class _LogSession(Protocol):
    def add(self, instance: object) -> None: ...

    def flush(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class _AuditQueryLogSession(_LogSession, Protocol):
    def scalars(self, statement: object) -> Any: ...


class _ControlSession(Protocol):
    def get(self, entity: object, ident: object) -> object | None: ...


class AuditWriteError(RuntimeError):
    def __init__(self, message: str = "Audit log entry write failed.") -> None:
        super().__init__(message)


class AuditQueryServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
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
        control_session: _ControlSession | None = None,
        redaction_policy: RedactionPolicy | None = None,
    ) -> None:
        self._session = session
        self._control_session = control_session
        self._audit_writer = audit_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()

    def list_audit_logs(
        self,
        *,
        actor_type: AuditActorType | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        run_id: str | None = None,
        stage_run_id: str | None = None,
        correlation_id: str | None = None,
        result: AuditResult | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> AuditLogQueryResponse:
        effective_limit = self._effective_query_limit(limit)
        decoded_cursor = self.decode_cursor(cursor) if cursor is not None else None
        query_echo = self._audit_query_echo(
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            correlation_id=correlation_id,
            result=result,
            since=since,
            until=until,
            cursor=cursor,
            limit=effective_limit,
        )
        return self._list_audit_log_rows(
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            correlation_id=correlation_id,
            result=result,
            since=since,
            until=until,
            cursor=decoded_cursor,
            limit=effective_limit,
            query_echo=query_echo,
        )

    def encode_cursor(self, created_at: datetime, audit_id: str) -> str:
        payload = {"created_at": created_at.isoformat(), "audit_id": audit_id}
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        return encoded.decode("ascii")

    def decode_cursor(self, cursor: str) -> tuple[datetime, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
            payload = json.loads(raw.decode("utf-8"))
            created_at = datetime.fromisoformat(payload["created_at"])
            audit_id = payload["audit_id"]
        except (
            UnicodeEncodeError,
            binascii.Error,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise self._invalid_query() from exc
        if not isinstance(audit_id, str) or not audit_id:
            raise self._invalid_query()
        return created_at, audit_id

    def _list_audit_log_rows(
        self,
        *,
        actor_type: AuditActorType | None,
        action: str | None,
        target_type: str | None,
        target_id: str | None,
        run_id: str | None,
        stage_run_id: str | None,
        correlation_id: str | None,
        result: AuditResult | None,
        since: datetime | None,
        until: datetime | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
        query_echo: AuditLogQuery,
    ) -> AuditLogQueryResponse:
        statement = select(AuditLogEntryModel)
        if actor_type is not None:
            statement = statement.where(AuditLogEntryModel.actor_type == actor_type)
        if action is not None:
            statement = statement.where(AuditLogEntryModel.action == action)
        if target_type is not None:
            statement = statement.where(AuditLogEntryModel.target_type == target_type)
        if target_id is not None:
            statement = statement.where(AuditLogEntryModel.target_id == target_id)
        if run_id is not None:
            statement = statement.where(AuditLogEntryModel.run_id == run_id)
        if stage_run_id is not None:
            statement = statement.where(AuditLogEntryModel.stage_run_id == stage_run_id)
        if correlation_id is not None:
            statement = statement.where(
                AuditLogEntryModel.correlation_id == correlation_id
            )
        if result is not None:
            statement = statement.where(AuditLogEntryModel.result == result)
        if since is not None:
            statement = statement.where(AuditLogEntryModel.created_at >= since)
        if until is not None:
            statement = statement.where(AuditLogEntryModel.created_at <= until)
        if cursor is not None:
            cursor_created_at, cursor_audit_id = cursor
            statement = statement.where(
                or_(
                    AuditLogEntryModel.created_at < cursor_created_at,
                    and_(
                        AuditLogEntryModel.created_at == cursor_created_at,
                        AuditLogEntryModel.audit_id < cursor_audit_id,
                    ),
                )
            )
        statement = statement.order_by(
            AuditLogEntryModel.created_at.desc(),
            AuditLogEntryModel.audit_id.desc(),
        ).limit(limit + 1)

        rows = list(self._session.scalars(statement))
        page_rows = rows[:limit]
        has_more = len(rows) > limit
        next_cursor = (
            self.encode_cursor(page_rows[-1].created_at, page_rows[-1].audit_id)
            if has_more and page_rows
            else None
        )
        return AuditLogQueryResponse(
            entries=[self._to_audit_projection(row) for row in page_rows],
            next_cursor=next_cursor,
            has_more=has_more,
            query=query_echo,
        )

    def _effective_query_limit(self, requested_limit: int | None) -> int:
        log_policy = self._current_log_policy()
        effective_limit = (
            log_policy.log_query_default_limit
            if requested_limit is None
            else requested_limit
        )
        if effective_limit <= 0 or effective_limit > log_policy.log_query_max_limit:
            raise self._invalid_query()
        return effective_limit

    def _audit_query_echo(
        self,
        *,
        actor_type: AuditActorType | None,
        action: str | None,
        target_type: str | None,
        target_id: str | None,
        run_id: str | None,
        stage_run_id: str | None,
        correlation_id: str | None,
        result: AuditResult | None,
        since: datetime | None,
        until: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> AuditLogQuery:
        try:
            return AuditLogQuery(
                actor_type=actor_type,
                action=action,
                target_type=target_type,
                target_id=target_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                correlation_id=correlation_id,
                result=result,
                since=since,
                until=until,
                cursor=cursor,
                limit=limit,
            )
        except ValidationError as exc:
            raise self._invalid_query() from exc

    def _current_log_policy(self) -> LogPolicy:
        if self._control_session is None:
            raise self._config_unavailable()
        try:
            model = self._control_session.get(
                PlatformRuntimeSettingsModel,
                RUNTIME_SETTINGS_ID,
            )
        except SQLAlchemyError as exc:
            raise self._config_unavailable() from exc
        if model is None:
            raise self._config_unavailable()
        if not self._has_required_log_query_limit_fields(model.log_policy):
            raise self._config_unavailable()
        try:
            log_policy = LogPolicy.model_validate(model.log_policy)
        except ValidationError as exc:
            raise self._config_unavailable() from exc
        hard_limit = PlatformHardLimits().log_policy.log_query_max_limit
        if (
            log_policy.log_query_max_limit > hard_limit
            or log_policy.log_query_default_limit > log_policy.log_query_max_limit
        ):
            raise self._config_unavailable()
        return log_policy

    @staticmethod
    def _has_required_log_query_limit_fields(log_policy: Any) -> bool:
        if not isinstance(log_policy, dict):
            return False
        return {
            "log_query_default_limit",
            "log_query_max_limit",
        } <= log_policy.keys()

    @staticmethod
    def _to_audit_projection(row: AuditLogEntryModel) -> AuditLogEntryProjection:
        return AuditLogEntryProjection(
            audit_id=row.audit_id,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            session_id=row.session_id,
            run_id=row.run_id,
            stage_run_id=row.stage_run_id,
            approval_id=row.approval_id,
            tool_confirmation_id=row.tool_confirmation_id,
            delivery_record_id=row.delivery_record_id,
            request_id=row.request_id,
            result=row.result,
            reason=row.reason,
            metadata_ref=row.metadata_ref,
            metadata_excerpt=row.metadata_excerpt,
            correlation_id=row.correlation_id,
            trace_id=row.trace_id,
            span_id=row.span_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _invalid_query() -> AuditQueryServiceError:
        return AuditQueryServiceError(
            ErrorCode.LOG_QUERY_INVALID,
            INVALID_LOG_QUERY_MESSAGE,
            422,
        )

    @staticmethod
    def _config_unavailable() -> AuditQueryServiceError:
        return AuditQueryServiceError(
            ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
            CONFIG_SNAPSHOT_UNAVAILABLE_MESSAGE,
            503,
        )

    def require_audit_record(
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
        rollback: Callable[[], None] | None = None,
        created_at: datetime | None = None,
    ) -> AuditRecordResult:
        try:
            return self.record_command_result(
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                result=result,
                reason=reason,
                metadata=metadata,
                trace_context=trace_context,
                created_at=created_at,
            )
        except AuditWriteError as exc:
            if rollback is not None:
                try:
                    rollback()
                except Exception:
                    pass
            raise AuditWriteError(
                f"Required audit record for action {action!r} could not be "
                "written; reject or roll back high-impact action."
            ) from exc

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
            audit_file_ref=None,
            audit_file_generation=None,
            audit_file_write_failed=False,
            created_at=created,
        )
        self._persist_or_raise(payload, entry)

        copy_result = self._try_write_audit_copy(
            audit_id=audit_id,
            result=result,
            trace_context=trace_context,
            payload=payload_summary,
            created_at=created,
        )
        self._record_audit_copy_result_or_raise(entry, copy_result)

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

    def record_tool_call(
        self,
        *,
        tool_name: str,
        command: str,
        exit_code: int,
        duration_ms: int,
        changed_files: list[str],
        stdout_excerpt: str,
        stderr_excerpt: str,
        trace_context: TraceContext,
        created_at: datetime | None = None,
        **metadata_overrides: Any,
    ) -> AuditRecordResult:
        metadata = {
            "command": command,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "changed_files": changed_files,
            "stdout_excerpt": stdout_excerpt,
            "stderr_excerpt": stderr_excerpt,
            **metadata_overrides,
        }
        return self.record_command_result(
            actor_type=AuditActorType.SYSTEM,
            actor_id=tool_name,
            action=f"tool.{tool_name}.succeeded",
            target_type="tool_action",
            target_id=self._tool_target_id(tool_name, trace_context),
            result=AuditResult.SUCCEEDED,
            reason="Tool call completed.",
            metadata=metadata,
            trace_context=trace_context,
            created_at=created_at,
        )

    def record_tool_error(
        self,
        *,
        tool_name: str,
        command: str,
        error_code: ErrorCode | str,
        result: AuditResult,
        reason: str,
        metadata: dict[str, Any] | None,
        trace_context: TraceContext,
        created_at: datetime | None = None,
        **metadata_overrides: Any,
    ) -> AuditRecordResult:
        action_suffix = "blocked" if result is AuditResult.BLOCKED else "failed"
        audit_metadata = {
            "command": command,
            "error_code": str(error_code),
            **(metadata or {}),
            **metadata_overrides,
        }
        if result is AuditResult.BLOCKED:
            return self.record_blocked_action(
                actor_type=AuditActorType.SYSTEM,
                actor_id=tool_name,
                action=f"tool.{tool_name}.{action_suffix}",
                target_type="tool_action",
                target_id=self._tool_target_id(tool_name, trace_context),
                reason=reason,
                metadata=audit_metadata,
                trace_context=trace_context,
                created_at=created_at,
            )
        return self.record_failed_command(
            actor_type=AuditActorType.SYSTEM,
            actor_id=tool_name,
            action=f"tool.{tool_name}.{action_suffix}",
            target_type="tool_action",
            target_id=self._tool_target_id(tool_name, trace_context),
            reason=reason,
            metadata=audit_metadata,
            trace_context=trace_context,
            created_at=created_at,
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
        return self.require_audit_record(
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

    def record_blocked_action(
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
        return self.require_audit_record(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=AuditResult.BLOCKED,
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

    @staticmethod
    def _tool_target_id(tool_name: str, trace_context: TraceContext) -> str:
        return f"{tool_name}:{trace_context.run_id or 'unknown'}:{trace_context.span_id}"

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

    def _record_audit_copy_result_or_raise(
        self,
        entry: AuditLogEntryModel,
        copy_result: _AuditCopyResult,
    ) -> None:
        if copy_result.write_result is not None:
            entry.audit_file_ref = copy_result.write_result.log_file_ref
            entry.audit_file_generation = copy_result.write_result.log_file_generation
            entry.audit_file_write_failed = False
        else:
            entry.audit_file_ref = None
            entry.audit_file_generation = None
            entry.audit_file_write_failed = copy_result.write_failed
        try:
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
    "AuditQueryServiceError",
    "AuditRecordResult",
    "AuditService",
    "AuditWriteError",
]
