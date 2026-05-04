from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.context.schemas import (
    ContextBlock,
    ContextBoundaryAction,
    ContextEnvelope,
    ContextEnvelopeSection,
    ContextSourceRef,
    ContextTrustLevel,
)
from backend.app.domain.enums import (
    ProviderProtocolType,
    ProviderSource,
    StageType,
    ToolRiskLevel,
)
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.prompts import ModelCallType
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    RuntimeLimitSnapshotRead,
    SnapshotModelRuntimeCapabilities,
)
from backend.app.tools.protocol import ToolBindableDescription


NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _provider(*, context_window_tokens: int = 1000) -> ProviderSnapshot:
    return ProviderSnapshot(
        snapshot_id="provider-snapshot-run-1-openai-gpt-5",
        run_id="run-1",
        provider_id="provider-openai",
        display_name="OpenAI",
        provider_source=ProviderSource.CUSTOM,
        protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url="https://api.openai.test",
        api_key_ref="env:OPENAI_API_KEY",
        model_id="gpt-5",
        is_default_model=True,
        capabilities=SnapshotModelRuntimeCapabilities(
            model_id="gpt-5",
            context_window_tokens=context_window_tokens,
            max_output_tokens=200,
            supports_tool_calling=True,
            supports_structured_output=True,
            supports_native_reasoning=True,
        ),
        source_config_version="provider-config-v1",
        created_at=NOW,
    )


def _limits(
    *,
    compression_threshold_ratio: float = 0.75,
    bash_stdout_preview_chars: int = 24,
    tool_output_preview_chars: int = 24,
) -> RuntimeLimitSnapshotRead:
    return RuntimeLimitSnapshotRead(
        snapshot_id="runtime-limit-snapshot-run-1",
        run_id="run-1",
        agent_limits=AgentRuntimeLimits(),
        context_limits=ContextLimits(
            compression_threshold_ratio=compression_threshold_ratio,
            bash_stdout_preview_chars=bash_stdout_preview_chars,
            tool_output_preview_chars=tool_output_preview_chars,
        ),
        source_config_version="runtime-settings-v1",
        hard_limits_version="platform-hard-limits-v1",
        schema_version="runtime-limit-snapshot-v1",
        created_at=NOW,
    )


def _trace_context() -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="span-1",
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def _block(
    *,
    section: ContextEnvelopeSection,
    block_id: str,
    summary: str,
    content_ref: str,
    source_kind: str | None = None,
    trust_level: ContextTrustLevel = ContextTrustLevel.TRUSTED_REFERENCE,
    boundary_action: ContextBoundaryAction = ContextBoundaryAction.REFERENCE_ONLY,
    estimated_tokens: int | None = None,
) -> ContextBlock:
    return ContextBlock(
        block_id=block_id,
        section=section,
        trust_level=trust_level,
        boundary_action=boundary_action,
        summary=summary,
        content_ref=content_ref,
        sources=(
            ContextSourceRef(
                source_kind=source_kind or section.value,
                source_ref=content_ref,
                source_label=block_id,
            ),
        ),
        estimated_tokens=estimated_tokens,
        estimated_chars=len(summary),
    )


def _envelope(
    *,
    runtime_blocks: tuple[ContextBlock, ...] = (),
    task_blocks: tuple[ContextBlock, ...] = (),
    specified_blocks: tuple[ContextBlock, ...] = (),
    working_blocks: tuple[ContextBlock, ...] = (),
    available_tools: tuple[ToolBindableDescription, ...] = (),
    response_schema: dict[str, object] | None = None,
) -> ContextEnvelope:
    return ContextEnvelope(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.CODE_GENERATION,
        template_snapshot_ref="template-snapshot-run-1",
        stage_contract_ref="stage-contract-code-generation",
        provider_snapshot_ref="provider-snapshot-run-1-openai-gpt-5",
        model_binding_snapshot_ref="model-binding-snapshot-run-1-code-generation",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        runtime_instructions=runtime_blocks,
        stage_contract=(),
        agent_role_prompt=(),
        task_objective=task_blocks,
        specified_action=specified_blocks,
        input_artifact_refs=(),
        context_references=(),
        working_observations=working_blocks,
        reasoning_trace=(),
        available_tools=available_tools,
        recent_observations=(),
        response_schema=response_schema or {"type": "object"},
        trace_context=_trace_context(),
        built_at=NOW,
    )


