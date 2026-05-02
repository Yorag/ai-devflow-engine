from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectRead(_StrictBaseModel):
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    root_path: str = Field(min_length=1)
    default_delivery_channel_id: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ProjectCreateRequest(_StrictBaseModel):
    root_path: str = Field(min_length=1)


class ProjectRemoveResult(_StrictBaseModel):
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
    "ProjectCreateRequest",
    "ProjectRead",
    "ProjectRemoveResult",
]
