import pytest
from fastapi.testclient import TestClient

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase
from backend.app.db.models.log import LogBase
from backend.app.main import create_app
from backend.app.observability.runtime_data import (
    RuntimeDataPreflight,
    RuntimeDataPreflightError,
    RuntimeDataSettings,
)


def create_control_and_log_tables(app) -> None:  # noqa: ANN001
    ControlBase.metadata.create_all(
        app.state.database_manager.engine(DatabaseRole.CONTROL)
    )
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))


def test_runtime_data_settings_derive_log_paths_from_environment_settings(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    settings = EnvironmentSettings(platform_runtime_root=runtime_root)

    runtime_settings = RuntimeDataSettings.from_environment_settings(settings)

    assert runtime_settings.root == runtime_root.resolve()
    assert runtime_settings.logs_dir == (runtime_root / "logs").resolve()
    assert runtime_settings.run_logs_dir == (runtime_root / "logs" / "runs").resolve()


def test_logs_dir_is_marked_as_platform_private_without_marking_workspace(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_settings = RuntimeDataSettings.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=runtime_root)
    )

    assert runtime_settings.is_platform_private_path(runtime_root / "logs" / "app.jsonl")
    assert runtime_settings.is_platform_private_path(runtime_root / "logs" / "runs" / "run-1.jsonl")
    assert not runtime_settings.is_platform_private_path(runtime_root / "workspaces" / "project")


def test_preflight_resolves_logs_dir_from_runtime_settings(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    preflight = RuntimeDataPreflight.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=runtime_root)
    )

    assert preflight.resolve_logs_dir() == (runtime_root / "logs").resolve()


def test_preflight_creates_runtime_log_directories_and_checks_writability(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    preflight = RuntimeDataPreflight.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=runtime_root)
    )

    runtime_settings = preflight.ensure_runtime_data_ready()

    assert runtime_settings.root.is_dir()
    assert runtime_settings.logs_dir.is_dir()
    assert runtime_settings.run_logs_dir.is_dir()
    preflight.assert_writable(runtime_settings.root)
    preflight.assert_writable(runtime_settings.logs_dir)
    preflight.assert_writable(runtime_settings.run_logs_dir)


def test_preflight_fails_when_runtime_root_path_is_a_file(tmp_path) -> None:
    runtime_root = tmp_path / "runtime-file"
    runtime_root.write_text("not a directory", encoding="utf-8")
    preflight = RuntimeDataPreflight.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=runtime_root)
    )

    with pytest.raises(RuntimeDataPreflightError) as exc_info:
        preflight.ensure_runtime_data_ready()

    assert exc_info.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert exc_info.value.path == runtime_root.resolve()
    assert "not a directory" in str(exc_info.value)


def test_preflight_fails_when_logs_path_is_a_file(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    logs_path = runtime_root / "logs"
    logs_path.write_text("not a directory", encoding="utf-8")
    preflight = RuntimeDataPreflight.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=runtime_root)
    )

    with pytest.raises(RuntimeDataPreflightError) as exc_info:
        preflight.ensure_runtime_data_ready()

    assert exc_info.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert exc_info.value.path == logs_path.resolve()
    assert "not a directory" in str(exc_info.value)


def test_preflight_fails_when_writability_probe_cannot_write(monkeypatch, tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    preflight = RuntimeDataPreflight.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=runtime_root)
    )

    def fail_write_text(self, data, encoding=None):  # noqa: ANN001
        raise OSError("write blocked")

    monkeypatch.setattr("pathlib.Path.write_text", fail_write_text)

    with pytest.raises(RuntimeDataPreflightError) as exc_info:
        preflight.assert_writable(runtime_root)

    assert exc_info.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert exc_info.value.path == runtime_root.resolve()
    assert "not writable" in str(exc_info.value)


def test_fastapi_lifespan_runs_preflight_before_serving_requests(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    app = create_app(settings=EnvironmentSettings(platform_runtime_root=runtime_root))
    create_control_and_log_tables(app)

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert (runtime_root / "logs").is_dir()
    assert (runtime_root / "logs" / "runs").is_dir()


def test_fastapi_lifespan_initializes_schema_before_startup_seed(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    default_project_root = tmp_path / "ai-devflow-engine"
    default_project_root.mkdir()
    app = create_app(
        settings=EnvironmentSettings(
            platform_runtime_root=runtime_root,
            default_project_root=default_project_root,
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/projects")

    assert response.status_code == 200
    assert response.json()[0]["project_id"] == "project-default"


def test_fastapi_lifespan_fails_when_runtime_data_is_unavailable(tmp_path) -> None:
    runtime_root = tmp_path / "runtime-file"
    runtime_root.write_text("not a directory", encoding="utf-8")
    app = create_app(settings=EnvironmentSettings(platform_runtime_root=runtime_root))

    with pytest.raises(RuntimeDataPreflightError):
        with TestClient(app):
            pass


def test_environment_settings_do_not_gain_log_or_database_path_fields() -> None:
    forbidden_fields = {
        "logs_dir",
        "run_logs_dir",
        "app_log_path",
        "audit_log_path",
        "log_retention_days",
        "log_query_limit",
        "control_database_url",
        "runtime_database_url",
        "graph_database_url",
        "event_database_url",
        "log_database_url",
    }

    assert forbidden_fields.isdisjoint(EnvironmentSettings.model_fields)
