from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas import common
from backend.app.schemas.delivery_channel import ProjectDeliveryChannelDetailProjection
from backend.app.schemas.project import ProjectRead
from backend.app.schemas.session import SessionRead


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def build_project() -> ProjectRead:
    return ProjectRead(
        project_id="project-default",
        name="AI Devflow Engine",
        root_path="C:/repo/ai-devflow-engine",
        default_delivery_channel_id="delivery-default",
        is_default=True,
        created_at=NOW,
        updated_at=NOW,
    )


def build_session() -> SessionRead:
    return SessionRead(
        session_id="session-1",
        project_id="project-default",
        display_name="Add schema contracts",
        status=common.SessionStatus.WAITING_CLARIFICATION,
        selected_template_id="template-feature",
        current_run_id="run-1",
        latest_stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        created_at=NOW,
        updated_at=NOW,
    )


def build_delivery_channel() -> ProjectDeliveryChannelDetailProjection:
    return ProjectDeliveryChannelDetailProjection(
        project_id="project-default",
        delivery_channel_id="delivery-default",
        delivery_mode=common.DeliveryMode.DEMO_DELIVERY,
        scm_provider_type=None,
        repository_identifier=None,
        default_branch=None,
        code_review_request_type=None,
        credential_ref=None,
        credential_status=common.CredentialStatus.UNBOUND,
        readiness_status=common.DeliveryReadinessStatus.READY,
        readiness_message="Demo delivery is ready.",
        last_validated_at=NOW,
        updated_at=NOW,
    )


def test_session_workspace_projection_groups_runs_feed_and_composer() -> None:
    from backend.app.schemas.feed import (
        ExecutionNodeProjection,
        MessageFeedEntry,
        StageItemProjection,
    )
    from backend.app.schemas.run import ComposerStateProjection, RunSummaryProjection
    from backend.app.schemas.workspace import SessionWorkspaceProjection

    run = RunSummaryProjection(
        run_id="run-1",
        attempt_index=1,
        status=common.RunStatus.WAITING_CLARIFICATION,
        trigger_source=common.RunTriggerSource.INITIAL_REQUIREMENT,
        started_at=NOW,
        ended_at=None,
        current_stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        is_active=True,
    )
    message = MessageFeedEntry(
        entry_id="entry-user-1",
        run_id="run-1",
        occurred_at=NOW,
        message_id="message-1",
        author="user",
        content="Add stable schema contracts.",
    )
    stage_node = ExecutionNodeProjection(
        entry_id="entry-stage-1",
        run_id="run-1",
        occurred_at=NOW,
        stage_run_id="stage-1",
        stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        status=common.StageStatus.WAITING_CLARIFICATION,
        attempt_index=1,
        started_at=NOW,
        ended_at=None,
        summary="Requirement Analysis is waiting for a clarification answer.",
        items=[
            StageItemProjection(
                item_id="item-clarification-question",
                type=common.StageItemType.DIALOGUE,
                occurred_at=NOW,
                title="Clarification question",
                summary="The system needs the target contract surface confirmed.",
                content="Which schema group should be implemented first?",
                artifact_refs=[],
                metrics={},
            )
        ],
        metrics={"duration_ms": 1200},
    )
    workspace = SessionWorkspaceProjection(
        session=build_session(),
        project=build_project(),
        delivery_channel=build_delivery_channel(),
        runs=[run],
        narrative_feed=[message, stage_node],
        current_run_id="run-1",
        current_stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        composer_state=ComposerStateProjection(
            mode="waiting_clarification",
            is_input_enabled=True,
            primary_action="send",
            secondary_actions=["pause", "terminate"],
            bound_run_id="run-1",
        ),
    )

    dumped = workspace.model_dump(mode="json")
    assert dumped["session"]["status"] == "waiting_clarification"
    assert dumped["runs"][0]["trigger_source"] == "initial_requirement"
    assert dumped["narrative_feed"][0]["type"] == "user_message"
    assert dumped["narrative_feed"][1]["type"] == "stage_node"
    assert dumped["narrative_feed"][1]["items"][0]["type"] == "dialogue"
    assert {entry["run_id"] for entry in dumped["narrative_feed"]} == {"run-1"}
    assert dumped["composer_state"] == {
        "mode": "waiting_clarification",
        "is_input_enabled": True,
        "primary_action": "send",
        "secondary_actions": ["pause", "terminate"],
        "bound_run_id": "run-1",
    }

    second_active_run = run.model_copy(update={"run_id": "run-2"})
    with pytest.raises(ValidationError):
        SessionWorkspaceProjection(
            session=build_session(),
            project=build_project(),
            delivery_channel=build_delivery_channel(),
            runs=[run, second_active_run],
            narrative_feed=[],
            current_run_id="run-1",
            current_stage_type=common.StageType.REQUIREMENT_ANALYSIS,
            composer_state=ComposerStateProjection(
                mode="running",
                is_input_enabled=False,
                primary_action="pause",
                secondary_actions=["terminate"],
                bound_run_id="run-1",
            ),
        )


