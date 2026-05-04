from __future__ import annotations

from datetime import UTC, datetime

from backend.app.context.schemas import (
    ContextBoundaryAction,
    ContextEnvelopeSection,
    ContextTrustLevel,
)
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ClarificationRecordModel,
    StageArtifactModel,
)
from backend.app.domain.changes import (
    ChangeOperation,
    ChangeSet,
    ChangeSetFile,
    ContextReference,
    ContextReferenceKind,
)
from backend.app.domain.enums import ApprovalStatus, StageType
from backend.app.schemas.run import (
    ImplementationPlanTaskRead,
    SolutionDesignArtifactRead,
    SolutionImplementationPlanRead,
)


NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _solution_design_artifact(
    *,
    artifact_id: str = "artifact-solution-design-1",
    plan_id: str = "plan-solution-design-1",
) -> SolutionDesignArtifactRead:
    return SolutionDesignArtifactRead(
        artifact_id=artifact_id,
        stage_run_id="stage-solution-design-1",
        technical_plan="Use ContextEnvelopeBuilder.",
        implementation_plan=SolutionImplementationPlanRead(
            plan_id=plan_id,
            source_stage_run_id="stage-solution-design-1",
            tasks=[
                ImplementationPlanTaskRead(
                    task_id="task-codegen-1",
                    order_index=1,
                    title="Generate code",
                    depends_on_task_ids=[],
                    target_files=["backend/app/context/source_resolver.py"],
                    target_modules=["backend.app.context.source_resolver"],
                    acceptance_refs=["A4.9a"],
                    verification_commands=[
                        "uv run pytest backend/tests/context/test_context_source_resolver.py -v"
                    ],
                    risk_handling="Do not edit ArtifactStore.",
                ),
                ImplementationPlanTaskRead(
                    task_id="task-test-1",
                    order_index=2,
                    title="Add tests",
                    depends_on_task_ids=["task-codegen-1"],
                    target_files=[
                        "backend/tests/context/test_context_source_resolver.py"
                    ],
                    target_modules=[
                        "backend.tests.context.test_context_source_resolver"
                    ],
                    acceptance_refs=["A4.9a"],
                    verification_commands=[
                        "uv run pytest backend/tests/context/test_context_source_resolver.py -v"
                    ],
                    risk_handling="Keep context summaries reference-only.",
                ),
            ],
            downstream_refs=["code_generation", "test_generation_execution"],
            created_at=NOW,
        ),
        impacted_files=["backend/app/context/source_resolver.py"],
        api_design=None,
        data_flow_design="Use explicit resolver inputs only.",
        risks=["Do not read runtime logs."],
        test_strategy="Focused context resolver tests.",
        validation_report="Plan approved.",
        requirement_refs=["requirement-1"],
        evidence_refs=["artifact://solution-design-1"],
    )


def _stage_artifact(
    *,
    artifact_id: str = "artifact-solution-design-1",
    run_id: str = "run-1",
    process: object | None = None,
) -> StageArtifactModel:
    return StageArtifactModel(
        artifact_id=artifact_id,
        run_id=run_id,
        stage_run_id=f"stage-{artifact_id}",
        artifact_type="solution_design",
        payload_ref=f"payload-{artifact_id}",
        process=process
        if process is not None
        else {
            "solution_design_artifact": _solution_design_artifact().model_dump(
                mode="json"
            )
        },
        metrics={},
        created_at=NOW,
    )


def test_resolve_stage_inputs_includes_approved_implementation_plan_and_skips_foreign_run() -> None:
    from backend.app.context.source_resolver import ContextSourceResolver

    blocks = ContextSourceResolver().resolve_stage_inputs(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=(
            _stage_artifact(),
            _stage_artifact(
                artifact_id="artifact-foreign",
                run_id="run-foreign",
                process={
                    "solution_design_artifact": _solution_design_artifact(
                        artifact_id="artifact-foreign",
                        plan_id="plan-foreign",
                    ).model_dump(mode="json")
                },
            ),
        ),
        allowed_context_run_ids=("run-1",),
        built_at=NOW,
    )

    assert len(blocks) == 1
    block = blocks[0]
    assert block.section is ContextEnvelopeSection.INPUT_ARTIFACT_REFS
    assert block.trust_level is ContextTrustLevel.TRUSTED_REFERENCE
    assert block.boundary_action is ContextBoundaryAction.ALLOW
    assert "plan_id=plan-solution-design-1" in block.summary
    assert "task_ids=task-codegen-1,task-test-1" in block.summary
    assert "order=1:task-codegen-1,2:task-test-1" in block.summary
    assert "depends_on_task_ids=task-test-1<-task-codegen-1" in block.summary
    assert "plan-foreign" not in block.summary
    assert [source.source_ref for source in block.sources] == [
        "stage-artifact://artifact-solution-design-1"
    ]
    assert all(
        source.source_ref != "stage-artifact://artifact-foreign"
        for source in block.sources
    )


