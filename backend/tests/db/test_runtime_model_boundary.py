from datetime import UTC, datetime

from sqlalchemy import inspect

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    RunControlRecordType,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
RUNTIME_TABLES = {
    "pipeline_runs",
    "stage_runs",
    "stage_artifacts",
    "clarification_records",
    "approval_requests",
    "approval_decisions",
    "tool_confirmation_requests",
    "run_control_records",
    "runtime_limit_snapshots",
    "provider_call_policy_snapshots",
    "provider_snapshots",
    "model_binding_snapshots",
    "delivery_channel_snapshots",
    "delivery_records",
}
FORBIDDEN_RUNTIME_TABLES = {
    "projects",
    "sessions",
    "pipeline_templates",
    "providers",
    "delivery_channels",
    "platform_runtime_settings",
    "graph_definitions",
    "graph_threads",
    "graph_checkpoints",
    "graph_interrupts",
    "domain_events",
    "run_log_entries",
    "audit_log_entries",
    "log_payloads",
    "feed_entries",
    "inspector_projections",
}


def enum_values(enum_type: type) -> list[str]:
    return [item.value for item in enum_type]


def test_runtime_models_register_only_runtime_role_metadata() -> None:
    from backend.app.db.models.runtime import (
        ApprovalDecisionModel,
        ApprovalRequestModel,
        ClarificationRecordModel,
        DeliveryChannelSnapshotModel,
        DeliveryRecordModel,
        ModelBindingSnapshotModel,
        PipelineRunModel,
        ProviderCallPolicySnapshotModel,
        ProviderSnapshotModel,
        RunControlRecordModel,
        RuntimeBase,
        RuntimeLimitSnapshotModel,
        StageArtifactModel,
        StageRunModel,
        ToolConfirmationRequestModel,
    )

    assert RuntimeBase.metadata is ROLE_METADATA[DatabaseRole.RUNTIME]
    assert {table.name for table in RuntimeBase.metadata.sorted_tables} == RUNTIME_TABLES
    assert FORBIDDEN_RUNTIME_TABLES.isdisjoint(RuntimeBase.metadata.tables)

    for model in (
        PipelineRunModel,
        StageRunModel,
        StageArtifactModel,
        ClarificationRecordModel,
        ApprovalRequestModel,
        ApprovalDecisionModel,
        ToolConfirmationRequestModel,
        RunControlRecordModel,
        RuntimeLimitSnapshotModel,
        ProviderCallPolicySnapshotModel,
        ProviderSnapshotModel,
        ModelBindingSnapshotModel,
        DeliveryChannelSnapshotModel,
        DeliveryRecordModel,
    ):
        assert model.metadata is ROLE_METADATA[DatabaseRole.RUNTIME]

    for role in (
        DatabaseRole.CONTROL,
        DatabaseRole.GRAPH,
        DatabaseRole.EVENT,
        DatabaseRole.LOG,
    ):
        assert RUNTIME_TABLES.isdisjoint(ROLE_METADATA[role].tables)


def test_runtime_tables_create_only_in_runtime_database(tmp_path) -> None:
    from backend.app.db.models.runtime import RuntimeBase

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))

    with manager.session(DatabaseRole.RUNTIME) as session:
        runtime_tables = set(inspect(session.bind).get_table_names())

    assert RUNTIME_TABLES.issubset(runtime_tables)
    assert FORBIDDEN_RUNTIME_TABLES.isdisjoint(runtime_tables)

    for role in (
        DatabaseRole.CONTROL,
        DatabaseRole.GRAPH,
        DatabaseRole.EVENT,
        DatabaseRole.LOG,
    ):
        with manager.session(role) as session:
            assert RUNTIME_TABLES.isdisjoint(inspect(session.bind).get_table_names())


