from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    ValidationError,
    field_validator,
)

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.domain.enums import ProviderProtocolType, ProviderSource, StageType
from backend.app.schemas.runtime_settings import SnapshotModelRuntimeCapabilities


PROVIDER_SNAPSHOT_SCHEMA_VERSION = "provider-snapshot-v1"
MODEL_BINDING_SNAPSHOT_SCHEMA_VERSION = "model-binding-snapshot-v1"
INTERNAL_MODEL_BINDING_TYPES = (
    "context_compression",
    "structured_output_repair",
    "validation_pass",
)


class FrozenSnapshotModelRuntimeCapabilities(SnapshotModelRuntimeCapabilities):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _FrozenDict(dict[str, object]):
    def _readonly(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("snapshot mappings are immutable")

    __setitem__ = _readonly
    __delitem__ = _readonly
    __ior__ = _readonly
    clear = _readonly
    pop = _readonly
    popitem = _readonly
    setdefault = _readonly
    update = _readonly


def _freeze_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _FrozenDict(
            {
                str(key): _freeze_json_value(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json_value(item) for item in value)
    return value


class ProviderSnapshotBuilderError(ValueError):
    def __init__(self, error_code: ErrorCode, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class ModelBindingSnapshotBuilderError(ValueError):
    def __init__(self, error_code: ErrorCode, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class ProviderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: StrictStr = Field(min_length=1, max_length=80)
    run_id: StrictStr = Field(min_length=1)
    provider_id: StrictStr = Field(min_length=1)
    display_name: StrictStr = Field(min_length=1)
    provider_source: ProviderSource
    protocol_type: ProviderProtocolType
    base_url: StrictStr = Field(min_length=1)
    api_key_ref: StrictStr | None = Field(default=None, min_length=1)
    model_id: StrictStr = Field(min_length=1)
    is_default_model: StrictBool = True
    capabilities: FrozenSnapshotModelRuntimeCapabilities
    source_config_version: StrictStr = Field(min_length=1)
    schema_version: Literal["provider-snapshot-v1"] = (
        PROVIDER_SNAPSHOT_SCHEMA_VERSION
    )
    created_at: datetime

    @field_validator("capabilities", mode="before")
    @classmethod
    def _validate_capabilities_input(cls, value: object) -> object:
        if isinstance(value, SnapshotModelRuntimeCapabilities):
            return value.model_dump(mode="python")
        return value


class InternalModelBindingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_type: Literal[
        "context_compression",
        "structured_output_repair",
        "validation_pass",
    ]
    provider_id: StrictStr = Field(min_length=1)
    model_id: StrictStr = Field(min_length=1)
    model_parameters: dict[str, object] = Field(default_factory=dict)

    @field_validator("model_parameters", mode="after")
    @classmethod
    def _freeze_model_parameters(
        cls,
        value: dict[str, object],
    ) -> dict[str, object]:
        frozen = _freeze_json_value(value)
        if not isinstance(frozen, dict):
            raise TypeError("model_parameters must be a mapping")
        return frozen


class ModelBindingSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: StrictStr = Field(min_length=1, max_length=80)
    run_id: StrictStr = Field(min_length=1)
    binding_id: StrictStr = Field(min_length=1)
    binding_type: Literal[
        "agent_role",
        "context_compression",
        "structured_output_repair",
        "validation_pass",
    ]
    stage_type: StageType | None = None
    role_id: StrictStr | None = Field(default=None, min_length=1)
    provider_snapshot_id: StrictStr = Field(min_length=1, max_length=80)
    provider_id: StrictStr = Field(min_length=1)
    model_id: StrictStr = Field(min_length=1)
    capabilities: FrozenSnapshotModelRuntimeCapabilities
    model_parameters: dict[str, object] = Field(default_factory=dict)
    source_config_version: StrictStr = Field(min_length=1)
    schema_version: Literal["model-binding-snapshot-v1"] = (
        MODEL_BINDING_SNAPSHOT_SCHEMA_VERSION
    )
    created_at: datetime

    @field_validator("capabilities", mode="before")
    @classmethod
    def _validate_capabilities_input(cls, value: object) -> object:
        if isinstance(value, SnapshotModelRuntimeCapabilities):
            return value.model_dump(mode="python")
        return value

    @field_validator("model_parameters", mode="after")
    @classmethod
    def _freeze_model_parameters(
        cls,
        value: dict[str, object],
    ) -> dict[str, object]:
        frozen = _freeze_json_value(value)
        if not isinstance(frozen, dict):
            raise TypeError("model_parameters must be a mapping")
        return frozen


class _ProviderSnapshotIndex:
    def __init__(
        self,
        *,
        defaults_by_provider: dict[str, ProviderSnapshot],
        by_provider_and_model: dict[tuple[str, str], ProviderSnapshot],
    ) -> None:
        self.defaults_by_provider = defaults_by_provider
        self.by_provider_and_model = by_provider_and_model


class ProviderSnapshotBuilder:
    @classmethod
    def build_for_run(
        cls,
        providers: Iterable[Any],
        *,
        run_id: str,
        required_provider_ids: Iterable[str],
        created_at: datetime,
        credential_env_prefixes: Iterable[str] | None = None,
        required_model_ids_by_provider: Mapping[str, Iterable[str]] | None = None,
    ) -> tuple[ProviderSnapshot, ...]:
        prefixes = tuple(
            credential_env_prefixes
            if credential_env_prefixes is not None
            else EnvironmentSettings().credential_env_prefixes
        )
        required_ids = tuple(sorted(set(required_provider_ids)))
        requested_model_ids = {
            provider_id: tuple(dict.fromkeys(model_ids))
            for provider_id, model_ids in (
                required_model_ids_by_provider or {}
            ).items()
        }
        providers_by_id = {
            cls._required_string(provider, "provider_id"): provider
            for provider in providers
        }
        missing_ids = [
            provider_id
            for provider_id in required_ids
            if provider_id not in providers_by_id
        ]
        if missing_ids:
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Required Provider configuration is unavailable: "
                f"{', '.join(missing_ids)}.",
            )

        snapshots: list[ProviderSnapshot] = []
        for provider_id in required_ids:
            provider = providers_by_id[provider_id]
            default_model_id = cls._required_string(provider, "default_model_id")
            model_ids = tuple(
                dict.fromkeys(
                    (
                        default_model_id,
                        *requested_model_ids.get(provider_id, ()),
                    )
                )
            )
            snapshots.extend(
                cls._build_provider_snapshot(
                    provider,
                    model_id=model_id,
                    run_id=run_id,
                    created_at=created_at,
                    credential_env_prefixes=prefixes,
                )
                for model_id in model_ids
            )
        return tuple(snapshots)

    @classmethod
    def _build_provider_snapshot(
        cls,
        provider: Any,
        *,
        model_id: str,
        run_id: str,
        created_at: datetime,
        credential_env_prefixes: tuple[str, ...],
    ) -> ProviderSnapshot:
        provider_id = cls._required_string(provider, "provider_id")
        display_name = cls._required_string(provider, "display_name")
        base_url = cls._required_string(provider, "base_url")
        api_key_ref = cls._optional_string(provider, "api_key_ref")
        if not cls._is_safe_api_key_ref(api_key_ref, credential_env_prefixes):
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_CREDENTIAL_ENV_NOT_ALLOWED,
                f"Provider {provider_id} api_key_ref must use an allowed env "
                "credential reference.",
            )

        capabilities = cls._capabilities_for_model(provider, model_id)
        try:
            return ProviderSnapshot(
                snapshot_id=_snapshot_id(
                    "provider-snapshot",
                    run_id,
                    f"{provider_id}:{model_id}",
                ),
                run_id=run_id,
                provider_id=provider_id,
                display_name=display_name,
                provider_source=ProviderSource(cls._required_attr(provider, "provider_source")),
                protocol_type=ProviderProtocolType(
                    cls._required_attr(provider, "protocol_type")
                ),
                base_url=base_url,
                api_key_ref=api_key_ref,
                model_id=model_id,
                is_default_model=(
                    model_id == cls._required_string(provider, "default_model_id")
                ),
                capabilities=capabilities,
                source_config_version=_utc_isoformat(
                    cls._required_datetime(provider, "updated_at")
                ),
                created_at=created_at,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                f"Provider {provider_id} snapshot configuration is invalid.",
            ) from exc

    @classmethod
    def _capabilities_for_model(
        cls,
        provider: Any,
        model_id: str,
    ) -> FrozenSnapshotModelRuntimeCapabilities:
        capabilities = cls._required_attr(provider, "runtime_capabilities")
        if not isinstance(capabilities, list):
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Provider runtime_capabilities are required for snapshot creation.",
            )
        matching = [
            capability
            for capability in capabilities
            if isinstance(capability, Mapping)
            and capability.get("model_id") == model_id
        ]
        if len(matching) != 1:
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Provider runtime_capabilities must include capabilities for "
                f"model {model_id}.",
            )
        cls._validate_capability_mapping(matching[0], model_id)
        try:
            return FrozenSnapshotModelRuntimeCapabilities(**dict(matching[0]))
        except ValidationError as exc:
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Provider runtime_capabilities for the selected model are invalid.",
            ) from exc

    @staticmethod
    def _validate_capability_mapping(
        capability: Mapping[str, Any],
        model_id: str,
    ) -> None:
        required_keys = {
            "model_id",
            "context_window_tokens",
            "max_output_tokens",
            "supports_tool_calling",
            "supports_structured_output",
            "supports_native_reasoning",
        }
        missing_keys = sorted(required_keys - set(capability))
        if missing_keys:
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Provider runtime_capabilities for model "
                f"{model_id} are missing required fields: "
                f"{', '.join(missing_keys)}.",
            )
        if not isinstance(capability["model_id"], str) or not capability["model_id"]:
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                f"Provider runtime_capabilities for model {model_id} are invalid.",
            )
        for field_name in ("context_window_tokens", "max_output_tokens"):
            value = capability[field_name]
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ProviderSnapshotBuilderError(
                    ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                    "Provider runtime_capabilities for model "
                    f"{model_id} have invalid {field_name}.",
                )
        for field_name in (
            "supports_tool_calling",
            "supports_structured_output",
            "supports_native_reasoning",
        ):
            if not isinstance(capability[field_name], bool):
                raise ProviderSnapshotBuilderError(
                    ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                    "Provider runtime_capabilities for model "
                    f"{model_id} have invalid {field_name}.",
                )

    @classmethod
    def _required_string(cls, source: Any, field_name: str) -> str:
        value = cls._required_attr(source, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                f"Provider {field_name} must be a non-empty string.",
            )
        return value

    @classmethod
    def _optional_string(cls, source: Any, field_name: str) -> str | None:
        value = cls._required_attr(source, field_name)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                f"Provider {field_name} must be a non-empty string when set.",
            )
        return value

    @staticmethod
    def _required_datetime(source: Any, field_name: str) -> datetime:
        value = ProviderSnapshotBuilder._required_attr(source, field_name)
        if not isinstance(value, datetime):
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                f"Provider {field_name} must be a datetime.",
            )
        return value

    @staticmethod
    def _required_attr(source: Any, field_name: str) -> Any:
        try:
            return getattr(source, field_name)
        except AttributeError as exc:
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                f"Provider {field_name} is required.",
            ) from exc

    @staticmethod
    def _is_safe_api_key_ref(
        value: str | None,
        credential_env_prefixes: tuple[str, ...],
    ) -> bool:
        if value is None:
            return True
        env_name = value.removeprefix("env:")
        env_name_has_valid_chars = all(
            char == "_" or char.isascii() and char.isalnum()
            for char in env_name
        )
        return (
            value.startswith("env:")
            and bool(env_name)
            and env_name_has_valid_chars
            and any(env_name.startswith(prefix) for prefix in credential_env_prefixes)
        )


