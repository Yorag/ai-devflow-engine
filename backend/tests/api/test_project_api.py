from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, DeliveryChannelModel, ProjectModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.domain.enums import DeliveryMode
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


def build_project_api_app(tmp_path: Path, default_project_root: Path):
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_project_root,
    )
    return build_project_api_app_with_settings(settings)


def build_project_api_app_with_settings(settings: EnvironmentSettings):
    app = create_app(settings=settings)
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    return app


def test_startup_registers_default_project_channel_and_audit_before_requests(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    app = build_project_api_app(tmp_path, default_root)

    with TestClient(app):
        manager = app.state.database_manager
        with manager.session(DatabaseRole.CONTROL) as session:
            project = session.get(ProjectModel, "project-default")
            channel = session.get(DeliveryChannelModel, "delivery-default")
        with manager.session(DatabaseRole.LOG) as session:
            audit = session.query(AuditLogEntryModel).one_or_none()

    assert project is not None
    assert project.root_path == str(default_root.resolve())
    assert project.default_delivery_channel_id == "delivery-default"
    assert channel is not None
    assert channel.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert audit.action == "project.ensure_default"
    assert audit.result is AuditResult.SUCCEEDED
    assert str(default_root.resolve()) not in audit.target_id
    assert audit.request_id
    assert audit.correlation_id


def test_get_projects_creates_default_project_and_audit_record(tmp_path: Path) -> None:
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    app = build_project_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        response = client.get(
            "/api/projects",
            headers={
                "X-Request-ID": "req-project-list",
                "X-Correlation-ID": "corr-project-list",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-project-list"
    assert response.headers["x-correlation-id"] == "corr-project-list"
    body = response.json()
    assert body == [
        {
            "project_id": "project-default",
            "name": "ai-devflow-engine",
            "root_path": str(default_root.resolve()),
            "default_delivery_channel_id": "delivery-default",
            "is_default": True,
            "created_at": body[0]["created_at"],
            "updated_at": body[0]["updated_at"],
        }
    ]

    manager = app.state.database_manager
    with manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, "delivery-default")
    with manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "project.ensure_default")
            .one()
        )

    assert channel is not None
    assert channel.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert audit.action == "project.ensure_default"
    assert audit.result is AuditResult.SUCCEEDED
    assert str(default_root.resolve()) not in audit.target_id
    assert audit.request_id
    assert audit.correlation_id


def test_post_projects_loads_local_project_and_project_list_persists(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    app = build_project_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects",
            json={"root_path": str(loaded_root)},
            headers={
                "X-Request-ID": "req-project-load",
                "X-Correlation-ID": "corr-project-load",
            },
        )
        list_response = client.get("/api/projects")

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["project_id"].startswith("project-")
    assert created["project_id"] != "project-default"
    assert created["name"] == "loaded-app"
    assert created["root_path"] == str(loaded_root.resolve())
    assert created["default_delivery_channel_id"]
    assert created["is_default"] is False

    listed = list_response.json()
    assert [project["project_id"] for project in listed] == [
        "project-default",
        created["project_id"],
    ]

    manager = app.state.database_manager
    with manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, created["default_delivery_channel_id"])
    with manager.session(DatabaseRole.LOG) as session:
        audit_actions = [row.action for row in session.query(AuditLogEntryModel).all()]

    assert channel is not None
    assert channel.project_id == created["project_id"]
    assert channel.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert "project.load" in audit_actions


def test_project_list_persists_loaded_project_after_app_restart(tmp_path: Path) -> None:
    default_root = tmp_path / "platform"
    loaded_root = tmp_path / "loaded-app"
    default_root.mkdir()
    loaded_root.mkdir()
    settings = EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )
    first_app = build_project_api_app_with_settings(settings)

    with TestClient(first_app) as client:
        create_response = client.post(
            "/api/projects",
            json={"root_path": str(loaded_root)},
        )

    created_project_id = create_response.json()["project_id"]
    second_app = build_project_api_app_with_settings(settings)
    with TestClient(second_app) as client:
        list_response = client.get("/api/projects")

    assert list_response.status_code == 200
    listed = list_response.json()
    assert [project["project_id"] for project in listed] == [
        "project-default",
        created_project_id,
    ]
    assert listed[1]["root_path"] == str(loaded_root.resolve())

    with second_app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        project_rows = session.query(ProjectModel).all()

    assert sorted(project.project_id for project in project_rows) == sorted(
        [
            "project-default",
            created_project_id,
        ]
    )


def test_post_projects_rejects_missing_root_with_unified_error_and_rejected_audit(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "platform"
    missing_root = tmp_path / "missing"
    default_root.mkdir()
    app = build_project_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects",
            json={"root_path": str(missing_root)},
            headers={
                "X-Request-ID": "req-project-invalid",
                "X-Correlation-ID": "corr-project-invalid",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error_code": "validation_error",
        "message": "Project root_path must be an existing directory.",
        "request_id": "req-project-invalid",
        "correlation_id": "corr-project-invalid",
    }

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "project.load.rejected")
            .one()
        )

    assert audit.action == "project.load.rejected"
    assert audit.result is AuditResult.REJECTED
    assert str(missing_root.resolve(strict=False)) not in audit.target_id
    assert audit.request_id == "req-project-invalid"


def test_project_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    default_root = tmp_path / "platform"
    default_root.mkdir()
    app = build_project_api_app(tmp_path, default_root)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]
    get_projects = paths["/api/projects"]["get"]
    post_projects = paths["/api/projects"]["post"]

    assert (
        get_projects["responses"]["200"]["content"]["application/json"]["schema"][
            "items"
        ]["$ref"]
        == "#/components/schemas/ProjectRead"
    )
    assert (
        get_projects["responses"]["500"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        post_projects["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProjectCreateRequest"
    )
    assert (
        post_projects["responses"]["201"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ProjectRead"
    )
    assert (
        post_projects["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        post_projects["responses"]["500"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ErrorResponse"
    )
    assert set(schemas["ProjectCreateRequest"]["required"]) == {"root_path"}
    assert set(schemas["ProjectRead"]["required"]) == {
        "project_id",
        "name",
        "root_path",
        "is_default",
        "created_at",
        "updated_at",
    }
    assert "default_delivery_channel_id" not in schemas["ProjectRead"]["required"]
    default_channel_schema = schemas["ProjectRead"]["properties"][
        "default_delivery_channel_id"
    ]
    assert {"type": "null"} in default_channel_schema["anyOf"]
