from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from backend.app.providers.base import ProviderConfig, ProviderResolutionEvent
from backend.app.schemas import common
from backend.app.schemas.runtime_settings import (
    ModelBindingSnapshotRead,
    ProviderSnapshotRead,
)


class ProviderRegistryError(RuntimeError):
    error_code = "provider_registry_error"

    def __init__(
        self,
        message: str,
        *,
        provider_snapshot_id: str | None = None,
        model_binding_snapshot_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_snapshot_id = provider_snapshot_id
        self.model_binding_snapshot_id = model_binding_snapshot_id


class ModelBindingSnapshotNotFoundError(ProviderRegistryError):
    error_code = "model_binding_snapshot_not_found"


class ProviderSnapshotNotFoundError(ProviderRegistryError):
    error_code = "provider_snapshot_not_found"


class ProviderSnapshotMismatchError(ProviderRegistryError):
    error_code = "provider_snapshot_mismatch"


class ProviderCapabilityError(ProviderRegistryError):
    error_code = "provider_capability_unsupported"


EventRecorder = Callable[[ProviderResolutionEvent], None]


class ProviderRegistry:
    def __init__(
        self,
        *,
        provider_snapshots: Iterable[ProviderSnapshotRead],
        model_binding_snapshots: Iterable[ModelBindingSnapshotRead],
        event_recorder: EventRecorder | None = None,
    ) -> None:
        self._providers_by_snapshot_id = {
            snapshot.snapshot_id: snapshot for snapshot in provider_snapshots
        }
        self._bindings_by_snapshot_id = {
            snapshot.snapshot_id: snapshot for snapshot in model_binding_snapshots
        }
        self._event_recorder = event_recorder

    def resolve(
        self,
        model_binding_snapshot_id: str,
        *,
        requires_tool_calling: bool = False,
    ) -> ProviderConfig:
        binding = self._bindings_by_snapshot_id.get(model_binding_snapshot_id)
        if binding is None:
            error = ModelBindingSnapshotNotFoundError(
                "Model binding snapshot was not found.",
                model_binding_snapshot_id=model_binding_snapshot_id,
            )
            self._record_failure(error, run_id="")
            raise error
        return self.resolve_from_model_binding_snapshot(
            binding,
            requires_tool_calling=requires_tool_calling,
        )

    def resolve_from_model_binding_snapshot(
        self,
        model_binding_snapshot: ModelBindingSnapshotRead,
        *,
        requires_tool_calling: bool = False,
    ) -> ProviderConfig:
        provider = self._providers_by_snapshot_id.get(
            model_binding_snapshot.provider_snapshot_id
        )
        if provider is None:
            error = ProviderSnapshotNotFoundError(
                "Provider snapshot was not found.",
                provider_snapshot_id=model_binding_snapshot.provider_snapshot_id,
                model_binding_snapshot_id=model_binding_snapshot.snapshot_id,
            )
            self._record_failure(error, run_id=model_binding_snapshot.run_id)
            raise error

        self._validate_binding_matches_provider(provider, model_binding_snapshot)
        if (
            requires_tool_calling
            and not model_binding_snapshot.capabilities.supports_tool_calling
        ):
            error = ProviderCapabilityError(
                "Model binding snapshot does not support supports_tool_calling.",
                provider_snapshot_id=provider.snapshot_id,
                model_binding_snapshot_id=model_binding_snapshot.snapshot_id,
            )
            self._record_failure(error, run_id=model_binding_snapshot.run_id)
            raise error

        if provider.api_key_ref is None:
            self._record(
                ProviderResolutionEvent(
                    event_type="provider_credential_unavailable",
                    run_id=model_binding_snapshot.run_id,
                    provider_snapshot_id=provider.snapshot_id,
                    model_binding_snapshot_id=model_binding_snapshot.snapshot_id,
                    provider_id=provider.provider_id,
                    model_id=model_binding_snapshot.model_id,
                    credential_ref_status="unbound",
                )
            )

        config = ProviderConfig(
            run_id=model_binding_snapshot.run_id,
            provider_snapshot_id=provider.snapshot_id,
            model_binding_snapshot_id=model_binding_snapshot.snapshot_id,
            binding_id=model_binding_snapshot.binding_id,
            binding_type=model_binding_snapshot.binding_type,
            stage_type=model_binding_snapshot.stage_type,
            role_id=model_binding_snapshot.role_id,
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            provider_source=provider.provider_source,
            protocol_type=provider.protocol_type,
            base_url=provider.base_url,
            api_key_ref=provider.api_key_ref,
            model_id=model_binding_snapshot.model_id,
            model_parameters=dict(model_binding_snapshot.model_parameters),
            context_window_tokens=(
                model_binding_snapshot.capabilities.context_window_tokens
            ),
            max_output_tokens=model_binding_snapshot.capabilities.max_output_tokens,
            supports_tool_calling=(
                model_binding_snapshot.capabilities.supports_tool_calling
            ),
            supports_structured_output=(
                model_binding_snapshot.capabilities.supports_structured_output
            ),
            supports_native_reasoning=(
                model_binding_snapshot.capabilities.supports_native_reasoning
            ),
            provider_source_config_version=provider.source_config_version,
            model_binding_source_config_version=(
                model_binding_snapshot.source_config_version
            ),
            provider_schema_version=provider.schema_version,
            model_binding_schema_version=model_binding_snapshot.schema_version,
        )
        self._record_success(config)
        return config

    @classmethod
    def resolve_from_template_snapshot(
        cls,
        template_snapshot: object,
        *,
        stage_type: common.StageType | str | None = None,
        role_id: str | None = None,
        binding_id: str | None = None,
        binding_type: str = "agent_role",
        requires_tool_calling: bool = False,
        event_recorder: EventRecorder | None = None,
    ) -> ProviderConfig:
        provider_snapshots = cls._snapshot_items(template_snapshot, "provider_snapshots")
        model_binding_snapshots = cls._snapshot_items(
            template_snapshot,
            "model_binding_snapshots",
        )
        selected = cls._select_binding(
            model_binding_snapshots,
            stage_type=stage_type,
            role_id=role_id,
            binding_id=binding_id,
            binding_type=binding_type,
        )
        return cls(
            provider_snapshots=provider_snapshots,
            model_binding_snapshots=model_binding_snapshots,
            event_recorder=event_recorder,
        ).resolve_from_model_binding_snapshot(
            selected,
            requires_tool_calling=requires_tool_calling,
        )

    @staticmethod
    def _snapshot_items(source: object, field_name: str) -> list[Any]:
        if isinstance(source, Mapping):
            value = source[field_name]
        else:
            value = getattr(source, field_name)
        return list(value)

    @staticmethod
    def _select_binding(
        bindings: list[ModelBindingSnapshotRead],
        *,
        stage_type: common.StageType | str | None,
        role_id: str | None,
        binding_id: str | None,
        binding_type: str,
    ) -> ModelBindingSnapshotRead:
        normalized_stage_type = (
            common.StageType(stage_type) if isinstance(stage_type, str) else stage_type
        )
        matches = [
            binding
            for binding in bindings
            if binding.binding_type == binding_type
            and (binding_id is None or binding.binding_id == binding_id)
            and (role_id is None or binding.role_id == role_id)
            and (
                normalized_stage_type is None
                or binding.stage_type is normalized_stage_type
            )
        ]
        if len(matches) != 1:
            raise ModelBindingSnapshotNotFoundError(
                "Exactly one model binding snapshot must match the template selector."
            )
        return matches[0]

    def _validate_binding_matches_provider(
        self,
        provider: ProviderSnapshotRead,
        binding: ModelBindingSnapshotRead,
    ) -> None:
        if provider.run_id != binding.run_id:
            raise ProviderSnapshotMismatchError(
                "Provider snapshot and model binding snapshot belong to different runs.",
                provider_snapshot_id=provider.snapshot_id,
                model_binding_snapshot_id=binding.snapshot_id,
            )
        if provider.provider_id != binding.provider_id:
            raise ProviderSnapshotMismatchError(
                "Provider snapshot id does not match model binding provider id.",
                provider_snapshot_id=provider.snapshot_id,
                model_binding_snapshot_id=binding.snapshot_id,
            )
        if provider.model_id != binding.model_id:
            raise ProviderSnapshotMismatchError(
                "Provider snapshot model does not match model binding model.",
                provider_snapshot_id=provider.snapshot_id,
                model_binding_snapshot_id=binding.snapshot_id,
            )
        if binding.capabilities.model_id != binding.model_id:
            raise ProviderSnapshotMismatchError(
                "Model binding capability model does not match bound model.",
                provider_snapshot_id=provider.snapshot_id,
                model_binding_snapshot_id=binding.snapshot_id,
            )

    def _record_success(self, config: ProviderConfig) -> None:
        self._record(
            ProviderResolutionEvent(
                event_type="provider_resolution_succeeded",
                run_id=config.run_id,
                provider_snapshot_id=config.provider_snapshot_id,
                model_binding_snapshot_id=config.model_binding_snapshot_id,
                provider_id=config.provider_id,
                model_id=config.model_id,
                credential_ref_status="bound" if config.api_key_ref else "unbound",
            )
        )

    def _record_failure(self, error: ProviderRegistryError, *, run_id: str) -> None:
        self._record(
            ProviderResolutionEvent(
                event_type="provider_resolution_failed",
                run_id=run_id,
                provider_snapshot_id=error.provider_snapshot_id,
                model_binding_snapshot_id=error.model_binding_snapshot_id,
                error_code=error.error_code,
                message=str(error),
            )
        )

    def _record(self, event: ProviderResolutionEvent) -> None:
        if self._event_recorder is not None:
            self._event_recorder(event)


__all__ = [
    "ModelBindingSnapshotNotFoundError",
    "ProviderCapabilityError",
    "ProviderRegistry",
    "ProviderRegistryError",
    "ProviderSnapshotMismatchError",
    "ProviderSnapshotNotFoundError",
]
