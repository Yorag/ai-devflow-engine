from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings


class RuntimeDataPreflightError(RuntimeError):
    def __init__(self, message: str, path: Path) -> None:
        self.error_code = ErrorCode.CONFIG_STORAGE_UNAVAILABLE
        self.path = path.expanduser().resolve(strict=False)
        super().__init__(f"{message}: {self.path}")


@dataclass(frozen=True)
class RuntimeDataSettings:
    root: Path
    logs_dir: Path
    run_logs_dir: Path
    platform_private_roots: tuple[Path, ...]

    @classmethod
    def from_environment_settings(cls, settings: EnvironmentSettings) -> "RuntimeDataSettings":
        root = settings.resolve_platform_runtime_root()
        logs_dir = (root / "logs").resolve()
        return cls(
            root=root,
            logs_dir=logs_dir,
            run_logs_dir=(logs_dir / "runs").resolve(),
            platform_private_roots=(logs_dir,),
        )

    def is_platform_private_path(self, path: Path) -> bool:
        candidate = path.expanduser().resolve(strict=False)
        return any(
            candidate == root or candidate.is_relative_to(root)
            for root in self.platform_private_roots
        )


@dataclass(frozen=True)
class RuntimeDataPreflight:
    settings: RuntimeDataSettings

    @classmethod
    def from_environment_settings(cls, settings: EnvironmentSettings) -> "RuntimeDataPreflight":
        return cls(RuntimeDataSettings.from_environment_settings(settings))

    def resolve_logs_dir(self) -> Path:
        return self.settings.logs_dir

    def ensure_runtime_data_ready(self) -> RuntimeDataSettings:
        for directory in (
            self.settings.root,
            self.settings.logs_dir,
            self.settings.run_logs_dir,
        ):
            self._ensure_directory(directory)
            self.assert_writable(directory)
        return self.settings

    def _ensure_directory(self, directory: Path) -> None:
        if directory.exists() and not directory.is_dir():
            raise RuntimeDataPreflightError("Runtime data path is not a directory", directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeDataPreflightError("Runtime data directory cannot be created", directory) from exc
        if not directory.is_dir():
            raise RuntimeDataPreflightError("Runtime data path is not a directory", directory)

    def assert_writable(self, directory: Path) -> None:
        if not directory.is_dir():
            raise RuntimeDataPreflightError("Runtime data path is not a directory", directory)

        marker_path = directory / f".write-test-{uuid4().hex}.tmp"
        try:
            marker_path.write_text("ok", encoding="utf-8")
        except OSError as exc:
            raise RuntimeDataPreflightError("Runtime data directory is not writable", directory) from exc
        finally:
            marker_path.unlink(missing_ok=True)
