from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Iterable, Sequence

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


_IMPLEMENTATION_PLAN_CONSUMER_STAGES = frozenset(
    {
        StageType.CODE_GENERATION,
        StageType.TEST_GENERATION_EXECUTION,
        StageType.CODE_REVIEW,
    }
)
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


class ContextSourceResolver:
    def resolve_stage_inputs(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        stage_type: StageType,
        stage_artifacts: Sequence[StageArtifactModel],
        allowed_context_run_ids: Sequence[str],
        built_at: datetime,
    ) -> tuple[ContextBlock, ...]:
        del session_id, stage_run_id, built_at
        if stage_type not in _IMPLEMENTATION_PLAN_CONSUMER_STAGES:
            return ()

        allowed = _allowed_run_ids(run_id, allowed_context_run_ids)
        blocks: list[ContextBlock] = []
        seen_plan_ids: set[str] = set()
        for artifact in stage_artifacts:
            if artifact.run_id not in allowed:
                continue
            solution = _solution_design_artifact(artifact)
            if solution is None:
                continue
            plan = solution.implementation_plan
            if plan.plan_id in seen_plan_ids:
                continue
            seen_plan_ids.add(plan.plan_id)
            blocks.append(
                _block(
                    block_id=f"implementation-plan:{plan.plan_id}",
                    section=ContextEnvelopeSection.INPUT_ARTIFACT_REFS,
                    trust_level=ContextTrustLevel.TRUSTED_REFERENCE,
                    boundary_action=ContextBoundaryAction.ALLOW,
                    summary=_implementation_plan_summary(solution),
                    content_ref=f"stage-artifact://{artifact.artifact_id}",
                    sources=(
                        ContextSourceRef(
                            source_kind="solution_design_artifact",
                            source_ref=f"stage-artifact://{artifact.artifact_id}",
                            source_label=solution.artifact_id,
                            version_ref=plan.plan_id,
                        ),
                    ),
                )
            )
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


def _solution_design_artifact(
    artifact: StageArtifactModel,
) -> SolutionDesignArtifactRead | None:
    payload = _artifact_process(artifact).get("solution_design_artifact")
    if payload is None:
        return None
    try:
        return SolutionDesignArtifactRead.model_validate(payload)
    except (TypeError, ValueError, ValidationError):
        return None


def _implementation_plan_summary(solution: SolutionDesignArtifactRead) -> str:
    plan = solution.implementation_plan
    ordered_tasks = sorted(plan.tasks, key=lambda task: task.order_index)
    task_ids = _bounded_join(task.task_id for task in ordered_tasks)
    order = _bounded_join(
        f"{task.order_index}:{task.task_id}" for task in ordered_tasks
    )
    dependencies = _bounded_join(
        f"{task.task_id}<-{','.join(task.depends_on_task_ids)}"
        for task in ordered_tasks
        if task.depends_on_task_ids
    )
    return (
        f"Approved solution design implementation plan: plan_id={plan.plan_id}; "
        f"artifact_id={solution.artifact_id}; task_ids={task_ids}; "
        f"order={order}; depends_on_task_ids={dependencies}."
    )


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
