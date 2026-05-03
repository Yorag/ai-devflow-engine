from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend.app.db.models.runtime import PipelineRunModel, StageRunModel
from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.repositories.runtime import StageRunRepository
from backend.app.schemas.observability import LogCategory, LogLevel


_LOGGER = logging.getLogger(__name__)

_WAITING_STATUSES = frozenset(
    {
        StageStatus.WAITING_CLARIFICATION,
        StageStatus.WAITING_APPROVAL,
        StageStatus.WAITING_TOOL_CONFIRMATION,
    }
)
_TERMINAL_STATUSES = frozenset(
    {
        StageStatus.COMPLETED,
        StageStatus.FAILED,
        StageStatus.TERMINATED,
        StageStatus.SUPERSEDED,
    }
)


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class StageRunService:
    def __init__(
        self,
        *,
        runtime_session: Session,
        repository: StageRunRepository | None = None,
        log_writer: RunLogWriter | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime_session = runtime_session
        self._repository = repository or StageRunRepository(runtime_session)
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))

    def start_stage(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        attempt_index: int,
        graph_node_key: str,
        stage_contract_ref: str,
        input_ref: str | None,
        summary: str | None,
        trace_context: TraceContext,
    ) -> StageRunModel:
        stage_type = StageType(stage_type)
        timestamp = self._now()
        stage = self._repository.create_stage_run(
            stage_run_id=stage_run_id,
            run_id=run_id,
            stage_type=stage_type,
            status=StageStatus.RUNNING,
            attempt_index=attempt_index,
            graph_node_key=graph_node_key,
            stage_contract_ref=stage_contract_ref,
            input_ref=input_ref,
            output_ref=None,
            summary=summary,
            started_at=timestamp,
            ended_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        run = self._runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise ValueError("PipelineRun was not found.")
        run.current_stage_run_id = stage.stage_run_id
        run.updated_at = timestamp
        self._runtime_session.flush()
        self._record_lifecycle_log(
            action="start",
            stage=stage,
            trace_context=trace_context,
            created_at=timestamp,
        )
        return stage

    def mark_stage_waiting(
        self,
        *,
        stage_run_id: str,
        status: StageStatus,
        summary: str | None,
        trace_context: TraceContext,
    ) -> StageRunModel:
        status = StageStatus(status)
        if status not in _WAITING_STATUSES:
            raise ValueError("Stage waiting status must be a supported waiting status.")
        timestamp = self._now()
        stage = self._load_stage(stage_run_id)
        self._assert_current_active_stage(stage)
        stage.status = status
        stage.summary = summary
        stage.updated_at = timestamp
        self._repository.save(stage)
        self._record_lifecycle_log(
            action="waiting",
            stage=stage,
            trace_context=trace_context,
            created_at=timestamp,
        )
        return stage

    def complete_stage(
        self,
        *,
        stage_run_id: str,
        status: StageStatus,
        output_ref: str | None,
        summary: str | None,
        trace_context: TraceContext,
    ) -> StageRunModel:
        status = StageStatus(status)
        if status not in _TERMINAL_STATUSES:
            raise ValueError("Stage completion status must be terminal.")
        timestamp = self._now()
        stage = self._load_stage(stage_run_id)
        self._assert_current_active_stage(stage)
        stage.status = status
        stage.output_ref = output_ref
        stage.summary = summary
        stage.ended_at = timestamp
        stage.updated_at = timestamp
        self._repository.save(stage)
        self._record_lifecycle_log(
            action="complete",
            stage=stage,
            trace_context=trace_context,
            created_at=timestamp,
        )
        return stage

    def _load_stage(self, stage_run_id: str) -> StageRunModel:
        stage = self._repository.get_stage_run(stage_run_id)
        if stage is None:
            raise ValueError("StageRun was not found.")
        return stage

    def _assert_current_active_stage(self, stage: StageRunModel) -> None:
        if stage.status in _TERMINAL_STATUSES:
            raise ValueError("terminal StageRun rows cannot be rewritten.")
        run = self._runtime_session.get(PipelineRunModel, stage.run_id)
        if run is None:
            raise ValueError("PipelineRun was not found.")
        if run.current_stage_run_id != stage.stage_run_id:
            raise ValueError("Stage transition must target the current active stage.")

    def _record_lifecycle_log(
        self,
        *,
        action: str,
        stage: StageRunModel,
        trace_context: TraceContext,
        created_at: datetime,
    ) -> None:
        if self._log_writer is None:
            return
        try:
            metadata: dict[str, Any] = {
                "action": action,
                "run_id": stage.run_id,
                "stage_run_id": stage.stage_run_id,
                "stage_type": stage.stage_type.value,
                "status": stage.status.value,
                "attempt_index": stage.attempt_index,
                "graph_node_key": stage.graph_node_key,
                "stage_contract_ref": stage.stage_contract_ref,
                "input_ref": stage.input_ref,
                "output_ref": stage.output_ref,
            }
            redacted_payload = self._redaction_policy.summarize_payload(
                metadata,
                payload_type="stage_run_lifecycle",
            )
            payload_summary = dict(redacted_payload.summary)
            if isinstance(redacted_payload.redacted_payload, dict):
                payload_summary.update(redacted_payload.redacted_payload)
            log_trace = self._trace_for_stage(
                trace_context,
                stage=stage,
                created_at=created_at,
                action=action,
            )
            self._log_writer.write_run_log(
                LogRecordInput(
                    source="services.stages",
                    category=LogCategory.RUNTIME,
                    level=LogLevel.INFO,
                    message=f"Stage run {action}.",
                    trace_context=log_trace,
                    payload=LogPayloadSummary(
                        payload_type="stage_run_lifecycle",
                        summary=payload_summary,
                        excerpt=redacted_payload.excerpt,
                        payload_size_bytes=redacted_payload.payload_size_bytes,
                        content_hash=redacted_payload.content_hash,
                        redaction_status=redacted_payload.redaction_status,
                    ),
                    created_at=created_at,
                )
            )
        except Exception:
            _LOGGER.exception(
                "Stage run log write failed for stage_run_id=%s",
                stage.stage_run_id,
            )

    @staticmethod
    def _trace_for_stage(
        trace_context: TraceContext,
        *,
        stage: StageRunModel,
        created_at: datetime,
        action: str,
    ) -> TraceContext:
        if (
            trace_context.run_id == stage.run_id
            and trace_context.stage_run_id == stage.stage_run_id
        ):
            return trace_context
        return trace_context.child_span(
            span_id=f"stage-{action}-{stage.stage_run_id}",
            created_at=created_at,
            run_id=stage.run_id,
            stage_run_id=stage.stage_run_id,
        )


__all__ = ["RunLogWriter", "StageRunService"]
