from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import FeedEntryType, SseEventType, StageStatus, StageType
from backend.app.schemas.events import SessionEvent


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EVENT_TABLES = {"domain_events"}
FORBIDDEN_EVENT_TABLES = {
    "projects",
    "sessions",
    "pipeline_templates",
    "providers",
    "delivery_channels",
    "platform_runtime_settings",
    "pipeline_runs",
    "stage_runs",
    "stage_artifacts",
    "approval_requests",
    "approval_decisions",
    "tool_confirmation_requests",
    "delivery_records",
    "graph_definitions",
    "graph_threads",
    "graph_checkpoints",
    "graph_interrupts",
    "run_log_entries",
    "audit_log_entries",
    "log_payloads",
    "feed_entries",
    "inspector_projections",
}


def enum_values(enum_type: type) -> list[str]:
    return [item.value for item in enum_type]


def _stage_updated_payload() -> dict[str, object]:
    return {
        "stage_node": {
            "entry_id": "feed-stage-1",
            "run_id": "run-1",
            "type": FeedEntryType.STAGE_NODE.value,
            "occurred_at": NOW.isoformat(),
            "stage_run_id": "stage-run-1",
            "stage_type": StageType.REQUIREMENT_ANALYSIS.value,
            "status": StageStatus.RUNNING.value,
            "attempt_index": 1,
            "started_at": NOW.isoformat(),
            "ended_at": None,
            "summary": "Analyzing the initial requirement.",
            "items": [],
            "metrics": {"duration_ms": 1200, "token_count": 42},
        }
    }


def test_event_models_register_only_event_role_metadata() -> None:
    from backend.app.db.models.event import DomainEventModel, EventBase

    assert EventBase.metadata is ROLE_METADATA[DatabaseRole.EVENT]
    assert {table.name for table in EventBase.metadata.sorted_tables} == EVENT_TABLES
    assert FORBIDDEN_EVENT_TABLES.isdisjoint(EventBase.metadata.tables)
    assert DomainEventModel.metadata is ROLE_METADATA[DatabaseRole.EVENT]

    for role in (
        DatabaseRole.CONTROL,
        DatabaseRole.RUNTIME,
        DatabaseRole.GRAPH,
        DatabaseRole.LOG,
    ):
        assert EVENT_TABLES.isdisjoint(ROLE_METADATA[role].tables)


def test_event_tables_create_only_in_event_database(tmp_path) -> None:
    from backend.app.db.models.event import EventBase

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))

    with manager.session(DatabaseRole.EVENT) as session:
        event_tables = set(inspect(session.bind).get_table_names())

    assert EVENT_TABLES.issubset(event_tables)
    assert FORBIDDEN_EVENT_TABLES.isdisjoint(event_tables)

    for role in (
        DatabaseRole.CONTROL,
        DatabaseRole.RUNTIME,
        DatabaseRole.GRAPH,
        DatabaseRole.LOG,
    ):
        with manager.session(role) as session:
            assert EVENT_TABLES.isdisjoint(inspect(session.bind).get_table_names())


def test_alembic_env_imports_event_models_for_metadata_loading() -> None:
    alembic_env = Path("backend/alembic/env.py").read_text(encoding="utf-8")

    assert "import backend.app.db.models.event  # noqa: F401" in alembic_env


def test_domain_event_model_stores_projection_source_payload_without_log_or_graph_state(
    tmp_path,
) -> None:
    from backend.app.db.models.event import DomainEventModel, EventBase

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))

    payload = _stage_updated_payload()
    with manager.session(DatabaseRole.EVENT) as session:
        event = DomainEventModel(
            event_id="event-stage-updated-1",
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            event_type=SseEventType.STAGE_UPDATED,
            sequence_index=1,
            occurred_at=NOW,
            payload=payload,
            correlation_id="correlation-1",
            causation_event_id=None,
            created_at=NOW,
        )
        session.add(event)
        session.commit()

        saved_event = session.get(DomainEventModel, "event-stage-updated-1")

    assert saved_event is not None
    assert saved_event.session_id == "session-1"
    assert saved_event.run_id == "run-1"
    assert saved_event.stage_run_id == "stage-run-1"
    assert saved_event.event_type is SseEventType.STAGE_UPDATED
    assert saved_event.sequence_index == 1
    assert saved_event.payload["stage_node"]["type"] == FeedEntryType.STAGE_NODE.value
    assert saved_event.correlation_id == "correlation-1"

    reconstructed = SessionEvent(
        event_id=saved_event.event_id,
        session_id=saved_event.session_id,
        run_id=saved_event.run_id,
        event_type=saved_event.event_type,
        occurred_at=saved_event.occurred_at,
        payload=saved_event.payload,
    )
    assert reconstructed.payload["stage_node"]["stage_run_id"] == "stage-run-1"

    columns = set(DomainEventModel.__table__.columns.keys())
    assert {
        "event_id",
        "session_id",
        "run_id",
        "stage_run_id",
        "event_type",
        "sequence_index",
        "occurred_at",
        "payload",
        "correlation_id",
        "causation_event_id",
        "created_at",
    }.issubset(columns)
    assert {
        "audit_id",
        "audit_payload",
        "audit_log_ref",
        "run_log_id",
        "log_payload",
        "log_file_ref",
        "line_offset",
        "line_number",
        "graph_thread_id",
        "graph_checkpoint_id",
        "raw_graph_state",
        "raw_node_event",
        "raw_tool_event",
        "raw_model_event",
        "inspector_payload",
    }.isdisjoint(columns)


def test_domain_event_type_uses_existing_sse_contract_values() -> None:
    from backend.app.db.models.event import DomainEventModel

    event_type = DomainEventModel.__table__.columns["event_type"].type

    assert event_type.enums == enum_values(SseEventType)
    assert "raw_langgraph_event" not in event_type.enums
    assert "run_log_entry" not in event_type.enums
    assert "audit_log_entry" not in event_type.enums
