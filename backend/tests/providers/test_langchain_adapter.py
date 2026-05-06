from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages.content import InvalidToolCall

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.prompts import ModelCallType
from backend.app.schemas.runtime_settings import (
    ProviderCallPolicy,
    ProviderCallPolicySnapshotRead,
)
from backend.app.tools.protocol import ToolBindableDescription
from backend.tests.fixtures import (
    fake_provider_fixture,
    provider_capabilities_fixture,
    provider_snapshot_fixture,
)


NOW = datetime(2026, 5, 4, 15, 0, 0, tzinfo=UTC)


def trace_context() -> TraceContext:
    return TraceContext(
        request_id="request-provider-1",
        trace_id="trace-provider-1",
        correlation_id="correlation-provider-1",
        span_id="span-provider-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def provider_policy_snapshot(**overrides: object) -> ProviderCallPolicySnapshotRead:
    policy_values = {
        "request_timeout_seconds": 45,
        "network_error_max_retries": 3,
        "rate_limit_max_retries": 2,
        "backoff_base_seconds": 1.0,
        "backoff_max_seconds": 8.0,
        "circuit_breaker_failure_threshold": 5,
        "circuit_breaker_recovery_seconds": 60,
        **overrides,
    }
    return ProviderCallPolicySnapshotRead(
        snapshot_id="provider-policy-snapshot-run-1",
        run_id="run-1",
        provider_call_policy=ProviderCallPolicy(**policy_values),
        source_config_version="runtime-settings-v2",
        schema_version="provider-call-policy-snapshot-v1",
        created_at=NOW,
    )


def tool(name: str = "read_file") -> ToolBindableDescription:
    return ToolBindableDescription(
        name=name,
        description="Read a file inside the workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.READ_ONLY,
        risk_categories=[],
        schema_version="tool-schema-v1",
    )


class _FakeBoundModel:
    def __init__(self, response: AIMessage) -> None:
        self._response = response

    def bind_tools(self, schemas, **kwargs):
        self.bound_schemas = schemas
        self.bound_kwargs = kwargs
        return self

    def invoke(self, _messages):
        return self._response


class _FakeStructuredModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = dict(payload)

    def bind_tools(self, schemas, **kwargs):
        self.bound_schemas = schemas
        self.bound_kwargs = kwargs
        return self

    def with_structured_output(self, schema, **kwargs):
        self.structured_schema = schema
        self.structured_kwargs = kwargs
        return self

    def invoke(self, _messages):
        return {
            "parsed": dict(self._payload),
            "raw": AIMessage(content="structured-ok"),
        }


class _FakeStructuredErrorModel:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def bind_tools(self, schemas, **kwargs):
        self.bound_schemas = schemas
        self.bound_kwargs = kwargs
        return self

    def with_structured_output(self, schema, **kwargs):
        self.structured_schema = schema
        self.structured_kwargs = kwargs
        return self

    def invoke(self, _messages):
        raise self._error


class _FakeRawDictModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = dict(payload)

    def invoke(self, _messages):
        return dict(self._payload)


class _RetrySequenceModel:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.invocations = 0

    def with_structured_output(self, schema, **kwargs):
        self.structured_schema = schema
        self.structured_kwargs = kwargs
        return self

    def invoke(self, _messages):
        self.invocations += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, dict):
            return {
                "parsed": dict(outcome),
                "raw": AIMessage(content="ok"),
            }
        return outcome


class _ArtifactProcessRecordRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def append_process_record(
        self,
        *,
        artifact_id: str,
        process_key: str,
        process_value: object,
        trace_context: TraceContext,
    ) -> None:
        self.calls.append(
            {
                "artifact_id": artifact_id,
                "process_key": process_key,
                "process_value": process_value,
                "trace_context": trace_context,
            }
        )


