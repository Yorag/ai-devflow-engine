from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from backend.app.schemas import common


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelRuntimeCapabilities(_StrictBaseModel):
    model_id: str = Field(min_length=1)
    context_window_tokens: PositiveInt = 128000
    max_output_tokens: PositiveInt
    supports_tool_calling: bool = False
    supports_structured_output: bool = False
    supports_native_reasoning: bool = False


class ProviderRead(_StrictBaseModel):
    provider_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider_source: common.ProviderSource
    protocol_type: common.ProviderProtocolType
    base_url: str = Field(min_length=1)
    api_key_ref: str | None = None
    default_model_id: str = Field(min_length=1)
    supported_model_ids: list[str] = Field(min_length=1)
    runtime_capabilities: list[ModelRuntimeCapabilities] = Field(min_length=1)
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ModelRuntimeCapabilities",
    "ProviderRead",
]
