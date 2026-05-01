from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas import common


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionRead(_StrictBaseModel):
    session_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: common.SessionStatus
    selected_template_id: str = Field(min_length=1)
    current_run_id: str | None = None
    latest_stage_type: common.StageType | None = None
    created_at: datetime
    updated_at: datetime


class SessionRenameRequest(_StrictBaseModel):
    display_name: str = Field(min_length=1)


class SessionDeleteResult(_StrictBaseModel):
    session_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    visibility_removed: bool
    blocked_by_active_run: bool
    blocking_run_id: str | None = None
    error_code: str | None = None
    message: str = Field(min_length=1)
    deletes_local_project_folder: Literal[False] = False
    deletes_target_repository: Literal[False] = False
    deletes_remote_repository: Literal[False] = False
    deletes_remote_branch: Literal[False] = False
    deletes_commits: Literal[False] = False
    deletes_code_review_requests: Literal[False] = False


__all__ = [
    "SessionDeleteResult",
    "SessionRead",
    "SessionRenameRequest",
]
