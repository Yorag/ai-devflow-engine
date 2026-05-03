from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.app.api.error_codes import ErrorCode
from backend.app.providers.base import ProviderConfig
from backend.app.providers.provider_registry import ProviderRegistry
from backend.app.schemas import common
from backend.app.schemas.runtime_settings import (
    ModelBindingSnapshotRead,
    ProviderSnapshotRead,
    SnapshotModelRuntimeCapabilities,
)


FIXTURE_NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)


def provider_capabilities_fixture(
    *,
    model_id: str = "deepseek-chat",
    context_window_tokens: int = 128000,
    max_output_tokens: int = 8192,
    supports_tool_calling: bool = True,
    supports_structured_output: bool = True,
    supports_native_reasoning: bool = False,
) -> SnapshotModelRuntimeCapabilities:
    return SnapshotModelRuntimeCapabilities(
        model_id=model_id,
        context_window_tokens=context_window_tokens,
        max_output_tokens=max_output_tokens,
        supports_tool_calling=supports_tool_calling,
        supports_structured_output=supports_structured_output,
        supports_native_reasoning=supports_native_reasoning,
    )


def provider_snapshot_fixture(
    *,
    snapshot_id: str = "provider-snapshot-1",
    run_id: str = "run-1",
    provider_id: str = "provider-deepseek",
    display_name: str = "DeepSeek",
    provider_source: common.ProviderSource = common.ProviderSource.BUILTIN,
    protocol_type: common.ProviderProtocolType = (
        common.ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
    ),
    base_url: str = "https://api.deepseek.com",
    api_key_ref: str | None = "env:DEEPSEEK_API_KEY",
    model_id: str = "deepseek-chat",
    capabilities: SnapshotModelRuntimeCapabilities | None = None,
    source_config_version: str = "provider-config-v1",
    schema_version: str = "provider-snapshot-v1",
    created_at: datetime | None = None,
) -> ProviderSnapshotRead:
    return ProviderSnapshotRead(
        snapshot_id=snapshot_id,
        run_id=run_id,
        provider_id=provider_id,
        display_name=display_name,
        provider_source=provider_source,
        protocol_type=protocol_type,
        base_url=base_url,
        api_key_ref=api_key_ref,
        model_id=model_id,
        capabilities=capabilities or provider_capabilities_fixture(model_id=model_id),
        source_config_version=source_config_version,
        schema_version=schema_version,
        created_at=created_at or FIXTURE_NOW,
    )


def model_binding_snapshot_fixture(
    *,
    snapshot_id: str = "model-binding-snapshot-1",
    run_id: str = "run-1",
    binding_id: str = "binding-code-generation",
    binding_type: str = "agent_role",
    stage_type: common.StageType | None = common.StageType.CODE_GENERATION,
    role_id: str | None = "role-code-generator",
    provider_snapshot_id: str = "provider-snapshot-1",
    provider_id: str = "provider-deepseek",
    model_id: str = "deepseek-chat",
    capabilities: SnapshotModelRuntimeCapabilities | None = None,
    model_parameters: dict[str, object] | None = None,
    source_config_version: str = "template-binding-v1",
    schema_version: str = "model-binding-snapshot-v1",
    created_at: datetime | None = None,
) -> ModelBindingSnapshotRead:
    return ModelBindingSnapshotRead(
        snapshot_id=snapshot_id,
        run_id=run_id,
        binding_id=binding_id,
        binding_type=binding_type,
        stage_type=stage_type,
        role_id=role_id,
        provider_snapshot_id=provider_snapshot_id,
        provider_id=provider_id,
        model_id=model_id,
        capabilities=capabilities or provider_capabilities_fixture(model_id=model_id),
        model_parameters=model_parameters or {"temperature": 0.2},
        source_config_version=source_config_version,
        schema_version=schema_version,
        created_at=created_at or FIXTURE_NOW,
    )


@dataclass(slots=True)
class FakeProviderError(RuntimeError):
    failure_kind: str
    message: str
    error_code: ErrorCode | None = None

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)


