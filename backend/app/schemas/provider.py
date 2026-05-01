from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from backend.app.schemas import common


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonEmptyString = Annotated[str, Field(min_length=1)]


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
    supported_model_ids: list[NonEmptyString] = Field(min_length=1)
    runtime_capabilities: list[ModelRuntimeCapabilities] = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_model_contract(self) -> "ProviderRead":
        if self.default_model_id not in self.supported_model_ids:
            raise ValueError("default_model_id must be in supported_model_ids")

        capability_model_ids = {
            capability.model_id for capability in self.runtime_capabilities
        }
        missing_model_ids = set(self.supported_model_ids) - capability_model_ids
        if missing_model_ids:
            raise ValueError(
                "runtime_capabilities must cover supported_model_ids: "
                f"{', '.join(sorted(missing_model_ids))}"
            )
        return self


__all__ = [
    "ModelRuntimeCapabilities",
    "ProviderRead",
]
