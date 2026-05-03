from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas import common
from backend.app.schemas.feed import TopLevelFeedEntry
from backend.app.schemas.runtime_settings import (
    ModelBindingSnapshotRead,
    ProviderCallPolicySnapshotRead,
    ProviderSnapshotRead,
    RuntimeLimitSnapshotRead,
)
from backend.app.schemas.session import SessionRead


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunSummaryProjection(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    attempt_index: int = Field(ge=1)
    status: common.RunStatus
    trigger_source: common.RunTriggerSource
    started_at: datetime
    ended_at: datetime | None = None
    current_stage_type: common.StageType | None = None
    is_active: bool


class RunPauseRequest(_StrictBaseModel):
    pass


class RunResumeRequest(_StrictBaseModel):
    pass


class RunCommandResponse(_StrictBaseModel):
    session: SessionRead
    run: RunSummaryProjection


class RunConfigurationSnapshotRead(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    template_snapshot_ref: str = Field(min_length=1)
    graph_definition_ref: str = Field(min_length=1)
    runtime_limit_snapshot: RuntimeLimitSnapshotRead
    provider_call_policy_snapshot: ProviderCallPolicySnapshotRead
    provider_snapshots: list[ProviderSnapshotRead] = Field(min_length=1)
    model_binding_snapshots: list[ModelBindingSnapshotRead] = Field(min_length=1)
    created_at: datetime


class ComposerStateProjection(_StrictBaseModel):
    mode: Literal[
        "draft",
        "running",
        "waiting_clarification",
        "waiting_approval",
        "waiting_tool_confirmation",
        "paused",
        "readonly",
    ]
    is_input_enabled: bool
    primary_action: Literal["send", "pause", "resume", "disabled"]
    secondary_actions: list[Literal["pause", "terminate"]] = Field(default_factory=list)
    bound_run_id: str | None = None


class ImplementationPlanTaskRead(_StrictBaseModel):
    task_id: str = Field(min_length=1)
    order_index: int = Field(ge=1)
    title: str = Field(min_length=1)
    depends_on_task_ids: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    target_modules: list[str] = Field(default_factory=list)
    acceptance_refs: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(min_length=1)
    risk_handling: str | None = None


class SolutionImplementationPlanRead(_StrictBaseModel):
    plan_id: str = Field(min_length=1)
    source_stage_run_id: str = Field(min_length=1)
    tasks: list[ImplementationPlanTaskRead] = Field(min_length=1)
    downstream_refs: list[str] = Field(min_length=1)
    created_at: datetime

    @field_validator("tasks")
    @classmethod
    def require_unique_task_ids(
        cls,
        value: list[ImplementationPlanTaskRead],
    ) -> list[ImplementationPlanTaskRead]:
        task_ids = [task.task_id for task in value]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("implementation_plan tasks must have unique task_id values")
        return value


class ImplementationPlanReference(_StrictBaseModel):
    artifact_id: str = Field(min_length=1)
    implementation_plan_id: str = Field(min_length=1)
    task_ids: list[str] = Field(min_length=1)


class SolutionDesignArtifactRead(_StrictBaseModel):
    artifact_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    technical_plan: str = Field(min_length=1)
    implementation_plan: SolutionImplementationPlanRead
    impacted_files: list[str] = Field(default_factory=list)
    api_design: str | None = None
    data_flow_design: str | None = None
    risks: list[str] = Field(default_factory=list)
    test_strategy: str = Field(min_length=1)
    validation_report: str = Field(min_length=1)
    requirement_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class RunTimelineProjection(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    attempt_index: int = Field(ge=1)
    trigger_source: common.RunTriggerSource
    status: common.RunStatus
    started_at: datetime
    ended_at: datetime | None = None
    current_stage_type: common.StageType | None = None
    entries: list[TopLevelFeedEntry] = Field(default_factory=list)


__all__ = [
    "ComposerStateProjection",
    "ImplementationPlanReference",
    "RunCommandResponse",
    "ImplementationPlanTaskRead",
    "RunConfigurationSnapshotRead",
    "RunPauseRequest",
    "RunResumeRequest",
    "RunSummaryProjection",
    "RunTimelineProjection",
    "SolutionDesignArtifactRead",
    "SolutionImplementationPlanRead",
]
