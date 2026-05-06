from __future__ import annotations

from typing import Protocol

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.enums import StageType
from backend.app.domain.trace_context import TraceContext


class RuntimeDispatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    graph_thread_id: str = Field(min_length=1)
    trace_context: TraceContext


class RuntimeExecutionDispatcher(Protocol):
    def dispatch_started_run(self, command: RuntimeDispatchCommand) -> None: ...


class NoopRuntimeExecutionDispatcher:
    def dispatch_started_run(self, command: RuntimeDispatchCommand) -> None:
        del command


def runtime_dispatcher_from_app_state(request: Request) -> RuntimeExecutionDispatcher:
    dispatcher = getattr(request.app.state, "runtime_execution_dispatcher", None)
    if dispatcher is None:
        return NoopRuntimeExecutionDispatcher()
    return dispatcher


__all__ = [
    "NoopRuntimeExecutionDispatcher",
    "RuntimeDispatchCommand",
    "RuntimeExecutionDispatcher",
    "runtime_dispatcher_from_app_state",
]
