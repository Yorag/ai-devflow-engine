from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas import common


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
FIXED_STAGE_SEQUENCE = [
    common.StageType.REQUIREMENT_ANALYSIS,
    common.StageType.SOLUTION_DESIGN,
    common.StageType.CODE_GENERATION,
    common.StageType.TEST_GENERATION_EXECUTION,
    common.StageType.CODE_REVIEW,
    common.StageType.DELIVERY_INTEGRATION,
]


def test_project_and_session_history_schemas_lock_control_plane_boundary() -> None:
    from backend.app.schemas.project import ProjectRead, ProjectRemoveResult
    from backend.app.schemas.session import (
        SessionDeleteResult,
        SessionRead,
        SessionRenameRequest,
    )

    project = ProjectRead(
        project_id="project-default",
        name="AI Devflow Engine",
        root_path="C:/repo/ai-devflow-engine",
        default_delivery_channel_id="delivery-default",
        is_default=True,
        created_at=NOW,
        updated_at=NOW,
    )

    assert project.model_dump(mode="json") == {
        "project_id": "project-default",
        "name": "AI Devflow Engine",
        "root_path": "C:/repo/ai-devflow-engine",
        "default_delivery_channel_id": "delivery-default",
        "is_default": True,
        "created_at": "2026-01-02T03:04:05Z",
        "updated_at": "2026-01-02T03:04:05Z",
    }
    assert "display_name" not in ProjectRead.model_fields
    assert "is_removed" not in ProjectRead.model_fields
    assert "removed_at" not in ProjectRead.model_fields

    session = SessionRead(
        session_id="session-1",
        project_id="project-default",
        display_name="Add schema contracts",
        status=common.SessionStatus.DRAFT,
        selected_template_id="template-feature",
        current_run_id=None,
        latest_stage_type=None,
        created_at=NOW,
        updated_at=NOW,
    )

    assert session.status is common.SessionStatus.DRAFT
    assert session.current_run_id is None
    assert session.latest_stage_type is None
    assert set(SessionRenameRequest.model_fields) == {"display_name"}
    assert SessionRenameRequest(display_name="Renamed").display_name == "Renamed"

    with pytest.raises(ValidationError):
        SessionRenameRequest(display_name="Renamed", current_run_id="run-1")

    deleted = SessionDeleteResult(
        session_id="session-1",
        project_id="project-default",
        visibility_removed=True,
        blocked_by_active_run=False,
        blocking_run_id=None,
        error_code=None,
        message="Session removed from regular product history.",
    )

    assert deleted.deletes_local_project_folder is False
    assert deleted.deletes_target_repository is False
    assert deleted.deletes_remote_repository is False
    assert deleted.deletes_remote_branch is False
    assert deleted.deletes_commits is False
    assert deleted.deletes_code_review_requests is False

    with pytest.raises(ValidationError):
        SessionDeleteResult(
            session_id="session-1",
            project_id="project-default",
            visibility_removed=True,
            blocked_by_active_run=False,
            blocking_run_id=None,
            error_code=None,
            message="Invalid physical delete claim.",
            deletes_target_repository=True,
        )

    blocked = SessionDeleteResult(
        session_id="session-1",
        project_id="project-default",
        visibility_removed=False,
        blocked_by_active_run=True,
        blocking_run_id="run-active",
        error_code="session_active_run_blocks_delete",
        message="Session has an active run.",
    )

    assert blocked.blocked_by_active_run is True
    assert blocked.error_code == "session_active_run_blocks_delete"

    removed_project = ProjectRemoveResult(
        project_id="project-extra",
        visibility_removed=True,
        blocked_by_active_run=False,
        blocking_run_id=None,
        error_code=None,
        message="Project removed from regular product history.",
    )

    assert removed_project.deletes_local_project_folder is False
    assert removed_project.deletes_target_repository is False
    assert removed_project.deletes_remote_repository is False
    assert removed_project.deletes_remote_branch is False
    assert removed_project.deletes_commits is False
    assert removed_project.deletes_code_review_requests is False

    with pytest.raises(ValidationError):
        ProjectRemoveResult(
            project_id="project-extra",
            visibility_removed=True,
            blocked_by_active_run=False,
            blocking_run_id=None,
            error_code=None,
            message="Invalid physical delete claim.",
            deletes_local_project_folder=True,
        )


