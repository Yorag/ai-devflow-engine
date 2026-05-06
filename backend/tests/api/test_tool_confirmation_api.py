from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, PipelineTemplateModel, ProjectModel, SessionModel
from backend.app.db.models.event import EventBase
from backend.app.db.models.graph import (
    GraphBase,
    GraphCheckpointModel,
    GraphDefinitionModel,
    GraphInterruptModel,
    GraphThreadModel,
)
from backend.app.db.models.log import LogBase
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    StageStatus,
    StageType,
    TemplateSource,
    ToolConfirmationStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.main import create_app
from backend.tests.services.test_tool_confirmation_commands import (
    FakeCheckpointPort,
    FakeRuntimePort,
    NOW,
    RecordingAuditService,
)


def build_app(tmp_path: Path):
    app = create_app(
        EnvironmentSettings(
            platform_runtime_root=tmp_path / "runtime",
            default_project_root=tmp_path / "project-root",
        )
    )
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.RUNTIME))
    GraphBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.GRAPH))
    EventBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.EVENT))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    app.state.h41_runtime_port = FakeRuntimePort()
    app.state.h44_runtime_port = app.state.h41_runtime_port
    app.state.h41_checkpoint_port = FakeCheckpointPort()
    app.state.h44_tool_confirmation_audit_service = RecordingAuditService()
    return app


def build_app_with_h44a_injection(tmp_path: Path):
    app = build_app(tmp_path)
    app.state.h44a_runtime_port = FakeRuntimePort()
    app.state.h44a_audit_service = RecordingAuditService()
    return app


