from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Iterable, Mapping, Sequence

from pydantic import ValidationError

from backend.app.context.schemas import (
    ContextBlock,
    ContextBoundaryAction,
    ContextEnvelopeSection,
    ContextSourceRef,
    ContextTrustLevel,
)
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ClarificationRecordModel,
    StageArtifactModel,
)
from backend.app.domain.changes import ChangeSet, ContextReference, ContextReferenceKind
from backend.app.domain.enums import StageType
from backend.app.schemas.run import SolutionDesignArtifactRead


_STAGE_INPUT_ARTIFACT_TYPES: Mapping[StageType, tuple[str, ...]] = {
    StageType.CODE_GENERATION: (
        "RequirementAnalysisArtifact",
        "SolutionDesignArtifact",
    ),
    StageType.TEST_GENERATION_EXECUTION: (
        "RequirementAnalysisArtifact",
        "SolutionDesignArtifact",
        "CodeGenerationArtifact",
    ),
    StageType.CODE_REVIEW: (
        "RequirementAnalysisArtifact",
        "SolutionDesignArtifact",
        "CodeGenerationArtifact",
        "TestGenerationExecutionArtifact",
    ),
    StageType.DELIVERY_INTEGRATION: (
        "CodeGenerationArtifact",
        "TestGenerationExecutionArtifact",
        "CodeReviewArtifact",
    ),
}
_STAGE_OUTPUT_REQUIRED_FIELDS: Mapping[str, tuple[str, ...]] = {
    "RequirementAnalysisArtifact": (
        "structured_requirement",
        "acceptance_criteria",
        "clarification_summary",
        "assumptions",
        "non_goals",
        "open_questions",
        "source_message_refs",
        "clarification_record_refs",
        "attachment_refs",
        "context_refs",
        "analysis_notes",
    ),
    "CodeGenerationArtifact": (
        "changeset_ref",
        "changed_files",
        "diff_refs",
        "file_edit_trace_refs",
        "implementation_notes",
        "requirement_refs",
        "solution_refs",
    ),
    "TestGenerationExecutionArtifact": (
        "test_changes_ref",
        "test_execution_result",
        "test_gap_report",
        "command_trace_refs",
        "failed_test_refs",
        "acceptance_criteria_refs",
        "changeset_refs",
    ),
    "CodeReviewArtifact": (
        "review_report",
        "issue_list",
        "risk_assessment",
        "regression_decision",
        "fix_requirements",
        "evidence_refs",
        "changeset_refs",
        "test_result_refs",
    ),
}
_WORKING_PROCESS_REF_KEYS = frozenset(
    {
        "command_trace_ref",
        "command_trace_refs",
        "diff_ref",
        "diff_refs",
        "file_edit_trace_ref",
        "file_edit_trace_refs",
        "model_call_ref",
        "model_call_refs",
        "process_ref",
        "process_refs",
        "provider_call_ref",
        "provider_call_refs",
        "tool_call_ref",
        "tool_call_refs",
        "tool_confirmation_trace_ref",
        "tool_confirmation_trace_refs",
        "validation_ref",
        "validation_refs",
    }
)
_TRUSTED_ALLOW_CONTEXT_REFERENCE_KINDS = frozenset(
    {
        ContextReferenceKind.ACCEPTANCE_CRITERIA,
        ContextReferenceKind.SOLUTION_ARTIFACT,
    }
)
_TRUSTED_REFERENCE_ONLY_CONTEXT_REFERENCE_KINDS = frozenset(
    {
        ContextReferenceKind.CHANGE_SET,
        ContextReferenceKind.COMPRESSED_CONTEXT,
    }
)
_UNTRUSTED_QUARANTINE_CONTEXT_REFERENCE_KINDS = frozenset(
    {
        ContextReferenceKind.REQUIREMENT_MESSAGE,
        ContextReferenceKind.CLARIFICATION,
        ContextReferenceKind.APPROVAL_FEEDBACK,
        ContextReferenceKind.REVIEW_FEEDBACK,
    }
)
_SHA256_REF_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTEXT_REFERENCE_SOURCE_PREFIXES = (
    "approval-decision://",
    "approval-request://",
    "artifact://process/",
    "attachment://",
    "changeset://",
    "clarification://",
    "delivery-record://",
    "diff://",
    "directory://",
    "file-excerpt://",
    "file-version://",
    "file://",
    "file_edit_trace:",
    "message://",
    "payload://",
    "reasoning://",
    "stage-artifact://",
    "tool-call://",
    "tool-confirmation://",
    "validation://",
    "workspace://",
)