def test_create_chat_model_uses_only_frozen_snapshot_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(
            api_key_ref="env:AI_DEVFLOW_CREDENTIAL_PROVIDER_TEST_KEY"
        )
    )
    monkeypatch.setenv("AI_DEVFLOW_CREDENTIAL_PROVIDER_TEST_KEY", "runtime-secret")
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
    )

    model = adapter.create_chat_model()

    assert model.model_name == fake_provider.config.model_id
    assert model.openai_api_base == fake_provider.config.base_url
    assert model.request_timeout == 45
    assert model.max_tokens == fake_provider.config.max_output_tokens


def test_create_chat_model_resolves_env_api_key_ref_before_sdk_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(
            api_key_ref="env:AI_DEVFLOW_CREDENTIAL_PROVIDER_TEST_KEY"
        )
    )
    monkeypatch.setenv("AI_DEVFLOW_CREDENTIAL_PROVIDER_TEST_KEY", "runtime-secret")
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
    )

    model = adapter.create_chat_model()

    assert model.openai_api_key.get_secret_value() == "runtime-secret"


def test_create_chat_model_rejects_missing_api_key_env_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.providers.langchain_adapter import (
        LangChainProviderAdapter,
        LangChainProviderAdapterError,
    )

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(
            api_key_ref="env:AI_DEVFLOW_CREDENTIAL_MISSING_PROVIDER_KEY"
        )
    )
    monkeypatch.delenv("AI_DEVFLOW_CREDENTIAL_MISSING_PROVIDER_KEY", raising=False)
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
    )

    with pytest.raises(LangChainProviderAdapterError) as error:
        adapter.create_chat_model()

    assert error.value.error_code == "provider_credential_unavailable"


def test_create_chat_model_rejects_missing_api_key_without_fixture_fallback() -> None:
    from backend.app.providers.langchain_adapter import (
        LangChainProviderAdapter,
        LangChainProviderAdapterError,
    )

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(api_key_ref=None)
    )
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
    )

    with pytest.raises(LangChainProviderAdapterError) as error:
        adapter.create_chat_model()

    assert error.value.error_code == "provider_credential_unavailable"


def test_bind_tools_rejects_models_without_tool_calling_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.providers.langchain_adapter import (
        LangChainProviderAdapter,
        LangChainProviderAdapterError,
    )

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(
            capabilities=provider_capabilities_fixture(supports_tool_calling=False)
        )
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "runtime-secret")
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
    )

    with pytest.raises(LangChainProviderAdapterError) as error:
        adapter.bind_tools(adapter.create_chat_model(), (tool(),))

    assert error.value.error_code == "provider_capability_unsupported"


def test_bind_tools_uses_langchain_tool_schema_with_strict_binding() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture()
    model = _FakeBoundModel(AIMessage(content="ok"))
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
    )

    adapter.bind_tools(model, (tool(),))

    assert model.bound_schemas == [tool().to_langchain_tool_schema()]
    assert model.bound_kwargs == {"strict": True}


