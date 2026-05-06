from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, PipelineTemplateModel, ProviderModel
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import ProviderProtocolType, ProviderSource, StageType, TemplateSource
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.template import FIXED_APPROVAL_CHECKPOINTS, FIXED_STAGE_SEQUENCE


NOW = datetime(2026, 5, 2, 10, 11, 12, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append(kwargs)
        return object()


class FailingAuditService:
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


class FailsOnSecondAuditService:
    def __init__(self) -> None:
        self.committed_records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        if self.committed_records:
            raise RuntimeError("audit ledger unavailable")
        self.committed_records.append(kwargs)
        return object()


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-template-seed",
        trace_id="trace-template-seed",
        correlation_id="correlation-template-seed",
        span_id="span-template-seed",
        parent_span_id=None,
        created_at=NOW,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={
            role: tmp_path / f"{role.value}.db"
            for role in DatabaseRole
        },
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    return manager


def build_provider(
    provider_id: str,
    *,
    configured: bool,
    enabled: bool = True,
    default_model_id: str | None = None,
) -> ProviderModel:
    model_id = default_model_id or f"{provider_id}-chat"
    return ProviderModel(
        provider_id=provider_id,
        display_name=provider_id,
        provider_source=ProviderSource.CUSTOM,
        protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url=f"https://{provider_id}.example.test/v1",
        api_key_ref=f"env:{provider_id.upper().replace('-', '_')}_API_KEY"
        if configured
        else None,
        default_model_id=model_id,
        supported_model_ids=[model_id],
        is_configured=configured,
        is_enabled=enabled,
        runtime_capabilities=[
            {
                "model_id": model_id,
                "context_window_tokens": 128000,
                "max_output_tokens": 8192,
                "supports_tool_calling": True,
                "supports_structured_output": True,
                "supports_native_reasoning": False,
            }
        ],
        created_at=NOW,
        updated_at=NOW,
    )


def test_seed_system_templates_creates_three_templates_from_role_assets(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import DEFAULT_TEMPLATE_ID, TemplateService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        templates = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).seed_system_templates(trace_context=build_trace())

    assert [template.template_id for template in templates] == [
        "template-bugfix",
        DEFAULT_TEMPLATE_ID,
        "template-refactor",
    ]
    assert [template.name for template in templates] == [
        "Bug 修复流程",
        "新功能开发流程",
        "重构流程",
    ]
    assert [template.description for template in templates] == [
        "Focused defect isolation with conservative tool use and regression depth.",
        "Balanced feature delivery with enough iteration and tool budget for new behavior.",
        "Behavior-preserving refactor flow with guarded execution and regression depth.",
    ]
    assert [
        template.max_react_iterations_per_stage
        for template in templates
    ] == [24, 30, 28]
    assert [template.max_tool_calls_per_stage for template in templates] == [
        48,
        80,
        60,
    ]
    assert [
        template.skip_high_risk_tool_confirmations
        for template in templates
    ] == [False, False, False]
    assert all(
        template.template_source is TemplateSource.SYSTEM_TEMPLATE
        for template in templates
    )
    assert all(
        template.fixed_stage_sequence == [stage.value for stage in FIXED_STAGE_SEQUENCE]
        for template in templates
    )
    assert all(
        template.approval_checkpoints
        == [checkpoint.value for checkpoint in FIXED_APPROVAL_CHECKPOINTS]
        for template in templates
    )
    assert all(template.created_at == NOW for template in templates)
    assert len(audit.records) == 1
    assert {record["action"] for record in audit.records} == {"template.seed_system"}
    assert {record["target_type"] for record in audit.records} == {"pipeline_template"}
    assert {record["target_id"] for record in audit.records} == {"system-template-seed"}
    assert {record["actor_type"] for record in audit.records} == {
        AuditActorType.SYSTEM
    }
    assert {record["actor_id"] for record in audit.records} == {"control-plane-seed"}
    assert {record["result"] for record in audit.records} == {AuditResult.SUCCEEDED}
    assert audit.records[0]["metadata"]["template_ids"] == [
        "template-bugfix",
        "template-feature",
        "template-refactor",
    ]
    assert all(
        "system_prompt" not in str(record["metadata"])
        for record in audit.records
    )


def test_template_bindings_use_stripped_prompt_bodies_and_fixed_stage_sequence(
    tmp_path: Path,
) -> None:
    from backend.app.services import templates as template_module
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        template = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())

    assert template.template_id == "template-feature"
    assert [binding["stage_type"] for binding in template.stage_role_bindings] == [
        stage.value for stage in FIXED_STAGE_SEQUENCE
    ]
    role_ids = [binding["role_id"] for binding in template.stage_role_bindings]
    assert role_ids == [
        "role-requirement-analyst",
        "role-solution-designer",
        "role-code-generator",
        "role-test-runner",
        "role-code-reviewer",
        "role-code-reviewer",
    ]
    assert all(binding["provider_id"] for binding in template.stage_role_bindings)
    _, requirement_stage_body = template_module.parse_front_matter(
        (
            template_module.ROLE_ASSET_DIR.parent
            / "stages"
            / "requirement_analysis.md"
        ).read_text(encoding="utf-8")
    )
    _, requirement_role_body = template_module.parse_front_matter(
        (
            template_module.ROLE_ASSET_DIR
            / "requirement_analyst.md"
        ).read_text(encoding="utf-8")
    )
    first_binding = template.stage_role_bindings[0]
    assert first_binding["stage_work_instruction"] == requirement_stage_body
    assert first_binding["system_prompt"] == requirement_role_body
    assert first_binding["stage_work_instruction"] != first_binding["system_prompt"]
    assert first_binding["stage_work_instruction"].startswith(
        "# Requirement Analysis Stage Prompt"
    )
    assert first_binding["system_prompt"].startswith("# Requirement Analyst")
    for binding in template.stage_role_bindings:
        assert binding["stage_work_instruction"].strip() == binding["stage_work_instruction"]
        assert binding["system_prompt"].strip() == binding["system_prompt"]
        assert binding["stage_work_instruction"].startswith("# ")
        assert binding["system_prompt"].startswith("# ")
        assert "prompt_id:" not in binding["stage_work_instruction"]
        assert "prompt_id:" not in binding["system_prompt"]
        assert "prompt_version:" not in binding["stage_work_instruction"]
        assert "prompt_version:" not in binding["system_prompt"]
        assert "---" not in binding["stage_work_instruction"]
        assert "---" not in binding["system_prompt"]


