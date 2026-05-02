from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    ProjectModel,
    SessionModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import SessionStatus, StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditResult


NOW = datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 2, 12, 5, 0, tzinfo=UTC)


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
        request_id="request-session-test",
        trace_id="trace-session-test",
        correlation_id="correlation-session-test",
        span_id="span-session-test",
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


def seed_project_and_templates(session) -> None:  # noqa: ANN001
    from backend.app.services.templates import TemplateService

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
    TemplateService(
        session,
        audit_service=RecordingAuditService(),
        now=lambda: NOW,
    ).seed_system_templates(trace_context=build_trace())


def test_create_session_uses_default_template_and_audits_draft_state(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService
    from backend.app.services.templates import DEFAULT_TEMPLATE_ID

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_and_templates(session)
        created = SessionService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        saved = session.get(SessionModel, created.session_id)

    assert created.session_id.startswith("session-")
    assert created.project_id == "project-default"
    assert created.display_name == "Untitled requirement"
    assert created.status is SessionStatus.DRAFT
    assert created.selected_template_id == DEFAULT_TEMPLATE_ID
    assert created.current_run_id is None
    assert created.latest_stage_type is None
    assert created.created_at == NOW
    assert saved is not None
    assert audit.records[0]["action"] == "session.create"
    assert audit.records[0]["target_id"] == created.session_id
    assert audit.records[0]["result"] is AuditResult.SUCCEEDED
    assert audit.records[0]["metadata"]["selected_template_id"] == DEFAULT_TEMPLATE_ID


def test_list_and_get_sessions_return_only_visible_project_sessions(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_and_templates(session)
        service = SessionService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        )
        first = service.create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        second = service.create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        first.updated_at = LATER
        hidden = service.create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        hidden.is_visible = False
        session.commit()

        listed = service.list_project_sessions(
            project_id="project-default",
            trace_context=build_trace(),
        )
        found = service.get_session(first.session_id, trace_context=build_trace())
        missing_hidden = service.get_session(hidden.session_id, trace_context=build_trace())

    assert [item.session_id for item in listed] == [first.session_id, second.session_id]
    assert found is not None
    assert found.session_id == first.session_id
    assert missing_hidden is None


def test_rename_session_changes_only_display_name_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_and_templates(session)
        service = SessionService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        )
        created = service.create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        renamed = service.rename_session(
            session_id=created.session_id,
            display_name="Renamed flow",
            trace_context=build_trace(),
        )

    assert renamed.display_name == "Renamed flow"
    assert renamed.status is SessionStatus.DRAFT
    assert renamed.current_run_id is None
    assert renamed.latest_stage_type is None
    assert [record["action"] for record in audit.records] == [
        "session.create",
        "session.rename",
    ]
    assert audit.records[-1]["metadata"]["old_display_name"] == "Untitled requirement"
    assert audit.records[-1]["metadata"]["display_name"] == "Renamed flow"


def test_update_selected_template_allows_only_draft_without_run_and_audits_rejections(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError
    from backend.app.services.templates import DEFAULT_TEMPLATE_ID

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_and_templates(session)
        service = SessionService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        )
        created = service.create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        updated = service.update_selected_template(
            session_id=created.session_id,
            template_id="template-bugfix",
            trace_context=build_trace(),
        )

        assert updated.selected_template_id == "template-bugfix"
        assert updated.status is SessionStatus.DRAFT
        assert updated.current_run_id is None
        assert updated.latest_stage_type is None

        with pytest.raises(SessionServiceError) as missing_template:
            service.update_selected_template(
                session_id=created.session_id,
                template_id="template-missing",
                trace_context=build_trace(),
            )

        updated.status = SessionStatus.RUNNING
        updated.current_run_id = "run-active"
        updated.latest_stage_type = StageType.REQUIREMENT_ANALYSIS
        session.commit()

        with pytest.raises(SessionServiceError) as non_draft:
            service.update_selected_template(
                session_id=created.session_id,
                template_id=DEFAULT_TEMPLATE_ID,
                trace_context=build_trace(),
            )

        saved = session.get(SessionModel, created.session_id)

    assert missing_template.value.status_code == 422
    assert "Pipeline template was not found." in missing_template.value.message
    assert non_draft.value.status_code == 409
    assert "Only draft Sessions without a run can change templates." in (
        non_draft.value.message
    )
    assert saved is not None
    assert saved.selected_template_id == "template-bugfix"
    assert [record["action"] for record in audit.records] == [
        "session.create",
        "session.template.update",
        "session.template.update.rejected",
        "session.template.update.rejected",
    ]
    assert audit.records[-1]["result"] is AuditResult.REJECTED


def test_session_write_rolls_back_when_success_audit_fails(tmp_path: Path) -> None:
    from backend.app.services.sessions import SessionService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_and_templates(session)
        service = SessionService(
            session,
            audit_service=FailingAuditService(),
            now=lambda: NOW,
        )
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            service.create_session(
                project_id="project-default",
                trace_context=build_trace(),
            )

        saved_sessions = session.query(SessionModel).all()

    assert saved_sessions == []


def test_missing_or_hidden_project_rejects_session_creation(tmp_path: Path) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_and_templates(session)
        project = session.get(ProjectModel, "project-default")
        assert project is not None
        project.is_visible = False
        session.commit()

        service = SessionService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        )
        with pytest.raises(SessionServiceError) as hidden_project:
            service.create_session(
                project_id="project-default",
                trace_context=build_trace(),
            )
        with pytest.raises(SessionServiceError) as missing_project:
            service.create_session(
                project_id="project-missing",
                trace_context=build_trace(),
            )

    assert hidden_project.value.status_code == 404
    assert hidden_project.value.message == "Project was not found."
    assert missing_project.value.status_code == 404
    assert missing_project.value.message == "Project was not found."
