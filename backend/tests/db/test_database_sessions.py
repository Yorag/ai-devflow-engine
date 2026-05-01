from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import insert, inspect, text
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DATABASE_FILE_NAMES, ROLE_METADATA, DatabaseRole
from backend.app.db.session import (
    DatabaseManager,
    get_control_session,
    get_event_session,
    get_graph_session,
    get_log_session,
    get_runtime_session,
)
from backend.tests.support.settings import (
    override_environment_settings,
    runtime_database_paths_fixture,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_database_manager_derives_five_sqlite_paths_from_runtime_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    settings = EnvironmentSettings(platform_runtime_root=runtime_root)

    manager = DatabaseManager.from_environment_settings(settings)

    assert set(manager.database_paths()) == set(DatabaseRole)
    for role in DatabaseRole:
        assert manager.database_path(role) == (runtime_root / DATABASE_FILE_NAMES[role]).resolve()
        assert manager.database_url(role).startswith("sqlite:///")
        assert str(manager.database_path(role)).replace("\\", "/") in manager.database_url(role)


def test_database_sessions_are_bound_to_their_own_role_files(tmp_path: Path) -> None:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )

    helpers = {
        DatabaseRole.CONTROL: get_control_session,
        DatabaseRole.RUNTIME: get_runtime_session,
        DatabaseRole.GRAPH: get_graph_session,
        DatabaseRole.EVENT: get_event_session,
        DatabaseRole.LOG: get_log_session,
    }

    for role, helper in helpers.items():
        with helper(manager) as session:
            session.execute(text(f"create table {role.value}_marker (id integer primary key)"))
            session.commit()
            assert Path(session.bind.url.database).resolve() == manager.database_path(role)

    for role in DatabaseRole:
        with manager.session(role) as session:
            tables = set(inspect(session.bind).get_table_names())
        assert f"{role.value}_marker" in tables
        other_markers = {f"{other.value}_marker" for other in DatabaseRole if other is not role}
        assert tables.isdisjoint(other_markers)


def test_database_sessions_enable_sqlite_foreign_key_enforcement(tmp_path: Path) -> None:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )

    for role in DatabaseRole:
        with manager.session(role) as session:
            assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_sqlite_rejects_orphan_same_database_foreign_keys(tmp_path: Path) -> None:
    from backend.app.db.models.control import ControlBase, SessionModel
    from backend.app.db.models.graph import GraphBase, GraphThreadModel
    from backend.app.db.models.log import LogBase, RunLogEntryModel
    from backend.app.db.models.runtime import RuntimeBase, StageRunModel
    from backend.app.domain.enums import SessionStatus, StageStatus, StageType
    from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    GraphBase.metadata.create_all(manager.engine(DatabaseRole.GRAPH))
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    orphan_insert_cases = [
        (
            DatabaseRole.CONTROL,
            SessionModel.__table__,
            {
                "session_id": "session-orphan",
                "project_id": "missing-project",
                "display_name": "Orphan session",
                "status": SessionStatus.DRAFT,
                "selected_template_id": "missing-template",
                "current_run_id": None,
                "latest_stage_type": None,
                "is_visible": True,
                "visibility_removed_at": None,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ),
        (
            DatabaseRole.RUNTIME,
            StageRunModel.__table__,
            {
                "stage_run_id": "stage-orphan",
                "run_id": "missing-run",
                "stage_type": StageType.REQUIREMENT_ANALYSIS,
                "status": StageStatus.RUNNING,
                "attempt_index": 1,
                "input_ref": None,
                "output_ref": None,
                "summary": None,
                "started_at": NOW,
                "ended_at": None,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ),
        (
            DatabaseRole.GRAPH,
            GraphThreadModel.__table__,
            {
                "graph_thread_id": "graph-thread-orphan",
                "run_id": "run-1",
                "graph_definition_id": "missing-graph-definition",
                "checkpoint_namespace": "run-1-main",
                "current_node_key": "requirement_analysis",
                "current_interrupt_id": None,
                "status": "running",
                "last_checkpoint_ref": None,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ),
        (
            DatabaseRole.LOG,
            RunLogEntryModel.__table__,
            {
                "log_id": "run-log-orphan",
                "session_id": "session-1",
                "run_id": "run-1",
                "stage_run_id": "stage-1",
                "approval_id": None,
                "tool_confirmation_id": None,
                "delivery_record_id": None,
                "graph_thread_id": None,
                "request_id": "request-1",
                "source": "tool.registry",
                "category": LogCategory.TOOL,
                "level": LogLevel.INFO,
                "message": "Orphan payload reference.",
                "log_file_ref": "logs/runs/run-1.jsonl",
                "line_offset": 1,
                "line_number": 1,
                "log_file_generation": "run-1",
                "payload_ref": "missing-payload",
                "payload_excerpt": None,
                "payload_size_bytes": 0,
                "redaction_status": RedactionStatus.NOT_REQUIRED,
                "correlation_id": "correlation-1",
                "trace_id": "trace-1",
                "span_id": "span-1",
                "parent_span_id": None,
                "duration_ms": None,
                "error_code": None,
                "created_at": NOW,
            },
        ),
    ]

    for role, table, values in orphan_insert_cases:
        with manager.session(role) as session:
            with pytest.raises(IntegrityError):
                session.execute(insert(table).values(values))
                session.commit()


def test_log_database_boundary_is_separate_from_event_and_product_state(tmp_path: Path) -> None:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )

    assert manager.database_path(DatabaseRole.LOG).name == "log.db"
    assert manager.database_path(DatabaseRole.EVENT).name == "event.db"
    assert ROLE_METADATA[DatabaseRole.LOG] is not ROLE_METADATA[DatabaseRole.EVENT]
    assert ROLE_METADATA[DatabaseRole.LOG] is not ROLE_METADATA[DatabaseRole.RUNTIME]

    with get_event_session(manager) as event_session:
        event_session.execute(text("create table domain_event_marker (id integer primary key)"))
        event_session.commit()

    with get_log_session(manager) as log_session:
        log_tables = set(inspect(log_session.bind).get_table_names())

    assert "domain_event_marker" not in log_tables


def test_test_runtime_database_paths_use_settings_override_without_env_fields(tmp_path: Path) -> None:
    paths = runtime_database_paths_fixture(tmp_path)

    assert set(paths) == set(DatabaseRole)
    for role, path in paths.items():
        assert path == (tmp_path / "runtime" / DATABASE_FILE_NAMES[role]).resolve()

    settings = override_environment_settings(platform_runtime_root=tmp_path / "runtime")
    assert DatabaseManager.from_environment_settings(settings).database_paths() == paths

    forbidden_fields = {
        "control_database_url",
        "runtime_database_url",
        "graph_database_url",
        "event_database_url",
        "log_database_url",
    }
    assert forbidden_fields.isdisjoint(EnvironmentSettings.model_fields)


def test_alembic_configuration_declares_each_database_role() -> None:
    config = Config("backend/alembic.ini")

    assert config.get_main_option("script_location") == "backend/alembic"
    for role in DatabaseRole:
        section = config.get_section(f"alembic:{role.value}")
        assert section is not None
        assert section["sqlalchemy.url"].endswith(DATABASE_FILE_NAMES[role])