def test_pipeline_template_and_agent_role_schemas_keep_fixed_stage_contract() -> None:
    from backend.app.schemas.template import (
        AgentRoleConfig,
        PipelineTemplateRead,
        StageRoleBinding,
    )

    role = AgentRoleConfig(
        role_id="role-requirement-analyst",
        role_name="Requirement Analyst",
        system_prompt="Analyze the requirement and produce structured acceptance criteria.",
        provider_id="provider-deepseek",
    )

    assert role.model_dump(mode="json") == {
        "role_id": "role-requirement-analyst",
        "role_name": "Requirement Analyst",
        "system_prompt": "Analyze the requirement and produce structured acceptance criteria.",
        "provider_id": "provider-deepseek",
    }

    binding = StageRoleBinding(
        stage_type=common.StageType.REQUIREMENT_ANALYSIS,
        role_id=role.role_id,
        system_prompt=role.system_prompt,
        provider_id=role.provider_id,
    )

    template = PipelineTemplateRead(
        template_id="template-feature",
        name="New Feature Flow",
        description="Default flow for new feature delivery.",
        template_source=common.TemplateSource.SYSTEM_TEMPLATE,
        base_template_id=None,
        fixed_stage_sequence=FIXED_STAGE_SEQUENCE,
        stage_role_bindings=[binding],
        approval_checkpoints=[
            common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
            common.ApprovalType.CODE_REVIEW_APPROVAL,
        ],
        auto_regression_enabled=True,
        max_auto_regression_retries=2,
        max_react_iterations_per_stage=30,
        max_tool_calls_per_stage=80,
        skip_high_risk_tool_confirmations=False,
        created_at=NOW,
        updated_at=NOW,
    )

    dumped = template.model_dump(mode="json")
    assert dumped["fixed_stage_sequence"] == [
        "requirement_analysis",
        "solution_design",
        "code_generation",
        "test_generation_execution",
        "code_review",
        "delivery_integration",
    ]
    assert dumped["stage_role_bindings"][0] == {
        "stage_type": "requirement_analysis",
        "role_id": "role-requirement-analyst",
        "stage_work_instruction": "Analyze the requirement and produce structured acceptance criteria.",
        "system_prompt": "Analyze the requirement and produce structured acceptance criteria.",
        "provider_id": "provider-deepseek",
    }
    assert dumped["approval_checkpoints"] == [
        "solution_design_approval",
        "code_review_approval",
    ]

    with pytest.raises(ValidationError):
        PipelineTemplateRead(
            template_id="template-invalid",
            name="Invalid Flow",
            description=None,
            template_source=common.TemplateSource.USER_TEMPLATE,
            base_template_id="template-feature",
            fixed_stage_sequence=[common.StageType.CODE_REVIEW],
            stage_role_bindings=[binding],
            approval_checkpoints=[
                common.ApprovalType.SOLUTION_DESIGN_APPROVAL,
                common.ApprovalType.CODE_REVIEW_APPROVAL,
            ],
            auto_regression_enabled=False,
            max_auto_regression_retries=0,
            max_react_iterations_per_stage=30,
            max_tool_calls_per_stage=80,
            skip_high_risk_tool_confirmations=False,
            created_at=NOW,
            updated_at=NOW,
        )

    with pytest.raises(ValidationError):
        PipelineTemplateRead(
            template_id="template-invalid",
            name="Invalid Flow",
            description=None,
            template_source=common.TemplateSource.USER_TEMPLATE,
            base_template_id="template-feature",
            fixed_stage_sequence=FIXED_STAGE_SEQUENCE,
            stage_role_bindings=[binding],
            approval_checkpoints=[common.ApprovalType.SOLUTION_DESIGN_APPROVAL],
            auto_regression_enabled=False,
            max_auto_regression_retries=0,
            max_react_iterations_per_stage=30,
            max_tool_calls_per_stage=80,
            skip_high_risk_tool_confirmations=False,
            created_at=NOW,
            updated_at=NOW,
        )


