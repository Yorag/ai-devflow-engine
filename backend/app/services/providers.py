from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models.control import ProviderModel
from backend.app.domain.enums import ProviderProtocolType, ProviderSource
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.provider import ModelRuntimeCapabilities


DEFAULT_CONTEXT_WINDOW_TOKENS = 128000
DEFAULT_MAX_OUTPUT_TOKENS = 4096
BUILTIN_PROVIDER_IDS = ("provider-volcengine", "provider-deepseek")
SEED_ACTOR_ID = "control-plane-seed"

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


class ProviderService:
    def __init__(
        self,
        session: Session,
        *,
        audit_service: Any,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._audit_service = audit_service
        self._now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def apply_model_capability_defaults(
        capabilities: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized = []
        for capability in capabilities:
            model = ModelRuntimeCapabilities(
                model_id=capability["model_id"],
                context_window_tokens=capability.get(
                    "context_window_tokens",
                    DEFAULT_CONTEXT_WINDOW_TOKENS,
                ),
                max_output_tokens=capability.get(
                    "max_output_tokens",
                    DEFAULT_MAX_OUTPUT_TOKENS,
                ),
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
            .filter(ProviderModel.provider_id.notin_(BUILTIN_PROVIDER_IDS))
            .order_by(ProviderModel.created_at.asc(), ProviderModel.provider_id.asc())
            .all()
        )
        return [*builtin_providers, *custom_providers]

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


__all__ = [
    "BUILTIN_PROVIDER_IDS",
    "BUILTIN_PROVIDER_SEEDS",
    "DEFAULT_CONTEXT_WINDOW_TOKENS",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "ProviderService",
]
