from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import DeliveryChannelModel
from backend.app.db.models.runtime import DeliveryChannelSnapshotModel, PipelineRunModel
from backend.app.domain.enums import (
    ApprovalType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    StageType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
)
from backend.app.services.delivery_channels import (
    API_ACTOR_ID,
    DeliveryChannelService,
)


DELIVERY_SNAPSHOT_SCHEMA_VERSION = "delivery-channel-snapshot-v1"
DELIVERY_SNAPSHOT_GATE_CONTEXT_MESSAGE = (
    "Delivery snapshot can be prepared only for code_review_approval before "
    "delivery_integration."
)
DELIVERY_SNAPSHOT_NOT_READY_MESSAGE = "DeliveryChannel is not ready for delivery snapshot."
DELIVERY_SNAPSHOT_MISSING_MESSAGE = "Delivery snapshot is missing for this run."
DELIVERY_SNAPSHOT_NOT_READY_FOR_DELIVERY_MESSAGE = (
    "Delivery snapshot is not ready for delivery."
)
LOG_SOURCE = "services.delivery_snapshots"


class DeliverySnapshotServiceError(RuntimeError):
    def __init__(self, error_code: ErrorCode, message: str, status_code: int) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class DeliverySnapshotService:
    def __init__(
        self,
        *,
        control_session: Session,
        runtime_session: Session,
        delivery_channel_service: DeliveryChannelService,
        audit_service: Any,
        log_writer: Any,
        redaction_policy: RedactionPolicy | None = None,
        auto_commit: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._delivery_channel_service = delivery_channel_service
        self._audit_service = audit_service
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._auto_commit = auto_commit
        self._now = now or (lambda: datetime.now(UTC))

    def prepare_delivery_snapshot(
        self,
        *,
        run_id: str,
        project_id: str,
        approval_type: ApprovalType,
        target_stage_type: StageType,
        trace_context: TraceContext,
    ) -> DeliveryChannelSnapshotModel:
        if (
            approval_type is not ApprovalType.CODE_REVIEW_APPROVAL
            or target_stage_type is not StageType.DELIVERY_INTEGRATION
        ):
            metadata = self._base_metadata(
                run_id=run_id,
                project_id=project_id,
                approval_type=approval_type,
                target_stage_type=target_stage_type,
            )
            self._record_rejected(
                target_id=run_id,
                reason=DELIVERY_SNAPSHOT_GATE_CONTEXT_MESSAGE,
                metadata=metadata,
                trace_context=trace_context,
            )
            self._write_log(
                message="Delivery snapshot preparation rejected.",
                level=LogLevel.WARNING,
                metadata=metadata,
                trace_context=trace_context,
                error_code=ErrorCode.VALIDATION_ERROR.value,
            )
            raise DeliverySnapshotServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELIVERY_SNAPSHOT_GATE_CONTEXT_MESSAGE,
                409,
            )

        run = self._runtime_session.get(
            PipelineRunModel,
            run_id,
            populate_existing=True,
        )
        if run is None:
            metadata = self._base_metadata(
                run_id=run_id,
                project_id=project_id,
                approval_type=approval_type,
                target_stage_type=target_stage_type,
            )
            self._record_rejected(
                target_id=run_id,
                reason=DELIVERY_SNAPSHOT_MISSING_MESSAGE,
                metadata=metadata,
                trace_context=trace_context,
            )
            self._write_log(
                message="Delivery snapshot preparation rejected.",
                level=LogLevel.WARNING,
                metadata=metadata,
                trace_context=trace_context,
                error_code=ErrorCode.NOT_FOUND.value,
            )
            raise DeliverySnapshotServiceError(
                ErrorCode.NOT_FOUND,
                DELIVERY_SNAPSHOT_MISSING_MESSAGE,
                404,
            )
        if run.project_id != project_id:
            metadata = self._base_metadata(
                run_id=run_id,
                project_id=project_id,
                approval_type=approval_type,
                target_stage_type=target_stage_type,
            )
            metadata["run_project_id"] = run.project_id
            self._record_rejected(
                target_id=run_id,
                reason="PipelineRun project does not match the requested project.",
                metadata=metadata,
                trace_context=trace_context,
            )
            self._write_log(
                message="Delivery snapshot preparation rejected.",
                level=LogLevel.WARNING,
                metadata=metadata,
                trace_context=trace_context,
                error_code=ErrorCode.VALIDATION_ERROR.value,
            )
            raise DeliverySnapshotServiceError(
                ErrorCode.VALIDATION_ERROR,
                "PipelineRun project does not match the requested project.",
                409,
            )

        existing = self._existing_snapshot(run)
        if existing is not None:
            return existing

        channel = self._delivery_channel_service.resolve_current_project_channel(
            project_id,
            trace_context=trace_context,
        )
        metadata = self._snapshot_metadata(
            run_id=run_id,
            project_id=project_id,
            channel=channel,
            approval_type=approval_type,
            target_stage_type=target_stage_type,
        )
        if (
            channel.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
            and (
                channel.readiness_status is not DeliveryReadinessStatus.READY
                or channel.credential_status is not CredentialStatus.READY
            )
        ):
            if self._auto_commit:
                self._runtime_session.rollback()
            self._record_rejected(
                target_id=run_id,
                reason=DELIVERY_SNAPSHOT_NOT_READY_MESSAGE,
                metadata=metadata,
                trace_context=trace_context,
            )
            self._write_log(
                message="Delivery snapshot preparation rejected.",
                level=LogLevel.WARNING,
                metadata=metadata,
                trace_context=trace_context,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY.value,
            )
            raise DeliverySnapshotServiceError(
                ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
                DELIVERY_SNAPSHOT_NOT_READY_MESSAGE,
                409,
            )

        created_at = self._now()
        snapshot = DeliveryChannelSnapshotModel(
            delivery_channel_snapshot_id=f"delivery-snapshot-{uuid4().hex}",
            run_id=run.run_id,
            source_delivery_channel_id=channel.delivery_channel_id,
            delivery_mode=channel.delivery_mode,
            scm_provider_type=channel.scm_provider_type,
            repository_identifier=channel.repository_identifier,
            default_branch=channel.default_branch,
            code_review_request_type=channel.code_review_request_type,
            credential_ref=channel.credential_ref,
            credential_status=channel.credential_status,
            readiness_status=channel.readiness_status,
            readiness_message=channel.readiness_message,
            last_validated_at=channel.last_validated_at,
            schema_version=DELIVERY_SNAPSHOT_SCHEMA_VERSION,
            created_at=created_at,
        )
        run.delivery_channel_snapshot_ref = snapshot.delivery_channel_snapshot_id
        run.updated_at = created_at
        prepared_metadata = dict(metadata)
        prepared_metadata["delivery_channel_snapshot_id"] = (
            snapshot.delivery_channel_snapshot_id
        )
        try:
            self._runtime_session.add(snapshot)
            self._runtime_session.add(run)
            self._runtime_session.flush()
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=API_ACTOR_ID,
                action="delivery_snapshot.prepare",
                target_type="pipeline_run",
                target_id=run_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata=prepared_metadata,
                trace_context=trace_context,
                rollback=self._runtime_session.rollback,
                created_at=created_at,
            )
            if self._auto_commit:
                self._runtime_session.commit()
                self._write_log(
                    message="Delivery snapshot prepared.",
                    level=LogLevel.INFO,
                    metadata=prepared_metadata,
                    trace_context=trace_context,
                )
            return snapshot
        except Exception as exc:
            self._runtime_session.rollback()
            self._record_failed(
                target_id=run_id,
                reason=str(exc) or type(exc).__name__,
                metadata={
                    **prepared_metadata,
                    "error_type": type(exc).__name__,
                },
                trace_context=trace_context,
            )
            raise

    def get_snapshot_for_run(
        self,
        *,
        run_id: str,
    ) -> DeliveryChannelSnapshotModel:
        run = self._runtime_session.get(
            PipelineRunModel,
            run_id,
            populate_existing=True,
        )
        if run is None or not run.delivery_channel_snapshot_ref:
            raise DeliverySnapshotServiceError(
                ErrorCode.DELIVERY_SNAPSHOT_MISSING,
                DELIVERY_SNAPSHOT_MISSING_MESSAGE,
                409,
            )
        snapshot = self._runtime_session.get(
            DeliveryChannelSnapshotModel,
            run.delivery_channel_snapshot_ref,
            populate_existing=True,
        )
        if snapshot is None:
            raise DeliverySnapshotServiceError(
                ErrorCode.DELIVERY_SNAPSHOT_MISSING,
                DELIVERY_SNAPSHOT_MISSING_MESSAGE,
                409,
            )
        return snapshot

    def assert_snapshot_ready_for_delivery(
        self,
        *,
        run_id: str,
    ) -> DeliveryChannelSnapshotModel:
        snapshot = self.get_snapshot_for_run(run_id=run_id)
        if (
            snapshot.readiness_status is not DeliveryReadinessStatus.READY
            or snapshot.credential_status is not CredentialStatus.READY
        ):
            raise DeliverySnapshotServiceError(
                ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
                DELIVERY_SNAPSHOT_NOT_READY_FOR_DELIVERY_MESSAGE,
                409,
            )
        return snapshot

    def _existing_snapshot(
        self,
        run: PipelineRunModel,
    ) -> DeliveryChannelSnapshotModel | None:
        if not run.delivery_channel_snapshot_ref:
            return None
        return self._runtime_session.get(
            DeliveryChannelSnapshotModel,
            run.delivery_channel_snapshot_ref,
            populate_existing=True,
        )

    def _write_log(
        self,
        *,
        message: str,
        level: LogLevel,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        error_code: str | None = None,
    ) -> None:
        redacted = self._redaction_policy.summarize_payload(
            metadata,
            payload_type="delivery_snapshot",
        )
        self._log_writer.write_run_log(
            LogRecordInput(
                source=LOG_SOURCE,
                category=LogCategory.DELIVERY,
                level=level,
                message=message,
                trace_context=trace_context,
                payload=LogPayloadSummary.from_redacted_payload(
                    "delivery_snapshot",
                    redacted,
                ),
                created_at=self._now(),
                error_code=error_code,
            )
        )

    def _record_rejected(
        self,
        *,
        target_id: str,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="delivery_snapshot.prepare.rejected",
            target_type="pipeline_run",
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
        try:
            self._audit_service.record_failed_command(
                actor_type=AuditActorType.USER,
                actor_id=API_ACTOR_ID,
                action="delivery_snapshot.prepare.failed",
                target_type="pipeline_run",
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
                message="Delivery snapshot preparation failed.",
                level=LogLevel.ERROR,
                metadata=metadata,
                trace_context=trace_context,
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )
        except Exception:
            pass

    def _base_metadata(
        self,
        *,
        run_id: str,
        project_id: str,
        approval_type: ApprovalType,
        target_stage_type: StageType,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "project_id": project_id,
            "approval_type": approval_type.value,
            "target_stage_type": target_stage_type.value,
        }

    def _snapshot_metadata(
        self,
        *,
        run_id: str,
        project_id: str,
        channel: DeliveryChannelModel,
        approval_type: ApprovalType,
        target_stage_type: StageType,
    ) -> dict[str, Any]:
        metadata = self._base_metadata(
            run_id=run_id,
            project_id=project_id,
            approval_type=approval_type,
            target_stage_type=target_stage_type,
        )
        metadata.update(
            {
                "delivery_channel_id": channel.delivery_channel_id,
                "delivery_mode": channel.delivery_mode.value,
                "scm_provider_type": self._enum_value(channel.scm_provider_type),
                "repository_identifier": channel.repository_identifier,
                "default_branch": channel.default_branch,
                "code_review_request_type": self._enum_value(
                    channel.code_review_request_type,
                ),
                "credential_ref": self._safe_credential_ref(channel.credential_ref),
                "credential_status": channel.credential_status.value,
                "readiness_status": channel.readiness_status.value,
                "readiness_message": channel.readiness_message,
                "last_validated_at": (
                    channel.last_validated_at.isoformat()
                    if channel.last_validated_at is not None
                    else None
                ),
            }
        )
        return metadata

    @staticmethod
    def _enum_value(value: Any) -> str | None:
        if value is None:
            return None
        return value.value

    def _safe_credential_ref(self, value: str | None) -> str | None:
        return self._delivery_channel_service.credential_ref_for_projection(value)


__all__ = [
    "DELIVERY_SNAPSHOT_GATE_CONTEXT_MESSAGE",
    "DELIVERY_SNAPSHOT_MISSING_MESSAGE",
    "DELIVERY_SNAPSHOT_NOT_READY_FOR_DELIVERY_MESSAGE",
    "DELIVERY_SNAPSHOT_NOT_READY_MESSAGE",
    "DELIVERY_SNAPSHOT_SCHEMA_VERSION",
    "DeliverySnapshotService",
    "DeliverySnapshotServiceError",
]