def test_invoke_structured_returns_normalized_tool_call_requests_and_usage() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeBoundModel(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"path": "src/app.py"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "total_tokens": 18,
                },
            )
        ),
    )

    result = adapter.invoke_structured(
        messages=(
            SystemMessage(content="system"),
            HumanMessage(content="user"),
        ),
        response_schema={
            "type": "object",
            "properties": {"decision_type": {"type": "string"}},
            "required": ["decision_type"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(tool(),),
        trace_context=trace_context(),
    )

    assert result.structured_output is None
    assert result.tool_call_requests[0].call_id == "call-1"
    assert result.tool_call_requests[0].tool_name == "read_file"
    assert result.tool_call_requests[0].input_payload == {"path": "src/app.py"}
    assert result.tool_call_requests[0].schema_version == "tool-schema-v1"
    assert result.usage.total_tokens == 18
    assert result.trace_summary.provider_snapshot_id == (
        fake_provider.config.provider_snapshot_id
    )
    assert result.raw_response_ref.startswith("sha256:")


def test_invoke_structured_respects_smaller_requested_output_budget() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    captured: dict[str, int | None] = {}
    fake_provider = fake_provider_fixture()

    def factory(_config, _timeout, max_tokens):
        captured["max_tokens"] = max_tokens
        return _FakeStructuredModel({"artifact_name": "solution", "summary": "done"})

    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=factory,
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {
                "artifact_name": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["artifact_name", "summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        requested_max_output_tokens=256,
    )

    assert captured["max_tokens"] == 256
    assert result.structured_output == {
        "artifact_name": "solution",
        "summary": "done",
    }


def test_invoke_structured_fallback_dict_outputs_are_candidates_only() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(
            capabilities=provider_capabilities_fixture(
                supports_structured_output=False
            )
        )
    )
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeRawDictModel(
            {"summary": "candidate"}
        ),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
    )

    assert result.structured_output is None
    assert result.structured_output_candidates == ({"summary": "candidate"},)


def test_invoke_structured_normalizes_openai_tool_call_arguments() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    message = AIMessage(content="")
    message.additional_kwargs["tool_calls"] = [
        {
            "id": "call-openai-1",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path":"src/app.py"}',
            },
        }
    ]
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeBoundModel(message),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(tool(),),
        trace_context=trace_context(),
    )

    assert len(result.tool_call_requests) == 1
    assert result.tool_call_requests[0].call_id == "call-openai-1"
    assert result.tool_call_requests[0].tool_name == "read_file"
    assert result.tool_call_requests[0].input_payload == {"path": "src/app.py"}
    assert result.tool_call_requests[0].schema_version == "tool-schema-v1"


def test_invoke_structured_treats_malformed_openai_tool_call_arguments_as_invalid() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    message = AIMessage(content="")
    message.additional_kwargs["tool_calls"] = [
        {
            "id": "call-openai-invalid-1",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path":',
            },
        }
    ]
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeBoundModel(message),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(tool(),),
        trace_context=trace_context(),
    )

    assert result.tool_call_requests == ()
    assert result.invalid_tool_call_candidates == (
        {
            "call_id": "call-openai-invalid-1",
            "tool_name": "read_file",
            "arguments_text": '{"path":',
            "error": "OpenAI tool call arguments must decode to a JSON object.",
        },
    )


def test_invoke_structured_returns_invalid_tool_call_candidates() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeBoundModel(
            AIMessage(
                content="",
                invalid_tool_calls=[
                    InvalidToolCall(
                        name="read_file",
                        args='{"path":',
                        id="invalid-call-1",
                        error="json decode error",
                        type="invalid_tool_call",
                    )
                ],
            )
        ),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(tool(),),
        trace_context=trace_context(),
    )

    assert result.invalid_tool_call_candidates == (
        {
            "call_id": "invalid-call-1",
            "tool_name": "read_file",
            "arguments_text": '{"path":',
            "error": "json decode error",
        },
    )


def test_invoke_structured_normalizes_malformed_usage_without_raising() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    message = AIMessage(
        content="summary",
        response_metadata={
            "token_usage": {
                "input_tokens": "unknown",
                "completion_tokens": 4,
                "total_tokens": "bad",
            }
        },
    )
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeBoundModel(message),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
    )

    assert result.provider_error_code is None
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens == 4
    assert result.usage.total_tokens is None


def test_trace_summary_does_not_expose_repr_of_unknown_objects() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    class _SecretObject:
        def __repr__(self) -> str:
            return "password=abcd"

    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        redaction_policy=RedactionPolicy(max_text_length=20, excerpt_length=40),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeRawDictModel(
            {"parse_error": _SecretObject()}
        ),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
    )

    trace_dump = str(result.trace_summary.model_dump())
    assert "password=abcd" not in trace_dump


