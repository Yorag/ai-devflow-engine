from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas import common
from backend.app.schemas.delivery_channel import ProjectDeliveryChannelDetailProjection
from backend.app.schemas.feed import TopLevelFeedEntry
from backend.app.schemas.project import ProjectRead
from backend.app.schemas.run import ComposerStateProjection, RunSummaryProjection
from backend.app.schemas.session import SessionRead


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionWorkspaceProjection(_StrictBaseModel):
    session: SessionRead
    project: ProjectRead
    delivery_channel: ProjectDeliveryChannelDetailProjection | None = None
    runs: list[RunSummaryProjection] = Field(default_factory=list)
    narrative_feed: list[TopLevelFeedEntry] = Field(default_factory=list)
    current_run_id: str | None = None
    current_stage_type: common.StageType | None = None
    composer_state: ComposerStateProjection

    @model_validator(mode="after")
    def validate_active_run_contract(self) -> "SessionWorkspaceProjection":
        active_runs = [run for run in self.runs if run.is_active]
        if len(active_runs) > 1:
            raise ValueError("SessionWorkspaceProjection allows at most one active run")
        if active_runs and self.current_run_id != active_runs[0].run_id:
            raise ValueError("current_run_id must match the active run")
        if (
            self.composer_state.bound_run_id
            and self.composer_state.bound_run_id != self.current_run_id
        ):
            raise ValueError("composer_state.bound_run_id must match current_run_id")
        return self


__all__ = [
    "SessionWorkspaceProjection",
]
