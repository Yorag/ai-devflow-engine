from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


APP_TITLE = "AI DevFlow Engine API"
API_PREFIX = "/api"
OPENAPI_URL = f"{API_PREFIX}/openapi.json"
DOCS_URL = f"{API_PREFIX}/docs"
SERVICE_NAME = "ai-devflow-engine"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_platform_runtime_root() -> Path:
    return Path.cwd() / ".runtime"


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_DEVFLOW_",
        extra="ignore",
    )

    platform_runtime_root: Path = Field(default_factory=_default_platform_runtime_root)
    default_project_root: Path = _repo_root()
    workspace_root: Path | None = None
    backend_cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    frontend_api_base_url: str = "http://localhost:8000/api"
    credential_env_prefixes: tuple[str, ...] = (
        "AI_DEVFLOW_CREDENTIAL_",
        "OPENAI_",
        "DEEPSEEK_",
        "VOLCENGINE_",
    )

    @field_validator("credential_env_prefixes", mode="after")
    @classmethod
    def remove_blank_credential_prefixes(cls, prefixes: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(prefix.strip() for prefix in prefixes if prefix.strip())

    def resolve_platform_runtime_root(self) -> Path:
        return self.platform_runtime_root.expanduser().resolve()

    def resolve_workspace_root(self) -> Path:
        if self.workspace_root is None:
            return (self.resolve_platform_runtime_root() / "workspaces").resolve()
        return self.workspace_root.expanduser().resolve()

    def is_allowed_credential_env_name(self, name: str) -> bool:
        if not name:
            return False
        return any(name.startswith(prefix) for prefix in self.credential_env_prefixes)