def test_resolve_stage_inputs_ignores_malformed_payloads_and_unrelated_stages() -> None:
    from backend.app.context.source_resolver import ContextSourceResolver

    resolver = ContextSourceResolver()
    malformed_blocks = resolver.resolve_stage_inputs(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=(
            _stage_artifact(
                artifact_id="artifact-malformed",
                process={"solution_design_artifact": {"artifact_id": "missing-fields"}},
            ),
        ),
        allowed_context_run_ids=("run-1",),
        built_at=NOW,
    )
    non_mapping_process_blocks = resolver.resolve_stage_inputs(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=(
            _stage_artifact(
                artifact_id="artifact-process-list",
                process=["not-a-process-mapping"],
            ),
        ),
        allowed_context_run_ids=("run-1",),
        built_at=NOW,
    )
    unrelated_stage_blocks = resolver.resolve_stage_inputs(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-solution-design-2",
        stage_type=StageType.SOLUTION_DESIGN,
        stage_artifacts=(_stage_artifact(),),
        allowed_context_run_ids=("run-1",),
        built_at=NOW,
    )

    assert malformed_blocks == ()
    assert non_mapping_process_blocks == ()
    assert unrelated_stage_blocks == ()


def test_resolve_context_references_keeps_stable_refs_and_quarantines_human_feedback() -> None:
    from backend.app.context.source_resolver import ContextSourceResolver

    clarification = ClarificationRecordModel(
        clarification_id="clarification-1",
        run_id="run-1",
        stage_run_id="stage-requirement-1",
        question="Should code generation include tests?",
        answer="Yes, include regression coverage.",
        payload_ref="payload://clarification-1",
        graph_interrupt_ref="graph-interrupt-1",
        requested_at=NOW,
        answered_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    approval = ApprovalDecisionModel(
        decision_id="approval-decision-1",
        approval_id="approval-1",
        run_id="run-1",
        decision=ApprovalStatus.REJECTED,
        reason="Need a clearer rollback story.",
        decided_by_actor_id="user-1",
        decided_at=NOW,
        created_at=NOW,
    )
    context_reference = ContextReference(
        reference_id="context-ref-1",
        kind=ContextReferenceKind.REQUIREMENT_MESSAGE,
        source_ref="message://session-1/1",
        source_label="Initial requirement",
    )
    approved_solution_reference = ContextReference(
        reference_id="context-ref-2",
        kind=ContextReferenceKind.SOLUTION_ARTIFACT,
        source_ref="stage-artifact://artifact-solution-design-1",
        source_label="Approved solution artifact",
    )
    change_set = ChangeSet(
        change_set_id="changeset-1",
        workspace_ref="workspace://run-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        files=(
            ChangeSetFile(
                path="backend/app/context/source_resolver.py",
                operation=ChangeOperation.MODIFY,
                diff_ref="diff://changeset-1/source-resolver",
            ),
        ),
        context_references=(context_reference,),
        file_edit_trace_refs=(
            "file_edit_trace:run-1:stage-code-generation-1:backend/app/context/source_resolver.py",
        ),
        created_at=NOW,
    )
    stage_artifact = _stage_artifact(
        artifact_id="artifact-codegen",
        process={
            "tool_call_ref": "tool-call://run-1/stage-code-generation-1/read-file",
            "provider_call_ref": "provider-call://run-1/stage-code-generation-1/1",
            "tool_confirmation_trace_ref": (
                "tool-confirmation://run-1/stage-code-generation-1/1"
            ),
            "validation_ref": "validation://run-1/stage-code-generation-1/tests",
            "model_call_ref": "model-call://run-1/stage-code-generation-1/1",
            "process_ref": "process://run-1/stage-code-generation-1/context",
            "reasoning_trace_ref": "reasoning://run-1/stage-code-generation-1/summary",
            "process_refs": (
                "raw unstructured process text " * 40,
                "artifact://process/run-1/stage-code-generation-1/stable",
            ),
            "raw_output": "x" * 5000,
        },
    )

    resolved = ContextSourceResolver().resolve_context_references(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=(stage_artifact,),
        context_references=(context_reference, approved_solution_reference),
        change_sets=(change_set,),
        clarifications=(clarification,),
        approval_decisions=(approval,),
        allowed_context_run_ids=("run-1",),
        built_at=NOW,
    )

    context_blocks = {
        block.block_id: block for block in resolved.context_references
    }
    requirement_block = context_blocks["context-reference:context-ref-1"]
    assert requirement_block.section is ContextEnvelopeSection.CONTEXT_REFERENCES
    assert requirement_block.trust_level is ContextTrustLevel.UNTRUSTED_OBSERVATION
    assert requirement_block.boundary_action is ContextBoundaryAction.QUARANTINE
    assert "message://session-1/1" in requirement_block.summary

    solution_block = context_blocks["context-reference:context-ref-2"]
    assert solution_block.trust_level is ContextTrustLevel.TRUSTED_REFERENCE
    assert solution_block.boundary_action is ContextBoundaryAction.ALLOW
    assert "stage-artifact://artifact-solution-design-1" in solution_block.summary

    working_summary = " ".join(block.summary for block in resolved.working_observations)
    assert "changeset://changeset-1" in working_summary
    assert "diff://changeset-1/source-resolver" in working_summary
    assert (
        "file_edit_trace:run-1:stage-code-generation-1:"
        "backend/app/context/source_resolver.py"
    ) in working_summary
    assert "tool-call://run-1/stage-code-generation-1/read-file" in working_summary
    assert "provider-call://run-1/stage-code-generation-1/1" in working_summary
    assert (
        "tool-confirmation://run-1/stage-code-generation-1/1"
        in working_summary
    )
    assert "validation://run-1/stage-code-generation-1/tests" in working_summary
    assert "raw unstructured process text" not in working_summary
    assert "xxxxx" not in working_summary
    assert all(
        block.boundary_action is ContextBoundaryAction.REFERENCE_ONLY
        for block in resolved.working_observations
    )
    trust_by_block_id = {
        block.block_id: block.trust_level
        for block in resolved.working_observations
    }
    assert trust_by_block_id["change-set:changeset-1"] is ContextTrustLevel.TRUSTED_REFERENCE
    assert trust_by_block_id["artifact-process-refs:artifact-codegen"] is (
        ContextTrustLevel.UNTRUSTED_OBSERVATION
    )
    source_kinds = {
        source.source_ref: source.source_kind
        for block in resolved.working_observations
        for source in block.sources
    }
    assert source_kinds["provider-call://run-1/stage-code-generation-1/1"] == (
        "provider_call_ref"
    )
    assert source_kinds["model-call://run-1/stage-code-generation-1/1"] == (
        "model_call_ref"
    )
    assert source_kinds["tool-confirmation://run-1/stage-code-generation-1/1"] == (
        "tool_confirmation_trace_ref"
    )
    assert source_kinds["validation://run-1/stage-code-generation-1/tests"] == (
        "validation_ref"
    )
    assert source_kinds["process://run-1/stage-code-generation-1/context"] == (
        "process_ref"
    )
    assert source_kinds[
        "artifact://process/run-1/stage-code-generation-1/stable"
    ] == "process_ref"

    assert (
        resolved.reasoning_trace[0].section
        is ContextEnvelopeSection.REASONING_TRACE
    )
    assert (
        "reasoning://run-1/stage-code-generation-1/summary"
        in resolved.reasoning_trace[0].summary
    )
    assert (
        resolved.reasoning_trace[0].boundary_action
        is ContextBoundaryAction.REFERENCE_ONLY
    )

    recent = resolved.recent_observations
    assert [block.trust_level for block in recent] == [
        ContextTrustLevel.UNTRUSTED_OBSERVATION,
        ContextTrustLevel.UNTRUSTED_OBSERVATION,
    ]
    assert [block.boundary_action for block in recent] == [
        ContextBoundaryAction.QUARANTINE,
        ContextBoundaryAction.QUARANTINE,
    ]
    assert "Yes, include regression coverage." in recent[0].summary
    assert "Need a clearer rollback story." in recent[1].summary


