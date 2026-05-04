from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models.runtime import StageArtifactModel, StageRunModel
from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.runtime.base import (
    RuntimeEngineResult,
    RuntimeExecutionContext,
    RuntimeInterrupt,
    RuntimeStepResult,
    RuntimeTerminalResult,
)
from backend.app.schemas import common
from backend.app.schemas.feed import ExecutionNodeProjection, StageItemProjection
from backend.app.schemas.observability import LogCategory, LogLevel
from backend.app.services.artifacts import ArtifactStore
from backend.app.services.events import DomainEvent, DomainEventType, EventStore
from backend.app.services.runtime_orchestration import CheckpointPort, RuntimeCommandPort
from backend.app.services.stages import StageRunService


_LOGGER = logging.getLogger(__name__)

DETERMINISTIC_STAGE_SEQUENCE = (
    StageType.REQUIREMENT_ANALYSIS,
    StageType.SOLUTION_DESIGN,
    StageType.CODE_GENERATION,
    StageType.TEST_GENERATION_EXECUTION,
    StageType.CODE_REVIEW,
    StageType.DELIVERY_INTEGRATION,
)

_STAGE_EVENT_TYPES: dict[StageType, tuple[DomainEventType, ...]] = {
    StageType.REQUIREMENT_ANALYSIS: (DomainEventType.REQUIREMENT_PARSED,),
    StageType.SOLUTION_DESIGN: (
        DomainEventType.SOLUTION_PROPOSED,
        DomainEventType.SOLUTION_VALIDATION_COMPLETED,
    ),
    StageType.CODE_GENERATION: (DomainEventType.CODE_PATCH_GENERATED,),
    StageType.TEST_GENERATION_EXECUTION: (
        DomainEventType.TESTS_GENERATED,
        DomainEventType.TESTS_EXECUTED,
    ),
    StageType.CODE_REVIEW: (DomainEventType.REVIEW_COMPLETED,),
    StageType.DELIVERY_INTEGRATION: (DomainEventType.STAGE_UPDATED,),
}

_STAGE_TITLES: dict[StageType, str] = {
    StageType.REQUIREMENT_ANALYSIS: "Requirement Analysis",
    StageType.SOLUTION_DESIGN: "Solution Design",
    StageType.CODE_GENERATION: "Code Generation",
    StageType.TEST_GENERATION_EXECUTION: "Test Generation & Execution",
    StageType.CODE_REVIEW: "Code Review",
    StageType.DELIVERY_INTEGRATION: "Delivery Integration",
}

