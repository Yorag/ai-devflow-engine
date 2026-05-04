from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.control import SessionModel
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    ClarificationRecordModel,
    PipelineRunModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    RunStatus,
    SessionStatus,
    SseEventType,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
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
from backend.app.services.approvals import ApprovalService
from backend.app.services.artifacts import ArtifactStore
from backend.app.services.clarifications import ClarificationService
from backend.app.services.events import DomainEvent, DomainEventType, EventStore
from backend.app.services.runtime_orchestration import (
    CheckpointPort,
    RuntimeCommandPort,
    RuntimeOrchestrationService,
)
from backend.app.services.runs import TerminalStatusProjector
from backend.app.services.stages import StageRunService
from backend.app.services.tool_confirmations import ToolConfirmationService


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


class _NoopAuditService:
    def require_audit_record(self, **kwargs: Any) -> object:
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        return object()

    def record_blocked_action(self, **kwargs: Any) -> object:
        return object()


class _NoopRunLogWriter:
    def write_run_log(self, record: LogRecordInput) -> object:
        return object()


class _CapturingRuntimeCommandPort:
    def __init__(self, wrapped: RuntimeCommandPort) -> None:
        self._wrapped = wrapped
        self.last_interrupt: GraphInterruptRef | None = None

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        interrupt = self._wrapped.create_interrupt(**kwargs)
        self.last_interrupt = interrupt
        return interrupt

    def resume_interrupt(self, **kwargs: Any) -> object:
        return self._wrapped.resume_interrupt(**kwargs)

    def resume_tool_confirmation(self, **kwargs: Any) -> object:
        return self._wrapped.resume_tool_confirmation(**kwargs)

    def pause_thread(self, **kwargs: Any) -> object:
        return self._wrapped.pause_thread(**kwargs)

    def resume_thread(self, **kwargs: Any) -> object:
        return self._wrapped.resume_thread(**kwargs)

    def terminate_thread(self, **kwargs: Any) -> object:
        return self._wrapped.terminate_thread(**kwargs)

    def assert_thread_terminal(self, **kwargs: Any) -> GraphThreadRef:
        return self._wrapped.assert_thread_terminal(**kwargs)


@dataclass(frozen=True)
class DeterministicToolConfirmationConfig:
    stage_type: StageType
    tool_name: str = "bash"
    command_preview: str | None = "uv run pytest -q"
    target_summary: str = "Deterministic high-risk tool action."
    risk_categories: list[ToolRiskCategory] | None = None
    reason: str = "Deterministic fixture requires high-risk tool confirmation."
    expected_side_effects: list[str] | None = None
    alternative_path_summary: str | None = None
    planned_deny_followup_action: str | None = "continue_current_stage"
    planned_deny_followup_summary: str | None = (
        "Continue current stage with deterministic fixture output."
    )


@dataclass(frozen=True)
class DeterministicInterruptConfig:
    clarification: bool = False
    solution_design_approval: bool = False
    code_review_approval: bool = False
    tool_confirmation: DeterministicToolConfirmationConfig | None = None


@dataclass(frozen=True)
class DeterministicTerminalConfig:
    complete_after_stages: bool = False
    fail_at_stage: StageType | None = None
    terminate_at_stage: StageType | None = None
    failure_reason: str = "Deterministic runtime fixture failed."
    termination_reason: str = "Deterministic runtime fixture terminated."
    completion_reason: str = "Deterministic runtime fixture completed."


