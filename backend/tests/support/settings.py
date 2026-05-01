from typing import Any

from backend.app.core.config import EnvironmentSettings


def override_environment_settings(**values: Any) -> EnvironmentSettings:
    return EnvironmentSettings(**values)