@dataclass
class FakeChatModel:
    fake_provider: FakeProvider
    scripted_responses: deque[dict[str, Any]] = field(default_factory=deque)

    def enqueue(self, item: Mapping[str, Any]) -> None:
        self.scripted_responses.append(dict(item))

    def enqueue_structured_success(self, payload: Mapping[str, Any]) -> None:
        self.enqueue({"kind": "structured_success", "payload": dict(payload)})

    def enqueue_tool_call_request(
        self,
        tool_name: str,
        input_payload: Mapping[str, Any],
    ) -> None:
        self.enqueue(
            {
                "kind": "tool_call_request",
                "tool_name": tool_name,
                "input_payload": dict(input_payload),
            }
        )

    def enqueue_structured_failure(
        self,
        *,
        error_code: ErrorCode | None,
        message: str,
        failure_kind: str = "structured_failure",
    ) -> None:
        self.enqueue(
            {
                "kind": "structured_failure",
                "error_code": error_code,
                "failure_kind": failure_kind,
                "message": message,
            }
        )

    def enqueue_timeout(self) -> None:
        self.enqueue({"kind": "timeout"})

    def enqueue_rate_limit(self) -> None:
        self.enqueue({"kind": "rate_limit"})

    def enqueue_network_error(self) -> None:
        self.enqueue({"kind": "network_error"})

    def _next(self) -> dict[str, Any]:
        if not self.scripted_responses:
            raise FakeProviderError(
                failure_kind="no_scripted_response",
                message="No scripted provider response is available.",
            )
        return self.scripted_responses.popleft()

    def invoke_structured(
        self,
        prompt: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        del prompt
        response = self._next()
        kind = response["kind"]
        if kind == "structured_success":
            return dict(response["payload"])  # type: ignore[arg-type]
        if kind == "tool_call_request":
            return {
                "decision_type": "request_tool_call",
                "tool_name": response["tool_name"],
                "input_payload": dict(response["input_payload"]),  # type: ignore[arg-type]
            }
        if kind == "structured_failure":
            raise FakeProviderError(
                failure_kind=str(
                    response.get("failure_kind", "structured_failure")
                ),
                message=str(response.get("message", "structured failure")),
                error_code=response.get("error_code"),  # type: ignore[arg-type]
            )
        if kind == "timeout":
            raise FakeProviderError(
                failure_kind="timeout",
                message="provider timed out",
                error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
            )
        if kind == "rate_limit":
            raise FakeProviderError(
                failure_kind="rate_limit",
                message="provider rate limited",
                error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
            )
        if kind == "network_error":
            raise FakeProviderError(
                failure_kind="network_error",
                message="provider network error",
                error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
            )
        raise AssertionError(f"Unsupported scripted response kind: {kind!r}")

    def invoke_failure(
        self,
        prompt: Mapping[str, object] | None = None,
    ) -> FakeProviderError:
        try:
            self.invoke_structured(prompt)
        except FakeProviderError as error:
            return error
        raise AssertionError("Expected FakeChatModel to raise FakeProviderError.")


@dataclass(slots=True)
class FakeProvider:
    config: ProviderConfig
    provider_snapshot: ProviderSnapshotRead
    model_binding_snapshot: ModelBindingSnapshotRead
    chat_model: FakeChatModel = field(init=False)

    def __post_init__(self) -> None:
        self.chat_model = FakeChatModel(fake_provider=self)

    def enqueue_structured_success(self, payload: Mapping[str, Any]) -> None:
        self.chat_model.enqueue_structured_success(payload)

    def enqueue_tool_call_request(
        self,
        tool_name: str,
        input_payload: Mapping[str, Any],
    ) -> None:
        self.chat_model.enqueue_tool_call_request(tool_name, input_payload)

    def enqueue_structured_failure(
        self,
        *,
        error_code: ErrorCode | None,
        message: str,
        failure_kind: str = "structured_failure",
    ) -> None:
        self.chat_model.enqueue_structured_failure(
            error_code=error_code,
            message=message,
            failure_kind=failure_kind,
        )

    def enqueue_timeout(self) -> None:
        self.chat_model.enqueue_timeout()

    def enqueue_rate_limit(self) -> None:
        self.chat_model.enqueue_rate_limit()

    def enqueue_network_error(self) -> None:
        self.chat_model.enqueue_network_error()


def fake_provider_fixture(
    *,
    provider_snapshot: ProviderSnapshotRead | None = None,
    model_binding_snapshot: ModelBindingSnapshotRead | None = None,
    scripted_responses: Iterable[Mapping[str, Any]] | None = None,
) -> FakeProvider:
    resolved_provider_snapshot = provider_snapshot or provider_snapshot_fixture()
    if model_binding_snapshot is None:
        resolved_model_binding_snapshot = model_binding_snapshot_fixture(
            provider_snapshot_id=resolved_provider_snapshot.snapshot_id,
            provider_id=resolved_provider_snapshot.provider_id,
            model_id=resolved_provider_snapshot.model_id,
            run_id=resolved_provider_snapshot.run_id,
            capabilities=resolved_provider_snapshot.capabilities,
        )
    else:
        resolved_model_binding_snapshot = model_binding_snapshot.model_copy(
            update={
                "run_id": resolved_provider_snapshot.run_id,
                "provider_snapshot_id": resolved_provider_snapshot.snapshot_id,
                "provider_id": resolved_provider_snapshot.provider_id,
                "model_id": resolved_provider_snapshot.model_id,
                "capabilities": resolved_provider_snapshot.capabilities,
            }
        )
    config = ProviderRegistry(
        provider_snapshots=[resolved_provider_snapshot],
        model_binding_snapshots=[resolved_model_binding_snapshot],
    ).resolve(
        resolved_model_binding_snapshot.snapshot_id,
        requires_tool_calling=resolved_model_binding_snapshot.capabilities.supports_tool_calling,
    )
    fake_provider = FakeProvider(
        config=config,
        provider_snapshot=resolved_provider_snapshot,
        model_binding_snapshot=resolved_model_binding_snapshot,
    )
    if scripted_responses is not None:
        for item in scripted_responses:
            _enqueue_script_item(fake_provider.chat_model, item)
    return fake_provider


def fake_chat_model_fixture(
    *,
    fake_provider: FakeProvider | None = None,
    scripted_responses: Iterable[Mapping[str, Any]] | None = None,
) -> FakeChatModel:
    resolved_provider = fake_provider or fake_provider_fixture()
    chat_model = resolved_provider.chat_model
    if scripted_responses is not None:
        for item in scripted_responses:
            _enqueue_script_item(chat_model, item)
    return chat_model


def _enqueue_script_item(chat_model: FakeChatModel, item: Mapping[str, Any]) -> None:
    normalized = dict(item)
    kind = normalized["kind"]
    if kind == "structured_success":
        payload = normalized.get("payload", normalized.get("value", {}))
        chat_model.enqueue_structured_success(payload)  # type: ignore[arg-type]
        return
    if kind == "tool_call_request":
        chat_model.enqueue_tool_call_request(
            str(normalized["tool_name"]),
            normalized.get("input_payload", {}),  # type: ignore[arg-type]
        )
        return
    if kind == "structured_failure":
        chat_model.enqueue_structured_failure(
            error_code=normalized.get("error_code"),  # type: ignore[arg-type]
            message=str(normalized.get("message", "structured failure")),
            failure_kind=str(
                normalized.get("failure_kind", "structured_failure")
            ),
        )
        return
    if kind == "timeout":
        chat_model.enqueue_timeout()
        return
    if kind == "rate_limit":
        chat_model.enqueue_rate_limit()
        return
    if kind == "network_error":
        chat_model.enqueue_network_error()
        return
    raise AssertionError(f"Unsupported scripted response kind: {kind!r}")
