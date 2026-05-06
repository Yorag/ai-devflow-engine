from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    DeliveryChannelModel,
    PipelineTemplateModel,
    ProjectModel,
    SessionModel,
)
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
    DeliveryChannelSnapshotModel,
    ApprovalRequestModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    SessionStatus,
    StageStatus,
    StageType,
    TemplateSource,
)
from backend.app.main import create_app
from backend.app.services.delivery_snapshots import DeliverySnapshotServiceError
from backend.tests.services.test_approval_commands import (
    FakeCheckpointPort,
    FakeRuntimePort,
    NOW,
    RecordingAuditService,
    RecordingDeliverySnapshotService,
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
    app.state.h44_audit_service = RecordingAuditService()
    app.state.h44_delivery_snapshot_service = RecordingDeliverySnapshotService(
        app.state.database_manager.session(DatabaseRole.RUNTIME)
    )
    return app


def seed_approval(app, **kwargs):
    manager = app.state.database_manager
    approval_type = kwargs["approval_type"]
    stage_type = kwargs["stage_type"]
    run_status = kwargs.get("run_status", RunStatus.WAITING_APPROVAL)
    session_status = kwargs.get("session_status", SessionStatus.WAITING_APPROVAL)
    delivery_mode = kwargs.get("delivery_mode", DeliveryMode.DEMO_DELIVERY)
    readiness_status = kwargs.get(
        "readiness_status",
        DeliveryReadinessStatus.READY,
    )
    credential_status = kwargs.get(
        "credential_status",
        CredentialStatus.READY,
    )

    session = manager.session(DatabaseRole.CONTROL)
    try:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Approval Project",
                root_path="C:/repo/approval-project",
                default_delivery_channel_id="delivery-channel-1",
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
                fixed_stage_sequence=[stage_type.value],
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
        session.commit()
    finally:
        session.close()

    session = manager.session(DatabaseRole.CONTROL)
    try:
        session.add(
            DeliveryChannelModel(
                delivery_channel_id="delivery-channel-1",
                project_id="project-1",
                delivery_mode=delivery_mode,
                scm_provider_type=ScmProviderType.GITHUB,
                repository_identifier="acme/approval-project",
                default_branch="main",
                code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
                credential_ref="env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
                credential_status=credential_status,
                readiness_status=readiness_status,
                readiness_message=(
                    "Delivery channel requires configuration."
                    if readiness_status is not DeliveryReadinessStatus.READY
                    else "Delivery channel is ready."
                ),
                last_validated_at=(
                    NOW
                    if readiness_status is DeliveryReadinessStatus.READY
                    else None
                ),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    finally:
        session.close()

    session = manager.session(DatabaseRole.CONTROL)
    try:
        session.add(
            SessionModel(
                session_id="session-1",
                project_id="project-1",
                display_name="Approval session",
                status=session_status,
                selected_template_id="template-1",
                current_run_id="run-1",
                latest_stage_type=stage_type,
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
                trace_id="trace-approval-command",
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
                stage_type=stage_type,
                status=StageStatus.WAITING_APPROVAL,
                attempt_index=1,
                graph_node_key=f"{stage_type.value}.main",
                stage_contract_ref=f"stage-contract-{stage_type.value}",
                input_ref=None,
                output_ref=None,
                summary="Waiting for approval.",
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
            ApprovalRequestModel(
                approval_id="approval-1",
                run_id="run-1",
                stage_run_id="stage-run-1",
                approval_type=approval_type,
                status=ApprovalStatus.PENDING,
                payload_ref="approval-payload-1",
                graph_interrupt_ref="interrupt-approval-1",
                requested_at=NOW,
                resolved_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    finally:
        session.close()
    _seed_graph_interrupt_for_approval(app, stage_type=stage_type, approval_id="approval-1")
    return "approval-1"


def _seed_graph_interrupt_for_approval(
    app,
    *,
    stage_type: StageType,
    approval_id: str,
) -> None:
    manager = app.state.database_manager
    checkpoint_ref = "graph-checkpoint://thread-1/checkpoint-approval-1"
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
                current_node_key=f"{stage_type.value}.main",
                current_interrupt_id="interrupt-approval-1",
                status="interrupted",
                last_checkpoint_ref=checkpoint_ref,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            GraphCheckpointModel(
                checkpoint_id="checkpoint-approval-1",
                graph_thread_id="thread-1",
                checkpoint_ref=checkpoint_ref,
                node_key=f"{stage_type.value}.main",
                state_ref=checkpoint_ref,
                sequence_index=1,
                created_at=NOW,
            )
        )
        session.add(
            GraphInterruptModel(
                interrupt_id="interrupt-approval-1",
                graph_thread_id="thread-1",
                interrupt_type=(
                    "solution_design_approval"
                    if stage_type is StageType.SOLUTION_DESIGN
                    else "code_review_approval"
                ),
                source_stage_type=stage_type,
                source_node_key=f"{stage_type.value}.main",
                payload_ref="approval-payload-1",
                runtime_object_ref=approval_id,
                runtime_object_type="approval_request",
                status="pending",
                requested_at=NOW,
                responded_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


class RejectingSnapshotService:
    def prepare_delivery_snapshot(self, **kwargs):
        raise DeliverySnapshotServiceError(
            error_code=backend_error_code(),
            message="DeliveryChannel is not ready for delivery snapshot.",
            status_code=409,
        )


def backend_error_code():
    from backend.app.api.error_codes import ErrorCode

    return ErrorCode.DELIVERY_SNAPSHOT_NOT_READY


def test_post_approval_approve_accepts_solution_design_and_returns_approval_result(
    tmp_path: Path,
) -> None:
    from backend.app.domain.enums import ApprovalType, StageType

    app = build_app(tmp_path)
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
        stage_type=StageType.SOLUTION_DESIGN,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/approvals/{approval_id}/approve",
            json={},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_result"]["approval_id"] == approval_id
    assert body["approval_result"]["decision"] == "approved"
    assert body["approval_result"]["next_stage_type"] == "code_generation"
    assert body["control_item"] is None


def test_post_approval_reject_requires_reason_and_returns_control_item(
    tmp_path: Path,
) -> None:
    from backend.app.domain.enums import ApprovalType, StageType

    app = build_app(tmp_path)
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/approvals/{approval_id}/reject",
            json={"reason": "Missing regression evidence."},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_result"]["decision"] == "rejected"
    assert body["approval_result"]["reason"] == "Missing regression evidence."
    assert body["control_item"]["control_type"] == "rollback"
    assert body["control_item"]["target_stage_type"] == "code_generation"


def test_post_approval_approve_returns_paused_conflict_without_mutation(
    tmp_path: Path,
) -> None:
    from backend.app.domain.enums import (
        ApprovalType,
        RunStatus,
        SessionStatus,
        StageType,
    )

    app = build_app(tmp_path)
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
        stage_type=StageType.SOLUTION_DESIGN,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/approvals/{approval_id}/approve",
            json={},
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "approval_not_actionable"
    assert "paused" in response.json()["message"]


def test_post_approval_approve_returns_delivery_readiness_conflict_for_code_review(
    tmp_path: Path,
) -> None:
    from backend.app.domain.enums import (
        ApprovalType,
        CredentialStatus,
        DeliveryMode,
        DeliveryReadinessStatus,
        StageType,
    )

    app = build_app(tmp_path)
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        credential_status=CredentialStatus.UNBOUND,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/approvals/{approval_id}/approve",
            json={},
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "delivery_snapshot_not_ready"
    assert response.json()["detail_ref"] == approval_id


def test_post_approval_approve_rolls_back_real_snapshot_when_later_command_step_fails(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    manager = app.state.database_manager
    app.state.h41_runtime_port = FakeRuntimePort(fail_on_resume=True)
    app.state.h44_runtime_port = app.state.h41_runtime_port
    del app.state.h44_delivery_snapshot_service
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        readiness_status=DeliveryReadinessStatus.READY,
        credential_status=CredentialStatus.READY,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/api/approvals/{approval_id}/approve", json={})

    assert response.status_code == 500
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, approval_id)
        run = session.get(PipelineRunModel, "run-1")
        assert approval is not None and approval.status is ApprovalStatus.PENDING
        assert run is not None and run.delivery_channel_snapshot_ref is None
        assert session.query(DeliveryChannelSnapshotModel).count() == 0


def test_post_approval_approve_maps_delivery_snapshot_domain_error_to_conflict(
    tmp_path: Path,
) -> None:
    from backend.app.domain.enums import ApprovalType, StageType

    app = build_app(tmp_path)
    app.state.h44_delivery_snapshot_service = RejectingSnapshotService()
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/api/approvals/{approval_id}/approve", json={})

    assert response.status_code == 409
    assert response.json()["error_code"] == "delivery_snapshot_not_ready"
    assert response.json()["message"] == "DeliveryChannel is not ready for delivery snapshot."


def test_post_approval_reject_missing_approval_returns_not_found(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/approvals/approval-missing/reject",
            json={"reason": "Missing approval."},
        )

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_post_approval_reject_blank_reason_returns_validation_error(tmp_path: Path) -> None:
    from backend.app.domain.enums import ApprovalType, StageType

    app = build_app(tmp_path)
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/approvals/{approval_id}/reject",
            json={"reason": "   "},
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"
    assert response.json()["message"] == "Request validation failed."


def test_approval_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    approve_route = document["paths"]["/api/approvals/{approvalId}/approve"]["post"]
    reject_route = document["paths"]["/api/approvals/{approvalId}/reject"]["post"]
    assert (
        approve_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ApprovalApproveRequest"
    )
    assert (
        reject_route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ApprovalRejectRequest"
    )
    assert (
        approve_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ApprovalCommandResponse"
    )
    assert (
        reject_route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ApprovalCommandResponse"
    )
    assert set(approve_route["responses"]) == {"200", "404", "409", "422", "500"}
    assert set(reject_route["responses"]) == {"200", "404", "409", "422", "500"}
