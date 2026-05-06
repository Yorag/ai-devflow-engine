from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    PipelineTemplateModel,
    ProjectModel,
    SessionModel,
)
from backend.app.db.models.event import EventBase
from backend.app.db.models.graph import (
    GraphBase,
    GraphCheckpointModel,
    GraphDefinitionModel,
    GraphThreadModel,
)
from backend.app.db.models.log import LogBase
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
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
from backend.app.schemas.feed import ApprovalRequestFeedEntry, ToolConfirmationFeedEntry
from backend.app.services.events import DomainEventType, EventStore
from backend.tests.services.test_pause_resume import (
    FakeCheckpointPort,
    FakeRuntimePort,
    NOW,
    RecordingAuditService,
    build_trace,
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
    EventBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.EVENT))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    app.state.h45_runtime_port = FakeRuntimePort()
    app.state.h41_runtime_port = app.state.h45_runtime_port
    app.state.h45_checkpoint_port = FakeCheckpointPort()
    app.state.h41_checkpoint_port = app.state.h45_checkpoint_port
    app.state.h45_audit_service = RecordingAuditService()
    return app


def build_app_without_injected_runtime_ports(tmp_path: Path):
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
    app.state.h45_audit_service = RecordingAuditService()
    return app


def seed_graph_thread_for_api(app) -> None:
    session = app.state.database_manager.session(DatabaseRole.GRAPH)
    try:
        session.add(
            GraphDefinitionModel(
                graph_definition_id="graph-definition-1",
                run_id="run-1",
                template_snapshot_ref="template-snapshot-1",
                graph_version="graph-v1",
                stage_nodes=[
                    {
                        "node_key": "code_generation.main",
                        "stage_type": StageType.CODE_GENERATION.value,
                    }
                ],
                stage_contracts={StageType.CODE_GENERATION.value: {"allowed_tools": []}},
                interrupt_policy={},
                retry_policy={},
                delivery_routing_policy={},
                schema_version="graph-definition-v1",
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            GraphThreadModel(
                graph_thread_id="thread-1",
                run_id="run-1",
                graph_definition_id="graph-definition-1",
                checkpoint_namespace="run-1-main",
                current_node_key="code_generation.main",
                current_interrupt_id=None,
                status="running",
                last_checkpoint_ref=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    finally:
        session.close()


def seed_active_run_for_api(
    app,
    *,
    run_status: RunStatus,
    session_status: SessionStatus,
    stage_status: StageStatus,
    with_pending_approval: bool = False,
    with_pending_tool_confirmation: bool = False,
) -> None:
    manager = app.state.database_manager
    session = manager.session(DatabaseRole.CONTROL)
    try:
        session.add_all(
            [
                ProjectModel(
                    project_id="project-1",
                    name="Pause Resume Project",
                    root_path="C:/repo/pause-resume-project",
                    default_delivery_channel_id=None,
                    is_default=True,
                    is_visible=True,
                    visibility_removed_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
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
                ),
                SessionModel(
                    session_id="session-1",
                    project_id="project-1",
                    display_name="Pause resume session",
                    status=session_status,
                    selected_template_id="template-1",
                    current_run_id="run-1",
                    latest_stage_type=StageType.CODE_GENERATION,
                    is_visible=True,
                    visibility_removed_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
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
                trace_id="trace-pause-resume",
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
                summary="Current stage.",
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
        if with_pending_approval:
            session.add(
                ApprovalRequestModel(
                    approval_id="approval-1",
                    run_id="run-1",
                    stage_run_id="stage-run-1",
                    approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
                    status=ApprovalStatus.PENDING,
                    payload_ref="approval-payload-1",
                    graph_interrupt_ref="interrupt-approval-1",
                    requested_at=NOW,
                    resolved_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        if with_pending_tool_confirmation:
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


def seed_tool_confirmation_event_for_api(app) -> None:
    session = app.state.database_manager.session(DatabaseRole.EVENT)
    try:
        projection = ToolConfirmationFeedEntry(
            entry_id="entry-tool-confirmation-1",
            run_id="run-1",
            occurred_at=NOW,
            stage_run_id="stage-run-1",
            tool_confirmation_id="tool-confirmation-1",
            status=ToolConfirmationStatus.PENDING,
            title="Confirm bash tool action",
            tool_name="bash",
            command_preview="Remove-Item -Recurse build",
            target_summary="Deletes generated build outputs.",
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE],
            reason="The command deletes files and requires explicit confirmation.",
            expected_side_effects=["Deletes build outputs."],
            allow_action="allow:tool-confirmation-1",
            deny_action="deny:tool-confirmation-1",
            is_actionable=True,
            requested_at=NOW,
            responded_at=None,
            decision=None,
            disabled_reason=None,
        )
        EventStore(
            session,
            now=lambda: NOW,
            id_factory=lambda: "event-tool-confirmation-request",
        ).append(
            DomainEventType.TOOL_CONFIRMATION_REQUESTED,
            payload={"tool_confirmation": projection.model_dump(mode="json")},
            trace_context=build_trace(),
        )
        session.commit()
    finally:
        session.close()


def seed_approval_event_for_api(app) -> None:
    session = app.state.database_manager.session(DatabaseRole.EVENT)
    try:
        projection = ApprovalRequestFeedEntry(
            entry_id="entry-approval-1",
            run_id="run-1",
            occurred_at=NOW,
            approval_id="approval-1",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            status=ApprovalStatus.PENDING,
            title="Review code review result",
            approval_object_excerpt="Review the approval object.",
            risk_excerpt="One risk remains.",
            approval_object_preview={"payload_ref": "approval-payload-1"},
            approve_action="approve",
            reject_action="reject",
            is_actionable=True,
            requested_at=NOW,
            delivery_readiness_status=None,
            delivery_readiness_message=None,
            open_settings_action=None,
            disabled_reason=None,
        )
        EventStore(
            session,
            now=lambda: NOW,
            id_factory=lambda: "event-approval-request",
        ).append(
            DomainEventType.APPROVAL_REQUESTED,
            payload={"approval_request": projection.model_dump(mode="json")},
            trace_context=build_trace(),
        )
        session.commit()
    finally:
        session.close()


def test_post_run_pause_returns_paused_session_and_run(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        response = client.post("/api/runs/run-1/pause", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "paused"
    assert body["run"]["status"] == "paused"
    assert body["run"]["run_id"] == "run-1"
    assert body["run"]["current_stage_type"] == "code_generation"


def test_post_run_pause_uses_persistent_graph_runtime_ports_by_default(
    tmp_path: Path,
) -> None:
    app = build_app_without_injected_runtime_ports(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )
    seed_graph_thread_for_api(app)

    with TestClient(app) as client:
        response = client.post("/api/runs/run-1/pause", json={})

    assert response.status_code == 200
    with app.state.database_manager.session(DatabaseRole.GRAPH) as session:
        thread = session.get(GraphThreadModel, "thread-1")
        assert thread is not None
        assert thread.status == "paused"
        assert thread.last_checkpoint_ref is not None
        checkpoints = session.query(GraphCheckpointModel).all()
        assert len(checkpoints) == 1
        assert checkpoints[0].graph_thread_id == "thread-1"
        assert checkpoints[0].checkpoint_ref == thread.last_checkpoint_ref


def test_post_run_pause_accepts_bodyless_request(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        response = client.post("/api/runs/run-1/pause")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "paused"
    assert body["run"]["status"] == "paused"


def test_post_run_resume_restores_waiting_approval(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.WAITING_APPROVAL,
        session_status=SessionStatus.WAITING_APPROVAL,
        stage_status=StageStatus.WAITING_APPROVAL,
        with_pending_approval=True,
    )
    seed_approval_event_for_api(app)

    with TestClient(app) as client:
        pause_response = client.post("/api/runs/run-1/pause", json={})
        response = client.post("/api/runs/run-1/resume", json={})

    assert pause_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "waiting_approval"
    assert body["run"]["status"] == "waiting_approval"


def test_post_run_resume_accepts_bodyless_request(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        pause_response = client.post("/api/runs/run-1/pause", json={})
        response = client.post("/api/runs/run-1/resume")

    assert pause_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "running"
    assert body["run"]["status"] == "running"


def test_post_run_pause_makes_workspace_tool_confirmation_non_actionable(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.WAITING_TOOL_CONFIRMATION,
        session_status=SessionStatus.WAITING_TOOL_CONFIRMATION,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
        with_pending_tool_confirmation=True,
    )
    seed_tool_confirmation_event_for_api(app)

    with TestClient(app) as client:
        pause_response = client.post("/api/runs/run-1/pause", json={})
        workspace = client.get("/api/sessions/session-1/workspace").json()

    assert pause_response.status_code == 200
    tool_confirmation = next(
        entry
        for entry in workspace["narrative_feed"]
        if entry["type"] == "tool_confirmation"
    )
    assert tool_confirmation["is_actionable"] is False
    assert "paused" in tool_confirmation["disabled_reason"]
    assert workspace["composer_state"]["mode"] == "paused"
    assert workspace["composer_state"]["primary_action"] == "resume"


def test_post_run_resume_restores_workspace_tool_confirmation_actionable(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.WAITING_TOOL_CONFIRMATION,
        session_status=SessionStatus.WAITING_TOOL_CONFIRMATION,
        stage_status=StageStatus.WAITING_TOOL_CONFIRMATION,
        with_pending_tool_confirmation=True,
    )
    seed_tool_confirmation_event_for_api(app)

    with TestClient(app) as client:
        pause_response = client.post("/api/runs/run-1/pause", json={})
        resume_response = client.post("/api/runs/run-1/resume", json={})
        workspace = client.get("/api/sessions/session-1/workspace").json()

    assert pause_response.status_code == 200
    assert resume_response.status_code == 200
    tool_confirmation = next(
        entry
        for entry in workspace["narrative_feed"]
        if entry["type"] == "tool_confirmation"
    )
    assert tool_confirmation["is_actionable"] is True
    assert tool_confirmation["disabled_reason"] is None
    assert workspace["composer_state"]["mode"] == "waiting_tool_confirmation"
    assert workspace["composer_state"]["primary_action"] == "pause"


def test_post_run_resume_rejects_non_paused_run(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        response = client.post("/api/runs/run-1/resume", json={})

    assert response.status_code == 409
    assert response.json()["error_code"] == "run_command_not_actionable"


def test_run_pause_resume_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    pause_route = document["paths"]["/api/runs/{runId}/pause"]["post"]
    resume_route = document["paths"]["/api/runs/{runId}/resume"]["post"]
    assert (
        pause_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/RunPauseRequest"
    )
    assert (
        resume_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/RunResumeRequest"
    )
    assert (
        pause_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RunCommandResponse"
    )
    assert (
        resume_route["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RunCommandResponse"
    )
    assert set(pause_route["responses"]) == {"200", "404", "409", "422", "500"}
    assert set(resume_route["responses"]) == {"200", "404", "409", "422", "500"}
