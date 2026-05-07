from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
from typing import Any, Protocol


JsonObject = dict[str, Any]
TraceContextManagerFactory = Callable[..., Any]

_RUN_STACK: ContextVar[tuple[Any, ...]] = ContextVar(
    "ai_devflow_langsmith_run_stack",
    default=(),
)
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|bearer|content|password|secret|token)",
    re.IGNORECASE,
)


class RuntimeTracer(Protocol):
    def trace_stage(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        stage_type: str,
        graph_node_key: str,
    ) -> Any: ...

    def trace_iteration(
        self,
        *,
        iteration_index: int,
        model_call_type: str,
        tool_result_count: int,
    ) -> Any: ...

    def trace_tool_call(
        self,
        *,
        tool_name: str,
        call_id: str,
        input_payload: Mapping[str, Any],
    ) -> Any: ...

    def record_model_decision(
        self,
        *,
        decision_type: str | None,
        status: str,
        trace_ref: str,
        model_call_ref: str,
        reason: str | None = None,
    ) -> None: ...

    def record_tool_result(
        self,
        *,
        tool_name: str,
        call_id: str,
        status: str,
        artifact_refs: Sequence[str],
        side_effect_refs: Sequence[str],
        error_code: str | None,
        safe_details: Mapping[str, Any],
    ) -> None: ...

    def record_stage_result(
        self,
        *,
        status: str,
        artifact_type: str | None = None,
        artifact_refs: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
    ) -> None: ...

    def record_stage_failure(
        self,
        *,
        reason: str,
        safe_details: Mapping[str, Any],
    ) -> None: ...


class NoopRuntimeTracer:
    @contextmanager
    def trace_stage(self, **kwargs: Any) -> Iterator[None]:
        del kwargs
        yield

    @contextmanager
    def trace_iteration(self, **kwargs: Any) -> Iterator[None]:
        del kwargs
        yield

    @contextmanager
    def trace_tool_call(self, **kwargs: Any) -> Iterator[None]:
        del kwargs
        yield

    def record_model_decision(self, **kwargs: Any) -> None:
        del kwargs

    def record_tool_result(self, **kwargs: Any) -> None:
        del kwargs

    def record_stage_result(self, **kwargs: Any) -> None:
        del kwargs

    def record_stage_failure(self, **kwargs: Any) -> None:
        del kwargs


class LangSmithRuntimeTracer:
    def __init__(
        self,
        *,
        trace_factory: TraceContextManagerFactory | None = None,
        tracing_enabled: Callable[[], bool | str] | None = None,
    ) -> None:
        self._trace_factory = trace_factory or _default_trace_factory
        self._tracing_enabled = tracing_enabled or _default_tracing_enabled

    @contextmanager
    def trace_stage(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        stage_type: str,
        graph_node_key: str,
    ) -> Iterator[None]:
        with self._span(
            name=f"stage_agent.{stage_type}",
            run_type="chain",
            inputs={
                "run_id": run_id,
                "stage_run_id": stage_run_id,
                "stage_type": stage_type,
                "graph_node_key": graph_node_key,
            },
            metadata={
                "run_id": run_id,
                "stage_run_id": stage_run_id,
                "stage_type": stage_type,
                "graph_node_key": graph_node_key,
            },
            tags=["runtime", "stage-agent", stage_type],
        ):
            yield

    @contextmanager
    def trace_iteration(
        self,
        *,
        iteration_index: int,
        model_call_type: str,
        tool_result_count: int,
    ) -> Iterator[None]:
        with self._span(
            name=f"stage_agent.iteration.{iteration_index}",
            run_type="chain",
            inputs={
                "iteration_index": iteration_index,
                "model_call_type": model_call_type,
                "tool_result_count": tool_result_count,
            },
            metadata={
                "iteration_index": iteration_index,
                "model_call_type": model_call_type,
                "tool_result_count": tool_result_count,
            },
            tags=["runtime", "stage-agent", "iteration"],
        ):
            yield

    @contextmanager
    def trace_tool_call(
        self,
        *,
        tool_name: str,
        call_id: str,
        input_payload: Mapping[str, Any],
    ) -> Iterator[None]:
        with self._span(
            name=f"stage_agent.tool.{tool_name}",
            run_type="tool",
            inputs={
                "tool_name": tool_name,
                "call_id": call_id,
                "input_payload_summary": _safe_input_payload_summary(input_payload),
            },
            metadata={
                "tool_name": tool_name,
                "call_id": call_id,
            },
            tags=["runtime", "stage-agent", "tool", tool_name],
        ):
            yield

    def record_model_decision(
        self,
        *,
        decision_type: str | None,
        status: str,
        trace_ref: str,
        model_call_ref: str,
        reason: str | None = None,
    ) -> None:
        self._add_outputs(
            {
                "decision_type": decision_type,
                "decision_status": status,
                "decision_trace_ref": trace_ref,
                "model_call_ref": model_call_ref,
                "reason": _bounded_string(reason) if reason else None,
            }
        )

    def record_tool_result(
        self,
        *,
        tool_name: str,
        call_id: str,
        status: str,
        artifact_refs: Sequence[str],
        side_effect_refs: Sequence[str],
        error_code: str | None,
        safe_details: Mapping[str, Any],
    ) -> None:
        self._add_outputs(
            {
                "tool_name": tool_name,
                "call_id": call_id,
                "status": status,
                "artifact_refs": list(artifact_refs),
                "side_effect_refs": list(side_effect_refs),
                "error_code": error_code,
                "safe_details": _safe_mapping_summary(safe_details),
            }
        )

    def record_stage_result(
        self,
        *,
        status: str,
        artifact_type: str | None = None,
        artifact_refs: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
    ) -> None:
        self._add_outputs(
            {
                "stage_status": status,
                "artifact_type": artifact_type,
                "artifact_refs": list(artifact_refs),
                "evidence_refs": list(evidence_refs),
            }
        )

    def record_stage_failure(
        self,
        *,
        reason: str,
        safe_details: Mapping[str, Any],
    ) -> None:
        self._add_outputs(
            {
                "stage_status": "failed",
                "failure_reason": _bounded_string(reason),
                "safe_details": _safe_mapping_summary(safe_details),
            }
        )

    @contextmanager
    def _span(
        self,
        *,
        name: str,
        run_type: str,
        inputs: JsonObject,
        metadata: JsonObject,
        tags: Sequence[str],
    ) -> Iterator[None]:
        if not self._is_enabled():
            yield
            return

        parent = _current_parent()
        try:
            manager = self._trace_factory(
                name=name,
                run_type=run_type,
                inputs=inputs,
                metadata=metadata,
                tags=list(tags),
                parent=parent,
            )
            run = manager.__enter__()
        except Exception:
            yield
            return

        stack = _RUN_STACK.get()
        token = _RUN_STACK.set((*stack, run))
        try:
            yield
        except BaseException as exc:
            _RUN_STACK.reset(token)
            try:
                manager.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:
                pass
            raise
        else:
            _RUN_STACK.reset(token)
            try:
                manager.__exit__(None, None, None)
            except Exception:
                pass

    def _add_outputs(self, outputs: JsonObject) -> None:
        stack = _RUN_STACK.get()
        if not stack:
            return
        run = stack[-1]
        clean_outputs = {key: value for key, value in outputs.items() if value is not None}
        try:
            run.add_outputs(clean_outputs)
        except Exception:
            pass

    def _is_enabled(self) -> bool:
        try:
            return bool(self._tracing_enabled())
        except Exception:
            return False


