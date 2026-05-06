from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, PipelineTemplateModel, ProviderModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.main import create_app
from backend.app.schemas.observability import AuditActorType, AuditResult


def build_seed_api_app(tmp_path: Path):
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    app = create_app(settings=settings)
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    return app


def test_startup_seeds_builtin_providers_and_system_templates_after_default_project(
    tmp_path: Path,
) -> None:
    app = build_seed_api_app(tmp_path)

    with TestClient(app):
        manager = app.state.database_manager
        with manager.session(DatabaseRole.CONTROL) as session:
            template_ids = [
                template.template_id
                for template in session.query(PipelineTemplateModel)
                .order_by(PipelineTemplateModel.template_id)
                .all()
            ]
            provider_ids = [
                provider.provider_id
                for provider in session.query(ProviderModel)
                .order_by(ProviderModel.provider_id)
                .all()
            ]
        with manager.session(DatabaseRole.LOG) as session:
            audit_actions = [
                audit.action
                for audit in session.query(AuditLogEntryModel)
                .order_by(AuditLogEntryModel.created_at)
                .all()
            ]

    assert template_ids == ["template-bugfix", "template-feature", "template-refactor"]
    assert provider_ids == ["provider-deepseek", "provider-volcengine"]
    assert audit_actions[0] == "project.ensure_default"
    assert audit_actions.count("provider.seed_builtin") == 1
    assert audit_actions.count("template.seed_system") == 1


def test_get_pipeline_templates_returns_seeded_templates_without_prompt_metadata(
    tmp_path: Path,
) -> None:
    app = build_seed_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/pipeline-templates")

    assert response.status_code == 200
    body = response.json()
    assert [template["template_id"] for template in body] == [
        "template-bugfix",
        "template-feature",
        "template-refactor",
    ]
    assert [template["name"] for template in body] == [
        "Bug 修复流程",
        "新功能开发流程",
        "重构流程",
    ]
    assert [template["description"] for template in body] == [
        "Focused defect isolation with conservative tool use and regression depth.",
        "Balanced feature delivery with enough iteration and tool budget for new behavior.",
        "Behavior-preserving refactor flow with guarded execution and regression depth.",
    ]
    assert [template["max_auto_regression_retries"] for template in body] == [
        2,
        1,
        2,
    ]
    assert [template["max_react_iterations_per_stage"] for template in body] == [
        24,
        30,
        28,
    ]
    assert [template["max_tool_calls_per_stage"] for template in body] == [
        48,
        80,
        60,
    ]
    assert [
        template["skip_high_risk_tool_confirmations"] for template in body
    ] == [False, False, False]
    for template in body:
        assert template["template_source"] == "system_template"
        assert template["fixed_stage_sequence"] == [
            "requirement_analysis",
            "solution_design",
            "code_generation",
            "test_generation_execution",
            "code_review",
            "delivery_integration",
        ]
        assert template["approval_checkpoints"] == [
            "solution_design_approval",
            "code_review_approval",
        ]
        assert len(template["stage_role_bindings"]) == 6
        for binding in template["stage_role_bindings"]:
            assert binding["system_prompt"]
            assert "prompt_id:" not in binding["system_prompt"]
            assert "prompt_version:" not in binding["system_prompt"]
            assert "---" not in binding["system_prompt"]
            assert "prompt_id" not in binding
            assert "prompt_version" not in binding


def test_get_pipeline_template_returns_one_template_and_audit_shape(
    tmp_path: Path,
) -> None:
    app = build_seed_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/pipeline-templates/template-feature",
            headers={
                "X-Request-ID": "req-template-detail",
                "X-Correlation-ID": "corr-template-detail",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-template-detail"
    body = response.json()
    assert body["template_id"] == "template-feature"
    assert body["name"] == "新功能开发流程"
    assert body["auto_regression_enabled"] is True
    assert body["max_auto_regression_retries"] == 1
    assert body["max_react_iterations_per_stage"] == 30
    assert body["max_tool_calls_per_stage"] == 80
    assert body["skip_high_risk_tool_confirmations"] is False

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        seed_audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "template.seed_system")
            .first()
        )

    assert seed_audit is not None
    assert seed_audit.actor_type is AuditActorType.SYSTEM
    assert seed_audit.actor_id == "control-plane-seed"
    assert seed_audit.result is AuditResult.SUCCEEDED
    assert "prompt_id" not in (seed_audit.metadata_excerpt or "")
    assert "prompt_version" not in (seed_audit.metadata_excerpt or "")


def test_get_pipeline_template_missing_returns_unified_not_found_error(
    tmp_path: Path,
) -> None:
    app = build_seed_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/pipeline-templates/template-missing",
            headers={
                "X-Request-ID": "req-template-missing",
                "X-Correlation-ID": "corr-template-missing",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Pipeline template was not found.",
        "request_id": "req-template-missing",
        "correlation_id": "corr-template-missing",
    }


def test_get_providers_starts_empty_until_user_adds_provider(
    tmp_path: Path,
) -> None:
    app = build_seed_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/providers")

    assert response.status_code == 200
    assert response.json() == []


def test_template_provider_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_seed_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    list_templates = paths["/api/pipeline-templates"]["get"]
    get_template = paths["/api/pipeline-templates/{templateId}"]["get"]
    list_providers = paths["/api/providers"]["get"]

    assert (
        list_templates["responses"]["200"]["content"]["application/json"]["schema"][
            "items"
        ]["$ref"]
        == "#/components/schemas/PipelineTemplateRead"
    )
    assert (
        list_templates["responses"]["500"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        get_template["parameters"][0]["name"]
        == "templateId"
    )
    assert (
        get_template["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PipelineTemplateRead"
    )
    assert (
        get_template["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        get_template["responses"]["500"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        list_providers["responses"]["200"]["content"]["application/json"]["schema"][
            "items"
        ]["$ref"]
        == "#/components/schemas/ProviderRead"
    )
    assert (
        list_providers["responses"]["500"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )
    assert "PipelineTemplateRead" in schemas
    assert "StageRoleBinding" in schemas
    assert "ProviderRead" in schemas
    assert "ModelRuntimeCapabilities" in schemas
    template_properties = schemas["PipelineTemplateRead"]["properties"]
    assert template_properties["max_react_iterations_per_stage"]["exclusiveMinimum"] == 0
    assert template_properties["max_tool_calls_per_stage"]["exclusiveMinimum"] == 0
    assert template_properties["skip_high_risk_tool_confirmations"]["type"] == "boolean"
    assert "PromptAssetRead" not in schemas
    assert "prompt_version" not in schemas["StageRoleBinding"]["properties"]
    assert "api_key" not in schemas["ProviderRead"]["properties"]