_TERMINAL_STAGE_STATUSES = frozenset(
    {
        StageStatus.COMPLETED,
        StageStatus.FAILED,
        StageStatus.TERMINATED,
        StageStatus.SUPERSEDED,
    }
)


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class DeterministicRuntimeEngine:
    def __init__(
        self,
        *,
        runtime_session: Session,
        event_session: Session,
        stage_service: StageRunService | None = None,
        artifact_store: ArtifactStore | None = None,
        event_store: EventStore | None = None,
        log_writer: RunLogWriter | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._now = now or (lambda: datetime.now(UTC))
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._stage_service = stage_service or StageRunService(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=self._now,
        )
        self._artifact_store = artifact_store or ArtifactStore(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=self._now,
        )
        self._event_store = event_store or EventStore(
            event_session,
            now=self._now,
        )

    def start(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult:
        return self.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    def run_next(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeStepResult:
        next_stage = self._next_stage(context.run_id)
        stage: StageRunModel | None = (
            next_stage if isinstance(next_stage, StageRunModel) else None
        )
        stage_type = next_stage.stage_type if stage is not None else next_stage
        stage_run_id = (
            stage.stage_run_id
            if stage is not None
            else self._stage_run_id(context.run_id, stage_type)
        )
        stage_trace = self._stage_trace(
            context,
            stage_type=stage_type,
            stage_run_id=stage_run_id,
        )
        if stage is not None:
            start_event = None
        else:
            stage = self._stage_service.start_stage(
                run_id=context.run_id,
                stage_run_id=stage_run_id,
                stage_type=stage_type,
                attempt_index=1,
                graph_node_key=stage_type.value,
                stage_contract_ref=stage_type.value,
                input_ref=None,
                summary=f"{_STAGE_TITLES[stage_type]} deterministic stage started.",
                trace_context=stage_trace,
            )
            start_event = self._append_stage_event(
                DomainEventType.STAGE_STARTED,
                context=context,
                stage=stage,
                status=StageStatus.RUNNING,
                trace_context=stage_trace,
                item_title=f"{_STAGE_TITLES[stage_type]} started",
                item_summary="Deterministic runtime entered the stage.",
                artifact_refs=[],
            )
        artifact = self.emit_stage_artifacts(
            context=context,
            stage=stage,
            trace_context=stage_trace,
        )
        completed_stage = self._stage_service.complete_stage(
            stage_run_id=stage.stage_run_id,
            status=StageStatus.COMPLETED,
            output_ref=artifact.artifact_id,
            summary=f"{_STAGE_TITLES[stage_type]} deterministic stage completed.",
            trace_context=stage_trace,
        )
        update_events = self._append_completion_events(
            context=context,
            stage=completed_stage,
            artifact_ref=artifact.artifact_id,
            trace_context=stage_trace,
        )
        checkpoint = checkpoint_port.save_checkpoint(
            thread=context.thread,
            purpose=CheckpointPurpose.RUNNING_SAFE_POINT,
            trace_context=stage_trace,
            stage_run_id=completed_stage.stage_run_id,
            stage_type=completed_stage.stage_type,
            workspace_snapshot_ref=context.workspace_snapshot_ref,
            payload_ref=artifact.payload_ref,
        )
        event_refs = [
            *([start_event.event_id] if start_event is not None else []),
            *[event.event_id for event in update_events],
        ]
        log_summary_ref = self._write_stage_log(
            context=context,
            stage=completed_stage,
            artifact_refs=[artifact.artifact_id],
            event_refs=event_refs,
            checkpoint=checkpoint,
            trace_context=stage_trace,
        )
        if log_summary_ref is not None:
            self._artifact_store.append_process_record(
                artifact_id=artifact.artifact_id,
                process_key="log_refs",
                process_value=[log_summary_ref],
                trace_context=stage_trace,
            )
        return RuntimeStepResult(
            run_id=context.run_id,
            stage_run_id=completed_stage.stage_run_id,
            stage_type=completed_stage.stage_type,
            status=completed_stage.status,
            trace_context=stage_trace,
            artifact_refs=[artifact.artifact_id],
            domain_event_refs=event_refs,
            log_summary_refs=[log_summary_ref] if log_summary_ref is not None else [],
            audit_refs=[],
            checkpoint_ref=checkpoint,
        )

    def resume(
        self,
        *,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult:
        raise NotImplementedError("deterministic interrupts belong to A4.3")

    def terminate(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeTerminalResult:
        raise NotImplementedError("deterministic terminal control belongs to A4.4")

    def emit_stage_artifacts(
        self,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel,
        trace_context: TraceContext,
    ) -> StageArtifactModel:
        payload_base = f"deterministic://{context.run_id}/{stage.stage_type.value}"
        artifact = self._artifact_store.create_stage_input(
            run_id=context.run_id,
            stage_run_id=stage.stage_run_id,
            artifact_id=self._artifact_id(stage.stage_run_id),
            artifact_type=f"{stage.stage_type.value}_deterministic_stage",
            payload_ref=f"{payload_base}/input",
            input_snapshot={
                "stage_type": stage.stage_type.value,
                "snapshot_refs": self._snapshot_refs(context),
            },
            input_refs=self._previous_stage_refs(context.run_id),
            trace_context=trace_context,
        )
        self._artifact_store.append_process_record(
            artifact_id=artifact.artifact_id,
            process_key="process_snapshot",
            process_value={
                "runtime": "deterministic_test",
                "stage_type": stage.stage_type.value,
                "stage_title": _STAGE_TITLES[stage.stage_type],
                "business_stage_sequence": [
                    item.value for item in DETERMINISTIC_STAGE_SEQUENCE
                ],
            },
            trace_context=trace_context,
        )
        self._artifact_store.append_process_record(
            artifact_id=artifact.artifact_id,
            process_key="tool_calls",
            process_value=[],
            trace_context=trace_context,
        )
        if stage.stage_type is StageType.SOLUTION_DESIGN:
            self._artifact_store.append_process_record(
                artifact_id=artifact.artifact_id,
                process_key="solution_validation",
                process_value={
                    "status": "completed",
                    "business_stage_type": StageType.SOLUTION_DESIGN.value,
                    "summary": (
                        "Deterministic solution validation completed inside "
                        "Solution Design."
                    ),
                },
                trace_context=trace_context,
            )
        self._artifact_store.attach_metric_set(
            artifact_id=artifact.artifact_id,
            metric_set=self._metrics_for_stage(stage.stage_type),
            trace_context=trace_context,
        )
        return self._artifact_store.complete_stage_output(
            artifact_id=artifact.artifact_id,
            payload_ref=f"{payload_base}/output",
            output_snapshot=self._output_snapshot_for_stage(stage.stage_type),
            output_refs=[],
            trace_context=trace_context,
        )

    def _next_stage(self, run_id: str) -> StageRunModel | StageType:
        rows = self._runtime_session.execute(
            select(StageRunModel)
            .where(StageRunModel.run_id == run_id)
            .order_by(StageRunModel.started_at.asc())
        ).scalars().all()
        rows_by_stage = {row.stage_type: row for row in rows}
        active_rows = [
            row for row in rows if row.status not in _TERMINAL_STAGE_STATUSES
        ]
        if len(active_rows) > 1:
            raise ValueError("multiple active deterministic stages cannot advance")
        if active_rows:
            active_row = active_rows[0]
            for stage_type in DETERMINISTIC_STAGE_SEQUENCE:
                if stage_type is active_row.stage_type:
                    if active_row.status is StageStatus.RUNNING:
                        return active_row
                    raise ValueError(
                        "active deterministic stage must be resolved before advancing"
                    )
                previous_row = rows_by_stage.get(stage_type)
                if previous_row is None or previous_row.status is not StageStatus.COMPLETED:
                    raise ValueError(
                        "out of order active deterministic stage cannot advance"
                    )
        for stage_type in DETERMINISTIC_STAGE_SEQUENCE:
            row = rows_by_stage.get(stage_type)
            if row is None:
                return stage_type
            if row.status is not StageStatus.COMPLETED:
                raise ValueError(
                    "active deterministic stage must be resolved before advancing"
                )
        raise ValueError(
            "deterministic stage sequence is exhausted; terminal control belongs to A4.4"
        )

    def _stage_run_id(self, run_id: str, stage_type: StageType) -> str:
        return _bounded_id(
            prefix="stage-run",
            seed=f"{run_id}-{stage_type.value}-deterministic-1",
        )

    def _artifact_id(self, stage_run_id: str) -> str:
        return _bounded_id(prefix="artifact", seed=stage_run_id)

    def _stage_trace(
        self,
        context: RuntimeExecutionContext,
        *,
        stage_type: StageType,
        stage_run_id: str,
    ) -> TraceContext:
        return context.trace_context.child_span(
            span_id=f"deterministic-{stage_type.value}-{stage_run_id}",
            created_at=self._now(),
            run_id=context.run_id,
            stage_run_id=stage_run_id,
            graph_thread_id=context.thread.thread_id,
        )

    def _append_stage_event(
        self,
        domain_event_type: DomainEventType,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel,
        status: StageStatus,
        trace_context: TraceContext,
        item_title: str,
        item_summary: str,
        artifact_refs: list[str],
    ) -> DomainEvent:
        node = self._stage_node_payload(
            stage=stage,
            status=status,
            item_title=item_title,
            item_summary=item_summary,
            artifact_refs=artifact_refs,
        )
        return self._event_store.append(
            domain_event_type,
            payload={"stage_node": node.model_dump(mode="json")},
            trace_context=trace_context,
            session_id=context.session_id,
            run_id=context.run_id,
            stage_run_id=stage.stage_run_id,
        )

    def _append_completion_events(
        self,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel,
        artifact_ref: str,
        trace_context: TraceContext,
    ) -> list[DomainEvent]:
        return [
            self._append_stage_event(
                domain_event_type,
                context=context,
                stage=stage,
                status=StageStatus.COMPLETED,
                trace_context=trace_context,
                item_title=f"{_STAGE_TITLES[stage.stage_type]} result",
                item_summary=self._output_snapshot_for_stage(stage.stage_type)[
                    "summary"
                ],
                artifact_refs=[artifact_ref],
            )
            for domain_event_type in _STAGE_EVENT_TYPES[stage.stage_type]
        ]

    def _stage_node_payload(
        self,
        *,
        stage: StageRunModel,
        status: StageStatus,
        item_title: str,
        item_summary: str,
        artifact_refs: list[str],
    ) -> ExecutionNodeProjection:
        occurred_at = self._now()
        return ExecutionNodeProjection(
            entry_id=f"entry-{stage.stage_run_id}",
            run_id=stage.run_id,
            occurred_at=occurred_at,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            status=status,
            attempt_index=stage.attempt_index,
            started_at=self._aware(stage.started_at),
            ended_at=self._aware(stage.ended_at),
            summary=(
                f"{_STAGE_TITLES[stage.stage_type]} deterministic stage "
                f"{status.value}."
            ),
            items=[
                StageItemProjection(
                    item_id=f"item-{stage.stage_run_id}-{status.value}",
                    type=common.StageItemType.RESULT
                    if status is StageStatus.COMPLETED
                    else common.StageItemType.REASONING,
                    occurred_at=occurred_at,
                    title=item_title,
                    summary=item_summary,
                    content=None,
                    artifact_refs=artifact_refs,
                    metrics=self._metrics_for_stage(stage.stage_type),
                )
            ],
            metrics=self._metrics_for_stage(stage.stage_type),
        )

    def _write_stage_log(
        self,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel,
        artifact_refs: list[str],
        event_refs: list[str],
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> str | None:
        if self._log_writer is None:
            return None
        duration_ms = self._duration_ms(stage)
        payload = {
            "action": "deterministic_stage_advanced",
            "run_id": stage.run_id,
            "session_id": context.session_id,
            "stage_run_id": stage.stage_run_id,
            "graph_thread_id": context.thread.thread_id,
            "trace_id": trace_context.trace_id,
            "stage_type": stage.stage_type.value,
            "status": stage.status.value,
            "duration_ms": duration_ms,
            "artifact_refs": artifact_refs,
            "event_refs": event_refs,
            "checkpoint_ref": checkpoint.checkpoint_id,
            "span_id": trace_context.span_id,
        }
        try:
            redacted = self._redaction_policy.summarize_payload(
                payload,
                payload_type="deterministic_runtime_stage",
            )
            summary = LogPayloadSummary.from_redacted_payload(
                "deterministic_runtime_stage",
                redacted,
            )
            if isinstance(redacted.redacted_payload, Mapping):
                summary.summary.update(dict(redacted.redacted_payload))
            summary.summary.update(payload)
            result = self._log_writer.write_run_log(
                LogRecordInput(
                    source="runtime.deterministic",
                    category=LogCategory.RUNTIME,
                    level=LogLevel.INFO,
                    message="Deterministic runtime advanced a stage.",
                    trace_context=trace_context,
                    payload=summary,
                    created_at=self._now(),
                    duration_ms=duration_ms,
                )
            )
            log_id = getattr(result, "log_id", None)
            return log_id if isinstance(log_id, str) and log_id else None
        except Exception:
            _LOGGER.exception(
                "Deterministic runtime log write failed for stage_run_id=%s",
                stage.stage_run_id,
            )
            return None

    def _previous_stage_refs(self, run_id: str) -> list[str]:
        rows = self._runtime_session.execute(
            select(StageRunModel)
            .where(StageRunModel.run_id == run_id)
            .order_by(StageRunModel.started_at.asc())
        ).scalars().all()
        return [row.output_ref for row in rows if row.output_ref]

    def _snapshot_refs(self, context: RuntimeExecutionContext) -> dict[str, object]:
        return {
            "template_snapshot_ref": context.template_snapshot_ref,
            "provider_snapshot_refs": list(context.provider_snapshot_refs),
            "model_binding_snapshot_refs": list(context.model_binding_snapshot_refs),
            "runtime_limit_snapshot_ref": context.runtime_limit_snapshot_ref,
            "provider_call_policy_snapshot_ref": (
                context.provider_call_policy_snapshot_ref
            ),
            "graph_definition_ref": context.graph_definition_ref,
            "delivery_channel_snapshot_ref": context.delivery_channel_snapshot_ref,
            "workspace_snapshot_ref": context.workspace_snapshot_ref,
        }

    def _output_snapshot_for_stage(self, stage_type: StageType) -> dict[str, object]:
        summaries = {
            StageType.REQUIREMENT_ANALYSIS: (
                "Structured requirement parsed for deterministic flow."
            ),
            StageType.SOLUTION_DESIGN: (
                "Solution design and internal validation completed."
            ),
            StageType.CODE_GENERATION: (
                "Deterministic code change plan produced without workspace mutation."
            ),
            StageType.TEST_GENERATION_EXECUTION: (
                "Deterministic test plan and execution summary produced."
            ),
            StageType.CODE_REVIEW: "Deterministic review summary produced.",
            StageType.DELIVERY_INTEGRATION: (
                "Delivery integration handoff prepared for later demo_delivery slice."
            ),
        }
        return {
            "stage_type": stage_type.value,
            "summary": summaries[stage_type],
            "status": "completed",
            "next_stage_type": self._next_stage_value_after(stage_type),
        }

    def _metrics_for_stage(self, stage_type: StageType) -> dict[str, int]:
        base = {
            "duration_ms": 1,
            "attempt_index": 1,
            "tool_call_count": 0,
        }
        if stage_type is StageType.TEST_GENERATION_EXECUTION:
            return {
                **base,
                "generated_test_count": 1,
                "executed_test_count": 1,
                "passed_test_count": 1,
                "failed_test_count": 0,
            }
        if stage_type is StageType.CODE_GENERATION:
            return {**base, "changed_file_count": 0}
        if stage_type is StageType.DELIVERY_INTEGRATION:
            return {**base, "delivery_artifact_count": 0}
        return base

    def _next_stage_value_after(self, stage_type: StageType) -> str | None:
        index = list(DETERMINISTIC_STAGE_SEQUENCE).index(stage_type)
        if index + 1 >= len(DETERMINISTIC_STAGE_SEQUENCE):
            return None
        return DETERMINISTIC_STAGE_SEQUENCE[index + 1].value

    def _duration_ms(self, stage: StageRunModel) -> int:
        if stage.ended_at is None:
            return 0
        started_at = self._aware(stage.started_at)
        ended_at = self._aware(stage.ended_at)
        return max(0, int((ended_at - started_at).total_seconds() * 1000))

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)


__all__ = [
    "DETERMINISTIC_STAGE_SEQUENCE",
    "DeterministicRuntimeEngine",
]


def _bounded_id(*, prefix: str, seed: str) -> str:
    candidate = f"{prefix}-{seed}"
    if len(candidate) <= 80:
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"