def seed_tool_confirmation(app, **kwargs) -> str:
    manager = app.state.database_manager
    run_status = kwargs.get("run_status", RunStatus.WAITING_TOOL_CONFIRMATION)
    session_status = kwargs.get(
        "session_status",
        SessionStatus.WAITING_TOOL_CONFIRMATION,
    )
    stage_status = kwargs.get(
        "stage_status",
        StageStatus.WAITING_TOOL_CONFIRMATION,
    )
    planned_deny_followup_action = kwargs.get(
        "planned_deny_followup_action",
        "continue_current_stage",
    )
    planned_deny_followup_summary = kwargs.get(
        "planned_deny_followup_summary",
        "Code Generation will continue with a low-risk fallback.",
    )

    session = manager.session(DatabaseRole.CONTROL)
    try:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Tool Project",
                root_path="C:/repo/tool-project",
                default_delivery_channel_id=None,
                is_default=True,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            PipelineTemplateModel(
                template_id="template-1",
                name="Default",
                description=None,
                template_source=TemplateSource.SYSTEM_TEMPLATE,
                base_template_id=None,
                fixed_stage_sequence=[StageType.CODE_GENERATION.value],
                stage_role_bindings=[],
                approval_checkpoints=[],
                auto_regression_enabled=False,
                max_auto_regression_retries=0,
                max_react_iterations_per_stage=30,
                max_tool_calls_per_stage=80,
                skip_high_risk_tool_confirmations=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            SessionModel(
                session_id="session-1",
                project_id="project-1",
                display_name="Tool session",
                status=session_status,
                selected_template_id="template-1",
                current_run_id="run-1",
                latest_stage_type=StageType.CODE_GENERATION,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    finally:
        session.close()

    session = manager.session(DatabaseRole.RUNTIME)
    try:
        session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limits-1",
                    run_id="run-1",
                    agent_limits={},
                    context_limits={},
                    source_config_version="test",
                    hard_limits_version="test",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-policy-1",
                    run_id="run-1",
                    provider_call_policy={},
                    source_config_version="test",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
    finally:
        session.close()

    session = manager.session(DatabaseRole.RUNTIME)
    try:
        session.add(
            PipelineRunModel(
                run_id="run-1",
                session_id="session-1",
                project_id="project-1",
                attempt_index=1,
                status=run_status,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-1",
                graph_definition_ref="graph-definition-1",
                graph_thread_ref="thread-1",
                workspace_ref="workspace-1",
                runtime_limit_snapshot_ref="runtime-limits-1",
                provider_call_policy_snapshot_ref="provider-policy-1",
                delivery_channel_snapshot_ref=None,
                current_stage_run_id="stage-run-1",
                trace_id="trace-tool-confirmation",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    finally:
        session.close()

    session = manager.session(DatabaseRole.RUNTIME)
    try:
        session.add(
            StageRunModel(
                stage_run_id="stage-run-1",
                run_id="run-1",
                stage_type=StageType.CODE_GENERATION,
                status=stage_status,
                attempt_index=1,
                graph_node_key="code_generation.main",
                stage_contract_ref="stage-contract-code-generation",
                input_ref=None,
                output_ref=None,
                summary="Waiting for tool confirmation.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    finally:
        session.close()

    session = manager.session(DatabaseRole.RUNTIME)
    try:
        session.add(
            ToolConfirmationRequestModel(
                tool_confirmation_id="tool-confirmation-1",
                run_id="run-1",
                stage_run_id="stage-run-1",
                confirmation_object_ref="tool-action-1",
                tool_name="bash",
                command_preview="Remove-Item -Recurse build",
                target_summary="Deletes generated build outputs.",
                risk_level=ToolRiskLevel.HIGH_RISK,
                risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE.value],
                reason="The command deletes files and requires explicit confirmation.",
                expected_side_effects=["Deletes build outputs."],
                alternative_path_summary="Keep generated files and stop the run.",
                planned_deny_followup_action=planned_deny_followup_action,
                planned_deny_followup_summary=planned_deny_followup_summary,
                deny_followup_action=None,
                deny_followup_summary=None,
                user_decision=None,
                status=ToolConfirmationStatus.PENDING,
                graph_interrupt_ref="interrupt-tool-confirmation-1",
                audit_log_ref=None,
                process_ref=None,
                requested_at=NOW,
                responded_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    finally:
        session.close()
    _seed_graph_interrupt_for_tool_confirmation(app)
    return "tool-confirmation-1"


def _seed_graph_interrupt_for_tool_confirmation(app) -> None:
    manager = app.state.database_manager
    checkpoint_ref = "graph-checkpoint://thread-1/checkpoint-tool-1"
    with manager.session(DatabaseRole.GRAPH) as session:
        session.add(
            GraphDefinitionModel(
                graph_definition_id="graph-definition-1",
                run_id="run-1",
                template_snapshot_ref="template-snapshot-1",
                graph_version="test-graph-v1",
                stage_nodes=[],
                stage_contracts={},
                interrupt_policy={},
                retry_policy={},
                delivery_routing_policy={},
                schema_version="graph-definition-v1",
                created_at=NOW,
            )
        )
        session.add(
            GraphThreadModel(
                graph_thread_id="thread-1",
                run_id="run-1",
                graph_definition_id="graph-definition-1",
                checkpoint_namespace="thread-1",
                current_node_key="code_generation.main",
                current_interrupt_id="interrupt-tool-confirmation-1",
                status="interrupted",
                last_checkpoint_ref=checkpoint_ref,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            GraphCheckpointModel(
                checkpoint_id="checkpoint-tool-1",
                graph_thread_id="thread-1",
                checkpoint_ref=checkpoint_ref,
                node_key="code_generation.main",
                state_ref=checkpoint_ref,
                sequence_index=1,
                created_at=NOW,
            )
        )
        session.add(
            GraphInterruptModel(
                interrupt_id="interrupt-tool-confirmation-1",
                graph_thread_id="thread-1",
                interrupt_type="tool_confirmation",
                source_stage_type=StageType.CODE_GENERATION,
                source_node_key="code_generation.main",
                payload_ref="tool-confirmation-1",
                runtime_object_ref="tool-confirmation-1",
                runtime_object_type="tool_confirmation_request",
                status="pending",
                requested_at=NOW,
                responded_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def test_post_tool_confirmation_allow_returns_tool_confirmation_projection(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(app)

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/allow",
            json={},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_confirmation"]["type"] == "tool_confirmation"
    assert body["tool_confirmation"]["tool_confirmation_id"] == confirmation_id
    assert body["tool_confirmation"]["status"] == "allowed"
    assert body["tool_confirmation"]["decision"] == "allowed"
    assert body["tool_confirmation"]["allow_action"] == f"allow:{confirmation_id}"
    assert body["tool_confirmation"]["deny_action"] == f"deny:{confirmation_id}"


def test_post_tool_confirmation_deny_returns_tool_confirmation_projection(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(app)

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/deny",
            json={"reason": "Risk is not acceptable."},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_confirmation"]["tool_confirmation_id"] == confirmation_id
    assert body["tool_confirmation"]["status"] == "denied"
    assert body["tool_confirmation"]["decision"] == "denied"
    assert body["tool_confirmation"]["deny_followup_action"] == "continue_current_stage"
    assert body["tool_confirmation"]["deny_followup_summary"] == (
        "Code Generation will continue with a low-risk fallback."
    )
    assert app.state.h41_runtime_port.calls[-1][1]["resume_payload"].values == {
        "decision": "denied",
        "tool_confirmation_id": confirmation_id,
        "confirmation_object_ref": "tool-action-1",
        "deny_followup_action": "continue_current_stage",
        "deny_followup_summary": "Code Generation will continue with a low-risk fallback.",
        "reason": "Risk is not acceptable.",
    }
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.deny_followup_action == "continue_current_stage"
        assert request.deny_followup_summary == (
            "Code Generation will continue with a low-risk fallback."
        )


def test_post_tool_confirmation_deny_persists_run_failed_followup_fields(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(
        app,
        planned_deny_followup_action="run_failed",
        planned_deny_followup_summary=(
            "The run will fail because no low-risk fallback is available."
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/deny",
            json={"reason": "Risk is not acceptable."},
        )

    assert response.status_code == 200
    assert app.state.h41_runtime_port.calls[-1][1]["resume_payload"].values[
        "deny_followup_action"
    ] == "run_failed"
    assert app.state.h41_runtime_port.calls[-1][1]["resume_payload"].values[
        "deny_followup_summary"
    ] == "The run will fail because no low-risk fallback is available."
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.deny_followup_action == "run_failed"
        assert request.deny_followup_summary == (
            "The run will fail because no low-risk fallback is available."
        )


def test_post_tool_confirmation_deny_persists_awaiting_run_control_followup_fields(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(
        app,
        planned_deny_followup_action="awaiting_run_control",
        planned_deny_followup_summary=(
            "The run is waiting for an explicit pause or terminate decision."
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/deny",
            json={"reason": "Need an explicit operator decision."},
        )

    assert response.status_code == 200
    assert app.state.h41_runtime_port.calls[-1][1]["resume_payload"].values[
        "deny_followup_action"
    ] == "awaiting_run_control"
    assert app.state.h41_runtime_port.calls[-1][1]["resume_payload"].values[
        "deny_followup_summary"
    ] == "The run is waiting for an explicit pause or terminate decision."
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.deny_followup_action == "awaiting_run_control"
        assert request.deny_followup_summary == (
            "The run is waiting for an explicit pause or terminate decision."
        )


def test_post_tool_confirmation_deny_returns_internal_error_when_followup_source_is_missing(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(
        app,
        planned_deny_followup_action=None,
        planned_deny_followup_summary=None,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/deny",
            json={"reason": "Do not run this tool action."},
        )

    assert response.status_code == 500
    assert response.json()["error_code"] == "internal_error"
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.deny_followup_action is None
        assert request.deny_followup_summary is None
        assert request.planned_deny_followup_action is None
        assert request.planned_deny_followup_summary is None
    assert app.state.h41_runtime_port.calls == []


def test_post_tool_confirmation_deny_rejects_blank_reason(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(app)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/deny",
            json={"reason": "   "},
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"


def test_post_tool_confirmation_allow_returns_paused_conflict_without_mutation(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(
        app,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/allow",
            json={},
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "tool_confirmation_not_actionable"
    assert "paused" in response.json()["message"]
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None


def test_post_tool_confirmation_allow_returns_terminal_conflict_without_mutation(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(
        app,
        run_status=RunStatus.COMPLETED,
        session_status=SessionStatus.COMPLETED,
        stage_status=StageStatus.COMPLETED,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/allow",
            json={},
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "tool_confirmation_not_actionable"
    assert "terminal" in response.json()["message"]
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None


def test_post_tool_confirmation_deny_returns_paused_conflict_without_mutation(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(
        app,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/deny",
            json={"reason": "Need a later operator decision."},
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "tool_confirmation_not_actionable"
    assert "paused" in response.json()["message"]
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.deny_followup_action is None
        assert request.deny_followup_summary is None


def test_post_tool_confirmation_deny_returns_terminal_conflict_without_mutation(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    confirmation_id = seed_tool_confirmation(
        app,
        run_status=RunStatus.COMPLETED,
        session_status=SessionStatus.COMPLETED,
        stage_status=StageStatus.COMPLETED,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/deny",
            json={"reason": "The run is already terminal."},
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "tool_confirmation_not_actionable"
    assert "terminal" in response.json()["message"]
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        request = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert request is not None
        assert request.status is ToolConfirmationStatus.PENDING
        assert request.user_decision is None
        assert request.deny_followup_action is None
        assert request.deny_followup_summary is None


def test_post_tool_confirmation_deny_missing_request_returns_not_found(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/tool-confirmations/tool-confirmation-missing/deny",
            json={},
        )

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_tool_confirmation_route_prefers_h44a_app_state_injection(
    tmp_path: Path,
) -> None:
    app = build_app_with_h44a_injection(tmp_path)
    confirmation_id = seed_tool_confirmation(app)

    with TestClient(app) as client:
        response = client.post(
            f"/api/tool-confirmations/{confirmation_id}/allow",
            json={},
        )

    assert response.status_code == 200
    assert app.state.h44a_runtime_port.calls[-1][0] == "resume_tool_confirmation"
    assert app.state.h44a_audit_service.records[0]["action"] == (
        "tool_confirmation.allow"
    )


def test_tool_confirmation_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    allow_route = document["paths"]["/api/tool-confirmations/{toolConfirmationId}/allow"][
        "post"
    ]
    deny_route = document["paths"]["/api/tool-confirmations/{toolConfirmationId}/deny"][
        "post"
    ]
    assert (
        allow_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ToolConfirmationAllowRequest"
    )
    assert (
        deny_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ToolConfirmationDenyRequest"
    )
    assert (
        allow_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ToolConfirmationCommandResponse"
    )
    assert (
        deny_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ToolConfirmationCommandResponse"
    )
    assert set(allow_route["responses"]) == {"200", "404", "409", "422", "500"}
    assert set(deny_route["responses"]) == {"200", "404", "409", "422", "500"}