def test_invoke_structured_returns_structured_failure_for_provider_errors() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeStructuredErrorModel(
            RuntimeError("provider timed out with token=secret")
        ),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
    )

    assert result.provider_error_code is ErrorCode.PROVIDER_RETRY_EXHAUSTED
    assert result.provider_error_message == "Provider call failed."
    assert result.structured_output is None
    assert result.tool_call_requests == ()


def test_invoke_structured_preserves_setup_errors_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.providers.langchain_adapter import (
        LangChainProviderAdapter,
        LangChainProviderAdapterError,
    )

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(
            api_key_ref="env:AI_DEVFLOW_CREDENTIAL_MISSING_PROVIDER_KEY"
        )
    )
    monkeypatch.delenv("AI_DEVFLOW_CREDENTIAL_MISSING_PROVIDER_KEY", raising=False)
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
    )

    with pytest.raises(LangChainProviderAdapterError) as error:
        adapter.invoke_structured(
            messages=(SystemMessage(content="system"), HumanMessage(content="user")),
            response_schema={"type": "object"},
            model_call_type=ModelCallType.STAGE_EXECUTION,
            tool_descriptions=(),
            trace_context=trace_context(),
        )

    assert error.value.error_code == "provider_credential_unavailable"


def test_invoke_with_retry_retries_timeout_with_exponential_backoff() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    waits: list[float] = []
    model = _RetrySequenceModel(
        [
            TimeoutError("request timed out"),
            ConnectionError("network down"),
            {"summary": "done"},
        ]
    )
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: model,
    )

    result = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=waits.append,
    )

    assert result.provider_error_code is None
    assert result.structured_output == {"summary": "done"}
    assert waits == [1.0, 2.0]
    assert model.invocations == 3
    assert [trace.status for trace in result.provider_retry_trace] == [
        "scheduled",
        "scheduled",
        "succeeded",
    ]
    assert result.provider_retry_trace[0].run_id == "run-1"
    assert result.provider_retry_trace[0].stage_run_id == "stage-run-1"


def test_invoke_with_retry_uses_unique_trace_refs_across_repeated_retries() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    model = _RetrySequenceModel(
        [
            TimeoutError("request timed out"),
            {"summary": "first"},
            TimeoutError("request timed out again"),
            {"summary": "second"},
        ]
    )
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: model,
    )
    times = iter(
        [
            NOW,
            NOW.replace(second=1),
            NOW.replace(second=2),
            NOW.replace(second=3),
        ]
    )

    first = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=lambda _seconds: None,
        now=lambda: next(times),
    )
    second = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=lambda _seconds: None,
        now=lambda: next(times),
    )

    trace_refs = [
        trace.trace_ref
        for trace in [*first.provider_retry_trace, *second.provider_retry_trace]
    ]
    assert len(trace_refs) == 4
    assert len(set(trace_refs)) == 4


def test_invoke_with_retry_does_not_retry_non_retryable_provider_errors() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    waits: list[float] = []
    model = _RetrySequenceModel([RuntimeError("401 unauthorized api key")])
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(
            circuit_breaker_failure_threshold=1
        ),
        chat_model_factory=lambda _config, _timeout, _max_tokens: model,
    )

    result = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=waits.append,
    )

    assert waits == []
    assert model.invocations == 1
    assert result.provider_error_code is ErrorCode.PROVIDER_RETRY_EXHAUSTED
    assert result.provider_retry_trace[-1].status == "not_retryable"
    assert result.provider_circuit_breaker_trace == ()


def test_invoke_with_retry_does_not_retry_empty_structured_response() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    waits: list[float] = []
    model = _RetrySequenceModel([{}])
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: model,
    )

    result = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=waits.append,
    )

    assert waits == []
    assert model.invocations == 1
    assert result.provider_error_code is ErrorCode.PROVIDER_RETRY_EXHAUSTED
    assert result.provider_retry_trace[-1].failure_kind == "empty_response"
    assert result.provider_retry_trace[-1].status == "not_retryable"


