from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.domain.enums import ApprovalType, StageType, TemplateSource
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    PlatformHardLimits,
    RuntimeLimitSnapshotRead,
)
from backend.app.services.graph_compiler import GraphCompiler


NOW = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)


class CapturingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FailingRunLogWriter:
    def write_run_log(self, record: LogRecordInput) -> object:
        raise RuntimeError("log sink unavailable")


def template_snapshot(
    *,
    auto_regression_enabled: bool = True,
    max_auto_regression_retries: int = 2,
    run_id: str = "run-1",
) -> TemplateSnapshot:
    stages = tuple(StageType)
    return TemplateSnapshot(
        snapshot_ref=f"template-snapshot-{run_id}",
        run_id=run_id,
        source_template_id="template-1",
        source_template_name="Function One",
        source_template=TemplateSource.SYSTEM_TEMPLATE,
        source_template_updated_at=NOW,
        fixed_stage_sequence=stages,
        stage_role_bindings=tuple(
            StageRoleSnapshot(
                stage_type=stage,
                role_id=f"role-{stage.value}",
                system_prompt=f"Prompt for {stage.value}.",
                provider_id="provider-1",
            )
            for stage in stages
        ),
        approval_checkpoints=(
            ApprovalType.SOLUTION_DESIGN_APPROVAL,
            ApprovalType.CODE_REVIEW_APPROVAL,
        ),
        auto_regression_enabled=auto_regression_enabled,
        max_auto_regression_retries=max_auto_regression_retries,
        created_at=NOW,
    )


def runtime_limit_snapshot(
    *,
    max_auto_regression_retries: int = 2,
    run_id: str = "run-1",
) -> RuntimeLimitSnapshotRead:
    return RuntimeLimitSnapshotRead(
        snapshot_id=f"runtime-limit-snapshot-{run_id}",
        run_id=run_id,
        agent_limits=AgentRuntimeLimits(
            max_react_iterations_per_stage=30,
            max_tool_calls_per_stage=80,
            max_file_edit_count=20,
            max_patch_attempts_per_file=3,
            max_structured_output_repair_attempts=3,
            max_auto_regression_retries=max_auto_regression_retries,
            max_clarification_rounds=5,
            max_no_progress_iterations=5,
        ),
        context_limits=ContextLimits(),
        source_config_version="runtime-settings-v1",
        hard_limits_version="platform-hard-limits-v1",
        schema_version="runtime-limit-snapshot-v1",
        created_at=NOW,
    )


def graph_definition(
    *,
    template: TemplateSnapshot | None = None,
    runtime_limit: RuntimeLimitSnapshotRead | None = None,
) -> GraphDefinition:
    resolved_template = template or template_snapshot()
    resolved_runtime = runtime_limit or runtime_limit_snapshot(
        max_auto_regression_retries=resolved_template.max_auto_regression_retries,
        run_id=resolved_template.run_id,
    )
    return GraphCompiler(now=lambda: NOW).compile(
        template_snapshot=resolved_template,
        runtime_limit_snapshot=resolved_runtime,
    )


def trace_context() -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="span-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-code-review-1",
        graph_thread_id="graph-thread-1",
        created_at=NOW,
    )


