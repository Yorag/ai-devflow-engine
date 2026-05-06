from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor
from typing import Any, Callable, Sequence

from backend.app.context.compression import (
    CompressedContextBlock,
    ContextCompressionRequest,
    ContextCompressionRunner,
)
from backend.app.context.schemas import (
    ContextBlock,
    ContextBoundaryAction,
    ContextEnvelope,
    ContextEnvelopeSection,
    ContextManifest,
    ContextSourceRef,
    ContextTrustLevel,
    PromptSectionRef,
    RenderedOutputKind,
)
from backend.app.context.source_resolver import ContextSourceResolver
from backend.app.context.size_guard import ContextOverflowError, ContextSizeGuard
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ClarificationRecordModel,
    StageArtifactModel,
)
from backend.app.domain.changes import ChangeSet, ContextReference
from backend.app.domain.enums import StageType
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.provider_snapshot import ProviderSnapshot
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.prompts.renderer import (
    PromptRenderedMessage,
    PromptRenderedSection,
    PromptRenderRequest,
    PromptRenderResult,
    PromptRenderer,
)
from backend.app.schemas.prompts import ModelCallType
from backend.app.schemas.runtime_settings import (
    ModelBindingSnapshotRead,
    RuntimeLimitSnapshotRead,
)
from backend.app.services.artifacts import ArtifactStore
from backend.app.tools.registry import ToolRegistry
from backend.app.tools.protocol import ToolBindableDescription


@dataclass(frozen=True, slots=True)
class ContextBuildRequest:
    session_id: str
    run_id: str
    stage_run_id: str
    stage_artifact_id: str
    stage_type: StageType
    stage_contract_ref: str
    model_call_type: ModelCallType
    task_objective: str
    specified_action: str
    response_schema: dict[str, object]
    output_schema_ref: str
    tool_schema_version: str
    template_version: str
    trace_context: TraceContext
    template_snapshot: TemplateSnapshot
    graph_definition: GraphDefinition
    runtime_limit_snapshot: RuntimeLimitSnapshotRead
    provider_snapshot: ProviderSnapshot
    model_binding_snapshot: ModelBindingSnapshotRead
    parse_error: str | None = None
    stage_artifacts: tuple[StageArtifactModel, ...] = ()
    context_references: tuple[ContextReference, ...] = ()
    change_sets: tuple[ChangeSet, ...] = ()
    clarifications: tuple[ClarificationRecordModel, ...] = ()
    approval_decisions: tuple[ApprovalDecisionModel, ...] = ()
    allowed_context_run_ids: tuple[str, ...] = ()
    reserved_output_tokens: int = 0
    max_recent_observation_blocks: int | None = None
    full_trace_ref: str | None = None
    compression_covered_step_range: str | None = None
    provider_adapter: Any | None = None


@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    envelope: ContextEnvelope
    manifest: ContextManifest
    rendered_messages: tuple[PromptRenderedMessage, ...]
    rendered_output_ref: str
    render_hash: str
    prompt_render_result: PromptRenderResult


