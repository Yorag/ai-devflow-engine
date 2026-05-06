from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.models.runtime import StageArtifactModel, StageRunModel
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.observability import LogCategory, LogLevel


_LOGGER = logging.getLogger(__name__)


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class ArtifactStoreError(RuntimeError):
    """Slice-specific runtime artifact storage error."""


class ArtifactStore:
    def __init__(
        self,
        *,
        runtime_session: Session,
        log_writer: RunLogWriter | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime_session = runtime_session
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))

    def create_stage_input(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        artifact_id: str,
        artifact_type: str,
        payload_ref: str,
        input_snapshot: Mapping[str, Any],
        input_refs: Sequence[str] | None,
        trace_context: TraceContext,
    ) -> StageArtifactModel:
        failure_metadata = {
            "run_id": run_id,
            "stage_run_id": stage_run_id,
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "payload_ref": payload_ref,
            "changed_process_keys": ["input_snapshot", "input_refs"],
        }
        try:
            stage = self._runtime_session.get(StageRunModel, stage_run_id)
        except SQLAlchemyError as exc:
            error = ArtifactStoreError("Stage artifact storage is unavailable.")
            self._write_failure_log(
                action="create_stage_input",
                metadata=failure_metadata,
                error=error,
                trace_context=trace_context,
            )
            raise error from exc
        if stage is None or stage.run_id != run_id:
            error = ArtifactStoreError("Stage artifact storage target was not found.")
            self._write_failure_log(
                action="create_stage_input",
                metadata=failure_metadata,
                error=error,
                trace_context=trace_context,
            )
            raise error

        timestamp = self._now()
        artifact = StageArtifactModel(
            artifact_id=artifact_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            artifact_type=artifact_type,
            payload_ref=payload_ref,
            process={
                "input_snapshot": dict(input_snapshot),
                "input_refs": list(input_refs or []),
            },
            metrics={},
            created_at=timestamp,
        )
        self._runtime_session.add(artifact)
        stage.input_ref = artifact_id
        stage.updated_at = timestamp
        try:
            self._runtime_session.flush()
        except SQLAlchemyError as exc:
            error = ArtifactStoreError("Stage artifact storage is unavailable.")
            self._write_failure_log(
                action="create_stage_input",
                metadata=failure_metadata,
                error=error,
                trace_context=trace_context,
            )
            raise error from exc
        self._write_log(
            action="create_stage_input",
            metadata={
                "run_id": artifact.run_id,
                "stage_run_id": artifact.stage_run_id,
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "payload_ref": artifact.payload_ref,
                "changed_process_keys": ["input_snapshot", "input_refs"],
                "input_snapshot": dict(input_snapshot),
                "input_refs": list(input_refs or []),
            },
            trace_context=trace_context,
        )
        return artifact

    def append_process_record(
        self,
        *,
        artifact_id: str,
        process_key: str,
        process_value: Any,
        trace_context: TraceContext,
    ) -> StageArtifactModel:
        try:
            artifact = self._load_stage_artifact(artifact_id)
        except ArtifactStoreError as exc:
            self._write_failure_log(
                action="append_process_record",
                metadata={
                    "artifact_id": artifact_id,
                    "changed_process_keys": [process_key],
                },
                error=exc,
                trace_context=trace_context,
            )
            raise
        process = dict(artifact.process or {})
        process[process_key] = process_value
        artifact.process = process
        try:
            self._runtime_session.flush()
        except SQLAlchemyError as exc:
            error = ArtifactStoreError("Stage artifact storage is unavailable.")
            self._write_failure_log(
                action="append_process_record",
                metadata={
                    "run_id": artifact.run_id,
                    "stage_run_id": artifact.stage_run_id,
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type,
                    "payload_ref": artifact.payload_ref,
                    "changed_process_keys": [process_key],
                },
                error=error,
                trace_context=trace_context,
            )
            raise error from exc
        self._write_log(
            action="append_process_record",
            metadata={
                "run_id": artifact.run_id,
                "stage_run_id": artifact.stage_run_id,
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "payload_ref": artifact.payload_ref,
                "changed_process_keys": [process_key],
                process_key: process_value,
            },
            trace_context=trace_context,
        )
        return artifact

    def complete_stage_output(
        self,
        *,
        artifact_id: str,
        payload_ref: str,
        output_snapshot: Mapping[str, Any],
        output_refs: Sequence[str] | None,
        trace_context: TraceContext,
    ) -> StageArtifactModel:
        try:
            artifact = self._load_stage_artifact(artifact_id)
            stage = self._runtime_session.get(StageRunModel, artifact.stage_run_id)
        except SQLAlchemyError as exc:
            error = ArtifactStoreError("Stage artifact storage is unavailable.")
            self._write_failure_log(
                action="complete_stage_output",
                metadata={"artifact_id": artifact_id, "payload_ref": payload_ref},
                error=error,
                trace_context=trace_context,
            )
            raise error from exc
        except ArtifactStoreError as exc:
            self._write_failure_log(
                action="complete_stage_output",
                metadata={"artifact_id": artifact_id, "payload_ref": payload_ref},
                error=exc,
                trace_context=trace_context,
            )
            raise
        if stage is None or artifact.run_id != stage.run_id:
            error = ArtifactStoreError("Stage artifact storage target was not found.")
            self._write_failure_log(
                action="complete_stage_output",
                metadata={
                    "run_id": artifact.run_id,
                    "stage_run_id": artifact.stage_run_id,
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type,
                    "payload_ref": payload_ref,
                    "changed_process_keys": ["output_snapshot", "output_refs"],
                },
                error=error,
                trace_context=trace_context,
            )
            raise error

        timestamp = self._now()
        artifact.payload_ref = payload_ref
        process = dict(artifact.process or {})
        process["output_snapshot"] = dict(output_snapshot)
        process["output_refs"] = list(output_refs or [])
        artifact.process = process
        stage.output_ref = artifact.artifact_id
        stage.updated_at = timestamp
        try:
            self._runtime_session.flush()
        except SQLAlchemyError as exc:
            error = ArtifactStoreError("Stage artifact storage is unavailable.")
            self._write_failure_log(
                action="complete_stage_output",
                metadata={
                    "run_id": artifact.run_id,
                    "stage_run_id": artifact.stage_run_id,
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type,
                    "payload_ref": artifact.payload_ref,
                    "changed_process_keys": ["output_snapshot", "output_refs"],
                },
                error=error,
                trace_context=trace_context,
            )
            raise error from exc
        self._write_log(
            action="complete_stage_output",
            metadata={
                "run_id": artifact.run_id,
                "stage_run_id": artifact.stage_run_id,
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "payload_ref": artifact.payload_ref,
                "changed_process_keys": ["output_snapshot", "output_refs"],
                "output_snapshot": dict(output_snapshot),
                "output_refs": list(output_refs or []),
            },
            trace_context=trace_context,
        )
        return artifact

    def attach_metric_set(
        self,
        *,
        artifact_id: str,
        metric_set: Mapping[str, Any],
        trace_context: TraceContext,
    ) -> StageArtifactModel:
        try:
            artifact = self._load_stage_artifact(artifact_id)
        except ArtifactStoreError as exc:
            self._write_failure_log(
                action="attach_metric_set",
                metadata={
                    "artifact_id": artifact_id,
                    "changed_metric_keys": list(metric_set.keys()),
                },
                error=exc,
                trace_context=trace_context,
            )
            raise
        metrics = dict(artifact.metrics or {})
        metrics.update(dict(metric_set))
        artifact.metrics = metrics
        try:
            self._runtime_session.flush()
        except SQLAlchemyError as exc:
            error = ArtifactStoreError("Stage artifact storage is unavailable.")
            self._write_failure_log(
                action="attach_metric_set",
                metadata={
                    "run_id": artifact.run_id,
                    "stage_run_id": artifact.stage_run_id,
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type,
                    "payload_ref": artifact.payload_ref,
                    "changed_metric_keys": list(metric_set.keys()),
                },
                error=error,
                trace_context=trace_context,
            )
            raise error from exc
        self._write_log(
            action="attach_metric_set",
            metadata={
                "run_id": artifact.run_id,
                "stage_run_id": artifact.stage_run_id,
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "payload_ref": artifact.payload_ref,
                "changed_metric_keys": list(metric_set.keys()),
                "metric_set": dict(metric_set),
            },
            trace_context=trace_context,
        )
        return artifact

    def get_stage_artifact(
        self,
        artifact_id: str,
        *,
        trace_context: TraceContext | None = None,
        log_missing_failure: bool = True,
    ) -> StageArtifactModel:
        try:
            artifact = self._load_stage_artifact(artifact_id)
        except ArtifactStoreError as exc:
            if log_missing_failure or "not found" not in str(exc).lower():
                self._write_failure_log(
                    action="get_stage_artifact",
                    metadata={"artifact_id": artifact_id},
                    error=exc,
                    trace_context=trace_context or self._fallback_trace_context(),
                )
            raise
        return artifact

    def _load_stage_artifact(self, artifact_id: str) -> StageArtifactModel:
        try:
            artifact = self._runtime_session.get(StageArtifactModel, artifact_id)
        except SQLAlchemyError as exc:
            raise ArtifactStoreError("Stage artifact storage is unavailable.") from exc
        if artifact is None:
            raise ArtifactStoreError("Stage artifact was not found.")
        return artifact

    def _write_log(
        self,
        *,
        action: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        if self._log_writer is None:
            return
        payload = {"action": action, **metadata}
        log_trace_context = self._trace_for_log(
            trace_context,
            metadata=payload,
            action=action,
        )
        if log_trace_context.run_id is None:
            _LOGGER.warning(
                "Stage artifact log write skipped because run_id is missing for artifact_id=%s",
                metadata.get("artifact_id"),
            )
            return
        try:
            redacted_payload = self._redaction_policy.summarize_payload(
                payload,
                payload_type="stage_artifact",
            )
            payload_summary = LogPayloadSummary.from_redacted_payload(
                "stage_artifact",
                redacted_payload,
            )
            if isinstance(redacted_payload.redacted_payload, dict):
                payload_summary.summary.update(redacted_payload.redacted_payload)
            payload_summary.summary.update(self._stable_log_summary(payload))
            self._log_writer.write_run_log(
                LogRecordInput(
                    source="services.artifacts",
                    category=LogCategory.RUNTIME,
                    level=LogLevel.INFO,
                    message=f"Stage artifact {action}.",
                    trace_context=log_trace_context,
                    payload=payload_summary,
                    created_at=self._now(),
                )
            )
        except Exception:
            _LOGGER.exception(
                "Stage artifact log write failed for artifact_id=%s",
                metadata.get("artifact_id"),
            )

    def _write_failure_log(
        self,
        *,
        action: str,
        metadata: dict[str, Any],
        error: ArtifactStoreError,
        trace_context: TraceContext,
    ) -> None:
        self._write_log(
            action=f"{action}_failed",
            metadata={
                **metadata,
                "error_message": str(error),
            },
            trace_context=trace_context,
        )

    def _stable_log_summary(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        stable_keys = (
            "action",
            "run_id",
            "stage_run_id",
            "artifact_id",
            "artifact_type",
            "payload_ref",
            "changed_process_keys",
            "changed_metric_keys",
            "error_message",
        )
        return {key: payload[key] for key in stable_keys if key in payload}

    def _trace_for_log(
        self,
        trace_context: TraceContext,
        *,
        metadata: Mapping[str, Any],
        action: str,
    ) -> TraceContext:
        run_id = metadata.get("run_id")
        stage_run_id = metadata.get("stage_run_id")
        if (
            not isinstance(run_id, str)
            or not isinstance(stage_run_id, str)
            or (trace_context.run_id == run_id and trace_context.stage_run_id == stage_run_id)
        ):
            return trace_context
        return trace_context.child_span(
            span_id=f"stage-artifact-{action}-{metadata.get('artifact_id', 'unknown')}",
            created_at=self._now(),
            run_id=run_id,
            stage_run_id=stage_run_id,
        )

    def _fallback_trace_context(self) -> TraceContext:
        timestamp = self._now()
        return TraceContext(
            request_id="artifact-store",
            trace_id="artifact-store",
            correlation_id="artifact-store",
            span_id="artifact-store",
            parent_span_id=None,
            session_id=None,
            run_id=None,
            stage_run_id=None,
            created_at=timestamp,
        )


__all__ = ["ArtifactStore", "ArtifactStoreError", "RunLogWriter"]
