from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.context.schemas import ContextBlock, ContextEnvelope, ContextManifest
from backend.app.domain.trace_context import TraceContext
from backend.app.prompts.definitions import COMPRESSION_PROMPT_ID
from backend.app.prompts.renderer import (
    PromptRenderedMessage,
    PromptRenderRequest,
    PromptRenderer,
)
from backend.app.providers.langchain_adapter import ModelCallResult
from backend.app.schemas.prompts import ModelCallType
from backend.app.services.artifacts import ArtifactStore
from backend.app.tools.protocol import ToolBindableDescription


COMPRESSED_CONTEXT_BLOCK_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "decisions_made": {"type": "array", "items": {"type": "string"}},
        "files_observed": {"type": "array", "items": {"type": "string"}},
        "files_modified": {"type": "array", "items": {"type": "string"}},
        "failed_attempts": {"type": "array", "items": {"type": "string"}},
        "open_issues": {"type": "array", "items": {"type": "string"}},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
    "additionalProperties": False,
}


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompressedContextBlock(_StrictBaseModel):
    compressed_context_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    covered_step_range: str = Field(min_length=1)
    compression_trigger_reason: str = Field(min_length=1)
    compression_prompt_id: str = Field(min_length=1)
    compression_prompt_version: str = Field(min_length=1)
    compression_render_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_call_ref: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    decisions_made: tuple[str, ...] = ()
    files_observed: tuple[str, ...] = ()
    files_modified: tuple[str, ...] = ()
    failed_attempts: tuple[str, ...] = ()
    open_issues: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    full_trace_ref: str = Field(min_length=1)
    created_at: datetime


class ContextCompressionResult(_StrictBaseModel):
    compressed_context_block: CompressedContextBlock | None = None
    model_call_trace: dict[str, object] | None = None
    warning: str | None = None


class ProviderAdapterProtocol(Protocol):
    def invoke_structured(
        self,
        *,
        messages: Sequence[BaseMessage],
        response_schema: dict[str, object],
        model_call_type: ModelCallType,
        tool_descriptions: Sequence[ToolBindableDescription],
        trace_context: TraceContext,
        requested_max_output_tokens: int | None = None,
    ) -> ModelCallResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ContextCompressionRequest:
    envelope: ContextEnvelope
    manifest: ContextManifest
    stage_artifact_id: str
    trace_context: TraceContext
    full_trace_ref: str
    covered_step_range: str
    compression_trigger_reason: str
    provider_adapter: ProviderAdapterProtocol
    requested_max_output_tokens: int | None = None


