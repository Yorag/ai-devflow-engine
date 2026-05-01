from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas import common


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectDeliveryChannelDetailProjection(_StrictBaseModel):
    project_id: str = Field(min_length=1)
    delivery_channel_id: str = Field(min_length=1)
    delivery_mode: common.DeliveryMode
    scm_provider_type: common.ScmProviderType | None = None
    repository_identifier: str | None = None
    default_branch: str | None = None
    code_review_request_type: common.CodeReviewRequestType | None = None
    credential_ref: str | None = None
    credential_status: common.CredentialStatus
    readiness_status: common.DeliveryReadinessStatus
    readiness_message: str | None = None
    last_validated_at: datetime | None = None
    updated_at: datetime


__all__ = [
    "ProjectDeliveryChannelDetailProjection",
]