def test_invoke_with_retry_does_not_retry_unparseable_structured_output() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    waits: list[float] = []
    model = _RetrySequenceModel(["not structured"])
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: model,
    )

    result = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=waits.append,
    )

    assert waits == []
    assert model.invocations == 1
    assert result.provider_error_code is ErrorCode.PROVIDER_RETRY_EXHAUSTED
    assert result.provider_retry_trace[-1].failure_kind == (
        "structured_output_unparseable"
    )
    assert result.provider_retry_trace[-1].status == "not_retryable"


def test_invoke_with_retry_opens_circuit_and_blocks_later_same_binding_call() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    model = _RetrySequenceModel(
        [
            ConnectionError("network down"),
            ConnectionError("network still down"),
            {"summary": "should not be reached"},
        ]
    )
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(
            circuit_breaker_failure_threshold=2,
            network_error_max_retries=5,
        ),
        chat_model_factory=lambda _config, _timeout, _max_tokens: model,
    )

    first = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=lambda _seconds: None,
    )
    second = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=lambda _seconds: None,
    )

    assert first.provider_error_code is ErrorCode.PROVIDER_CIRCUIT_OPEN
    assert first.provider_circuit_breaker_trace[-1].action == "opened"
    assert first.provider_circuit_breaker_trace[-1].stage_run_id == "stage-run-1"
    assert [trace.status for trace in first.provider_retry_trace] == [
        "scheduled",
        "exhausted",
    ]
    assert first.provider_retry_trace[-1].status == "exhausted"
    assert first.provider_retry_trace[-1].backoff_wait_seconds is None
    assert second.provider_error_code is ErrorCode.PROVIDER_CIRCUIT_OPEN
    assert second.provider_circuit_breaker_trace[-1].action == "blocked"
    assert model.invocations == 2


def test_invoke_with_retry_records_closed_trace_after_half_open_success() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    model = _RetrySequenceModel(
        [
            ConnectionError("network down"),
            {"summary": "recovered"},
        ]
    )
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(
            circuit_breaker_failure_threshold=1,
            circuit_breaker_recovery_seconds=30,
        ),
        chat_model_factory=lambda _config, _timeout, _max_tokens: model,
    )

    opened = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=lambda _seconds: None,
        now=lambda: NOW,
    )
    recovered = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=lambda _seconds: None,
        now=lambda: NOW.replace(second=31),
    )

    assert opened.provider_error_code is ErrorCode.PROVIDER_CIRCUIT_OPEN
    assert recovered.provider_error_code is None
    assert recovered.structured_output == {"summary": "recovered"}
    assert [trace.action for trace in recovered.provider_circuit_breaker_trace] == [
        "half_open",
        "closed",
    ]


