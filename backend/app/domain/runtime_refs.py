from __future__ import annotations

from typing import Any

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.enums import ContractEnum, StageType
from backend.app.domain.trace_context import TraceContext


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphThreadStatus(ContractEnum):
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_TOOL_CONFIRMATION = "waiting_tool_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class GraphInterruptType(ContractEnum):
    CLARIFICATION_REQUEST = "clarification_request"
    APPROVAL = "approval"
    TOOL_CONFIRMATION = "tool_confirmation"


class GraphInterruptStatus(ContractEnum):
    PENDING = "pending"
    RESUMED = "resumed"
    CANCELLED = "cancelled"


class CheckpointPurpose(ContractEnum):
    RUNNING_SAFE_POINT = "running_safe_point"
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_TOOL_CONFIRMATION = "waiting_tool_confirmation"
    PAUSE = "pause"
    TERMINAL = "terminal"


class RuntimeCommandType(ContractEnum):
    CREATE_INTERRUPT = "create_interrupt"
    RESUME_INTERRUPT = "resume_interrupt"
    RESUME_TOOL_CONFIRMATION = "resume_tool_confirmation"
    PAUSE_THREAD = "pause_thread"
    RESUME_THREAD = "resume_thread"
    TERMINATE_THREAD = "terminate_thread"
    RERUN_TERMINAL_CHECK = "rerun_terminal_check"


class GraphThreadRef(_StrictBaseModel):
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: GraphThreadStatus
    current_stage_run_id: str | None = Field(default=None, min_length=1)
    current_stage_type: StageType | None = None
    checkpoint_id: str | None = Field(default=None, min_length=1)


class CheckpointRef(_StrictBaseModel):
    checkpoint_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str | None = Field(default=None, min_length=1)
    stage_type: StageType | None = None
    purpose: CheckpointPurpose
    workspace_snapshot_ref: str | None = Field(default=None, min_length=1)
    payload_ref: str | None = Field(default=None, min_length=1)


class GraphInterruptRef(_StrictBaseModel):
    interrupt_id: str = Field(min_length=1)
    thread: GraphThreadRef
    interrupt_type: GraphInterruptType
    status: GraphInterruptStatus
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    payload_ref: str = Field(min_length=1)
    clarification_id: str | None = Field(default=None, min_length=1)
    approval_id: str | None = Field(default=None, min_length=1)
    tool_confirmation_id: str | None = Field(default=None, min_length=1)
    tool_action_ref: str | None = Field(default=None, min_length=1)
    checkpoint_ref: CheckpointRef

    @model_validator(mode="after")
    def require_interrupt_specific_refs(self) -> Self:
        if self.interrupt_type is GraphInterruptType.TOOL_CONFIRMATION and (
            not self.tool_confirmation_id or not self.tool_action_ref
        ):
            raise ValueError(
                "tool confirmation interrupt requires tool_confirmation_id "
                "and tool_action_ref"
            )
        if self.interrupt_type is GraphInterruptType.APPROVAL and not self.approval_id:
            raise ValueError("approval interrupt requires approval_id")
        if (
            self.interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST
            and not self.clarification_id
        ):
            raise ValueError("clarification interrupt requires clarification_id")
        return self


class RuntimeResumePayload(_StrictBaseModel):
    resume_id: str = Field(min_length=1)
    payload_ref: str = Field(min_length=1)
    values: dict[str, Any] = Field(default_factory=dict)


class RuntimeCommandResult(_StrictBaseModel):
    command_type: RuntimeCommandType
    thread: GraphThreadRef
    trace_context: TraceContext
    interrupt_ref: GraphInterruptRef | None = None
    checkpoint_ref: CheckpointRef | None = None
    payload_ref: str | None = Field(default=None, min_length=1)


__all__ = [
    "CheckpointPurpose",
    "CheckpointRef",
    "GraphInterruptRef",
    "GraphInterruptStatus",
    "GraphInterruptType",
    "GraphThreadRef",
    "GraphThreadStatus",
    "RuntimeCommandResult",
    "RuntimeCommandType",
    "RuntimeResumePayload",
]
