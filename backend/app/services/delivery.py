from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.runtime import (
    DeliveryChannelSnapshotModel,
    DeliveryRecordModel,
    PipelineRunModel,
    StageRunModel,
)
from backend.app.delivery.base import DeliveryAdapter, DeliveryAdapterResult
from backend.app.domain.enums import DeliveryMode, StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
)


DELIVERY_RECORD_NOT_FOUND_MESSAGE = "DeliveryRecord was not found."
DELIVERY_RECORD_TARGET_NOT_FOUND_MESSAGE = "DeliveryRecord target was not found."
DELIVERY_RECORD_STAGE_MISMATCH_MESSAGE = (
    "DeliveryRecord requires the current delivery_integration stage."
)
DELIVERY_RECORD_SNAPSHOT_MISMATCH_MESSAGE = (
    "DeliveryRecord snapshot does not match the run."
)
DELIVERY_RECORD_MODE_MISMATCH_MESSAGE = (
    "Delivery adapter result mode does not match the frozen delivery snapshot."
)
DELIVERY_RECORD_STATUS_INVALID_MESSAGE = "DeliveryRecord status payload is invalid."
DELIVERY_ADAPTER_NOT_FOUND_MESSAGE = (
    "Delivery adapter was not found for the frozen delivery mode."
)
DELIVERY_ADAPTER_REGISTRY_INVALID_MESSAGE = "Delivery adapter registry is invalid."
LOG_SOURCE = "services.delivery"
ACTOR_ID = "delivery-service"
TERMINAL_DELIVERY_RECORD_STATUSES = frozenset({"succeeded", "failed", "blocked"})


