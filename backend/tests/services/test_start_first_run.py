from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    PipelineTemplateModel,
    ProjectModel,
    ProviderModel,
    SessionModel,
    StartupPublicationModel,
)
from backend.app.db.models.event import DomainEventModel, EventBase
from backend.app.db.models.graph import GraphBase, GraphDefinitionModel, GraphThreadModel
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderSnapshotModel,
    RuntimeBase,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    ProviderProtocolType,
    ProviderSource,
    RunStatus,
    SessionStatus,
    StageStatus,
    StageType,
    TemplateSource,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings


NOW = datetime(2026, 5, 3, 18, 0, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        return object()

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_failed_command", **kwargs})
        return object()


class FailingCommandResultAuditService(RecordingAuditService):
    def __init__(self, *, fail_action: str) -> None:
        super().__init__()
        self._fail_action = fail_action

    def require_audit_record(self, **kwargs: Any) -> object:
        return self.record_command_result(**kwargs)

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        if kwargs["action"] == self._fail_action:
            raise RuntimeError("audit ledger unavailable")
        return object()


class RecordingLogWriter:
    def __init__(self) -> None:
        self.records: list[object] = []

    def write(self, record) -> object:  # noqa: ANN001
        self.records.append(record)
        return object()

    def write_run_log(self, record) -> object:  # noqa: ANN001
        self.records.append(record)
        return object()


class RecordingRunPromptValidationService:
    def __init__(self, *, fail_message: str | None = None) -> None:
        self.fail_message = fail_message
        self.calls: list[dict[str, Any]] = []

    def validate_run_prompt_snapshots(
        self,
        *,
        template_snapshot,
        trace_context,
    ) -> None:  # noqa: ANN001
        self.calls.append(
            {
                "template_snapshot": template_snapshot,
                "trace_context": trace_context,
            }
        )
        if self.fail_message is not None:
            from backend.app.services.runs import RunPromptValidationError

            raise RunPromptValidationError(self.fail_message)


class BlockingRunPromptValidationService:
    def __init__(self) -> None:
        self.first_call_entered = threading.Event()
        self.release_first_call = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    def validate_run_prompt_snapshots(
        self,
        *,
        template_snapshot,
        trace_context,
    ) -> None:  # noqa: ANN001
        del template_snapshot, trace_context
        with self._lock:
            self.calls += 1
            call_index = self.calls
        if call_index == 1:
            self.first_call_entered.set()
            assert self.release_first_call.wait(timeout=5)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-start-first-run",
        trace_id="trace-start-first-run",
        correlation_id="correlation-start-first-run",
        span_id="span-start-first-run",
        parent_span_id=None,
        created_at=NOW,
    )


def build_settings(tmp_path: Path) -> EnvironmentSettings:
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    return EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )


def build_manager(settings: EnvironmentSettings) -> DatabaseManager:
    manager = DatabaseManager.from_environment_settings(settings)
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    GraphBase.metadata.create_all(manager.engine(DatabaseRole.GRAPH))
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    return manager


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def collect_runtime_log_rows(settings: EnvironmentSettings) -> list[dict[str, Any]]:
    runtime_settings = RuntimeDataSettings.from_environment_settings(settings)
    rows = read_jsonl(runtime_settings.logs_dir / "app.jsonl")
    if runtime_settings.run_logs_dir.exists():
        for path in sorted(runtime_settings.run_logs_dir.glob("*.jsonl")):
            rows.extend(read_jsonl(path))
    return rows