class ContextEnvelopeBuilder:
    def __init__(
        self,
        *,
        prompt_renderer: PromptRenderer,
        tool_registry: ToolRegistry,
        artifact_store: ArtifactStore,
        source_resolver: ContextSourceResolver | None = None,
        context_size_guard: ContextSizeGuard | None = None,
        compression_runner: ContextCompressionRunner | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._prompt_renderer = prompt_renderer
        self._tool_registry = tool_registry
        self._artifact_store = artifact_store
        self._source_resolver = source_resolver or ContextSourceResolver()
        self._context_size_guard = context_size_guard
        self._compression_runner = compression_runner
        self._now = now or (lambda: datetime.now(UTC))

    def build_for_stage_call(self, request: ContextBuildRequest) -> ContextBuildResult:
        self._validate_request(request)
        built_at = self._now()
        allowed_context_run_ids = request.allowed_context_run_ids or (request.run_id,)
        stage_contract = request.graph_definition.stage_contracts[
            request.stage_type.value
        ]
        contract_ref = self._stage_contract_ref(
            stage_contract=stage_contract,
            fallback=request.stage_contract_ref,
        )
        stage_role = self._stage_role_binding(request)
        available_tools = self._available_tools(stage_contract)

        stage_inputs = self._source_resolver.resolve_stage_inputs(
            session_id=request.session_id,
            run_id=request.run_id,
            stage_run_id=request.stage_run_id,
            stage_type=request.stage_type,
            stage_artifacts=request.stage_artifacts,
            allowed_context_run_ids=allowed_context_run_ids,
            built_at=built_at,
        )
        resolved_sources = self._source_resolver.resolve_context_references(
            session_id=request.session_id,
            run_id=request.run_id,
            stage_run_id=request.stage_run_id,
            stage_type=request.stage_type,
            stage_artifacts=request.stage_artifacts,
            context_references=request.context_references,
            change_sets=request.change_sets,
            clarifications=request.clarifications,
            approval_decisions=request.approval_decisions,
            allowed_context_run_ids=allowed_context_run_ids,
            built_at=built_at,
        )

        prompt_render = self._prompt_renderer.render_messages(
            PromptRenderRequest(
                session_id=request.session_id,
                run_id=request.run_id,
                stage_run_id=request.stage_run_id,
                stage_type=request.stage_type,
                model_call_type=request.model_call_type,
                template_snapshot_ref=request.template_snapshot.snapshot_ref,
                system_prompt_ref=self._system_prompt_ref(request, stage_role),
                stage_contracts={request.stage_type.value: dict(stage_contract)},
                agent_role_prompt=stage_role.system_prompt,
                task_objective=request.task_objective,
                specified_action=request.specified_action,
                available_tools=list(available_tools),
                response_schema=dict(request.response_schema),
                output_schema_ref=request.output_schema_ref,
                tool_schema_version=request.tool_schema_version,
                parse_error=request.parse_error,
                created_at=built_at,
            )
        )

        envelope = ContextEnvelope(
            session_id=request.session_id,
            run_id=request.run_id,
            stage_run_id=request.stage_run_id,
            stage_type=request.stage_type,
            template_snapshot_ref=request.template_snapshot.snapshot_ref,
            stage_contract_ref=contract_ref,
            provider_snapshot_ref=request.provider_snapshot.snapshot_id,
            model_binding_snapshot_ref=request.model_binding_snapshot.snapshot_id,
            model_call_type=request.model_call_type,
            runtime_instructions=self._runtime_instruction_blocks(
                prompt_render_result=prompt_render,
            ),
            stage_contract=self._prompt_backed_blocks(
                prompt_render_result=prompt_render,
                section=ContextEnvelopeSection.STAGE_CONTRACT,
                trust_level=ContextTrustLevel.STAGE_CONTRACT_TRUSTED,
                section_ids=(
                    ContextEnvelopeSection.STAGE_CONTRACT.value,
                    "stage_prompt_fragment",
                ),
            ),
            agent_role_prompt=self._agent_role_blocks(
                request=request,
                stage_role=stage_role,
                prompt_render_result=prompt_render,
            ),
            task_objective=(
                self._simple_block(
                    section=ContextEnvelopeSection.TASK_OBJECTIVE,
                    block_id=f"task-objective:{request.stage_run_id}",
                    summary=request.task_objective,
                    content_ref=f"stage-task-objective://{request.stage_run_id}",
                    source_kind="stage_task_objective",
                    source_label="task_objective",
                ),
            ),
            specified_action=(
                self._simple_block(
                    section=ContextEnvelopeSection.SPECIFIED_ACTION,
                    block_id=f"specified-action:{request.stage_run_id}",
                    summary=request.specified_action,
                    content_ref=f"stage-specified-action://{request.stage_run_id}",
                    source_kind="stage_specified_action",
                    source_label="specified_action",
                ),
            ),
            input_artifact_refs=stage_inputs,
            context_references=resolved_sources.context_references,
            working_observations=resolved_sources.working_observations,
            reasoning_trace=resolved_sources.reasoning_trace,
            available_tools=available_tools,
            recent_observations=resolved_sources.recent_observations,
            response_schema=dict(request.response_schema),
            trace_context=request.trace_context,
            built_at=built_at,
        )
        if envelope.model_binding_snapshot_ref != request.model_binding_snapshot.snapshot_id:
            raise ValueError(
                "ContextEnvelope.model_binding_snapshot_ref must match "
                "model_binding_snapshot.snapshot_id"
            )
        envelope = self._apply_size_guard(
            envelope=envelope,
            request=request,
            built_at=built_at,
        )

        rendered_messages = self.render_messages(
            envelope=envelope,
            prompt_render_result=prompt_render,
        )
        render_hash = PromptRenderer.compute_render_hash(list(rendered_messages))
        rendered_output_ref = (
            f"artifact://context-envelopes/{request.run_id}/"
            f"{request.stage_run_id}/{request.model_call_type.value}"
        )
        manifest = ContextManifest.from_envelope(
            envelope,
            provider_snapshot=request.provider_snapshot,
            prompt_refs=prompt_render.metadata.prompt_refs,
            render_hash=render_hash,
            rendered_output_ref=rendered_output_ref,
            rendered_output_kind=RenderedOutputKind.MESSAGE_SEQUENCE,
            template_version=request.template_version,
            output_schema_ref=request.output_schema_ref,
            tool_schema_version=request.tool_schema_version,
            system_prompt_ref=prompt_render.system_prompt_ref,
            runtime_limit_snapshot_ref=request.runtime_limit_snapshot.snapshot_id,
            compression_threshold_ratio=(
                request.runtime_limit_snapshot.context_limits.compression_threshold_ratio
            ),
            compression_trigger_token_threshold=self._compression_trigger_tokens(
                request=request
            ),
        )
        self.append_manifest_record(
            artifact_id=request.stage_artifact_id,
            manifest=manifest,
            trace_context=request.trace_context,
        )
        return ContextBuildResult(
            envelope=envelope,
            manifest=manifest,
            rendered_messages=rendered_messages,
            rendered_output_ref=rendered_output_ref,
            render_hash=render_hash,
            prompt_render_result=prompt_render,
        )

    def _apply_size_guard(
        self,
        *,
        envelope: ContextEnvelope,
        request: ContextBuildRequest,
        built_at: datetime,
    ) -> ContextEnvelope:
        if self._context_size_guard is None:
            return envelope

        input_artifact_refs = self._budget_blocks(
            envelope.input_artifact_refs,
            request=request,
            built_at=built_at,
        )
        context_references = self._budget_blocks(
            envelope.context_references,
            request=request,
            built_at=built_at,
        )
        working_observations = self._budget_blocks(
            envelope.working_observations,
            request=request,
            built_at=built_at,
        )
        working_observations = self._window_blocks(
            working_observations,
            request=request,
            built_at=built_at,
        )
        reasoning_trace = self._budget_blocks(
            envelope.reasoning_trace,
            request=request,
            built_at=built_at,
        )
        reasoning_trace = self._window_blocks(
            reasoning_trace,
            request=request,
            built_at=built_at,
        )
        recent_observations = self._budget_blocks(
            envelope.recent_observations,
            request=request,
            built_at=built_at,
        )
        recent_observations = self._window_blocks(
            recent_observations,
            request=request,
            built_at=built_at,
        )

        guarded = envelope.model_copy(
            update={
                "input_artifact_refs": input_artifact_refs,
                "context_references": context_references,
                "working_observations": working_observations,
                "reasoning_trace": reasoning_trace,
                "recent_observations": recent_observations,
            }
        )
        decision = self._context_size_guard.ensure_within_model_window(
            envelope=guarded,
            provider_snapshot=request.provider_snapshot,
            runtime_limit_snapshot=request.runtime_limit_snapshot,
            reserved_output_tokens=request.reserved_output_tokens,
        )
        if not decision.requires_compression:
            return guarded
        if self._compression_runner is None:
            self._raise_compression_required(
                decision=decision,
                safe_message=(
                    "Context compression required but no compression runner is "
                    "configured."
                ),
            )
        if request.provider_adapter is None:
            self._raise_compression_required(
                decision=decision,
                safe_message=(
                    "Context compression required but no provider adapter is "
                    "configured."
                ),
            )
        compression_result = self._compression_runner.compress(
            ContextCompressionRequest(
                envelope=guarded,
                manifest=self._pre_compression_manifest(
                    envelope=guarded,
                    request=request,
                ),
                stage_artifact_id=request.stage_artifact_id,
                trace_context=request.trace_context,
                full_trace_ref=(
                    request.full_trace_ref
                    or f"stage-process://{request.stage_run_id}/full"
                ),
                covered_step_range=request.compression_covered_step_range or "unknown",
                compression_trigger_reason="compression_threshold_exceeded",
                provider_adapter=request.provider_adapter,
                requested_max_output_tokens=request.reserved_output_tokens or None,
            )
        )
        if compression_result.compressed_context_block is None:
            self._raise_compression_required(
                decision=decision,
                safe_message="Context compression required but compression failed.",
            )
        compressed_block = self._compressed_context_block(
            compression_result.compressed_context_block
        )
        compressed = guarded.model_copy(
            update={
                "context_references": (),
                "working_observations": (),
                "reasoning_trace": (),
                "recent_observations": (compressed_block,),
            }
        )
        post_compression_decision = self._context_size_guard.ensure_within_model_window(
            envelope=compressed,
            provider_snapshot=request.provider_snapshot,
            runtime_limit_snapshot=request.runtime_limit_snapshot,
            reserved_output_tokens=request.reserved_output_tokens,
        )
        if post_compression_decision.requires_compression:
            self._raise_compression_required(
                decision=post_compression_decision,
                safe_message="Compressed context still exceeds the model window.",
            )
        return compressed

    def _budget_blocks(
        self,
        blocks: Sequence[ContextBlock],
        *,
        request: ContextBuildRequest,
        built_at: datetime,
    ) -> tuple[ContextBlock, ...]:
        if self._context_size_guard is None or not blocks:
            return tuple(blocks)
        return self._context_size_guard.apply_observation_budget(
            blocks=blocks,
            runtime_limit_snapshot=request.runtime_limit_snapshot,
            built_at=built_at,
        ).blocks

    def _window_blocks(
        self,
        blocks: Sequence[ContextBlock],
        *,
        request: ContextBuildRequest,
        built_at: datetime,
    ) -> tuple[ContextBlock, ...]:
        if (
            self._context_size_guard is None
            or not blocks
            or request.max_recent_observation_blocks is None
        ):
            return tuple(blocks)
        return self._context_size_guard.apply_sliding_window(
            blocks=blocks,
            max_recent_blocks=request.max_recent_observation_blocks,
            stage_run_id=request.stage_run_id,
            built_at=built_at,
        ).blocks

    def _compression_trigger_tokens(self, *, request: ContextBuildRequest) -> int:
        if self._context_size_guard is None:
            base_threshold = max(
                1,
                floor(
                request.provider_snapshot.capabilities.context_window_tokens
                * request.runtime_limit_snapshot.context_limits.compression_threshold_ratio
                ),
            )
            if request.reserved_output_tokens <= 0:
                return base_threshold
            conservative_threshold = floor(
                max(
                    1,
                    request.provider_snapshot.capabilities.context_window_tokens
                    - request.reserved_output_tokens,
                )
                * request.runtime_limit_snapshot.context_limits.compression_threshold_ratio
            )
            return max(1, min(base_threshold, conservative_threshold))
        return max(
            1,
            self._context_size_guard.compression_trigger_tokens(
                provider_snapshot=request.provider_snapshot,
                runtime_limit_snapshot=request.runtime_limit_snapshot,
                reserved_output_tokens=request.reserved_output_tokens,
            ),
        )

    def _pre_compression_manifest(
        self,
        *,
        envelope: ContextEnvelope,
        request: ContextBuildRequest,
    ) -> ContextManifest:
        return ContextManifest.from_envelope(
            envelope,
            provider_snapshot=request.provider_snapshot,
            prompt_refs=[],
            render_hash="0" * 64,
            rendered_output_ref=(
                f"artifact://context-envelopes/{request.run_id}/"
                f"{request.stage_run_id}/pre_compression"
            ),
            rendered_output_kind=RenderedOutputKind.MESSAGE_SEQUENCE,
            template_version=request.template_version,
            output_schema_ref=request.output_schema_ref,
            tool_schema_version=request.tool_schema_version,
            runtime_limit_snapshot_ref=request.runtime_limit_snapshot.snapshot_id,
            compression_threshold_ratio=(
                request.runtime_limit_snapshot.context_limits.compression_threshold_ratio
            ),
            compression_trigger_token_threshold=self._compression_trigger_tokens(
                request=request
            ),
        )

    @staticmethod
    def _compressed_context_block(block: CompressedContextBlock) -> ContextBlock:
        content_ref = f"compressed_context_block://{block.compressed_context_id}"
        return ContextBlock(
            block_id=f"compressed-context:{block.compressed_context_id}",
            section=ContextEnvelopeSection.RECENT_OBSERVATIONS,
            trust_level=ContextTrustLevel.TRUSTED_REFERENCE,
            boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
            summary=block.summary,
            content_ref=content_ref,
            sources=(
                ContextSourceRef(
                    source_kind="compressed_context_block",
                    source_ref=content_ref,
                    source_label=block.compressed_context_id,
                ),
            ),
            estimated_chars=len(block.summary),
            compressed=True,
        )

    @staticmethod
    def _raise_compression_required(
        *,
        decision: object,
        safe_message: str,
    ) -> None:
        raise ContextOverflowError(
            safe_message,
            reason="compression_required",
            total_estimated_tokens=decision.total_estimated_tokens,
            compression_trigger_tokens=decision.compression_trigger_tokens,
        )

    def render_messages(
        self,
        *,
        envelope: ContextEnvelope,
        prompt_render_result: PromptRenderResult,
    ) -> tuple[PromptRenderedMessage, ...]:
        additions = self._non_prompt_sections_text(envelope)
        if not additions:
            return tuple(prompt_render_result.messages)

        messages = list(prompt_render_result.messages)
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].role == "user":
                messages[index] = PromptRenderedMessage(
                    role="user",
                    content=f"{messages[index].content}\n\n{additions}",
                )
                return tuple(messages)
        messages.append(PromptRenderedMessage(role="user", content=additions))
        return tuple(messages)

    def append_manifest_record(
        self,
        *,
        artifact_id: str,
        manifest: ContextManifest,
        trace_context: TraceContext,
    ) -> None:
        self._artifact_store.append_process_record(
            artifact_id=artifact_id,
            process_key="context_manifest",
            process_value=manifest.model_dump(mode="json"),
            trace_context=trace_context,
        )

    @staticmethod
    def _validate_request(request: ContextBuildRequest) -> None:
        checks = (
            (
                "trace_context.session_id",
                request.trace_context.session_id,
                request.session_id,
            ),
            ("trace_context.run_id", request.trace_context.run_id, request.run_id),
            (
                "trace_context.stage_run_id",
                request.trace_context.stage_run_id,
                request.stage_run_id,
            ),
            ("template_snapshot.run_id", request.template_snapshot.run_id, request.run_id),
            ("graph_definition.run_id", request.graph_definition.run_id, request.run_id),
            ("provider_snapshot.run_id", request.provider_snapshot.run_id, request.run_id),
            (
                "model_binding_snapshot.run_id",
                request.model_binding_snapshot.run_id,
                request.run_id,
            ),
            (
                "model_binding_snapshot.provider_snapshot_id",
                request.model_binding_snapshot.provider_snapshot_id,
                request.provider_snapshot.snapshot_id,
            ),
            (
                "model_binding_snapshot.provider_id",
                request.model_binding_snapshot.provider_id,
                request.provider_snapshot.provider_id,
            ),
            (
                "model_binding_snapshot.model_id",
                request.model_binding_snapshot.model_id,
                request.provider_snapshot.model_id,
            ),
            (
                "model_binding_snapshot.capabilities.model_id",
                request.model_binding_snapshot.capabilities.model_id,
                request.provider_snapshot.model_id,
            ),
        )
        for name, actual, expected in checks:
            if actual != expected:
                raise ValueError(f"{name} must match request.run_id/session identity")
        if (
            request.model_binding_snapshot.stage_type is not None
            and request.model_binding_snapshot.stage_type != request.stage_type
        ):
            raise ValueError(
                "model_binding_snapshot.stage_type must match request.stage_type"
            )
        if (
            request.model_call_type is ModelCallType.STRUCTURED_OUTPUT_REPAIR
            and not request.parse_error
        ):
            raise ValueError("parse_error is required for structured_output_repair")

    def _stage_role_binding(self, request: ContextBuildRequest) -> StageRoleSnapshot:
        for binding in request.template_snapshot.stage_role_bindings:
            if binding.stage_type is request.stage_type:
                return binding
        raise ValueError(
            "template_snapshot.stage_role_bindings must include the current stage_type"
        )

    def _available_tools(
        self,
        stage_contract: dict[str, object],
    ) -> tuple[ToolBindableDescription, ...]:
        raw_allowed_tools = stage_contract.get("allowed_tools", ())
        if not isinstance(raw_allowed_tools, list | tuple):
            raise ValueError("stage contract allowed_tools must be a sequence")
        if not all(isinstance(tool_name, str) for tool_name in raw_allowed_tools):
            raise ValueError("stage contract allowed_tools must contain only strings")
        allowed_tools = {
            tool_name for tool_name in raw_allowed_tools
        }
        return tuple(
            tool
            for tool in self._tool_registry.list_bindable_tools()
            if tool.name in allowed_tools
        )

    @staticmethod
    def _stage_contract_ref(
        *,
        stage_contract: dict[str, object],
        fallback: str,
    ) -> str:
        contract_ref = stage_contract.get("stage_contract_ref")
        if contract_ref is None:
            return fallback
        if not isinstance(contract_ref, str) or not contract_ref:
            raise ValueError("stage contract stage_contract_ref must be a non-empty string")
        if contract_ref != fallback:
            raise ValueError(
                "request.stage_contract_ref must match graph_definition stage contract ref"
            )
        return contract_ref

    def _prompt_backed_blocks(
        self,
        *,
        prompt_render_result: PromptRenderResult,
        section: ContextEnvelopeSection,
        trust_level: ContextTrustLevel,
        section_ids: tuple[str, ...] | None = None,
    ) -> tuple[ContextBlock, ...]:
        rendered_section_ids = section_ids or (section.value,)
        return tuple(
            self._prompt_section_block(
                rendered_section=rendered_section,
                section=section,
                trust_level=trust_level,
            )
            for rendered_section in prompt_render_result.sections
            if rendered_section.section_id in rendered_section_ids
        )

    def _runtime_instruction_blocks(
        self,
        *,
        prompt_render_result: PromptRenderResult,
    ) -> tuple[ContextBlock, ...]:
        section_ids = {"runtime_instructions"}
        if (
            prompt_render_result.metadata.model_call_type
            is ModelCallType.STRUCTURED_OUTPUT_REPAIR
        ):
            section_ids.add("structured_output_repair")
        return tuple(
            self._prompt_section_block(
                rendered_section=rendered_section,
                section=ContextEnvelopeSection.RUNTIME_INSTRUCTIONS,
                trust_level=ContextTrustLevel.SYSTEM_TRUSTED,
            )
            for rendered_section in prompt_render_result.sections
            if rendered_section.section_id in section_ids
        )

    def _agent_role_blocks(
        self,
        *,
        request: ContextBuildRequest,
        stage_role: StageRoleSnapshot,
        prompt_render_result: PromptRenderResult,
    ) -> tuple[ContextBlock, ...]:
        sections = [
            section
            for section in prompt_render_result.sections
            if section.section_id == ContextEnvelopeSection.AGENT_ROLE_PROMPT.value
        ]
        if not sections:
            return ()
        system_prompt_ref = self._system_prompt_ref(request, stage_role)
        return tuple(
            ContextBlock(
                block_id=f"prompt-section:{section.section_id}:{index}",
                section=ContextEnvelopeSection.AGENT_ROLE_PROMPT,
                trust_level=ContextTrustLevel.AGENT_ROLE_CONFIG,
                boundary_action=ContextBoundaryAction.ALLOW,
                summary=section.body,
                content_ref=system_prompt_ref,
                sources=(
                    ContextSourceRef(
                        source_kind="template_snapshot_stage_role_prompt",
                        source_ref=system_prompt_ref,
                        source_label=f"{request.stage_type.value}.system_prompt",
                    ),
                ),
                prompt_section_refs=self._prompt_section_refs(section),
                estimated_chars=len(section.body),
            )
            for index, section in enumerate(sections, start=1)
        )

    def _prompt_section_block(
        self,
        *,
        rendered_section: PromptRenderedSection,
        section: ContextEnvelopeSection,
        trust_level: ContextTrustLevel,
    ) -> ContextBlock:
        prompt_ref = rendered_section.prompt_ref
        source_ref = (
            prompt_ref.source_ref
            if prompt_ref is not None
            else rendered_section.rendered_content_ref
        )
        return ContextBlock(
            block_id=f"prompt-section:{rendered_section.section_id}",
            section=section,
            trust_level=trust_level,
            boundary_action=ContextBoundaryAction.ALLOW,
            summary=rendered_section.body,
            content_ref=rendered_section.rendered_content_ref,
            sources=(
                ContextSourceRef(
                    source_kind=(
                        "prompt_asset" if prompt_ref is not None else "prompt_render"
                    ),
                    source_ref=source_ref,
                    source_label=rendered_section.title,
                    content_hash=(
                        prompt_ref.content_hash if prompt_ref is not None else None
                    ),
                ),
            ),
            prompt_section_refs=self._prompt_section_refs(rendered_section),
            estimated_chars=len(rendered_section.body),
        )

    @staticmethod
    def _prompt_section_refs(
        rendered_section: PromptRenderedSection,
    ) -> tuple[PromptSectionRef, ...]:
        if rendered_section.prompt_ref is None:
            return ()
        return (
            PromptSectionRef(
                section_id=rendered_section.section_id,
                title=rendered_section.title,
                prompt_ref=rendered_section.prompt_ref,
                rendered_content_ref=rendered_section.rendered_content_ref,
                rendered_content_hash=rendered_section.rendered_content_hash,
                cache_scope=rendered_section.cache_scope,
            ),
        )

    @staticmethod
    def _simple_block(
        *,
        section: ContextEnvelopeSection,
        block_id: str,
        summary: str,
        content_ref: str,
        source_kind: str,
        source_label: str,
    ) -> ContextBlock:
        return ContextBlock(
            block_id=block_id,
            section=section,
            trust_level=ContextTrustLevel.TRUSTED_REFERENCE,
            boundary_action=ContextBoundaryAction.ALLOW,
            summary=summary,
            content_ref=content_ref,
            sources=(
                ContextSourceRef(
                    source_kind=source_kind,
                    source_ref=content_ref,
                    source_label=source_label,
                ),
            ),
            estimated_chars=len(summary),
        )

    @staticmethod
    def _non_prompt_sections_text(envelope: ContextEnvelope) -> str:
        sections = (
            ("Input Artifact Refs", envelope.input_artifact_refs),
            ("Context References", envelope.context_references),
            ("Working Observations", envelope.working_observations),
            ("Reasoning Trace", envelope.reasoning_trace),
            ("Recent Observations", envelope.recent_observations),
        )
        chunks = [
            _format_context_section(title, blocks)
            for title, blocks in sections
            if blocks
        ]
        return "\n\n".join(chunks)

    @staticmethod
    def _system_prompt_ref(
        request: ContextBuildRequest,
        stage_role: StageRoleSnapshot,
    ) -> str:
        return (
            f"template-snapshot://{request.template_snapshot.snapshot_ref}/"
            f"stage-role-bindings/{stage_role.role_id}/system_prompt"
        )


def _format_context_section(
    title: str,
    blocks: Sequence[ContextBlock],
) -> str:
    lines = [title]
    for block in blocks:
        lines.append(f"- {block.summary} ({block.content_ref})")
    return "\n".join(lines)


__all__ = [
    "ContextBuildRequest",
    "ContextBuildResult",
    "ContextEnvelopeBuilder",
]