def _default_trace_factory(**kwargs: Any) -> Any:
    from langsmith import trace

    return trace(**kwargs)


def _default_tracing_enabled() -> bool | str:
    from langsmith.utils import tracing_is_enabled

    return tracing_is_enabled()


def _current_parent() -> object:
    stack = _RUN_STACK.get()
    if stack:
        return stack[-1]
    return "ignore"


def _safe_input_payload_summary(payload: Mapping[str, Any]) -> JsonObject:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    summary: JsonObject = {
        "input_keys": sorted(str(key) for key in payload),
        "payload_size_bytes": len(encoded.encode("utf-8")),
        "redaction_status": "summary_only",
    }
    for key in (
        "path",
        "pattern",
        "glob",
        "query",
        "command",
        "argv",
        "cwd",
        "old_path",
        "new_path",
    ):
        if key not in payload:
            continue
        value = payload[key]
        if _is_sensitive_key(key):
            continue
        if isinstance(value, str):
            summary[key] = _redact_inline_secrets(_bounded_string(value, limit=500))
        elif isinstance(value, list | tuple):
            summary[key] = [
                _redact_inline_secrets(_bounded_string(str(item), limit=200))
                for item in value[:20]
            ]
        else:
            summary[key] = value
    return summary


def _safe_mapping_summary(payload: Mapping[str, Any]) -> JsonObject:
    summary: JsonObject = {}
    for key, value in payload.items():
        key_text = str(key)
        if _is_sensitive_key(key_text):
            summary[key_text] = "[redacted]"
            continue
        if isinstance(value, str):
            summary[key_text] = _redact_inline_secrets(_bounded_string(value))
        elif isinstance(value, int | float | bool) or value is None:
            summary[key_text] = value
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            summary[key_text] = [
                _bounded_string(str(item), limit=120) for item in value[:20]
            ]
        else:
            summary[key_text] = _bounded_string(str(value), limit=200)
    return summary


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_PATTERN.search(key))


def _redact_inline_secrets(value: str) -> str:
    value = re.sub(
        r"(?i)(api[_-]?key|token|password|secret)=([^\s]+)",
        r"\1=[redacted]",
        value,
    )
    value = re.sub(r"(?i)(bearer)\s+[a-z0-9._~+/=-]+", r"\1 [redacted]", value)
    return value


def _bounded_string(value: str | None, *, limit: int = 300) -> str:
    if value is None:
        return ""
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


__all__ = [
    "LangSmithRuntimeTracer",
    "NoopRuntimeTracer",
    "RuntimeTracer",
]