def test_run_timeline_and_solution_artifact_lock_feed_and_downstream_refs() -> None:
    from backend.app.schemas.feed import ExecutionNodeProjection
    from backend.app.schemas.run import (
        ImplementationPlanReference,
        ImplementationPlanTaskRead,
        RunTimelineProjection,
        SolutionDesignArtifactRead,
        SolutionImplementationPlanRead,
    )

    plan_task = ImplementationPlanTaskRead(
        task_id="task-schema-feed",
        order_index=1,
        title="Define feed schemas",
        depends_on_task_ids=[],
        target_files=["backend/app/schemas/feed.py"],
        target_modules=["backend.app.schemas.feed"],
        acceptance_refs=["C1.3"],
        verification_commands=[
            "uv run --no-sync python -m pytest backend/tests/schemas/test_run_feed_event_schemas.py -q"
        ],
        risk_handling="Keep this slice schema-only.",
    )
    implementation_plan = SolutionImplementationPlanRead(
        plan_id="plan-solution-design-1",
        source_stage_run_id="stage-solution-1",
        tasks=[plan_task],
        downstream_refs=[
            "code_generation",
            "test_generation_execution",
            "code_review",
        ],
        created_at=NOW,
    )
    artifact = SolutionDesignArtifactRead(
        artifact_id="artifact-solution-1",
        stage_run_id="stage-solution-1",
        technical_plan="Use Pydantic schemas as the contract boundary.",
        implementation_plan=implementation_plan,
        impacted_files=["backend/app/schemas/feed.py"],
        api_design=None,
        data_flow_design="Workspace projection and SSE events share feed entry objects.",
        risks=["Projection drift between snapshot and SSE payloads."],
        test_strategy="Schema contract tests verify strict payload boundaries.",
        validation_report="Implementation plan covers downstream references.",
        requirement_refs=["requirement-1"],
        evidence_refs=["evidence-1"],
    )
    plan_ref = ImplementationPlanReference(
        artifact_id=artifact.artifact_id,
        implementation_plan_id=artifact.implementation_plan.plan_id,
        task_ids=[plan_task.task_id],
    )
    stage_node = ExecutionNodeProjection(
        entry_id="entry-stage-solution",
        run_id="run-1",
        occurred_at=NOW,
        stage_run_id="stage-solution-1",
        stage_type=common.StageType.SOLUTION_DESIGN,
        status=common.StageStatus.COMPLETED,
        attempt_index=1,
        started_at=NOW,
        ended_at=NOW,
        summary="Solution Design completed with an implementation plan.",
        items=[],
        metrics={},
    )
    timeline = RunTimelineProjection(
        run_id="run-1",
        session_id="session-1",
        attempt_index=1,
        trigger_source=common.RunTriggerSource.INITIAL_REQUIREMENT,
        status=common.RunStatus.RUNNING,
        started_at=NOW,
        ended_at=None,
        current_stage_type=common.StageType.CODE_GENERATION,
        entries=[stage_node],
    )

    assert artifact.implementation_plan.tasks[0].task_id == "task-schema-feed"
    assert artifact.implementation_plan.downstream_refs == [
        "code_generation",
        "test_generation_execution",
        "code_review",
    ]
    assert plan_ref.model_dump(mode="json") == {
        "artifact_id": "artifact-solution-1",
        "implementation_plan_id": "plan-solution-design-1",
        "task_ids": ["task-schema-feed"],
    }
    assert timeline.model_dump(mode="json")["entries"][0]["type"] == "stage_node"

    with pytest.raises(ValidationError):
        RunTimelineProjection(
            run_id="run-1",
            session_id="session-1",
            attempt_index=1,
            trigger_source=common.RunTriggerSource.INITIAL_REQUIREMENT,
            status=common.RunStatus.RUNNING,
            started_at=NOW,
            ended_at=None,
            current_stage_type=common.StageType.CODE_GENERATION,
            entries=[
                {
                    "entry_id": "entry-graph",
                    "run_id": "run-1",
                    "type": "graph_node_started",
                    "occurred_at": NOW,
                }
            ],
        )