def test_pipeline_run_stage_and_snapshot_models_express_runtime_truth(tmp_path) -> None:
    from backend.app.db.models.runtime import (
        ModelBindingSnapshotModel,
        PipelineRunModel,
        ProviderCallPolicySnapshotModel,
        ProviderSnapshotModel,
        RuntimeBase,
        RuntimeLimitSnapshotModel,
        StageArtifactModel,
        StageRunModel,
    )

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))

    with manager.session(DatabaseRole.RUNTIME) as session:
        run = PipelineRunModel(
            run_id="run-1",
            session_id="session-1",
            project_id="project-default",
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
            current_stage_run_id="stage-run-1",
            trace_id="trace-1",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        runtime_limit_snapshot = RuntimeLimitSnapshotModel(
            snapshot_id="runtime-limit-snapshot-1",
            run_id=run.run_id,
            agent_limits={"max_react_iterations_per_stage": 30},
            context_limits={"compression_threshold_ratio": 0.8},
            source_config_version="runtime-settings-v1",
            hard_limits_version="platform-hard-limits-v1",
            schema_version="runtime-limit-snapshot-v1",
            created_at=NOW,
        )
        provider_call_policy_snapshot = ProviderCallPolicySnapshotModel(
            snapshot_id="provider-call-policy-snapshot-1",
            run_id=run.run_id,
            provider_call_policy={
                "request_timeout_seconds": 60,
                "network_error_max_retries": 3,
                "rate_limit_max_retries": 3,
                "backoff_base_seconds": 1.0,
                "backoff_max_seconds": 30.0,
                "circuit_breaker_failure_threshold": 5,
                "circuit_breaker_recovery_seconds": 60,
            },
            source_config_version="runtime-settings-v1",
            schema_version="provider-call-policy-snapshot-v1",
            created_at=NOW,
        )
        provider_snapshot = ProviderSnapshotModel(
            snapshot_id="provider-snapshot-1",
            run_id=run.run_id,
            provider_id="provider-deepseek",
            display_name="DeepSeek",
            provider_source=ProviderSource.BUILTIN,
            protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
            base_url="https://api.deepseek.com",
            api_key_ref="env:DEEPSEEK_API_KEY",
            model_id="deepseek-chat",
            capabilities={
                "model_id": "deepseek-chat",
                "context_window_tokens": 128000,
                "max_output_tokens": 8192,
                "supports_tool_calling": False,
                "supports_structured_output": False,
                "supports_native_reasoning": False,
            },
            source_config_version="provider-config-v1",
            schema_version="provider-snapshot-v1",
            created_at=NOW,
        )
        model_binding_snapshot = ModelBindingSnapshotModel(
            snapshot_id="model-binding-snapshot-1",
            run_id=run.run_id,
            binding_id="role-requirement-analyst",
            binding_type="agent_role",
            stage_type=StageType.REQUIREMENT_ANALYSIS,
            role_id="role-requirement-analyst",
            provider_snapshot_id=provider_snapshot.snapshot_id,
            provider_id=provider_snapshot.provider_id,
            model_id=provider_snapshot.model_id,
            capabilities=provider_snapshot.capabilities,
            model_parameters={"temperature": 0.2},
            source_config_version="template-config-v1",
            schema_version="model-binding-snapshot-v1",
            created_at=NOW,
        )
        stage_run = StageRunModel(
            stage_run_id="stage-run-1",
            run_id=run.run_id,
            stage_type=StageType.REQUIREMENT_ANALYSIS,
            status=StageStatus.RUNNING,
            attempt_index=1,
            graph_node_key="requirement_analysis.main",
            stage_contract_ref="stage-contract-requirement-analysis",
            input_ref="artifact-input-1",
            output_ref=None,
            summary="Analyzing the first requirement.",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        artifact = StageArtifactModel(
            artifact_id="artifact-input-1",
            run_id=run.run_id,
            stage_run_id=stage_run.stage_run_id,
            artifact_type="requirement_input",
            payload_ref="payload-ref-1",
            process={"source": "composer"},
            metrics={"token_count": 12},
            created_at=NOW,
        )
        session.add_all([runtime_limit_snapshot, provider_call_policy_snapshot])
        session.flush()
        session.add(run)
        session.flush()
        session.add_all([provider_snapshot, stage_run])
        session.flush()
        session.add_all([model_binding_snapshot, artifact])
        session.commit()

        saved_run = session.get(PipelineRunModel, "run-1")
        saved_runtime_limit = session.get(RuntimeLimitSnapshotModel, "runtime-limit-snapshot-1")
        saved_model_binding = session.get(ModelBindingSnapshotModel, "model-binding-snapshot-1")

    assert saved_run is not None
    assert saved_run.session_id == "session-1"
    assert saved_run.runtime_limit_snapshot_ref == "runtime-limit-snapshot-1"
    assert saved_run.provider_call_policy_snapshot_ref == "provider-call-policy-snapshot-1"
    assert saved_run.trace_id == "trace-1"
    assert saved_runtime_limit is not None
    assert saved_runtime_limit.context_limits["compression_threshold_ratio"] == 0.8
    assert saved_model_binding is not None
    assert saved_model_binding.capabilities["context_window_tokens"] == 128000

    run_columns = set(PipelineRunModel.__table__.columns.keys())
    assert {
        "run_id",
        "session_id",
        "project_id",
        "attempt_index",
        "status",
        "trigger_source",
        "template_snapshot_ref",
        "graph_definition_ref",
        "graph_thread_ref",
        "runtime_limit_snapshot_ref",
        "provider_call_policy_snapshot_ref",
        "trace_id",
    }.issubset(run_columns)
    assert {
        "session_status",
        "display_name",
        "selected_template_id",
        "graph_checkpoint_payload",
        "domain_event_payload",
        "audit_payload",
        "log_payload",
    }.isdisjoint(run_columns)

    stage_columns = set(StageRunModel.__table__.columns.keys())
    assert {"graph_node_key", "stage_contract_ref"}.issubset(stage_columns)


def test_stage_and_control_enums_keep_product_semantics() -> None:
    from backend.app.db.models.runtime import (
        RunControlRecordModel,
        StageRunModel,
        ToolConfirmationRequestModel,
    )

    stage_type = StageRunModel.__table__.columns["stage_type"].type
    stage_status = StageRunModel.__table__.columns["status"].type
    control_type = RunControlRecordModel.__table__.columns["control_type"].type
    tool_status = ToolConfirmationRequestModel.__table__.columns["status"].type

    assert stage_type.enums == enum_values(StageType)
    assert stage_status.enums == enum_values(StageStatus)
    assert "pending" not in stage_status.enums
    assert "draft" not in stage_status.enums
    assert control_type.enums == enum_values(RunControlRecordType)
    assert "tool_confirmation" in control_type.enums
    assert "system_status" not in control_type.enums
    assert tool_status.enums == enum_values(ToolConfirmationStatus)
    assert "approved" not in tool_status.enums
    assert "rejected" not in tool_status.enums


def test_approval_tool_confirmation_and_delivery_boundaries_are_separate(tmp_path) -> None:
    from backend.app.db.models.runtime import (
        ApprovalDecisionModel,
        ApprovalRequestModel,
        DeliveryChannelSnapshotModel,
        DeliveryRecordModel,
        PipelineRunModel,
        ProviderCallPolicySnapshotModel,
        RunControlRecordModel,
        RuntimeBase,
        RuntimeLimitSnapshotModel,
        StageRunModel,
        ToolConfirmationRequestModel,
    )

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))

    with manager.session(DatabaseRole.RUNTIME) as session:
        run = PipelineRunModel(
            run_id="run-approval-1",
            session_id="session-approval-1",
            project_id="project-default",
            attempt_index=1,
            status=RunStatus.WAITING_TOOL_CONFIRMATION,
            trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
            template_snapshot_ref="template-snapshot-1",
            graph_definition_ref="graph-definition-1",
            graph_thread_ref="graph-thread-1",
            workspace_ref="workspace-1",
            runtime_limit_snapshot_ref="runtime-limit-snapshot-tool-1",
            provider_call_policy_snapshot_ref="provider-call-policy-snapshot-tool-1",
            delivery_channel_snapshot_ref="delivery-channel-snapshot-1",
            current_stage_run_id="stage-run-tool-1",
            trace_id="trace-tool-1",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        runtime_limit_snapshot = RuntimeLimitSnapshotModel(
            snapshot_id="runtime-limit-snapshot-tool-1",
            run_id=run.run_id,
            agent_limits={"max_tool_calls_per_stage": 80},
            context_limits={"compression_threshold_ratio": 0.8},
            source_config_version="runtime-settings-v1",
            hard_limits_version="platform-hard-limits-v1",
            schema_version="runtime-limit-snapshot-v1",
            created_at=NOW,
        )
        provider_call_policy_snapshot = ProviderCallPolicySnapshotModel(
            snapshot_id="provider-call-policy-snapshot-tool-1",
            run_id=run.run_id,
            provider_call_policy={
                "request_timeout_seconds": 60,
                "network_error_max_retries": 3,
                "rate_limit_max_retries": 3,
                "backoff_base_seconds": 1.0,
                "backoff_max_seconds": 30.0,
                "circuit_breaker_failure_threshold": 5,
                "circuit_breaker_recovery_seconds": 60,
            },
            source_config_version="runtime-settings-v1",
            schema_version="provider-call-policy-snapshot-v1",
            created_at=NOW,
        )
        solution_stage = StageRunModel(
            stage_run_id="stage-run-solution-1",
            run_id=run.run_id,
            stage_type=StageType.SOLUTION_DESIGN,
            status=StageStatus.WAITING_APPROVAL,
            attempt_index=1,
            graph_node_key="solution_design.main",
            stage_contract_ref="stage-contract-solution-design",
            input_ref="artifact-solution-input-1",
            output_ref="solution-design-artifact-1",
            summary="Waiting for solution design approval.",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        tool_stage = StageRunModel(
            stage_run_id="stage-run-tool-1",
            run_id=run.run_id,
            stage_type=StageType.CODE_GENERATION,
            status=StageStatus.WAITING_TOOL_CONFIRMATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="artifact-code-input-1",
            output_ref=None,
            summary="Waiting for a high-risk bash confirmation.",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        delivery_stage = StageRunModel(
            stage_run_id="stage-run-delivery-1",
            run_id=run.run_id,
            stage_type=StageType.DELIVERY_INTEGRATION,
            status=StageStatus.COMPLETED,
            attempt_index=1,
            graph_node_key="delivery_integration.main",
            stage_contract_ref="stage-contract-delivery-integration",
            input_ref="artifact-delivery-input-1",
            output_ref="delivery-result-1",
            summary="Delivered the result.",
            started_at=NOW,
            ended_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        approval_request = ApprovalRequestModel(
            approval_id="approval-1",
            run_id=run.run_id,
            stage_run_id="stage-run-solution-1",
            approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
            status=ApprovalStatus.PENDING,
            payload_ref="solution-design-artifact-1",
            graph_interrupt_ref="graph-interrupt-approval-1",
            requested_at=NOW,
            resolved_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        approval_decision = ApprovalDecisionModel(
            decision_id="approval-decision-1",
            approval_id=approval_request.approval_id,
            run_id=run.run_id,
            decision=ApprovalStatus.APPROVED,
            reason=None,
            decided_by_actor_id="user-1",
            decided_at=NOW,
            created_at=NOW,
        )
        tool_confirmation = ToolConfirmationRequestModel(
            tool_confirmation_id="tool-confirmation-1",
            run_id=run.run_id,
            stage_run_id="stage-run-tool-1",
            confirmation_object_ref="tool-call-1",
            tool_name="bash",
            command_preview="npm install",
            target_summary="Install project dependencies.",
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.DEPENDENCY_CHANGE.value],
            reason="Dependency installation changes the workspace.",
            expected_side_effects=["Updates node_modules."],
            alternative_path_summary="Use already installed dependencies if available.",
            user_decision=None,
            status=ToolConfirmationStatus.PENDING,
            graph_interrupt_ref="graph-interrupt-tool-1",
            audit_log_ref="audit-log-1",
            process_ref="stage-process-1",
            requested_at=NOW,
            responded_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        control_record = RunControlRecordModel(
            control_record_id="control-tool-1",
            run_id=run.run_id,
            stage_run_id="stage-run-tool-1",
            control_type=RunControlRecordType.TOOL_CONFIRMATION,
            source_stage_type=StageType.CODE_GENERATION,
            target_stage_type=None,
            payload_ref=tool_confirmation.tool_confirmation_id,
            graph_interrupt_ref=tool_confirmation.graph_interrupt_ref,
            occurred_at=NOW,
            created_at=NOW,
        )
        delivery_snapshot = DeliveryChannelSnapshotModel(
            delivery_channel_snapshot_id="delivery-channel-snapshot-1",
            run_id=run.run_id,
            source_delivery_channel_id="delivery-default",
            delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
            scm_provider_type=ScmProviderType.GITHUB,
            repository_identifier="owner/repo",
            default_branch="main",
            code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
            credential_ref="env:GITHUB_TOKEN",
            credential_status=CredentialStatus.READY,
            readiness_status=DeliveryReadinessStatus.READY,
            readiness_message="Ready for git_auto_delivery.",
            last_validated_at=NOW,
            schema_version="delivery-channel-snapshot-v1",
            created_at=NOW,
        )
        delivery_record = DeliveryRecordModel(
            delivery_record_id="delivery-record-1",
            run_id=run.run_id,
            stage_run_id="stage-run-delivery-1",
            delivery_channel_snapshot_ref=delivery_snapshot.delivery_channel_snapshot_id,
            delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
            status="succeeded",
            branch_name="feat/example",
            commit_sha="abc1234",
            code_review_url="https://example.test/pull/1",
            result_ref="delivery-result-1",
            process_ref="delivery-process-1",
            failure_reason=None,
            created_at=NOW,
            completed_at=NOW,
        )
        session.add_all(
            [runtime_limit_snapshot, provider_call_policy_snapshot, delivery_snapshot]
        )
        session.flush()
        session.add(run)
        session.flush()
        session.add_all([solution_stage, tool_stage, delivery_stage])
        session.flush()
        session.add_all([approval_request, tool_confirmation])
        session.flush()
        session.add_all([approval_decision, control_record, delivery_record])
        session.commit()

        saved_tool_confirmation = session.get(
            ToolConfirmationRequestModel,
            "tool-confirmation-1",
        )
        saved_delivery_record = session.get(DeliveryRecordModel, "delivery-record-1")

    assert saved_tool_confirmation is not None
    assert saved_tool_confirmation.status is ToolConfirmationStatus.PENDING
    assert saved_tool_confirmation.risk_categories == [ToolRiskCategory.DEPENDENCY_CHANGE.value]
    assert saved_delivery_record is not None
    assert saved_delivery_record.delivery_channel_snapshot_ref == "delivery-channel-snapshot-1"

    tool_columns = set(ToolConfirmationRequestModel.__table__.columns.keys())
    assert {
        "confirmation_object_ref",
        "tool_name",
        "command_preview",
        "target_summary",
        "risk_level",
        "risk_categories",
        "expected_side_effects",
        "alternative_path_summary",
        "user_decision",
        "status",
        "graph_interrupt_ref",
        "audit_log_ref",
        "process_ref",
    }.issubset(tool_columns)
    assert {"approval_id", "approval_type", "approval_decision_id"}.isdisjoint(tool_columns)

    delivery_snapshot_columns = set(DeliveryChannelSnapshotModel.__table__.columns.keys())
    assert {
        "delivery_mode",
        "scm_provider_type",
        "repository_identifier",
        "default_branch",
        "code_review_request_type",
        "credential_ref",
        "credential_status",
        "readiness_status",
        "readiness_message",
        "last_validated_at",
    }.issubset(delivery_snapshot_columns)
