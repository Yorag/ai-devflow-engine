from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, PipelineTemplateModel, ProviderModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.domain.trace_context import TraceContext
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult
from backend.app.schemas.template import FIXED_APPROVAL_CHECKPOINTS, FIXED_STAGE_SEQUENCE
from backend.app.services.providers import ProviderService


def build_template_api_app(tmp_path: Path):
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    app = create_app(settings=settings)
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    configure_required_template_providers(app)
    return app


class _NoopAuditService:
    def record_command_result(self, **kwargs):
        return object()


def configure_required_template_providers(app) -> None:
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        ProviderService(
            session,
            audit_service=_NoopAuditService(),
            now=lambda: datetime(2026, 5, 5, 9, 0, 0, tzinfo=UTC),
        ).seed_builtin_providers(
            trace_context=TraceContext(
                request_id="template-test-provider-seed",
                trace_id="template-test-provider-seed",
                correlation_id="template-test-provider-seed",
                span_id="template-test-provider-seed",
                parent_span_id=None,
                created_at=datetime(2026, 5, 5, 9, 0, 0, tzinfo=UTC),
            )
        )
        for provider in (
            session.query(ProviderModel)
            .filter(
                ProviderModel.provider_id.in_(
                    ["provider-deepseek", "provider-volcengine"]
                )
            )
            .all()
        ):
            provider.is_configured = True
            provider.is_enabled = True
        session.commit()


