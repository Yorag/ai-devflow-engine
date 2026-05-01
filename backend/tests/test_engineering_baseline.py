from pathlib import Path


def test_backend_app_is_file_backed_package() -> None:
    import backend.app as app_package

    package_file = Path(app_package.__file__ or "")

    assert package_file.name == "__init__.py"
    assert app_package.__version__ == "0.1.0"