def test_tool_confirmation_feed_and_events_are_separate_from_approval() -> None:
    from backend.app.schemas.events import SessionEvent
    from backend.app.schemas.feed import ControlItemFeedEntry, ToolConfirmationFeedEntry

    tool_confirmation = ToolConfirmationFeedEntry(
        entry_id="entry-tool-confirmation",
        run_id="run-1",
        occurred_at=NOW,
        stage_run_id="stage-test-1",
        tool_confirmation_id="tool-confirmation-1",
        status=common.ToolConfirmationStatus.PENDING,
        title="Confirm dependency install",
        tool_name="bash",
        command_preview="npm install",
        target_summary="frontend/package-lock.json",
        risk_level=common.ToolRiskLevel.HIGH_RISK,
        risk_categories=[common.ToolRiskCategory.DEPENDENCY_CHANGE],
        reason="The command modifies dependencies.",
        expected_side_effects=["May update lockfile."],
        allow_action="allow:tool-confirmation-1",
        deny_action="deny:tool-confirmation-1",
        is_actionable=True,
        requested_at=NOW,
        responded_at=None,
        decision=None,
        disabled_reason=None,
    )
    event = SessionEvent(
        event_id="event-tool-confirmation",
        session_id="session-1",
        run_id="run-1",
        event_type=common.SseEventType.TOOL_CONFIRMATION_REQUESTED,
        occurred_at=NOW,
        payload={"tool_confirmation": tool_confirmation.model_dump(mode="json")},
    )

    dumped_tool_confirmation = tool_confirmation.model_dump(mode="json")
    assert dumped_tool_confirmation["type"] == "tool_confirmation"
    assert "approval_id" not in dumped_tool_confirmation
    assert "approval_type" not in dumped_tool_confirmation
    assert "approve_action" not in dumped_tool_confirmation
    assert "reject_action" not in dumped_tool_confirmation
    assert event.payload["tool_confirmation"]["tool_confirmation_id"] == (
        "tool-confirmation-1"
    )

    with pytest.raises(ValidationError):
        ToolConfirmationFeedEntry(
            **tool_confirmation.model_dump(mode="json"),
            approval_id="approval-1",
        )

    with pytest.raises(ValidationError):
        SessionEvent(
            event_id="event-invalid-tool-confirmation",
            session_id="session-1",
            run_id="run-1",
            event_type=common.SseEventType.TOOL_CONFIRMATION_REQUESTED,
            occurred_at=NOW,
            payload={"approval_request": dumped_tool_confirmation},
        )

    with pytest.raises(ValidationError):
        SessionEvent(
            event_id="event-mixed-tool-confirmation",
            session_id="session-1",
            run_id="run-1",
            event_type=common.SseEventType.TOOL_CONFIRMATION_REQUESTED,
            occurred_at=NOW,
            payload={
                "tool_confirmation": dumped_tool_confirmation,
                "approval_request": dumped_tool_confirmation,
            },
        )

    with pytest.raises(ValidationError):
        ControlItemFeedEntry(
            entry_id="entry-invalid-control",
            run_id="run-1",
            occurred_at=NOW,
            control_record_id="control-1",
            control_type="tool_confirmation",
            source_stage_type=common.StageType.TEST_GENERATION_EXECUTION,
            target_stage_type=common.StageType.TEST_GENERATION_EXECUTION,
            title="Invalid control item",
            summary="Tool confirmation must not be a control item.",
            payload_ref="payload-1",
        )


