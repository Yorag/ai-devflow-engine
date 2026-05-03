from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    DeliveryChannelModel,
    PipelineTemplateModel,
    PlatformRuntimeSettingsModel,
    ProjectModel,
    SessionModel,
)
from backend.app.db.models.event import EventBase
from backend.app.db.models.runtime import (
    ModelBindingSnapshotModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    ProviderSnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    SessionStatus,
    StageItemType,
    StageStatus,
    StageType,
    TemplateSource,
    ToolConfirmationStatus,
    ToolRiskLevel,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas import common
from backend.app.schemas.feed import (
    ApprovalRequestFeedEntry,
    ApprovalResultFeedEntry,
    ExecutionNodeProjection,
    MessageFeedEntry,
    StageItemProjection,
    ToolConfirmationFeedEntry,
)
from backend.app.services.events import DomainEventType, EventStore


NOW = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
SAFE_DELIVERY_CREDENTIAL_REF = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"


def _manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    return manager


def _trace(
    *,
    session_id: str = "session-1",
    run_id: str | None = "run-active",
    stage_run_id: str | None = None,
) -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-run-active",
        correlation_id="correlation-1",
        span_id="span-1",
        parent_span_id=None,
        session_id=session_id,
        run_id=run_id,
        stage_run_id=stage_run_id,
        created_at=NOW,
    )