def test_seed_system_templates_uses_first_configured_provider_for_all_system_stages(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        session.add_all(
            [
                build_provider(
                    "provider-deepseek",
                    configured=False,
                    default_model_id="deepseek-chat",
                ),
                build_provider(
                    "provider-volcengine",
                    configured=True,
                    default_model_id="doubao-seed-1-6",
                ),
                build_provider(
                    "provider-mimo",
                    configured=True,
                    default_model_id="MiMo-V2.5",
                ),
            ]
        )
        session.commit()

        template = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())

    assert {
        binding["provider_id"] for binding in template.stage_role_bindings
    } == {"provider-mimo"}
    assert all(
        binding["provider_id"] != "provider-deepseek"
        for binding in template.stage_role_bindings
    )
    assert template.run_auxiliary_model_binding == {
        "provider_id": "provider-mimo",
        "model_id": "MiMo-V2.5",
        "model_parameters": {"temperature": 0},
    }


def test_seed_system_templates_refreshes_provider_bindings_when_provider_becomes_unavailable(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        deepseek = build_provider(
            "provider-deepseek",
            configured=True,
            default_model_id="deepseek-chat",
        )
        replacement = build_provider(
            "provider-mimo",
            configured=True,
            default_model_id="MiMo-V2.5",
        )
        session.add_all([deepseek, replacement])
        session.commit()

        service = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        )
        service.get_default_template(trace_context=build_trace())
        deepseek.is_configured = False
        deepseek.api_key_ref = None
        session.add(deepseek)
        session.commit()

        refreshed = service.get_default_template(trace_context=build_trace())

    assert {
        binding["provider_id"] for binding in refreshed.stage_role_bindings
    } == {"provider-mimo"}
    assert refreshed.run_auxiliary_model_binding == {
        "provider_id": "provider-mimo",
        "model_id": "MiMo-V2.5",
        "model_parameters": {"temperature": 0},
    }


