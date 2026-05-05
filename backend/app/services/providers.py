from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.models.control import ProviderModel
from backend.app.domain.enums import ProviderProtocolType, ProviderSource
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.provider import ModelRuntimeCapabilities, ProviderWriteRequest


DEFAULT_CONTEXT_WINDOW_TOKENS = 128000
DEFAULT_MAX_OUTPUT_TOKENS = 4096
BUILTIN_PROVIDER_IDS = ("provider-volcengine", "provider-deepseek")
SEED_ACTOR_ID = "control-plane-seed"
API_ACTOR_ID = "api-user"

PROVIDER_NOT_FOUND_MESSAGE = "Provider was not found."
CUSTOM_DISPLAY_NAME_REQUIRED_MESSAGE = "Custom Provider display_name is required."
CUSTOM_PROTOCOL_MISMATCH_MESSAGE = (
    "Custom Provider protocol_type must be openai_completions_compatible."
)
BUILTIN_IDENTITY_CHANGE_MESSAGE = (
    "Built-in Provider identity fields cannot be modified."
)
INVALID_MODEL_BINDING_MESSAGE = (
    "Provider default_model_id must be in supported_model_ids."
)
MISSING_MODEL_CAPABILITY_MESSAGE = (
    "Provider runtime_capabilities must cover supported_model_ids."
)
EXTRA_MODEL_CAPABILITY_MESSAGE = (
    "Provider runtime_capabilities must only reference supported_model_ids."
)
DUPLICATE_MODEL_CAPABILITY_MESSAGE = (
    "Provider runtime_capabilities must not contain duplicate model ids."
)
INVALID_CREDENTIAL_REFERENCE_MESSAGE = (
    "Provider api_key_ref must use an env: credential reference."
)
BLOCKED_API_KEY_REF = "[blocked:api_key_ref]"

BUILTIN_PROVIDER_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "provider_id": "provider-volcengine",
        "display_name": "火山引擎",
        "provider_source": ProviderSource.BUILTIN,
        "protocol_type": ProviderProtocolType.VOLCENGINE_NATIVE,
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key_ref": "env:VOLCENGINE_API_KEY",
        "default_model_id": "doubao-seed-1-6",
        "supported_model_ids": ["doubao-seed-1-6"],
        "runtime_capabilities": [
            {
                "model_id": "doubao-seed-1-6",
                "context_window_tokens": 128000,
                "max_output_tokens": 8192,
                "supports_tool_calling": True,
                "supports_structured_output": True,
                "supports_native_reasoning": False,
            }
        ],
    },
    {
        "provider_id": "provider-deepseek",
        "display_name": "DeepSeek",
        "provider_source": ProviderSource.BUILTIN,
        "protocol_type": ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        "base_url": "https://api.deepseek.com",
        "api_key_ref": "env:DEEPSEEK_API_KEY",
        "default_model_id": "deepseek-chat",
        "supported_model_ids": ["deepseek-chat", "deepseek-reasoner"],
        "runtime_capabilities": [
            {
                "model_id": "deepseek-chat",
                "context_window_tokens": 128000,
                "max_output_tokens": 8192,
                "supports_tool_calling": True,
                "supports_structured_output": False,
                "supports_native_reasoning": False,
            },
            {
                "model_id": "deepseek-reasoner",
                "context_window_tokens": 128000,
                "max_output_tokens": 8192,
                "supports_tool_calling": False,
                "supports_structured_output": False,
                "supports_native_reasoning": True,
            },
        ],
    },
)


class ProviderServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ProviderService:
    def __init__(
        self,
        session: Session,
        *,
        audit_service: Any,
        now: Callable[[], datetime] | None = None,
        credential_env_prefixes: Iterable[str] | None = None,
    ) -> None:
        self._session = session
        self._audit_service = audit_service
        self._now = now or (lambda: datetime.now(UTC))
        self._credential_env_prefixes = tuple(
            credential_env_prefixes
            if credential_env_prefixes is not None
            else EnvironmentSettings().credential_env_prefixes
        )

    @staticmethod
    def apply_model_capability_defaults(
        capabilities: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized = []
        for capability in capabilities:
            context_window_tokens = capability.get("context_window_tokens")
            if context_window_tokens is None:
                context_window_tokens = DEFAULT_CONTEXT_WINDOW_TOKENS
            max_output_tokens = capability.get("max_output_tokens")
            if max_output_tokens is None:
                max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS
            model = ModelRuntimeCapabilities(
                model_id=capability["model_id"],
                context_window_tokens=context_window_tokens,
                max_output_tokens=max_output_tokens,
                supports_tool_calling=capability.get("supports_tool_calling", False),
                supports_structured_output=capability.get(
                    "supports_structured_output",
                    False,
                ),
                supports_native_reasoning=capability.get(
                    "supports_native_reasoning",
                    False,
                ),
            )
            normalized.append(model.model_dump(mode="python"))
        return normalized

    def seed_builtin_providers(
        self,
        *,
        trace_context: TraceContext,
    ) -> list[ProviderModel]:
        existing_ids = {
            provider_id
            for (provider_id,) in self._session.query(ProviderModel.provider_id)
            .filter(ProviderModel.provider_id.in_(BUILTIN_PROVIDER_IDS))
            .all()
        }
        missing_seeds = [
            seed
            for seed in BUILTIN_PROVIDER_SEEDS
            if seed["provider_id"] not in existing_ids
        ]
        if not missing_seeds:
            return self._ordered_builtin_providers()

        timestamp = self._now()
        created: list[ProviderModel] = []
        for seed in missing_seeds:
            provider = ProviderModel(
                provider_id=seed["provider_id"],
                display_name=seed["display_name"],
                provider_source=seed["provider_source"],
                protocol_type=seed["protocol_type"],
                base_url=seed["base_url"],
                api_key_ref=seed["api_key_ref"],
                default_model_id=seed["default_model_id"],
                supported_model_ids=list(seed["supported_model_ids"]),
                is_configured=False,
                is_enabled=True,
                runtime_capabilities=self.apply_model_capability_defaults(
                    seed["runtime_capabilities"]
                ),
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._session.add(provider)
            self._session.flush()
            created.append(provider)

        if created:
            try:
                self._record_seed_audit(
                    providers=created,
                    trace_context=trace_context,
                )
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise

        return self._ordered_builtin_providers()

    def list_providers(self, *, trace_context: TraceContext) -> list[ProviderModel]:
        builtin_providers = self.seed_builtin_providers(trace_context=trace_context)
        custom_providers = (
            self._session.query(ProviderModel)
            .filter(ProviderModel.is_configured.is_(True))
            .order_by(ProviderModel.created_at.asc(), ProviderModel.provider_id.asc())
            .all()
        )
        return custom_providers

    def get_provider(
        self,
        provider_id: str,
        *,
        trace_context: TraceContext,
    ) -> ProviderModel | None:
        self.seed_builtin_providers(trace_context=trace_context)
        return self._session.get(ProviderModel, provider_id)

    def api_key_ref_for_projection(self, value: str | None) -> str | None:
        return self._audit_api_key_ref(value)

    def create_custom_provider(
        self,
        body: ProviderWriteRequest,
        *,
        trace_context: TraceContext,
    ) -> ProviderModel:
        try:
            payload = self._validated_write_payload(
                body,
                existing_provider=None,
                is_builtin=False,
                rejected_action="provider.create_custom.rejected",
                target_id="provider-custom-new",
                trace_context=trace_context,
            )
        except Exception:
            self._session.rollback()
            raise

        timestamp = self._now()
        provider = ProviderModel(
            provider_id=self._new_custom_provider_id(),
            display_name=payload["display_name"],
            provider_source=ProviderSource.CUSTOM,
            protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
            base_url=payload["base_url"],
            api_key_ref=payload["api_key_ref"],
            default_model_id=payload["default_model_id"],
            supported_model_ids=payload["supported_model_ids"],
            is_configured=True,
            is_enabled=payload["is_enabled"],
            runtime_capabilities=payload["runtime_capabilities"],
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._session.add(provider)
        self._session.flush()
        try:
            self._record_success(
                action="provider.create_custom",
                provider=provider,
                old_api_key_ref=None,
                trace_context=trace_context,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return provider

    def patch_provider(
        self,
        provider_id: str,
        body: ProviderWriteRequest,
        *,
        trace_context: TraceContext,
    ) -> ProviderModel:
        provider = self.get_provider(provider_id, trace_context=trace_context)
        if provider is None:
            self._record_rejected(
                action="provider.patch.rejected",
                target_id=provider_id,
                reason=PROVIDER_NOT_FOUND_MESSAGE,
                metadata={"provider_id": provider_id},
                trace_context=trace_context,
            )
            raise ProviderServiceError(
                ErrorCode.NOT_FOUND,
                PROVIDER_NOT_FOUND_MESSAGE,
                404,
            )
        if provider.provider_source is ProviderSource.BUILTIN:
            return self.patch_builtin_provider_runtime_config(
                provider_id,
                body,
                trace_context=trace_context,
            )
        return self.patch_custom_provider(provider_id, body, trace_context=trace_context)

    def patch_custom_provider(
        self,
        provider_id: str,
        body: ProviderWriteRequest,
        *,
        trace_context: TraceContext,
    ) -> ProviderModel:
        provider = self.get_provider(provider_id, trace_context=trace_context)
        if provider is None or provider.provider_source is not ProviderSource.CUSTOM:
            self._record_rejected(
                action="provider.patch_custom.rejected",
                target_id=provider_id,
                reason=PROVIDER_NOT_FOUND_MESSAGE,
                metadata={"provider_id": provider_id},
                trace_context=trace_context,
            )
            raise ProviderServiceError(
                ErrorCode.NOT_FOUND,
                PROVIDER_NOT_FOUND_MESSAGE,
                404,
            )

        try:
            payload = self._validated_write_payload(
                body,
                existing_provider=provider,
                is_builtin=False,
                rejected_action="provider.patch_custom.rejected",
                target_id=provider_id,
                trace_context=trace_context,
            )
        except Exception:
            self._session.rollback()
            raise

        old_api_key_ref = provider.api_key_ref
        self._apply_runtime_payload(provider, payload)
        provider.display_name = payload["display_name"]
        provider.is_configured = True
        provider.updated_at = self._now()
        self._session.add(provider)
        self._session.flush()
        try:
            self._record_success(
                action="provider.patch_custom",
                provider=provider,
                old_api_key_ref=old_api_key_ref,
                trace_context=trace_context,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return provider

    def patch_builtin_provider_runtime_config(
        self,
        provider_id: str,
        body: ProviderWriteRequest,
        *,
        trace_context: TraceContext,
    ) -> ProviderModel:
        provider = self.get_provider(provider_id, trace_context=trace_context)
        if provider is None or provider.provider_source is not ProviderSource.BUILTIN:
            self._record_rejected(
                action="provider.patch_builtin_runtime_config.rejected",
                target_id=provider_id,
                reason=PROVIDER_NOT_FOUND_MESSAGE,
                metadata={"provider_id": provider_id},
                trace_context=trace_context,
            )
            raise ProviderServiceError(
                ErrorCode.NOT_FOUND,
                PROVIDER_NOT_FOUND_MESSAGE,
                404,
            )

        try:
            payload = self._validated_write_payload(
                body,
                existing_provider=provider,
                is_builtin=True,
                rejected_action="provider.patch_builtin_runtime_config.rejected",
                target_id=provider_id,
                trace_context=trace_context,
            )
        except Exception:
            self._session.rollback()
            raise

        old_api_key_ref = provider.api_key_ref
        self._apply_runtime_payload(provider, payload)
        provider.is_configured = True
        provider.updated_at = self._now()
        self._session.add(provider)
        self._session.flush()
        try:
            self._record_success(
                action="provider.patch_builtin_runtime_config",
                provider=provider,
                old_api_key_ref=old_api_key_ref,
                trace_context=trace_context,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return provider

    def _ordered_builtin_providers(self) -> list[ProviderModel]:
        providers = (
            self._session.query(ProviderModel)
            .filter(ProviderModel.provider_id.in_(BUILTIN_PROVIDER_IDS))
            .all()
        )
        by_id = {provider.provider_id: provider for provider in providers}
        return [
            by_id[provider_id]
            for provider_id in BUILTIN_PROVIDER_IDS
            if provider_id in by_id
        ]

    def _record_seed_audit(
        self,
        *,
        providers: list[ProviderModel],
        trace_context: TraceContext,
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.SYSTEM,
            actor_id=SEED_ACTOR_ID,
            action="provider.seed_builtin",
            target_type="provider",
            target_id="builtin-provider-seed",
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata={
                "provider_ids": [
                    provider.provider_id
                    for provider in providers
                ],
                "display_names": [
                    provider.display_name
                    for provider in providers
                ],
                "api_key_refs": [
                    provider.api_key_ref
                    for provider in providers
                ],
                "default_model_ids": [
                    provider.default_model_id
                    for provider in providers
                ],
                "supported_model_counts": {
                    provider.provider_id: len(provider.supported_model_ids)
                    for provider in providers
                },
            },
                trace_context=trace_context,
        )

    def _new_custom_provider_id(self) -> str:
        while True:
            provider_id = f"provider-custom-{uuid4().hex[:12]}"
            if self._session.get(ProviderModel, provider_id) is None:
                return provider_id

    def _validated_write_payload(
        self,
        body: ProviderWriteRequest,
        *,
        existing_provider: ProviderModel | None,
        is_builtin: bool,
        rejected_action: str,
        target_id: str,
        trace_context: TraceContext,
    ) -> dict[str, Any]:
        if is_builtin:
            self._validate_builtin_identity(
                body,
                existing_provider=existing_provider,
                rejected_action=rejected_action,
                target_id=target_id,
                trace_context=trace_context,
            )
        else:
            self._validate_custom_identity(
                body,
                existing_provider=existing_provider,
                rejected_action=rejected_action,
                target_id=target_id,
                trace_context=trace_context,
            )

        self._validate_api_key_ref(
            body.api_key_ref,
            rejected_action=rejected_action,
            target_id=target_id,
            trace_context=trace_context,
        )
        if body.default_model_id not in body.supported_model_ids:
            self._raise_rejected_config(
                action=rejected_action,
                target_id=target_id,
                message=INVALID_MODEL_BINDING_MESSAGE,
                metadata={
                    "default_model_id": body.default_model_id,
                    "supported_model_ids": list(body.supported_model_ids),
                },
                trace_context=trace_context,
            )

        capabilities = [
            capability.model_dump(mode="python", exclude_none=True)
            for capability in body.runtime_capabilities
        ]
        capability_model_id_list = [
            capability["model_id"] for capability in capabilities
        ]
        capability_model_ids = set(capability_model_id_list)
        duplicate_model_ids = sorted(
            {
                model_id
                for model_id in capability_model_id_list
                if capability_model_id_list.count(model_id) > 1
            }
        )
        if duplicate_model_ids:
            self._raise_rejected_config(
                action=rejected_action,
                target_id=target_id,
                message=DUPLICATE_MODEL_CAPABILITY_MESSAGE,
                metadata={
                    "duplicate_model_ids": duplicate_model_ids,
                },
                trace_context=trace_context,
            )

        missing_model_ids = set(body.supported_model_ids) - capability_model_ids
        if missing_model_ids:
            self._raise_rejected_config(
                action=rejected_action,
                target_id=target_id,
                message=MISSING_MODEL_CAPABILITY_MESSAGE,
                metadata={
                    "supported_model_ids": list(body.supported_model_ids),
                    "missing_model_ids": sorted(missing_model_ids),
                },
                trace_context=trace_context,
            )

        extra_model_ids = capability_model_ids - set(body.supported_model_ids)
        if extra_model_ids:
            self._raise_rejected_config(
                action=rejected_action,
                target_id=target_id,
                message=EXTRA_MODEL_CAPABILITY_MESSAGE,
                metadata={
                    "supported_model_ids": list(body.supported_model_ids),
                    "extra_model_ids": sorted(extra_model_ids),
                },
                trace_context=trace_context,
            )

        display_name = (
            body.display_name
            if body.display_name is not None
            else existing_provider.display_name if existing_provider is not None else None
        )
        return {
            "display_name": display_name,
            "base_url": body.base_url,
            "api_key_ref": body.api_key_ref,
            "default_model_id": body.default_model_id,
            "supported_model_ids": list(body.supported_model_ids),
            "is_enabled": body.is_enabled,
            "runtime_capabilities": self.apply_model_capability_defaults(capabilities),
        }

    def _validate_custom_identity(
        self,
        body: ProviderWriteRequest,
        *,
        existing_provider: ProviderModel | None,
        rejected_action: str,
        target_id: str,
        trace_context: TraceContext,
    ) -> None:
        if existing_provider is None and body.display_name is None:
            self._raise_rejected_config(
                action=rejected_action,
                target_id=target_id,
                message=CUSTOM_DISPLAY_NAME_REQUIRED_MESSAGE,
                metadata={"display_name_status": "missing"},
                trace_context=trace_context,
            )
        if (
            body.protocol_type is not None
            and body.protocol_type
            is not ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
        ):
            self._raise_rejected_config(
                action=rejected_action,
                target_id=target_id,
                message=CUSTOM_PROTOCOL_MISMATCH_MESSAGE,
                metadata={
                    "submitted_protocol_type": body.protocol_type.value,
                    "required_protocol_type": (
                        ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE.value
                    ),
                },
                trace_context=trace_context,
            )

    def _validate_builtin_identity(
        self,
        body: ProviderWriteRequest,
        *,
        existing_provider: ProviderModel | None,
        rejected_action: str,
        target_id: str,
        trace_context: TraceContext,
    ) -> None:
        if existing_provider is None:
            return
        display_changed = (
            body.display_name is not None
            and body.display_name != existing_provider.display_name
        )
        protocol_changed = (
            body.protocol_type is not None
            and body.protocol_type is not existing_provider.protocol_type
        )
        if display_changed or protocol_changed:
            self._record_rejected(
                action=rejected_action,
                target_id=target_id,
                reason=BUILTIN_IDENTITY_CHANGE_MESSAGE,
                metadata={
                    "provider_id": existing_provider.provider_id,
                    "provider_source": existing_provider.provider_source.value,
                    "display_name_changed": display_changed,
                    "protocol_type_changed": protocol_changed,
                },
                trace_context=trace_context,
            )
            raise ProviderServiceError(
                ErrorCode.VALIDATION_ERROR,
                BUILTIN_IDENTITY_CHANGE_MESSAGE,
                409,
            )

    def _validate_api_key_ref(
        self,
        value: str | None,
        *,
        rejected_action: str,
        target_id: str,
        trace_context: TraceContext,
    ) -> None:
        if value is None:
            return
        if self._is_safe_api_key_ref(value):
            return
        self._raise_rejected_config(
            action=rejected_action,
            target_id=target_id,
            message=INVALID_CREDENTIAL_REFERENCE_MESSAGE,
            metadata={"api_key_ref_status": "invalid_reference"},
            trace_context=trace_context,
        )

    def _raise_rejected_config(
        self,
        *,
        action: str,
        target_id: str,
        message: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        self._record_rejected(
            action=action,
            target_id=target_id,
            reason=message,
            metadata={
                **metadata,
                "error_code": ErrorCode.CONFIG_INVALID_VALUE.value,
            },
            trace_context=trace_context,
        )
        raise ProviderServiceError(
            ErrorCode.CONFIG_INVALID_VALUE,
            message,
            422,
        )

    def _apply_runtime_payload(
        self,
        provider: ProviderModel,
        payload: dict[str, Any],
    ) -> None:
        provider.base_url = payload["base_url"]
        provider.api_key_ref = payload["api_key_ref"]
        provider.default_model_id = payload["default_model_id"]
        provider.supported_model_ids = payload["supported_model_ids"]
        provider.is_enabled = payload["is_enabled"]
        provider.runtime_capabilities = payload["runtime_capabilities"]

    def _record_success(
        self,
        *,
        action: str,
        provider: ProviderModel,
        old_api_key_ref: str | None,
        trace_context: TraceContext,
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action=action,
            target_type="provider",
            target_id=provider.provider_id,
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata=self._provider_audit_metadata(
                provider,
                old_api_key_ref=old_api_key_ref,
            ),
            trace_context=trace_context,
        )

    def _record_rejected(
        self,
        *,
        action: str,
        target_id: str,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action=action,
            target_type="provider",
            target_id=target_id,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
        )

    def _provider_audit_metadata(
        self,
        provider: ProviderModel,
        *,
        old_api_key_ref: str | None,
    ) -> dict[str, Any]:
        capability_model_ids = [
            item.get("model_id") for item in provider.runtime_capabilities
        ]
        capability_flags = [
            {
                "model_id": item.get("model_id"),
                "supports_tool_calling": item.get("supports_tool_calling", False),
                "supports_structured_output": item.get(
                    "supports_structured_output",
                    False,
                ),
                "supports_native_reasoning": item.get(
                    "supports_native_reasoning",
                    False,
                ),
            }
            for item in provider.runtime_capabilities
        ]
        return {
            "provider_id": provider.provider_id,
            "provider_source": provider.provider_source.value,
            "protocol_type": provider.protocol_type.value,
            "api_key_ref": self._audit_api_key_ref(provider.api_key_ref),
            "ref_transition": {
                "changed": old_api_key_ref != provider.api_key_ref,
                "before_ref": self._audit_api_key_ref(old_api_key_ref),
                "after_ref": self._audit_api_key_ref(provider.api_key_ref),
            },
            "default_model_id": provider.default_model_id,
            "supported_model_ids": list(provider.supported_model_ids),
            "is_enabled": provider.is_enabled,
            "runtime_capability_model_ids": capability_model_ids,
            "runtime_capability_flags": capability_flags,
            "runtime_capability_count": len(provider.runtime_capabilities),
        }

    def _is_safe_api_key_ref(self, value: str) -> bool:
        env_name = value.removeprefix("env:")
        env_name_has_valid_chars = all(
            char == "_" or char.isascii() and char.isalnum() for char in env_name
        )
        env_name_has_allowed_prefix = any(
            env_name.startswith(prefix) for prefix in self._credential_env_prefixes
        )
        return (
            value.startswith("env:")
            and bool(env_name)
            and env_name_has_valid_chars
            and env_name_has_allowed_prefix
        )

    def _audit_api_key_ref(self, value: str | None) -> str | None:
        if value is None:
            return None
        if self._is_safe_api_key_ref(value):
            return value
        return BLOCKED_API_KEY_REF


__all__ = [
    "API_ACTOR_ID",
    "BLOCKED_API_KEY_REF",
    "BUILTIN_PROVIDER_IDS",
    "BUILTIN_PROVIDER_SEEDS",
    "DEFAULT_CONTEXT_WINDOW_TOKENS",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "ProviderService",
    "ProviderServiceError",
]