@dataclass(frozen=True, slots=True)
class ResolvedContextSources:
    context_references: tuple[ContextBlock, ...] = ()
    working_observations: tuple[ContextBlock, ...] = ()
    reasoning_trace: tuple[ContextBlock, ...] = ()
    recent_observations: tuple[ContextBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class _StructuredStageOutput:
    artifact_type: str
    payload: Mapping[str, Any]
    evidence_refs: tuple[str, ...] = ()


class ContextSourceResolver:
    def resolve_stage_inputs(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        stage_artifacts: Sequence[StageArtifactModel],
        user_messages: Sequence[Any] = (),
        allowed_context_run_ids: Sequence[str],
        built_at: datetime,
    ) -> tuple[ContextBlock, ...]:
        del stage_run_id, built_at
        allowed = _allowed_run_ids(run_id, allowed_context_run_ids)
        if stage_type is StageType.REQUIREMENT_ANALYSIS:
            return _user_message_blocks(
                user_messages,
                session_id=session_id,
                allowed_run_ids=allowed,
            )

        allowed_artifact_types = _STAGE_INPUT_ARTIFACT_TYPES.get(stage_type)
        if not allowed_artifact_types:
            return ()

        blocks: list[ContextBlock] = []
        seen: set[str] = set()
        for artifact in stage_artifacts:
            if artifact.run_id not in allowed:
                continue
            for output in _structured_stage_outputs(artifact):
                if output.artifact_type not in allowed_artifact_types:
                    continue
                block = _stage_output_block(artifact, output)
                if block is None or block.block_id in seen:
                    continue
                seen.add(block.block_id)
                blocks.append(block)
        return tuple(blocks)

    def resolve_context_references(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        stage_artifacts: Sequence[StageArtifactModel],
        context_references: Sequence[ContextReference],
        change_sets: Sequence[ChangeSet],
        clarifications: Sequence[ClarificationRecordModel],
        approval_decisions: Sequence[ApprovalDecisionModel],
        allowed_context_run_ids: Sequence[str],
        built_at: datetime,
    ) -> ResolvedContextSources:
        del session_id, stage_run_id, stage_type, built_at
        allowed = _allowed_run_ids(run_id, allowed_context_run_ids)
        allowed_artifacts = tuple(
            artifact for artifact in stage_artifacts if artifact.run_id in allowed
        )
        allowed_change_sets = tuple(
            change_set for change_set in change_sets if change_set.run_id in allowed
        )

        return ResolvedContextSources(
            context_references=_context_reference_blocks(
                context_references,
                allowed_run_ids=allowed,
            ),
            working_observations=(
                *_change_set_blocks(allowed_change_sets, allowed_run_ids=allowed),
                *_artifact_ref_blocks(allowed_artifacts, allowed_run_ids=allowed),
            ),
            reasoning_trace=_reasoning_trace_blocks(
                allowed_artifacts,
                allowed_run_ids=allowed,
            ),
            recent_observations=_recent_observation_blocks(
                clarifications=clarifications,
                approval_decisions=approval_decisions,
                allowed_run_ids=allowed,
            ),
        )


def _allowed_run_ids(
    run_id: str,
    allowed_context_run_ids: Sequence[str],
) -> set[str]:
    return set(allowed_context_run_ids) or {run_id}


def _user_message_blocks(
    user_messages: Sequence[Any],
    *,
    session_id: str,
    allowed_run_ids: set[str],
) -> tuple[ContextBlock, ...]:
    blocks: list[ContextBlock] = []
    seen: set[str] = set()
    for message in user_messages:
        payload = _message_payload(message)
        message_run_id = _optional_string(payload.get("run_id"))
        if message_run_id is not None and message_run_id not in allowed_run_ids:
            continue
        message_id = _optional_string(payload.get("message_id"))
        content = _optional_string(payload.get("content"))
        if message_id is None or content is None:
            continue
        ref = f"message://{session_id}/{message_id}"
        if ref in seen:
            continue
        seen.add(ref)
        stage_ref = _optional_string(payload.get("stage_run_id")) or "none"
        blocks.append(
            _block(
                block_id=f"user-message:{message_id}",
                section=ContextEnvelopeSection.INPUT_ARTIFACT_REFS,
                trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
                boundary_action=ContextBoundaryAction.QUARANTINE,
                summary=(
                    f"User message {message_id}: run_id={message_run_id or 'none'}; "
                    f"stage_run_id={stage_ref}; content={_short_text(content, limit=600)}"
                ),
                content_ref=ref,
                sources=(
                    ContextSourceRef(
                        source_kind="user_message",
                        source_ref=ref,
                        source_label=message_id,
                    ),
                ),
            )
        )
    return tuple(blocks)


def _message_payload(message: Any) -> dict[str, Any]:
    if isinstance(message, Mapping):
        return dict(message)
    model_dump = getattr(message, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    values: dict[str, Any] = {}
    for key in ("message_id", "run_id", "stage_run_id", "author", "content"):
        value = getattr(message, key, None)
        if value is not None:
            values[key] = value
    return values


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _structured_stage_outputs(
    artifact: StageArtifactModel,
) -> tuple[_StructuredStageOutput, ...]:
    process = _artifact_process(artifact)
    outputs: list[_StructuredStageOutput] = []
    snapshot = process.get("output_snapshot")
    if isinstance(snapshot, Mapping):
        artifact_type = snapshot.get("artifact_type")
        payload = snapshot.get("artifact_payload")
        if isinstance(artifact_type, str) and isinstance(payload, Mapping):
            outputs.append(
                _StructuredStageOutput(
                    artifact_type=artifact_type,
                    payload=payload,
                    evidence_refs=_non_empty_strings(snapshot.get("evidence_refs")),
                )
            )

    legacy_solution = process.get("solution_design_artifact")
    if isinstance(legacy_solution, Mapping):
        outputs.append(
            _StructuredStageOutput(
                artifact_type="SolutionDesignArtifact",
                payload=legacy_solution,
            )
        )
    return tuple(outputs)


def _stage_output_block(
    artifact: StageArtifactModel,
    output: _StructuredStageOutput,
) -> ContextBlock | None:
    if output.artifact_type == "SolutionDesignArtifact":
        solution = _solution_design_artifact(artifact, output.payload)
        if solution is None:
            return None
        plan = solution.implementation_plan
        return _block(
            block_id=f"stage-output-artifact:{output.artifact_type}:{plan.plan_id}",
            section=ContextEnvelopeSection.INPUT_ARTIFACT_REFS,
            trust_level=ContextTrustLevel.TRUSTED_REFERENCE,
            boundary_action=ContextBoundaryAction.ALLOW,
            summary=(
                f"Stage output artifact: artifact_type={output.artifact_type}; "
                f"{_implementation_plan_summary(solution)}"
            ),
            content_ref=f"stage-artifact://{artifact.artifact_id}",
            sources=(
                ContextSourceRef(
                    source_kind="stage_output_artifact",
                    source_ref=f"stage-artifact://{artifact.artifact_id}",
                    source_label=output.artifact_type,
                    version_ref=plan.plan_id,
                ),
            ),
        )

    if not _has_required_fields(output.artifact_type, output.payload):
        return None
    return _block(
        block_id=f"stage-output-artifact:{output.artifact_type}:{artifact.artifact_id}",
        section=ContextEnvelopeSection.INPUT_ARTIFACT_REFS,
        trust_level=ContextTrustLevel.TRUSTED_REFERENCE,
        boundary_action=ContextBoundaryAction.ALLOW,
        summary=_stage_output_summary(output.artifact_type, output.payload),
        content_ref=f"stage-artifact://{artifact.artifact_id}",
        sources=(
            ContextSourceRef(
                source_kind="stage_output_artifact",
                source_ref=f"stage-artifact://{artifact.artifact_id}",
                source_label=output.artifact_type,
            ),
        ),
    )


def _solution_design_artifact(
    artifact: StageArtifactModel,
    payload: Mapping[str, Any],
) -> SolutionDesignArtifactRead | None:
    candidate = dict(payload)
    candidate.setdefault("artifact_id", artifact.artifact_id)
    candidate.setdefault("stage_run_id", artifact.stage_run_id)
    try:
        return SolutionDesignArtifactRead.model_validate(candidate)
    except (TypeError, ValueError, ValidationError):
        return None


def _implementation_plan_summary(solution: SolutionDesignArtifactRead) -> str:
    plan = solution.implementation_plan
    ordered_tasks = sorted(plan.tasks, key=lambda task: task.order_index)
    task_ids = _bounded_join(task.task_id for task in ordered_tasks)
    task_details = _bounded_join(
        f"task_id={task.task_id}" for task in ordered_tasks
    )
    order = _bounded_join(
        f"{task.order_index}:{task.task_id}" for task in ordered_tasks
    )
    target_files = _bounded_join(
        file_path
        for task in ordered_tasks
        for file_path in task.target_files
    )
    target_modules = _bounded_join(
        module
        for task in ordered_tasks
        for module in task.target_modules
    )
    verification_commands = _bounded_join(
        command
        for task in ordered_tasks
        for command in task.verification_commands
    )
    dependencies = _bounded_join(
        f"{task.task_id}<-{','.join(task.depends_on_task_ids)}"
        for task in ordered_tasks
        if task.depends_on_task_ids
    )
    risks = _bounded_join(
        task.risk_handling or "" for task in ordered_tasks
    )
    return (
        f"Approved solution design implementation plan: plan_id={plan.plan_id}; "
        f"artifact_id={solution.artifact_id}; task_ids={task_ids}; "
        f"tasks={task_details}; order={order}; target_files={target_files}; "
        f"target_modules={target_modules}; "
        f"verification_commands={verification_commands}; "
        f"depends_on_task_ids={dependencies}; risk_handling={risks}."
    )


def _stage_output_summary(
    artifact_type: str,
    payload: Mapping[str, Any],
) -> str:
    if artifact_type == "RequirementAnalysisArtifact":
        return (
            f"Stage output artifact: artifact_type={artifact_type}; "
            f"structured_requirement={_short_text(_string_value(payload, 'structured_requirement'))}; "
            f"acceptance_criteria={_bounded_join(_string_list(payload.get('acceptance_criteria')))}; "
            f"source_message_refs={_bounded_join(_string_list(payload.get('source_message_refs')))}."
        )
    if artifact_type == "CodeGenerationArtifact":
        return (
            f"Stage output artifact: artifact_type={artifact_type}; "
            f"changeset_ref={_string_value(payload, 'changeset_ref')}; "
            f"changed_files={_bounded_join(_string_list(payload.get('changed_files')))}; "
            f"diff_refs={_bounded_join(_string_list(payload.get('diff_refs')))}; "
            f"file_edit_trace_refs={_bounded_join(_string_list(payload.get('file_edit_trace_refs')))}."
        )
    if artifact_type == "TestGenerationExecutionArtifact":
        return (
            f"Stage output artifact: artifact_type={artifact_type}; "
            f"test_execution_result={_short_text(_string_value(payload, 'test_execution_result'))}; "
            f"command_trace_refs={_bounded_join(_string_list(payload.get('command_trace_refs')))}; "
            f"changeset_refs={_bounded_join(_string_list(payload.get('changeset_refs')))}."
        )
    if artifact_type == "CodeReviewArtifact":
        return (
            f"Stage output artifact: artifact_type={artifact_type}; "
            f"regression_decision={_short_text(_string_value(payload, 'regression_decision'))}; "
            f"evidence_refs={_bounded_join(_string_list(payload.get('evidence_refs')))}; "
            f"changeset_refs={_bounded_join(_string_list(payload.get('changeset_refs')))}; "
            f"test_result_refs={_bounded_join(_string_list(payload.get('test_result_refs')))}."
        )
    return f"Stage output artifact: artifact_type={artifact_type}."


def _context_reference_blocks(
    context_references: Sequence[ContextReference],
    *,
    allowed_run_ids: set[str],
) -> tuple[ContextBlock, ...]:
    blocks: list[ContextBlock] = []
    seen: set[str] = set()
    for reference in context_references:
        if not _context_reference_allowed(reference, allowed_run_ids=allowed_run_ids):
            continue
        if reference.ref in seen:
            continue
        seen.add(reference.ref)
        trust_level, boundary_action = _context_reference_policy(reference.kind)
        source = ContextSourceRef(
            source_kind=f"context_reference:{reference.kind.value}",
            source_ref=reference.source_ref,
            source_label=reference.source_label,
            version_ref=reference.version_ref,
            file_path=reference.path,
        )
        blocks.append(
            _block(
                block_id=f"context-reference:{reference.reference_id}",
                section=ContextEnvelopeSection.CONTEXT_REFERENCES,
                trust_level=trust_level,
                boundary_action=boundary_action,
                summary=_context_reference_summary(reference),
                content_ref=reference.ref,
                sources=(source,),
            )
        )
    return tuple(blocks)


def _change_set_blocks(
    change_sets: Sequence[ChangeSet],
    *,
    allowed_run_ids: set[str],
) -> tuple[ContextBlock, ...]:
    blocks: list[ContextBlock] = []
    for change_set in change_sets:
        refs = _dedupe(
            ref
            for ref in (
                change_set.ref,
                *change_set.diff_refs,
                *change_set.file_edit_trace_refs,
            )
            if _allow_stable_ref(ref, allowed_run_ids=allowed_run_ids)
        )
        changed_files = _bounded_join(change_set.changed_files)
        ref_summary = _bounded_join(refs)
        sources = tuple(
            ContextSourceRef(
                source_kind=_source_kind_for_ref(ref),
                source_ref=ref,
                source_label=change_set.change_set_id,
            )
            for ref in refs
        )
        blocks.append(
            _block(
                block_id=f"change-set:{change_set.change_set_id}",
                section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
                trust_level=ContextTrustLevel.TRUSTED_REFERENCE,
                boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
                summary=(
                    f"ChangeSet reference summary: change_set_ref={change_set.ref}; "
                    f"changed_files={changed_files}; refs={ref_summary}."
                ),
                content_ref=change_set.ref,
                sources=sources,
            )
        )
    return tuple(blocks)


def _artifact_ref_blocks(
    stage_artifacts: Sequence[StageArtifactModel],
    *,
    allowed_run_ids: set[str],
) -> tuple[ContextBlock, ...]:
    blocks: list[ContextBlock] = []
    for artifact in stage_artifacts:
        refs = _dedupe(
            ref
            for key, value in _artifact_process(artifact).items()
            if _is_working_process_ref_key(key)
            for ref in _string_refs(value, allowed_run_ids=allowed_run_ids)
        )
        if not refs:
            continue
        sources = tuple(
            ContextSourceRef(
                source_kind=_source_kind_for_ref(ref),
                source_ref=ref,
                source_label=artifact.artifact_id,
            )
            for ref in refs
        )
        blocks.append(
            _block(
                block_id=f"artifact-process-refs:{artifact.artifact_id}",
                section=ContextEnvelopeSection.WORKING_OBSERVATIONS,
                trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
                boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
                summary=(
                    f"Stage artifact process reference summary: "
                    f"artifact_id={artifact.artifact_id}; refs={_bounded_join(refs)}."
                ),
                content_ref=f"stage-artifact://{artifact.artifact_id}#process-refs",
                sources=sources,
            )
        )
    return tuple(blocks)


def _reasoning_trace_blocks(
    stage_artifacts: Sequence[StageArtifactModel],
    *,
    allowed_run_ids: set[str],
) -> tuple[ContextBlock, ...]:
    blocks: list[ContextBlock] = []
    for artifact in stage_artifacts:
        refs = _dedupe(
            ref
            for key, value in _artifact_process(artifact).items()
            if "reasoning" in key and _is_ref_key(key)
            for ref in _string_refs(
                value,
                allowed_run_ids=allowed_run_ids,
                allow_hash=True,
            )
        )
        if not refs:
            continue
        blocks.append(
            _block(
                block_id=f"reasoning-trace:{artifact.artifact_id}",
                section=ContextEnvelopeSection.REASONING_TRACE,
                trust_level=ContextTrustLevel.TRUSTED_REFERENCE,
                boundary_action=ContextBoundaryAction.REFERENCE_ONLY,
                summary=(
                    f"Reasoning trace reference summary: "
                    f"artifact_id={artifact.artifact_id}; refs={_bounded_join(refs)}."
                ),
                content_ref=f"stage-artifact://{artifact.artifact_id}#reasoning-refs",
                sources=tuple(
                    ContextSourceRef(
                        source_kind="reasoning_trace_ref",
                        source_ref=ref,
                        source_label=artifact.artifact_id,
                    )
                    for ref in refs
                ),
            )
        )
    return tuple(blocks)


def _recent_observation_blocks(
    *,
    clarifications: Sequence[ClarificationRecordModel],
    approval_decisions: Sequence[ApprovalDecisionModel],
    allowed_run_ids: set[str],
) -> tuple[ContextBlock, ...]:
    blocks: list[ContextBlock] = []
    for clarification in clarifications:
        if clarification.run_id not in allowed_run_ids or not clarification.answer:
            continue
        blocks.append(
            _block(
                block_id=f"clarification-answer:{clarification.clarification_id}",
                section=ContextEnvelopeSection.RECENT_OBSERVATIONS,
                trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
                boundary_action=ContextBoundaryAction.QUARANTINE,
                summary=(
                    f"Clarification answer {clarification.clarification_id}: "
                    f"{_short_text(clarification.answer)}"
                ),
                content_ref=(
                    clarification.payload_ref
                    or f"clarification://{clarification.clarification_id}"
                ),
                sources=(
                    ContextSourceRef(
                        source_kind="clarification_answer",
                        source_ref=(
                            clarification.payload_ref
                            or f"clarification://{clarification.clarification_id}"
                        ),
                        source_label=clarification.clarification_id,
                    ),
                ),
            )
        )
    for decision in approval_decisions:
        if decision.run_id not in allowed_run_ids or not decision.reason:
            continue
        blocks.append(
            _block(
                block_id=f"approval-reason:{decision.decision_id}",
                section=ContextEnvelopeSection.RECENT_OBSERVATIONS,
                trust_level=ContextTrustLevel.UNTRUSTED_OBSERVATION,
                boundary_action=ContextBoundaryAction.QUARANTINE,
                summary=(
                    f"Approval decision reason {decision.decision_id}: "
                    f"decision={decision.decision.value}; "
                    f"reason={_short_text(decision.reason)}"
                ),
                content_ref=f"approval-decision://{decision.decision_id}",
                sources=(
                    ContextSourceRef(
                        source_kind="approval_decision_reason",
                        source_ref=f"approval-decision://{decision.decision_id}",
                        source_label=decision.approval_id,
                    ),
                ),
            )
        )
    return tuple(blocks)


def _block(
    *,
    block_id: str,
    section: ContextEnvelopeSection,
    trust_level: ContextTrustLevel,
    boundary_action: ContextBoundaryAction,
    summary: str,
    content_ref: str,
    sources: tuple[ContextSourceRef, ...],
) -> ContextBlock:
    return ContextBlock(
        block_id=block_id,
        section=section,
        trust_level=trust_level,
        boundary_action=boundary_action,
        summary=summary,
        content_ref=content_ref,
        sources=sources,
        estimated_chars=len(summary),
    )


def _is_ref_key(key: str) -> bool:
    return key.endswith("_ref") or key.endswith("_refs")


def _is_working_process_ref_key(key: str) -> bool:
    return key in _WORKING_PROCESS_REF_KEYS


def _string_refs(
    value: Any,
    *,
    allowed_run_ids: set[str],
    allow_hash: bool = False,
) -> tuple[str, ...]:
    if isinstance(value, str) and _allow_stable_ref(
        value,
        allowed_run_ids=allowed_run_ids,
        allow_hash=allow_hash,
    ):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(
            item
            for item in value
            if isinstance(item, str)
            and _allow_stable_ref(
                item,
                allowed_run_ids=allowed_run_ids,
                allow_hash=allow_hash,
            )
        )
    return ()


def _dedupe(refs: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        ordered.append(ref)
    return tuple(ordered)


def _source_kind_for_ref(ref: str) -> str | None:
    if ref.startswith("changeset://"):
        return "change_set"
    if ref.startswith("diff://"):
        return "diff"
    if ref.startswith("file_edit_trace:"):
        return "file_edit_trace"
    if ref.startswith("model-call://"):
        return "model_call_ref"
    if ref.startswith("provider-call://"):
        return "provider_call_ref"
    if ref.startswith("process://"):
        return "process_ref"
    if ref.startswith("artifact://process/"):
        return "process_ref"
    if ref.startswith("tool-call://"):
        return "tool_call_ref"
    if ref.startswith("tool-confirmation://"):
        return "tool_confirmation_trace_ref"
    if ref.startswith("validation://"):
        return "validation_ref"
    if ref.startswith("reasoning://"):
        return "reasoning_trace_ref"
    if ref.startswith("command://"):
        return "command_trace_ref"
    return None


def _allow_stable_ref(
    value: str,
    *,
    allowed_run_ids: set[str],
    allow_hash: bool = False,
) -> bool:
    if not value or len(value) > 512 or any(char.isspace() for char in value):
        return False
    if allow_hash and _SHA256_REF_PATTERN.fullmatch(value):
        return True
    if _source_kind_for_ref(value) is None:
        return False
    ref_run_id = _run_id_from_ref(value)
    return ref_run_id is None or ref_run_id in allowed_run_ids


def _context_reference_policy(
    kind: ContextReferenceKind,
) -> tuple[ContextTrustLevel, ContextBoundaryAction]:
    if kind in _TRUSTED_ALLOW_CONTEXT_REFERENCE_KINDS:
        return (
            ContextTrustLevel.TRUSTED_REFERENCE,
            ContextBoundaryAction.ALLOW,
        )
    if kind in _TRUSTED_REFERENCE_ONLY_CONTEXT_REFERENCE_KINDS:
        return (
            ContextTrustLevel.TRUSTED_REFERENCE,
            ContextBoundaryAction.REFERENCE_ONLY,
        )
    if kind in _UNTRUSTED_QUARANTINE_CONTEXT_REFERENCE_KINDS:
        return (
            ContextTrustLevel.UNTRUSTED_OBSERVATION,
            ContextBoundaryAction.QUARANTINE,
        )
    return (
        ContextTrustLevel.UNTRUSTED_OBSERVATION,
        ContextBoundaryAction.REFERENCE_ONLY,
    )


def _context_reference_allowed(
    reference: ContextReference,
    *,
    allowed_run_ids: set[str],
) -> bool:
    if not _is_allowed_context_reference_source_ref(reference.source_ref):
        return False
    ref_run_id = _run_id_from_ref(reference.source_ref)
    return ref_run_id is None or ref_run_id in allowed_run_ids


def _context_reference_summary(reference: ContextReference) -> str:
    return _short_text(
        (
            f"Context reference {reference.reference_id}: "
            f"kind={reference.kind.value}; source_ref={reference.source_ref}; "
            f"label={reference.source_label}."
        ),
        limit=240,
    )


def _is_allowed_context_reference_source_ref(source_ref: str) -> bool:
    return source_ref.startswith(_CONTEXT_REFERENCE_SOURCE_PREFIXES)


def _artifact_process(artifact: StageArtifactModel) -> dict[str, Any]:
    process = artifact.process
    return process if isinstance(process, dict) else {}


def _has_required_fields(
    artifact_type: str,
    payload: Mapping[str, Any],
) -> bool:
    required_fields = _STAGE_OUTPUT_REQUIRED_FIELDS.get(artifact_type)
    return required_fields is not None and all(
        field_name in payload for field_name in required_fields
    )


def _string_value(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else "none"


def _string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _non_empty_strings(value: object) -> tuple[str, ...]:
    return _string_list(value)


def _run_id_from_ref(ref: str) -> str | None:
    if ref.startswith("file_edit_trace:"):
        parts = ref.split(":", 3)
        if len(parts) != 4 or any(not part for part in parts):
            return None
        return parts[1]
    if ref.startswith("artifact://process/"):
        remainder = ref.removeprefix("artifact://process/")
        run_id, _, _tail = remainder.partition("/")
        return run_id or None
    if "://" not in ref:
        return None
    scheme, remainder = ref.split("://", 1)
    if scheme in {"changeset", "diff", "message", "stage-artifact"}:
        return None
    run_id, _, _tail = remainder.partition("/")
    return run_id or None


def _bounded_join(
    items: Iterable[str],
    *,
    max_items: int = 8,
    max_chars: int = 240,
) -> str:
    values = [item for item in items if item]
    if not values:
        return "none"
    head = values[:max_items]
    text = ",".join(head)
    if len(values) > max_items:
        text = f"{text},...(+{len(values) - max_items} more)"
    if len(text) <= max_chars:
        return text
    return _short_text(text, limit=max_chars)


def _short_text(value: str, *, limit: int = 240) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


__all__ = [
    "ContextSourceResolver",
    "ResolvedContextSources",
]
