from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas import common


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def build_section(title: str, records: dict[str, object] | None = None):
    from backend.app.schemas.inspector import InspectorSection

    return InspectorSection(
        title=title,
        records=records or {f"{title.lower()}_ref": f"{title.lower()}-record-1"},
        stable_refs=[f"{title.lower()}-ref-1"],
    )


def build_implementation_plan():
    from backend.app.schemas.run import (
        ImplementationPlanTaskRead,
        SolutionImplementationPlanRead,
    )

    return SolutionImplementationPlanRead(
        plan_id="plan-solution-design-1",
        source_stage_run_id="stage-solution-1",
        tasks=[
            ImplementationPlanTaskRead(
                task_id="task-codegen-1",
                order_index=1,
                title="Generate implementation from approved design",
                depends_on_task_ids=[],
                target_files=["backend/app/services/runtime.py"],
                target_modules=["backend.app.services.runtime"],
                acceptance_refs=["solution-design-acceptance-1"],
                verification_commands=[
                    "uv run --no-sync python -m pytest backend/tests/runtime -q"
                ],
                risk_handling="Stop if implementation plan references missing files.",
            )
        ],
        downstream_refs=[
            "code_generation",
            "test_generation_execution",
            "code_review",
        ],
        created_at=NOW,
    )


def test_stage_inspector_groups_sections_and_stable_traces() -> None:
    from backend.app.schemas.inspector import StageInspectorProjection
    from backend.app.schemas.metrics import MetricSet

    inspector = StageInspectorProjection(
        stage_run_id="stage-solution-1",
        run_id="run-1",
        stage_type=common.StageType.SOLUTION_DESIGN,
        status=common.StageStatus.COMPLETED,
        attempt_index=1,
        started_at=NOW,
        ended_at=NOW,
        identity=build_section(
            "identity",
            {
                "stage_run_id": "stage-solution-1",
                "run_id": "run-1",
                "stage_type": "solution_design",
            },
        ),
        input=build_section(
            "input",
            {
                "requirement_artifact_ref": "artifact-requirement-1",
                "clarification_record_refs": ["clarification-1"],
            },
        ),
        process=build_section(
            "process",
            {
                "decision_trace_ref": "decision-trace-1",
                "provider_retry_trace": "provider-retry-trace-1",
                "provider_circuit_breaker_trace": "provider-circuit-breaker-trace-1",
                "tool_confirmation_trace": "tool-confirmation-trace-1",
            },
        ),
        output=build_section(
            "output",
            {
                "solution_artifact_ref": "artifact-solution-1",
                "implementation_plan_id": "plan-solution-design-1",
            },
        ),
        artifacts=build_section(
            "artifacts",
            {
                "artifact_refs": ["artifact-solution-1"],
                "approval_result_refs": ["approval-result-1"],
            },
        ),
        metrics=MetricSet(
            duration_ms=4200,
            input_tokens=1000,
            output_tokens=600,
            total_tokens=1600,
            attempt_index=1,
            context_file_count=4,
            reasoning_step_count=6,
            tool_call_count=1,
        ),
        implementation_plan=build_implementation_plan(),
        tool_confirmation_trace_refs=["tool-confirmation-trace-1"],
        provider_retry_trace_refs=["provider-retry-trace-1"],
        provider_circuit_breaker_trace_refs=["provider-circuit-breaker-trace-1"],
        approval_result_refs=["approval-result-1"],
    )

    dumped = inspector.model_dump(mode="json")
    assert list(
        key
        for key in dumped
        if key in {"identity", "input", "process", "output", "artifacts", "metrics"}
    ) == ["identity", "input", "process", "output", "artifacts", "metrics"]
    assert dumped["stage_type"] == "solution_design"
    assert dumped["implementation_plan"]["tasks"][0]["task_id"] == "task-codegen-1"
    assert dumped["tool_confirmation_trace_refs"] == ["tool-confirmation-trace-1"]
    assert dumped["provider_retry_trace_refs"] == ["provider-retry-trace-1"]
    assert dumped["provider_circuit_breaker_trace_refs"] == [
        "provider-circuit-breaker-trace-1"
    ]
    assert dumped["approval_result_refs"] == ["approval-result-1"]
    assert "generated_test_count" not in dumped["metrics"]

    with pytest.raises(ValidationError):
        StageInspectorProjection(
            **{
                **inspector.model_dump(mode="json"),
                "stage_type": "solution_validation",
            }
        )