def _seed_workspace(manager: DatabaseManager) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add_all(
            [
                ProjectModel(
                    project_id="project-1",
                    name="Workspace Project",
                    root_path="C:/work/workspace-project",
                    default_delivery_channel_id="delivery-1",
                    is_default=False,
                    is_visible=True,
                    visibility_removed_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                PipelineTemplateModel(
                    template_id="template-feature",
                    name="Feature pipeline",
                    description="Build a feature.",
                    template_source=TemplateSource.SYSTEM_TEMPLATE,
                    base_template_id=None,
                    fixed_stage_sequence=[StageType.REQUIREMENT_ANALYSIS.value],
                    stage_role_bindings=[],
                    approval_checkpoints=[],
                    auto_regression_enabled=True,
                    max_auto_regression_retries=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                DeliveryChannelModel(
                    delivery_channel_id="delivery-1",
                    project_id="project-1",
                    delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
                    scm_provider_type=ScmProviderType.GITHUB,
                    repository_identifier="example/workspace-project",
                    default_branch="main",
                    code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
                    credential_ref=SAFE_DELIVERY_CREDENTIAL_REF,
                    credential_status=CredentialStatus.READY,
                    readiness_status=DeliveryReadinessStatus.READY,
                    readiness_message="git_auto_delivery is ready.",
                    last_validated_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                SessionModel(
                    session_id="session-1",
                    project_id="project-1",
                    display_name="Add workspace projection",
                    status=SessionStatus.WAITING_TOOL_CONFIRMATION,
                    selected_template_id="template-feature",
                    current_run_id="run-active",
                    latest_stage_type=StageType.CODE_GENERATION,
                    is_visible=True,
                    visibility_removed_at=None,
                    created_at=NOW,
                    updated_at=NOW + timedelta(minutes=8),
                ),
                PlatformRuntimeSettingsModel(
                    settings_id="settings-latest",
                    config_version="latest-config-not-a-run-snapshot",
                    schema_version="runtime-settings-v1",
                    hard_limits_version="platform-hard-limits-v9",
                    agent_limits={"max_react_iterations_per_stage": 99},
                    provider_call_policy={"network_error_max_retries": 9},
                    context_limits={"grep_max_results": 999},
                    log_policy={"log_query_default_limit": 50},
                    created_by_actor_id=None,
                    updated_by_actor_id=None,
                    last_audit_log_id=None,
                    last_trace_id=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-old",
                    run_id="run-old",
                    agent_limits={"max_react_iterations_per_stage": 3},
                    context_limits={"grep_max_results": 10},
                    source_config_version="runtime-config-old",
                    hard_limits_version="platform-hard-limits-v1",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW - timedelta(minutes=10),
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="policy-old",
                    run_id="run-old",
                    provider_call_policy={"network_error_max_retries": 1},
                    source_config_version="runtime-config-old",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW - timedelta(minutes=10),
                ),
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-active",
                    run_id="run-active",
                    agent_limits={"max_react_iterations_per_stage": 5},
                    context_limits={"grep_max_results": 20},
                    source_config_version="runtime-config-active",
                    hard_limits_version="platform-hard-limits-v1",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="policy-active",
                    run_id="run-active",
                    provider_call_policy={"network_error_max_retries": 2},
                    source_config_version="runtime-config-active",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                PipelineRunModel(
                    run_id="run-old",
                    session_id="session-1",
                    project_id="project-1",
                    attempt_index=1,
                    status=RunStatus.FAILED,
                    trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                    template_snapshot_ref="template-snapshot-old",
                    graph_definition_ref="graph-definition-old",
                    graph_thread_ref="graph-thread-old",
                    workspace_ref="workspace-old",
                    runtime_limit_snapshot_ref="runtime-limit-old",
                    provider_call_policy_snapshot_ref="policy-old",
                    delivery_channel_snapshot_ref=None,
                    current_stage_run_id="stage-old",
                    trace_id="trace-run-old",
                    started_at=NOW - timedelta(minutes=9),
                    ended_at=NOW - timedelta(minutes=4),
                    created_at=NOW - timedelta(minutes=9),
                    updated_at=NOW - timedelta(minutes=4),
                ),
                PipelineRunModel(
                    run_id="run-active",
                    session_id="session-1",
                    project_id="project-1",
                    attempt_index=2,
                    status=RunStatus.WAITING_TOOL_CONFIRMATION,
                    trigger_source=RunTriggerSource.RETRY,
                    template_snapshot_ref="template-snapshot-active",
                    graph_definition_ref="graph-definition-active",
                    graph_thread_ref="graph-thread-active",
                    workspace_ref="workspace-active",
                    runtime_limit_snapshot_ref="runtime-limit-active",
                    provider_call_policy_snapshot_ref="policy-active",
                    delivery_channel_snapshot_ref=None,
                    current_stage_run_id="stage-active",
                    trace_id="trace-run-active",
                    started_at=NOW + timedelta(minutes=1),
                    ended_at=None,
                    created_at=NOW + timedelta(minutes=1),
                    updated_at=NOW + timedelta(minutes=7),
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                ProviderSnapshotModel(
                    snapshot_id="provider-snapshot-active",
                    run_id="run-active",
                    provider_id="provider-deepseek",
                    display_name="DeepSeek",
                    provider_source=ProviderSource.BUILTIN,
                    protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
                    base_url="https://api.deepseek.com",
                    api_key_ref="env:DEEPSEEK_API_KEY",
                    model_id="deepseek-chat",
                    capabilities={
                        "model_id": "deepseek-chat",
                        "max_output_tokens": 8192,
                    },
                    source_config_version="provider-config-active",
                    schema_version="provider-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                ModelBindingSnapshotModel(
                    snapshot_id="model-binding-active",
                    run_id="run-active",
                    binding_id="binding-code-generation",
                    binding_type="agent_role",
                    stage_type=StageType.CODE_GENERATION,
                    role_id="role-code-generator",
                    provider_snapshot_id="provider-snapshot-active",
                    provider_id="provider-deepseek",
                    model_id="deepseek-chat",
                    capabilities={
                        "model_id": "deepseek-chat",
                        "max_output_tokens": 8192,
                    },
                    model_parameters={},
                    source_config_version="template-binding-active",
                    schema_version="model-binding-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                StageRunModel(
                    stage_run_id="stage-old",
                    run_id="run-old",
                    stage_type=StageType.TEST_GENERATION_EXECUTION,
                    status=StageStatus.FAILED,
                    attempt_index=1,
                    graph_node_key="test_generation_execution.main",
                    stage_contract_ref="stage-contract-test-generation-execution",
                    input_ref=None,
                    output_ref=None,
                    summary="The old run failed.",
                    started_at=NOW - timedelta(minutes=8),
                    ended_at=NOW - timedelta(minutes=4),
                    created_at=NOW - timedelta(minutes=8),
                    updated_at=NOW - timedelta(minutes=4),
                ),
                StageRunModel(
                    stage_run_id="stage-active",
                    run_id="run-active",
                    stage_type=StageType.CODE_GENERATION,
                    status=StageStatus.WAITING_TOOL_CONFIRMATION,
                    attempt_index=1,
                    graph_node_key="code_generation.main",
                    stage_contract_ref="stage-contract-code-generation",
                    input_ref=None,
                    output_ref=None,
                    summary="Waiting for a high-risk tool decision.",
                    started_at=NOW + timedelta(minutes=2),
                    ended_at=None,
                    created_at=NOW + timedelta(minutes=2),
                    updated_at=NOW + timedelta(minutes=7),
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                ToolConfirmationRequestModel(
                    tool_confirmation_id="tool-confirmation-1",
                    run_id="run-active",
                    stage_run_id="stage-active",
                    confirmation_object_ref="tool-call-1",
                    tool_name="bash",
                    command_preview="npm install",
                    target_summary="frontend/package-lock.json",
                    risk_level=ToolRiskLevel.HIGH_RISK,
                    risk_categories=["dependency_change", "network_download"],
                    reason="Installing dependencies changes lock files.",
                    expected_side_effects=["package-lock update"],
                    alternative_path_summary=None,
                    user_decision=None,
                    status=ToolConfirmationStatus.PENDING,
                    graph_interrupt_ref="interrupt-tool-1",
                    audit_log_ref=None,
                    process_ref="process-tool-confirmation-1",
                    requested_at=NOW + timedelta(minutes=7),
                    responded_at=None,
                    created_at=NOW + timedelta(minutes=7),
                    updated_at=NOW + timedelta(minutes=7),
                ),
            ]
        )
        session.commit()

    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(session, now=lambda: NOW, id_factory=_event_id_factory())
        store.append(
            DomainEventType.SESSION_MESSAGE_APPENDED,
            payload={
                "message_item": MessageFeedEntry(
                    entry_id="entry-message",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=2),
                    message_id="message-1",
                    author="user",
                    content="Add workspace projection.",
                    stage_run_id=None,
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active"),
        )
        store.append(
            DomainEventType.STAGE_UPDATED,
            payload={
                "stage_node": ExecutionNodeProjection(
                    entry_id="entry-stage-active",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=6),
                    stage_run_id="stage-active",
                    stage_type=common.StageType.CODE_GENERATION,
                    status=common.StageStatus.WAITING_TOOL_CONFIRMATION,
                    attempt_index=1,
                    started_at=NOW + timedelta(minutes=2),
                    ended_at=None,
                    summary="Code Generation is waiting for tool confirmation.",
                    items=[
                        StageItemProjection(
                            item_id="item-tool-context",
                            type=StageItemType.TOOL_CONFIRMATION,
                            occurred_at=NOW + timedelta(minutes=7),
                            title="Tool confirmation requested",
                            summary="A high-risk command requires confirmation.",
                            content=None,
                            artifact_refs=["process-tool-confirmation-1"],
                            metrics={},
                        )
                    ],
                    metrics={},
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        store.append(
            DomainEventType.TOOL_CONFIRMATION_REQUESTED,
            payload={
                "tool_confirmation": ToolConfirmationFeedEntry(
                    entry_id="entry-tool-confirmation",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7),
                    stage_run_id="stage-active",
                    tool_confirmation_id="tool-confirmation-1",
                    status=common.ToolConfirmationStatus.PENDING,
                    title="Allow dependency install",
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
                    decision=None,
                    disabled_reason=None,
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()


def _event_id_factory():
    ids = iter(["event-message", "event-stage", "event-tool"])
    return lambda: next(ids)


def test_workspace_projection_aggregates_visible_session_runtime_runs_feed_and_composer(
    tmp_path,
) -> None:
    from backend.app.schemas.feed import ToolConfirmationFeedEntry
    from backend.app.services.projections.workspace import WorkspaceProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)

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
    assert dumped["session"]["session_id"] == "session-1"
    assert dumped["session"]["status"] == "waiting_tool_confirmation"
    assert dumped["project"]["project_id"] == "project-1"
    assert dumped["delivery_channel"]["delivery_channel_id"] == "delivery-1"
    assert dumped["delivery_channel"]["credential_ref"] == SAFE_DELIVERY_CREDENTIAL_REF
    assert [run["run_id"] for run in dumped["runs"]] == ["run-old", "run-active"]
    assert dumped["runs"][0] == {
        "run_id": "run-old",
        "attempt_index": 1,
        "status": "failed",
        "trigger_source": "initial_requirement",
        "started_at": (NOW - timedelta(minutes=9)).isoformat().replace("+00:00", "Z"),
        "ended_at": (NOW - timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
        "current_stage_type": "test_generation_execution",
        "is_active": False,
    }
    assert dumped["runs"][1]["run_id"] == "run-active"
    assert dumped["runs"][1]["current_stage_type"] == "code_generation"
    assert dumped["runs"][1]["is_active"] is True
    assert dumped["current_run_id"] == "run-active"
    assert dumped["current_stage_type"] == "code_generation"
    assert dumped["composer_state"] == {
        "mode": "waiting_tool_confirmation",
        "is_input_enabled": False,
        "primary_action": "pause",
        "secondary_actions": ["terminate"],
        "bound_run_id": "run-active",
    }
    assert [entry["type"] for entry in dumped["narrative_feed"]] == [
        "user_message",
        "stage_node",
        "tool_confirmation",
    ]
    tool_confirmation = next(
        entry
        for entry in workspace.narrative_feed
        if isinstance(entry, ToolConfirmationFeedEntry)
    )
    assert tool_confirmation.tool_confirmation_id == "tool-confirmation-1"
    assert tool_confirmation.is_actionable is True
    assert "graph_thread_ref" not in dumped
    assert "latest-config-not-a-run-snapshot" not in str(dumped)


def test_workspace_projection_replays_approval_result_into_matching_request(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(
                [
                    "event-approval-request",
                    "event-approval-result",
                    "event-approval-result-duplicate",
                ]
            ).__next__,
        )
        approval_request = ApprovalRequestFeedEntry(
            entry_id="entry-approval-request",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=8),
            approval_id="approval-1",
            approval_type=common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            status=common.ApprovalStatus.PENDING,
            title="Review solution design",
            approval_object_excerpt="Review the proposed design.",
            risk_excerpt=None,
            approval_object_preview={},
            approve_action="approve",
            reject_action="reject",
            is_actionable=True,
            requested_at=NOW + timedelta(minutes=8),
            delivery_readiness_status=None,
            delivery_readiness_message=None,
            open_settings_action=None,
            disabled_reason=None,
        )
        approval_result = ApprovalResultFeedEntry(
            entry_id="entry-approval-result",
            run_id="run-active",
            occurred_at=NOW + timedelta(minutes=9),
            approval_id="approval-1",
            approval_type=common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            decision=common.ApprovalStatus.APPROVED,
            reason=None,
            created_at=NOW + timedelta(minutes=9),
            next_stage_type=common.StageType.CODE_GENERATION,
        )
        store.append(
            DomainEventType.APPROVAL_REQUESTED,
            payload={"approval_request": approval_request.model_dump(mode="json")},
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        store.append(
            DomainEventType.APPROVAL_APPROVED,
            payload={"approval_result": approval_result.model_dump(mode="json")},
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        store.append(
            DomainEventType.APPROVAL_APPROVED,
            payload={"approval_result": approval_result.model_dump(mode="json")},
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        from backend.app.services.projections.workspace import WorkspaceProjectionService

        workspace = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_session_workspace("session-1")

    dumped = workspace.model_dump(mode="json")
    approval_request_entry = next(
        entry
        for entry in dumped["narrative_feed"]
        if entry["type"] == "approval_request"
    )
    assert approval_request_entry["status"] == "approved"
    assert approval_request_entry["is_actionable"] is False
    assert [
        entry["approval_id"]
        for entry in dumped["narrative_feed"]
        if entry["type"] == "approval_result"
    ] == ["approval-1"]


def test_workspace_projection_rejects_removed_session(tmp_path) -> None:
    from backend.app.services.projections.workspace import (
        WorkspaceProjectionService,
        WorkspaceProjectionServiceError,
    )

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.CONTROL) as session:
        removed = session.get(SessionModel, "session-1")
        assert removed is not None
        removed.is_visible = False
        removed.visibility_removed_at = NOW
        session.add(removed)
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(WorkspaceProjectionServiceError) as exc_info:
            service.get_session_workspace("session-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Session workspace was not found."


def test_workspace_projection_rejects_session_under_removed_project(tmp_path) -> None:
    from backend.app.services.projections.workspace import (
        WorkspaceProjectionService,
        WorkspaceProjectionServiceError,
    )

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.CONTROL) as session:
        removed = session.get(ProjectModel, "project-1")
        assert removed is not None
        removed.is_visible = False
        removed.visibility_removed_at = NOW
        session.add(removed)
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(WorkspaceProjectionServiceError) as exc_info:
            service.get_session_workspace("session-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Session workspace was not found."
