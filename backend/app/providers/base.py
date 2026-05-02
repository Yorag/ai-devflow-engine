from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from backend.app.schemas import common


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    run_id: str
    provider_snapshot_id: str
    model_binding_snapshot_id: str
    binding_id: str
    binding_type: str
    stage_type: common.StageType | None
    role_id: str | None
    provider_id: str
    display_name: str
    provider_source: common.ProviderSource
    protocol_type: common.ProviderProtocolType
    base_url: str
    api_key_ref: str | None
    model_id: str
    model_parameters: Mapping[str, object] = field(default_factory=dict)
    context_window_tokens: int = 128000
    max_output_tokens: int = 1
    supports_tool_calling: bool = False
    supports_structured_output: bool = False
    supports_native_reasoning: bool = False
    provider_source_config_version: str = ""
    model_binding_source_config_version: str = ""
    provider_schema_version: str = ""
    model_binding_schema_version: str = ""


@dataclass(frozen=True, slots=True)
class ProviderResolutionEvent:
    event_type: str
    run_id: str
    provider_snapshot_id: str | None = None
    model_binding_snapshot_id: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    credential_ref_status: str | None = None
    error_code: str | None = None
    message: str | None = None

    def to_record(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "event_type": self.event_type,
                "run_id": self.run_id,
                "provider_snapshot_id": self.provider_snapshot_id,
                "model_binding_snapshot_id": self.model_binding_snapshot_id,
                "provider_id": self.provider_id,
                "model_id": self.model_id,
                "credential_ref_status": self.credential_ref_status,
                "error_code": self.error_code,
                "message": self.message,
            }.items()
            if value is not None
        }


class ModelProvider(Protocol):
    @property
    def config(self) -> ProviderConfig:
        ...


__all__ = [
    "ModelProvider",
    "ProviderConfig",
    "ProviderResolutionEvent",
]
