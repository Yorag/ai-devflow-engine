from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DATABASE_FILE_NAMES, DatabaseRole


def _sqlite_url_for_path(path: Path) -> str:
    resolved = path.expanduser().resolve(strict=False)
    return f"sqlite:///{resolved.as_posix()}"


def _enable_sqlite_foreign_keys(
    dbapi_connection: Any,
    _connection_record: Any,
) -> None:
    original_autocommit = getattr(dbapi_connection, "autocommit", None)
    if original_autocommit is not None:
        dbapi_connection.autocommit = True

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
        if original_autocommit is not None:
            dbapi_connection.autocommit = original_autocommit


def enable_sqlite_foreign_key_enforcement(engine: Engine) -> None:
    if engine.url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)


@dataclass
class DatabaseManager:
    _database_paths: dict[DatabaseRole, Path]
    _database_urls: dict[DatabaseRole, str]
    _engines: dict[DatabaseRole, Engine] = field(default_factory=dict, init=False)
    _session_factories: dict[DatabaseRole, sessionmaker[Session]] = field(
        default_factory=dict,
        init=False,
    )

    @classmethod
    def from_environment_settings(cls, settings: EnvironmentSettings) -> "DatabaseManager":
        runtime_root = settings.resolve_platform_runtime_root()
        paths = {
            role: (runtime_root / file_name).resolve(strict=False)
            for role, file_name in DATABASE_FILE_NAMES.items()
        }
        urls = {role: _sqlite_url_for_path(path) for role, path in paths.items()}
        return cls(paths, urls)

    def database_paths(self) -> dict[DatabaseRole, Path]:
        return dict(self._database_paths)

    def database_path(self, role: DatabaseRole) -> Path:
        return self._database_paths[role]

    def database_url(self, role: DatabaseRole) -> str:
        return self._database_urls[role]

    def engine(self, role: DatabaseRole) -> Engine:
        if role not in self._engines:
            url = self._database_urls[role]
            database_path = Path(make_url(url).database or "")
            database_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                url,
                connect_args={"check_same_thread": False},
            )
            enable_sqlite_foreign_key_enforcement(engine)
            self._engines[role] = engine
        return self._engines[role]

    def session_factory(self, role: DatabaseRole) -> sessionmaker[Session]:
        if role not in self._session_factories:
            self._session_factories[role] = sessionmaker(
                bind=self.engine(role),
                autoflush=False,
                expire_on_commit=False,
            )
        return self._session_factories[role]

    def session(self, role: DatabaseRole) -> Session:
        return self.session_factory(role)()


_default_database_manager: DatabaseManager | None = None


def get_database_manager() -> DatabaseManager:
    global _default_database_manager
    if _default_database_manager is None:
        _default_database_manager = DatabaseManager.from_environment_settings(EnvironmentSettings())
    return _default_database_manager


def _session_for(role: DatabaseRole, manager: DatabaseManager | None = None) -> Session:
    return (manager or get_database_manager()).session(role)


def get_control_session(manager: DatabaseManager | None = None) -> Session:
    return _session_for(DatabaseRole.CONTROL, manager)


def get_runtime_session(manager: DatabaseManager | None = None) -> Session:
    return _session_for(DatabaseRole.RUNTIME, manager)


def get_graph_session(manager: DatabaseManager | None = None) -> Session:
    return _session_for(DatabaseRole.GRAPH, manager)


def get_event_session(manager: DatabaseManager | None = None) -> Session:
    return _session_for(DatabaseRole.EVENT, manager)


def get_log_session(manager: DatabaseManager | None = None) -> Session:
    return _session_for(DatabaseRole.LOG, manager)