def test_provider_call_stage_item_and_sse_stage_payload_share_projection_semantics() -> None:
    from backend.app.schemas.events import SessionEvent
    from backend.app.schemas.feed import (
        ControlItemFeedEntry,
        ExecutionNodeProjection,
        ProviderCallStageItem,
    )

    provider_item = ProviderCallStageItem(
        item_id="item-provider-call",
        occurred_at=NOW,
        title="DeepSeek retry",
        summary="Provider call is waiting before retry.",
        content="The provider returned a retryable rate limit.",
        artifact_refs=["model-call-trace-1"],
        metrics={"latency_ms": 2300},
        provider_id="provider-deepseek",
        model_id="deepseek-chat",
        status="retrying",
        retry_attempt=2,
        max_retry_attempts=3,
        backoff_wait_seconds=8,
        circuit_breaker_status=common.ProviderCircuitBreakerStatus.CLOSED,
        failure_reason="rate_limited",
        process_ref="provider-retry-trace-1",
    )
    stage_node = ExecutionNodeProjection(
        entry_id="entry-stage-provider",
        run_id="run-1",
        occurred_at=NOW,
        stage_run_id="stage-code-1",
        stage_type=common.StageType.CODE_GENERATION,
        status=common.StageStatus.RUNNING,
        attempt_index=1,
        started_at=NOW,
        ended_at=None,
        summary="Code Generation is retrying a provider call.",
        items=[provider_item],
        metrics={},
    )
    stage_event = SessionEvent(
        event_id="event-stage-updated",
        session_id="session-1",
        run_id="run-1",
        event_type=common.SseEventType.STAGE_UPDATED,
        occurred_at=NOW,
        payload={"stage_node": stage_node.model_dump(mode="json")},
    )
    clarification = ControlItemFeedEntry(
        entry_id="entry-clarification",
        run_id="run-1",
        occurred_at=NOW,
        control_record_id="control-clarification",
        control_type=common.ControlItemType.CLARIFICATION_WAIT,
        source_stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        target_stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        title="Clarification needed",
        summary="Requirement Analysis is waiting for user input.",
        payload_ref="clarification-record-1",
    )
    clarification_event = SessionEvent(
        event_id="event-clarification",
        session_id="session-1",
        run_id="run-1",
        event_type=common.SseEventType.CLARIFICATION_REQUESTED,
        occurred_at=NOW,
        payload={
            "run_id": "run-1",
            "stage_run_id": "stage-requirement-1",
            "control_item": clarification.model_dump(mode="json"),
        },
    )

    provider_dump = stage_node.model_dump(mode="json")["items"][0]
    assert provider_dump["type"] == "provider_call"
    assert provider_dump["status"] == "retrying"
    assert provider_dump["retry_attempt"] == 2
    assert provider_dump["backoff_wait_seconds"] == 8
    assert provider_dump["circuit_breaker_status"] == "closed"
    assert provider_dump["failure_reason"] == "rate_limited"
    assert stage_event.payload["stage_node"]["items"][0]["type"] == "provider_call"
    assert clarification_event.payload["control_item"]["control_type"] == (
        "clarification_wait"
    )

    with pytest.raises(ValidationError):
        ProviderCallStageItem(
            **provider_item.model_dump(mode="json"),
            approval_type="solution_design_approval",
        )


def test_delivery_result_is_success_only_and_failures_use_system_status() -> None:
    from backend.app.schemas.events import SessionEvent
    from backend.app.schemas.feed import DeliveryResultFeedEntry, SystemStatusFeedEntry

    delivery_result = DeliveryResultFeedEntry(
        entry_id="entry-delivery-result",
        run_id="run-1",
        occurred_at=NOW,
        delivery_record_id="delivery-1",
        delivery_mode=common.DeliveryMode.DEMO_DELIVERY,
        status="succeeded",
        summary="Demo delivery completed.",
        branch_name="demo/run-1",
        commit_sha=None,
        code_review_url=None,
        test_summary="44 tests passed.",
        result_ref="delivery-result-ref-1",
    )
    delivery_event = SessionEvent(
        event_id="event-delivery-result",
        session_id="session-1",
        run_id="run-1",
        event_type=common.SseEventType.DELIVERY_RESULT,
        occurred_at=NOW,
        payload={"delivery_result": delivery_result.model_dump(mode="json")},
    )
    failed_status = SystemStatusFeedEntry(
        entry_id="entry-system-status",
        run_id="run-2",
        occurred_at=NOW,
        status=common.RunStatus.FAILED,
        title="Delivery failed",
        reason="Delivery Integration could not coordinate side effects.",
        retry_action="retry:run-2",
    )
    system_event = SessionEvent(
        event_id="event-system-status",
        session_id="session-1",
        run_id="run-2",
        event_type=common.SseEventType.SYSTEM_STATUS,
        occurred_at=NOW,
        payload={"system_status": failed_status.model_dump(mode="json")},
    )

    assert delivery_event.payload["delivery_result"]["status"] == "succeeded"
    assert system_event.payload["system_status"]["status"] == "failed"

    with pytest.raises(ValidationError):
        DeliveryResultFeedEntry(
            **{
                **delivery_result.model_dump(mode="json"),
                "status": "failed",
            }
        )

    with pytest.raises(ValidationError):
        SystemStatusFeedEntry(
            **{
                **failed_status.model_dump(mode="json"),
                "status": "completed",
            }
        )
