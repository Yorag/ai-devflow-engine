from datetime import UTC, datetime

from sqlalchemy import inspect

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    ScmProviderType,
    SessionStatus,
    StageType,
    TemplateSource,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
CONTROL_TABLES = {
    "projects",
    "sessions",
    "startup_publications",
    "pipeline_templates",
    "providers",
    "delivery_channels",
    "platform_runtime_settings",
}
FORBIDDEN_CONTROL_TABLES = {
    "pipeline_runs",
    "stage_runs",
    "graph_threads",
    "domain_events",
    "run_log_entries",
    "audit_log_entries",
    "log_payloads",
    "approval_requests",
    "delivery_records",
    "tool_confirmation_requests",
    "stage_artifacts",
}


def test_control_models_register_only_control_role_metadata() -> None:
    from backend.app.db.models.control import (
        ControlBase,
        DeliveryChannelModel,
        PipelineTemplateModel,
        PlatformRuntimeSettingsModel,
        ProjectModel,
        ProviderModel,
        SessionModel,
    )

    assert ControlBase.metadata is ROLE_METADATA[DatabaseRole.CONTROL]
    assert {table.name for table in ControlBase.metadata.sorted_tables} == CONTROL_TABLES
    assert FORBIDDEN_CONTROL_TABLES.isdisjoint(ControlBase.metadata.tables)

    for model in (
        ProjectModel,
        SessionModel,
        PipelineTemplateModel,
        ProviderModel,
        DeliveryChannelModel,
        PlatformRuntimeSettingsModel,
    ):
        assert model.metadata is ROLE_METADATA[DatabaseRole.CONTROL]

    for role in (
        DatabaseRole.RUNTIME,
        DatabaseRole.GRAPH,
        DatabaseRole.EVENT,
        DatabaseRole.LOG,
    ):
        assert CONTROL_TABLES.isdisjoint(ROLE_METADATA[role].tables)


def test_control_tables_create_only_in_control_database(tmp_path) -> None:
    from backend.app.db.models.control import ControlBase

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))

    with manager.session(DatabaseRole.CONTROL) as session:
        control_tables = set(inspect(session.bind).get_table_names())

    assert CONTROL_TABLES.issubset(control_tables)
    assert FORBIDDEN_CONTROL_TABLES.isdisjoint(control_tables)

    for role in (
        DatabaseRole.RUNTIME,
        DatabaseRole.GRAPH,
        DatabaseRole.EVENT,
        DatabaseRole.LOG,
    ):
        with manager.session(role) as session:
            assert CONTROL_TABLES.isdisjoint(inspect(session.bind).get_table_names())