class ContextCompressionRunner:
    def __init__(
        self,
        *,
        prompt_renderer: PromptRenderer,
        artifact_store: ArtifactStore,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._prompt_renderer = prompt_renderer
        self._artifact_store = artifact_store
        self._now = now or (lambda: datetime.now(UTC))

    def compress(
        self,
        request: ContextCompressionRequest,
    ) -> ContextCompressionResult:
        prompt_render = self._prompt_renderer.render_messages(
            PromptRenderRequest(
                session_id=request.envelope.session_id,
                run_id=request.envelope.run_id,
                stage_run_id=request.envelope.stage_run_id,
                stage_type=request.envelope.stage_type,
                model_call_type=ModelCallType.CONTEXT_COMPRESSION,
                template_snapshot_ref=request.envelope.template_snapshot_ref,
                stage_contracts={
                    request.envelope.stage_type.value: {
                        "stage_type": request.envelope.stage_type.value,
                        "stage_contract_ref": request.envelope.stage_contract_ref,
                        "allowed_tools": [],
                    }
                },
                task_objective="Compress prior model-call context.",
                specified_action="Return a compressed context block.",
                available_tools=[],
                response_schema=dict(COMPRESSED_CONTEXT_BLOCK_SCHEMA),
                output_schema_ref="schema://compressed-context-block",
                tool_schema_version=request.manifest.tool_schema_version,
                compression_source_context=_compression_source_context(
                    request.envelope
                ),
                compression_trigger_reason=request.compression_trigger_reason,
                full_trace_ref=request.full_trace_ref,
                created_at=self._now(),
            )
        )
        model_call_result = request.provider_adapter.invoke_structured(
            messages=tuple(_to_langchain_message(message) for message in prompt_render.messages),
            response_schema=dict(COMPRESSED_CONTEXT_BLOCK_SCHEMA),
            model_call_type=ModelCallType.CONTEXT_COMPRESSION,
            tool_descriptions=(),
            trace_context=request.trace_context,
            requested_max_output_tokens=request.requested_max_output_tokens,
        )
        model_call_trace = model_call_result.trace_summary.model_dump(mode="json")

        if model_call_result.provider_error_code is not None:
            self._append_model_call_trace(request, model_call_trace)
            return ContextCompressionResult(
                model_call_trace=model_call_trace,
                warning="Context compression provider call failed.",
            )
        if model_call_result.structured_output is None:
            self._append_model_call_trace(request, model_call_trace)
            return ContextCompressionResult(
                model_call_trace=model_call_trace,
                warning="Context compression structured output was unavailable.",
            )

        try:
            compressed_block = _compressed_context_block(
                request=request,
                prompt_render_hash=prompt_render.render_hash,
                prompt_id=COMPRESSION_PROMPT_ID,
                prompt_version=prompt_render.metadata.prompt_refs[0].prompt_version,
                model_call_result=model_call_result,
                structured_output=model_call_result.structured_output,
                created_at=self._now(),
            )
        except (TypeError, ValueError, ValidationError):
            self._append_model_call_trace(request, model_call_trace)
            return ContextCompressionResult(
                model_call_trace=model_call_trace,
                warning="Context compression structured output was invalid.",
            )

        self._append_process_record_list(
            request=request,
            process_key="compressed_context_block",
            process_value=compressed_block.model_dump(mode="json"),
        )
        self._append_model_call_trace(request, model_call_trace)
        return ContextCompressionResult(
            compressed_context_block=compressed_block,
            model_call_trace=model_call_trace,
        )

    def _append_model_call_trace(
        self,
        request: ContextCompressionRequest,
        model_call_trace: dict[str, object],
    ) -> None:
        self._append_process_record_list(
            request=request,
            process_key="context_compression_model_call_trace",
            process_value=model_call_trace,
        )

    def _append_process_record_list(
        self,
        *,
        request: ContextCompressionRequest,
        process_key: str,
        process_value: dict[str, object],
    ) -> None:
        existing_records = self._existing_process_record_list(
            artifact_id=request.stage_artifact_id,
            process_key=process_key,
        )
        self._artifact_store.append_process_record(
            artifact_id=request.stage_artifact_id,
            process_key=process_key,
            process_value=[*existing_records, process_value],
            trace_context=request.trace_context,
        )

    def _existing_process_record_list(
        self,
        *,
        artifact_id: str,
        process_key: str,
    ) -> tuple[dict[str, object], ...]:
        get_stage_artifact = getattr(self._artifact_store, "get_stage_artifact", None)
        if get_stage_artifact is None:
            return ()
        artifact = get_stage_artifact(artifact_id)
        process = getattr(artifact, "process", None)
        if not isinstance(process, dict):
            return ()
        existing = process.get(process_key)
        if existing is None:
            return ()
        if isinstance(existing, list | tuple):
            return tuple(
                dict(item) for item in existing if isinstance(item, dict)
            )
        if isinstance(existing, dict):
            return (dict(existing),)
        return ()


def _compressed_context_block(
    *,
    request: ContextCompressionRequest,
    prompt_render_hash: str,
    prompt_id: str,
    prompt_version: str,
    model_call_result: ModelCallResult,
    structured_output: dict[str, object],
    created_at: datetime,
) -> CompressedContextBlock:
    summary = structured_output.get("summary")
    if not isinstance(summary, str) or not summary:
        raise ValueError("compressed context summary is required")
    model_call_ref = model_call_result.raw_response_ref or _stable_model_call_ref(
        request=request,
        model_call_result=model_call_result,
    )
    return CompressedContextBlock(
        compressed_context_id=_compressed_context_id(
            request.stage_artifact_id,
            request.covered_step_range,
            prompt_render_hash,
        ),
        stage_run_id=request.envelope.stage_run_id,
        covered_step_range=request.covered_step_range,
        compression_trigger_reason=request.compression_trigger_reason,
        compression_prompt_id=prompt_id,
        compression_prompt_version=prompt_version,
        compression_render_hash=prompt_render_hash,
        model_call_ref=model_call_ref,
        summary=summary,
        decisions_made=_string_tuple(structured_output.get("decisions_made")),
        files_observed=_string_tuple(structured_output.get("files_observed")),
        files_modified=_string_tuple(structured_output.get("files_modified")),
        failed_attempts=_string_tuple(structured_output.get("failed_attempts")),
        open_issues=_string_tuple(structured_output.get("open_issues")),
        evidence_refs=_string_tuple(structured_output.get("evidence_refs")),
        full_trace_ref=request.full_trace_ref,
        created_at=created_at,
    )


def _compression_source_context(envelope: ContextEnvelope) -> str:
    blocks = (
        *envelope.input_artifact_refs,
        *envelope.context_references,
        *envelope.working_observations,
        *envelope.reasoning_trace,
        *envelope.recent_observations,
    )
    if not blocks:
        return "No non-prompt context blocks were available."
    return "\n".join(_format_context_block(block) for block in blocks)


def _format_context_block(block: ContextBlock) -> str:
    return (
        f"[{block.section.value}] {block.block_id}: {block.summary} "
        f"(ref={block.content_ref})"
    )


def _to_langchain_message(message: PromptRenderedMessage) -> BaseMessage:
    if message.role == "system":
        return SystemMessage(content=message.content)
    return HumanMessage(content=message.content)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise TypeError("compressed context list fields must be arrays")
    if not all(isinstance(item, str) for item in value):
        raise TypeError("compressed context list fields must contain strings")
    return tuple(value)


def _compressed_context_id(
    stage_artifact_id: str,
    covered_step_range: str,
    prompt_render_hash: str,
) -> str:
    digest = sha256(
        f"{stage_artifact_id}:{covered_step_range}:{prompt_render_hash}".encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return f"compressed-context-{digest}"


def _stable_model_call_ref(
    *,
    request: ContextCompressionRequest,
    model_call_result: ModelCallResult,
) -> str:
    digest = sha256(
        (
            f"{request.envelope.run_id}:{request.envelope.stage_run_id}:"
            f"{model_call_result.provider_snapshot_id}:"
            f"{model_call_result.model_binding_snapshot_id}:"
            f"{request.trace_context.span_id}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"model-call://{request.envelope.run_id}/{digest}"


__all__ = [
    "COMPRESSED_CONTEXT_BLOCK_SCHEMA",
    "CompressedContextBlock",
    "ContextCompressionRequest",
    "ContextCompressionResult",
    "ContextCompressionRunner",
    "ProviderAdapterProtocol",
]
