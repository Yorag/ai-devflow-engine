from pathlib import Path
from typing import Any

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager


def override_environment_settings(**values: Any) -> EnvironmentSettings:
    return EnvironmentSettings(**values)


def runtime_database_paths_fixture(tmp_path: Path) -> dict[DatabaseRole, Path]:
    settings = override_environment_settings(platform_runtime_root=tmp_path / "runtime")
    return DatabaseManager.from_environment_settings(settings).database_paths()
