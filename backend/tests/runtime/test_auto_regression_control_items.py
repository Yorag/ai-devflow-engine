from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    PipelineTemplateModel,
    ProjectModel,
    SessionModel,
)
from backend.app.db.models.event import DomainEventModel, EventBase
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RunControlRecordModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    RunControlRecordType,
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    StageStatus,
    StageType,
    TemplateSource,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.services.control_records import ControlRecordService
from backend.app.services.projections.inspector import InspectorProjectionService
from backend.tests.runtime.test_auto_regression_policy import (
    code_review_artifact,
    graph_definition,
    runtime_limit_snapshot,
    template_snapshot,
)


NOW = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)


class CapturingApprovalCreator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_code_review_approval(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(approval_id="approval-1", graph_interrupt_ref="interrupt-1")


def build_manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    return manager


def seed_code_review_run(manager: DatabaseManager) -> TraceContext:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Project",
                root_path="C:/repo/project",
                default_delivery_channel_id=None,
                is_default=True,
                is_visible=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            PipelineTemplateModel(
                template_id="template-1",
                name="Template",
                description="Function one template.",
                template_source=TemplateSource.SYSTEM_TEMPLATE,
                base_template_id=None,
                fixed_stage_sequence=[stage.value for stage in StageType],
                stage_role_bindings=[],
                approval_checkpoints=[],
                auto_regression_enabled=True,
                max_auto_regression_retries=2,
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
                display_name="Session",
                status=SessionStatus.RUNNING,
                selected_template_id="template-1",
                current_run_id="run-1",
                latest_stage_type=StageType.CODE_REVIEW,
                is_visible=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RuntimeLimitSnapshotModel(
                snapshot_id="runtime-limit-snapshot-1",
                run_id="run-1",
                agent_limits={"max_auto_regression_retries": 2},
                context_limits={"compression_threshold_ratio": 0.8},
                source_config_version="runtime-settings-v1",
                hard_limits_version="platform-hard-limits-v1",
                schema_version="runtime-limit-snapshot-v1",
                created_at=NOW,
            )
        )
        session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id="provider-call-policy-snapshot-1",
                run_id="run-1",
                provider_call_policy={"request_timeout_seconds": 60},
                source_config_version="provider-policy-v1",
                schema_version="provider-call-policy-snapshot-v1",
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            PipelineRunModel(
                run_id="run-1",
                session_id="session-1",
                project_id="project-1",
                attempt_index=1,
                status=RunStatus.RUNNING,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-1",
                graph_definition_ref="graph-definition-1",
                graph_thread_ref="graph-thread-1",
                workspace_ref="workspace-1",
                runtime_limit_snapshot_ref="runtime-limit-snapshot-1",
                provider_call_policy_snapshot_ref="provider-call-policy-snapshot-1",
                delivery_channel_snapshot_ref=None,
                current_stage_run_id="stage-run-code-review-1",
                trace_id="trace-1",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            StageRunModel(
                stage_run_id="stage-run-code-review-1",
                run_id="run-1",
                stage_type=StageType.CODE_REVIEW,
                status=StageStatus.RUNNING,
                attempt_index=2,
                graph_node_key="code_review",
                stage_contract_ref="stage-contract-code_review",
                input_ref="artifact-code-review-input-1",
                output_ref="artifact-code-review-output-1",
                summary="Reviewing generated code.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

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


def test_append_retry_control_item_persists_record_event_and_inspector_metrics(
    tmp_path,
) -> None:
    manager = build_manager(tmp_path)
    trace = seed_code_review_run(manager)

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = ControlRecordService(
            runtime_session=runtime_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        result = service.append_retry_control_item(
            run_id="run-1",
            stage_run_id="stage-run-code-review-1",
            source_stage_type=StageType.CODE_REVIEW,
            target_stage_type=StageType.CODE_GENERATION,
            payload_ref="stage-artifact://code-review-artifact-1/output",
            summary=(
                "Automatic regression retry 2 within the current run; "
                "continue in code_generation from Code Review attempt 1."
            ),
            retry_index=2,
            source_attempt_index=1,
            trace_context=trace,
        )
        runtime_session.commit()
        event_session.commit()
        control_record_id = result.control_record.control_record_id

    with manager.session(DatabaseRole.RUNTIME) as session:
        control = session.get(RunControlRecordModel, control_record_id)
        assert control is not None
        assert control.control_type is RunControlRecordType.RETRY
        assert control.source_stage_type is StageType.CODE_REVIEW
        assert control.target_stage_type is StageType.CODE_GENERATION
        artifact = session.get(StageArtifactModel, f"artifact-{control_record_id}")
        assert artifact is not None
        assert artifact.artifact_type == "control_item_trace"
        assert artifact.process["control_record_id"] == control_record_id
        assert artifact.process["output_snapshot"]["source_attempt_index"] == 1
        assert artifact.process["output_snapshot"]["policy_source_attempt_index"] == 1
        assert artifact.metrics == {"retry_index": 2, "source_attempt_index": 1}

    with manager.session(DatabaseRole.EVENT) as session:
        event = session.query(DomainEventModel).one()
        assert event.event_type.value == "control_item_created"
        assert event.payload["control_item"]["control_type"] == "retry"
        assert event.payload["control_item"]["target_stage_type"] == "code_generation"

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_control_item_detail(control_record_id)

    dumped = projection.model_dump(mode="json")
    assert dumped["control_type"] == "retry"
    assert dumped["output"]["records"]["target_stage_type"] == "code_generation"
    assert dumped["metrics"] == {"retry_index": 2, "source_attempt_index": 1}


def test_auto_regression_runner_appends_retry_control_item_for_retry_decision(
    tmp_path,
) -> None:
    from backend.app.runtime.auto_regression import AutoRegressionRunner

    manager = build_manager(tmp_path)
    trace = seed_code_review_run(manager)
    template = template_snapshot(max_auto_regression_retries=2)
    runtime_limit = runtime_limit_snapshot(max_auto_regression_retries=2)
    graph = graph_definition(template=template, runtime_limit=runtime_limit)

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        runner = AutoRegressionRunner(
            control_records=ControlRecordService(
                runtime_session=runtime_session,
                event_session=event_session,
                now=lambda: NOW,
            )
        )
        result = runner.run(
            session_id="session-1",
            code_review_artifact=code_review_artifact(),
            code_review_artifact_ref="stage-artifact://code-review-artifact-1/output",
            template_snapshot=template,
            runtime_limit_snapshot=runtime_limit,
            graph_definition=graph,
            attempts_used=1,
            source_attempt_index=1,
            trace_context=trace,
            approval_object_excerpt="Review found issues.",
            risk_excerpt="Medium regression risk.",
            approval_object_preview={"review": "summary"},
        )
        runtime_session.commit()
        event_session.commit()

    assert result.status == "retry_control_item_appended"
    assert result.decision.retry_index == 2
    assert result.control_item is not None
    assert result.control_item.control_type.value == "retry"
    assert result.control_item.payload_ref == (
        "stage-artifact://code-review-artifact-1/output"
    )
    assert result.trace_artifact_id is not None


def test_auto_regression_runner_exposes_first_retry_control_metrics(
    tmp_path,
) -> None:
    from backend.app.runtime.auto_regression import AutoRegressionRunner

    manager = build_manager(tmp_path)
    trace = seed_code_review_run(manager)
    template = template_snapshot(max_auto_regression_retries=2)
    runtime_limit = runtime_limit_snapshot(max_auto_regression_retries=2)
    graph = graph_definition(template=template, runtime_limit=runtime_limit)

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        runner = AutoRegressionRunner(
            control_records=ControlRecordService(
                runtime_session=runtime_session,
                event_session=event_session,
                now=lambda: NOW,
            )
        )
        result = runner.run(
            session_id="session-1",
            code_review_artifact=code_review_artifact(),
            code_review_artifact_ref="stage-artifact://code-review-artifact-1/output",
            template_snapshot=template,
            runtime_limit_snapshot=runtime_limit,
            graph_definition=graph,
            attempts_used=0,
            source_attempt_index=0,
            trace_context=trace,
            approval_object_excerpt="Review found issues.",
            risk_excerpt="Medium regression risk.",
            approval_object_preview={"review": "summary"},
        )
        runtime_session.commit()
        event_session.commit()
        control_record_id = result.control_record_id

    assert control_record_id is not None
    with manager.session(DatabaseRole.RUNTIME) as session:
        artifact = session.get(StageArtifactModel, f"artifact-{control_record_id}")
        assert artifact is not None
        assert artifact.process["output_snapshot"]["source_attempt_index"] == 1
        assert artifact.process["output_snapshot"]["policy_source_attempt_index"] == 0

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_control_item_detail(control_record_id)

    assert projection.metrics.model_dump(mode="json") == {
        "retry_index": 1,
        "source_attempt_index": 1,
    }


def test_auto_regression_runner_blocks_disabled_regression_without_approval(
    tmp_path,
) -> None:
    from backend.app.runtime.auto_regression import AutoRegressionRunner

    manager = build_manager(tmp_path)
    trace = seed_code_review_run(manager)
    template = template_snapshot(
        auto_regression_enabled=False,
        max_auto_regression_retries=0,
    )
    runtime_limit = runtime_limit_snapshot(max_auto_regression_retries=0)
    graph = graph_definition(template=template, runtime_limit=runtime_limit)
    approval_creator = CapturingApprovalCreator()

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        runner = AutoRegressionRunner(
            control_records=ControlRecordService(
                runtime_session=runtime_session,
                event_session=event_session,
                now=lambda: NOW,
            ),
            approval_creator=approval_creator,
        )
        result = runner.run(
            session_id="session-1",
            code_review_artifact=code_review_artifact(),
            code_review_artifact_ref="stage-artifact://code-review-artifact-1/output",
            template_snapshot=template,
            runtime_limit_snapshot=runtime_limit,
            graph_definition=graph,
            attempts_used=0,
            source_attempt_index=0,
            trace_context=trace,
            approval_object_excerpt="Review found unresolved issues.",
            risk_excerpt="High risk.",
            approval_object_preview={"review": "changes_requested"},
        )

        assert runtime_session.query(RunControlRecordModel).count() == 0

    assert result.status == "blocked"
    assert result.decision.reason == "auto_regression_disabled"
    assert approval_creator.calls == []


def test_auto_regression_runner_marks_retry_exhausted_without_silent_approval(
    tmp_path,
) -> None:
    from backend.app.runtime.auto_regression import AutoRegressionRunner

    manager = build_manager(tmp_path)
    trace = seed_code_review_run(manager)
    template = template_snapshot(max_auto_regression_retries=1)
    runtime_limit = runtime_limit_snapshot(max_auto_regression_retries=1)
    graph = graph_definition(template=template, runtime_limit=runtime_limit)
    approval_creator = CapturingApprovalCreator()

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        runner = AutoRegressionRunner(
            control_records=ControlRecordService(
                runtime_session=runtime_session,
                event_session=event_session,
                now=lambda: NOW,
            ),
            approval_creator=approval_creator,
        )
        result = runner.run(
            session_id="session-1",
            code_review_artifact=code_review_artifact(),
            code_review_artifact_ref="stage-artifact://code-review-artifact-1/output",
            template_snapshot=template,
            runtime_limit_snapshot=runtime_limit,
            graph_definition=graph,
            attempts_used=1,
            source_attempt_index=1,
            trace_context=trace,
            approval_object_excerpt="Review found unresolved issues.",
            risk_excerpt="High risk.",
            approval_object_preview={"review": "summary"},
        )

        assert runtime_session.query(RunControlRecordModel).count() == 0

    assert result.status == "retry_exhausted"
    assert result.exhausted_failure is not None
    assert result.exhausted_failure.stage_status is StageStatus.FAILED
    assert (
        result.exhausted_failure.reason == "auto_regression_retry_limit_exhausted"
    )
    assert "Retry limit exhausted" in result.exhausted_failure.user_visible_summary
    assert approval_creator.calls == []


def test_auto_regression_runner_creates_code_review_approval_for_stable_review(
    tmp_path,
) -> None:
    from backend.app.runtime.auto_regression import AutoRegressionRunner

    manager = build_manager(tmp_path)
    trace = seed_code_review_run(manager)
    template = template_snapshot(max_auto_regression_retries=2)
    runtime_limit = runtime_limit_snapshot(max_auto_regression_retries=2)
    graph = graph_definition(template=template, runtime_limit=runtime_limit)
    approval_creator = CapturingApprovalCreator()

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        runner = AutoRegressionRunner(
            control_records=ControlRecordService(
                runtime_session=runtime_session,
                event_session=event_session,
                now=lambda: NOW,
            ),
            approval_creator=approval_creator,
        )
        result = runner.run(
            session_id="session-1",
            code_review_artifact=code_review_artifact(regression_decision="approved"),
            code_review_artifact_ref="stage-artifact://code-review-artifact-1/output",
            template_snapshot=template,
            runtime_limit_snapshot=runtime_limit,
            graph_definition=graph,
            attempts_used=1,
            source_attempt_index=1,
            trace_context=trace,
            approval_object_excerpt="Review approved.",
            risk_excerpt=None,
            approval_object_preview={"review": "approved"},
        )

        assert runtime_session.query(RunControlRecordModel).count() == 0

    assert result.status == "approval_requested"
    assert len(approval_creator.calls) == 1
    assert approval_creator.calls[0]["session_id"] == "session-1"
    assert approval_creator.calls[0]["run_id"] == "run-1"
    assert approval_creator.calls[0]["stage_run_id"] == "stage-run-code-review-1"
    assert approval_creator.calls[0]["payload_ref"] == (
        "stage-artifact://code-review-artifact-1/output"
    )


@pytest.mark.parametrize(
    ("retry_index", "source_attempt_index", "expected_error"),
    [
        (0, 1, "retry_index"),
        (True, 1, "retry_index"),
        (1, 0, "source_attempt_index"),
        (1, True, "source_attempt_index"),
    ],
)
def test_append_retry_control_item_rejects_invalid_attempt_indexes(
    tmp_path,
    retry_index: int,
    source_attempt_index: int,
    expected_error: str,
) -> None:
    manager = build_manager(tmp_path)
    trace = seed_code_review_run(manager)

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = ControlRecordService(
            runtime_session=runtime_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        with pytest.raises(ValueError, match=expected_error):
            service.append_retry_control_item(
                run_id="run-1",
                stage_run_id="stage-run-code-review-1",
                source_stage_type=StageType.CODE_REVIEW,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="stage-artifact://code-review-artifact-1/output",
                summary="Invalid retry.",
                retry_index=retry_index,
                source_attempt_index=source_attempt_index,
                trace_context=trace,
            )