def seed_control_plane(
    session,
    *,
    settings: EnvironmentSettings,
    audit: RecordingAuditService,
    log_writer: RecordingLogWriter,
) -> None:
    from backend.app.services.providers import ProviderService
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService
    from backend.app.services.templates import TemplateService

    session.add(
        ProjectModel(
            project_id="project-default",
            name="AI Devflow Engine",
            root_path=str(settings.default_project_root),
            default_delivery_channel_id=None,
            is_default=True,
            is_visible=True,
            visibility_removed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()
    ProviderService(
        session,
        audit_service=audit,
        now=lambda: NOW,
        credential_env_prefixes=settings.credential_env_prefixes,
    ).seed_builtin_providers(trace_context=build_trace())
    TemplateService(
        session,
        audit_service=audit,
        now=lambda: NOW,
    ).seed_system_templates(trace_context=build_trace())
    PlatformRuntimeSettingsService(
        session,
        audit_service=audit,
        log_writer=log_writer,
        now=lambda: NOW,
    ).get_current_settings(trace_context=build_trace())


def _build_team_provider() -> ProviderModel:
    return ProviderModel(
        provider_id="provider-team",
        display_name="Team Provider",
        provider_source=ProviderSource.CUSTOM,
        protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
        base_url="https://team.example.test/v1",
        api_key_ref="env:TEAM_PROVIDER_API_KEY",
        default_model_id="team-chat",
        supported_model_ids=["team-chat"],
        runtime_capabilities=[
            {
                "model_id": "team-chat",
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


def _create_user_template_with_provider(
    session,
    *,
    template_id: str,
    provider_id: str,
) -> PipelineTemplateModel:
    source = session.get(PipelineTemplateModel, "template-feature")
    assert source is not None
    return PipelineTemplateModel(
        template_id=template_id,
        name=f"{template_id} name",
        description=None,
        template_source=TemplateSource.USER_TEMPLATE,
        base_template_id=source.template_id,
        fixed_stage_sequence=list(source.fixed_stage_sequence),
        stage_role_bindings=[
            {**binding, "provider_id": provider_id}
            for binding in source.stage_role_bindings
        ],
        approval_checkpoints=list(source.approval_checkpoints),
        auto_regression_enabled=source.auto_regression_enabled,
        max_auto_regression_retries=source.max_auto_regression_retries,
        created_at=NOW,
        updated_at=NOW,
    )


def test_session_service_start_run_from_new_requirement_creates_first_run_state(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        trace_context = build_trace()

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            result = SessionService(
                control_session,
                runtime_session=runtime_session,
                event_session=event_session,
                graph_session=graph_session,
                audit_service=audit,
                log_writer=log_writer,
                environment_settings=settings,
                now=lambda: NOW,
            ).start_run_from_new_requirement(
                session_id=draft.session_id,
                content="Implement workspace projection startup.",
                trace_context=trace_context,
            )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert result.session.session_id == draft.session_id
    assert result.session.status is SessionStatus.RUNNING
    assert result.run.status is RunStatus.RUNNING
    assert result.stage.stage_type is StageType.REQUIREMENT_ANALYSIS
    assert result.stage.status is StageStatus.RUNNING
    assert result.message_item.content == "Implement workspace projection startup."
    assert result.message_item.run_id == result.run.run_id
    assert result.message_item.stage_run_id == result.stage.stage_run_id

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, draft.session_id)
        assert saved_session is not None
        assert saved_session.status is SessionStatus.RUNNING
        assert saved_session.current_run_id == result.run.run_id
        assert saved_session.latest_stage_type is StageType.REQUIREMENT_ANALYSIS

    with manager.session(DatabaseRole.RUNTIME) as session:
        saved_run = session.get(PipelineRunModel, result.run.run_id)
        saved_stage = session.get(StageRunModel, result.stage.stage_run_id)
        assert saved_run is not None
        assert saved_run.attempt_index == 1
        assert saved_run.trigger_source.value == "initial_requirement"
        assert saved_run.trace_id != trace_context.trace_id
        assert saved_run.graph_definition_ref
        assert saved_run.graph_thread_ref
        assert saved_run.workspace_ref
        assert saved_run.runtime_limit_snapshot_ref
        assert saved_run.provider_call_policy_snapshot_ref
        assert saved_stage is not None
        assert saved_stage.stage_type is StageType.REQUIREMENT_ANALYSIS
        assert saved_stage.status is StageStatus.RUNNING
        assert saved_stage.graph_node_key == "requirement_analysis"

    with manager.session(DatabaseRole.GRAPH) as session:
        definition = session.get(GraphDefinitionModel, result.run.graph_definition_ref)
        thread = session.get(GraphThreadModel, result.run.graph_thread_ref)
        assert definition is not None
        assert definition.run_id == result.run.run_id
        assert thread is not None
        assert thread.run_id == result.run.run_id
        assert thread.current_node_key == "requirement_analysis"
        assert thread.status == "running"

    with manager.session(DatabaseRole.EVENT) as session:
        event_types = [
            row.event_type.value
            for row in session.query(DomainEventModel)
            .filter(DomainEventModel.session_id == draft.session_id)
            .order_by(DomainEventModel.sequence_index.asc())
            .all()
        ]
    assert event_types == [
        "pipeline_run_created",
        "session_status_changed",
        "stage_started",
        "session_message_appended",
    ]

    with manager.session(DatabaseRole.EVENT) as session:
        stage_started = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.session_id == draft.session_id,
                DomainEventModel.event_type == "stage_started",
            )
            .one()
        )
    stage_node = stage_started.payload["stage_node"]
    assert stage_node["stage_run_id"] == result.stage.stage_run_id
    assert stage_node["stage_type"] == "requirement_analysis"
    assert stage_node["status"] == "running"
    assert stage_node["summary"] == "Requirement Analysis started from the first user requirement."

    actions = [record["action"] for record in audit.records if "action" in record]
    assert "session.message.new_requirement.accepted" in actions
    assert "session.message.new_requirement" in actions
    accepted = next(
        record
        for record in audit.records
        if record.get("action") == "session.message.new_requirement.accepted"
    )
    assert accepted["trace_context"].trace_id == result.run.trace_id
    assert accepted["trace_context"].request_id == trace_context.request_id
    assert accepted["trace_context"].correlation_id == trace_context.correlation_id


def test_session_service_start_run_from_new_requirement_rolls_back_when_success_audit_fails(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = FailingCommandResultAuditService(
        fail_action="session.message.new_requirement"
    )
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            with pytest.raises(SessionServiceError) as exc_info:
                SessionService(
                    control_session,
                    runtime_session=runtime_session,
                    event_session=event_session,
                    graph_session=graph_session,
                    audit_service=audit,
                    log_writer=log_writer,
                    environment_settings=settings,
                    now=lambda: NOW,
                ).start_run_from_new_requirement(
                    session_id=draft.session_id,
                    content="Implement workspace projection startup.",
                    trace_context=build_trace(),
                )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, draft.session_id)
        assert saved_session is not None
        assert saved_session.status is SessionStatus.DRAFT
        assert saved_session.current_run_id is None
        assert saved_session.latest_stage_type is None

    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(PipelineRunModel).count() == 0
        assert session.query(StageRunModel).count() == 0

    with manager.session(DatabaseRole.GRAPH) as session:
        assert session.query(GraphDefinitionModel).count() == 0
        assert session.query(GraphThreadModel).count() == 0

    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_session_service_start_run_from_new_requirement_rejects_started_session(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        draft.status = SessionStatus.RUNNING
        draft.current_run_id = "run-existing"
        draft.latest_stage_type = StageType.REQUIREMENT_ANALYSIS
        control_session.add(draft)
        control_session.commit()

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            service = SessionService(
                control_session,
                runtime_session=runtime_session,
                event_session=event_session,
                graph_session=graph_session,
                audit_service=audit,
                log_writer=log_writer,
                environment_settings=settings,
                now=lambda: NOW,
            )
            with pytest.raises(SessionServiceError) as exc_info:
                service.start_run_from_new_requirement(
                    session_id=draft.session_id,
                    content="Second requirement.",
                    trace_context=build_trace(),
                )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code.value == "validation_error"
    assert "draft" in exc_info.value.message
    assert "current_run_id" in exc_info.value.message

    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(PipelineRunModel).count() == 0
        assert session.query(StageRunModel).count() == 0
    with manager.session(DatabaseRole.GRAPH) as session:
        assert session.query(GraphDefinitionModel).count() == 0
        assert session.query(GraphThreadModel).count() == 0
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_session_service_start_run_from_new_requirement_respects_injected_credential_env_prefixes(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    settings = build_settings(tmp_path).model_copy(
        update={
            "credential_env_prefixes": (
                "TEAM_PROVIDER_",
                "OPENAI_",
                "DEEPSEEK_",
                "VOLCENGINE_",
            )
        }
    )
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        control_session.add(_build_team_provider())
        team_template = _create_user_template_with_provider(
            control_session,
            template_id="template-team-provider",
            provider_id="provider-team",
        )
        control_session.add(team_template)
        control_session.commit()

        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        draft.selected_template_id = team_template.template_id
        draft.updated_at = NOW
        control_session.add(draft)
        control_session.commit()

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            result = SessionService(
                control_session,
                runtime_session=runtime_session,
                event_session=event_session,
                graph_session=graph_session,
                audit_service=audit,
                log_writer=log_writer,
                environment_settings=settings,
                now=lambda: NOW,
            ).start_run_from_new_requirement(
                session_id=draft.session_id,
                content="Use the team provider for startup.",
                trace_context=build_trace(),
            )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert result.run.run_id

    with manager.session(DatabaseRole.RUNTIME) as session:
        snapshots = (
            session.query(ProviderSnapshotModel)
            .filter(ProviderSnapshotModel.run_id == result.run.run_id)
            .all()
        )

    assert any(snapshot.provider_id == "provider-team" for snapshot in snapshots)


def test_session_service_start_run_from_new_requirement_calls_prompt_validation_hook_once(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()
    prompt_validation = RecordingRunPromptValidationService()
    request_trace = build_trace()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=request_trace,
        )

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            result = SessionService(
                control_session,
                runtime_session=runtime_session,
                event_session=event_session,
                graph_session=graph_session,
                audit_service=audit,
                log_writer=log_writer,
                environment_settings=settings,
                prompt_validation_service=prompt_validation,
                now=lambda: NOW,
            ).start_run_from_new_requirement(
                session_id=draft.session_id,
                content="Implement workspace projection startup.",
                trace_context=request_trace,
            )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert len(prompt_validation.calls) == 1
    call = prompt_validation.calls[0]
    assert call["template_snapshot"].run_id == result.run.run_id
    assert call["trace_context"].run_id == result.run.run_id
    assert call["trace_context"].trace_id == result.run.trace_id
    assert call["trace_context"].request_id == request_trace.request_id
    assert call["trace_context"].correlation_id == request_trace.correlation_id


def test_session_service_start_run_from_new_requirement_rolls_back_when_prompt_validation_hook_rejects(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()
    prompt_validation = RecordingRunPromptValidationService(
        fail_message="Pipeline template prompt validation failed."
    )

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            with pytest.raises(SessionServiceError) as exc_info:
                SessionService(
                    control_session,
                    runtime_session=runtime_session,
                    event_session=event_session,
                    graph_session=graph_session,
                    audit_service=audit,
                    log_writer=log_writer,
                    environment_settings=settings,
                    prompt_validation_service=prompt_validation,
                    now=lambda: NOW,
                ).start_run_from_new_requirement(
                    session_id=draft.session_id,
                    content="Implement workspace projection startup.",
                    trace_context=build_trace(),
                )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert len(prompt_validation.calls) == 1

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, draft.session_id)
        assert saved_session is not None
        assert saved_session.status is SessionStatus.DRAFT
        assert saved_session.current_run_id is None

    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(PipelineRunModel).count() == 0
        assert session.query(StageRunModel).count() == 0

    with manager.session(DatabaseRole.GRAPH) as session:
        assert session.query(GraphDefinitionModel).count() == 0
        assert session.query(GraphThreadModel).count() == 0

    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_session_service_start_run_from_new_requirement_maps_default_prompt_validation_rejection_to_422(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        template = control_session.get(PipelineTemplateModel, draft.selected_template_id)
        assert template is not None
        bindings = list(template.stage_role_bindings)
        bindings[0] = {**bindings[0], "system_prompt": "   "}
        template.stage_role_bindings = bindings
        template.updated_at = NOW
        control_session.add(template)
        control_session.commit()

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            with pytest.raises(SessionServiceError) as exc_info:
                SessionService(
                    control_session,
                    runtime_session=runtime_session,
                    event_session=event_session,
                    graph_session=graph_session,
                    audit_service=audit,
                    log_writer=log_writer,
                    environment_settings=settings,
                    now=lambda: NOW,
                ).start_run_from_new_requirement(
                    session_id=draft.session_id,
                    content="Implement workspace projection startup.",
                    trace_context=build_trace(),
                )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR


def test_session_service_start_run_from_new_requirement_writes_rejected_runtime_log(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=RecordingLogWriter(),
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        draft.status = SessionStatus.RUNNING
        draft.current_run_id = "run-existing"
        draft.latest_stage_type = StageType.REQUIREMENT_ANALYSIS
        control_session.add(draft)
        control_session.commit()

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            with pytest.raises(SessionServiceError):
                SessionService(
                    control_session,
                    runtime_session=runtime_session,
                    event_session=event_session,
                    graph_session=graph_session,
                    audit_service=audit,
                    log_writer=log_writer,
                    environment_settings=settings,
                    now=lambda: NOW,
                ).start_run_from_new_requirement(
                    session_id=draft.session_id,
                    content="Second requirement.",
                    trace_context=build_trace(),
                )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    rows = collect_runtime_log_rows(settings)
    assert any(
        row["payload_type"] == "run_start_rejected"
        and row["session_id"] == draft.session_id
        for row in rows
    )


def test_session_service_start_run_from_new_requirement_writes_failed_runtime_log(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = FailingCommandResultAuditService(
        fail_action="session.message.new_requirement"
    )
    log_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=RecordingLogWriter(),
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            with pytest.raises(SessionServiceError):
                SessionService(
                    control_session,
                    runtime_session=runtime_session,
                    event_session=event_session,
                    graph_session=graph_session,
                    audit_service=audit,
                    log_writer=log_writer,
                    environment_settings=settings,
                    now=lambda: NOW,
                ).start_run_from_new_requirement(
                    session_id=draft.session_id,
                    content="Implement workspace projection startup.",
                    trace_context=build_trace(),
                )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    rows = collect_runtime_log_rows(settings)
    assert any(
        row["payload_type"] == "run_start_failed"
        and row["session_id"] == draft.session_id
        for row in rows
    )


def test_session_service_start_run_from_new_requirement_cleans_up_partial_startup_commit_failure(
    tmp_path: Path,
) -> None:
    from backend.app.services.projections.workspace import WorkspaceProjectionService
    from backend.app.services.sessions import SessionService, SessionServiceError

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            original_control_commit = control_session.commit

            def failing_control_commit() -> None:
                if runtime_session.query(PipelineRunModel).count() > 0:
                    raise RuntimeError("control publish unavailable")
                original_control_commit()

            control_session.commit = failing_control_commit  # type: ignore[method-assign]

            with pytest.raises(SessionServiceError) as exc_info:
                SessionService(
                    control_session,
                    runtime_session=runtime_session,
                    event_session=event_session,
                    graph_session=graph_session,
                    audit_service=audit,
                    log_writer=log_writer,
                    environment_settings=settings,
                    now=lambda: NOW,
                ).start_run_from_new_requirement(
                    session_id=draft.session_id,
                    content="Implement workspace projection startup.",
                    trace_context=build_trace(),
                )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, draft.session_id)
        assert saved_session is not None
        assert saved_session.status is SessionStatus.DRAFT
        assert saved_session.current_run_id is None
        assert saved_session.latest_stage_type is None
        publication = (
            session.query(StartupPublicationModel)
            .filter(StartupPublicationModel.session_id == draft.session_id)
            .one_or_none()
        )
        assert publication is not None
        assert publication.publication_state == "aborted"

    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(PipelineRunModel).count() == 0
        assert session.query(StageRunModel).count() == 0

    with manager.session(DatabaseRole.GRAPH) as session:
        assert session.query(GraphDefinitionModel).count() == 0
        assert session.query(GraphThreadModel).count() == 0

    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        workspace = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_session_workspace(draft.session_id)

    assert workspace.session.status is SessionStatus.DRAFT
    assert workspace.runs == []
    assert workspace.narrative_feed == []


def test_run_lifecycle_start_first_run_rejects_stale_session_after_concurrent_claim(
    tmp_path: Path,
) -> None:
    from backend.app.services.runs import RunLifecycleService, RunLifecycleServiceError
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService
    from backend.app.services.sessions import SessionService

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )
        _ = draft.status
        template = control_session.get(PipelineTemplateModel, draft.selected_template_id)
        assert template is not None
        control_session.expunge(draft)

        with manager.session(DatabaseRole.CONTROL) as competing_session:
            claimed = competing_session.get(SessionModel, draft.session_id)
            assert claimed is not None
            claimed.status = SessionStatus.RUNNING
            claimed.current_run_id = "run-existing"
            claimed.latest_stage_type = StageType.REQUIREMENT_ANALYSIS
            competing_session.add(claimed)
            competing_session.commit()

        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            service = RunLifecycleService(
                control_session=control_session,
                runtime_session=runtime_session,
                event_session=event_session,
                graph_session=graph_session,
                audit_service=audit,
                log_writer=log_writer,
                now=lambda: NOW,
            )
            with pytest.raises(RunLifecycleServiceError) as exc_info:
                service.start_first_run(
                    session=draft,
                    template=template,
                    content="Implement workspace projection startup.",
                    trace_context=build_trace(),
                    runtime_settings_service=PlatformRuntimeSettingsService(
                        control_session,
                        audit_service=audit,
                        log_writer=log_writer,
                        now=lambda: NOW,
                    ),
                )
        finally:
            runtime_session.close()
            event_session.close()
            graph_session.close()

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, draft.session_id)
        assert saved_session is not None
        assert saved_session.status is SessionStatus.RUNNING
        assert saved_session.current_run_id == "run-existing"

    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(PipelineRunModel).count() == 0
        assert session.query(StageRunModel).count() == 0

    with manager.session(DatabaseRole.GRAPH) as session:
        assert session.query(GraphDefinitionModel).count() == 0
        assert session.query(GraphThreadModel).count() == 0

    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_session_service_start_run_from_new_requirement_rejects_true_simultaneous_startup(
    tmp_path: Path,
) -> None:
    from backend.app.services.sessions import SessionService, SessionServiceError

    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    blocking_validation = BlockingRunPromptValidationService()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
        )
        draft = SessionService(
            control_session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )

    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}

    def start_run(name: str, prompt_validation_service: Any) -> None:
        control_session = manager.session(DatabaseRole.CONTROL)
        runtime_session = manager.session(DatabaseRole.RUNTIME)
        event_session = manager.session(DatabaseRole.EVENT)
        graph_session = manager.session(DatabaseRole.GRAPH)
        try:
            results[name] = SessionService(
                control_session,
                runtime_session=runtime_session,
                event_session=event_session,
                graph_session=graph_session,
                audit_service=RecordingAuditService(),
                log_writer=RecordingLogWriter(),
                environment_settings=settings,
                prompt_validation_service=prompt_validation_service,
                now=lambda: NOW,
            ).start_run_from_new_requirement(
                session_id=draft.session_id,
                content=f"Implement startup path from {name}.",
                trace_context=build_trace(),
            )
        except BaseException as exc:  # noqa: BLE001
            errors[name] = exc
        finally:
            control_session.close()
            runtime_session.close()
            event_session.close()
            graph_session.close()

    first = threading.Thread(
        target=start_run,
        args=("first", blocking_validation),
    )
    first.start()
    assert blocking_validation.first_call_entered.wait(timeout=5)

    second = threading.Thread(
        target=start_run,
        args=("second", RecordingRunPromptValidationService()),
    )
    second.start()

    blocking_validation.release_first_call.set()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert "first" in results
    assert "second" in errors
    assert isinstance(errors["second"], SessionServiceError)
    second_error = errors["second"]
    assert second_error.status_code == 409
    assert second_error.error_code is ErrorCode.VALIDATION_ERROR

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, draft.session_id)
        assert saved_session is not None
        assert saved_session.status is SessionStatus.RUNNING
        assert saved_session.current_run_id == results["first"].run.run_id
        assert saved_session.latest_stage_type is StageType.REQUIREMENT_ANALYSIS

    with manager.session(DatabaseRole.RUNTIME) as session:
        runs = (
            session.query(PipelineRunModel)
            .filter(PipelineRunModel.session_id == draft.session_id)
            .all()
        )
        assert len(runs) == 1
        assert session.query(StageRunModel).count() == 1

    with manager.session(DatabaseRole.GRAPH) as session:
        assert session.query(GraphDefinitionModel).count() == 1
        assert session.query(GraphThreadModel).count() == 1

    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 4
