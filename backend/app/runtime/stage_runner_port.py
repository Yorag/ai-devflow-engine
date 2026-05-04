from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.runtime.base import RuntimeExecutionContext


NonEmptyRef = Annotated[str, Field(min_length=1)]


class StageNodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    status: StageStatus
    artifact_refs: list[NonEmptyRef] = Field(default_factory=list)
    domain_event_refs: list[NonEmptyRef] = Field(default_factory=list)
    log_summary_refs: list[NonEmptyRef] = Field(default_factory=list)
    audit_refs: list[NonEmptyRef] = Field(default_factory=list)
    route_key: str | None = Field(default=None, min_length=1)


@dataclass(frozen=True)
class StageNodeInvocation:
    run_id: str
    stage_run_id: str
    stage_type: StageType
    graph_node_key: str
    stage_contract_ref: str
    runtime_context: RuntimeExecutionContext
    trace_context: TraceContext


class StageNodeRunnerPort(Protocol):
    def run_stage(self, invocation: StageNodeInvocation) -> StageNodeResult: ...


__all__ = [
    "StageNodeInvocation",
    "StageNodeResult",
    "StageNodeRunnerPort",
]