def test_provider_traces_use_ordinary_artifact_process_record_keys() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter
    from backend.app.services.artifacts import ArtifactStore

    assert not hasattr(ArtifactStore, "append_provider_retry_trace")
    assert not hasattr(ArtifactStore, "append_provider_circuit_breaker_trace")

    model = _RetrySequenceModel([ConnectionError("network down")])
    fake_provider = fake_provider_fixture()
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(
            circuit_breaker_failure_threshold=1,
            network_error_max_retries=5,
        ),
        chat_model_factory=lambda _config, _timeout, _max_tokens: model,
    )

    result = adapter.invoke_with_retry(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={"type": "object"},
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
        sleep=lambda _seconds: None,
        now=lambda: NOW,
    )
    recorder = _ArtifactProcessRecordRecorder()
    retry_records = [
        trace.model_dump(mode="json") for trace in result.provider_retry_trace
    ]
    circuit_records = [
        trace.model_dump(mode="json")
        for trace in result.provider_circuit_breaker_trace
    ]

    recorder.append_process_record(
        artifact_id="artifact-stage-1",
        process_key="provider_retry_trace",
        process_value=retry_records,
        trace_context=trace_context(),
    )
    recorder.append_process_record(
        artifact_id="artifact-stage-1",
        process_key="provider_retry_trace_refs",
        process_value=[trace["trace_ref"] for trace in retry_records],
        trace_context=trace_context(),
    )
    recorder.append_process_record(
        artifact_id="artifact-stage-1",
        process_key="provider_retry_trace_ref",
        process_value=retry_records[-1]["trace_ref"],
        trace_context=trace_context(),
    )
    recorder.append_process_record(
        artifact_id="artifact-stage-1",
        process_key="provider_circuit_breaker_trace",
        process_value=circuit_records,
        trace_context=trace_context(),
    )
    recorder.append_process_record(
        artifact_id="artifact-stage-1",
        process_key="provider_circuit_breaker_trace_refs",
        process_value=[trace["trace_ref"] for trace in circuit_records],
        trace_context=trace_context(),
    )
    recorder.append_process_record(
        artifact_id="artifact-stage-1",
        process_key="provider_circuit_breaker_trace_ref",
        process_value=circuit_records[-1]["trace_ref"],
        trace_context=trace_context(),
    )

    assert result.provider_error_code is ErrorCode.PROVIDER_CIRCUIT_OPEN
    assert [call["process_key"] for call in recorder.calls] == [
        "provider_retry_trace",
        "provider_retry_trace_refs",
        "provider_retry_trace_ref",
        "provider_circuit_breaker_trace",
        "provider_circuit_breaker_trace_refs",
        "provider_circuit_breaker_trace_ref",
    ]
    assert recorder.calls[0]["process_value"] == retry_records
    assert recorder.calls[3]["process_value"] == circuit_records
    assert retry_records[0]["run_id"] == "run-1"
    assert circuit_records[0]["stage_run_id"] == "stage-run-1"


def test_invoke_structured_does_not_emit_native_reasoning_when_capability_is_false() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(
            capabilities=provider_capabilities_fixture(supports_native_reasoning=False)
        )
    )
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeBoundModel(
            AIMessage(
                content="summary",
                additional_kwargs={"reasoning": "secret reasoning"},
            )
        ),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
    )

    assert result.native_reasoning_ref is None


def test_invoke_structured_emits_native_reasoning_ref_when_capability_is_true() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture(
        provider_snapshot=provider_snapshot_fixture(
            capabilities=provider_capabilities_fixture(supports_native_reasoning=True)
        )
    )
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeBoundModel(
            AIMessage(
                content="summary",
                additional_kwargs={"reasoning": "native reasoning"},
            )
        ),
    )

    result = adapter.invoke_structured(
        messages=(SystemMessage(content="system"), HumanMessage(content="user")),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
    )

    assert result.native_reasoning_ref is not None
    assert result.native_reasoning_ref.startswith("sha256:")


def test_trace_summary_redacts_credentials_and_truncates_model_visible_text() -> None:
    from backend.app.providers.langchain_adapter import LangChainProviderAdapter

    fake_provider = fake_provider_fixture()
    oversized_output = "x" * 100
    adapter = LangChainProviderAdapter(
        provider_config=fake_provider.config,
        provider_call_policy_snapshot=provider_policy_snapshot(),
        redaction_policy=RedactionPolicy(max_text_length=20, excerpt_length=40),
        chat_model_factory=lambda _config, _timeout, _max_tokens: _FakeBoundModel(
            AIMessage(content=oversized_output)
        ),
    )

    result = adapter.invoke_structured(
        messages=(
            SystemMessage(content="system with sk-secret"),
            HumanMessage(content="user content " * 20),
        ),
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        model_call_type=ModelCallType.STAGE_EXECUTION,
        tool_descriptions=(),
        trace_context=trace_context(),
    )

    trace_dump = str(result.trace_summary.model_dump())
    assert "sk-secret" not in trace_dump
    assert "env:DEEPSEEK_API_KEY" not in trace_dump
    assert oversized_output not in trace_dump
    assert result.trace_summary.output_summary["content_hash"].startswith("sha256:")
