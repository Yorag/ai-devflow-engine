from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
import time
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.redaction import RedactionPolicy
from backend.app.providers.base import ProviderConfig
from backend.app.providers.retry_policy import (
    ProviderCircuitBreaker,
    ProviderCircuitBreakerTraceRecord,
    ProviderNonRetryableFailure,
    ProviderRetryPolicy,
    ProviderRetryTraceRecord,
    classify_provider_failure,
)
from backend.app.schemas.prompts import ModelCallType
from backend.app.schemas.runtime_settings import ProviderCallPolicySnapshotRead
from backend.app.tools.protocol import ToolBindableDescription


JsonObject = dict[str, object]
ChatModelFactory = Callable[[ProviderConfig, int, int], Any]


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LangChainProviderAdapterError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        safe_message: str,
        *,
        provider_snapshot_id: str,
        model_binding_snapshot_id: str,
    ) -> None:
        super().__init__(safe_message)
        self.error_code = error_code
        self.safe_message = safe_message
        self.provider_snapshot_id = provider_snapshot_id
        self.model_binding_snapshot_id = model_binding_snapshot_id


class ModelCallToolRequest(_StrictBaseModel):
    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    input_payload: JsonObject = Field(default_factory=dict)
    schema_version: str | None = None


class ModelCallUsage(_StrictBaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ModelCallTraceSummary(_StrictBaseModel):
    request_id: str
    trace_id: str
    correlation_id: str
    span_id: str
    parent_span_id: str | None = None
    run_id: str | None = None
    stage_run_id: str | None = None
    provider_snapshot_id: str
    model_binding_snapshot_id: str
    model_call_type: ModelCallType
    input_summary: JsonObject
    output_summary: JsonObject


class ModelCallResult(_StrictBaseModel):
    provider_snapshot_id: str
    model_binding_snapshot_id: str
    model_call_type: ModelCallType
    structured_output: JsonObject | None = None
    structured_output_candidates: tuple[JsonObject, ...] = ()
    tool_call_requests: tuple[ModelCallToolRequest, ...] = ()
    invalid_tool_call_candidates: tuple[JsonObject, ...] = ()
    provider_error_code: ErrorCode | None = None
    provider_error_message: str | None = None
    usage: ModelCallUsage = Field(default_factory=ModelCallUsage)
    raw_response_ref: str | None = None
    native_reasoning_ref: str | None = None
    provider_retry_trace: tuple[ProviderRetryTraceRecord, ...] = ()
    provider_circuit_breaker_trace: tuple[ProviderCircuitBreakerTraceRecord, ...] = ()
    trace_summary: ModelCallTraceSummary


class LangChainProviderAdapter:
    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        provider_call_policy_snapshot: ProviderCallPolicySnapshotRead,
        redaction_policy: RedactionPolicy | None = None,
        chat_model_factory: ChatModelFactory | None = None,
        circuit_breaker: ProviderCircuitBreaker | None = None,
    ) -> None:
        self.provider_config = provider_config
        self.provider_call_policy_snapshot = provider_call_policy_snapshot
        self.redaction_policy = redaction_policy or RedactionPolicy()
        self._chat_model_factory = chat_model_factory
        self._retry_policy = ProviderRetryPolicy(provider_call_policy_snapshot)
        self._circuit_breaker = circuit_breaker or ProviderCircuitBreaker(
            self._retry_policy
        )
        self._trace_ref_sequence = 0

    def create_chat_model(self, requested_max_output_tokens: int | None = None) -> Any:
        request_timeout = (
            self.provider_call_policy_snapshot.provider_call_policy.request_timeout_seconds
        )
        max_tokens = self._effective_max_tokens(requested_max_output_tokens)
        provider_config = self._provider_config_with_resolved_api_key(
            require_available=self._chat_model_factory is None
        )
        if self._chat_model_factory is not None:
            return self._chat_model_factory(
                provider_config,
                request_timeout,
                max_tokens,
            )
        return ChatOpenAI(
            model=provider_config.model_id,
            openai_api_base=provider_config.base_url,
            openai_api_key=provider_config.api_key_ref,
            request_timeout=request_timeout,
            max_tokens=max_tokens,
            model_kwargs=dict(provider_config.model_parameters),
        )

    def bind_tools(
        self,
        chat_model: Any,
        tool_descriptions: Sequence[ToolBindableDescription],
    ) -> Any:
        if not self.provider_config.supports_tool_calling:
            raise LangChainProviderAdapterError(
                "provider_capability_unsupported",
                "Provider model binding does not support tool calling.",
                provider_snapshot_id=self.provider_config.provider_snapshot_id,
                model_binding_snapshot_id=(
                    self.provider_config.model_binding_snapshot_id
                ),
            )
        tool_schemas = [
            description.to_langchain_tool_schema()
            for description in tool_descriptions
        ]
        return chat_model.bind_tools(tool_schemas, strict=True)

    def with_structured_output(self, chat_model: Any, response_schema: JsonObject) -> Any:
        if not self.provider_config.supports_structured_output:
            return chat_model
        if not hasattr(chat_model, "with_structured_output"):
            return chat_model
        normalized_schema = self._structured_output_schema(response_schema)
        return chat_model.with_structured_output(
            normalized_schema,
            include_raw=True,
            strict=True,
        )

    def invoke_structured(
        self,
        *,
        messages: Sequence[BaseMessage],
        response_schema: JsonObject,
        model_call_type: ModelCallType,
        tool_descriptions: Sequence[ToolBindableDescription],
        trace_context: TraceContext,
        requested_max_output_tokens: int | None = None,
    ) -> ModelCallResult:
        input_summary = self._summarize_input(messages)
        runnable = self._structured_runnable(
            response_schema=response_schema,
            tool_descriptions=tool_descriptions,
            requested_max_output_tokens=requested_max_output_tokens,
        )

        try:
            raw_response = runnable.invoke(tuple(messages))
            return self._result_from_raw_response(
                raw_response,
                model_call_type=model_call_type,
                trace_context=trace_context,
                input_summary=input_summary,
                tool_descriptions=tool_descriptions,
            )
        except Exception:
            output_summary = self._summarize_output(
                {"provider_error": "Provider call failed."}
            )
            return self._result(
                model_call_type=model_call_type,
                trace_context=trace_context,
                input_summary=input_summary,
                output_summary=output_summary,
                provider_error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
                provider_error_message="Provider call failed.",
            )

    def invoke_with_retry(
        self,
        *,
        messages: Sequence[BaseMessage],
        response_schema: JsonObject,
        model_call_type: ModelCallType,
        tool_descriptions: Sequence[ToolBindableDescription],
        trace_context: TraceContext,
        requested_max_output_tokens: int | None = None,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> ModelCallResult:
        input_summary = self._summarize_input(messages)
        sleep_fn = sleep or time.sleep
        now_fn = now or (lambda: datetime.now(UTC))
        key = self._circuit_breaker.binding_key(
            provider_snapshot_id=self.provider_config.provider_snapshot_id,
            model_binding_snapshot_id=self.provider_config.model_binding_snapshot_id,
        )
        retry_trace: list[ProviderRetryTraceRecord] = []
        circuit_trace: list[ProviderCircuitBreakerTraceRecord] = []
        retry_attempt = 1

        while True:
            occurred_at = now_fn()
            before_call = self._circuit_breaker.before_call(
                key,
                occurred_at=occurred_at,
            )
            if before_call.action == "half_open":
                circuit_trace.append(
                    self._circuit_trace_record(
                        state=before_call.state,
                        action="half_open",
                        occurred_at=occurred_at,
                        trace_context=trace_context,
                    )
                )
            if not before_call.allowed:
                circuit_trace.append(
                    self._circuit_trace_record(
                        state=before_call.state,
                        action="blocked",
                        occurred_at=occurred_at,
                        trace_context=trace_context,
                    )
                )
                return self._provider_failure_result(
                    model_call_type=model_call_type,
                    trace_context=trace_context,
                    input_summary=input_summary,
                    provider_error_code=ErrorCode.PROVIDER_CIRCUIT_OPEN,
                    provider_error_message="Provider circuit breaker is open.",
                    provider_retry_trace=tuple(retry_trace),
                    provider_circuit_breaker_trace=tuple(circuit_trace),
                )

            try:
                result = self._invoke_structured_once(
                    messages=messages,
                    response_schema=response_schema,
                    model_call_type=model_call_type,
                    tool_descriptions=tool_descriptions,
                    trace_context=trace_context,
                    input_summary=input_summary,
                    requested_max_output_tokens=requested_max_output_tokens,
                )
                self._raise_for_non_retryable_result(result)
            except Exception as exc:
                failure = (
                    exc.failure
                    if isinstance(exc, ProviderNonRetryableFailure)
                    else self._retry_policy.failure_from_exception(exc)
                )
                decision = self._retry_policy.decision_for_failure(
                    failure,
                    retry_attempt=retry_attempt,
                )
                if not failure.retryable:
                    retry_trace.append(
                        self._retry_trace_record(
                            failure_kind=decision.failure_kind,
                            retry_attempt=decision.retry_attempt,
                            max_retry_attempts=decision.max_retry_attempts,
                            backoff_wait_seconds=decision.backoff_wait_seconds,
                            status=decision.status,
                            error_code=decision.error_code,
                            occurred_at=occurred_at,
                            trace_context=trace_context,
                        )
                    )
                    return self._provider_failure_result(
                        model_call_type=model_call_type,
                        trace_context=trace_context,
                        input_summary=input_summary,
                        provider_error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
                        provider_error_message=decision.safe_message,
                        provider_retry_trace=tuple(retry_trace),
                        provider_circuit_breaker_trace=tuple(circuit_trace),
                    )
                circuit_state = self._circuit_breaker.record_failure(
                    key,
                    failure_kind=failure.failure_kind,
                    occurred_at=occurred_at,
                )
                if circuit_state.status.value == "open":
                    retry_trace.append(
                        self._retry_trace_record(
                            failure_kind=decision.failure_kind,
                            retry_attempt=decision.retry_attempt,
                            max_retry_attempts=decision.max_retry_attempts,
                            backoff_wait_seconds=None,
                            status="exhausted",
                            error_code=decision.error_code,
                            occurred_at=occurred_at,
                            trace_context=trace_context,
                        )
                    )
                    circuit_trace.append(
                        self._circuit_trace_record(
                            state=circuit_state,
                            action="opened",
                            occurred_at=occurred_at,
                            trace_context=trace_context,
                        )
                    )
                    return self._provider_failure_result(
                        model_call_type=model_call_type,
                        trace_context=trace_context,
                        input_summary=input_summary,
                        provider_error_code=ErrorCode.PROVIDER_CIRCUIT_OPEN,
                        provider_error_message="Provider circuit breaker is open.",
                        provider_retry_trace=tuple(retry_trace),
                        provider_circuit_breaker_trace=tuple(circuit_trace),
                    )
                if not decision.should_retry:
                    retry_trace.append(
                        self._retry_trace_record(
                            failure_kind=decision.failure_kind,
                            retry_attempt=decision.retry_attempt,
                            max_retry_attempts=decision.max_retry_attempts,
                            backoff_wait_seconds=decision.backoff_wait_seconds,
                            status=decision.status,
                            error_code=decision.error_code,
                            occurred_at=occurred_at,
                            trace_context=trace_context,
                        )
                    )
                    return self._provider_failure_result(
                        model_call_type=model_call_type,
                        trace_context=trace_context,
                        input_summary=input_summary,
                        provider_error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
                        provider_error_message=decision.safe_message,
                        provider_retry_trace=tuple(retry_trace),
                        provider_circuit_breaker_trace=tuple(circuit_trace),
                    )
                retry_trace.append(
                    self._retry_trace_record(
                        failure_kind=decision.failure_kind,
                        retry_attempt=decision.retry_attempt,
                        max_retry_attempts=decision.max_retry_attempts,
                        backoff_wait_seconds=decision.backoff_wait_seconds,
                        status=decision.status,
                        error_code=decision.error_code,
                        occurred_at=occurred_at,
                        trace_context=trace_context,
                    )
                )
                sleep_fn(float(decision.backoff_wait_seconds or 0.0))
                retry_attempt += 1
                continue

            closed_state = self._circuit_breaker.record_success(
                key,
                occurred_at=occurred_at,
            )
            if before_call.action == "half_open":
                circuit_trace.append(
                    self._circuit_trace_record(
                        state=closed_state,
                        action="closed",
                        occurred_at=occurred_at,
                        trace_context=trace_context,
                    )
                )
            if retry_trace:
                retry_trace.append(
                    self._retry_trace_record(
                        failure_kind=retry_trace[-1].failure_kind,
                        retry_attempt=retry_attempt - 1,
                        max_retry_attempts=retry_trace[-1].max_retry_attempts,
                        backoff_wait_seconds=None,
                        status="succeeded",
                        error_code=None,
                        occurred_at=occurred_at,
                        trace_context=trace_context,
                    )
                )
            return result.model_copy(
                update={
                    "provider_retry_trace": tuple(retry_trace),
                    "provider_circuit_breaker_trace": tuple(circuit_trace),
                }
            )

    def _raise_for_non_retryable_result(self, result: ModelCallResult) -> None:
        if result.provider_error_code is not None:
            return
        if result.structured_output == {}:
            raise ProviderNonRetryableFailure(
                classify_provider_failure(
                    "empty_response",
                    "Provider response was empty.",
                )
            )
        if (
            result.structured_output is None
            and not result.structured_output_candidates
            and not result.tool_call_requests
        ):
            raise ProviderNonRetryableFailure(
                classify_provider_failure(
                    "structured_output_unparseable",
                    "Provider structured output could not be parsed.",
                )
            )

    def _invoke_structured_once(
        self,
        *,
        messages: Sequence[BaseMessage],
        response_schema: JsonObject,
        model_call_type: ModelCallType,
        tool_descriptions: Sequence[ToolBindableDescription],
        trace_context: TraceContext,
        input_summary: JsonObject,
        requested_max_output_tokens: int | None = None,
    ) -> ModelCallResult:
        runnable = self._structured_runnable(
            response_schema=response_schema,
            tool_descriptions=tool_descriptions,
            requested_max_output_tokens=requested_max_output_tokens,
        )
        raw_response = runnable.invoke(tuple(messages))
        return self._result_from_raw_response(
            raw_response,
            model_call_type=model_call_type,
            trace_context=trace_context,
            input_summary=input_summary,
            tool_descriptions=tool_descriptions,
        )

    def _structured_runnable(
        self,
        *,
        response_schema: JsonObject,
        tool_descriptions: Sequence[ToolBindableDescription],
        requested_max_output_tokens: int | None = None,
    ) -> Any:
        chat_model = self.create_chat_model(
            requested_max_output_tokens=requested_max_output_tokens
        )
        if tool_descriptions:
            chat_model = self.bind_tools(chat_model, tool_descriptions)
        return self.with_structured_output(chat_model, response_schema)

    def _result_from_raw_response(
        self,
        raw_response: Any,
        *,
        model_call_type: ModelCallType,
        trace_context: TraceContext,
        input_summary: JsonObject,
        tool_descriptions: Sequence[ToolBindableDescription],
    ) -> ModelCallResult:
        normalized = self._normalize_response(raw_response)
        output_summary = self._summarize_output(normalized["summary_payload"])
        return self._result(
            model_call_type=model_call_type,
            trace_context=trace_context,
            input_summary=input_summary,
            output_summary=output_summary,
            structured_output=normalized["structured_output"],
            structured_output_candidates=normalized["structured_output_candidates"],
            tool_call_requests=self._normalize_tool_calls(
                normalized["ai_message"],
                tool_descriptions,
            ),
            invalid_tool_call_candidates=self._normalize_invalid_tool_calls(
                normalized["ai_message"]
            ),
            usage=self._normalize_usage(normalized["ai_message"]),
            raw_response_ref=self._raw_response_ref(raw_response),
            native_reasoning_ref=self._native_reasoning_ref(
                normalized["ai_message"]
            ),
        )

    def _provider_failure_result(
        self,
        *,
        model_call_type: ModelCallType,
        trace_context: TraceContext,
        input_summary: JsonObject,
        provider_error_code: ErrorCode,
        provider_error_message: str,
        provider_retry_trace: tuple[ProviderRetryTraceRecord, ...],
        provider_circuit_breaker_trace: tuple[ProviderCircuitBreakerTraceRecord, ...],
    ) -> ModelCallResult:
        output_summary = self._summarize_output(
            {
                "provider_error": provider_error_message,
                "provider_error_code": provider_error_code.value,
            }
        )
        return self._result(
            model_call_type=model_call_type,
            trace_context=trace_context,
            input_summary=input_summary,
            output_summary=output_summary,
            provider_error_code=provider_error_code,
            provider_error_message=provider_error_message,
            provider_retry_trace=provider_retry_trace,
            provider_circuit_breaker_trace=provider_circuit_breaker_trace,
        )

    def _provider_config_with_resolved_api_key(
        self,
        *,
        require_available: bool,
    ) -> ProviderConfig:
        api_key_ref = self.provider_config.api_key_ref
        if require_available and (
            not isinstance(api_key_ref, str) or api_key_ref.strip() == ""
        ):
            raise LangChainProviderAdapterError(
                "provider_credential_unavailable",
                "Provider credential is unavailable.",
                provider_snapshot_id=self.provider_config.provider_snapshot_id,
                model_binding_snapshot_id=(
                    self.provider_config.model_binding_snapshot_id
                ),
            )
        if not isinstance(api_key_ref, str) or not api_key_ref.startswith("env:"):
            return self.provider_config
        env_name = api_key_ref.removeprefix("env:")
        api_key = os.environ.get(env_name)
        if not require_available and (api_key is None or api_key == ""):
            return self.provider_config
        if not env_name or api_key is None or api_key == "":
            raise LangChainProviderAdapterError(
                "provider_credential_unavailable",
                "Provider credential environment reference is unavailable.",
                provider_snapshot_id=self.provider_config.provider_snapshot_id,
                model_binding_snapshot_id=(
                    self.provider_config.model_binding_snapshot_id
                ),
            )
        return replace(self.provider_config, api_key_ref=api_key)

    def _effective_max_tokens(self, requested_max_output_tokens: int | None) -> int:
        if requested_max_output_tokens is None:
            return self.provider_config.max_output_tokens
        return min(self.provider_config.max_output_tokens, requested_max_output_tokens)

    def _structured_output_schema(self, response_schema: JsonObject) -> JsonObject:
        schema = dict(response_schema)
        schema.setdefault("title", self._structured_output_schema_title())
        schema.setdefault("properties", {})
        return schema

    def _structured_output_schema_title(self) -> str:
        if self.provider_config.binding_type == "context_compression":
            return "CompressedContextBlock"
        if self.provider_config.binding_type == "structured_output_repair":
            return "StructuredOutputRepair"
        if self.provider_config.binding_type == "validation_pass":
            return "ValidationPass"
        return "AgentDecision"

    def _normalize_response(self, raw_response: Any) -> dict[str, Any]:
        if (
            isinstance(raw_response, Mapping)
            and "parsed" in raw_response
            and "raw" in raw_response
        ):
            parsed = raw_response["parsed"]
            structured_output = dict(parsed) if isinstance(parsed, Mapping) else None
            candidates = (structured_output,) if structured_output is not None else ()
            raw_message = raw_response["raw"]
            ai_message = raw_message if isinstance(raw_message, AIMessage) else None
            return {
                "ai_message": ai_message,
                "structured_output": structured_output,
                "structured_output_candidates": candidates,
                "summary_payload": self._response_summary_payload(raw_response),
            }

        if isinstance(raw_response, AIMessage):
            candidate = self._content_candidate(raw_response.content)
            return {
                "ai_message": raw_response,
                "structured_output": None,
                "structured_output_candidates": (
                    (candidate,) if candidate is not None else ()
                ),
                "summary_payload": self._ai_message_summary_payload(raw_response),
            }

        if isinstance(raw_response, Mapping):
            candidate = dict(raw_response)
            return {
                "ai_message": None,
                "structured_output": None,
                "structured_output_candidates": (candidate,),
                "summary_payload": self._response_summary_payload(raw_response),
            }

        return {
            "ai_message": None,
            "structured_output": None,
            "structured_output_candidates": (),
            "summary_payload": self._response_summary_payload(raw_response),
        }

    def _content_candidate(self, content: Any) -> JsonObject | None:
        if isinstance(content, Mapping):
            return dict(content)
        return None

    def _normalize_tool_calls(
        self,
        ai_message: AIMessage | None,
        tool_descriptions: Sequence[ToolBindableDescription],
    ) -> tuple[ModelCallToolRequest, ...]:
        if ai_message is None:
            return ()
        schema_versions = {
            description.name: description.schema_version
            for description in tool_descriptions
        }
        normalized = [
            self._tool_request_from_langchain_call(call, schema_versions)
            for call in getattr(ai_message, "tool_calls", ()) or ()
        ]
        if normalized:
            return tuple(normalized)
        openai_tool_calls = (
            ai_message.additional_kwargs.get("tool_calls", ()) or ()
        )
        normalized_openai = [
            self._tool_request_from_openai_call(call, schema_versions)
            for call in openai_tool_calls
        ]
        return tuple(
            request
            for request in normalized_openai
            if request is not None
        )

    def _tool_request_from_langchain_call(
        self,
        call: Mapping[str, Any],
        schema_versions: Mapping[str, str],
    ) -> ModelCallToolRequest:
        tool_name = str(call.get("name", ""))
        args = call.get("args")
        return ModelCallToolRequest(
            call_id=str(call.get("id") or tool_name),
            tool_name=tool_name,
            input_payload=dict(args) if isinstance(args, Mapping) else {},
            schema_version=schema_versions.get(tool_name),
        )

    def _tool_request_from_openai_call(
        self,
        call: Mapping[str, Any],
        schema_versions: Mapping[str, str],
    ) -> ModelCallToolRequest | None:
        function = call.get("function")
        function_payload = function if isinstance(function, Mapping) else {}
        tool_name = str(function_payload.get("name", ""))
        input_payload = self._json_object_from_arguments(
            function_payload.get("arguments")
        )
        if tool_name == "" or input_payload is None:
            return None
        return ModelCallToolRequest(
            call_id=str(call.get("id") or tool_name),
            tool_name=tool_name,
            input_payload=input_payload,
            schema_version=schema_versions.get(tool_name),
        )

    def _normalize_invalid_tool_calls(
        self,
        ai_message: AIMessage | None,
    ) -> tuple[JsonObject, ...]:
        if ai_message is None:
            return ()
        invalid_calls = [
            {
                "call_id": str(call.get("id") or call.get("name") or "invalid_tool_call"),
                "tool_name": str(call.get("name") or ""),
                "arguments_text": (
                    call.get("args") if isinstance(call.get("args"), str) else None
                ),
                "error": call.get("error") if isinstance(call.get("error"), str) else None,
            }
            for call in getattr(ai_message, "invalid_tool_calls", ()) or ()
            if isinstance(call, Mapping)
        ]
        invalid_calls.extend(
            candidate
            for candidate in (
                self._invalid_openai_tool_call_candidate(call)
                for call in ai_message.additional_kwargs.get("tool_calls", ()) or ()
            )
            if candidate is not None
        )
        return tuple(invalid_calls)

    def _invalid_openai_tool_call_candidate(
        self,
        call: Mapping[str, Any],
    ) -> JsonObject | None:
        function = call.get("function")
        function_payload = function if isinstance(function, Mapping) else {}
        tool_name = str(function_payload.get("name", ""))
        arguments = function_payload.get("arguments")
        arguments_text = arguments if isinstance(arguments, str) else None
        if tool_name == "":
            return {
                "call_id": str(call.get("id") or "invalid_tool_call"),
                "tool_name": "",
                "arguments_text": arguments_text,
                "error": "OpenAI tool call is missing function.name.",
            }
        parse_result = self._parse_json_object_from_arguments(arguments)
        if parse_result["input_payload"] is not None:
            return None
        return {
            "call_id": str(call.get("id") or tool_name),
            "tool_name": tool_name,
            "arguments_text": arguments_text,
            "error": str(parse_result["error"]),
        }

    def _json_object_from_arguments(self, arguments: object) -> JsonObject | None:
        return self._parse_json_object_from_arguments(arguments)["input_payload"]

    def _parse_json_object_from_arguments(self, arguments: object) -> dict[str, object]:
        if isinstance(arguments, Mapping):
            return {"input_payload": dict(arguments), "error": None}
        if arguments is None or arguments == "":
            return {"input_payload": {}, "error": None}
        if not isinstance(arguments, str):
            return {
                "input_payload": None,
                "error": "OpenAI tool call arguments must be a JSON object or string.",
            }
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {
                "input_payload": None,
                "error": "OpenAI tool call arguments must decode to a JSON object.",
            }
        if not isinstance(parsed, Mapping):
            return {
                "input_payload": None,
                "error": "OpenAI tool call arguments must decode to a JSON object.",
            }
        return {"input_payload": dict(parsed), "error": None}

    def _normalize_usage(self, ai_message: AIMessage | None) -> ModelCallUsage:
        if ai_message is None:
            return ModelCallUsage()
        usage_metadata = getattr(ai_message, "usage_metadata", None)
        if isinstance(usage_metadata, Mapping):
            return ModelCallUsage(
                input_tokens=self._int_or_none(usage_metadata.get("input_tokens")),
                output_tokens=self._int_or_none(usage_metadata.get("output_tokens")),
                total_tokens=self._int_or_none(usage_metadata.get("total_tokens")),
            )
        token_usage = ai_message.response_metadata.get("token_usage")
        if isinstance(token_usage, Mapping):
            input_tokens = token_usage.get("input_tokens", token_usage.get("prompt_tokens"))
            output_tokens = token_usage.get(
                "output_tokens",
                token_usage.get("completion_tokens"),
            )
            return ModelCallUsage(
                input_tokens=self._int_or_none(input_tokens),
                output_tokens=self._int_or_none(output_tokens),
                total_tokens=self._int_or_none(token_usage.get("total_tokens")),
            )
        return ModelCallUsage()

    def _native_reasoning_ref(self, ai_message: AIMessage | None) -> str | None:
        if ai_message is None or not self.provider_config.supports_native_reasoning:
            return None
        reasoning = (
            ai_message.additional_kwargs.get("reasoning")
            or ai_message.additional_kwargs.get("reasoning_content")
            or ai_message.response_metadata.get("reasoning")
            or ai_message.response_metadata.get("reasoning_content")
        )
        if not isinstance(reasoning, str) or reasoning == "":
            return None
        digest = sha256(reasoning.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _result(
        self,
        *,
        model_call_type: ModelCallType,
        trace_context: TraceContext,
        input_summary: JsonObject,
        output_summary: JsonObject,
        structured_output: JsonObject | None = None,
        structured_output_candidates: tuple[JsonObject, ...] = (),
        tool_call_requests: tuple[ModelCallToolRequest, ...] = (),
        invalid_tool_call_candidates: tuple[JsonObject, ...] = (),
        provider_error_code: ErrorCode | None = None,
        provider_error_message: str | None = None,
        usage: ModelCallUsage | None = None,
        raw_response_ref: str | None = None,
        native_reasoning_ref: str | None = None,
        provider_retry_trace: tuple[ProviderRetryTraceRecord, ...] = (),
        provider_circuit_breaker_trace: tuple[ProviderCircuitBreakerTraceRecord, ...] = (),
    ) -> ModelCallResult:
        return ModelCallResult(
            provider_snapshot_id=self.provider_config.provider_snapshot_id,
            model_binding_snapshot_id=self.provider_config.model_binding_snapshot_id,
            model_call_type=model_call_type,
            structured_output=structured_output,
            structured_output_candidates=structured_output_candidates,
            tool_call_requests=tool_call_requests,
            invalid_tool_call_candidates=invalid_tool_call_candidates,
            provider_error_code=provider_error_code,
            provider_error_message=provider_error_message,
            usage=usage or ModelCallUsage(),
            raw_response_ref=raw_response_ref,
            native_reasoning_ref=native_reasoning_ref,
            provider_retry_trace=provider_retry_trace,
            provider_circuit_breaker_trace=provider_circuit_breaker_trace,
            trace_summary=ModelCallTraceSummary(
                request_id=trace_context.request_id,
                trace_id=trace_context.trace_id,
                correlation_id=trace_context.correlation_id,
                span_id=trace_context.span_id,
                parent_span_id=trace_context.parent_span_id,
                run_id=trace_context.run_id,
                stage_run_id=trace_context.stage_run_id,
                provider_snapshot_id=self.provider_config.provider_snapshot_id,
                model_binding_snapshot_id=(
                    self.provider_config.model_binding_snapshot_id
                ),
                model_call_type=model_call_type,
                input_summary=input_summary,
                output_summary=output_summary,
            ),
        )

    def _retry_trace_record(
        self,
        *,
        failure_kind: str,
        retry_attempt: int,
        max_retry_attempts: int,
        backoff_wait_seconds: float | None,
        status: str,
        error_code: ErrorCode | None,
        occurred_at: datetime,
        trace_context: TraceContext,
    ) -> ProviderRetryTraceRecord:
        trace_ref = self._trace_ref(
            "provider-retry-trace",
            status,
            retry_attempt,
            occurred_at=occurred_at,
            trace_context=trace_context,
        )
        return ProviderRetryTraceRecord(
            trace_ref=trace_ref,
            run_id=trace_context.run_id or self.provider_config.run_id,
            stage_run_id=trace_context.stage_run_id,
            provider_snapshot_id=self.provider_config.provider_snapshot_id,
            model_binding_snapshot_id=self.provider_config.model_binding_snapshot_id,
            provider_id=self.provider_config.provider_id,
            model_id=self.provider_config.model_id,
            failure_kind=failure_kind,  # type: ignore[arg-type]
            retry_attempt=retry_attempt,
            max_retry_attempts=max_retry_attempts,
            backoff_wait_seconds=backoff_wait_seconds,
            status=status,  # type: ignore[arg-type]
            error_code=error_code,
            occurred_at=occurred_at,
        )

    def _circuit_trace_record(
        self,
        *,
        state: object,
        action: str,
        occurred_at: datetime,
        trace_context: TraceContext,
    ) -> ProviderCircuitBreakerTraceRecord:
        trace_ref = self._trace_ref(
            "provider-circuit-breaker-trace",
            action,
            getattr(state, "consecutive_failures"),
            occurred_at=occurred_at,
            trace_context=trace_context,
        )
        return ProviderCircuitBreakerTraceRecord(
            trace_ref=trace_ref,
            run_id=trace_context.run_id or self.provider_config.run_id,
            stage_run_id=trace_context.stage_run_id,
            provider_snapshot_id=self.provider_config.provider_snapshot_id,
            model_binding_snapshot_id=self.provider_config.model_binding_snapshot_id,
            provider_id=self.provider_config.provider_id,
            model_id=self.provider_config.model_id,
            status=getattr(state, "status"),
            consecutive_failures=getattr(state, "consecutive_failures"),
            opened_at=getattr(state, "opened_at"),
            next_retry_at=getattr(state, "next_retry_at"),
            failure_kind=getattr(state, "last_failure_kind"),
            action=action,  # type: ignore[arg-type]
            occurred_at=occurred_at,
        )

    def _trace_ref(
        self,
        prefix: str,
        status: str,
        sequence: int,
        *,
        occurred_at: datetime,
        trace_context: TraceContext,
    ) -> str:
        self._trace_ref_sequence += 1
        source = (
            f"{self.provider_config.run_id}:"
            f"{self.provider_config.provider_snapshot_id}:"
            f"{self.provider_config.model_binding_snapshot_id}:"
            f"{trace_context.request_id}:"
            f"{trace_context.trace_id}:"
            f"{trace_context.span_id}:"
            f"{trace_context.stage_run_id}:"
            f"{occurred_at.isoformat()}:"
            f"{prefix}:{status}:{sequence}:{self._trace_ref_sequence}"
        )
        digest = sha256(source.encode("utf-8")).hexdigest()[:24]
        return f"{prefix}-{digest}"

    def _summarize_input(self, messages: Sequence[BaseMessage]) -> JsonObject:
        payload = [
            {
                "message_type": message.type,
                "content": message.content,
            }
            for message in messages
        ]
        return self._redacted_summary(payload, payload_type="model_input_messages")

    def _summarize_output(self, payload: Any) -> JsonObject:
        return self._redacted_summary(payload, payload_type="model_output")

    def _redacted_summary(self, payload: Any, *, payload_type: str) -> JsonObject:
        redacted = self.redaction_policy.summarize_payload(
            payload,
            payload_type=payload_type,
        )
        return {
            **redacted.summary,
            "excerpt": redacted.excerpt,
            "payload_size_bytes": redacted.payload_size_bytes,
            "content_hash": redacted.content_hash,
            "redaction_status": redacted.redaction_status.value,
            "redacted_payload": redacted.redacted_payload,
        }

    def _ai_message_summary_payload(self, message: AIMessage) -> JsonObject:
        return {
            "content": message.content,
            "tool_call_count": len(getattr(message, "tool_calls", ()) or ()),
            "response_metadata": self._safe_response_metadata(message),
        }

    def _safe_response_metadata(self, message: AIMessage) -> JsonObject:
        return {
            key: value
            for key, value in message.response_metadata.items()
            if key not in {"reasoning", "reasoning_content"}
        }

    def _response_summary_payload(self, response: Any) -> JsonObject:
        if isinstance(response, Mapping):
            return {
                str(key): self._summary_safe_value(value)
                for key, value in response.items()
            }
        return {
            "response_type": type(response).__name__,
        }

    def _summary_safe_value(self, value: Any) -> object:
        if isinstance(value, AIMessage):
            return self._ai_message_summary_payload(value)
        if isinstance(value, Mapping):
            return {
                str(key): self._summary_safe_value(item)
                for key, item in value.items()
                if key not in {"reasoning", "reasoning_content"}
            }
        if isinstance(value, list):
            return [self._summary_safe_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._summary_safe_value(item) for item in value]
        if isinstance(value, str | int | float | bool) or value is None:
            return value
        return {"value_type": type(value).__name__}

    def _raw_response_ref(self, response: Any) -> str:
        payload = self._summary_safe_value(response)
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: {"value_type": type(value).__name__},
        ).encode("utf-8")
        return f"sha256:{sha256(encoded).hexdigest()}"

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


__all__ = [
    "LangChainProviderAdapter",
    "LangChainProviderAdapterError",
    "ModelCallResult",
    "ModelCallToolRequest",
    "ModelCallTraceSummary",
    "ModelCallUsage",
]
