from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.runtime import (
    RunControlRecordModel,
    StageArtifactModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    RunControlRecordType,
    SseEventType,
    StageType,
    ToolConfirmationStatus,
    ToolRiskLevel,
)
from backend.app.schemas import common
from backend.app.schemas.feed import (
    ExecutionNodeProjection,
    StageItemProjection,
    ToolConfirmationFeedEntry,
)
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.projections.inspector import (
    InspectorProjectionService,
    InspectorProjectionServiceError,
)
from backend.tests.projections.test_workspace_projection import (
    NOW,
    _manager,
    _seed_workspace,
    _trace,
)


FORBIDDEN_DETAIL_KEYS = {
    "approval_id",
    "approval_type",
    "approve_action",
    "reject_action",
    "control_type",
    "graph_thread_ref",
    "graph_thread_id",
}


def test_tool_confirmation_detail_projection_builds_sections_from_runtime_artifacts_and_events(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_primary_tool_confirmation_detail(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_tool_confirmation_detail("tool-confirmation-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["tool_confirmation_id"] == "tool-confirmation-1"
    assert dumped["run_id"] == "run-active"
    assert dumped["stage_run_id"] == "stage-active"
    assert dumped["status"] == "pending"
    assert dumped["tool_name"] == "bash"
    assert dumped["command_preview"] == "npm install"
    assert dumped["target_summary"] == "frontend/package-lock.json"
    assert dumped["risk_level"] == "high_risk"
    assert dumped["risk_categories"] == ["dependency_change", "network_download"]
    assert dumped["reason"] == "Installing dependencies changes lock files."
    assert dumped["expected_side_effects"] == ["package-lock update"]
    assert dumped["decision"] is None
    assert "control_record_id" not in dumped
    assert set(dumped) >= {
        "identity",
        "input",
        "process",
        "output",
        "artifacts",
        "metrics",
    }

    assert dumped["identity"]["records"] == {
        "tool_confirmation_id": "tool-confirmation-1",
        "run_id": "run-active",
        "stage_run_id": "stage-active",
        "stage_type": "code_generation",
        "status": "pending",
        "requested_at": (NOW + timedelta(minutes=7)).isoformat().replace(
            "+00:00", "Z"
        ),
        "responded_at": None,
    }
    assert dumped["input"]["records"]["confirmation_object_ref"] == "tool-call-1"
    assert dumped["input"]["records"]["tool_name"] == "bash"
    assert dumped["input"]["records"]["command_preview"] == "npm install"
    assert dumped["input"]["records"]["target_summary"] == "frontend/package-lock.json"
    assert dumped["input"]["records"]["alternative_path_summary"] == (
        "Use already installed dependencies if available."
    )
    assert dumped["input"]["records"]["context_refs"] == [
        "context-package-json",
        "context-lockfile",
    ]
    assert dumped["process"]["records"]["tool_confirmation_event"][
        "tool_confirmation_id"
    ] == "tool-confirmation-1"
    assert dumped["process"]["records"]["tool_confirmation_event"]["title"] == (
        "Allow dependency install for active confirmation"
    )
    assert dumped["process"]["records"]["tool_confirmation_event"]["allow_action"] == (
        "allow_once"
    )
    assert dumped["process"]["records"]["tool_confirmation_event"]["deny_action"] == (
        "deny_once"
    )
    assert dumped["process"]["records"]["tool_confirmation_trace_refs"] == [
        "process-tool-confirmation-1",
        "trace-tool-confirmation-primary",
        "trace-tool-confirmation-extra",
    ]
    assert dumped["process"]["records"]["tool_call_refs"] == ["tool-call-1"]
    assert dumped["process"]["records"]["tool_result_refs"] == ["tool-result-1"]
    assert dumped["process"]["records"]["user_decision"] is None
    assert dumped["process"]["records"]["process_ref"] == "process-tool-confirmation-1"
    assert dumped["process"]["records"]["audit_log_ref"] == (
        "audit-tool-confirmation-1"
    )
    assert dumped["process"]["records"]["alternative_path_summary"] == (
        "Use already installed dependencies if available."
    )
    assert dumped["process"]["records"]["confirmation_object_ref"] == "tool-call-1"
    assert dumped["process"]["records"]["control_record_id"] == "control-tool-1"
    assert dumped["process"]["records"]["alternative_path_judgment"] == {
        "alternative_path_summary": "Use already installed dependencies if available.",
        "result_status": "waiting_tool_confirmation",
    }
    assert dumped["process"]["records"]["allowed_tool_execution_process"] is None
    assert dumped["process"]["records"]["audit_refs"] == [
        "audit-tool-confirmation-1",
        "audit-extra-1",
    ]
    assert dumped["process"]["records"]["stage_node_refs"] == [
        "entry-stage-active",
        "entry-stage-tool-confirmation-context",
    ]
    assert dumped["process"]["records"]["graph_interrupt_ref"] == "interrupt-tool-1"
    assert dumped["process"]["log_refs"] == [
        "log-tool-confirmation-1",
        "log-confirmed-action-extra",
    ]
    assert dumped["output"]["records"]["result_snapshot"] == {
        "result_status": "waiting_tool_confirmation",
        "follow_up_refs": ["follow-up-tool-confirmation-1"],
    }
    assert dumped["output"]["records"]["result_status"] == (
        "waiting_tool_confirmation"
    )
    assert dumped["output"]["records"]["user_decision"] is None
    assert dumped["output"]["records"]["follow_up_refs"] == [
        "follow-up-tool-confirmation-1"
    ]
    assert dumped["output"]["records"]["follow_up_result"] == (
        "follow-up-tool-confirmation-1"
    )
    assert dumped["output"]["records"]["tool_result_ref"] == "tool-result-1"
    assert dumped["output"]["records"]["tool_result_refs"] == ["tool-result-1"]
    assert dumped["output"]["records"]["side_effect_refs"] == [
        "side-effect-lockfile-update"
    ]
    assert dumped["output"]["records"]["decision"] is None
    assert dumped["artifacts"]["records"]["artifact_refs"] == [
        "artifact-tool-confirmation-1",
        "artifact-tool-confirmation-confirmed-action-extra",
    ]
    assert dumped["artifacts"]["records"]["payload_refs"] == [
        "payload-tool-confirmation-1",
        "payload-tool-confirmation-confirmed-action-extra",
    ]
    assert dumped["artifacts"]["records"]["artifact_types"] == [
        "tool_confirmation_trace",
        "tool_confirmation_trace",
    ]
    assert dumped["artifacts"]["records"]["confirmation_object_ref"] == "tool-call-1"
    assert dumped["artifacts"]["records"]["audit_refs"] == [
        "audit-tool-confirmation-1",
        "audit-extra-1",
    ]
    assert dumped["artifacts"]["records"]["side_effect_refs"] == [
        "side-effect-lockfile-update"
    ]
    assert dumped["artifacts"]["records"]["context_refs"] == [
        "context-package-json",
        "context-lockfile",
    ]
    assert dumped["artifacts"]["log_refs"] == [
        "log-tool-confirmation-1",
        "log-confirmed-action-extra",
    ]
    assert dumped["metrics"] == {"duration_ms": 750, "tool_call_count": 1}
    assert "artifact-tool-confirmation-other" not in str(dumped)
    assert "artifact-tool-confirmation-shared-wrong-id" not in str(dumped)
    assert "payload-tool-confirmation-other" not in str(dumped)
    assert "payload-tool-confirmation-shared-wrong-id" not in str(dumped)
    assert "tool-result-shared-wrong-id" not in str(dumped)
    assert "tool-confirmation-other" not in str(dumped)
    _assert_forbidden_keys_absent(dumped)


def test_tool_confirmation_detail_projection_builds_allowed_and_denied_outcomes_without_schema_substitution(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_outcome_tool_confirmation(
        manager,
        tool_confirmation_id="tool-confirmation-allowed",
        artifact_id="artifact-tool-confirmation-allowed",
        payload_ref="payload-tool-confirmation-allowed",
        status=ToolConfirmationStatus.ALLOWED,
        user_decision=ToolConfirmationStatus.ALLOWED,
        result_status="allowed",
        result_ref="tool-result-allowed",
        follow_up_ref="follow-up-allowed-command",
        side_effect_refs=["side-effect-allowed-lockfile-update"],
        alternative_path_summary="No alternative path used.",
        denied_path_result=None,
        minutes=9,
    )
    _seed_outcome_tool_confirmation(
        manager,
        tool_confirmation_id="tool-confirmation-denied",
        artifact_id="artifact-tool-confirmation-denied",
        payload_ref="payload-tool-confirmation-denied",
        status=ToolConfirmationStatus.DENIED,
        user_decision=ToolConfirmationStatus.DENIED,
        result_status="alternative_path_selected",
        result_ref=None,
        follow_up_ref="follow-up-denied-alternative",
        side_effect_refs=[],
        alternative_path_summary="Use already installed dependencies if available.",
        denied_path_result={
            "status": "alternative_path_selected",
            "alternative_path_summary": (
                "Use already installed dependencies if available."
            ),
            "failure_result_status": "failed_without_safe_alternative",
            "waiting_result_status": "waiting_runtime_control",
        },
        minutes=10,
    )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        allowed = service.get_tool_confirmation_detail("tool-confirmation-allowed")
        denied = service.get_tool_confirmation_detail("tool-confirmation-denied")

    allowed_dumped = allowed.model_dump(mode="json")
    denied_dumped = denied.model_dump(mode="json")
    assert allowed_dumped["decision"] == "allowed"
    assert allowed_dumped["output"]["records"]["decision"] == "allowed"
    assert allowed_dumped["output"]["records"]["user_decision"] == "allowed"
    assert allowed_dumped["output"]["records"]["result_snapshot"] == {
        "result_status": "allowed",
        "result_ref": "tool-result-allowed",
        "follow_up_refs": ["follow-up-allowed-command"],
        "side_effect_refs": ["side-effect-allowed-lockfile-update"],
    }
    assert allowed_dumped["output"]["records"]["result_status"] == "allowed"
    assert allowed_dumped["output"]["records"]["follow_up_refs"] == [
        "follow-up-allowed-command"
    ]
    assert allowed_dumped["output"]["records"]["tool_result_refs"] == [
        "tool-result-allowed"
    ]
    assert allowed_dumped["output"]["records"]["tool_result_ref"] == (
        "tool-result-allowed"
    )
    assert allowed_dumped["output"]["records"]["follow_up_result"] == (
        "follow-up-allowed-command"
    )
    assert allowed_dumped["output"]["records"]["side_effect_refs"] == [
        "side-effect-allowed-lockfile-update"
    ]
    assert allowed_dumped["process"]["records"]["user_decision"] == "allowed"
    assert allowed_dumped["process"]["records"]["control_record_id"] == (
        "control-tool-confirmation-allowed"
    )
    assert allowed_dumped["process"]["records"]["allowed_tool_execution_process"] == {
        "tool_call_refs": ["tool-call-tool-confirmation-allowed"],
        "tool_result_refs": ["tool-result-allowed"],
        "result_status": "allowed",
        "side_effect_refs": ["side-effect-allowed-lockfile-update"],
    }
    assert allowed_dumped["artifacts"]["records"]["tool_result_refs"] == [
        "tool-result-allowed"
    ]
    assert allowed_dumped["input"]["records"]["alternative_path_summary"] == (
        "No alternative path used."
    )

    assert denied_dumped["decision"] == "denied"
    assert denied_dumped["output"]["records"]["decision"] == "denied"
    assert denied_dumped["output"]["records"]["user_decision"] == "denied"
    assert denied_dumped["output"]["records"]["result_snapshot"] == {
        "result_status": "alternative_path_selected",
        "follow_up_refs": ["follow-up-denied-alternative"],
        "denied_path_result": {
            "status": "alternative_path_selected",
            "alternative_path_summary": (
                "Use already installed dependencies if available."
            ),
            "failure_result_status": "failed_without_safe_alternative",
            "waiting_result_status": "waiting_runtime_control",
        },
    }
    assert denied_dumped["output"]["records"]["result_status"] == (
        "alternative_path_selected"
    )
    assert denied_dumped["output"]["records"]["follow_up_refs"] == [
        "follow-up-denied-alternative"
    ]
    assert denied_dumped["output"]["records"]["tool_result_refs"] == []
    assert denied_dumped["output"]["records"]["tool_result_ref"] is None
    assert denied_dumped["output"]["records"]["follow_up_result"] == (
        "follow-up-denied-alternative"
    )
    assert denied_dumped["output"]["records"]["side_effect_refs"] == []
    assert denied_dumped["output"]["records"]["denied_path_result"] == {
        "status": "alternative_path_selected",
        "alternative_path_summary": "Use already installed dependencies if available.",
        "failure_result_status": "failed_without_safe_alternative",
        "waiting_result_status": "waiting_runtime_control",
    }
    assert denied_dumped["process"]["records"]["user_decision"] == "denied"
    assert denied_dumped["process"]["records"]["control_record_id"] == (
        "control-tool-confirmation-denied"
    )
    assert denied_dumped["process"]["records"]["alternative_path_judgment"] == {
        "alternative_path_summary": (
            "Use already installed dependencies if available."
        ),
        "result_status": "alternative_path_selected",
    }
    assert denied_dumped["process"]["records"]["allowed_tool_execution_process"] is None
    assert denied_dumped["artifacts"]["records"]["tool_result_refs"] == []
    assert denied_dumped["input"]["records"]["alternative_path_summary"] == (
        "Use already installed dependencies if available."
    )
    _assert_forbidden_keys_absent(allowed_dumped)
    _assert_forbidden_keys_absent(denied_dumped)


def test_tool_confirmation_detail_projection_filters_to_matching_confirmation_only(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_primary_tool_confirmation_detail(manager)
    _seed_outcome_tool_confirmation(
        manager,
        tool_confirmation_id="tool-confirmation-unrelated",
        artifact_id="artifact-tool-confirmation-unrelated",
        payload_ref="payload-tool-confirmation-unrelated",
        status=ToolConfirmationStatus.PENDING,
        user_decision=None,
        result_status="waiting_tool_confirmation",
        result_ref="tool-result-unrelated",
        follow_up_ref="follow-up-unrelated",
        side_effect_refs=[],
        alternative_path_summary="Unrelated alternative.",
        denied_path_result=None,
        minutes=11,
    )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_tool_confirmation_detail("tool-confirmation-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["artifacts"]["records"]["artifact_refs"] == [
        "artifact-tool-confirmation-1",
        "artifact-tool-confirmation-confirmed-action-extra",
    ]
    assert dumped["process"]["records"]["tool_confirmation_event"][
        "tool_confirmation_id"
    ] == "tool-confirmation-1"
    assert "tool-confirmation-unrelated" not in str(dumped)
    assert "artifact-tool-confirmation-unrelated" not in str(dumped)
    assert "payload-tool-confirmation-unrelated" not in str(dumped)
    assert "tool-result-unrelated" not in str(dumped)


def test_tool_confirmation_detail_projection_requires_control_linkage_and_resolves_decision_fallbacks(
    tmp_path,
) -> None:
    missing_control_manager = _manager(tmp_path / "missing-control")
    _seed_workspace(missing_control_manager)

    with (
        missing_control_manager.session(DatabaseRole.CONTROL) as control_session,
        missing_control_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        missing_control_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_tool_confirmation_detail("tool-confirmation-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Tool confirmation inspector was not found."

    feed_decision_manager = _manager(tmp_path / "feed-decision")
    _seed_workspace(feed_decision_manager)
    _seed_primary_tool_confirmation_detail(
        feed_decision_manager,
        feed_decision=common.ToolConfirmationStatus.ALLOWED,
    )

    with (
        feed_decision_manager.session(DatabaseRole.CONTROL) as control_session,
        feed_decision_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        feed_decision_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_tool_confirmation_detail("tool-confirmation-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["process"]["records"]["tool_confirmation_event"]["decision"] == (
        "allowed"
    )
    assert dumped["decision"] == "allowed"
    assert dumped["process"]["records"]["user_decision"] == "allowed"
    assert dumped["output"]["records"]["decision"] == "allowed"
    assert dumped["output"]["records"]["user_decision"] == "allowed"

    artifact_decision_manager = _manager(tmp_path / "artifact-decision")
    _seed_workspace(artifact_decision_manager)
    _seed_primary_tool_confirmation_detail(
        artifact_decision_manager,
        artifact_decision=ToolConfirmationStatus.DENIED,
    )

    with (
        artifact_decision_manager.session(DatabaseRole.CONTROL) as control_session,
        artifact_decision_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        artifact_decision_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_tool_confirmation_detail("tool-confirmation-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["decision"] == "denied"
    assert dumped["process"]["records"]["user_decision"] == "denied"
    assert dumped["output"]["records"]["decision"] == "denied"
    assert dumped["output"]["records"]["user_decision"] == "denied"


def test_tool_confirmation_detail_projection_matches_plan_or_linkage_without_broad_refs(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_primary_tool_confirmation_detail(manager, include_or_linkage_artifacts=True)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_tool_confirmation_detail("tool-confirmation-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["artifacts"]["records"]["artifact_refs"] == [
        "artifact-tool-confirmation-1",
        "artifact-tool-confirmation-confirmed-action-extra",
        "artifact-match-trace-ref",
        "artifact-match-trace-refs",
        "artifact-match-audit-ref",
        "artifact-match-audit-refs",
    ]
    assert dumped["output"]["records"]["result_status"] == "waiting_tool_confirmation"
    assert "artifact-tool-confirmation-shared-wrong-id" not in str(dumped)
    assert "tool-result-shared-wrong-id" not in str(dumped)


def test_tool_confirmation_detail_projection_uses_persisted_follow_up_result_and_event_disabled_reason(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_primary_tool_confirmation_detail(
        manager,
        confirmation_alternative_path_summary=None,
        artifact_alternative_path_summary=None,
        feed_disabled_reason="Use cached dependency state.",
        follow_up_result="persisted-follow-up-result",
    )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_tool_confirmation_detail("tool-confirmation-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["input"]["records"]["alternative_path_summary"] == (
        "Use cached dependency state."
    )
    assert dumped["process"]["records"]["alternative_path_summary"] == (
        "Use cached dependency state."
    )
    assert dumped["process"]["records"]["alternative_path_judgment"] == {
        "alternative_path_summary": "Use cached dependency state.",
        "result_status": "waiting_tool_confirmation",
    }
    assert dumped["output"]["records"]["alternative_path_summary"] == (
        "Use cached dependency state."
    )
    assert dumped["output"]["records"]["result_snapshot"]["follow_up_result"] == (
        "persisted-follow-up-result"
    )
    assert dumped["output"]["records"]["follow_up_refs"] == [
        "follow-up-tool-confirmation-1"
    ]
    assert dumped["output"]["records"]["follow_up_result"] == (
        "persisted-follow-up-result"
    )


def test_tool_confirmation_detail_projection_ignores_unsupported_decision_values(
    tmp_path,
) -> None:
    cancelled_manager = _manager(tmp_path / "cancelled-decision")
    _seed_workspace(cancelled_manager)
    _seed_primary_tool_confirmation_detail(
        cancelled_manager,
        user_decision=ToolConfirmationStatus.CANCELLED,
    )

    with (
        cancelled_manager.session(DatabaseRole.CONTROL) as control_session,
        cancelled_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        cancelled_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_tool_confirmation_detail("tool-confirmation-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["decision"] is None
    assert dumped["process"]["records"]["user_decision"] is None
    assert dumped["output"]["records"]["decision"] is None
    assert dumped["output"]["records"]["user_decision"] is None

    malformed_artifact_manager = _manager(tmp_path / "malformed-artifact-decision")
    _seed_workspace(malformed_artifact_manager)
    _seed_primary_tool_confirmation_detail(
        malformed_artifact_manager,
        artifact_decision="cancelled",
    )

    with (
        malformed_artifact_manager.session(DatabaseRole.CONTROL) as control_session,
        malformed_artifact_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        malformed_artifact_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_tool_confirmation_detail("tool-confirmation-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["decision"] is None
    assert dumped["process"]["records"]["user_decision"] is None
    assert dumped["output"]["records"]["decision"] is None
    assert dumped["output"]["records"]["user_decision"] is None


def test_tool_confirmation_detail_projection_rejects_missing_hidden_session_hidden_project_and_cross_run_linkage(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_tool_confirmation_detail("tool-confirmation-missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Tool confirmation inspector was not found."

    hidden_session_manager = _manager(tmp_path / "hidden-session")
    _seed_workspace(hidden_session_manager)
    with hidden_session_manager.session(DatabaseRole.CONTROL) as session:
        hidden_session = session.get(SessionModel, "session-1")
        assert hidden_session is not None
        hidden_session.is_visible = False
        hidden_session.visibility_removed_at = NOW + timedelta(minutes=9)
        session.add(hidden_session)
        session.commit()

    with (
        hidden_session_manager.session(DatabaseRole.CONTROL) as control_session,
        hidden_session_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        hidden_session_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_tool_confirmation_detail("tool-confirmation-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Tool confirmation inspector was not found."

    hidden_project_manager = _manager(tmp_path / "hidden-project")
    _seed_workspace(hidden_project_manager)
    with hidden_project_manager.session(DatabaseRole.CONTROL) as session:
        hidden_project = session.get(ProjectModel, "project-1")
        assert hidden_project is not None
        hidden_project.is_visible = False
        hidden_project.visibility_removed_at = NOW + timedelta(minutes=9)
        session.add(hidden_project)
        session.commit()

    with (
        hidden_project_manager.session(DatabaseRole.CONTROL) as control_session,
        hidden_project_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        hidden_project_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_tool_confirmation_detail("tool-confirmation-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Tool confirmation inspector was not found."

    cross_run_manager = _manager(tmp_path / "cross-run-linkage")
    _seed_workspace(cross_run_manager)
    _seed_primary_tool_confirmation_detail(cross_run_manager)
    with cross_run_manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RunControlRecordModel(
                control_record_id="control-tool-cross-run",
                run_id="run-old",
                stage_run_id="stage-old",
                control_type=RunControlRecordType.TOOL_CONFIRMATION,
                source_stage_type=StageType.CODE_GENERATION,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="tool-confirmation-1",
                graph_interrupt_ref="interrupt-tool-1",
                occurred_at=NOW + timedelta(minutes=8),
                created_at=NOW + timedelta(minutes=8),
            )
        )
        session.commit()

    with (
        cross_run_manager.session(DatabaseRole.CONTROL) as control_session,
        cross_run_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        cross_run_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_tool_confirmation_detail("tool-confirmation-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Tool confirmation inspector was not found."


def _seed_primary_tool_confirmation_detail(
    manager,
    *,
    feed_decision: common.ToolConfirmationStatus | None = None,
    artifact_decision: ToolConfirmationStatus | str | None = None,
    include_or_linkage_artifacts: bool = False,
    user_decision: ToolConfirmationStatus | None = None,
    confirmation_alternative_path_summary: str | None = (
        "Use already installed dependencies if available."
    ),
    artifact_alternative_path_summary: str | None = (
        "Use already installed dependencies if available."
    ),
    feed_disabled_reason: str | None = None,
    follow_up_result: str | None = None,
) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        confirmation = session.get(ToolConfirmationRequestModel, "tool-confirmation-1")
        assert confirmation is not None
        confirmation.audit_log_ref = "audit-tool-confirmation-1"
        confirmation.alternative_path_summary = confirmation_alternative_path_summary
        confirmation.user_decision = user_decision
        confirmation.responded_at = (
            NOW + timedelta(minutes=7) if user_decision is not None else None
        )
        confirmation.updated_at = NOW + timedelta(minutes=7)
        session.add(
            RunControlRecordModel(
                control_record_id="control-tool-1",
                run_id="run-active",
                stage_run_id="stage-active",
                control_type=RunControlRecordType.TOOL_CONFIRMATION,
                source_stage_type=StageType.CODE_GENERATION,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="tool-confirmation-1",
                graph_interrupt_ref="interrupt-tool-1",
                occurred_at=NOW + timedelta(minutes=8),
                created_at=NOW + timedelta(minutes=8),
            )
        )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-tool-confirmation-1",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="tool_confirmation_trace",
                payload_ref="payload-tool-confirmation-1",
                process={
                    "tool_confirmation_id": "tool-confirmation-1",
                    "confirmation_object_ref": "tool-call-1",
                    "process_ref": "process-tool-confirmation-1",
                    "audit_log_ref": "audit-tool-confirmation-1",
                    "tool_confirmation_trace_ref": (
                        "trace-tool-confirmation-primary"
                    ),
                    "tool_confirmation_trace_refs": [
                        "trace-tool-confirmation-primary",
                        "trace-tool-confirmation-extra",
                    ],
                    "tool_result_ref": "tool-result-1",
                    "tool_result_refs": ["tool-result-1"],
                    "tool_call_ref": "tool-call-1",
                    "audit_ref": "audit-tool-confirmation-1",
                    "audit_refs": ["audit-extra-1"],
                    "side_effect_refs": ["side-effect-lockfile-update"],
                    "alternative_path_summary": (
                        "Use already installed dependencies if available."
                    ),
                    "result_snapshot": {
                        "result_status": "waiting_tool_confirmation",
                        "follow_up_refs": ["follow-up-tool-confirmation-1"],
                        "graph_thread_ref": "graph-thread-hidden",
                    },
                    "log_refs": ["log-tool-confirmation-1"],
                    "context_refs": ["context-package-json", "context-lockfile"],
                    "metrics": {"duration_ms": 750, "tool_call_count": 1},
                },
                metrics={"duration_ms": 750, "tool_call_count": 1},
                created_at=NOW + timedelta(minutes=7, seconds=30),
            )
        )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-tool-confirmation-other",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="tool_confirmation_trace",
                payload_ref="payload-tool-confirmation-other",
                process={
                    "tool_confirmation_id": "tool-confirmation-other",
                    "confirmation_object_ref": "tool-call-other",
                    "process_ref": "process-tool-confirmation-other",
                    "audit_log_ref": "audit-tool-confirmation-other",
                    "result_snapshot": {"result_status": "unrelated"},
                    "log_refs": ["log-tool-confirmation-other"],
                },
                metrics={"duration_ms": 999, "tool_call_count": 99},
                created_at=NOW + timedelta(minutes=7, seconds=45),
            )
        )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-tool-confirmation-confirmed-action-extra",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="tool_confirmation_trace",
                payload_ref="payload-tool-confirmation-confirmed-action-extra",
                process={
                    "confirmation_object_ref": "tool-call-1",
                    "log_refs": ["log-confirmed-action-extra"],
                },
                metrics={},
                created_at=NOW + timedelta(minutes=7, seconds=35),
            )
        )
        if artifact_decision is not None:
            session.flush()
            primary_artifact = session.get(
                StageArtifactModel,
                "artifact-tool-confirmation-1",
            )
            assert primary_artifact is not None
            primary_process = dict(primary_artifact.process)
            result_snapshot = dict(primary_process["result_snapshot"])
            result_snapshot["decision"] = (
                artifact_decision.value
                if isinstance(artifact_decision, ToolConfirmationStatus)
                else artifact_decision
            )
            primary_process["result_snapshot"] = result_snapshot
            primary_artifact.process = primary_process
            session.add(primary_artifact)
        if artifact_alternative_path_summary is None or follow_up_result is not None:
            session.flush()
            primary_artifact = session.get(
                StageArtifactModel,
                "artifact-tool-confirmation-1",
            )
            assert primary_artifact is not None
            primary_process = dict(primary_artifact.process)
            if artifact_alternative_path_summary is None:
                primary_process.pop("alternative_path_summary", None)
            else:
                primary_process["alternative_path_summary"] = (
                    artifact_alternative_path_summary
                )
            if follow_up_result is not None:
                result_snapshot = dict(primary_process["result_snapshot"])
                result_snapshot["follow_up_result"] = follow_up_result
                primary_process["result_snapshot"] = result_snapshot
            primary_artifact.process = primary_process
            session.add(primary_artifact)
        if include_or_linkage_artifacts:
            session.add_all(
                [
                    StageArtifactModel(
                        artifact_id="artifact-match-trace-ref",
                        run_id="run-active",
                        stage_run_id="stage-active",
                        artifact_type="tool_confirmation_trace",
                        payload_ref="payload-match-trace-ref",
                        process={
                            "tool_confirmation_trace_ref": (
                                "process-tool-confirmation-1"
                            )
                        },
                        metrics={},
                        created_at=NOW + timedelta(minutes=7, seconds=36),
                    ),
                    StageArtifactModel(
                        artifact_id="artifact-match-trace-refs",
                        run_id="run-active",
                        stage_run_id="stage-active",
                        artifact_type="tool_confirmation_trace",
                        payload_ref="payload-match-trace-refs",
                        process={
                            "tool_confirmation_trace_refs": [
                                "process-tool-confirmation-1"
                            ]
                        },
                        metrics={},
                        created_at=NOW + timedelta(minutes=7, seconds=37),
                    ),
                    StageArtifactModel(
                        artifact_id="artifact-match-audit-ref",
                        run_id="run-active",
                        stage_run_id="stage-active",
                        artifact_type="tool_confirmation_trace",
                        payload_ref="payload-match-audit-ref",
                        process={"audit_ref": "audit-tool-confirmation-1"},
                        metrics={},
                        created_at=NOW + timedelta(minutes=7, seconds=38),
                    ),
                    StageArtifactModel(
                        artifact_id="artifact-match-audit-refs",
                        run_id="run-active",
                        stage_run_id="stage-active",
                        artifact_type="tool_confirmation_trace",
                        payload_ref="payload-match-audit-refs",
                        process={"audit_refs": ["audit-tool-confirmation-1"]},
                        metrics={},
                        created_at=NOW + timedelta(minutes=7, seconds=39),
                    ),
                ]
            )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-tool-confirmation-shared-wrong-id",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="tool_confirmation_trace",
                payload_ref="payload-tool-confirmation-shared-wrong-id",
                process={
                    "tool_confirmation_id": "tool-confirmation-shared-wrong-id",
                    "process_ref": "process-tool-confirmation-1",
                    "audit_log_ref": "audit-tool-confirmation-1",
                    "tool_result_ref": "tool-result-shared-wrong-id",
                    "tool_result_refs": ["tool-result-shared-wrong-id"],
                    "result_snapshot": {"result_status": "wrongly-associated"},
                    "log_refs": ["log-shared-wrong-id"],
                },
                metrics={"duration_ms": 999, "tool_call_count": 99},
                created_at=NOW + timedelta(minutes=7, seconds=50),
            )
        )
        session.commit()

    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(
                [
                    "event-tool-confirmation-primary-detail",
                    "event-stage-tool-confirmation-context",
                    "event-tool-confirmation-other-detail",
                ]
            ).__next__,
        )
        store.append(
            DomainEventType.TOOL_CONFIRMATION_REQUESTED,
            payload={
                "tool_confirmation": ToolConfirmationFeedEntry(
                    entry_id="entry-tool-confirmation-primary-detail",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7, seconds=10),
                    stage_run_id="stage-active",
                    tool_confirmation_id="tool-confirmation-1",
                    status=common.ToolConfirmationStatus.PENDING,
                    title="Allow dependency install for active confirmation",
                    tool_name="bash",
                    command_preview="npm install",
                    target_summary="frontend/package-lock.json",
                    risk_level=common.ToolRiskLevel.HIGH_RISK,
                    risk_categories=[
                        common.ToolRiskCategory.DEPENDENCY_CHANGE,
                        common.ToolRiskCategory.NETWORK_DOWNLOAD,
                    ],
                    reason="Installing dependencies changes lock files.",
                    expected_side_effects=["package-lock update"],
                    allow_action="allow_once",
                    deny_action="deny_once",
                    is_actionable=True,
                    requested_at=NOW + timedelta(minutes=7),
                    responded_at=None,
                    decision=feed_decision,
                    disabled_reason=feed_disabled_reason,
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        store.append(
            DomainEventType.STAGE_UPDATED,
            payload={
                "stage_node": ExecutionNodeProjection(
                    entry_id="entry-stage-tool-confirmation-context",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7, seconds=20),
                    stage_run_id="stage-active",
                    stage_type=common.StageType.CODE_GENERATION,
                    status=common.StageStatus.WAITING_TOOL_CONFIRMATION,
                    attempt_index=1,
                    started_at=NOW + timedelta(minutes=2),
                    ended_at=None,
                    summary="Tool confirmation context for dependency install.",
                    items=[
                        StageItemProjection(
                            item_id="item-tool-confirmation-context",
                            type=common.StageItemType.TOOL_CONFIRMATION,
                            occurred_at=NOW + timedelta(minutes=7, seconds=20),
                            title="Tool confirmation requested",
                            summary="A high-risk dependency install requires approval.",
                            content=None,
                            artifact_refs=["tool-confirmation-1"],
                            metrics={},
                        )
                    ],
                    metrics={"tool_call_count": 1},
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        store.append(
            DomainEventType.TOOL_CONFIRMATION_REQUESTED,
            payload={
                "tool_confirmation": ToolConfirmationFeedEntry(
                    entry_id="entry-tool-confirmation-other-detail",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7, seconds=30),
                    stage_run_id="stage-active",
                    tool_confirmation_id="tool-confirmation-other",
                    status=common.ToolConfirmationStatus.PENDING,
                    title="Unrelated tool confirmation",
                    tool_name="bash",
                    command_preview="rm -rf build",
                    target_summary="build",
                    risk_level=common.ToolRiskLevel.HIGH_RISK,
                    risk_categories=[common.ToolRiskCategory.FILE_DELETE_OR_MOVE],
                    reason="Unrelated confirmation must not appear.",
                    expected_side_effects=["delete build"],
                    allow_action="allow_once",
                    deny_action="deny_once",
                    is_actionable=True,
                    requested_at=NOW + timedelta(minutes=7),
                    responded_at=None,
                    decision=None,
                    disabled_reason=None,
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.add(
            DomainEventModel(
                event_id="event-stage-tool-confirmation-malformed",
                session_id="session-1",
                run_id="run-active",
                stage_run_id="stage-active",
                event_type=SseEventType.STAGE_UPDATED,
                sequence_index=99,
                occurred_at=NOW + timedelta(minutes=7, seconds=25),
                payload={
                    "stage_node": {
                        "entry_id": "entry-stage-tool-confirmation-malformed",
                        "run_id": "run-active",
                        "stage_run_id": "stage-active",
                        "type": "stage_node",
                    }
                },
                correlation_id="correlation-1",
                causation_event_id=None,
                created_at=NOW,
            )
        )
        session.commit()


def _seed_outcome_tool_confirmation(
    manager,
    *,
    tool_confirmation_id: str,
    artifact_id: str,
    payload_ref: str,
    status: ToolConfirmationStatus,
    user_decision: ToolConfirmationStatus | None,
    result_status: str,
    result_ref: str | None,
    follow_up_ref: str,
    side_effect_refs: list[str],
    alternative_path_summary: str,
    denied_path_result: dict[str, object] | None,
    minutes: int,
) -> None:
    responded_at = NOW + timedelta(minutes=minutes) if user_decision else None
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            ToolConfirmationRequestModel(
                tool_confirmation_id=tool_confirmation_id,
                run_id="run-active",
                stage_run_id="stage-active",
                confirmation_object_ref=f"tool-call-{tool_confirmation_id}",
                tool_name="bash",
                command_preview="npm install",
                target_summary="frontend/package-lock.json",
                risk_level=ToolRiskLevel.HIGH_RISK,
                risk_categories=["dependency_change", "network_download"],
                reason="Installing dependencies changes lock files.",
                expected_side_effects=["package-lock update"],
                alternative_path_summary=alternative_path_summary,
                user_decision=user_decision,
                status=status,
                graph_interrupt_ref=f"interrupt-{tool_confirmation_id}",
                audit_log_ref=f"audit-{tool_confirmation_id}",
                process_ref=f"process-{tool_confirmation_id}",
                requested_at=NOW + timedelta(minutes=minutes - 1),
                responded_at=responded_at,
                created_at=NOW + timedelta(minutes=minutes - 1),
                updated_at=NOW + timedelta(minutes=minutes),
            )
        )
        session.add(
            RunControlRecordModel(
                control_record_id=f"control-{tool_confirmation_id}",
                run_id="run-active",
                stage_run_id="stage-active",
                control_type=RunControlRecordType.TOOL_CONFIRMATION,
                source_stage_type=StageType.CODE_GENERATION,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref=tool_confirmation_id,
                graph_interrupt_ref=f"interrupt-{tool_confirmation_id}",
                occurred_at=NOW + timedelta(minutes=minutes),
                created_at=NOW + timedelta(minutes=minutes),
            )
        )
        result_snapshot = {
            "result_status": result_status,
            "follow_up_refs": [follow_up_ref],
            "graph_thread_id": "hidden-thread-id",
        }
        if result_ref is not None:
            result_snapshot["result_ref"] = result_ref
        if side_effect_refs:
            result_snapshot["side_effect_refs"] = side_effect_refs
        if denied_path_result is not None:
            result_snapshot["denied_path_result"] = denied_path_result
        session.add(
            StageArtifactModel(
                artifact_id=artifact_id,
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="tool_confirmation_trace",
                payload_ref=payload_ref,
                process={
                    "tool_confirmation_id": tool_confirmation_id,
                    "confirmation_object_ref": f"tool-call-{tool_confirmation_id}",
                    "process_ref": f"process-{tool_confirmation_id}",
                    "audit_log_ref": f"audit-{tool_confirmation_id}",
                    "tool_result_ref": result_ref,
                    "tool_result_refs": [result_ref] if result_ref is not None else [],
                    "result_snapshot": result_snapshot,
                    "side_effect_refs": side_effect_refs,
                    "alternative_path_summary": alternative_path_summary,
                    "log_refs": [f"log-{tool_confirmation_id}"],
                },
                metrics={"duration_ms": 500, "tool_call_count": 1},
                created_at=NOW + timedelta(minutes=minutes),
            )
        )
        session.commit()


def _assert_forbidden_keys_absent(value: object) -> None:
    if isinstance(value, dict):
        forbidden_keys = FORBIDDEN_DETAIL_KEYS.intersection(value)
        assert forbidden_keys == set()
        for item in value.values():
            _assert_forbidden_keys_absent(item)
    elif isinstance(value, list):
        for item in value:
            _assert_forbidden_keys_absent(item)