def test_tool_confirmation_inspector_is_not_approval_or_control_item_detail() -> None:
    from backend.app.schemas.inspector import ToolConfirmationInspectorProjection
    from backend.app.schemas.metrics import MetricSet

    inspector = ToolConfirmationInspectorProjection(
        tool_confirmation_id="tool-confirmation-1",
        run_id="run-1",
        stage_run_id="stage-test-1",
        status=common.ToolConfirmationStatus.PENDING,
        requested_at=NOW,
        responded_at=None,
        tool_name="bash",
        command_preview="npm install",
        target_summary="frontend/package-lock.json",
        risk_level=common.ToolRiskLevel.HIGH_RISK,
        risk_categories=[common.ToolRiskCategory.DEPENDENCY_CHANGE],
        reason="The command changes dependencies.",
        expected_side_effects=["May update the lockfile."],
        decision=None,
        identity=build_section("identity"),
        input=build_section("input"),
        process=build_section(
            "process",
            {
                "risk_decision_ref": "risk-decision-1",
                "audit_ref": "audit-tool-confirmation-1",
            },
        ),
        output=build_section("output"),
        artifacts=build_section("artifacts"),
        metrics=MetricSet(duration_ms=900, tool_call_count=1),
    )

    dumped = inspector.model_dump(mode="json")
    assert dumped["risk_level"] == "high_risk"
    assert dumped["risk_categories"] == ["dependency_change"]
    assert "approval_id" not in dumped
    assert "approval_type" not in dumped
    assert "approve_action" not in dumped
    assert "reject_action" not in dumped
    assert "control_record_id" not in dumped

    with pytest.raises(ValidationError):
        ToolConfirmationInspectorProjection(
            **{
                **inspector.model_dump(mode="json"),
                "risk_level": "low_risk_write",
            }
        )

    with pytest.raises(ValidationError):
        ToolConfirmationInspectorProjection(
            **{
                **inspector.model_dump(mode="json"),
                "approval_id": "approval-1",
            }
        )

    with pytest.raises(ValidationError):
        ToolConfirmationInspectorProjection(
            **{
                **inspector.model_dump(mode="json"),
                "control_record_id": "control-1",
            }
        )


def test_control_item_inspector_rejects_tool_confirmation_semantics() -> None:
    from backend.app.schemas.inspector import ControlItemInspectorProjection
    from backend.app.schemas.metrics import MetricSet

    inspector = ControlItemInspectorProjection(
        control_record_id="control-retry-1",
        run_id="run-1",
        control_type=common.ControlItemType.RETRY,
        source_stage_type=common.StageType.CODE_REVIEW,
        target_stage_type=common.StageType.CODE_GENERATION,
        occurred_at=NOW,
        identity=build_section("identity"),
        input=build_section("input"),
        process=build_section(
            "process",
            {
                "trigger_payload_ref": "retry-payload-1",
                "history_attempt_refs": ["run-1-attempt-1"],
            },
        ),
        output=build_section(
            "output",
            {
                "target_stage_type": "code_generation",
                "result_status": "accepted",
            },
        ),
        artifacts=build_section("artifacts"),
        metrics=MetricSet(retry_index=2, source_attempt_index=1),
    )

    dumped = inspector.model_dump(mode="json")
    assert dumped["control_type"] == "retry"
    assert dumped["metrics"] == {"retry_index": 2, "source_attempt_index": 1}

    with pytest.raises(ValidationError):
        ControlItemInspectorProjection(
            **{
                **inspector.model_dump(mode="json"),
                "control_type": "tool_confirmation",
            }
        )

    with pytest.raises(ValidationError):
        ControlItemInspectorProjection(
            **{
                **inspector.model_dump(mode="json"),
                "control_type": "system_status",
            }
        )


def test_delivery_result_detail_and_metric_set_hide_inapplicable_metrics() -> None:
    from backend.app.schemas.inspector import DeliveryResultDetailProjection
    from backend.app.schemas.metrics import MetricSet

    metrics = MetricSet(
        duration_ms=3000,
        changed_file_count=5,
        delivery_artifact_count=2,
    )
    assert metrics.model_dump(mode="json") == {
        "duration_ms": 3000,
        "changed_file_count": 5,
        "delivery_artifact_count": 2,
    }

    detail = DeliveryResultDetailProjection(
        delivery_record_id="delivery-record-1",
        run_id="run-1",
        delivery_mode=common.DeliveryMode.DEMO_DELIVERY,
        status="succeeded",
        created_at=NOW,
        identity=build_section("identity"),
        input=build_section(
            "input",
            {
                "delivery_snapshot_ref": "delivery-snapshot-1",
                "test_result_ref": "test-result-1",
                "review_result_ref": "review-result-1",
            },
        ),
        process=build_section(
            "process",
            {
                "delivery_process_ref": "delivery-process-1",
                "delivery_stage_ref": "stage-delivery-1",
            },
        ),
        output=build_section(
            "output",
            {
                "summary": "Demo delivery completed.",
                "test_summary": "45 tests passed.",
                "review_summary": "No blocking findings.",
            },
        ),
        artifacts=build_section(
            "artifacts",
            {
                "delivery_artifact_refs": ["artifact-delivery-1"],
                "branch_name": "demo/run-1",
            },
        ),
        metrics=metrics,
    )

    dumped = detail.model_dump(mode="json")
    assert dumped["delivery_mode"] == "demo_delivery"
    assert dumped["status"] == "succeeded"
    assert dumped["metrics"] == {
        "duration_ms": 3000,
        "changed_file_count": 5,
        "delivery_artifact_count": 2,
    }

    with pytest.raises(ValidationError):
        DeliveryResultDetailProjection(
            **{
                **detail.model_dump(mode="json"),
                "status": "failed",
            }
        )
