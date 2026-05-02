from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StrictBool

from backend.app.schemas import common


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonEmptyString = Annotated[str, Field(min_length=1)]


class ConfigurationPackageScope(_StrictBaseModel):
    scope_type: Literal["project"]
    project_id: str = Field(min_length=1)


class ConfigurationPackageModelRuntimeCapabilities(_StrictBaseModel):
    model_id: str = Field(min_length=1)
    context_window_tokens: PositiveInt = 128000
    max_output_tokens: PositiveInt | None = None
    supports_tool_calling: StrictBool = False
    supports_structured_output: StrictBool = False
    supports_native_reasoning: StrictBool = False


class ConfigurationPackageProvider(_StrictBaseModel):
    provider_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider_source: common.ProviderSource
    protocol_type: common.ProviderProtocolType
    base_url: str = Field(min_length=1)
    api_key_ref: str | None = None
    default_model_id: str = Field(min_length=1)
    supported_model_ids: list[NonEmptyString] = Field(min_length=1)
    runtime_capabilities: list[ConfigurationPackageModelRuntimeCapabilities] = Field(
        min_length=1
    )


class ConfigurationPackageDeliveryChannel(_StrictBaseModel):
    delivery_mode: common.DeliveryMode
    scm_provider_type: common.ScmProviderType | None = None
    repository_identifier: str | None = None
    default_branch: str | None = None
    code_review_request_type: common.CodeReviewRequestType | None = None
    credential_ref: str | None = None


class ConfigurationPackageTemplateSlotConfig(_StrictBaseModel):
    stage_type: common.StageType
    role_id: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)


class ConfigurationPackageTemplateConfig(_StrictBaseModel):
    template_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    template_source: common.TemplateSource
    stage_role_bindings: list[ConfigurationPackageTemplateSlotConfig] = Field(
        min_length=1
    )
    auto_regression_enabled: bool
    max_auto_regression_retries: int = Field(ge=0)


class ConfigurationPackageImportRequest(_StrictBaseModel):
    package_schema_version: str = Field(min_length=1)
    scope: ConfigurationPackageScope
    providers: list[ConfigurationPackageProvider] = Field(default_factory=list)
    delivery_channels: list[ConfigurationPackageDeliveryChannel] = Field(
        default_factory=list
    )
    pipeline_templates: list[ConfigurationPackageTemplateConfig] = Field(
        default_factory=list
    )


class ConfigurationPackageRead(ConfigurationPackageImportRequest):
    package_id: str = Field(min_length=1)
    exported_at: datetime


class ConfigurationPackageExport(ConfigurationPackageImportRequest):
    export_id: str = Field(min_length=1)
    exported_at: datetime


class ConfigurationPackageChangedObject(_StrictBaseModel):
    object_type: Literal["provider", "delivery_channel", "pipeline_template"]
    object_id: str = Field(min_length=1)
    action: Literal["created", "updated", "unchanged"]
    config_version: str = Field(min_length=1)


class ConfigurationPackageFieldError(_StrictBaseModel):
    field: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ConfigurationPackageImportResult(_StrictBaseModel):
    package_id: str = Field(min_length=1)
    package_schema_version: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    changed_objects: list[ConfigurationPackageChangedObject] = Field(default_factory=list)
    field_errors: list[ConfigurationPackageFieldError] = Field(default_factory=list)


__all__ = [
    "ConfigurationPackageChangedObject",
    "ConfigurationPackageDeliveryChannel",
    "ConfigurationPackageExport",
    "ConfigurationPackageFieldError",
    "ConfigurationPackageImportRequest",
    "ConfigurationPackageImportResult",
    "ConfigurationPackageModelRuntimeCapabilities",
    "ConfigurationPackageProvider",
    "ConfigurationPackageRead",
    "ConfigurationPackageScope",
    "ConfigurationPackageTemplateConfig",
    "ConfigurationPackageTemplateSlotConfig",
]