class ModelBindingSnapshotBuilder:
    @classmethod
    def build_for_run(
        cls,
        template_snapshot: Any,
        *,
        provider_snapshots: Iterable[ProviderSnapshot],
        internal_bindings: Iterable[InternalModelBindingSelection],
        run_id: str,
        created_at: datetime,
    ) -> tuple[ModelBindingSnapshot, ...]:
        if template_snapshot.run_id != run_id:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Template snapshot run_id must match the PipelineRun run_id.",
            )

        snapshot_index = cls._provider_snapshot_index(
            provider_snapshots,
            run_id=run_id,
        )
        internal_by_type = cls._internal_bindings_by_type(internal_bindings)

        agent_role_bindings = tuple(
            cls._build_agent_role_binding(
                binding,
                provider_snapshot=cls._require_default_provider_snapshot(
                    snapshot_index.defaults_by_provider,
                    binding.provider_id,
                ),
                run_id=run_id,
                created_at=created_at,
                source_config_version=_utc_isoformat(
                    template_snapshot.source_template_updated_at
                ),
            )
            for binding in tuple(template_snapshot.stage_role_bindings)
        )
        internal_snapshots = tuple(
            cls._build_internal_binding(
                internal_by_type[binding_type],
                provider_snapshot=cls._require_provider_model_snapshot(
                    snapshot_index.by_provider_and_model,
                    internal_by_type[binding_type].provider_id,
                    internal_by_type[binding_type].model_id,
                ),
                run_id=run_id,
                created_at=created_at,
            )
            for binding_type in INTERNAL_MODEL_BINDING_TYPES
        )
        return (*agent_role_bindings, *internal_snapshots)

    @classmethod
    def _provider_snapshot_index(
        cls,
        provider_snapshots: Iterable[ProviderSnapshot],
        *,
        run_id: str,
    ) -> _ProviderSnapshotIndex:
        defaults_by_provider: dict[str, ProviderSnapshot] = {}
        by_provider_and_model: dict[tuple[str, str], ProviderSnapshot] = {}
        for snapshot in provider_snapshots:
            if snapshot.run_id != run_id:
                raise ModelBindingSnapshotBuilderError(
                    ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                    "Provider snapshot run_id must match the PipelineRun run_id.",
                )
            if snapshot.capabilities.model_id != snapshot.model_id:
                raise ModelBindingSnapshotBuilderError(
                    ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                    "Provider snapshot capabilities.model_id must match model_id.",
                )
            if snapshot.is_default_model:
                if snapshot.provider_id in defaults_by_provider:
                    raise ModelBindingSnapshotBuilderError(
                        ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                        "Provider snapshots must include exactly one default model "
                        f"for provider {snapshot.provider_id}.",
                    )
                defaults_by_provider[snapshot.provider_id] = snapshot
            provider_model_key = (snapshot.provider_id, snapshot.model_id)
            if provider_model_key in by_provider_and_model:
                raise ModelBindingSnapshotBuilderError(
                    ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                    "Provider snapshots must not duplicate provider/model "
                    f"{snapshot.provider_id}/{snapshot.model_id}.",
                )
            by_provider_and_model[provider_model_key] = snapshot
        if not defaults_by_provider:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Provider snapshots are required for model binding snapshots.",
            )
        missing_defaults = sorted(
            provider_id
            for provider_id, _model_id in by_provider_and_model
            if provider_id not in defaults_by_provider
        )
        if missing_defaults:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Provider snapshots must include a default model for providers: "
                f"{', '.join(dict.fromkeys(missing_defaults))}.",
            )
        return _ProviderSnapshotIndex(
            defaults_by_provider=defaults_by_provider,
            by_provider_and_model=by_provider_and_model,
        )

    @classmethod
    def _internal_bindings_by_type(
        cls,
        internal_bindings: Iterable[InternalModelBindingSelection],
    ) -> dict[str, InternalModelBindingSelection]:
        selections = tuple(internal_bindings)
        by_type = {selection.binding_type: selection for selection in selections}
        duplicate_types = sorted(
            {
                selection.binding_type
                for selection in selections
                if sum(1 for item in selections if item.binding_type == selection.binding_type)
                > 1
            }
        )
        if duplicate_types:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Duplicate internal model binding selections: "
                f"{', '.join(duplicate_types)}.",
            )
        missing_types = [
            binding_type
            for binding_type in INTERNAL_MODEL_BINDING_TYPES
            if binding_type not in by_type
        ]
        if missing_types:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Missing internal model binding selections: "
                f"{', '.join(missing_types)}.",
            )
        return by_type

    @staticmethod
    def _require_default_provider_snapshot(
        defaults_by_provider: dict[str, ProviderSnapshot],
        provider_id: str,
    ) -> ProviderSnapshot:
        snapshot = defaults_by_provider.get(provider_id)
        if snapshot is None:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                f"Provider snapshot is unavailable for provider {provider_id}.",
            )
        return snapshot

    @staticmethod
    def _require_provider_model_snapshot(
        by_provider_and_model: dict[tuple[str, str], ProviderSnapshot],
        provider_id: str,
        model_id: str,
    ) -> ProviderSnapshot:
        snapshot = by_provider_and_model.get((provider_id, model_id))
        if snapshot is None:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Provider snapshot is unavailable for provider/model "
                f"{provider_id}/{model_id}.",
            )
        return snapshot

    @classmethod
    def _build_agent_role_binding(
        cls,
        binding: Any,
        *,
        provider_snapshot: ProviderSnapshot,
        run_id: str,
        created_at: datetime,
        source_config_version: str,
    ) -> ModelBindingSnapshot:
        return cls._build_snapshot(
            run_id=run_id,
            binding_id=f"agent_role:{binding.stage_type.value}:{binding.role_id}",
            binding_type="agent_role",
            stage_type=binding.stage_type,
            role_id=binding.role_id,
            provider_snapshot=provider_snapshot,
            model_id=provider_snapshot.model_id,
            model_parameters={},
            source_config_version=source_config_version,
            created_at=created_at,
        )

    @classmethod
    def _build_internal_binding(
        cls,
        selection: InternalModelBindingSelection,
        *,
        provider_snapshot: ProviderSnapshot,
        run_id: str,
        created_at: datetime,
    ) -> ModelBindingSnapshot:
        return cls._build_snapshot(
            run_id=run_id,
            binding_id=selection.binding_type,
            binding_type=selection.binding_type,
            stage_type=None,
            role_id=None,
            provider_snapshot=provider_snapshot,
            model_id=selection.model_id,
            model_parameters=dict(selection.model_parameters),
            source_config_version="internal-model-binding-selection-v1",
            created_at=created_at,
        )

    @staticmethod
    def _build_snapshot(
        *,
        run_id: str,
        binding_id: str,
        binding_type: str,
        stage_type: StageType | None,
        role_id: str | None,
        provider_snapshot: ProviderSnapshot,
        model_id: str,
        model_parameters: dict[str, object],
        source_config_version: str,
        created_at: datetime,
    ) -> ModelBindingSnapshot:
        if provider_snapshot.run_id != run_id:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Provider snapshot run_id must match the PipelineRun run_id.",
            )
        if provider_snapshot.model_id != model_id:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Model binding model_id must match the referenced ProviderSnapshot.",
            )
        if provider_snapshot.capabilities.model_id != model_id:
            raise ModelBindingSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Model binding capabilities.model_id must match model_id.",
            )
        return ModelBindingSnapshot(
            snapshot_id=_snapshot_id("model-binding-snapshot", run_id, binding_id),
            run_id=run_id,
            binding_id=binding_id,
            binding_type=binding_type,
            stage_type=stage_type,
            role_id=role_id,
            provider_snapshot_id=provider_snapshot.snapshot_id,
            provider_id=provider_snapshot.provider_id,
            model_id=model_id,
            capabilities=provider_snapshot.capabilities.model_dump(mode="python"),
            model_parameters=model_parameters,
            source_config_version=source_config_version,
            created_at=created_at,
        )


def _snapshot_id(prefix: str, run_id: str, suffix: str) -> str:
    candidate = f"{prefix}-{run_id}-{suffix}"
    if len(candidate) <= 80:
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


__all__ = [
    "INTERNAL_MODEL_BINDING_TYPES",
    "FrozenSnapshotModelRuntimeCapabilities",
    "MODEL_BINDING_SNAPSHOT_SCHEMA_VERSION",
    "PROVIDER_SNAPSHOT_SCHEMA_VERSION",
    "InternalModelBindingSelection",
    "ModelBindingSnapshot",
    "ModelBindingSnapshotBuilder",
    "ModelBindingSnapshotBuilderError",
    "ProviderSnapshot",
    "ProviderSnapshotBuilder",
    "ProviderSnapshotBuilderError",
]