def test_project_session_template_models_express_control_history_boundary(tmp_path) -> None:
    from backend.app.db.models.control import (
        ControlBase,
        PipelineTemplateModel,
        ProjectModel,
        SessionModel,
    )

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))

    with manager.session(DatabaseRole.CONTROL) as session:
        project = ProjectModel(
            project_id="project-default",
            name="AI Devflow Engine",
            root_path="C:/repo/ai-devflow-engine",
            default_delivery_channel_id=None,
            is_default=True,
            is_visible=True,
            visibility_removed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        template = PipelineTemplateModel(
            template_id="template-feature",
            name="New Feature Flow",
            description="Default flow for new feature delivery.",
            template_source=TemplateSource.SYSTEM_TEMPLATE,
            base_template_id=None,
            fixed_stage_sequence=[
                StageType.REQUIREMENT_ANALYSIS.value,
                StageType.SOLUTION_DESIGN.value,
                StageType.CODE_GENERATION.value,
                StageType.TEST_GENERATION_EXECUTION.value,
                StageType.CODE_REVIEW.value,
                StageType.DELIVERY_INTEGRATION.value,
            ],
            stage_role_bindings=[
                {
                    "stage_type": StageType.REQUIREMENT_ANALYSIS.value,
                    "role_id": "role-requirement-analyst",
                    "system_prompt": "Analyze requirements.",
                    "provider_id": "provider-deepseek",
                }
            ],
            approval_checkpoints=["solution_design_approval", "code_review_approval"],
            auto_regression_enabled=True,
            max_auto_regression_retries=2,
            max_react_iterations_per_stage=30,
            max_tool_calls_per_stage=80,
            skip_high_risk_tool_confirmations=False,
            created_at=NOW,
            updated_at=NOW,
        )
        draft_session = SessionModel(
            session_id="session-1",
            project_id=project.project_id,
            display_name="Add control models",
            status=SessionStatus.DRAFT,
            selected_template_id=template.template_id,
            current_run_id=None,
            latest_stage_type=None,
            is_visible=True,
            visibility_removed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([project, template, draft_session])
        session.commit()

    project_columns = set(ProjectModel.__table__.columns.keys())
    session_columns = set(SessionModel.__table__.columns.keys())
    template_columns = set(PipelineTemplateModel.__table__.columns.keys())

    assert {"is_default", "is_visible", "visibility_removed_at"}.issubset(project_columns)
    assert {"display_name", "status", "current_run_id", "latest_stage_type"}.issubset(
        session_columns
    )
    assert {"fixed_stage_sequence", "stage_role_bindings", "approval_checkpoints"}.issubset(
        template_columns
    )
    assert {
        "max_react_iterations_per_stage",
        "max_tool_calls_per_stage",
        "skip_high_risk_tool_confirmations",
    }.issubset(template_columns)
    assert {
        "deletes_local_project_folder",
        "deletes_target_repository",
        "deletes_remote_repository",
        "deletes_remote_branch",
        "deletes_commits",
        "deletes_code_review_requests",
    }.isdisjoint(project_columns | session_columns)
    assert "pipeline_run_id" not in template_columns


def test_provider_and_delivery_channel_models_keep_control_configuration_boundary(tmp_path) -> None:
    from backend.app.db.models.control import (
        ControlBase,
        DeliveryChannelModel,
        ProjectModel,
        ProviderModel,
    )

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))

    with manager.session(DatabaseRole.CONTROL) as session:
        project = ProjectModel(
            project_id="project-default",
            name="AI Devflow Engine",
            root_path="C:/repo/ai-devflow-engine",
            default_delivery_channel_id="delivery-default",
            is_default=True,
            is_visible=True,
            visibility_removed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        provider = ProviderModel(
            provider_id="provider-deepseek",
            display_name="DeepSeek",
            provider_source=ProviderSource.BUILTIN,
            protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
            base_url="https://api.deepseek.com",
            api_key_ref="env:DEEPSEEK_API_KEY",
            default_model_id="deepseek-chat",
            supported_model_ids=["deepseek-chat"],
            runtime_capabilities=[
                {
                    "model_id": "deepseek-chat",
                    "context_window_tokens": 128000,
                    "max_output_tokens": 8192,
                    "supports_tool_calling": False,
                    "supports_structured_output": False,
                    "supports_native_reasoning": False,
                }
            ],
            created_at=NOW,
            updated_at=NOW,
        )
        delivery = DeliveryChannelModel(
            delivery_channel_id="delivery-default",
            project_id=project.project_id,
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
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([project, provider])
        session.flush()
        session.add(delivery)
        session.commit()

        saved_provider = session.get(ProviderModel, "provider-deepseek")
        saved_delivery = session.get(DeliveryChannelModel, "delivery-default")

    assert saved_provider is not None
    assert saved_provider.runtime_capabilities[0]["context_window_tokens"] == 128000
    assert saved_provider.runtime_capabilities[0]["supports_native_reasoning"] is False
    assert saved_delivery is not None
    assert saved_delivery.project_id == "project-default"

    provider_columns = set(ProviderModel.__table__.columns.keys())
    delivery_columns = set(DeliveryChannelModel.__table__.columns.keys())
    assert {"api_key_ref", "runtime_capabilities", "supported_model_ids"}.issubset(
        provider_columns
    )
    assert {"api_key", "secret", "credential_value"}.isdisjoint(provider_columns)
    assert {"project_id", "delivery_mode", "credential_ref", "readiness_status"}.issubset(
        delivery_columns
    )
    assert {"session_id", "template_id", "delivery_channel_snapshot_ref"}.isdisjoint(
        delivery_columns
    )


def test_platform_runtime_settings_model_stores_groups_versions_and_audit_refs_only() -> None:
    from backend.app.db.models.control import PlatformRuntimeSettingsModel

    settings = PlatformRuntimeSettingsModel(
        settings_id="platform-runtime-settings",
        config_version="runtime-settings-v1",
        schema_version="runtime-settings-schema-v1",
        hard_limits_version="platform-hard-limits-v1",
        agent_limits={"max_react_iterations_per_stage": 30},
        provider_call_policy={"request_timeout_seconds": 60},
        internal_model_bindings={
            "context_compression": {
                "provider_id": "provider-deepseek",
                "model_id": "deepseek-chat",
                "model_parameters": {"temperature": 0},
                "source_config_version": "runtime-settings-v1",
            },
            "structured_output_repair": {
                "provider_id": "provider-deepseek",
                "model_id": "deepseek-chat",
                "model_parameters": {"temperature": 0},
                "source_config_version": "runtime-settings-v1",
            },
            "validation_pass": {
                "provider_id": "provider-deepseek",
                "model_id": "deepseek-reasoner",
                "model_parameters": {"temperature": 0},
                "source_config_version": "runtime-settings-v1",
            },
        },
        context_limits={"compression_threshold_ratio": 0.8},
        log_policy={"log_query_default_limit": 100, "log_query_max_limit": 500},
        created_by_actor_id="system",
        updated_by_actor_id="system",
        last_audit_log_id="audit-1",
        last_trace_id="trace-1",
        created_at=NOW,
        updated_at=NOW,
    )

    columns = set(PlatformRuntimeSettingsModel.__table__.columns.keys())
    assert settings.internal_model_bindings["context_compression"]["model_id"] == (
        "deepseek-chat"
    )
    assert settings.context_limits["compression_threshold_ratio"] == 0.8
    assert {
        "settings_id",
        "config_version",
        "schema_version",
        "hard_limits_version",
        "agent_limits",
        "provider_call_policy",
        "internal_model_bindings",
        "context_limits",
        "log_policy",
        "created_by_actor_id",
        "updated_by_actor_id",
        "last_audit_log_id",
        "last_trace_id",
        "created_at",
        "updated_at",
    }.issubset(columns)
    assert {
        "compression_prompt",
        "control_database_url",
        "runtime_database_url",
        "graph_database_url",
        "event_database_url",
        "log_database_url",
        "database_paths",
        "api_key",
        "credential_value",
    }.isdisjoint(columns)