class DeterministicRuntimeEngine:
    def __init__(
        self,
        *,
        runtime_session: Session,
        event_session: Session,
        control_session: Session | None = None,
        audit_service: Any | None = None,
        delivery_snapshot_service: Any | None = None,
        stage_service: StageRunService | None = None,
        artifact_store: ArtifactStore | None = None,
        event_store: EventStore | None = None,
        log_writer: RunLogWriter | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._audit_service = audit_service or _NoopAuditService()
        self._delivery_snapshot_service = delivery_snapshot_service
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
        self._interrupt_config = DeterministicInterruptConfig()
        self._terminal_config = DeterministicTerminalConfig()

    def configure_interrupts(
        self,
        config: DeterministicInterruptConfig | None = None,
        *,
        clarification: bool | None = None,
        solution_design_approval: bool | None = None,
        code_review_approval: bool | None = None,
        tool_confirmation: DeterministicToolConfirmationConfig | None = None,
    ) -> None:
        base = config or self._interrupt_config
        self._interrupt_config = DeterministicInterruptConfig(
            clarification=base.clarification if clarification is None else clarification,
            solution_design_approval=(
                base.solution_design_approval
                if solution_design_approval is None
                else solution_design_approval
            ),
            code_review_approval=(
                base.code_review_approval
                if code_review_approval is None
                else code_review_approval
            ),
            tool_confirmation=(
                tool_confirmation if tool_confirmation is not None else base.tool_confirmation
            ),
        )

    def configure_terminal_control(
        self,
        config: DeterministicTerminalConfig | None = None,
        *,
        complete_after_stages: bool | None = None,
        fail_at_stage: StageType | None = None,
        terminate_at_stage: StageType | None = None,
        failure_reason: str | None = None,
        termination_reason: str | None = None,
        completion_reason: str | None = None,
    ) -> None:
        base = config or self._terminal_config
        resolved_fail_at_stage = (
            fail_at_stage if fail_at_stage is not None else base.fail_at_stage
        )
        resolved_terminate_at_stage = (
            terminate_at_stage
            if terminate_at_stage is not None
            else base.terminate_at_stage
        )
        if (
            resolved_fail_at_stage is not None
            and resolved_terminate_at_stage is not None
        ):
            raise ValueError(
                "deterministic terminal control cannot configure both failure and termination"
            )
        self._terminal_config = DeterministicTerminalConfig(
            complete_after_stages=(
                base.complete_after_stages
                if complete_after_stages is None
                else complete_after_stages
            ),
            fail_at_stage=resolved_fail_at_stage,
            terminate_at_stage=resolved_terminate_at_stage,
            failure_reason=(
                base.failure_reason if failure_reason is None else failure_reason
            ),
            termination_reason=(
                base.termination_reason
                if termination_reason is None
                else termination_reason
            ),
            completion_reason=(
                base.completion_reason
                if completion_reason is None
                else completion_reason
            ),
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
    ) -> RuntimeEngineResult:
        try:
            next_stage = self._next_stage(context.run_id)
        except ValueError as exc:
            if (
                "deterministic stage sequence is exhausted" in str(exc)
                and self._terminal_config.complete_after_stages
                and self._stage_sequence_completed(context.run_id)
            ):
                return self.emit_completed_terminal_result(
                    context=context,
                    runtime_port=runtime_port,
                    checkpoint_port=checkpoint_port,
                    reason=self._terminal_config.completion_reason,
                )
            raise
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
        artifact = self._existing_stage_artifact(stage.stage_run_id)
        if artifact is None:
            artifact = self.emit_stage_artifacts(
                context=context,
                stage=stage,
                trace_context=stage_trace,
            )
        interrupt_previously_emitted = self._has_any_interrupt(stage)
        if interrupt_previously_emitted and stage.status is StageStatus.RUNNING:
            artifact = self._refresh_stage_output_artifact(
                context=context,
                stage=stage,
                artifact=artifact,
                trace_context=stage_trace,
            )
        interrupt_result = self._maybe_emit_interrupt(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            stage=stage,
            artifact=artifact,
            trace_context=stage_trace,
            start_event_ref=start_event.event_id if start_event is not None else None,
            interrupt_previously_emitted=interrupt_previously_emitted,
        )
        if interrupt_result is not None:
            return interrupt_result
        terminal_result = self._maybe_emit_terminal_result(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            stage=stage,
            artifact=artifact,
            trace_context=stage_trace,
            start_event_ref=start_event.event_id if start_event is not None else None,
        )
        if terminal_result is not None:
            return terminal_result
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
        resume_trace = context.trace_context.child_span(
            span_id=f"deterministic-resume-{interrupt.interrupt_ref.interrupt_id}",
            created_at=self._now(),
            stage_run_id=interrupt.stage_run_id,
            graph_thread_id=interrupt.interrupt_ref.thread.thread_id,
            approval_id=interrupt.interrupt_ref.approval_id,
            tool_confirmation_id=interrupt.interrupt_ref.tool_confirmation_id,
        )
        orchestration = self._runtime_orchestration(
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
        try:
            if (
                interrupt.interrupt_ref.interrupt_type
                is GraphInterruptType.TOOL_CONFIRMATION
            ):
                command_result = orchestration.resume_tool_confirmation(
                    interrupt=interrupt.interrupt_ref,
                    resume_payload=resume_payload,
                    trace_context=resume_trace,
                )
            else:
                command_result = orchestration.resume_interrupt(
                    interrupt=interrupt.interrupt_ref,
                    resume_payload=resume_payload,
                    trace_context=resume_trace,
                )
        except Exception as exc:
            self._runtime_session.rollback()
            if self._control_session is not None:
                self._control_session.rollback()
            self._event_session.rollback()
            self._write_resume_failure_log(
                context=context,
                interrupt=interrupt,
                resume_payload=resume_payload,
                trace_context=resume_trace,
                error=exc,
            )
            raise
        self._mark_running_after_interrupt(context=context, interrupt=interrupt)
        target_stage_type = self._resume_target_stage_type(
            source_stage_type=interrupt.stage_type,
            resume_payload=resume_payload,
        )
        log_ref = self._write_resume_log(
            context=context,
            interrupt=interrupt,
            resume_payload=resume_payload,
            command_result=command_result,
            source_stage_type=interrupt.stage_type,
            target_stage_type=target_stage_type,
            trace_context=resume_trace,
        )
        return RuntimeStepResult(
            run_id=context.run_id,
            stage_run_id=interrupt.stage_run_id,
            stage_type=target_stage_type,
            status=StageStatus.RUNNING,
            trace_context=resume_trace,
            artifact_refs=[],
            domain_event_refs=[],
            log_summary_refs=[log_ref] if log_ref is not None else [],
            audit_refs=[],
            checkpoint_ref=None,
        )

    def resume_from_interrupt(
        self,
        *,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeStepResult:
        result = self.resume(
            context=context,
            interrupt=interrupt,
            resume_payload=resume_payload,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
        if not isinstance(result, RuntimeStepResult):
            raise TypeError("deterministic interrupt resume must return a step result")
        return result

    def _maybe_emit_interrupt(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        trace_context: TraceContext,
        start_event_ref: str | None,
        interrupt_previously_emitted: bool,
    ) -> RuntimeInterrupt | None:
        if interrupt_previously_emitted:
            return None
        if (
            self._interrupt_config.clarification
            and stage.stage_type is StageType.REQUIREMENT_ANALYSIS
        ):
            if self._has_pending_clarification(stage):
                return None
            return self._emit_clarification_interrupt(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
                stage=stage,
                artifact=artifact,
                trace_context=trace_context,
                start_event_ref=start_event_ref,
            )
        if (
            self._interrupt_config.solution_design_approval
            and stage.stage_type is StageType.SOLUTION_DESIGN
        ):
            if self._has_pending_approval(stage):
                return None
            return self._emit_approval_interrupt(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
                stage=stage,
                artifact=artifact,
                approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
                trace_context=trace_context,
                start_event_ref=start_event_ref,
            )
        if (
            self._interrupt_config.code_review_approval
            and stage.stage_type is StageType.CODE_REVIEW
        ):
            if self._has_pending_approval(stage):
                return None
            return self._emit_approval_interrupt(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
                stage=stage,
                artifact=artifact,
                approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
                trace_context=trace_context,
                start_event_ref=start_event_ref,
            )
        tool_config = self._interrupt_config.tool_confirmation
        if tool_config is not None and stage.stage_type is tool_config.stage_type:
            if self._has_pending_tool_confirmation(stage):
                return None
            return self._emit_tool_confirmation_interrupt(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
                stage=stage,
                artifact=artifact,
                config=tool_config,
                trace_context=trace_context,
                start_event_ref=start_event_ref,
        )
        return None

    def _maybe_emit_terminal_result(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        trace_context: TraceContext,
        start_event_ref: str | None,
    ) -> RuntimeTerminalResult | None:
        config = self._terminal_config
        if config.fail_at_stage is stage.stage_type:
            return self.fail_run(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
                stage=stage,
                artifact=artifact,
                reason=config.failure_reason,
                trace_context=trace_context,
                start_event_ref=start_event_ref,
            )
        if config.terminate_at_stage is stage.stage_type:
            return self.terminate_run(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
                stage=stage,
                artifact=artifact,
                reason=config.termination_reason,
                trace_context=trace_context,
                start_event_ref=start_event_ref,
            )
        return None

    def _emit_clarification_interrupt(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        trace_context: TraceContext,
        start_event_ref: str | None,
    ) -> RuntimeInterrupt:
        capture_port = _CapturingRuntimeCommandPort(runtime_port)
        service = ClarificationService(
            control_session=self._require_control_session(),
            runtime_session=self._runtime_session,
            event_session=self._event_session,
            audit_service=self._audit_service,
            runtime_orchestration=self._runtime_orchestration(
                runtime_port=capture_port,
                checkpoint_port=checkpoint_port,
            ),
            now=self._now,
        )
        result = service.request_clarification(
            session_id=context.session_id,
            run_id=context.run_id,
            stage_run_id=stage.stage_run_id,
            question="Confirm the deterministic requirement interpretation.",
            payload_ref=artifact.artifact_id,
            trace_context=trace_context,
        )
        clarification = self._runtime_session.get(
            ClarificationRecordModel,
            result.clarification_id,
        )
        run = self._load_run(context.run_id)
        if clarification is None:
            raise RuntimeError("ClarificationRecord was not persisted.")
        interrupt_ref = self._clarification_interrupt_ref(
            clarification=clarification,
            run=run,
            stage=stage,
            interrupt_ref=capture_port.last_interrupt,
        )
        event_refs = self._event_refs(
            context=context,
            stage=stage,
            start_event_ref=start_event_ref,
            event_type=SseEventType.CLARIFICATION_REQUESTED,
        )
        log_ref = self._write_interrupt_log(
            context=context,
            stage=stage,
            interrupt_ref=interrupt_ref,
            artifact_refs=[artifact.artifact_id],
            event_refs=event_refs,
            trace_context=trace_context,
            result_status="waiting_clarification",
        )
        return self._interrupt_result(
            context=context,
            stage=stage,
            interrupt_ref=interrupt_ref,
            artifact_refs=[artifact.artifact_id],
            event_refs=event_refs,
            log_ref=log_ref,
            trace_context=trace_context,
        )

    def _emit_approval_interrupt(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        approval_type: ApprovalType,
        trace_context: TraceContext,
        start_event_ref: str | None,
    ) -> RuntimeInterrupt:
        capture_port = _CapturingRuntimeCommandPort(runtime_port)
        service = ApprovalService(
            control_session=self._require_control_session(),
            runtime_session=self._runtime_session,
            event_session=self._event_session,
            runtime_orchestration=self._runtime_orchestration(
                runtime_port=capture_port,
                checkpoint_port=checkpoint_port,
            ),
            audit_service=self._audit_service,
            delivery_snapshot_service=self._delivery_snapshot_service,
            log_writer=self._log_writer or _NoopRunLogWriter(),
            redaction_policy=self._redaction_policy,
            now=self._now,
        )
        common_kwargs = {
            "session_id": context.session_id,
            "run_id": context.run_id,
            "stage_run_id": stage.stage_run_id,
            "payload_ref": artifact.artifact_id,
            "approval_object_excerpt": self._approval_excerpt(approval_type),
            "risk_excerpt": "Deterministic runtime approval fixture.",
            "approval_object_preview": {
                "artifact_id": artifact.artifact_id,
                "stage_type": stage.stage_type.value,
            },
            "trace_context": trace_context,
        }
        if approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL:
            result = service.create_solution_design_approval(**common_kwargs)
        else:
            result = service.create_code_review_approval(**common_kwargs)
        approval = self._runtime_session.get(ApprovalRequestModel, result.approval_id)
        run = self._load_run(context.run_id)
        if approval is None:
            raise RuntimeError("ApprovalRequest was not persisted.")
        interrupt_ref = self._approval_interrupt_ref(
            approval=approval,
            run=run,
            stage=stage,
            interrupt_ref=capture_port.last_interrupt,
        )
        event_refs = self._event_refs(
            context=context,
            stage=stage,
            start_event_ref=start_event_ref,
            event_type=SseEventType.APPROVAL_REQUESTED,
        )
        log_ref = self._write_interrupt_log(
            context=context,
            stage=stage,
            interrupt_ref=interrupt_ref,
            artifact_refs=[artifact.artifact_id],
            event_refs=event_refs,
            trace_context=trace_context,
            result_status="waiting_approval",
        )
        return self._interrupt_result(
            context=context,
            stage=stage,
            interrupt_ref=interrupt_ref,
            artifact_refs=[artifact.artifact_id],
            event_refs=event_refs,
            log_ref=log_ref,
            trace_context=trace_context,
        )

    def _emit_tool_confirmation_interrupt(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        config: DeterministicToolConfirmationConfig,
        trace_context: TraceContext,
        start_event_ref: str | None,
    ) -> RuntimeInterrupt:
        capture_port = _CapturingRuntimeCommandPort(runtime_port)
        service = ToolConfirmationService(
            control_session=self._require_control_session(),
            runtime_session=self._runtime_session,
            event_session=self._event_session,
            runtime_orchestration=self._runtime_orchestration(
                runtime_port=capture_port,
                checkpoint_port=checkpoint_port,
            ),
            audit_service=self._audit_service,
            log_writer=self._log_writer or _NoopRunLogWriter(),
            redaction_policy=self._redaction_policy,
            now=self._now,
        )
        risk_categories = config.risk_categories or [
            ToolRiskCategory.UNKNOWN_COMMAND,
        ]
        result = service.create_request(
            session_id=context.session_id,
            run_id=context.run_id,
            stage_run_id=stage.stage_run_id,
            confirmation_object_ref=artifact.artifact_id,
            tool_name=config.tool_name,
            command_preview=config.command_preview,
            target_summary=config.target_summary,
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=risk_categories,
            reason=config.reason,
            expected_side_effects=config.expected_side_effects
            or ["A deterministic high-risk tool action would run."],
            alternative_path_summary=config.alternative_path_summary,
            planned_deny_followup_action=config.planned_deny_followup_action,
            planned_deny_followup_summary=config.planned_deny_followup_summary,
            trace_context=trace_context,
        )
        request = self._runtime_session.get(
            ToolConfirmationRequestModel,
            result.tool_confirmation_id,
        )
        run = self._load_run(context.run_id)
        if request is None:
            raise RuntimeError("ToolConfirmationRequest was not persisted.")
        interrupt_ref = self._tool_confirmation_interrupt_ref(
            request=request,
            run=run,
            stage=stage,
            interrupt_ref=capture_port.last_interrupt,
        )
        event_refs = self._event_refs(
            context=context,
            stage=stage,
            start_event_ref=start_event_ref,
            event_type=SseEventType.TOOL_CONFIRMATION_REQUESTED,
        )
        log_ref = self._write_interrupt_log(
            context=context,
            stage=stage,
            interrupt_ref=interrupt_ref,
            artifact_refs=[artifact.artifact_id],
            event_refs=event_refs,
            trace_context=trace_context,
            result_status="waiting_tool_confirmation",
        )
        return self._interrupt_result(
            context=context,
            stage=stage,
            interrupt_ref=interrupt_ref,
            artifact_refs=[artifact.artifact_id],
            event_refs=event_refs,
            log_ref=log_ref,
            trace_context=trace_context,
        )

    def terminate(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeTerminalResult:
        run = self._load_run(context.run_id)
        if run.current_stage_run_id is None:
            raise ValueError("deterministic terminate requires a current stage")
        stage = self._runtime_session.get(StageRunModel, run.current_stage_run_id)
        if stage is None:
            raise ValueError("deterministic terminate current stage was not found")
        self._require_non_terminal_current_stage(stage)
        terminate_trace = context.trace_context.child_span(
            span_id=f"deterministic-terminate-{stage.stage_run_id}",
            created_at=self._now(),
            run_id=context.run_id,
            stage_run_id=stage.stage_run_id,
            graph_thread_id=context.thread.thread_id,
        )
        artifact = self._existing_stage_artifact(stage.stage_run_id)
        if artifact is None:
            artifact = self.emit_stage_artifacts(
                context=context,
                stage=stage,
                trace_context=terminate_trace,
            )
        return self.terminate_run(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            stage=stage,
            artifact=artifact,
            reason="Deterministic runtime termination requested.",
            trace_context=terminate_trace,
        )

    def fail_run(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        reason: str,
        trace_context: TraceContext,
        start_event_ref: str | None = None,
    ) -> RuntimeTerminalResult:
        return self.emit_terminal_result(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            terminal_status=GraphThreadStatus.FAILED,
            run_status=RunStatus.FAILED,
            stage=stage,
            artifact=artifact,
            reason=reason,
            direct_failure_point=stage.stage_type.value,
            trace_context=trace_context,
            start_event_ref=start_event_ref,
        )

    def terminate_run(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        reason: str,
        trace_context: TraceContext,
        start_event_ref: str | None = None,
    ) -> RuntimeTerminalResult:
        run = self._load_run(context.run_id)
        thread = self._terminal_source_thread(
            context=context,
            run=run,
            stage=stage,
        )
        try:
            command_result = self._runtime_orchestration(
                runtime_port=runtime_port,
                checkpoint_port=checkpoint_port,
            ).terminate_thread(
                thread=thread,
                trace_context=trace_context,
            )
        except Exception:
            self._runtime_session.rollback()
            self._event_session.rollback()
            if self._control_session is not None:
                self._control_session.rollback()
            raise
        return self.emit_terminal_result(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            terminal_status=GraphThreadStatus.TERMINATED,
            run_status=RunStatus.TERMINATED,
            stage=stage,
            artifact=artifact,
            reason=reason,
            direct_failure_point=stage.stage_type.value,
            trace_context=command_result.trace_context,
            thread=command_result.thread,
            start_event_ref=start_event_ref,
        )

    def emit_terminal_result(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        terminal_status: GraphThreadStatus,
        run_status: RunStatus,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        reason: str,
        direct_failure_point: str,
        trace_context: TraceContext,
        thread: GraphThreadRef | None = None,
        start_event_ref: str | None = None,
    ) -> RuntimeTerminalResult:
        del runtime_port, checkpoint_port
        control_session_db = self._require_control_session()
        control_session = control_session_db.get(SessionModel, context.session_id)
        if control_session is None:
            raise ValueError("deterministic terminal control session was not found")
        run = self._load_run(context.run_id)
        self._validate_terminal_source_identity(
            context=context,
            run=run,
            stage=stage,
            artifact=artifact,
        )
        self._require_non_terminal_current_stage(stage)
        occurred_at = self._now()
        terminal_trace = trace_context.child_span(
            span_id=f"deterministic-terminal-{run_status.value}-{context.run_id}",
            created_at=occurred_at,
            run_id=context.run_id,
            stage_run_id=stage.stage_run_id,
            graph_thread_id=context.thread.thread_id,
        )

        run.status = run_status
        run.ended_at = occurred_at
        run.updated_at = occurred_at
        stage.status = self._stage_status_for_terminal(run_status)
        stage.output_ref = artifact.artifact_id
        stage.summary = reason
        stage.ended_at = occurred_at
        stage.updated_at = occurred_at
        control_session.status = self._session_status_for_terminal(run_status)
        control_session.latest_stage_type = stage.stage_type
        control_session.updated_at = occurred_at
        self._runtime_session.add_all([run, stage])
        control_session_db.add(control_session)

        self._artifact_store.append_process_record(
            artifact_id=artifact.artifact_id,
            process_key="terminal_result",
            process_value={
                "status": run_status.value,
                "reason": reason,
                "direct_failure_point": direct_failure_point,
                "source_stage_type": stage.stage_type.value,
                "retry_action": f"retry:{run.run_id}",
            },
            trace_context=terminal_trace,
        )
        stage_event = self._append_stage_event(
            DomainEventType.STAGE_UPDATED,
            context=context,
            stage=stage,
            status=stage.status,
            trace_context=terminal_trace,
            item_title=f"{_STAGE_TITLES[stage.stage_type]} terminal result",
            item_summary=reason,
            artifact_refs=[artifact.artifact_id],
        )
        domain_event_refs = [
            *([start_event_ref] if start_event_ref is not None else []),
            stage_event.event_id,
        ]
        if run_status in {RunStatus.FAILED, RunStatus.TERMINATED}:
            domain_event_type = (
                DomainEventType.RUN_TERMINATED
                if run_status is RunStatus.TERMINATED
                else DomainEventType.RUN_FAILED
            )
            TerminalStatusProjector(
                events=self._event_store,
                now=self._now,
            ).append_terminal_system_status(
                domain_event_type=domain_event_type,
                run=run,
                title="Run terminated"
                if run_status is RunStatus.TERMINATED
                else "Run failed",
                reason=reason,
                trace_context=terminal_trace,
                is_current_tail=control_session.current_run_id == run.run_id,
                occurred_at=occurred_at,
            )
            system_status_ref = self._latest_event_ref(
                session_id=context.session_id,
                run_id=context.run_id,
                event_type=SseEventType.SYSTEM_STATUS,
            )
            if system_status_ref is not None:
                domain_event_refs.append(system_status_ref)
        self._runtime_session.commit()
        control_session_db.commit()
        self._event_session.commit()

        terminal_thread = thread or self._thread_ref(
            run=run,
            stage=stage,
            status=terminal_status,
        )
        if terminal_thread.status is not terminal_status:
            terminal_thread = terminal_thread.model_copy(
                update={"status": terminal_status}
            )
        result_ref = f"deterministic://{context.run_id}/terminal/{run_status.value}"
        log_ref = self._write_terminal_log(
            context=context,
            stage=stage,
            terminal_status=terminal_status,
            run_status=run_status,
            reason=reason,
            direct_failure_point=direct_failure_point,
            artifact_refs=[artifact.artifact_id],
            event_refs=domain_event_refs,
            result_ref=result_ref,
            terminal_trace=terminal_trace,
        )
        return RuntimeTerminalResult(
            run_id=context.run_id,
            status=terminal_status,
            thread=terminal_thread,
            trace_context=terminal_trace,
            result_ref=result_ref,
            artifact_refs=[artifact.artifact_id],
            domain_event_refs=domain_event_refs,
            log_summary_refs=[log_ref] if log_ref is not None else [],
            audit_refs=[],
        )

    def emit_completed_terminal_result(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
        reason: str,
    ) -> RuntimeTerminalResult:
        del runtime_port, checkpoint_port
        control_session_db = self._require_control_session()
        control_session = control_session_db.get(SessionModel, context.session_id)
        if control_session is None:
            raise ValueError("deterministic terminal control session was not found")
        run = self._load_run(context.run_id)
        occurred_at = self._now()
        terminal_trace = context.trace_context.child_span(
            span_id=f"deterministic-terminal-completed-{context.run_id}",
            created_at=occurred_at,
            run_id=context.run_id,
            stage_run_id=None,
            graph_thread_id=context.thread.thread_id,
        )
        run.status = RunStatus.COMPLETED
        run.current_stage_run_id = None
        run.ended_at = occurred_at
        run.updated_at = occurred_at
        control_session.status = SessionStatus.COMPLETED
        control_session.updated_at = occurred_at
        self._runtime_session.add(run)
        control_session_db.add(control_session)
        event = self._event_store.append(
            DomainEventType.RUN_COMPLETED,
            payload={
                "session_id": context.session_id,
                "status": SessionStatus.COMPLETED.value,
                "current_run_id": context.run_id,
                "current_stage_type": None,
            },
            trace_context=terminal_trace,
            session_id=context.session_id,
            run_id=context.run_id,
        )
        self._runtime_session.commit()
        control_session_db.commit()
        self._event_session.commit()
        result_ref = f"deterministic://{context.run_id}/terminal/completed"
        log_ref = self._write_terminal_log(
            context=context,
            stage=None,
            terminal_status=GraphThreadStatus.COMPLETED,
            run_status=RunStatus.COMPLETED,
            reason=reason,
            direct_failure_point=None,
            artifact_refs=[],
            event_refs=[event.event_id],
            result_ref=result_ref,
            terminal_trace=terminal_trace,
        )
        return RuntimeTerminalResult(
            run_id=context.run_id,
            status=GraphThreadStatus.COMPLETED,
            thread=context.thread.model_copy(
                update={
                    "status": GraphThreadStatus.COMPLETED,
                    "current_stage_run_id": None,
                    "current_stage_type": None,
                }
            ),
            trace_context=terminal_trace,
            result_ref=result_ref,
            artifact_refs=[],
            domain_event_refs=[event.event_id],
            log_summary_refs=[log_ref] if log_ref is not None else [],
            audit_refs=[],
        )

    def _runtime_orchestration(
        self,
        *,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeOrchestrationService:
        return RuntimeOrchestrationService(
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            clock=self._now,
        )

    def _require_control_session(self) -> Session:
        if self._control_session is None:
            raise ValueError("control_session is required for deterministic interrupts")
        return self._control_session

    def _load_run(self, run_id: str) -> PipelineRunModel:
        run = self._runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise ValueError("PipelineRun was not found.")
        return run

    def _latest_event_ref(
        self,
        *,
        session_id: str,
        run_id: str,
        event_type: SseEventType,
    ) -> str | None:
        event = (
            self._event_session.query(DomainEventModel)
            .filter(
                DomainEventModel.event_type == event_type,
                DomainEventModel.session_id == session_id,
                DomainEventModel.run_id == run_id,
            )
            .order_by(
                DomainEventModel.sequence_index.desc(),
                DomainEventModel.event_id.desc(),
            )
            .first()
        )
        return event.event_id if event is not None else None

    def _stage_sequence_completed(self, run_id: str) -> bool:
        rows = self._runtime_session.execute(
            select(StageRunModel).where(StageRunModel.run_id == run_id)
        ).scalars().all()
        rows_by_stage = {row.stage_type: row for row in rows}
        return all(
            (stage := rows_by_stage.get(stage_type)) is not None
            and stage.status is StageStatus.COMPLETED
            for stage_type in DETERMINISTIC_STAGE_SEQUENCE
        )

    def _terminal_source_thread(
        self,
        *,
        context: RuntimeExecutionContext,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> GraphThreadRef:
        if (
            context.thread.current_stage_run_id == stage.stage_run_id
            and context.thread.current_stage_type is stage.stage_type
        ):
            return context.thread
        return self._thread_ref(
            run=run,
            stage=stage,
            status=context.thread.status,
        )

    def _validate_terminal_source_identity(
        self,
        *,
        context: RuntimeExecutionContext,
        run: PipelineRunModel,
        stage: StageRunModel,
        artifact: StageArtifactModel,
    ) -> None:
        if stage.run_id != context.run_id:
            raise ValueError("terminal source identity mismatch")
        if run.current_stage_run_id != stage.stage_run_id:
            raise ValueError("terminal source identity mismatch")
        if artifact.run_id != context.run_id or artifact.run_id != stage.run_id:
            raise ValueError("terminal source identity mismatch")
        if artifact.stage_run_id != stage.stage_run_id:
            raise ValueError("terminal source identity mismatch")

    def _require_non_terminal_current_stage(self, stage: StageRunModel) -> None:
        if stage.status in _TERMINAL_STAGE_STATUSES:
            raise ValueError("deterministic terminal control requires a non-terminal current stage")

    @staticmethod
    def _stage_status_for_terminal(run_status: RunStatus) -> StageStatus:
        if run_status is RunStatus.FAILED:
            return StageStatus.FAILED
        if run_status is RunStatus.TERMINATED:
            return StageStatus.TERMINATED
        if run_status is RunStatus.COMPLETED:
            return StageStatus.COMPLETED
        raise ValueError("deterministic terminal run status is unsupported")

    @staticmethod
    def _session_status_for_terminal(run_status: RunStatus) -> SessionStatus:
        if run_status is RunStatus.FAILED:
            return SessionStatus.FAILED
        if run_status is RunStatus.TERMINATED:
            return SessionStatus.TERMINATED
        if run_status is RunStatus.COMPLETED:
            return SessionStatus.COMPLETED
        raise ValueError("deterministic terminal run status is unsupported")

    def _has_pending_clarification(self, stage: StageRunModel) -> bool:
        return (
            self._runtime_session.query(ClarificationRecordModel)
            .filter(
                ClarificationRecordModel.run_id == stage.run_id,
                ClarificationRecordModel.stage_run_id == stage.stage_run_id,
                ClarificationRecordModel.answer.is_(None),
                ClarificationRecordModel.answered_at.is_(None),
            )
            .first()
            is not None
        )

    def _has_pending_approval(self, stage: StageRunModel) -> bool:
        return (
            self._runtime_session.query(ApprovalRequestModel)
            .filter(
                ApprovalRequestModel.run_id == stage.run_id,
                ApprovalRequestModel.stage_run_id == stage.stage_run_id,
                ApprovalRequestModel.status == ApprovalStatus.PENDING,
            )
            .first()
            is not None
        )

    def _has_pending_tool_confirmation(self, stage: StageRunModel) -> bool:
        return (
            self._runtime_session.query(ToolConfirmationRequestModel)
            .filter(
                ToolConfirmationRequestModel.run_id == stage.run_id,
                ToolConfirmationRequestModel.stage_run_id == stage.stage_run_id,
                ToolConfirmationRequestModel.status == ToolConfirmationStatus.PENDING,
            )
            .first()
            is not None
        )

    def _has_any_interrupt(self, stage: StageRunModel) -> bool:
        if (
            self._runtime_session.query(ClarificationRecordModel)
            .filter(
                ClarificationRecordModel.run_id == stage.run_id,
                ClarificationRecordModel.stage_run_id == stage.stage_run_id,
            )
            .first()
            is not None
        ):
            return True
        if (
            self._runtime_session.query(ApprovalRequestModel)
            .filter(
                ApprovalRequestModel.run_id == stage.run_id,
                ApprovalRequestModel.stage_run_id == stage.stage_run_id,
            )
            .first()
            is not None
        ):
            return True
        return (
            self._runtime_session.query(ToolConfirmationRequestModel)
            .filter(
                ToolConfirmationRequestModel.run_id == stage.run_id,
                ToolConfirmationRequestModel.stage_run_id == stage.stage_run_id,
            )
            .first()
            is not None
        )

    def _event_refs(
        self,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel,
        start_event_ref: str | None,
        event_type: SseEventType,
    ) -> list[str]:
        refs = [start_event_ref] if start_event_ref is not None else []
        event = (
            self._event_session.query(DomainEventModel)
            .filter(
                DomainEventModel.event_type == event_type,
                DomainEventModel.session_id == context.session_id,
                DomainEventModel.run_id == context.run_id,
                DomainEventModel.stage_run_id == stage.stage_run_id,
            )
            .order_by(
                DomainEventModel.sequence_index.desc(),
                DomainEventModel.event_id.desc(),
            )
            .first()
        )
        if event is not None:
            refs.append(event.event_id)
        return refs

    def _clarification_interrupt_ref(
        self,
        *,
        clarification: ClarificationRecordModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        interrupt_ref: GraphInterruptRef | None = None,
    ) -> GraphInterruptRef:
        if interrupt_ref is not None:
            return interrupt_ref
        thread = self._thread_ref(
            run=run,
            stage=stage,
            status=GraphThreadStatus.WAITING_CLARIFICATION,
        )
        return GraphInterruptRef(
            interrupt_id=clarification.graph_interrupt_ref,
            thread=thread,
            interrupt_type=GraphInterruptType.CLARIFICATION_REQUEST,
            status=GraphInterruptStatus.PENDING,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            payload_ref=clarification.payload_ref or clarification.clarification_id,
            clarification_id=clarification.clarification_id,
            checkpoint_ref=self._checkpoint_stub(
                run=run,
                stage=stage,
                purpose=CheckpointPurpose.WAITING_CLARIFICATION,
                payload_ref=clarification.payload_ref or clarification.clarification_id,
            ),
        )

    def _approval_interrupt_ref(
        self,
        *,
        approval: ApprovalRequestModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        interrupt_ref: GraphInterruptRef | None = None,
    ) -> GraphInterruptRef:
        if interrupt_ref is not None:
            return interrupt_ref
        thread = self._thread_ref(
            run=run,
            stage=stage,
            status=GraphThreadStatus.WAITING_APPROVAL,
        )
        return GraphInterruptRef(
            interrupt_id=approval.graph_interrupt_ref,
            thread=thread,
            interrupt_type=GraphInterruptType.APPROVAL,
            status=GraphInterruptStatus.PENDING,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            payload_ref=approval.payload_ref,
            approval_id=approval.approval_id,
            checkpoint_ref=self._checkpoint_stub(
                run=run,
                stage=stage,
                purpose=CheckpointPurpose.WAITING_APPROVAL,
                payload_ref=approval.payload_ref,
            ),
        )

    def _tool_confirmation_interrupt_ref(
        self,
        *,
        request: ToolConfirmationRequestModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        interrupt_ref: GraphInterruptRef | None = None,
    ) -> GraphInterruptRef:
        if interrupt_ref is not None:
            return interrupt_ref
        thread = self._thread_ref(
            run=run,
            stage=stage,
            status=GraphThreadStatus.WAITING_TOOL_CONFIRMATION,
        )
        return GraphInterruptRef(
            interrupt_id=request.graph_interrupt_ref,
            thread=thread,
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            status=GraphInterruptStatus.PENDING,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            payload_ref=request.tool_confirmation_id,
            tool_confirmation_id=request.tool_confirmation_id,
            tool_action_ref=request.confirmation_object_ref,
            checkpoint_ref=self._checkpoint_stub(
                run=run,
                stage=stage,
                purpose=CheckpointPurpose.WAITING_TOOL_CONFIRMATION,
                payload_ref=request.tool_confirmation_id,
            ),
        )

    def _thread_ref(
        self,
        *,
        run: PipelineRunModel,
        stage: StageRunModel,
        status: GraphThreadStatus,
    ) -> GraphThreadRef:
        return GraphThreadRef(
            thread_id=run.graph_thread_ref,
            run_id=run.run_id,
            status=status,
            current_stage_run_id=stage.stage_run_id,
            current_stage_type=stage.stage_type,
        )

    @staticmethod
    def _checkpoint_stub(
        *,
        run: PipelineRunModel,
        stage: StageRunModel,
        purpose: CheckpointPurpose,
        payload_ref: str,
    ) -> CheckpointRef:
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{payload_ref}",
            thread_id=run.graph_thread_ref,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            purpose=purpose,
            workspace_snapshot_ref=None,
            payload_ref=payload_ref,
        )

    def _interrupt_result(
        self,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel,
        interrupt_ref: GraphInterruptRef,
        artifact_refs: list[str],
        event_refs: list[str],
        log_ref: str | None,
        trace_context: TraceContext,
    ) -> RuntimeInterrupt:
        return RuntimeInterrupt(
            run_id=context.run_id,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            interrupt_ref=interrupt_ref,
            payload_ref=interrupt_ref.payload_ref,
            trace_context=trace_context,
            artifact_refs=artifact_refs,
            domain_event_refs=event_refs,
            log_summary_refs=[log_ref] if log_ref is not None else [],
            audit_refs=[],
        )

    @staticmethod
    def _approval_excerpt(approval_type: ApprovalType) -> str:
        if approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL:
            return "Review the deterministic solution design artifact."
        return "Review the deterministic code review artifact."

    def _write_interrupt_log(
        self,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel,
        interrupt_ref: GraphInterruptRef,
        artifact_refs: list[str],
        event_refs: list[str],
        trace_context: TraceContext,
        result_status: str,
    ) -> str | None:
        if self._log_writer is None:
            return None
        payload = {
            "action": "deterministic_interrupt_requested",
            "run_id": stage.run_id,
            "session_id": context.session_id,
            "stage_run_id": stage.stage_run_id,
            "stage_type": stage.stage_type.value,
            "graph_thread_id": interrupt_ref.thread.thread_id,
            "interrupt_id": interrupt_ref.interrupt_id,
            "interrupt_type": interrupt_ref.interrupt_type.value,
            "payload_ref": interrupt_ref.payload_ref,
            "artifact_refs": artifact_refs,
            "event_refs": event_refs,
            "checkpoint_ref": interrupt_ref.checkpoint_ref.checkpoint_id,
            "result_status": result_status,
            "span_id": trace_context.span_id,
            **(
                {"clarification_id": interrupt_ref.clarification_id}
                if interrupt_ref.clarification_id is not None
                else {}
            ),
            **(
                {"approval_id": interrupt_ref.approval_id}
                if interrupt_ref.approval_id is not None
                else {}
            ),
            **(
                {"tool_confirmation_id": interrupt_ref.tool_confirmation_id}
                if interrupt_ref.tool_confirmation_id is not None
                else {}
            ),
        }
        try:
            redacted = self._redaction_policy.summarize_payload(
                payload,
                payload_type="deterministic_runtime_interrupt",
            )
            summary = LogPayloadSummary.from_redacted_payload(
                "deterministic_runtime_interrupt",
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
                    message="Deterministic runtime requested an interrupt.",
                    trace_context=trace_context,
                    payload=summary,
                    created_at=self._now(),
                )
            )
            log_id = getattr(result, "log_id", None)
            return log_id if isinstance(log_id, str) and log_id else None
        except Exception:
            _LOGGER.exception(
                "Deterministic runtime interrupt log write failed for stage_run_id=%s",
                stage.stage_run_id,
            )
            return None

    def _mark_running_after_interrupt(
        self,
        *,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
    ) -> None:
        timestamp = self._now()
        run = self._runtime_session.get(PipelineRunModel, context.run_id)
        stage = self._runtime_session.get(StageRunModel, interrupt.stage_run_id)
        if run is None or stage is None:
            raise ValueError("deterministic interrupt resume target was not found")
        control_session = None
        if self._control_session is not None:
            control_session = self._control_session.get(SessionModel, context.session_id)
        if self._control_session is not None and control_session is None:
            raise ValueError("deterministic interrupt control session was not found")
        run.status = RunStatus.RUNNING
        run.updated_at = timestamp
        stage.status = StageStatus.RUNNING
        stage.updated_at = timestamp
        self._runtime_session.add_all([run, stage])
        if control_session is not None:
            control_session.status = SessionStatus.RUNNING
            control_session.updated_at = timestamp
            self._control_session.add(control_session)
            self._control_session.commit()
        self._runtime_session.commit()

    def _existing_stage_artifact(self, stage_run_id: str) -> StageArtifactModel | None:
        return (
            self._runtime_session.execute(
                select(StageArtifactModel)
                .where(StageArtifactModel.stage_run_id == stage_run_id)
                .order_by(StageArtifactModel.created_at.asc())
            )
            .scalars()
            .first()
        )

    def _refresh_stage_output_artifact(
        self,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel,
        artifact: StageArtifactModel,
        trace_context: TraceContext,
    ) -> StageArtifactModel:
        process = dict(artifact.process or {})
        process["output_snapshot"] = self._output_snapshot_for_stage(stage.stage_type)
        process["output_refs"] = []
        artifact.payload_ref = (
            f"deterministic://{context.run_id}/{stage.stage_type.value}/output"
        )
        artifact.process = process
        stage.output_ref = artifact.artifact_id
        stage.updated_at = trace_context.created_at
        self._runtime_session.flush()
        return artifact

    @staticmethod
    def _resume_target_stage_type(
        *,
        source_stage_type: StageType,
        resume_payload: RuntimeResumePayload,
    ) -> StageType:
        if (
            resume_payload.values.get("decision") == "rejected"
            and resume_payload.values.get("next_stage_type") is not None
        ):
            return StageType(str(resume_payload.values["next_stage_type"]))
        return source_stage_type

    def _write_resume_log(
        self,
        *,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        command_result: object,
        source_stage_type: StageType,
        target_stage_type: StageType,
        trace_context: TraceContext,
    ) -> str | None:
        if self._log_writer is None:
            return None
        payload = {
            "action": "deterministic_interrupt_resumed",
            "run_id": context.run_id,
            "session_id": context.session_id,
            "stage_run_id": interrupt.stage_run_id,
            "source_stage_type": source_stage_type.value,
            "target_stage_type": target_stage_type.value,
            "graph_thread_id": interrupt.interrupt_ref.thread.thread_id,
            "interrupt_id": interrupt.interrupt_ref.interrupt_id,
            "interrupt_type": interrupt.interrupt_ref.interrupt_type.value,
            "decision": resume_payload.values.get("decision"),
            "payload_ref": resume_payload.payload_ref,
            "result_status": "running",
            "span_id": trace_context.span_id,
        }
        command_payload_ref = getattr(command_result, "payload_ref", None)
        if command_payload_ref is not None:
            payload["command_payload_ref"] = command_payload_ref
        try:
            redacted = self._redaction_policy.summarize_payload(
                payload,
                payload_type="deterministic_runtime_resume",
            )
            summary = LogPayloadSummary.from_redacted_payload(
                "deterministic_runtime_resume",
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
                    message="Deterministic runtime resumed an interrupt.",
                    trace_context=trace_context,
                    payload=summary,
                    created_at=self._now(),
                )
            )
            log_id = getattr(result, "log_id", None)
            return log_id if isinstance(log_id, str) and log_id else None
        except Exception:
            _LOGGER.exception(
                "Deterministic runtime resume log write failed for stage_run_id=%s",
                interrupt.stage_run_id,
            )
            return None

    def _write_resume_failure_log(
        self,
        *,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        trace_context: TraceContext,
        error: Exception,
    ) -> str | None:
        if self._log_writer is None:
            return None
        payload = {
            "action": "deterministic_interrupt_resume_failed",
            "run_id": context.run_id,
            "session_id": context.session_id,
            "stage_run_id": interrupt.stage_run_id,
            "source_stage_type": interrupt.stage_type.value,
            "graph_thread_id": interrupt.interrupt_ref.thread.thread_id,
            "interrupt_id": interrupt.interrupt_ref.interrupt_id,
            "interrupt_type": interrupt.interrupt_ref.interrupt_type.value,
            "decision": resume_payload.values.get("decision"),
            "payload_ref": resume_payload.payload_ref,
            "result_status": "failed",
            "error_message": str(error),
            "span_id": trace_context.span_id,
        }
        try:
            redacted = self._redaction_policy.summarize_payload(
                payload,
                payload_type="deterministic_runtime_resume_failure",
            )
            summary = LogPayloadSummary.from_redacted_payload(
                "deterministic_runtime_resume_failure",
                redacted,
            )
            if isinstance(redacted.redacted_payload, Mapping):
                summary.summary.update(dict(redacted.redacted_payload))
            summary.summary.update(payload)
            result = self._log_writer.write_run_log(
                LogRecordInput(
                    source="runtime.deterministic",
                    category=LogCategory.RUNTIME,
                    level=LogLevel.ERROR,
                    message="Deterministic runtime failed to resume an interrupt.",
                    trace_context=trace_context,
                    payload=summary,
                    created_at=self._now(),
                )
            )
            log_id = getattr(result, "log_id", None)
            return log_id if isinstance(log_id, str) and log_id else None
        except Exception:
            _LOGGER.exception(
                "Deterministic runtime resume failure log write failed for stage_run_id=%s",
                interrupt.stage_run_id,
            )
            return None

    def _write_terminal_log(
        self,
        *,
        context: RuntimeExecutionContext,
        stage: StageRunModel | None,
        terminal_status: GraphThreadStatus,
        run_status: RunStatus,
        reason: str,
        direct_failure_point: str | None,
        artifact_refs: list[str],
        event_refs: list[str],
        result_ref: str,
        terminal_trace: TraceContext,
    ) -> str | None:
        if self._log_writer is None:
            return None
        retry_action = (
            f"retry:{context.run_id}"
            if run_status in {RunStatus.FAILED, RunStatus.TERMINATED}
            else None
        )
        payload = {
            "action": f"deterministic_terminal_{run_status.value}",
            "run_id": context.run_id,
            "session_id": context.session_id,
            "stage_run_id": stage.stage_run_id if stage is not None else None,
            "source_stage_type": stage.stage_type.value if stage is not None else None,
            "graph_thread_id": context.thread.thread_id,
            "terminal_status": terminal_status.value,
            "run_status": run_status.value,
            "terminal_reason": reason,
            "direct_failure_point": direct_failure_point,
            "retry_action": retry_action,
            "artifact_refs": artifact_refs,
            "event_refs": event_refs,
            "result_ref": result_ref,
            "span_id": terminal_trace.span_id,
        }
        try:
            redacted = self._redaction_policy.summarize_payload(
                payload,
                payload_type="deterministic_runtime_terminal",
            )
            summary = LogPayloadSummary.from_redacted_payload(
                "deterministic_runtime_terminal",
                redacted,
            )
            if isinstance(redacted.redacted_payload, Mapping):
                summary.summary.update(dict(redacted.redacted_payload))
            summary.summary.update(payload)
            result = self._log_writer.write_run_log(
                LogRecordInput(
                    source="runtime.deterministic",
                    category=LogCategory.RUNTIME,
                    level=LogLevel.ERROR
                    if run_status is RunStatus.FAILED
                    else LogLevel.INFO,
                    message="Deterministic runtime emitted a terminal result.",
                    trace_context=terminal_trace,
                    payload=summary,
                    created_at=self._now(),
                )
            )
            log_id = getattr(result, "log_id", None)
            return log_id if isinstance(log_id, str) and log_id else None
        except Exception:
            _LOGGER.exception(
                "Deterministic runtime terminal log write failed for stage_run_id=%s",
                stage.stage_run_id if stage is not None else None,
            )
            return None

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
    "DeterministicInterruptConfig",
    "DeterministicRuntimeEngine",
    "DeterministicToolConfirmationConfig",
]


def _bounded_id(*, prefix: str, seed: str) -> str:
    candidate = f"{prefix}-{seed}"
    if len(candidate) <= 80:
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"