def test_provider_and_delivery_channel_schemas_expose_refs_without_secret_values() -> None:
    from backend.app.schemas.delivery_channel import (
        ProjectDeliveryChannelDetailProjection,
    )
    from backend.app.schemas.provider import ModelRuntimeCapabilities, ProviderRead

    default_capabilities = ModelRuntimeCapabilities(
        model_id="deepseek-chat",
        max_output_tokens=8192,
    )

    assert default_capabilities.context_window_tokens == 128000
    assert default_capabilities.supports_tool_calling is False
    assert default_capabilities.supports_structured_output is False
    assert default_capabilities.supports_native_reasoning is False

    with pytest.raises(ValidationError):
        ModelRuntimeCapabilities(
            model_id="bad-model",
            context_window_tokens=0,
            max_output_tokens=1,
        )

    with pytest.raises(ValidationError):
        ModelRuntimeCapabilities(
            model_id="bad-model",
            context_window_tokens=128000,
            max_output_tokens=0,
        )

    provider = ProviderRead(
        provider_id="provider-deepseek",
        display_name="DeepSeek",
        provider_source=common.ProviderSource.BUILTIN,
        protocol_type=common.ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url="https://api.deepseek.com",
        api_key_ref="env:DEEPSEEK_API_KEY",
        default_model_id="deepseek-chat",
        supported_model_ids=["deepseek-chat", "deepseek-reasoner"],
        runtime_capabilities=[
            default_capabilities,
            ModelRuntimeCapabilities(
                model_id="deepseek-reasoner",
                max_output_tokens=8192,
                supports_native_reasoning=True,
            ),
        ],
        created_at=NOW,
        updated_at=NOW,
    )

    provider_dump = provider.model_dump(mode="json")
    assert provider_dump["api_key_ref"] == "env:DEEPSEEK_API_KEY"
    assert "api_key" not in provider_dump
    assert "secret" not in provider_dump

    with pytest.raises(ValidationError):
        ProviderRead(
            provider_id="provider-custom",
            display_name="Custom",
            provider_source=common.ProviderSource.CUSTOM,
            protocol_type=common.ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
            base_url="https://models.example.test",
            api_key_ref="env:CUSTOM_API_KEY",
            api_key="plain-secret",
            default_model_id="custom-model",
            supported_model_ids=["custom-model"],
            runtime_capabilities=[
                ModelRuntimeCapabilities(
                    model_id="custom-model",
                    max_output_tokens=4096,
                )
            ],
            created_at=NOW,
            updated_at=NOW,
        )

    for invalid_provider_fields in (
        {
            "supported_model_ids": ["custom-model", ""],
            "runtime_capabilities": [
                ModelRuntimeCapabilities(
                    model_id="custom-model",
                    max_output_tokens=4096,
                )
            ],
        },
        {
            "default_model_id": "custom-reasoner",
            "supported_model_ids": ["custom-model"],
            "runtime_capabilities": [
                ModelRuntimeCapabilities(
                    model_id="custom-model",
                    max_output_tokens=4096,
                ),
                ModelRuntimeCapabilities(
                    model_id="custom-reasoner",
                    max_output_tokens=4096,
                ),
            ],
        },
        {
            "supported_model_ids": ["custom-model", "custom-reasoner"],
            "runtime_capabilities": [
                ModelRuntimeCapabilities(
                    model_id="custom-model",
                    max_output_tokens=4096,
                )
            ],
        },
    ):
        with pytest.raises(ValidationError):
            ProviderRead(
                **{
                    "provider_id": "provider-custom",
                    "display_name": "Custom",
                    "provider_source": common.ProviderSource.CUSTOM,
                    "protocol_type": common.ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
                    "base_url": "https://models.example.test",
                    "api_key_ref": "env:CUSTOM_API_KEY",
                    "default_model_id": "custom-model",
                    "created_at": NOW,
                    "updated_at": NOW,
                    **invalid_provider_fields,
                }
            )

    delivery = ProjectDeliveryChannelDetailProjection(
        project_id="project-default",
        delivery_channel_id="delivery-default",
        delivery_mode=common.DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=common.ScmProviderType.GITHUB,
        repository_identifier="owner/repo",
        default_branch="main",
        code_review_request_type=common.CodeReviewRequestType.PULL_REQUEST,
        credential_ref="env:GITHUB_TOKEN",
        credential_status=common.CredentialStatus.READY,
        readiness_status=common.DeliveryReadinessStatus.READY,
        readiness_message="Ready for git_auto_delivery.",
        last_validated_at=NOW,
        updated_at=NOW,
    )

    delivery_dump = delivery.model_dump(mode="json")
    assert delivery_dump["credential_ref"] == "env:GITHUB_TOKEN"
    assert delivery_dump["readiness_status"] == "ready"
    assert "credential_value" not in delivery_dump

    with pytest.raises(ValidationError):
        ProjectDeliveryChannelDetailProjection(
            project_id="project-default",
            delivery_channel_id="delivery-invalid",
            delivery_mode=common.DeliveryMode.GIT_AUTO_DELIVERY,
            scm_provider_type=None,
            repository_identifier=None,
            default_branch=None,
            code_review_request_type=None,
            credential_ref=None,
            credential_status=common.CredentialStatus.UNBOUND,
            readiness_status=common.DeliveryReadinessStatus.READY,
            readiness_message="Invalid ready git_auto_delivery config.",
            last_validated_at=NOW,
            updated_at=NOW,
        )

    with pytest.raises(ValidationError):
        ProjectDeliveryChannelDetailProjection(
            **{
                **delivery.model_dump(mode="python"),
                "credential_status": common.CredentialStatus.INVALID,
            }
        )


