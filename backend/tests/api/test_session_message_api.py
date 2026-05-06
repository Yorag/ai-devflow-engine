from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProviderModel, SessionModel
from backend.app.db.models.event import DomainEventModel, EventBase
from backend.app.db.models.graph import GraphBase, GraphDefinitionModel, GraphThreadModel
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.db.models.runtime import PipelineRunModel, RuntimeBase, StageRunModel
from backend.app.domain.enums import RunStatus, SessionStatus, StageStatus, StageType
from backend.app.main import create_app
from backend.app.schemas.observability import AuditResult


def build_app(tmp_path: Path):
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    app = create_app(
        EnvironmentSettings(
            platform_runtime_root=tmp_path / "runtime",
            default_project_root=default_root,
        )
    )
    ControlBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.RUNTIME))
    GraphBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.GRAPH))
    EventBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.EVENT))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    return app


def create_draft_session(client: TestClient) -> dict:
    response = client.post("/api/projects/project-default/sessions")
    assert response.status_code == 201
    configure_required_providers(client.app)
    return response.json()


def configure_required_providers(app) -> None:  # noqa: ANN001
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        providers = (
            session.query(ProviderModel)
            .filter(
                ProviderModel.provider_id.in_(
                    ["provider-deepseek", "provider-volcengine"]
                )
            )
            .all()
        )
        assert {provider.provider_id for provider in providers} == {
            "provider-deepseek",
            "provider-volcengine",
        }
        for provider in providers:
            provider.is_configured = True
            provider.is_enabled = True
            session.add(provider)
        session.commit()


def test_post_session_message_new_requirement_starts_first_run_and_returns_first_user_message(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        created = create_draft_session(client)
        response = client.post(
            f"/api/sessions/{created['session_id']}/messages",
            json={
                "message_type": "new_requirement",
                "content": "Implement workspace projection startup.",
            },
            headers={
                "X-Request-ID": "req-new-requirement",
                "X-Correlation-ID": "corr-new-requirement",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["session_id"] == created["session_id"]
    assert body["session"]["status"] == "running"
    assert body["session"]["current_run_id"]
    assert body["session"]["latest_stage_type"] == "requirement_analysis"
    assert body["message_item"]["type"] == "user_message"
    assert body["message_item"]["author"] == "user"
    assert body["message_item"]["content"] == "Implement workspace projection startup."
    assert body["message_item"]["run_id"] == body["session"]["current_run_id"]
    assert body["message_item"]["stage_run_id"]

    run_id = body["session"]["current_run_id"]
    stage_run_id = body["message_item"]["stage_run_id"]

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, created["session_id"])
        assert control_session is not None
        assert control_session.status is SessionStatus.RUNNING
        assert control_session.current_run_id == run_id
        assert control_session.latest_stage_type is StageType.REQUIREMENT_ANALYSIS

    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, run_id)
        assert run is not None
        assert run.status is RunStatus.RUNNING
        assert run.attempt_index == 1
        assert run.graph_definition_ref
        assert run.graph_thread_ref
        assert run.workspace_ref
        assert run.runtime_limit_snapshot_ref
        assert run.provider_call_policy_snapshot_ref
        assert run.template_snapshot_ref
        stage = session.get(StageRunModel, stage_run_id)
        assert stage is not None
        assert stage.stage_type is StageType.REQUIREMENT_ANALYSIS
        assert stage.status is StageStatus.RUNNING
        assert stage.attempt_index == 1
        assert stage.graph_node_key == "requirement_analysis"

    with app.state.database_manager.session(DatabaseRole.GRAPH) as session:
        definition = session.get(GraphDefinitionModel, run.graph_definition_ref)
        thread = session.get(GraphThreadModel, run.graph_thread_ref)
        assert definition is not None
        assert definition.run_id == run_id
        assert thread is not None
        assert thread.run_id == run_id
        assert thread.graph_definition_id == definition.graph_definition_id
        assert thread.current_node_key == "requirement_analysis"
        assert thread.status == "running"

    with app.state.database_manager.session(DatabaseRole.EVENT) as session:
        event_types = [
            row.event_type.value
            for row in session.query(DomainEventModel)
            .filter(DomainEventModel.session_id == created["session_id"])
            .order_by(DomainEventModel.sequence_index.asc())
            .all()
        ]
    assert event_types == [
        "pipeline_run_created",
        "session_status_changed",
        "stage_started",
        "session_message_appended",
    ]

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "session.message.new_requirement")
            .one()
        )
    assert audit.result is AuditResult.SUCCEEDED
    assert audit.request_id == "req-new-requirement"
    assert audit.correlation_id == "corr-new-requirement"