def test_seed_system_templates_is_idempotent_and_returns_ordered_rows(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        )
        first = service.seed_system_templates(trace_context=build_trace())
        second = service.seed_system_templates(trace_context=build_trace())
        saved_count = session.query(PipelineTemplateModel).count()

    assert saved_count == 3
    assert [template.template_id for template in second] == [
        template.template_id for template in first
    ]
    assert len(audit.records) == 1


def test_seed_system_templates_refreshes_existing_system_template_defaults(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    with manager.session(DatabaseRole.CONTROL) as session:
        for template_id in (
            "template-bugfix",
            "template-feature",
            "template-refactor",
        ):
            session.add(
                PipelineTemplateModel(
                    template_id=template_id,
                    name=template_id,
                    description="Old indistinguishable template.",
                    template_source=TemplateSource.SYSTEM_TEMPLATE,
                    base_template_id=None,
                    fixed_stage_sequence=[stage.value for stage in FIXED_STAGE_SEQUENCE],
                    stage_role_bindings=[],
                    approval_checkpoints=[
                        checkpoint.value for checkpoint in FIXED_APPROVAL_CHECKPOINTS
                    ],
                    auto_regression_enabled=True,
                    max_auto_regression_retries=1,
                    max_react_iterations_per_stage=30,
                    max_tool_calls_per_stage=80,
                    skip_high_risk_tool_confirmations=True,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        session.commit()

        templates = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).seed_system_templates(trace_context=build_trace())

    assert [template.name for template in templates] == [
        "Bug 修复流程",
        "新功能开发流程",
        "重构流程",
    ]
    assert [template.description for template in templates] == [
        "Focused defect isolation with conservative tool use and regression depth.",
        "Balanced feature delivery with enough iteration and tool budget for new behavior.",
        "Behavior-preserving refactor flow with guarded execution and regression depth.",
    ]
    assert [template.max_auto_regression_retries for template in templates] == [
        2,
        1,
        2,
    ]
    assert [
        template.max_react_iterations_per_stage
        for template in templates
    ] == [24, 30, 28]
    assert [template.max_tool_calls_per_stage for template in templates] == [
        48,
        80,
        60,
    ]
    assert [
        template.skip_high_risk_tool_confirmations
        for template in templates
    ] == [False, False, False]
    assert all(template.stage_role_bindings for template in templates)
    assert all(
        binding["stage_work_instruction"] != binding["system_prompt"]
        for template in templates
        for binding in template.stage_role_bindings
    )
    assert [record["action"] for record in audit.records] == ["template.seed_system"]


def test_existing_templates_do_not_require_prompt_assets_for_read_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.services import templates as template_module
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        )
        service.seed_system_templates(trace_context=build_trace())

        def fail_asset_load() -> dict[str, object]:
            raise RuntimeError("prompt assets should not be loaded")

        monkeypatch.setattr(
            template_module,
            "load_default_agent_role_seed_assets",
            fail_asset_load,
        )

        listed = service.list_templates(trace_context=build_trace())
        detail = service.get_template("template-feature", trace_context=build_trace())

    assert [template.template_id for template in listed] == [
        "template-bugfix",
        "template-feature",
        "template-refactor",
    ]
    assert detail is not None
    assert detail.template_id == "template-feature"


def test_template_seed_uses_single_batch_audit_to_avoid_partial_success(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)
    audit = FailsOnSecondAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        )
        templates = service.seed_system_templates(trace_context=build_trace())

        saved_templates = session.query(PipelineTemplateModel).all()

    saved_ids = {template.template_id for template in saved_templates}
    assert saved_ids == {"template-bugfix", "template-feature", "template-refactor"}
    assert [template.template_id for template in templates] == [
        "template-bugfix",
        "template-feature",
        "template-refactor",
    ]
    assert len(audit.committed_records) == 1
    assert audit.committed_records[0]["target_id"] == "system-template-seed"


def test_template_seed_audit_failure_does_not_leave_partial_control_rows(
    tmp_path: Path,
) -> None:
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = TemplateService(
            session,
            audit_service=FailingAuditService(),
            now=lambda: NOW,
        )
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            service.seed_system_templates(trace_context=build_trace())

        saved_templates = session.query(PipelineTemplateModel).all()

    assert saved_templates == []


def test_get_template_returns_none_for_missing_template(tmp_path: Path) -> None:
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        )
        missing = service.get_template(
            "template-missing",
            trace_context=build_trace(),
        )

    assert missing is None