def write_payload(name: str = "Custom feature flow") -> dict:
    return {
        "name": name,
        "description": "Team-owned feature template",
        "fixed_stage_sequence": [stage.value for stage in FIXED_STAGE_SEQUENCE],
        "stage_role_bindings": [
            {
                "stage_type": stage_type.value,
                "role_id": role_id,
                "system_prompt": f"# Prompt for {stage_type.value}",
                "provider_id": "provider-deepseek",
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
        "approval_checkpoints": [
            checkpoint.value for checkpoint in FIXED_APPROVAL_CHECKPOINTS
        ],
        "auto_regression_enabled": False,
        "max_auto_regression_retries": 3,
    }


def editable_payload(name: str = "Custom feature flow") -> dict:
    payload = write_payload(name)
    payload.pop("fixed_stage_sequence")
    payload.pop("approval_checkpoints")
    return payload


def assert_error(
    response,
    *,
    status_code: int,
    error_code: str,
    message: str,
    request_id: str,
    correlation_id: str,
) -> None:
    assert response.status_code == status_code
    assert response.json() == {
        "error_code": error_code,
        "message": message,
        "request_id": request_id,
        "correlation_id": correlation_id,
    }


def test_template_command_routes_create_save_as_patch_delete_and_audit(
    tmp_path: Path,
) -> None:
    app = build_template_api_app(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/pipeline-templates",
            json=write_payload("Standalone user flow"),
            headers={
                "X-Request-ID": "req-template-create",
                "X-Correlation-ID": "corr-template-create",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()

        save_as_response = client.post(
            "/api/pipeline-templates/template-feature/save-as",
            json=write_payload("Feature variant"),
            headers={
                "X-Request-ID": "req-template-save-as",
                "X-Correlation-ID": "corr-template-save-as",
            },
        )
        assert save_as_response.status_code == 201
        saved_as = save_as_response.json()

        patch_response = client.patch(
            f"/api/pipeline-templates/{saved_as['template_id']}",
            json=write_payload("Feature variant updated"),
            headers={
                "X-Request-ID": "req-template-patch",
                "X-Correlation-ID": "corr-template-patch",
            },
        )
        assert patch_response.status_code == 200
        patched = patch_response.json()

        list_response = client.get("/api/pipeline-templates")
        delete_response = client.delete(
            f"/api/pipeline-templates/{saved_as['template_id']}",
            headers={
                "X-Request-ID": "req-template-delete",
                "X-Correlation-ID": "corr-template-delete",
            },
        )
        after_delete_response = client.get("/api/pipeline-templates")

    assert created["template_id"].startswith("template-user-")
    assert created["template_source"] == "user_template"
    assert created["base_template_id"] is None
    assert saved_as["template_id"].startswith("template-user-")
    assert saved_as["template_source"] == "user_template"
    assert saved_as["base_template_id"] == "template-feature"
    assert patched["template_id"] == saved_as["template_id"]
    assert patched["name"] == "Feature variant updated"
    assert patched["template_source"] == "user_template"
    assert list_response.status_code == 200
    assert [item["template_id"] for item in list_response.json()] == [
        "template-bugfix",
        "template-feature",
        "template-refactor",
        created["template_id"],
        saved_as["template_id"],
    ]
    assert delete_response.status_code == 204
    assert after_delete_response.status_code == 200
    assert saved_as["template_id"] not in {
        item["template_id"] for item in after_delete_response.json()
    }

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audits = {
            (row.action, row.request_id): row
            for row in session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action.in_(
                    ["template.save_as", "template.patch", "template.delete"]
                )
            )
            .all()
        }

    assert audits[("template.save_as", "req-template-create")].result is (
        AuditResult.SUCCEEDED
    )
    assert audits[("template.save_as", "req-template-save-as")].result is (
        AuditResult.SUCCEEDED
    )
    assert audits[("template.patch", "req-template-patch")].result is (
        AuditResult.SUCCEEDED
    )
    assert audits[("template.delete", "req-template-delete")].result is (
        AuditResult.SUCCEEDED
    )
    assert audits[("template.patch", "req-template-patch")].correlation_id == (
        "corr-template-patch"
    )
    assert "Prompt for" not in (
        audits[("template.save_as", "req-template-save-as")].metadata_excerpt or ""
    )


def test_template_command_routes_return_unified_errors_for_system_or_missing_template(
    tmp_path: Path,
) -> None:
    app = build_template_api_app(tmp_path)

    with TestClient(app) as client:
        patch_system = client.patch(
            "/api/pipeline-templates/template-feature",
            json=write_payload(),
            headers={
                "X-Request-ID": "req-template-patch-system",
                "X-Correlation-ID": "corr-template-patch-system",
            },
        )
        delete_system = client.delete(
            "/api/pipeline-templates/template-feature",
            headers={
                "X-Request-ID": "req-template-delete-system",
                "X-Correlation-ID": "corr-template-delete-system",
            },
        )
        save_as_missing = client.post(
            "/api/pipeline-templates/template-missing/save-as",
            json=write_payload(),
            headers={
                "X-Request-ID": "req-template-save-as-missing",
                "X-Correlation-ID": "corr-template-save-as-missing",
            },
        )

    assert_error(
        patch_system,
        status_code=409,
        error_code="validation_error",
        message="System templates cannot be overwritten.",
        request_id="req-template-patch-system",
        correlation_id="corr-template-patch-system",
    )
    assert_error(
        delete_system,
        status_code=409,
        error_code="validation_error",
        message="System templates cannot be deleted.",
        request_id="req-template-delete-system",
        correlation_id="corr-template-delete-system",
    )
    assert_error(
        save_as_missing,
        status_code=404,
        error_code="not_found",
        message="Pipeline template was not found.",
        request_id="req-template-save-as-missing",
        correlation_id="corr-template-save-as-missing",
    )

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        rejected_actions = [
            row.action
            for row in session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.result == AuditResult.REJECTED)
            .order_by(AuditLogEntryModel.created_at)
            .all()
        ]

    assert "template.patch.rejected" in rejected_actions
    assert "template.delete.rejected" in rejected_actions
    assert "template.save_as.rejected" in rejected_actions


def test_template_command_routes_validate_payload_without_saving(
    tmp_path: Path,
) -> None:
    app = build_template_api_app(tmp_path)
    payload = write_payload()
    payload["stage_role_bindings"] = deepcopy(payload["stage_role_bindings"])
    payload["stage_role_bindings"][0]["provider_id"] = "provider-missing"

    with TestClient(app) as client:
        response = client.post(
            "/api/pipeline-templates/template-feature/save-as",
            json=payload,
            headers={
                "X-Request-ID": "req-template-invalid-provider",
                "X-Correlation-ID": "corr-template-invalid-provider",
            },
        )

    assert_error(
        response,
        status_code=422,
        error_code="validation_error",
        message="Pipeline template references an unknown Provider.",
        request_id="req-template-invalid-provider",
        correlation_id="corr-template-invalid-provider",
    )
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        user_count = (
            session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_source == "user_template")
            .count()
        )

    assert user_count == 0


def test_template_command_routes_accept_editable_only_payload(
    tmp_path: Path,
) -> None:
    app = build_template_api_app(tmp_path)

    with TestClient(app) as client:
        save_as_response = client.post(
            "/api/pipeline-templates/template-feature/save-as",
            json=editable_payload("Editable-only variant"),
            headers={
                "X-Request-ID": "req-template-editable-save-as",
                "X-Correlation-ID": "corr-template-editable-save-as",
            },
        )
        assert save_as_response.status_code == 201
        saved_as = save_as_response.json()

        patch_response = client.patch(
            f"/api/pipeline-templates/{saved_as['template_id']}",
            json=editable_payload("Editable-only variant updated"),
            headers={
                "X-Request-ID": "req-template-editable-patch",
                "X-Correlation-ID": "corr-template-editable-patch",
            },
        )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["name"] == "Editable-only variant updated"
    assert patched["fixed_stage_sequence"] == [
        stage.value for stage in FIXED_STAGE_SEQUENCE
    ]
    assert patched["approval_checkpoints"] == [
        checkpoint.value for checkpoint in FIXED_APPROVAL_CHECKPOINTS
    ]


def test_template_command_routes_reject_delete_of_template_used_as_save_as_source(
    tmp_path: Path,
) -> None:
    app = build_template_api_app(tmp_path)

    with TestClient(app) as client:
        parent_response = client.post(
            "/api/pipeline-templates",
            json=write_payload("Parent user flow"),
            headers={
                "X-Request-ID": "req-template-parent",
                "X-Correlation-ID": "corr-template-parent",
            },
        )
        assert parent_response.status_code == 201
        parent = parent_response.json()

        child_response = client.post(
            f"/api/pipeline-templates/{parent['template_id']}/save-as",
            json=write_payload("Child user flow"),
            headers={
                "X-Request-ID": "req-template-child",
                "X-Correlation-ID": "corr-template-child",
            },
        )
        assert child_response.status_code == 201
        child = child_response.json()

        delete_response = client.delete(
            f"/api/pipeline-templates/{parent['template_id']}",
            headers={
                "X-Request-ID": "req-template-delete-parent",
                "X-Correlation-ID": "corr-template-delete-parent",
            },
        )

        parent_detail = client.get(f"/api/pipeline-templates/{parent['template_id']}")
        child_detail = client.get(f"/api/pipeline-templates/{child['template_id']}")

    assert_error(
        delete_response,
        status_code=409,
        error_code="validation_error",
        message="Pipeline template is used as a base template by another template.",
        request_id="req-template-delete-parent",
        correlation_id="corr-template-delete-parent",
    )
    assert parent_detail.status_code == 200
    assert child_detail.status_code == 200
    assert child_detail.json()["base_template_id"] == parent["template_id"]

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        rejected = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "template.delete.rejected",
                AuditLogEntryModel.request_id == "req-template-delete-parent",
            )
            .one_or_none()
        )

    assert rejected is not None
    assert rejected.result is AuditResult.REJECTED


