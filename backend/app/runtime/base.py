from __future__ import annotations

from typing import Annotated, Protocol, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.runtime_refs import (
    CheckpointRef,
    GraphInterruptRef,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.services.runtime_orchestration import CheckpointPort, RuntimeCommandPort


NonEmptyRef = Annotated[str, Field(min_length=1)]

_TERMINAL_THREAD_STATUSES = frozenset(
    {
        GraphThreadStatus.COMPLETED,
        GraphThreadStatus.FAILED,
        GraphThreadStatus.TERMINATED,
    }
)


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_equal(
    *,
    field_name: str,
    value: object,
    expected_field_name: str,
    expected_value: object,
) -> None:
    if value != expected_value:
        raise ValueError(
            f"{field_name} must match {expected_field_name}: "
            f"{value!r} != {expected_value!r}"
        )


def _require_optional_equal(
    *,
    field_name: str,
    value: object | None,
    expected_field_name: str,
    expected_value: object,
) -> None:
    if value is not None:
        _require_equal(
            field_name=field_name,
            value=value,
            expected_field_name=expected_field_name,
            expected_value=expected_value,
        )


class RuntimeExecutionContext(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    thread: GraphThreadRef
    trace_context: TraceContext
    template_snapshot_ref: str = Field(min_length=1)
    provider_snapshot_refs: list[NonEmptyRef] = Field(min_length=1)
    model_binding_snapshot_refs: list[NonEmptyRef] = Field(min_length=1)
    runtime_limit_snapshot_ref: str = Field(min_length=1)
    provider_call_policy_snapshot_ref: str = Field(min_length=1)
    graph_definition_ref: str = Field(min_length=1)
    delivery_channel_snapshot_ref: str | None = Field(default=None, min_length=1)
    workspace_snapshot_ref: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_identity_consistency(self) -> Self:
        _require_equal(
            field_name="thread.run_id",
            value=self.thread.run_id,
            expected_field_name="run_id",
            expected_value=self.run_id,
        )
        _require_optional_equal(
            field_name="trace_context.run_id",
            value=self.trace_context.run_id,
            expected_field_name="run_id",
            expected_value=self.run_id,
        )
        _require_optional_equal(
            field_name="trace_context.session_id",
            value=self.trace_context.session_id,
            expected_field_name="session_id",
            expected_value=self.session_id,
        )
        _require_optional_equal(
            field_name="trace_context.graph_thread_id",
            value=self.trace_context.graph_thread_id,
            expected_field_name="thread.thread_id",
            expected_value=self.thread.thread_id,
        )
        return self


class RuntimeStepResult(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    status: StageStatus
    trace_context: TraceContext
    artifact_refs: list[NonEmptyRef] = Field(default_factory=list)
    domain_event_refs: list[NonEmptyRef] = Field(default_factory=list)
    log_summary_refs: list[NonEmptyRef] = Field(default_factory=list)
    audit_refs: list[NonEmptyRef] = Field(default_factory=list)
    checkpoint_ref: CheckpointRef | None = None

    @model_validator(mode="after")
    def validate_identity_consistency(self) -> Self:
        _require_optional_equal(
            field_name="trace_context.run_id",
            value=self.trace_context.run_id,
            expected_field_name="run_id",
            expected_value=self.run_id,
        )
        _require_optional_equal(
            field_name="trace_context.stage_run_id",
            value=self.trace_context.stage_run_id,
            expected_field_name="stage_run_id",
            expected_value=self.stage_run_id,
        )
        if self.checkpoint_ref is not None:
            _require_equal(
                field_name="checkpoint_ref.run_id",
                value=self.checkpoint_ref.run_id,
                expected_field_name="run_id",
                expected_value=self.run_id,
            )
            _require_optional_equal(
                field_name="checkpoint_ref.stage_run_id",
                value=self.checkpoint_ref.stage_run_id,
                expected_field_name="stage_run_id",
                expected_value=self.stage_run_id,
            )
            _require_optional_equal(
                field_name="checkpoint_ref.stage_type",
                value=self.checkpoint_ref.stage_type,
                expected_field_name="stage_type",
                expected_value=self.stage_type,
            )
        return self


class RuntimeInterrupt(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    interrupt_ref: GraphInterruptRef
    payload_ref: str = Field(min_length=1)
    trace_context: TraceContext
    artifact_refs: list[NonEmptyRef] = Field(default_factory=list)
    domain_event_refs: list[NonEmptyRef] = Field(default_factory=list)
    log_summary_refs: list[NonEmptyRef] = Field(default_factory=list)
    audit_refs: list[NonEmptyRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity_consistency(self) -> Self:
        _require_equal(
            field_name="interrupt_ref.run_id",
            value=self.interrupt_ref.run_id,
            expected_field_name="run_id",
            expected_value=self.run_id,
        )
        _require_equal(
            field_name="interrupt_ref.stage_run_id",
            value=self.interrupt_ref.stage_run_id,
            expected_field_name="stage_run_id",
            expected_value=self.stage_run_id,
        )
        _require_equal(
            field_name="interrupt_ref.stage_type",
            value=self.interrupt_ref.stage_type,
            expected_field_name="stage_type",
            expected_value=self.stage_type,
        )
        _require_equal(
            field_name="interrupt_ref.payload_ref",
            value=self.interrupt_ref.payload_ref,
            expected_field_name="payload_ref",
            expected_value=self.payload_ref,
        )
        _require_optional_equal(
            field_name="trace_context.run_id",
            value=self.trace_context.run_id,
            expected_field_name="run_id",
            expected_value=self.run_id,
        )
        _require_optional_equal(
            field_name="trace_context.stage_run_id",
            value=self.trace_context.stage_run_id,
            expected_field_name="stage_run_id",
            expected_value=self.stage_run_id,
        )
        return self


class RuntimeTerminalResult(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    status: GraphThreadStatus
    thread: GraphThreadRef
    trace_context: TraceContext
    result_ref: str | None = Field(default=None, min_length=1)
    artifact_refs: list[NonEmptyRef] = Field(default_factory=list)
    domain_event_refs: list[NonEmptyRef] = Field(default_factory=list)
    log_summary_refs: list[NonEmptyRef] = Field(default_factory=list)
    audit_refs: list[NonEmptyRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity_consistency(self) -> Self:
        if self.status not in _TERMINAL_THREAD_STATUSES:
            terminal_values = ", ".join(status.value for status in _TERMINAL_THREAD_STATUSES)
            raise ValueError(f"status must be terminal: {terminal_values}")
        _require_equal(
            field_name="thread.status",
            value=self.thread.status,
            expected_field_name="status",
            expected_value=self.status,
        )
        _require_equal(
            field_name="thread.run_id",
            value=self.thread.run_id,
            expected_field_name="run_id",
            expected_value=self.run_id,
        )
        _require_optional_equal(
            field_name="trace_context.run_id",
            value=self.trace_context.run_id,
            expected_field_name="run_id",
            expected_value=self.run_id,
        )
        return self


RuntimeEngineResult: TypeAlias = (
    RuntimeStepResult | RuntimeInterrupt | RuntimeTerminalResult
)


class RuntimeEngine(Protocol):
    def start(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult: ...

    def run_next(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult: ...

    def resume(
        self,
        *,
        context: RuntimeExecutionContext,
        interrupt: RuntimeInterrupt,
        resume_payload: RuntimeResumePayload,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeEngineResult: ...

    def terminate(
        self,
        *,
        context: RuntimeExecutionContext,
        runtime_port: RuntimeCommandPort,
        checkpoint_port: CheckpointPort,
    ) -> RuntimeTerminalResult: ...


__all__ = [
    "RuntimeEngine",
    "RuntimeEngineResult",
    "RuntimeExecutionContext",
    "RuntimeInterrupt",
    "RuntimeStepResult",
    "RuntimeTerminalResult",
]