def _tool(*, description: str = "Read files.") -> ToolBindableDescription:
    return ToolBindableDescription(
        name="read_file",
        description=description,
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


def test_compression_threshold_uses_snapshot_ratio_and_reserved_output_only_lowers() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    guard = ContextSizeGuard()

    assert guard.compression_trigger_tokens(
        provider_snapshot=_provider(context_window_tokens=1000),
        runtime_limit_snapshot=_limits(compression_threshold_ratio=0.75),
    ) == 750
    assert guard.compression_trigger_tokens(
        provider_snapshot=_provider(context_window_tokens=1000),
        runtime_limit_snapshot=_limits(compression_threshold_ratio=0.75),
        reserved_output_tokens=200,
    ) == 600


def test_observation_budget_truncates_large_runtime_observation_and_keeps_full_ref() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    block = _block(
        section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
        block_id="bash-output-1",
        summary="x" * 80,
        content_ref="artifact://bash/stdout/full",
        source_kind="bash_stdout",
        trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
    )

    result = ContextSizeGuard().apply_observation_budget(
        blocks=(block,),
        runtime_limit_snapshot=_limits(bash_stdout_preview_chars=16),
        built_at=NOW,
    )

    budgeted = result.blocks[0]
    assert budgeted.truncated is True
    assert budgeted.boundary_action is ContextBoundaryAction.TRUNCATE
    assert budgeted.content_ref == "artifact://bash/stdout/full"
    assert "full_ref=artifact://bash/stdout/full" in budgeted.summary
    assert "x" * 40 not in budgeted.summary
    assert result.warnings[0].warning_code == "observation_truncated"


def test_sliding_window_indexes_older_process_refs_and_keeps_recent_blocks() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    blocks = tuple(
        _block(
            section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
            block_id=f"process-{index}",
            summary=f"Process observation {index}",
            content_ref=f"artifact://process/run-1/{index}",
        )
        for index in range(1, 6)
    )

    result = ContextSizeGuard().apply_sliding_window(
        blocks=blocks,
        max_recent_blocks=2,
        stage_run_id="stage-run-1",
        built_at=NOW,
    )

    assert [block.block_id for block in result.blocks] == [
        "context-index:stage-run-1:working_observations:1-3",
        "process-4",
        "process-5",
    ]
    index_block = result.blocks[0]
    assert index_block.boundary_action is ContextBoundaryAction.REFERENCE_ONLY
    assert index_block.content_ref.startswith("context-index://stage-run-1/")
    assert "artifact://process/run-1/1" in index_block.summary
    assert result.warnings[0].warning_code == "working_window_indexed"


def test_sliding_window_index_ref_is_stable_across_build_times() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    blocks = tuple(
        _block(
            section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
            block_id=f"process-{index}",
            summary=f"Process observation {index}",
            content_ref=f"artifact://process/run-1/{index}",
        )
        for index in range(1, 5)
    )
    guard = ContextSizeGuard()

    first = guard.apply_sliding_window(
        blocks=blocks,
        max_recent_blocks=1,
        stage_run_id="stage-run-1",
        built_at=NOW,
    )
    second = guard.apply_sliding_window(
        blocks=blocks,
        max_recent_blocks=1,
        stage_run_id="stage-run-1",
        built_at=NOW + timedelta(minutes=5),
    )

    assert first.blocks[0].content_ref == second.blocks[0].content_ref
    assert first.blocks[0].summary == second.blocks[0].summary


def test_model_window_decision_requires_compression_when_total_reaches_threshold() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    envelope = _envelope(
        task_blocks=(
            _block(
                section=ContextEnvelopeSection.TASK_OBJECTIVE,
                block_id="task-objective",
                summary="Generate code.",
                content_ref="stage-task-objective://stage-run-1",
                estimated_tokens=100,
            ),
        ),
        working_blocks=(
            _block(
                section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
                block_id="large-working-context",
                summary="Large context.",
                content_ref="artifact://process/run-1/large",
                estimated_tokens=650,
            ),
        ),
    )

    decision = ContextSizeGuard().ensure_within_model_window(
        envelope=envelope,
        provider_snapshot=_provider(context_window_tokens=1000),
        runtime_limit_snapshot=_limits(compression_threshold_ratio=0.75),
    )

    assert decision.total_estimated_tokens == 755
    assert decision.compression_trigger_tokens == 750
    assert decision.requires_compression is True
    assert decision.warnings[0].warning_code == "compression_required"


def test_specified_action_tokens_are_pinned_and_can_overflow() -> None:
    from backend.app.context.size_guard import ContextOverflowError, ContextSizeGuard

    envelope = _envelope(
        specified_blocks=(
            _block(
                section=ContextEnvelopeSection.SPECIFIED_ACTION,
                block_id="specified-action",
                summary="Pinned specified action.",
                content_ref="stage-specified-action://stage-run-1",
                boundary_action=ContextBoundaryAction.ALLOW,
                estimated_tokens=800,
            ),
        )
    )

    with pytest.raises(ContextOverflowError, match="Pinned context exceeds"):
        ContextSizeGuard().ensure_within_model_window(
            envelope=envelope,
            provider_snapshot=_provider(context_window_tokens=1000),
            runtime_limit_snapshot=_limits(compression_threshold_ratio=0.75),
        )


def test_pinned_context_overflow_raises_safe_error() -> None:
    from backend.app.context.size_guard import ContextOverflowError, ContextSizeGuard

    envelope = _envelope(
        runtime_blocks=(
            _block(
                section=ContextEnvelopeSection.RUNTIME_INSTRUCTIONS,
                block_id="runtime-instructions",
                summary="Pinned runtime prompt.",
                content_ref="artifact://prompt/runtime",
                source_kind="prompt_asset",
                trust_level=ContextTrustLevel.SYSTEM_TRUSTED,
                boundary_action=ContextBoundaryAction.ALLOW,
                estimated_tokens=800,
            ),
        )
    )

    with pytest.raises(ContextOverflowError, match="Pinned context exceeds") as exc_info:
        ContextSizeGuard().ensure_within_model_window(
            envelope=envelope,
            provider_snapshot=_provider(context_window_tokens=1000),
            runtime_limit_snapshot=_limits(compression_threshold_ratio=0.75),
        )

    assert exc_info.value.reason == "pinned_context_overflow"
    assert exc_info.value.total_estimated_tokens == 805
    assert exc_info.value.compression_trigger_tokens == 750


def test_token_estimator_uses_summary_when_provided_estimate_is_too_low() -> None:
    from backend.app.context.size_guard import ContextTokenEstimator

    block = _block(
        section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
        block_id="underestimated",
        summary="x" * 100,
        content_ref="artifact://process/run-1/underestimated",
        estimated_tokens=1,
    )

    assert ContextTokenEstimator().estimate_block(block) == 25


def test_compression_trigger_never_drops_below_one_token() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    assert (
        ContextSizeGuard().compression_trigger_tokens(
            provider_snapshot=_provider(context_window_tokens=10),
            runtime_limit_snapshot=_limits(compression_threshold_ratio=0.5),
            reserved_output_tokens=100,
        )
        == 1
    )


def test_response_schema_tokens_are_pinned_and_can_overflow() -> None:
    from backend.app.context.size_guard import ContextOverflowError, ContextSizeGuard

    envelope = _envelope(
        response_schema={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "string",
                    "description": "x" * 1000,
                }
            },
            "required": ["payload"],
            "additionalProperties": False,
        }
    )

    with pytest.raises(ContextOverflowError, match="Pinned context exceeds") as exc_info:
        ContextSizeGuard().ensure_within_model_window(
            envelope=envelope,
            provider_snapshot=_provider(context_window_tokens=400),
            runtime_limit_snapshot=_limits(compression_threshold_ratio=0.5),
        )

    assert exc_info.value.reason == "pinned_context_overflow"