def test_template_command_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_template_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    assert "/api/pipeline-templates" in paths
    assert "/api/pipeline-templates/{templateId}" in paths
    assert "/api/pipeline-templates/{templateId}/save-as" in paths

    create_template = paths["/api/pipeline-templates"]["post"]
    patch_template = paths["/api/pipeline-templates/{templateId}"]["patch"]
    save_as_template = paths["/api/pipeline-templates/{templateId}/save-as"]["post"]
    delete_template = paths["/api/pipeline-templates/{templateId}"]["delete"]

    assert set(create_template["responses"]) == {"201", "422", "500"}
    assert set(patch_template["responses"]) == {"200", "404", "409", "422", "500"}
    assert set(save_as_template["responses"]) == {"201", "404", "422", "500"}
    assert set(delete_template["responses"]) == {"204", "404", "409", "422", "500"}
    assert (
        create_template["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PipelineTemplateWriteRequest"
    )
    assert (
        create_template["responses"]["201"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/PipelineTemplateRead"
    )
    assert (
        patch_template["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PipelineTemplateWriteRequest"
    )
    assert (
        patch_template["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/PipelineTemplateRead"
    )
    assert (
        save_as_template["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PipelineTemplateWriteRequest"
    )
    assert (
        save_as_template["responses"]["201"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/PipelineTemplateRead"
    )

    for operation in [create_template, patch_template, save_as_template, delete_template]:
        assert (
            operation["responses"]["422"]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )
        assert (
            operation["responses"]["500"]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )
    for operation in [patch_template, save_as_template, delete_template]:
        assert (
            operation["responses"]["404"]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )
    for operation in [patch_template, delete_template]:
        assert (
            operation["responses"]["409"]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )

    assert set(schemas["PipelineTemplateWriteRequest"]["required"]) == {
        "name",
        "stage_role_bindings",
        "auto_regression_enabled",
        "max_auto_regression_retries",
    }
    assert "template_source" not in schemas["PipelineTemplateWriteRequest"]["properties"]
    assert "base_template_id" not in schemas["PipelineTemplateWriteRequest"]["properties"]
    assert "role_name" not in schemas["PipelineTemplateWriteRequest"]["properties"]
