from __future__ import annotations

from pathlib import Path

from backend.app.db.base import DatabaseRole
from backend.app.db.models.runtime import ApprovalRequestModel, PipelineRunModel
from backend.app.domain.enums import (
    ApprovalStatus,
    RunStatus,
    StageType,
)
from backend.app.services.projections.workspace import WorkspaceProjectionService
from backend.tests.services.test_approval_creation import (
    NOW,
    build_manager,
    build_service,
    build_trace,
    seed_running_stage,
)


def test_approval_request_enters_workspace_feed_as_top_level_entry_and_keeps_source_stage(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.SOLUTION_DESIGN)
    service, _runtime_port, _log_writer = build_service(manager)

    result = service.create_solution_design_approval(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        payload_ref="solution-design-artifact-1",
        approval_object_excerpt="Review the proposed design.",
        risk_excerpt="Touches runtime orchestration.",
        approval_object_preview={"artifact_id": "solution-design-artifact-1"},
        trace_context=build_trace(stage_run_id="stage-run-1"),
    )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        workspace = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_session_workspace("session-1")

    dumped = workspace.model_dump(mode="json")
    assert dumped["session"]["status"] == "waiting_approval"
    assert dumped["session"]["latest_stage_type"] == "solution_design"
    assert dumped["current_stage_type"] == "solution_design"
    assert dumped["composer_state"] == {
        "mode": "waiting_approval",
        "is_input_enabled": False,
        "primary_action": "pause",
        "secondary_actions": ["terminate"],
        "bound_run_id": "run-1",
    }
    assert [entry["type"] for entry in dumped["narrative_feed"]] == [
        "approval_request"
    ]
    approval_entry = dumped["narrative_feed"][0]
    assert approval_entry["approval_id"] == result.approval_id
    assert approval_entry["approval_type"] == "solution_design_approval"
    assert approval_entry["status"] == "pending"
    assert approval_entry["is_actionable"] is True
    assert approval_entry["disabled_reason"] is None
    assert approval_entry["delivery_readiness_status"] is None
    assert approval_entry["open_settings_action"] is None
    assert approval_entry["approval_object_preview"] == {
        "artifact_id": "solution-design-artifact-1"
    }
    assert "control_item" not in approval_entry


def test_build_projection_marks_paused_or_non_pending_approvals_not_actionable(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.CODE_REVIEW)
    service, _runtime_port, _log_writer = build_service(manager)
    result = service.create_code_review_approval(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        payload_ref="code-review-artifact-1",
        approval_object_excerpt="Review code changes.",
        risk_excerpt=None,
        approval_object_preview={},
        trace_context=build_trace(stage_run_id="stage-run-1"),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, result.approval_id)
        run = session.get(PipelineRunModel, "run-1")
        assert approval is not None and run is not None
        run.status = RunStatus.PAUSED
        paused = service.build_approval_request_projection(
            approval=approval,
            run=run,
            approval_object_excerpt="Review code changes.",
            risk_excerpt=None,
            approval_object_preview={},
            occurred_at=NOW,
        )
        approval.status = ApprovalStatus.APPROVED
        completed = service.build_approval_request_projection(
            approval=approval,
            run=run,
            approval_object_excerpt="Review code changes.",
            risk_excerpt=None,
            approval_object_preview={},
            occurred_at=NOW,
        )

    assert paused.is_actionable is False
    assert (
        paused.disabled_reason
        == "Current run is paused; resume it to continue approval."
    )
    assert completed.is_actionable is False
    assert completed.disabled_reason == "Approval is no longer pending."