class DeliveryServiceError(RuntimeError):
    def __init__(self, error_code: ErrorCode, message: str, status_code: int) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class DeliveryRecordService:
    def __init__(
        self,
        *,
        runtime_session: Session,
        audit_service: Any | None = None,
        log_writer: Any | None = None,
        redaction_policy: RedactionPolicy | None = None,
        auto_commit: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime_session = runtime_session
        self._audit_service = audit_service
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._auto_commit = auto_commit
        self._now = now or (lambda: datetime.now(UTC))

    def create_record(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        delivery_mode: DeliveryMode,
        status: str,
        result_ref: str | None = None,
        process_ref: str | None = None,
        branch_name: str | None = None,
        commit_sha: str | None = None,
        code_review_url: str | None = None,
        failure_reason: str | None = None,
        trace_context: TraceContext,
    ) -> DeliveryRecordModel:
        try:
            self._validate_status_payload(
                status=status,
                failure_reason=failure_reason,
            )
            run, stage, snapshot = self._validate_record_target(
                run_id=run_id,
                stage_run_id=stage_run_id,
                delivery_mode=delivery_mode,
                trace_context=trace_context,
            )
        except DeliveryServiceError as exc:
            self._record_rejected(
                target_id=run_id,
                reason=exc.message,
                metadata={
                    **self._base_metadata(
                        run_id=run_id,
                        stage_run_id=stage_run_id,
                        delivery_mode=delivery_mode,
                    ),
                    "status": status,
                    "error_code": exc.error_code.value,
                },
                trace_context=trace_context,
            )
            self._write_log(
                message="DeliveryRecord creation rejected.",
                level=LogLevel.WARNING,
                metadata={
                    **self._base_metadata(
                        run_id=run_id,
                        stage_run_id=stage_run_id,
                        delivery_mode=delivery_mode,
                    ),
                    "status": status,
                    "error_code": exc.error_code.value,
                },
                trace_context=trace_context,
                error_code=exc.error_code.value,
            )
            raise

        created_at = self._now()
        record = DeliveryRecordModel(
            delivery_record_id=f"delivery-record-{uuid4().hex}",
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            delivery_channel_snapshot_ref=snapshot.delivery_channel_snapshot_id,
            delivery_mode=delivery_mode,
            status=status,
            branch_name=branch_name,
            commit_sha=commit_sha,
            code_review_url=code_review_url,
            result_ref=result_ref,
            process_ref=process_ref,
            failure_reason=failure_reason,
            created_at=created_at,
            completed_at=(
                created_at if status in {"succeeded", "failed", "blocked"} else None
            ),
        )
        metadata = self._record_metadata(
            record=record,
            snapshot=snapshot,
            trace_context=trace_context,
        )
        try:
            self._runtime_session.add(record)
            self._runtime_session.flush()
            self._require_audit(
                action="delivery_record.create",
                target_id=record.delivery_record_id,
                metadata=metadata,
                trace_context=trace_context.model_copy(
                    update={"delivery_record_id": record.delivery_record_id}
                ),
                created_at=created_at,
            )
            if self._auto_commit:
                self._runtime_session.commit()
            self._write_log(
                message="DeliveryRecord created.",
                level=LogLevel.INFO,
                metadata=metadata,
                trace_context=trace_context.model_copy(
                    update={"delivery_record_id": record.delivery_record_id}
                ),
            )
            return record
        except Exception as exc:
            self._runtime_session.rollback()
            self._record_failed(
                target_id=record.delivery_record_id,
                reason=str(exc) or type(exc).__name__,
                metadata={**metadata, "error_type": type(exc).__name__},
                trace_context=trace_context.model_copy(
                    update={"delivery_record_id": record.delivery_record_id}
                ),
            )
            raise

    def get_record(self, delivery_record_id: str) -> DeliveryRecordModel:
        record = self._runtime_session.get(
            DeliveryRecordModel,
            delivery_record_id,
            populate_existing=True,
        )
        if record is None:
            raise DeliveryServiceError(
                ErrorCode.NOT_FOUND,
                DELIVERY_RECORD_NOT_FOUND_MESSAGE,
                404,
            )
        return record

    def record_adapter_selection_rejected(
        self,
        *,
        delivery_mode: DeliveryMode,
        trace_context: TraceContext,
    ) -> None:
        metadata = {
            "run_id": trace_context.run_id,
            "stage_run_id": trace_context.stage_run_id,
            "delivery_mode": delivery_mode.value,
            "error_code": ErrorCode.NOT_FOUND.value,
        }
        if self._audit_service is not None:
            self._audit_service.record_rejected_command(
                actor_type=AuditActorType.SYSTEM,
                actor_id=ACTOR_ID,
                action="delivery_adapter.select.rejected",
                target_type="delivery_adapter",
                target_id=delivery_mode.value,
                reason=DELIVERY_ADAPTER_NOT_FOUND_MESSAGE,
                metadata=metadata,
                trace_context=trace_context,
                created_at=self._now(),
            )
        self._write_log(
            message="Delivery adapter selection rejected.",
            level=LogLevel.WARNING,
            metadata=metadata,
            trace_context=trace_context,
            error_code=ErrorCode.NOT_FOUND.value,
        )

    def _validate_record_target(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        delivery_mode: DeliveryMode,
        trace_context: TraceContext,
    ) -> tuple[PipelineRunModel, StageRunModel, DeliveryChannelSnapshotModel]:
        run = self._runtime_session.get(
            PipelineRunModel,
            run_id,
            populate_existing=True,
        )
        if run is None:
            raise DeliveryServiceError(
                ErrorCode.NOT_FOUND,
                DELIVERY_RECORD_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        stage = self._runtime_session.get(
            StageRunModel,
            stage_run_id,
            populate_existing=True,
        )
        if stage is None or stage.run_id != run.run_id:
            raise DeliveryServiceError(
                ErrorCode.NOT_FOUND,
                DELIVERY_RECORD_TARGET_NOT_FOUND_MESSAGE,
                404,
            )
        if stage.stage_type is not StageType.DELIVERY_INTEGRATION:
            raise DeliveryServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_RECORD_STAGE_MISMATCH_MESSAGE,
                409,
            )
        if run.current_stage_run_id != stage.stage_run_id:
            raise DeliveryServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_RECORD_STAGE_MISMATCH_MESSAGE,
                409,
            )
        if not run.delivery_channel_snapshot_ref:
            raise DeliveryServiceError(
                ErrorCode.DELIVERY_SNAPSHOT_MISSING,
                DELIVERY_RECORD_SNAPSHOT_MISMATCH_MESSAGE,
                409,
            )
        snapshot = self._runtime_session.get(
            DeliveryChannelSnapshotModel,
            run.delivery_channel_snapshot_ref,
            populate_existing=True,
        )
        if (
            snapshot is None
            or snapshot.run_id != run.run_id
            or snapshot.delivery_channel_snapshot_id != run.delivery_channel_snapshot_ref
        ):
            raise DeliveryServiceError(
                ErrorCode.DELIVERY_SNAPSHOT_MISSING,
                DELIVERY_RECORD_SNAPSHOT_MISMATCH_MESSAGE,
                409,
            )
        if delivery_mode is not snapshot.delivery_mode:
            raise DeliveryServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_RECORD_MODE_MISMATCH_MESSAGE,
                409,
            )
        if (
            trace_context.run_id is not None
            and trace_context.run_id != run.run_id
        ):
            raise DeliveryServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_RECORD_TARGET_NOT_FOUND_MESSAGE,
                409,
            )
        if (
            trace_context.stage_run_id is not None
            and trace_context.stage_run_id != stage.stage_run_id
        ):
            raise DeliveryServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_RECORD_TARGET_NOT_FOUND_MESSAGE,
                409,
            )
        return run, stage, snapshot

    @staticmethod
    def _validate_status_payload(
        *,
        status: str,
        failure_reason: str | None,
    ) -> None:
        if status not in TERMINAL_DELIVERY_RECORD_STATUSES:
            raise DeliveryServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_RECORD_STATUS_INVALID_MESSAGE,
                409,
            )
        if status == "succeeded" and failure_reason is not None:
            raise DeliveryServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_RECORD_STATUS_INVALID_MESSAGE,
                409,
            )
        if status != "succeeded" and failure_reason is None:
            raise DeliveryServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_RECORD_STATUS_INVALID_MESSAGE,
                409,
            )

    def _require_audit(
        self,
        *,
        action: str,
        target_id: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
    ) -> None:
        if self._audit_service is None:
            return
        self._audit_service.require_audit_record(
            actor_type=AuditActorType.SYSTEM,
            actor_id=ACTOR_ID,
            action=action,
            target_type="delivery_record",
            target_id=target_id,
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata=metadata,
            trace_context=trace_context,
            rollback=self._runtime_session.rollback,
            created_at=created_at,
        )

    def _record_rejected(
        self,
        *,
        target_id: str,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        if self._audit_service is not None:
            self._audit_service.record_rejected_command(
                actor_type=AuditActorType.SYSTEM,
                actor_id=ACTOR_ID,
                action="delivery_record.create.rejected",
                target_type="delivery_record",
                target_id=target_id,
                reason=reason,
                metadata=metadata,
                trace_context=trace_context,
                created_at=self._now(),
            )

    def _record_failed(
        self,
        *,
        target_id: str,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        if self._audit_service is not None:
            try:
                self._audit_service.record_failed_command(
                    actor_type=AuditActorType.SYSTEM,
                    actor_id=ACTOR_ID,
                    action="delivery_record.create.failed",
                    target_type="delivery_record",
                    target_id=target_id,
                    reason=reason,
                    metadata=metadata,
                    trace_context=trace_context,
                    created_at=self._now(),
                )
            except Exception:
                pass
        try:
            self._write_log(
                message="DeliveryRecord creation failed.",
                level=LogLevel.ERROR,
                metadata=metadata,
                trace_context=trace_context,
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )
        except Exception:
            pass

    def _write_log(
        self,
        *,
        message: str,
        level: LogLevel,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        error_code: str | None = None,
    ) -> None:
        if self._log_writer is None:
            return
        redacted = self._redaction_policy.summarize_payload(
            metadata,
            payload_type="delivery_record",
        )
        self._log_writer.write_run_log(
            LogRecordInput(
                source=LOG_SOURCE,
                category=LogCategory.DELIVERY,
                level=level,
                message=message,
                trace_context=trace_context,
                payload=LogPayloadSummary.from_redacted_payload(
                    "delivery_record",
                    redacted,
                ),
                created_at=self._now(),
                error_code=error_code,
            )
        )

    def _base_metadata(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        delivery_mode: DeliveryMode,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "stage_run_id": stage_run_id,
            "delivery_mode": delivery_mode.value,
        }

    def _record_metadata(
        self,
        *,
        record: DeliveryRecordModel,
        snapshot: DeliveryChannelSnapshotModel,
        trace_context: TraceContext,
    ) -> dict[str, Any]:
        return {
            "run_id": record.run_id,
            "stage_run_id": record.stage_run_id,
            "delivery_record_id": record.delivery_record_id,
            "delivery_channel_snapshot_ref": record.delivery_channel_snapshot_ref,
            "delivery_mode": record.delivery_mode.value,
            "status": record.status,
            "result_ref": record.result_ref,
            "process_ref": record.process_ref,
            "branch_name": record.branch_name,
            "commit_sha": record.commit_sha,
            "code_review_url": record.code_review_url,
            "snapshot_run_id": snapshot.run_id,
            "request_id": trace_context.request_id,
            "trace_id": trace_context.trace_id,
            "correlation_id": trace_context.correlation_id,
            "span_id": trace_context.span_id,
        }


class DeliveryService:
    def __init__(
        self,
        *,
        record_service: DeliveryRecordService,
        adapters: Mapping[DeliveryMode, DeliveryAdapter] | Sequence[DeliveryAdapter] | None = None,
    ) -> None:
        self._record_service = record_service
        self._adapters = self._normalize_adapters(adapters)

    def get_adapter(
        self,
        delivery_mode: DeliveryMode,
        *,
        trace_context: TraceContext,
    ) -> DeliveryAdapter:
        adapter = self._adapters.get(delivery_mode)
        if adapter is None:
            self._record_service.record_adapter_selection_rejected(
                delivery_mode=delivery_mode,
                trace_context=trace_context,
            )
            raise DeliveryServiceError(
                ErrorCode.NOT_FOUND,
                DELIVERY_ADAPTER_NOT_FOUND_MESSAGE,
                404,
            )
        return adapter

    def create_delivery_record_from_adapter_result(
        self,
        *,
        adapter_result: DeliveryAdapterResult,
    ) -> DeliveryRecordModel:
        return self._record_service.create_record(
            run_id=adapter_result.run_id,
            stage_run_id=adapter_result.stage_run_id,
            delivery_mode=adapter_result.delivery_mode,
            status=adapter_result.status,
            result_ref=adapter_result.result_ref,
            process_ref=adapter_result.process_ref,
            branch_name=adapter_result.branch_name,
            commit_sha=adapter_result.commit_sha,
            code_review_url=adapter_result.code_review_url,
            failure_reason=(
                adapter_result.error.safe_message
                if adapter_result.error is not None
                else None
            ),
            trace_context=adapter_result.trace_context,
        )

    @staticmethod
    def _normalize_adapters(
        adapters: Mapping[DeliveryMode, DeliveryAdapter] | Sequence[DeliveryAdapter] | None,
    ) -> dict[DeliveryMode, DeliveryAdapter]:
        if adapters is None:
            return {}
        if isinstance(adapters, Mapping):
            normalized: dict[DeliveryMode, DeliveryAdapter] = {}
            for delivery_mode, adapter in adapters.items():
                if delivery_mode is not adapter.delivery_mode:
                    raise DeliveryServiceError(
                        ErrorCode.VALIDATION_ERROR,
                        (
                            f"{DELIVERY_ADAPTER_REGISTRY_INVALID_MESSAGE} "
                            f"Mapping key {delivery_mode.value!r} does not match "
                            f"adapter mode {adapter.delivery_mode.value!r}."
                        ),
                        409,
                    )
                normalized[delivery_mode] = adapter
            return normalized

        normalized = {}
        for adapter in adapters:
            if adapter.delivery_mode in normalized:
                raise DeliveryServiceError(
                    ErrorCode.VALIDATION_ERROR,
                    (
                        f"{DELIVERY_ADAPTER_REGISTRY_INVALID_MESSAGE} "
                        f"duplicate adapter registration for "
                        f"{adapter.delivery_mode.value!r}."
                    ),
                    409,
                )
            normalized[adapter.delivery_mode] = adapter
        return normalized


__all__ = [
    "DELIVERY_ADAPTER_NOT_FOUND_MESSAGE",
    "DELIVERY_RECORD_MODE_MISMATCH_MESSAGE",
    "DELIVERY_RECORD_NOT_FOUND_MESSAGE",
    "DELIVERY_RECORD_SNAPSHOT_MISMATCH_MESSAGE",
    "DELIVERY_RECORD_STAGE_MISMATCH_MESSAGE",
    "DELIVERY_RECORD_STATUS_INVALID_MESSAGE",
    "DELIVERY_RECORD_TARGET_NOT_FOUND_MESSAGE",
    "DeliveryRecordService",
    "DeliveryService",
    "DeliveryServiceError",
]