def test_available_tool_schema_tokens_can_trigger_compression_decision() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    guard = ContextSizeGuard()
    working_block = _block(
        section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
        block_id="working-context",
        summary="Working context.",
        content_ref="artifact://process/run-1/working",
        estimated_tokens=490,
    )
    provider = _provider(context_window_tokens=1000)
    limits = _limits(compression_threshold_ratio=0.5)

    without_tool = guard.ensure_within_model_window(
        envelope=_envelope(working_blocks=(working_block,)),
        provider_snapshot=provider,
        runtime_limit_snapshot=limits,
    )
    with_tool = guard.ensure_within_model_window(
        envelope=_envelope(
            working_blocks=(working_block,),
            available_tools=(
                _tool(description="Read a file and return bounded content references."),
            ),
        ),
        provider_snapshot=provider,
        runtime_limit_snapshot=limits,
    )

    assert without_tool.requires_compression is False
    assert with_tool.requires_compression is True


def test_observation_budget_truncates_additional_large_source_kinds() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    blocks = tuple(
        _block(
            section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
            block_id=f"{source_kind}-1",
            summary="y" * 80,
            content_ref=f"artifact://{source_kind}/full",
            source_kind=source_kind,
            trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
        )
        for source_kind in ("grep_result", "diff", "tool_error")
    )

    result = ContextSizeGuard().apply_observation_budget(
        blocks=blocks,
        runtime_limit_snapshot=_limits(tool_output_preview_chars=16),
        built_at=NOW,
    )

    assert [block.truncated for block in result.blocks] == [True, True, True]
    assert all(block.content_ref.endswith("/full") for block in result.blocks)
    assert all("full_ref=artifact://" in block.summary for block in result.blocks)
    assert len(result.warnings) == 3


def test_sliding_window_rejects_mixed_section_input() -> None:
    from backend.app.context.size_guard import ContextSizeGuard

    blocks = (
        _block(
            section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
            block_id="working-1",
            summary="Working observation.",
            content_ref="artifact://process/run-1/working-1",
        ),
        _block(
            section=ContextEnvelopeSection.REASONING_TRACE,
            block_id="reasoning-1",
            summary="Reasoning trace.",
            content_ref="artifact://process/run-1/reasoning-1",
        ),
    )

    with pytest.raises(ValueError, match="same context section"):
        ContextSizeGuard().apply_sliding_window(
            blocks=blocks,
            max_recent_blocks=1,
            stage_run_id="stage-run-1",
            built_at=NOW,
        )