def test_configuration_package_schemas_allow_user_visible_config_only() -> None:
    from backend.app.schemas.configuration_package import (
        ConfigurationPackageExport,
        ConfigurationPackageImportRequest,
        ConfigurationPackageRead,
    )

    package_payload = {
        "package_schema_version": "function-one-v1",
        "scope": {
            "scope_type": "project",
            "project_id": "project-default",
        },
        "providers": [
            {
                "provider_id": "provider-deepseek",
                "display_name": "DeepSeek",
                "provider_source": "builtin",
                "protocol_type": "openai_completions_compatible",
                "base_url": "https://api.deepseek.com",
                "api_key_ref": "env:DEEPSEEK_API_KEY",
                "default_model_id": "deepseek-chat",
                "supported_model_ids": ["deepseek-chat"],
                "runtime_capabilities": [
                    {
                        "model_id": "deepseek-chat",
                        "context_window_tokens": 128000,
                        "max_output_tokens": 8192,
                        "supports_tool_calling": False,
                        "supports_structured_output": False,
                        "supports_native_reasoning": False,
                    }
                ],
            }
        ],
        "delivery_channels": [
            {
                "delivery_mode": "demo_delivery",
                "scm_provider_type": None,
                "repository_identifier": None,
                "default_branch": None,
                "code_review_request_type": None,
                "credential_ref": None,
            }
        ],
        "pipeline_templates": [
            {
                "template_id": "template-feature",
                "name": "New Feature Flow",
                "template_source": "system_template",
                "stage_role_bindings": [
                    {
                        "stage_type": "requirement_analysis",
                        "role_id": "role-requirement-analyst",
                        "stage_work_instruction": "Analyze requirements.",
                        "system_prompt": "Analyze requirements.",
                        "provider_id": "provider-deepseek",
                    }
                ],
                "auto_regression_enabled": True,
                "max_auto_regression_retries": 2,
                "max_react_iterations_per_stage": 30,
                "max_tool_calls_per_stage": 80,
                "skip_high_risk_tool_confirmations": False,
            }
        ],
    }

    package_read = ConfigurationPackageRead(
        package_id="package-1",
        exported_at=NOW,
        **package_payload,
    )
    import_request = ConfigurationPackageImportRequest(**package_payload)
    package_export = ConfigurationPackageExport(
        export_id="export-1",
        exported_at=NOW,
        **package_payload,
    )

    assert package_read.scope.scope_type == "project"
    assert import_request.providers[0].api_key_ref == "env:DEEPSEEK_API_KEY"
    assert package_export.pipeline_templates[0].stage_role_bindings[0].role_id == (
        "role-requirement-analyst"
    )
    assert (
        package_export.pipeline_templates[0]
        .stage_role_bindings[0]
        .stage_work_instruction
        == "Analyze requirements."
    )
    assert package_export.pipeline_templates[0].max_react_iterations_per_stage == 30
    assert package_export.pipeline_templates[0].max_tool_calls_per_stage == 80
    assert (
        package_export.pipeline_templates[0].skip_high_risk_tool_confirmations
        is False
    )

    package_with_defaulted_capabilities = deepcopy(package_payload)
    package_with_defaulted_capabilities["providers"][0]["runtime_capabilities"] = [
        {
            "model_id": "deepseek-chat",
        }
    ]
    defaulted_import = ConfigurationPackageImportRequest(
        **package_with_defaulted_capabilities
    )
    defaulted_capabilities = defaulted_import.providers[0].runtime_capabilities[0]
    assert defaulted_capabilities.context_window_tokens == 128000
    assert defaulted_capabilities.max_output_tokens is None
    assert defaulted_capabilities.supports_tool_calling is False
    assert defaulted_capabilities.supports_structured_output is False
    assert defaulted_capabilities.supports_native_reasoning is False

    package_with_invalid_capabilities = deepcopy(package_payload)
    package_with_invalid_capabilities["providers"][0]["runtime_capabilities"] = [
        {
            "model_id": "deepseek-chat",
            "max_output_tokens": 0,
        }
    ]
    with pytest.raises(ValidationError):
        ConfigurationPackageImportRequest(**package_with_invalid_capabilities)

    package_with_empty_supported_model = deepcopy(package_payload)
    package_with_empty_supported_model["providers"][0]["supported_model_ids"] = [
        "deepseek-chat",
        "",
    ]
    with pytest.raises(ValidationError):
        ConfigurationPackageImportRequest(**package_with_empty_supported_model)

    package_with_string_capability_bool = deepcopy(package_payload)
    package_with_string_capability_bool["providers"][0]["runtime_capabilities"][0][
        "supports_tool_calling"
    ] = "yes"
    with pytest.raises(ValidationError):
        ConfigurationPackageImportRequest(**package_with_string_capability_bool)

    package_with_default_model_outside_supported = deepcopy(package_payload)
    package_with_default_model_outside_supported["providers"][0][
        "default_model_id"
    ] = "deepseek-reasoner"
    package_with_default_model_outside_supported["providers"][0][
        "runtime_capabilities"
    ].append(
        {
            "model_id": "deepseek-reasoner",
            "context_window_tokens": 128000,
            "max_output_tokens": 8192,
            "supports_tool_calling": False,
            "supports_structured_output": False,
            "supports_native_reasoning": True,
        }
    )
    semantic_invalid_import = ConfigurationPackageImportRequest(
        **package_with_default_model_outside_supported
    )
    assert semantic_invalid_import.providers[0].default_model_id == (
        "deepseek-reasoner"
    )

    package_with_uncovered_supported_model = deepcopy(package_payload)
    package_with_uncovered_supported_model["providers"][0]["supported_model_ids"] = [
        "deepseek-chat",
        "deepseek-reasoner",
    ]
    semantic_incomplete_import = ConfigurationPackageImportRequest(
        **package_with_uncovered_supported_model
    )
    assert semantic_incomplete_import.providers[0].supported_model_ids == [
        "deepseek-chat",
        "deepseek-reasoner",
    ]

    package_with_invalid_git_delivery = deepcopy(package_payload)
    package_with_invalid_git_delivery["delivery_channels"] = [
        {
            "delivery_mode": "git_auto_delivery",
            "scm_provider_type": "github",
            "repository_identifier": "owner/repo",
            "default_branch": "main",
            "code_review_request_type": "pull_request",
            "credential_ref": None,
        }
    ]
    semantic_invalid_delivery_import = ConfigurationPackageImportRequest(
        **package_with_invalid_git_delivery
    )
    assert semantic_invalid_delivery_import.delivery_channels[0].credential_ref is None

    for schema_type in (
        ConfigurationPackageRead,
        ConfigurationPackageImportRequest,
        ConfigurationPackageExport,
    ):
        assert "platform_runtime_settings" not in schema_type.model_fields
        assert "compression_threshold_ratio" not in schema_type.model_fields
        assert "system_prompt_assets" not in schema_type.model_fields
        assert "runtime_snapshots" not in schema_type.model_fields
        assert "audit_logs" not in schema_type.model_fields
        assert "database_paths" not in schema_type.model_fields

    forbidden_top_level = deepcopy(package_payload)
    forbidden_top_level["platform_runtime_settings"] = {}
    with pytest.raises(ValidationError):
        ConfigurationPackageImportRequest(**forbidden_top_level)

    forbidden_role_name = deepcopy(package_payload)
    forbidden_role_name["pipeline_templates"][0]["stage_role_bindings"][0][
        "role_name"
    ] = "Renamed Role"
    with pytest.raises(ValidationError):
        ConfigurationPackageImportRequest(**forbidden_role_name)

    forbidden_stage_contract = deepcopy(package_payload)
    forbidden_stage_contract["pipeline_templates"][0]["stage_contracts"] = []
    with pytest.raises(ValidationError):
        ConfigurationPackageImportRequest(**forbidden_stage_contract)
