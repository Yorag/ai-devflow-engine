from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, SessionModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.domain.enums import SessionStatus
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


def build_session_api_app(tmp_path: Path):
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


def _assert_error(
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


def _alternate_template_id(selected_template_id: str) -> str:
    if selected_template_id == "template-bugfix":
        return "template-refactor"
    return "template-bugfix"


def _create_session(client: TestClient) -> dict:
    response = client.post("/api/projects/project-default/sessions")
    assert response.status_code == 201
    return response.json()


def _assert_same_session_identity(actual: dict, expected: dict) -> None:
    assert actual["session_id"] == expected["session_id"]
    assert actual["project_id"] == expected["project_id"]
    assert actual["display_name"] == expected["display_name"]
    assert actual["status"] == expected["status"]
    assert actual["selected_template_id"] == expected["selected_template_id"]
    assert actual["current_run_id"] == expected["current_run_id"]
    assert actual["latest_stage_type"] == expected["latest_stage_type"]
    assert actual["created_at"]
    assert actual["updated_at"]


def test_session_routes_create_list_get_rename_and_update_template(
    tmp_path: Path,
) -> None:
    app = build_session_api_app(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/project-default/sessions",
            headers={
                "X-Request-ID": "req-session-create",
                "X-Correlation-ID": "corr-session-create",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        list_response = client.get("/api/projects/project-default/sessions")
        get_response = client.get(f"/api/sessions/{created['session_id']}")
        rename_response = client.patch(
            f"/api/sessions/{created['session_id']}",
            json={"display_name": "Requirement discovery"},
            headers={
                "X-Request-ID": "req-session-rename",
                "X-Correlation-ID": "corr-session-rename",
            },
        )
        next_template_id = _alternate_template_id(created["selected_template_id"])
        template_response = client.put(
            f"/api/sessions/{created['session_id']}/template",
            json={"template_id": next_template_id},
            headers={
                "X-Request-ID": "req-session-template-update",
                "X-Correlation-ID": "corr-session-template-update",
            },
        )

    assert create_response.status_code == 201
    assert create_response.headers["x-request-id"] == "req-session-create"
    assert create_response.headers["x-correlation-id"] == "corr-session-create"
    assert created["session_id"].startswith("session-")
    assert created["project_id"] == "project-default"
    assert created["display_name"] == "Untitled requirement"
    assert created["status"] == "draft"
    assert created["selected_template_id"].startswith("template-")
    assert created["current_run_id"] is None
    assert created["latest_stage_type"] is None
    assert created["created_at"]
    assert created["updated_at"]

    assert list_response.status_code == 200
    listed = list_response.json()
    assert len(listed) == 1
    _assert_same_session_identity(listed[0], created)
    assert get_response.status_code == 200
    _assert_same_session_identity(get_response.json(), created)

    assert rename_response.status_code == 200
    renamed = rename_response.json()
    assert renamed["session_id"] == created["session_id"]
    assert renamed["display_name"] == "Requirement discovery"
    assert renamed["selected_template_id"] == created["selected_template_id"]

    assert template_response.status_code == 200
    updated = template_response.json()
    assert updated["session_id"] == created["session_id"]
    assert updated["display_name"] == "Requirement discovery"
    assert updated["selected_template_id"] == next_template_id
    assert updated["status"] == "draft"

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audits = {
            row.action: row
            for row in session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.target_id == created["session_id"])
            .all()
        }

    assert set(audits) == {
        "session.create",
        "session.rename",
        "session.template.update",
    }
    assert audits["session.create"].result is AuditResult.SUCCEEDED
    assert audits["session.create"].request_id == "req-session-create"
    assert audits["session.create"].correlation_id == "corr-session-create"
    assert audits["session.rename"].result is AuditResult.SUCCEEDED
    assert audits["session.rename"].request_id == "req-session-rename"
    assert audits["session.rename"].correlation_id == "corr-session-rename"
    assert audits["session.template.update"].result is AuditResult.SUCCEEDED
    assert audits["session.template.update"].request_id == (
        "req-session-template-update"
    )
    assert audits["session.template.update"].correlation_id == (
        "corr-session-template-update"
    )


def test_create_and_list_sessions_missing_project_return_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_session_api_app(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/project-missing/sessions",
            headers={
                "X-Request-ID": "req-session-project-create",
                "X-Correlation-ID": "corr-session-project-create",
            },
        )
        list_response = client.get(
            "/api/projects/project-missing/sessions",
            headers={
                "X-Request-ID": "req-session-project-list",
                "X-Correlation-ID": "corr-session-project-list",
            },
        )

    _assert_error(
        create_response,
        status_code=404,
        error_code="not_found",
        message="Project was not found.",
        request_id="req-session-project-create",
        correlation_id="corr-session-project-create",
    )
    _assert_error(
        list_response,
        status_code=404,
        error_code="not_found",
        message="Project was not found.",
        request_id="req-session-project-list",
        correlation_id="corr-session-project-list",
    )


def test_missing_session_routes_return_unified_not_found(tmp_path: Path) -> None:
    app = build_session_api_app(tmp_path)

    with TestClient(app) as client:
        get_response = client.get(
            "/api/sessions/session-missing",
            headers={
                "X-Request-ID": "req-session-get-missing",
                "X-Correlation-ID": "corr-session-get-missing",
            },
        )
        rename_response = client.patch(
            "/api/sessions/session-missing",
            json={"display_name": "Renamed"},
            headers={
                "X-Request-ID": "req-session-rename-missing",
                "X-Correlation-ID": "corr-session-rename-missing",
            },
        )
        template_response = client.put(
            "/api/sessions/session-missing/template",
            json={"template_id": "template-feature"},
            headers={
                "X-Request-ID": "req-session-template-missing-session",
                "X-Correlation-ID": "corr-session-template-missing-session",
            },
        )

    for response, request_id, correlation_id in [
        (get_response, "req-session-get-missing", "corr-session-get-missing"),
        (rename_response, "req-session-rename-missing", "corr-session-rename-missing"),
        (
            template_response,
            "req-session-template-missing-session",
            "corr-session-template-missing-session",
        ),
    ]:
        _assert_error(
            response,
            status_code=404,
            error_code="not_found",
            message="Session was not found.",
            request_id=request_id,
            correlation_id=correlation_id,
        )


def test_update_template_missing_template_returns_unified_error_and_rejected_audit(
    tmp_path: Path,
) -> None:
    app = build_session_api_app(tmp_path)

    with TestClient(app) as client:
        created = _create_session(client)
        response = client.put(
            f"/api/sessions/{created['session_id']}/template",
            json={"template_id": "template-missing"},
            headers={
                "X-Request-ID": "req-session-template-missing",
                "X-Correlation-ID": "corr-session-template-missing",
            },
        )

    _assert_error(
        response,
        status_code=422,
        error_code="validation_error",
        message="Pipeline template was not found.",
        request_id="req-session-template-missing",
        correlation_id="corr-session-template-missing",
    )
    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "session.template.update.rejected")
            .one()
        )

    assert audit.target_id == created["session_id"]
    assert audit.result is AuditResult.REJECTED
    assert audit.reason == "Pipeline template was not found."
    assert audit.request_id == "req-session-template-missing"
    assert audit.correlation_id == "corr-session-template-missing"
    assert "template-missing" in (audit.metadata_excerpt or "")


