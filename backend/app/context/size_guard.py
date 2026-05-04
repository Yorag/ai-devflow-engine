from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from math import floor
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from backend.app.context.schemas import (
    ContextBlock,
    ContextBoundaryAction,
    ContextEnvelope,
    ContextEnvelopeSection,
    ContextSourceRef,
    ContextTrustLevel,
)
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.schemas.runtime_settings import RuntimeLimitSnapshotRead


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextOverflowError(RuntimeError):
    def __init__(
        self,
        safe_message: str,
        *,
        reason: str,
        total_estimated_tokens: int,
        compression_trigger_tokens: int,
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.reason = reason
        self.total_estimated_tokens = total_estimated_tokens
        self.compression_trigger_tokens = compression_trigger_tokens


class ContextSizeWarning(_StrictBaseModel):
    warning_code: Literal[
        "observation_truncated",
        "working_window_indexed",
        "compression_required",
        "pinned_context_overflow",
    ]
    block_id: str | None = None
    source_ref: str | None = None
    safe_message: str


class ContextSizeDecision(_StrictBaseModel):
    total_estimated_tokens: int
    pinned_estimated_tokens: int
    compression_trigger_tokens: int
    context_window_tokens: int
    reserved_output_tokens: int
    requires_compression: bool
    warnings: tuple[ContextSizeWarning, ...] = ()


class ObservationBudgetResult(_StrictBaseModel):
    blocks: tuple[ContextBlock, ...]
    warnings: tuple[ContextSizeWarning, ...] = ()


class SlidingWindowResult(_StrictBaseModel):
    blocks: tuple[ContextBlock, ...]
    warnings: tuple[ContextSizeWarning, ...] = ()


class ContextTokenEstimator:
    def estimate_text(self, text: str) -> int:
        return max(1, (len(text) + 3) // 4) if text else 0

    def estimate_block(self, block: ContextBlock) -> int:
        summary_tokens = self.estimate_text(block.summary)
        if block.estimated_tokens is not None:
            return max(block.estimated_tokens, summary_tokens)
        return summary_tokens

    def estimate_blocks(self, blocks: Sequence[ContextBlock]) -> int:
        return sum(self.estimate_block(block) for block in blocks)

    def estimate_envelope(self, envelope: ContextEnvelope) -> int:
        return (
            self.estimate_blocks(_all_blocks(envelope))
            + self.estimate_response_schema(envelope)
            + self.estimate_available_tools(envelope)
        )

    def estimate_response_schema(self, envelope: ContextEnvelope) -> int:
        return self.estimate_text(_stable_json(envelope.response_schema))

    def estimate_available_tools(self, envelope: ContextEnvelope) -> int:
        return sum(
            self.estimate_text(_stable_json(tool.model_dump(mode="json")))
            for tool in envelope.available_tools
        )


class ContextSizeGuard:
    def __init__(
        self,
        *,
        token_estimator: ContextTokenEstimator | None = None,
    ) -> None:
        self._token_estimator = token_estimator or ContextTokenEstimator()

    def compression_trigger_tokens(
        self,
        *,
        provider_snapshot: ProviderSnapshot,
        runtime_limit_snapshot: RuntimeLimitSnapshotRead,
        reserved_output_tokens: int = 0,
    ) -> int:
        context_window_tokens = provider_snapshot.capabilities.context_window_tokens
        ratio = runtime_limit_snapshot.context_limits.compression_threshold_ratio
        base_threshold = max(1, floor(context_window_tokens * ratio))
        if reserved_output_tokens <= 0:
            return base_threshold
        conservative_threshold = max(
            1,
            floor(max(1, context_window_tokens - reserved_output_tokens) * ratio),
        )
        return min(base_threshold, conservative_threshold)

    def apply_observation_budget(
        self,
        *,
        blocks: Sequence[ContextBlock],
        runtime_limit_snapshot: RuntimeLimitSnapshotRead,
        built_at: datetime,
    ) -> ObservationBudgetResult:
        del built_at
        warnings: list[ContextSizeWarning] = []
        budgeted: list[ContextBlock] = []
        for block in blocks:
            limit = _preview_limit_for_block(
                block,
                runtime_limit_snapshot=runtime_limit_snapshot,
            )
            if limit is None or len(block.summary) <= limit:
                budgeted.append(block)
                continue
            omitted_chars = len(block.summary) - limit
            summary = (
                f"{block.summary[:limit]}... "
                f"[truncated: {omitted_chars} chars omitted; "
                f"full_ref={block.content_ref}]"
            )
            budgeted.append(
                block.model_copy(
                    update={
                        "summary": summary,
                        "boundary_action": ContextBoundaryAction.TRUNCATE,
                        "truncated": True,
                        "estimated_chars": len(summary),
                        "estimated_tokens": self._token_estimator.estimate_text(
                            summary
                        ),
                    }
                )
            )
            warnings.append(
                ContextSizeWarning(
                    warning_code="observation_truncated",
                    block_id=block.block_id,
                    source_ref=block.content_ref,
                    safe_message=(
                        "Observation exceeded the model-visible preview budget; "
                        "a stable full_ref was preserved."
                    ),
                )
            )
        return ObservationBudgetResult(blocks=tuple(budgeted), warnings=tuple(warnings))

    def apply_sliding_window(
        self,
        *,
        blocks: Sequence[ContextBlock],
        max_recent_blocks: int,
        stage_run_id: str,
        built_at: datetime,
    ) -> SlidingWindowResult:
        sections = {block.section for block in blocks}
        if len(sections) > 1:
            raise ValueError("apply_sliding_window blocks must share the same context section")
        if max_recent_blocks <= 0 or len(blocks) <= max_recent_blocks:
            return SlidingWindowResult(blocks=tuple(blocks))
        del built_at

        older = tuple(blocks[:-max_recent_blocks])
        recent = tuple(blocks[-max_recent_blocks:])
        section = older[0].section
        index_block = _index_block(
            older,
            section=section,
            stage_run_id=stage_run_id,
        )
        warning = ContextSizeWarning(
            warning_code="working_window_indexed",
            block_id=index_block.block_id,
            source_ref=index_block.content_ref,
            safe_message=(
                "Older working observations were replaced with a bounded "
                "reference index; original records remain available by ref."
            ),
        )
        return SlidingWindowResult(
            blocks=(index_block, *recent),
            warnings=(warning,),
        )

    def ensure_within_model_window(
        self,
        *,
        envelope: ContextEnvelope,
        provider_snapshot: ProviderSnapshot,
        runtime_limit_snapshot: RuntimeLimitSnapshotRead,
        reserved_output_tokens: int = 0,
    ) -> ContextSizeDecision:
        trigger_tokens = self.compression_trigger_tokens(
            provider_snapshot=provider_snapshot,
            runtime_limit_snapshot=runtime_limit_snapshot,
            reserved_output_tokens=reserved_output_tokens,
        )
        all_blocks = _all_blocks(envelope)
        response_schema_tokens = self._token_estimator.estimate_response_schema(envelope)
        available_tool_tokens = self._token_estimator.estimate_available_tools(envelope)
        total_tokens = (
            self._token_estimator.estimate_blocks(all_blocks)
            + response_schema_tokens
            + available_tool_tokens
        )
        pinned_tokens = (
            self._token_estimator.estimate_blocks(_pinned_blocks(envelope))
            + response_schema_tokens
            + available_tool_tokens
        )
        if pinned_tokens > trigger_tokens:
            raise ContextOverflowError(
                "Pinned context exceeds the compression trigger threshold.",
                reason="pinned_context_overflow",
                total_estimated_tokens=pinned_tokens,
                compression_trigger_tokens=trigger_tokens,
            )

        warnings: tuple[ContextSizeWarning, ...] = ()
        requires_compression = total_tokens >= trigger_tokens
        if requires_compression:
            warnings = (
                ContextSizeWarning(
                    warning_code="compression_required",
                    safe_message=(
                        "Estimated context reaches the compression trigger threshold."
                    ),
                ),
            )
        return ContextSizeDecision(
            total_estimated_tokens=total_tokens,
            pinned_estimated_tokens=pinned_tokens,
            compression_trigger_tokens=trigger_tokens,
            context_window_tokens=provider_snapshot.capabilities.context_window_tokens,
            reserved_output_tokens=max(0, reserved_output_tokens),
            requires_compression=requires_compression,
            warnings=warnings,
        )


def _all_blocks(envelope: ContextEnvelope) -> tuple[ContextBlock, ...]:
    return (
        *envelope.runtime_instructions,
        *envelope.stage_contract,
        *envelope.agent_role_prompt,
        *envelope.task_objective,
        *envelope.specified_action,
        *envelope.input_artifact_refs,
        *envelope.context_references,
        *envelope.working_observations,
        *envelope.reasoning_trace,
        *envelope.recent_observations,
    )


def _pinned_blocks(envelope: ContextEnvelope) -> tuple[ContextBlock, ...]:
    return (
        *envelope.runtime_instructions,
        *envelope.stage_contract,
        *envelope.agent_role_prompt,
        *envelope.task_objective,
        *envelope.specified_action,
        *envelope.input_artifact_refs,
    )


def _preview_limit_for_block(
    block: ContextBlock,
    *,
    runtime_limit_snapshot: RuntimeLimitSnapshotRead,
) -> int | None:
    source_kinds = {source.source_kind for source in block.sources}
    limits = runtime_limit_snapshot.context_limits
    if "bash_stdout" in source_kinds:
        return limits.bash_stdout_preview_chars
    if "bash_stderr" in source_kinds:
        return limits.bash_stderr_preview_chars
    if source_kinds.intersection(
        {
            "diff",
            "grep_result",
            "remote_delivery_result",
            "test_output",
            "tool_error",
            "tool_output",
        }
    ):
        return limits.tool_output_preview_chars
    if "file_read" in source_kinds:
        return limits.file_read_max_chars
    if "model_output" in source_kinds:
        return limits.model_output_process_preview_chars
    return None


def _index_block(
    older: tuple[ContextBlock, ...],
    *,
    section: ContextEnvelopeSection,
    stage_run_id: str,
) -> ContextBlock:
    first_index = 1
    last_index = len(older)
    block_id = (
        f"context-index:{stage_run_id}:{section.value}:{first_index}-{last_index}"
    )
    refs = tuple(block.content_ref for block in older)
    digest = sha256(
        "|".join((stage_run_id, section.value, *refs)).encode("utf-8")
    ).hexdigest()[:16]
    bounded_refs = ", ".join(refs[:8])
    if len(refs) > 8:
        bounded_refs = f"{bounded_refs}, ... (+{len(refs) - 8} more)"
    summary = (
        f"Indexed older {section.value} blocks {first_index}-{last_index}; "
        f"refs={bounded_refs}."
    )
    return ContextBlock(
        block_id=block_id,
        section=section,
        trust_level=_least_trusted_level(older),
        boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
        summary=summary,
        content_ref=f"context-index://{stage_run_id}/{section.value}/{digest}",
        sources=tuple(
            ContextSourceRef(
                source_kind="context_index_source",
                source_ref=block.content_ref,
                source_label=block.block_id,
            )
            for block in older
        ),
        estimated_chars=len(summary),
    )


def _least_trusted_level(blocks: Sequence[ContextBlock]) -> ContextTrustLevel:
    if any(block.trust_level is ContextTrustLevel.UNTRUSTED_OBSERVATION for block in blocks):
        return ContextTrustLevel.UNTRUSTED_OBSERVATION
    if any(block.trust_level is ContextTrustLevel.TRUSTED_REFERENCE for block in blocks):
        return ContextTrustLevel.TRUSTED_REFERENCE
    return blocks[0].trust_level


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ContextOverflowError",
    "ContextSizeDecision",
    "ContextSizeGuard",
    "ContextSizeWarning",
    "ContextTokenEstimator",
    "ObservationBudgetResult",
    "SlidingWindowResult",
]