def test_new_requirement_auto_titles_default_draft_session_and_list_reflects_name(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    content = (
        "Build   checkout\n\nworkspace history controls with very long trailing detail"
    )
    expected_title = "Build checkout workspace hist..."

    with TestClient(app) as client:
        created = create_draft_session(client)
        response = client.post(
            f"/api/sessions/{created['session_id']}/messages",
            json={"message_type": "new_requirement", "content": content},
        )
        list_response = client.get("/api/projects/project-default/sessions")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["session_id"] == created["session_id"]
    assert body["session"]["display_name"] == expected_title

    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed[0]["session_id"] == created["session_id"]
    assert listed[0]["display_name"] == expected_title


def test_new_requirement_does_not_auto_title_renamed_session(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        created = create_draft_session(client)
        rename = client.patch(
            f"/api/sessions/{created['session_id']}",
            json={"display_name": "Manual planning session"},
        )
        assert rename.status_code == 200
        response = client.post(
            f"/api/sessions/{created['session_id']}/messages",
            json={
                "message_type": "new_requirement",
                "content": "This text must not replace a user-selected name.",
            },
        )
        list_response = client.get("/api/projects/project-default/sessions")

    assert response.status_code == 200
    assert response.json()["session"]["display_name"] == "Manual planning session"
    assert list_response.status_code == 200
    assert list_response.json()[0]["display_name"] == "Manual planning session"


def test_new_requirement_rejects_non_draft_or_existing_run_session(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        created = create_draft_session(client)
        first = client.post(
            f"/api/sessions/{created['session_id']}/messages",
            json={"message_type": "new_requirement", "content": "First requirement."},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/sessions/{created['session_id']}/messages",
            json={"message_type": "new_requirement", "content": "Second requirement."},
            headers={
                "X-Request-ID": "req-second-requirement",
                "X-Correlation-ID": "corr-second-requirement",
            },
        )

    assert second.status_code == 409
    assert second.json()["error_code"] == "validation_error"
    assert "draft" in second.json()["message"]
    assert "current_run_id" in second.json()["message"]

    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action == "session.message.new_requirement.rejected"
            )
            .one()
        )
    assert audit.result is AuditResult.REJECTED
    assert audit.request_id == "req-second-requirement"
    assert audit.correlation_id == "corr-second-requirement"


def test_new_requirement_missing_session_returns_not_found(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/session-missing/messages",
            json={"message_type": "new_requirement", "content": "Start missing session."},
            headers={
                "X-Request-ID": "req-new-requirement-missing",
                "X-Correlation-ID": "corr-new-requirement-missing",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Session was not found.",
        "request_id": "req-new-requirement-missing",
        "correlation_id": "corr-new-requirement-missing",
    }


def test_session_message_route_is_documented_for_new_requirement(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    path = document["paths"]["/api/sessions/{sessionId}/messages"]["post"]
    schema = document["components"]["schemas"]["SessionMessageAppendRequest"]

    assert (
        path["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionMessageAppendRequest"
    )
    assert (
        path["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionMessageAppendResponse"
    )
    assert set(path["responses"]) == {"200", "404", "409", "422", "500", "503"}
    assert set(schema["required"]) == {"message_type", "content"}
    assert set(schema["properties"]["message_type"]["enum"]) == {
        "clarification_reply",
        "new_requirement",
    }