@pytest.mark.parametrize(
    ("status", "current_run_id"),
    [
        (SessionStatus.DRAFT, "run-started"),
        (SessionStatus.RUNNING, None),
    ],
)
def test_update_template_rejects_after_run_started_or_non_draft_with_conflict(
    tmp_path: Path,
    status: SessionStatus,
    current_run_id: str | None,
) -> None:
    app = build_session_api_app(tmp_path)

    with TestClient(app) as client:
        created = _create_session(client)
        next_template_id = _alternate_template_id(created["selected_template_id"])

        with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
            model = session.get(SessionModel, created["session_id"])
            assert model is not None
            model.status = status
            model.current_run_id = current_run_id
            session.add(model)
            session.commit()

        response = client.put(
            f"/api/sessions/{created['session_id']}/template",
            json={"template_id": next_template_id},
            headers={
                "X-Request-ID": "req-session-template-conflict",
                "X-Correlation-ID": "corr-session-template-conflict",
            },
        )

    _assert_error(
        response,
        status_code=409,
        error_code="validation_error",
        message="Only draft Sessions without a run can change templates.",
        request_id="req-session-template-conflict",
        correlation_id="corr-session-template-conflict",
    )


def test_session_routes_are_documented_in_openapi(tmp_path: Path) -> None:
    app = build_session_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    assert "/api/projects/{projectId}/sessions" in paths
    assert "/api/sessions/{sessionId}" in paths
    assert "/api/sessions/{sessionId}/template" in paths

    project_sessions = paths["/api/projects/{projectId}/sessions"]
    get_session = paths["/api/sessions/{sessionId}"]["get"]
    patch_session = paths["/api/sessions/{sessionId}"]["patch"]
    put_session_template = paths["/api/sessions/{sessionId}/template"]["put"]

    assert set(project_sessions["post"]["responses"]) == {"201", "404", "422", "500"}
    assert set(project_sessions["get"]["responses"]) == {"200", "404", "422", "500"}
    assert set(get_session["responses"]) == {"200", "404", "422", "500"}
    assert set(patch_session["responses"]) == {"200", "404", "422", "500"}
    assert set(put_session_template["responses"]) == {
        "200",
        "404",
        "409",
        "422",
        "500",
    }

    assert (
        project_sessions["post"]["responses"]["201"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/SessionRead"
    )
    assert (
        project_sessions["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["items"]["$ref"]
        == "#/components/schemas/SessionRead"
    )
    assert (
        get_session["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionRead"
    )
    assert (
        patch_session["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionRenameRequest"
    )
    assert (
        patch_session["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/SessionRead"
    )
    assert (
        put_session_template["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/SessionTemplateUpdateRequest"
    )
    assert (
        put_session_template["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/SessionRead"
    )

    for operation in [
        project_sessions["post"],
        project_sessions["get"],
        get_session,
        patch_session,
        put_session_template,
    ]:
        for status_code in ("404", "500"):
            assert (
                operation["responses"][status_code]["content"]["application/json"][
                    "schema"
                ]["$ref"]
                == "#/components/schemas/ErrorResponse"
            )

    for operation in [
        project_sessions["post"],
        project_sessions["get"],
        get_session,
        patch_session,
        put_session_template,
    ]:
        assert (
            operation["responses"]["422"]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )

    assert (
        put_session_template["responses"]["409"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )
    assert set(schemas["SessionRenameRequest"]["required"]) == {"display_name"}
    assert set(schemas["SessionTemplateUpdateRequest"]["required"]) == {"template_id"}
    assert set(schemas["SessionRead"]["required"]) == {
        "session_id",
        "project_id",
        "display_name",
        "status",
        "selected_template_id",
        "created_at",
        "updated_at",
    }
    assert "ErrorResponse" in schemas
