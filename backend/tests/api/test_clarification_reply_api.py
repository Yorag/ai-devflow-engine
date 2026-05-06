from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, SessionModel
from backend.app.db.models.event import DomainEventModel, EventBase
from backend.app.db.models.graph import GraphBase
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.db.models.runtime import (
    ClarificationRecordModel,
    PipelineRunModel,
    RuntimeBase,
)
from backend.app.domain.enums import RunStatus, SseEventType
from backend.app.main import create_app
from backend.app.services.sessions import DEFAULT_SESSION_DISPLAY_NAME


def build_app(tmp_path: Path):
    from backend.tests.services.test_clarification_flow import (
        FakeCheckpointPort,
        FakeRuntimePort,
        RecordingAuditService,
    )

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
    app.state.h41_runtime_port = FakeRuntimePort()
    app.state.h41_checkpoint_port = FakeCheckpointPort()
    app.state.h41_audit_service = RecordingAuditService()
    return app


def seed_waiting_clarification_via_service(app) -> str:
    from backend.app.services.clarifications import ClarificationService
    from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
    from backend.tests.services.test_clarification_flow import (
        build_trace,
        seed_waiting_requirement_analysis,
    )

    manager = app.state.database_manager
    seed_waiting_requirement_analysis(manager)
    control_session = manager.session(DatabaseRole.CONTROL)
    runtime_session = manager.session(DatabaseRole.RUNTIME)
    event_session = manager.session(DatabaseRole.EVENT)
    try:
        service = ClarificationService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
            audit_service=app.state.h41_audit_service,
            runtime_orchestration=RuntimeOrchestrationService(
                runtime_port=app.state.h41_runtime_port,
                checkpoint_port=app.state.h41_checkpoint_port,
            ),
        )
        result = service.request_clarification(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            question="Which package should be changed?",
            payload_ref="clarification-payload-1",
            trace_context=build_trace(),
        )
        return result.clarification_id
    finally:
        control_session.close()
        runtime_session.close()
        event_session.close()


def test_post_session_message_accepts_clarification_reply_and_restores_running(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    clarification_id = seed_waiting_clarification_via_service(app)

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/session-1/messages",
            json={
                "message_type": "clarification_reply",
                "content": "Change backend only.",
            },
            headers={
                "X-Request-ID": "req-clarification-reply",
                "X-Correlation-ID": "corr-clarification-reply",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "running"
    assert body["message_item"]["type"] == "user_message"
    assert body["message_item"]["content"] == "Change backend only."
    assert body["message_item"]["stage_run_id"] == "stage-run-1"
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        clarification = session.get(ClarificationRecordModel, clarification_id)
        run = session.get(PipelineRunModel, "run-1")
        assert clarification.answer == "Change backend only."
        assert run.status is RunStatus.RUNNING
    with app.state.database_manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.CLARIFICATION_ANSWERED)
            .one()
        )
        assert event.payload["message_item"]["content"] == "Change backend only."
    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(AuditLogEntryModel.action == "session.message.clarification_reply")
            .one()
        )
    assert audit.request_id == "req-clarification-reply"
    assert audit.correlation_id == "corr-clarification-reply"


def test_clarification_reply_does_not_auto_title_default_named_session(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)
    seed_waiting_clarification_via_service(app)

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        model = session.get(SessionModel, "session-1")
        assert model is not None
        model.display_name = DEFAULT_SESSION_DISPLAY_NAME
        session.add(model)
        session.commit()

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/session-1/messages",
            json={
                "message_type": "clarification_reply",
                "content": "Keep the existing default title.",
            },
        )

    assert response.status_code == 200
    assert response.json()["session"]["display_name"] == DEFAULT_SESSION_DISPLAY_NAME
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        saved = session.get(SessionModel, "session-1")
        assert saved is not None
        assert saved.display_name == DEFAULT_SESSION_DISPLAY_NAME


def test_clarification_reply_rejects_illegal_state_with_conflict_and_audit(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        create_response = client.post("/api/projects/project-default/sessions")
        assert create_response.status_code == 201
        created = create_response.json()
        response = client.post(
            f"/api/sessions/{created['session_id']}/messages",
            json={"message_type": "clarification_reply", "content": "Too early."},
            headers={
                "X-Request-ID": "req-clarification-conflict",
                "X-Correlation-ID": "corr-clarification-conflict",
            },
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "validation_error"
    assert "waiting_clarification" in response.json()["message"]
    with app.state.database_manager.session(DatabaseRole.LOG) as session:
        audit = (
            session.query(AuditLogEntryModel)
            .filter(
                AuditLogEntryModel.action
                == "session.message.clarification_reply.rejected"
            )
            .one()
        )
        assert audit.request_id == "req-clarification-conflict"
        assert audit.correlation_id == "corr-clarification-conflict"


def test_clarification_reply_missing_session_returns_not_found(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/session-missing/messages",
            json={"message_type": "clarification_reply", "content": "Too early."},
            headers={
                "X-Request-ID": "req-clarification-missing",
                "X-Correlation-ID": "corr-clarification-missing",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Session was not found.",
        "request_id": "req-clarification-missing",
        "correlation_id": "corr-clarification-missing",
    }


def test_clarification_reply_route_is_documented_in_openapi(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    path = document["paths"]["/api/sessions/{sessionId}/messages"]["post"]
    schemas = document["components"]["schemas"]
    assert (
        path["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionMessageAppendRequest"
    )
    assert (
        path["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/SessionMessageAppendResponse"
    )
    assert set(path["responses"]) == {"200", "404", "409", "422", "500", "503"}
    for code in ("404", "409", "422", "500", "503"):
        assert (
            path["responses"][code]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    assert set(schemas["SessionMessageAppendRequest"]["required"]) == {
        "message_type",
        "content",
    }
    assert set(
        schemas["SessionMessageAppendRequest"]["properties"]["message_type"]["enum"]
    ) == {"clarification_reply", "new_requirement"}
    assert set(schemas["SessionMessageAppendResponse"]["required"]) == {
        "session",
        "message_item",
    }