def test_resolve_context_references_filters_foreign_run_observations() -> None:
    from backend.app.context.source_resolver import ContextSourceResolver

    foreign_clarification = ClarificationRecordModel(
        clarification_id="clarification-foreign",
        run_id="run-foreign",
        stage_run_id="stage-foreign",
        question="Foreign question?",
        answer="Foreign answer.",
        payload_ref="payload://clarification-foreign",
        graph_interrupt_ref="graph-interrupt-foreign",
        requested_at=NOW,
        answered_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    foreign_change_set = ChangeSet(
        change_set_id="changeset-foreign",
        workspace_ref="workspace://run-foreign",
        run_id="run-foreign",
        stage_run_id="stage-foreign",
        files=(
            ChangeSetFile(
                path="backend/app/foreign.py",
                operation=ChangeOperation.MODIFY,
                diff_ref="diff://foreign",
            ),
        ),
        created_at=NOW,
    )

    resolved = ContextSourceResolver().resolve_context_references(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=(
            _stage_artifact(artifact_id="artifact-foreign", run_id="run-foreign"),
        ),
        context_references=(),
        change_sets=(foreign_change_set,),
        clarifications=(foreign_clarification,),
        approval_decisions=(),
        allowed_context_run_ids=("run-1",),
        built_at=NOW,
    )

    assert resolved.working_observations == ()
    assert resolved.reasoning_trace == ()
    assert resolved.recent_observations == ()


def test_resolve_context_references_filters_embedded_foreign_refs_and_unknown_schemes() -> None:
    from backend.app.context.source_resolver import ContextSourceResolver

    foreign_tool_reference = ContextReference(
        reference_id="context-ref-foreign-tool",
        kind=ContextReferenceKind.TOOL_OBSERVATION,
        source_ref="tool-call://run-foreign/stage-foreign/1",
        source_label="Foreign tool observation",
    )
    local_change_set = ChangeSet(
        change_set_id="changeset-local",
        workspace_ref="workspace://run-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        files=(
            ChangeSetFile(
                path="backend/app/context/source_resolver.py",
                operation=ChangeOperation.MODIFY,
                diff_ref="diff://changeset-local/source-resolver",
            ),
        ),
        file_edit_trace_refs=(
            "file_edit_trace:run-foreign:stage-foreign:backend/app/foreign.py",
            "file_edit_trace:run-1:stage-code-generation-1:backend/app/context/source_resolver.py",
        ),
        created_at=NOW,
    )
    stable_hash = f"sha256:{'a' * 64}"
    stage_artifact = _stage_artifact(
        artifact_id="artifact-local",
        process={
            "provider_call_ref": "provider-call://run-foreign/stage-foreign/1",
            "tool_call_ref": "tool-call://run-1/stage-code-generation-1/read-file",
            "process_refs": (
                "artifact://process/run-foreign/stage-foreign/stable",
                "artifact://process/run-1/stage-code-generation-1/stable",
                "https://example.com/not-allowed",
            ),
            "reasoning_trace_refs": (
                "reasoning://run-foreign/stage-foreign/summary",
                "reasoning://run-1/stage-code-generation-1/summary",
                stable_hash,
            ),
        },
    )

    resolved = ContextSourceResolver().resolve_context_references(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=(stage_artifact,),
        context_references=(foreign_tool_reference,),
        change_sets=(local_change_set,),
        clarifications=(),
        approval_decisions=(),
        allowed_context_run_ids=("run-1",),
        built_at=NOW,
    )

    assert resolved.context_references == ()
    working_summary = " ".join(block.summary for block in resolved.working_observations)
    assert "tool-call://run-1/stage-code-generation-1/read-file" in working_summary
    assert (
        "artifact://process/run-1/stage-code-generation-1/stable"
        in working_summary
    )
    assert (
        "file_edit_trace:run-1:stage-code-generation-1:"
        "backend/app/context/source_resolver.py"
    ) in working_summary
    assert "provider-call://run-foreign/stage-foreign/1" not in working_summary
    assert "artifact://process/run-foreign/stage-foreign/stable" not in working_summary
    assert "https://example.com/not-allowed" not in working_summary
    assert "file_edit_trace:run-foreign:stage-foreign:backend/app/foreign.py" not in working_summary

    reasoning_summary = " ".join(block.summary for block in resolved.reasoning_trace)
    assert stable_hash in reasoning_summary
    assert "reasoning://run-1/stage-code-generation-1/summary" in reasoning_summary
    assert "reasoning://run-foreign/stage-foreign/summary" not in reasoning_summary


