from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.changes import ContextReferenceKind


JsonObject = dict[str, Any]


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewTargetReference(_StrictBaseModel):
    reference_id: str = Field(min_length=1)
    reference_kind: ContextReferenceKind
    source_ref: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    path: str | None = Field(default=None, min_length=1)
    version_ref: str | None = Field(default=None, min_length=1)
    metadata: JsonObject = Field(default_factory=dict)


class PreviewTarget(_StrictBaseModel):
    preview_target_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    target_type: str = Field(min_length=1)
    reference: PreviewTargetReference
    created_at: datetime
