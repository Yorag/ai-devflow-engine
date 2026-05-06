from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    PipelineTemplateModel,
    ProjectModel,
    ProviderModel,
    SessionModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    ProviderProtocolType,
    ProviderSource,
    SessionStatus,
    TemplateSource,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.template import (
    FIXED_APPROVAL_CHECKPOINTS,
    FIXED_STAGE_SEQUENCE,
    PipelineTemplateWriteRequest,
)


NOW = datetime(2026, 5, 2, 13, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 2, 13, 5, 0, tzinfo=UTC)
LATEST = datetime(2026, 5, 2, 13, 10, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append(
            {
                "method": "record_rejected_command",
                "result": AuditResult.REJECTED,
                **kwargs,
            }
        )
        return object()


class FailingAuditService:
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")

    def record_rejected_command(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-template-crud",
        trace_id="trace-template-crud",
        correlation_id="correlation-template-crud",
        span_id="span-template-crud",
        parent_span_id=None,
        created_at=NOW,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    return manager


def seed_templates_and_custom_provider(
    session,  # noqa: ANN001
    audit: RecordingAuditService,
) -> None:
    from backend.app.services.providers import ProviderService
    from backend.app.services.templates import TemplateService

    ProviderService(session, audit_service=audit, now=lambda: NOW).seed_builtin_providers(
        trace_context=build_trace()
    )
    deepseek = session.get(ProviderModel, "provider-deepseek")
    assert deepseek is not None
    deepseek.is_configured = True
    deepseek.is_enabled = True
    session.add(deepseek)
    session.add(
        ProviderModel(
            provider_id="provider-custom",
            display_name="Custom Provider",
            provider_source=ProviderSource.CUSTOM,
            protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
            base_url="https://example.test",
            api_key_ref="env:CUSTOM_PROVIDER_API_KEY",
            default_model_id="custom-chat",
            supported_model_ids=["custom-chat"],
            is_configured=True,
            is_enabled=True,
            runtime_capabilities=[
                {
                    "model_id": "custom-chat",
                    "context_window_tokens": 128000,
                    "max_output_tokens": 4096,
                    "supports_tool_calling": False,
                    "supports_structured_output": False,
                    "supports_native_reasoning": False,
                }
            ],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()
    TemplateService(session, audit_service=audit, now=lambda: NOW).seed_system_templates(
        trace_context=build_trace()
    )


def seed_project(session) -> None:  # noqa: ANN001
    session.add(
        ProjectModel(
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
    )
    session.commit()


def write_request(
    *,
    name: str = "Custom feature flow",
    provider_id: str = "provider-custom",
    auxiliary_provider_id: str = "provider-custom",
    auxiliary_model_id: str = "custom-chat",
    max_react_iterations_per_stage: int = 25,
    max_tool_calls_per_stage: int = 55,
    skip_high_risk_tool_confirmations: bool = True,
) -> PipelineTemplateWriteRequest:
    return PipelineTemplateWriteRequest(
        name=name,
        description="Team-owned feature template",
        fixed_stage_sequence=list(FIXED_STAGE_SEQUENCE),
        stage_role_bindings=[
            {
                "stage_type": stage_type.value,
                "role_id": role_id,
                "system_prompt": f"  # Prompt for {stage_type.value}  ",
                "provider_id": provider_id,
            }
            for stage_type, role_id in [
                (FIXED_STAGE_SEQUENCE[0], "role-requirement-analyst"),
                (FIXED_STAGE_SEQUENCE[1], "role-solution-designer"),
                (FIXED_STAGE_SEQUENCE[2], "role-code-generator"),
                (FIXED_STAGE_SEQUENCE[3], "role-test-runner"),
                (FIXED_STAGE_SEQUENCE[4], "role-code-reviewer"),
                (FIXED_STAGE_SEQUENCE[5], "role-code-reviewer"),
            ]
        ],
        run_auxiliary_model_binding={
            "provider_id": auxiliary_provider_id,
            "model_id": auxiliary_model_id,
            "model_parameters": {"temperature": 0},
        },
        approval_checkpoints=list(FIXED_APPROVAL_CHECKPOINTS),
        auto_regression_enabled=False,
        max_auto_regression_retries=3,
        max_react_iterations_per_stage=max_react_iterations_per_stage,
        max_tool_calls_per_stage=max_tool_calls_per_stage,
        skip_high_risk_tool_confirmations=skip_high_risk_tool_confirmations,
    )


def _action_records(
    audit: RecordingAuditService,
    action: str,
) -> list[dict[str, Any]]:
    return [record for record in audit.records if record["action"] == action]


def _metadata_text(record: dict[str, Any]) -> str:
    return str(record.get("metadata", ""))


def test_save_as_user_template_from_system_template_creates_user_template_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        service = TemplateService(session, audit_service=audit, now=lambda: LATER)
        created = service.save_as_user_template(
            source_template_id="template-feature",
            body=write_request(),
            trace_context=build_trace(),
        )
        saved = session.get(PipelineTemplateModel, created.template_id)

    assert saved is not None
    assert created.template_id.startswith("template-user-")
    assert saved.template_source is TemplateSource.USER_TEMPLATE
    assert saved.base_template_id == "template-feature"
    assert saved.name == "Custom feature flow"
    assert saved.description == "Team-owned feature template"
    assert saved.fixed_stage_sequence == [stage.value for stage in FIXED_STAGE_SEQUENCE]
    assert saved.run_auxiliary_model_binding == {
        "provider_id": "provider-custom",
        "model_id": "custom-chat",
        "model_parameters": {"temperature": 0},
    }
    assert saved.approval_checkpoints == [
        checkpoint.value for checkpoint in FIXED_APPROVAL_CHECKPOINTS
    ]
    assert saved.auto_regression_enabled is False
    assert saved.max_auto_regression_retries == 3
    assert saved.max_react_iterations_per_stage == 25
    assert saved.max_tool_calls_per_stage == 55
    assert saved.skip_high_risk_tool_confirmations is True
    assert saved.created_at == LATER
    assert saved.updated_at == LATER
    assert all(
        binding["system_prompt"] == binding["system_prompt"].strip()
        for binding in saved.stage_role_bindings
    )

    records = _action_records(audit, "template.save_as")
    assert len(records) == 1
    record = records[0]
    assert record["method"] == "record_command_result"
    assert record["actor_type"] is AuditActorType.USER
    assert record["actor_id"] == "api-user"
    assert record["target_type"] == "pipeline_template"
    assert record["target_id"] == created.template_id
    assert record["result"] is AuditResult.SUCCEEDED
    assert record["metadata"]["template_id"] == created.template_id
    assert record["metadata"]["source_template_id"] == "template-feature"
    assert record["metadata"]["base_template_id"] == "template-feature"
    assert record["metadata"]["template_source"] == "user_template"
    assert record["metadata"]["stage_types"] == [
        stage.value for stage in FIXED_STAGE_SEQUENCE
    ]
    assert record["metadata"]["role_ids"] == [
        "role-requirement-analyst",
        "role-solution-designer",
        "role-code-generator",
        "role-test-runner",
        "role-code-reviewer",
    ]
    assert record["metadata"]["provider_ids"] == ["provider-custom"]
    assert record["metadata"]["run_auxiliary_model_binding"] == {
        "provider_id": "provider-custom",
        "model_id": "custom-chat",
    }
    assert record["metadata"]["max_react_iterations_per_stage"] == 25
    assert record["metadata"]["max_tool_calls_per_stage"] == 55
    assert record["metadata"]["skip_high_risk_tool_confirmations"] is True
    assert "Prompt for" not in _metadata_text(record)
    assert "system_prompt" not in _metadata_text(record)


def test_create_user_template_without_source_and_list_orders_system_then_users(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        first = TemplateService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).save_as_user_template(
            source_template_id=None,
            body=write_request(name="Standalone one"),
            trace_context=build_trace(),
        )
        second = TemplateService(
            session,
            audit_service=audit,
            now=lambda: LATEST,
        ).save_as_user_template(
            source_template_id=None,
            body=write_request(name="Standalone two"),
            trace_context=build_trace(),
        )
        listed = TemplateService(
            session,
            audit_service=audit,
            now=lambda: LATEST,
        ).list_templates(trace_context=build_trace())

    assert first.base_template_id is None
    assert second.base_template_id is None
    assert [template.template_id for template in listed] == [
        "template-bugfix",
        "template-feature",
        "template-refactor",
        first.template_id,
        second.template_id,
    ]


def test_patch_user_template_updates_allowed_fields_keeps_identity_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        created = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).save_as_user_template(
            source_template_id="template-feature",
            body=write_request(),
            trace_context=build_trace(),
        )

        updated = TemplateService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).patch_user_template(
            template_id=created.template_id,
            body=write_request(
                name="Updated flow",
                provider_id="provider-deepseek",
                auxiliary_provider_id="provider-deepseek",
                auxiliary_model_id="deepseek-chat",
                max_react_iterations_per_stage=20,
                max_tool_calls_per_stage=40,
                skip_high_risk_tool_confirmations=False,
            ),
            trace_context=build_trace(),
        )

    assert updated.template_id == created.template_id
    assert updated.template_source is TemplateSource.USER_TEMPLATE
    assert updated.base_template_id == "template-feature"
    assert updated.name == "Updated flow"
    assert updated.created_at == NOW
    assert updated.updated_at == LATER
    assert {binding["provider_id"] for binding in updated.stage_role_bindings} == {
        "provider-deepseek"
    }
    assert updated.run_auxiliary_model_binding == {
        "provider_id": "provider-deepseek",
        "model_id": "deepseek-chat",
        "model_parameters": {"temperature": 0},
    }
    assert updated.max_react_iterations_per_stage == 20
    assert updated.max_tool_calls_per_stage == 40
    assert updated.skip_high_risk_tool_confirmations is False

    records = _action_records(audit, "template.patch")
    assert len(records) == 1
    assert records[0]["target_id"] == created.template_id
    assert records[0]["metadata"]["template_id"] == created.template_id
    assert records[0]["metadata"]["base_template_id"] == "template-feature"
    assert records[0]["metadata"]["run_auxiliary_model_binding"] == {
        "provider_id": "provider-deepseek",
        "model_id": "deepseek-chat",
    }
    assert records[0]["metadata"]["max_react_iterations_per_stage"] == 20
    assert records[0]["metadata"]["max_tool_calls_per_stage"] == 40
    assert records[0]["metadata"]["skip_high_risk_tool_confirmations"] is False
    assert "Prompt for" not in _metadata_text(records[0])
    assert "system_prompt" not in _metadata_text(records[0])


def test_system_template_patch_and_delete_are_rejected_and_audited(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        service = TemplateService(session, audit_service=audit, now=lambda: LATER)

        with pytest.raises(TemplateServiceError) as patch_error:
            service.patch_user_template(
                template_id="template-feature",
                body=write_request(),
                trace_context=build_trace(),
            )
        with pytest.raises(TemplateServiceError) as delete_error:
            service.delete_user_template(
                template_id="template-feature",
                trace_context=build_trace(),
            )

    assert patch_error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert patch_error.value.status_code == 409
    assert patch_error.value.message == "System templates cannot be overwritten."
    assert delete_error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert delete_error.value.status_code == 409
    assert delete_error.value.message == "System templates cannot be deleted."
    assert _action_records(audit, "template.patch.rejected")
    assert _action_records(audit, "template.delete.rejected")


def test_missing_patch_and_delete_templates_are_not_found_and_audited(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        service = TemplateService(session, audit_service=audit, now=lambda: LATER)

        with pytest.raises(TemplateServiceError) as patch_error:
            service.patch_user_template(
                template_id="template-missing-patch",
                body=write_request(),
                trace_context=build_trace(),
            )
        with pytest.raises(TemplateServiceError) as delete_error:
            service.delete_user_template(
                template_id="template-missing-delete",
                trace_context=build_trace(),
            )

    assert patch_error.value.error_code is ErrorCode.NOT_FOUND
    assert patch_error.value.status_code == 404
    assert patch_error.value.message == "Pipeline template was not found."
    assert delete_error.value.error_code is ErrorCode.NOT_FOUND
    assert delete_error.value.status_code == 404
    assert delete_error.value.message == "Pipeline template was not found."
    assert _action_records(audit, "template.patch.rejected")[0]["target_id"] == (
        "template-missing-patch"
    )
    assert _action_records(audit, "template.delete.rejected")[0]["target_id"] == (
        "template-missing-delete"
    )


def test_missing_source_and_unknown_provider_are_rejected_and_audited(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        service = TemplateService(session, audit_service=audit, now=lambda: LATER)

        with pytest.raises(TemplateServiceError) as missing_source:
            service.save_as_user_template(
                source_template_id="template-missing",
                body=write_request(),
                trace_context=build_trace(),
            )
        with pytest.raises(TemplateServiceError) as missing_provider:
            service.save_as_user_template(
                source_template_id="template-feature",
                body=write_request(provider_id="provider-missing"),
                trace_context=build_trace(),
            )
        with pytest.raises(TemplateServiceError) as missing_auxiliary_provider:
            service.save_as_user_template(
                source_template_id="template-feature",
                body=write_request(auxiliary_provider_id="provider-missing"),
                trace_context=build_trace(),
            )
        with pytest.raises(TemplateServiceError) as unsupported_auxiliary_model:
            service.save_as_user_template(
                source_template_id="template-feature",
                body=write_request(auxiliary_model_id="custom-missing-model"),
                trace_context=build_trace(),
            )

        user_count = (
            session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_source == TemplateSource.USER_TEMPLATE)
            .count()
        )

    assert missing_source.value.error_code is ErrorCode.NOT_FOUND
    assert missing_source.value.status_code == 404
    assert missing_source.value.message == "Pipeline template was not found."
    assert missing_provider.value.error_code is ErrorCode.VALIDATION_ERROR
    assert missing_provider.value.status_code == 422
    assert missing_provider.value.message == (
        "Pipeline template references an unknown Provider."
    )
    assert missing_auxiliary_provider.value.error_code is ErrorCode.VALIDATION_ERROR
    assert missing_auxiliary_provider.value.status_code == 422
    assert missing_auxiliary_provider.value.message == (
        "Pipeline template references an unknown Provider."
    )
    assert unsupported_auxiliary_model.value.error_code is ErrorCode.VALIDATION_ERROR
    assert unsupported_auxiliary_model.value.status_code == 422
    assert unsupported_auxiliary_model.value.message == (
        "Pipeline template run auxiliary model is not supported by the selected Provider."
    )
    assert user_count == 0
    assert _action_records(audit, "template.save_as.rejected")


def test_editable_field_validation_rejects_role_order_and_blank_prompts(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        service = TemplateService(session, audit_service=audit, now=lambda: LATER)
        bad_role_bindings = deepcopy(write_request().stage_role_bindings)
        bad_role_bindings[0] = bad_role_bindings[0].model_copy(
            update={"role_id": "role-code-generator"}
        )
        blank_prompt_bindings = deepcopy(write_request().stage_role_bindings)
        blank_prompt_bindings[0] = blank_prompt_bindings[0].model_copy(
            update={"system_prompt": "   "}
        )

        for bindings in [bad_role_bindings, blank_prompt_bindings]:
            body = write_request().model_copy(update={"stage_role_bindings": bindings})
            with pytest.raises(TemplateServiceError) as error:
                service.save_as_user_template(
                    source_template_id="template-feature",
                    body=body,
                    trace_context=build_trace(),
                )
            assert error.value.error_code is ErrorCode.VALIDATION_ERROR
            assert error.value.status_code == 422
            assert error.value.message == (
                "Pipeline template contains invalid editable fields."
            )

    assert len(_action_records(audit, "template.save_as.rejected")) == 2


def test_blank_prompt_keeps_invalid_editable_fields_error_message(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        blank_prompt_bindings = deepcopy(write_request().stage_role_bindings)
        blank_prompt_bindings[0] = blank_prompt_bindings[0].model_copy(
            update={"system_prompt": "   "}
        )
        body = write_request().model_copy(update={"stage_role_bindings": blank_prompt_bindings})

        with pytest.raises(TemplateServiceError) as error:
            TemplateService(
                session,
                audit_service=audit,
                now=lambda: LATER,
            ).save_as_user_template(
                source_template_id="template-feature",
                body=body,
                trace_context=build_trace(),
            )

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert error.value.status_code == 422
    assert error.value.message == "Pipeline template contains invalid editable fields."


def test_editable_field_validation_accepts_role_applicable_to_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.services import templates as templates_module
    from backend.app.services.templates import TemplateService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        monkeypatch.setitem(
            templates_module.ROLE_STAGE_TYPES,
            "role-alt-requirement-analyst",
            [FIXED_STAGE_SEQUENCE[0]],
        )
        bindings = deepcopy(write_request().stage_role_bindings)
        bindings[0] = bindings[0].model_copy(
            update={"role_id": "role-alt-requirement-analyst"}
        )

        created = TemplateService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).save_as_user_template(
            source_template_id="template-feature",
            body=write_request().model_copy(update={"stage_role_bindings": bindings}),
            trace_context=build_trace(),
        )
        saved = session.get(PipelineTemplateModel, created.template_id)

    assert saved is not None
    assert saved.stage_role_bindings[0]["role_id"] == "role-alt-requirement-analyst"
    assert _action_records(audit, "template.save_as")[0]["metadata"]["role_ids"] == [
        "role-alt-requirement-analyst",
        "role-solution-designer",
        "role-code-generator",
        "role-test-runner",
        "role-code-reviewer",
    ]
    assert "Prompt for" not in _metadata_text(
        _action_records(audit, "template.save_as")[0]
    )
    assert "system_prompt" not in _metadata_text(
        _action_records(audit, "template.save_as")[0]
    )


def test_prompt_validation_hook_runs_once_before_save_rejections(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    class CountingTemplateService(TemplateService):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.prompt_validation_calls = 0

        def validate_template_prompts_before_save(
            self,
            bindings: list[dict[str, str]],
        ) -> list[dict[str, str]]:
            self.prompt_validation_calls += 1
            return super().validate_template_prompts_before_save(bindings)

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        blank_prompt_bindings = deepcopy(write_request().stage_role_bindings)
        blank_prompt_bindings[0] = blank_prompt_bindings[0].model_copy(
            update={"system_prompt": "   "}
        )
        blank_prompt_body = write_request().model_copy(
            update={"stage_role_bindings": blank_prompt_bindings}
        )
        blank_prompt_service = CountingTemplateService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        )

        with pytest.raises(TemplateServiceError):
            blank_prompt_service.save_as_user_template(
                source_template_id="template-feature",
                body=blank_prompt_body,
                trace_context=build_trace(),
            )

        unknown_provider_service = CountingTemplateService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        )
        with pytest.raises(TemplateServiceError):
            unknown_provider_service.save_as_user_template(
                source_template_id="template-feature",
                body=write_request(provider_id="provider-missing"),
                trace_context=build_trace(),
            )

    assert blank_prompt_service.prompt_validation_calls == 1
    assert unknown_provider_service.prompt_validation_calls == 1


def test_delete_user_template_falls_back_draft_sessions_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import DEFAULT_TEMPLATE_ID, TemplateService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project(session)
        seed_templates_and_custom_provider(session, audit)
        created = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).save_as_user_template(
            source_template_id="template-feature",
            body=write_request(),
            trace_context=build_trace(),
        )
        session.add_all(
            [
                SessionModel(
                    session_id="session-one",
                    project_id="project-default",
                    display_name="Draft one",
                    status=SessionStatus.DRAFT,
                    selected_template_id=created.template_id,
                    current_run_id=None,
                    latest_stage_type=None,
                    is_visible=True,
                    visibility_removed_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                SessionModel(
                    session_id="session-two",
                    project_id="project-default",
                    display_name="Draft two",
                    status=SessionStatus.DRAFT,
                    selected_template_id=created.template_id,
                    current_run_id=None,
                    latest_stage_type=None,
                    is_visible=True,
                    visibility_removed_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()

        TemplateService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).delete_user_template(
            template_id=created.template_id,
            trace_context=build_trace(),
        )
        saved_template = session.get(PipelineTemplateModel, created.template_id)
        saved_sessions = {
            model.session_id: model
            for model in session.query(SessionModel).order_by(SessionModel.session_id)
        }

    assert saved_template is None
    assert saved_sessions["session-one"].selected_template_id == DEFAULT_TEMPLATE_ID
    assert saved_sessions["session-two"].selected_template_id == DEFAULT_TEMPLATE_ID
    assert saved_sessions["session-one"].updated_at.replace(tzinfo=UTC) == LATER
    record = _action_records(audit, "template.delete")[0]
    assert record["target_id"] == created.template_id
    assert record["metadata"]["fallback_template_id"] == DEFAULT_TEMPLATE_ID
    assert record["metadata"]["fallback_session_ids"] == ["session-one", "session-two"]
    assert "Prompt for" not in _metadata_text(record)
    assert "system_prompt" not in _metadata_text(record)


def test_delete_user_template_rejects_started_session_reference_without_changes(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project(session)
        seed_templates_and_custom_provider(session, audit)
        created = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).save_as_user_template(
            source_template_id=None,
            body=write_request(),
            trace_context=build_trace(),
        )
        session.add(
            SessionModel(
                session_id="session-started",
                project_id="project-default",
                display_name="Started",
                status=SessionStatus.DRAFT,
                selected_template_id=created.template_id,
                current_run_id="run-started",
                latest_stage_type=None,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

        service = TemplateService(session, audit_service=audit, now=lambda: LATER)
        with pytest.raises(TemplateServiceError) as error:
            service.delete_user_template(
                template_id=created.template_id,
                trace_context=build_trace(),
            )
        saved_template = session.get(PipelineTemplateModel, created.template_id)
        saved_session = session.get(SessionModel, "session-started")

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert error.value.status_code == 409
    assert error.value.message == (
        "Pipeline template is selected by a Session that has already started."
    )
    assert saved_template is not None
    assert saved_session is not None
    assert saved_session.selected_template_id == created.template_id
    assert _action_records(audit, "template.delete.rejected")


def test_delete_user_template_falls_back_hidden_started_session(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import DEFAULT_TEMPLATE_ID, TemplateService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project(session)
        seed_templates_and_custom_provider(session, audit)
        created = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).save_as_user_template(
            source_template_id=None,
            body=write_request(),
            trace_context=build_trace(),
        )
        session.add(
            SessionModel(
                session_id="session-hidden-started",
                project_id="project-default",
                display_name="Hidden started",
                status=SessionStatus.FAILED,
                selected_template_id=created.template_id,
                current_run_id="run-failed",
                latest_stage_type=None,
                is_visible=False,
                visibility_removed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

        TemplateService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).delete_user_template(
            template_id=created.template_id,
            trace_context=build_trace(),
        )
        saved_template = session.get(PipelineTemplateModel, created.template_id)
        saved_session = session.get(SessionModel, "session-hidden-started")

    assert saved_template is None
    assert saved_session is not None
    assert saved_session.selected_template_id == DEFAULT_TEMPLATE_ID
    assert saved_session.is_visible is False
    assert saved_session.visibility_removed_at is not None
    assert saved_session.updated_at.replace(tzinfo=UTC) == LATER
    record = _action_records(audit, "template.delete")[0]
    assert record["metadata"]["fallback_session_ids"] == ["session-hidden-started"]


def test_delete_user_template_rejects_non_draft_session_without_current_run(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project(session)
        seed_templates_and_custom_provider(session, audit)
        created = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).save_as_user_template(
            source_template_id=None,
            body=write_request(),
            trace_context=build_trace(),
        )
        session.add(
            SessionModel(
                session_id="session-running-no-run",
                project_id="project-default",
                display_name="Running without current run",
                status=SessionStatus.RUNNING,
                selected_template_id=created.template_id,
                current_run_id=None,
                latest_stage_type=None,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

        service = TemplateService(session, audit_service=audit, now=lambda: LATER)
        with pytest.raises(TemplateServiceError) as error:
            service.delete_user_template(
                template_id=created.template_id,
                trace_context=build_trace(),
            )
        saved_template = session.get(PipelineTemplateModel, created.template_id)
        saved_session = session.get(SessionModel, "session-running-no-run")

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert error.value.status_code == 409
    assert error.value.message == (
        "Pipeline template is selected by a Session that has already started."
    )
    assert saved_template is not None
    assert saved_session is not None
    assert saved_session.selected_template_id == created.template_id
    rejected = _action_records(audit, "template.delete.rejected")[0]
    assert rejected["metadata"]["blocked_session_ids"] == ["session-running-no-run"]


def test_delete_user_template_rejects_template_used_as_save_as_source(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService, TemplateServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_templates_and_custom_provider(session, audit)
        service = TemplateService(session, audit_service=audit, now=lambda: NOW)
        parent = service.save_as_user_template(
            source_template_id=None,
            body=write_request(name="Parent flow"),
            trace_context=build_trace(),
        )
        child = service.save_as_user_template(
            source_template_id=parent.template_id,
            body=write_request(name="Child flow"),
            trace_context=build_trace(),
        )

        with pytest.raises(TemplateServiceError) as error:
            TemplateService(
                session,
                audit_service=audit,
                now=lambda: LATER,
            ).delete_user_template(
                template_id=parent.template_id,
                trace_context=build_trace(),
            )
        saved_parent = session.get(PipelineTemplateModel, parent.template_id)
        saved_child = session.get(PipelineTemplateModel, child.template_id)

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert error.value.status_code == 409
    assert error.value.message == (
        "Pipeline template is used as a base template by another template."
    )
    assert saved_parent is not None
    assert saved_child is not None
    assert saved_child.base_template_id == parent.template_id
    rejected = _action_records(audit, "template.delete.rejected")[0]
    assert rejected["target_id"] == parent.template_id
    assert rejected["metadata"]["child_template_ids"] == [child.template_id]


def test_user_template_writes_roll_back_when_success_audit_fails(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project(session)
        seed_templates_and_custom_provider(session, RecordingAuditService())
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            TemplateService(
                session,
                audit_service=FailingAuditService(),
                now=lambda: NOW,
            ).save_as_user_template(
                source_template_id="template-feature",
                body=write_request(),
                trace_context=build_trace(),
            )
        assert (
            session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_source == TemplateSource.USER_TEMPLATE)
            .count()
            == 0
        )

        audit = RecordingAuditService()
        created = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).save_as_user_template(
            source_template_id=None,
            body=write_request(name="Rollback candidate"),
            trace_context=build_trace(),
        )
        session.add(
            SessionModel(
                session_id="session-draft",
                project_id="project-default",
                display_name="Draft",
                status=SessionStatus.DRAFT,
                selected_template_id=created.template_id,
                current_run_id=None,
                latest_stage_type=None,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

        failing_service = TemplateService(
            session,
            audit_service=FailingAuditService(),
            now=lambda: LATER,
        )
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            failing_service.patch_user_template(
                template_id=created.template_id,
                body=write_request(name="Should roll back"),
                trace_context=build_trace(),
            )
        saved_after_patch = session.get(PipelineTemplateModel, created.template_id)
        assert saved_after_patch is not None
        assert saved_after_patch.name == "Rollback candidate"

        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            failing_service.delete_user_template(
                template_id=created.template_id,
                trace_context=build_trace(),
            )
        saved_after_delete = session.get(PipelineTemplateModel, created.template_id)
        draft_session = session.get(SessionModel, "session-draft")

    assert saved_after_delete is not None
    assert draft_session is not None
    assert draft_session.selected_template_id == created.template_id