def test_resolve_context_references_rejects_unknown_context_reference_scheme_and_bounds_summary() -> None:
    from backend.app.context.source_resolver import ContextSourceResolver

    unknown_scheme_reference = ContextReference(
        reference_id="context-ref-unknown",
        kind=ContextReferenceKind.SOLUTION_ARTIFACT,
        source_ref="foo://run-1/not-allowed",
        source_label="Unexpected scheme",
    )
    long_reference = ContextReference(
        reference_id="context-ref-long",
        kind=ContextReferenceKind.REVIEW_FEEDBACK,
        source_ref="message://session-1/very-long-feedback",
        source_label="review-feedback-" + ("x" * 400),
    )

    resolved = ContextSourceResolver().resolve_context_references(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-code-generation-1",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=(),
        context_references=(unknown_scheme_reference, long_reference),
        change_sets=(),
        clarifications=(),
        approval_decisions=(),
        allowed_context_run_ids=("run-1",),
        built_at=NOW,
    )

    assert len(resolved.context_references) == 1
    block = resolved.context_references[0]
    assert block.block_id == "context-reference:context-ref-long"
    assert block.trust_level is ContextTrustLevel.UNTRUSTED_OBSERVATION
    assert block.boundary_action is ContextBoundaryAction.QUARANTINE
    assert len(block.summary) <= 240
    assert block.summary.endswith("...")
    assert "foo://run-1/not-allowed" not in block.summary
