from pathlib import Path


def test_backend_app_is_file_backed_package() -> None:
    import backend.app as app_package

    package_file = Path(app_package.__file__ or "")

    assert package_file.name == "__init__.py"
    assert app_package.__version__ == "0.1.0"


def test_production_api_routes_do_not_define_in_memory_runtime_ports() -> None:
    route_files = (
        Path("backend/app/api/routes/sessions.py"),
        Path("backend/app/api/routes/runs.py"),
        Path("backend/app/api/routes/tool_confirmations.py"),
    )

    for route_file in route_files:
        source = route_file.read_text(encoding="utf-8")
        assert "InMemoryRuntimeCommandPort" not in source
        assert "InMemoryCheckpointPort" not in source
