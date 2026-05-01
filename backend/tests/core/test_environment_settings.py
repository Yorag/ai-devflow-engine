import json

from backend.app.core.config import EnvironmentSettings
from backend.tests.support.settings import override_environment_settings


def test_environment_settings_loads_startup_values_from_environment(monkeypatch, tmp_path) -> None:
    runtime_root = tmp_path / "runtime-env"
    workspace_root = tmp_path / "workspace-env"
    project_root = tmp_path / "project-env"

    monkeypatch.setenv("AI_DEVFLOW_PLATFORM_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("AI_DEVFLOW_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AI_DEVFLOW_DEFAULT_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv(
        "AI_DEVFLOW_BACKEND_CORS_ORIGINS",
        json.dumps(["http://localhost:5173", "http://127.0.0.1:5173"]),
    )
    monkeypatch.setenv("AI_DEVFLOW_FRONTEND_API_BASE_URL", "http://localhost:5173/api")
    monkeypatch.setenv(
        "AI_DEVFLOW_CREDENTIAL_ENV_PREFIXES",
        json.dumps(["CUSTOM_", "OPENAI_"]),
    )

    settings = EnvironmentSettings()

    assert settings.resolve_platform_runtime_root() == runtime_root.resolve()
    assert settings.resolve_workspace_root() == workspace_root.resolve()
    assert settings.default_project_root == project_root
    assert settings.backend_cors_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    assert settings.frontend_api_base_url == "http://localhost:5173/api"
    assert settings.credential_env_prefixes == ("CUSTOM_", "OPENAI_")


def test_workspace_root_defaults_under_platform_runtime_root(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"

    settings = EnvironmentSettings(platform_runtime_root=runtime_root)

    assert settings.resolve_platform_runtime_root() == runtime_root.resolve()
    assert settings.resolve_workspace_root() == (runtime_root / "workspaces").resolve()


def test_platform_runtime_root_defaults_to_current_working_directory(monkeypatch, tmp_path) -> None:
    service_root = tmp_path / "service"
    service_root.mkdir()
    monkeypatch.chdir(service_root)

    settings = EnvironmentSettings()

    assert settings.resolve_platform_runtime_root() == (service_root / ".runtime").resolve()


def test_explicit_workspace_root_is_resolved_without_using_business_config(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    workspace_root = tmp_path / "workspace"

    settings = EnvironmentSettings(
        platform_runtime_root=runtime_root,
        workspace_root=workspace_root,
    )

    assert settings.resolve_workspace_root() == workspace_root.resolve()


def test_credential_env_names_must_match_allowed_prefixes() -> None:
    settings = EnvironmentSettings(credential_env_prefixes=("CUSTOM_", "OPENAI_"))

    assert settings.is_allowed_credential_env_name("CUSTOM_TOKEN")
    assert settings.is_allowed_credential_env_name("OPENAI_API_KEY")
    assert not settings.is_allowed_credential_env_name("PATH")
    assert not settings.is_allowed_credential_env_name("")
    assert not settings.is_allowed_credential_env_name("env:CUSTOM_TOKEN")


def test_default_credential_prefixes_do_not_allow_startup_setting_names() -> None:
    settings = EnvironmentSettings()

    assert settings.is_allowed_credential_env_name("AI_DEVFLOW_CREDENTIAL_OPENAI_API_KEY")
    assert not settings.is_allowed_credential_env_name("AI_DEVFLOW_PLATFORM_RUNTIME_ROOT")


def test_environment_settings_do_not_contain_business_runtime_or_prompt_fields() -> None:
    forbidden_fields = {
        "provider_base_url",
        "provider_model_id",
        "model_id",
        "context_window_tokens",
        "max_output_tokens",
        "supports_tool_calling",
        "supports_structured_output",
        "supports_native_reasoning",
        "delivery_mode",
        "repository_identifier",
        "target_branch",
        "code_review_request_type",
        "max_react_iterations_per_stage",
        "max_tool_calls_per_stage",
        "log_retention_days",
        "compression_threshold_ratio",
        "compression_prompt",
        "prompt_id",
        "prompt_version",
        "system_prompt",
        "deterministic_test_runtime",
        "control_database_url",
        "runtime_database_url",
        "graph_database_url",
        "event_database_url",
        "log_database_url",
    }

    assert forbidden_fields.isdisjoint(EnvironmentSettings.model_fields)


def test_override_environment_settings_is_test_only_constructor(tmp_path) -> None:
    runtime_root = tmp_path / "override-runtime"

    settings = override_environment_settings(platform_runtime_root=runtime_root)

    assert isinstance(settings, EnvironmentSettings)
    assert settings.resolve_platform_runtime_root() == runtime_root.resolve()
