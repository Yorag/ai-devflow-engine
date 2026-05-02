from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    @model_validator(mode="after")
    def validate_delivery_mode_contract(self) -> "ProjectDeliveryChannelDetailProjection":
        if self.delivery_mode is not common.DeliveryMode.GIT_AUTO_DELIVERY:
            return self

        git_fields = {
            "scm_provider_type": self.scm_provider_type,
            "repository_identifier": self.repository_identifier,
            "default_branch": self.default_branch,
            "code_review_request_type": self.code_review_request_type,
            "credential_ref": self.credential_ref,
        }
        missing_fields = [field for field, value in git_fields.items() if not value]
        if missing_fields:
            raise ValueError(
                "git_auto_delivery requires "
                f"{', '.join(sorted(missing_fields))}"
            )
        if (
            self.readiness_status is common.DeliveryReadinessStatus.READY
            and self.credential_status is not common.CredentialStatus.READY
        ):
            raise ValueError(
                "git_auto_delivery readiness_status=ready requires "
                "credential_status=ready"
            )
        return self


class ProjectDeliveryChannelUpdateRequest(_StrictBaseModel):
    delivery_mode: common.DeliveryMode
    scm_provider_type: common.ScmProviderType | None = None
    repository_identifier: str | None = None
    default_branch: str | None = None
    code_review_request_type: common.CodeReviewRequestType | None = None
    credential_ref: str | None = None


__all__ = [
    "ProjectDeliveryChannelDetailProjection",
    "ProjectDeliveryChannelUpdateRequest",
]