def code_review_artifact(
    *,
    regression_decision: str = "changes_requested",
    issue_list: list[dict[str, object]] | None = None,
    fix_requirements: list[dict[str, object]] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    return {
        "artifact_type": "CodeReviewArtifact",
        "review_report": {"summary": "Review found issues."},
        "issue_list": issue_list
        if issue_list is not None
        else [{"severity": "important", "evidence_refs": ["evidence://issue-1"]}],
        "risk_assessment": {"risk": "medium"},
        "regression_decision": regression_decision,
        "fix_requirements": fix_requirements
        if fix_requirements is not None
        else [{"summary": "Fix the failing behavior."}],
        "evidence_refs": evidence_refs
        if evidence_refs is not None
        else ["evidence://review-1"],
        "changeset_refs": ["changeset://run-1/1"],
        "test_result_refs": ["test-result://run-1/1"],
    }


def test_resolve_max_auto_regression_retries_uses_frozen_template_runtime_graph_and_hard_limit() -> None:
    from backend.app.runtime.auto_regression import AutoRegressionPolicy

    template = template_snapshot(max_auto_regression_retries=3)
    runtime = runtime_limit_snapshot(max_auto_regression_retries=3)
    graph = graph_definition(template=template, runtime_limit=runtime)
    hard_limits = PlatformHardLimits()

    resolved = AutoRegressionPolicy(
        platform_hard_limits=hard_limits,
    ).resolve_max_auto_regression_retries(
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
    )

    assert resolved == 3
    assert resolved == hard_limits.agent_limits.max_auto_regression_retries


def test_should_retry_review_issue_routes_changes_requested_back_to_code_generation_and_logs() -> None:
    from backend.app.runtime.auto_regression import (
        AUTO_REGRESSION_ROUTE_KEY,
        AutoRegressionPolicy,
    )

    writer = CapturingRunLogWriter()
    template = template_snapshot(max_auto_regression_retries=2)
    runtime = runtime_limit_snapshot(max_auto_regression_retries=2)
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = AutoRegressionPolicy(
        log_writer=writer,
        now=lambda: NOW,
    ).should_retry_review_issue(
        code_review_artifact=code_review_artifact(),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is True
    assert decision.approval_allowed is False
    assert decision.status == "retry_scheduled"
    assert decision.retry_index == 1
    assert decision.route_key == AUTO_REGRESSION_ROUTE_KEY
    assert decision.return_stage is StageType.CODE_GENERATION
    assert writer.records[0].trace_context.trace_id == "trace-1"
    assert writer.records[0].source == "runtime.auto_regression"
    assert writer.records[0].payload.summary["status"] == "retry_scheduled"
    assert "Review found issues" not in str(writer.records[0].payload.summary)


def test_stable_review_skips_retry_and_allows_code_review_approval() -> None:
    from backend.app.runtime.auto_regression import should_retry_review_issue

    template = template_snapshot()
    runtime = runtime_limit_snapshot()
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = should_retry_review_issue(
        code_review_artifact=code_review_artifact(regression_decision="approved"),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is False
    assert decision.approval_allowed is True
    assert decision.status == "skipped"
    assert decision.reason == "stable_review"
    assert decision.route_key is None


def test_template_disabled_auto_regression_skips_retry_from_frozen_template_snapshot() -> None:
    from backend.app.runtime.auto_regression import should_retry_review_issue

    template = template_snapshot(
        auto_regression_enabled=False,
        max_auto_regression_retries=0,
    )
    runtime = runtime_limit_snapshot(max_auto_regression_retries=0)
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = should_retry_review_issue(
        code_review_artifact=code_review_artifact(),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is False
    assert decision.approval_allowed is True
    assert decision.reason == "auto_regression_disabled"


def test_missing_review_evidence_does_not_schedule_automatic_regression() -> None:
    from backend.app.runtime.auto_regression import should_retry_review_issue

    template = template_snapshot()
    runtime = runtime_limit_snapshot()
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = should_retry_review_issue(
        code_review_artifact=code_review_artifact(
            issue_list=[],
            fix_requirements=[],
            evidence_refs=[],
        ),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is False
    assert decision.approval_allowed is False
    assert decision.reason == "missing_review_evidence"


def test_code_review_artifact_helper_preserves_empty_top_level_evidence_refs() -> None:
    artifact = code_review_artifact(evidence_refs=[])

    assert artifact["evidence_refs"] == []


def test_placeholder_review_evidence_does_not_schedule_automatic_regression() -> None:
    from backend.app.runtime.auto_regression import should_retry_review_issue

    template = template_snapshot()
    runtime = runtime_limit_snapshot()
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = should_retry_review_issue(
        code_review_artifact=code_review_artifact(
            issue_list=[
                {
                    "severity": " ",
                    "evidence_refs": [" "],
                }
            ],
            fix_requirements=[{"summary": " "}],
            evidence_refs=[" "],
        ),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is False
    assert decision.approval_allowed is False
    assert decision.reason == "missing_review_evidence"


def test_unstructured_placeholder_review_evidence_does_not_schedule_regression() -> None:
    from backend.app.runtime.auto_regression import should_retry_review_issue

    template = template_snapshot()
    runtime = runtime_limit_snapshot()
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = should_retry_review_issue(
        code_review_artifact=code_review_artifact(
            issue_list=["placeholder"],
            fix_requirements=["placeholder"],
            evidence_refs=["placeholder"],
        ),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is False
    assert decision.approval_allowed is False
    assert decision.reason == "missing_review_evidence"


@pytest.mark.parametrize(
    ("issue_list", "fix_requirements", "evidence_refs"),
    [
        (
            [
                {
                    "body": "placeholder",
                    "evidence_refs": ["evidence://issue-placeholder"],
                }
            ],
            [{"summary": "placeholder"}],
            ["evidence://review-placeholder"],
        ),
        (
            [
                {
                    "severity": "placeholder",
                    "evidence_refs": ["artifact-issue-placeholder"],
                }
            ],
            [{"summary": "placeholder"}],
            ["artifact-review-placeholder"],
        ),
    ],
)
def test_structured_placeholder_review_text_does_not_schedule_regression(
    issue_list: list[dict[str, object]],
    fix_requirements: list[dict[str, object]],
    evidence_refs: list[str],
) -> None:
    from backend.app.runtime.auto_regression import should_retry_review_issue

    template = template_snapshot()
    runtime = runtime_limit_snapshot()
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = should_retry_review_issue(
        code_review_artifact=code_review_artifact(
            issue_list=issue_list,
            fix_requirements=fix_requirements,
            evidence_refs=evidence_refs,
        ),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is False
    assert decision.approval_allowed is False
    assert decision.reason == "missing_review_evidence"


def test_retry_limit_exhaustion_blocks_approval_and_records_exhausted_status() -> None:
    from backend.app.runtime.auto_regression import AutoRegressionPolicy

    writer = CapturingRunLogWriter()
    template = template_snapshot(max_auto_regression_retries=1)
    runtime = runtime_limit_snapshot(max_auto_regression_retries=1)
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = AutoRegressionPolicy(
        log_writer=writer,
        now=lambda: NOW,
    ).should_retry_review_issue(
        code_review_artifact=code_review_artifact(),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=1,
        source_attempt_index=1,
        trace_context=trace_context(),
    )

    assert decision.should_retry is False
    assert decision.approval_allowed is False
    assert decision.status == "exhausted"
    assert decision.reason == "retry_limit_exhausted"
    assert writer.records[0].payload.summary["status"] == "exhausted"


def test_run_log_write_failure_does_not_mask_policy_decision() -> None:
    from backend.app.runtime.auto_regression import AutoRegressionPolicy

    template = template_snapshot()
    runtime = runtime_limit_snapshot()
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = AutoRegressionPolicy(
        log_writer=FailingRunLogWriter(),
        now=lambda: NOW,
    ).should_retry_review_issue(
        code_review_artifact=code_review_artifact(),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is True


def test_unknown_regression_decision_is_not_copied_to_decision_or_log_summary() -> None:
    from backend.app.runtime.auto_regression import AutoRegressionPolicy

    raw_regression_decision = (
        "Stack trace at C:\\workspace\\run with credential sk-test-secret"
    )
    writer = CapturingRunLogWriter()
    template = template_snapshot()
    runtime = runtime_limit_snapshot()
    graph = graph_definition(template=template, runtime_limit=runtime)

    decision = AutoRegressionPolicy(
        log_writer=writer,
        now=lambda: NOW,
    ).should_retry_review_issue(
        code_review_artifact=code_review_artifact(
            regression_decision=raw_regression_decision,
        ),
        template_snapshot=template,
        runtime_limit_snapshot=runtime,
        graph_definition=graph,
        attempts_used=0,
        source_attempt_index=0,
        trace_context=trace_context(),
    )

    assert decision.should_retry is False
    assert decision.approval_allowed is False
    assert decision.reason == "missing_review_evidence"
    assert decision.regression_decision is None
    assert raw_regression_decision not in str(writer.records[0].payload.summary)
    assert "sk-test-secret" not in str(writer.records[0].payload.summary)
    assert "C:\\workspace" not in str(writer.records[0].payload.summary)


@pytest.mark.parametrize(
    "updates",
    [
        {
            "status": "skipped",
            "reason": "stable_review",
            "retry_index": 1,
        },
        {
            "status": "skipped",
            "reason": "stable_review",
            "route_key": "review_regression_retry",
        },
        {
            "status": "skipped",
            "reason": "stable_review",
            "return_stage": StageType.CODE_GENERATION,
        },
        {
            "status": "exhausted",
            "reason": "retry_limit_exhausted",
            "approval_allowed": True,
        },
        {
            "status": "skipped",
            "reason": "missing_review_evidence",
            "approval_allowed": True,
        },
        {
            "status": "skipped",
            "reason": "retry_limit_exhausted",
        },
        {
            "status": "retry_scheduled",
            "reason": "changes_requested",
        },
    ],
)
def test_auto_regression_decision_rejects_inconsistent_non_retry_shapes(
    updates: dict[str, object],
) -> None:
    from backend.app.runtime.auto_regression import AutoRegressionDecision

    values = {
        "run_id": "run-1",
        "stage_run_id": "stage-run-code-review-1",
        "should_retry": False,
        "approval_allowed": False,
        "status": "skipped",
        "reason": "stable_review",
        "regression_decision": "approved",
        "source_attempt_index": 0,
        "attempts_used": 0,
        "max_retries": 2,
    }
    values.update(updates)

    with pytest.raises(ValueError):
        AutoRegressionDecision(**values)


def test_graph_retry_policy_auto_regression_enabled_must_be_strict_bool() -> None:
    from backend.app.runtime.auto_regression import AutoRegressionPolicy

    template = template_snapshot(auto_regression_enabled=True)
    runtime = runtime_limit_snapshot()
    graph = graph_definition(template=template, runtime_limit=runtime)
    malformed_graph = graph.model_copy(
        update={
            "retry_policy": {
                **dict(graph.retry_policy),
                "auto_regression_enabled": 1,
            }
        }
    )

    with pytest.raises(ValueError, match="auto_regression_enabled"):
        AutoRegressionPolicy().resolve_max_auto_regression_retries(
            template_snapshot=template,
            runtime_limit_snapshot=runtime,
            graph_definition=malformed_graph,
        )
