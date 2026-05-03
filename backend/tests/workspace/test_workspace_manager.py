from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app.core.config import EnvironmentSettings
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, LogCategory, LogLevel
from backend.app.tools.execution_gate import ToolWorkspaceBoundaryError
from backend.app.workspace.manager import RunWorkspace, WorkspaceManager, WorkspaceManagerError


NOW = datetime(2026, 5, 3, 18, 0, 0, tzinfo=UTC)


def build_trace(*, run_id: str = "run-1") -> TraceContext:
    return TraceContext(
        request_id="request-workspace-1",
        trace_id="trace-workspace-1",
        correlation_id="correlation-workspace-1",
        span_id="span-workspace-1",
        parent_span_id=None,
        session_id="session-1",
        run_id=run_id,
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records = []

    def write_run_log(self, record) -> object:  # noqa: ANN001
        self.records.append(record)
        return object()


class ExplodingRunLogWriter:
    def write_run_log(self, _record) -> object:  # noqa: ANN001
        raise OSError("run log unavailable")


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record_blocked_action(self, **kwargs: object) -> object:
        self.records.append(dict(kwargs))
        return object()


class ExplodingAuditService:
    def record_blocked_action(self, **_kwargs: object) -> object:
        raise RuntimeError("audit unavailable")


def build_settings(
    tmp_path: Path,
    *,
    runtime_under_project: bool = True,
    workspace_root: Path | None = None,
) -> EnvironmentSettings:
    default_project_root = tmp_path / "repo"
    default_project_root.mkdir(parents=True, exist_ok=True)
    platform_runtime_root = (
        default_project_root / ".runtime"
        if runtime_under_project
        else tmp_path / "service-runtime"
    )
    resolved_workspace_root = workspace_root or (tmp_path / "managed-workspaces")
    return EnvironmentSettings(
        platform_runtime_root=platform_runtime_root,
        default_project_root=default_project_root,
        workspace_root=resolved_workspace_root,
    )


def build_manager(
    tmp_path: Path,
    *,
    runtime_under_project: bool = True,
    workspace_root: Path | None = None,
    log_writer: RecordingRunLogWriter | ExplodingRunLogWriter | None = None,
    audit_service: RecordingAuditService | ExplodingAuditService | None = None,
) -> WorkspaceManager:
    return WorkspaceManager(
        settings=build_settings(
            tmp_path,
            runtime_under_project=runtime_under_project,
            workspace_root=workspace_root,
        ),
        log_writer=log_writer,
        audit_service=audit_service,
        now=lambda: NOW,
    )


def test_create_for_run_creates_workspace_under_resolved_root_and_marks_runtime_logs_excluded(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)

    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    assert isinstance(workspace, RunWorkspace)
    assert workspace.run_id == "run-1"
    assert workspace.workspace_ref == "workspace-1"
    assert workspace.root == (tmp_path / "managed-workspaces" / "workspace-1").resolve()
    assert workspace.root.is_dir()
    assert workspace.excluded_relative_paths == (".runtime/logs",)


def test_create_for_run_recreates_clean_workspace_when_stale_contents_exist(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )
    stale_file = workspace.root / "stale.txt"
    stale_file.write_text("old", encoding="ascii")

    recreated = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    assert recreated.root == workspace.root
    assert recreated.root.is_dir()
    assert not stale_file.exists()
    assert list(recreated.root.iterdir()) == []


def test_get_run_workspace_returns_existing_workspace_and_missing_lookup_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    created = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    loaded = manager.get_run_workspace(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    assert loaded == created

    with pytest.raises(WorkspaceManagerError, match="Run workspace was not found"):
        manager.get_run_workspace(
            run_id="run-2",
            workspace_ref="workspace-2",
            trace_context=build_trace(run_id="run-2"),
        )


def test_assert_inside_workspace_allows_nested_paths_and_rejects_escape_absolute_and_logs(
    tmp_path: Path,
) -> None:
    log_writer = RecordingRunLogWriter()
    audit_service = RecordingAuditService()
    manager = build_manager(
        tmp_path,
        log_writer=log_writer,
        audit_service=audit_service,
    )
    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    allowed = manager.assert_inside_workspace(
        "src/app.py",
        workspace=workspace,
        trace_context=build_trace(),
    )

    assert allowed == (workspace.root / "src" / "app.py").resolve()

    for target in (
        "src/../../outside.py",
        "/outside.py",
        "C:/outside.py",
        ".runtime/logs/run-1.jsonl",
    ):
        with pytest.raises(ToolWorkspaceBoundaryError) as blocked:
            manager.assert_inside_workspace(
                target,
                workspace=workspace,
                trace_context=build_trace(),
            )
        assert blocked.value.target == target

    assert audit_service.records[-1]["actor_type"] is AuditActorType.SYSTEM
    assert audit_service.records[-1]["action"] == "workspace.boundary.blocked"
    assert audit_service.records[-1]["target_type"] == "workspace_path"
    assert log_writer.records[-1].category is LogCategory.WORKSPACE
    assert log_writer.records[-1].level is LogLevel.WARNING


def test_assert_inside_workspace_normalizes_windows_style_paths_and_blocks_windows_escape_forms(
    tmp_path: Path,
) -> None:
    audit_service = RecordingAuditService()
    manager = build_manager(tmp_path, audit_service=audit_service)
    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    allowed = manager.assert_inside_workspace(
        "src\\app.py",
        workspace=workspace,
        trace_context=build_trace(),
    )

    assert allowed == (workspace.root / "src" / "app.py").resolve()

    for target in (
        "src\\..\\..\\outside.py",
        "\\outside.py",
        "\\\\server\\share\\outside.py",
        "C:outside.py",
    ):
        with pytest.raises(ToolWorkspaceBoundaryError) as blocked:
            manager.assert_inside_workspace(
                target,
                workspace=workspace,
                trace_context=build_trace(),
            )
        assert blocked.value.target == target


def test_boundary_audit_metadata_redacts_sensitive_target(tmp_path: Path) -> None:
    audit_service = RecordingAuditService()
    manager = build_manager(tmp_path, audit_service=audit_service)
    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    with pytest.raises(ToolWorkspaceBoundaryError):
        manager.assert_inside_workspace(
            "../Bearer sk-raw-secret",
            workspace=workspace,
            trace_context=build_trace(),
        )

    metadata = audit_service.records[-1]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["target"] == "[blocked:sensitive_text_pattern]"
    assert metadata["target_redaction_status"] == "blocked"


def test_cleanup_run_workspace_removes_directory_and_is_idempotent(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )
    (workspace.root / "nested").mkdir()
    (workspace.root / "nested" / "file.txt").write_text("data", encoding="ascii")

    manager.cleanup_run_workspace(workspace=workspace, trace_context=build_trace())
    manager.cleanup_run_workspace(workspace=workspace, trace_context=build_trace())

    assert not workspace.root.exists()


def test_cleanup_run_workspace_rejects_roots_outside_managed_workspace_boundary(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    manager = WorkspaceManager(settings=settings, now=lambda: NOW)

    for workspace in (
        RunWorkspace(
            run_id="run-1",
            workspace_ref="workspace-root",
            root=settings.resolve_workspace_root(),
            excluded_relative_paths=(),
        ),
        RunWorkspace(
            run_id="run-1",
            workspace_ref="outside-root",
            root=(tmp_path / "outside-root").resolve(),
            excluded_relative_paths=(),
        ),
    ):
        with pytest.raises(
            WorkspaceManagerError,
            match="Run workspace could not be cleaned",
        ):
            manager.cleanup_run_workspace(
                workspace=workspace,
                trace_context=build_trace(),
            )


def test_workspace_root_outside_default_project_root_has_no_runtime_log_relative_exclusion(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path, runtime_under_project=False)

    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    assert workspace.excluded_relative_paths == ()


def test_create_lookup_and_cleanup_failures_write_workspace_error_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_writer = RecordingRunLogWriter()
    blocked_root = tmp_path / "blocked-root"
    blocked_root.write_text("not a directory", encoding="ascii")
    manager = build_manager(
        tmp_path,
        workspace_root=blocked_root,
        log_writer=log_writer,
    )

    with pytest.raises(WorkspaceManagerError, match="Run workspace could not be created"):
        manager.create_for_run(
            run_id="run-1",
            workspace_ref="workspace-1",
            trace_context=build_trace(),
        )

    missing_manager = build_manager(tmp_path, log_writer=log_writer)
    with pytest.raises(WorkspaceManagerError, match="Run workspace was not found"):
        missing_manager.get_run_workspace(
            run_id="run-9",
            workspace_ref="workspace-9",
            trace_context=build_trace(run_id="run-9"),
        )

    workspace = missing_manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )
    monkeypatch.setattr(
        "backend.app.workspace.manager.rmtree",
        lambda path: (_ for _ in ()).throw(OSError("locked")),
    )

    with pytest.raises(WorkspaceManagerError, match="Run workspace could not be cleaned"):
        missing_manager.cleanup_run_workspace(
            workspace=workspace,
            trace_context=build_trace(),
        )

    error_records = [
        record for record in log_writer.records if record.level is LogLevel.ERROR
    ]
    assert [record.payload.summary["action"] for record in error_records] == [
        "create_for_run_failed",
        "get_run_workspace_failed",
        "cleanup_run_workspace_failed",
    ]


def test_runtime_log_write_failure_does_not_rollback_filesystem_outcome(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path, log_writer=ExplodingRunLogWriter())

    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )
    manager.cleanup_run_workspace(workspace=workspace, trace_context=build_trace())

    assert not workspace.root.exists()


def test_audit_write_failure_does_not_unblock_boundary_violation(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, audit_service=ExplodingAuditService())
    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=build_trace(),
    )

    with pytest.raises(ToolWorkspaceBoundaryError):
        manager.assert_inside_workspace(
            "../outside.py",
            workspace=workspace,
            trace_context=build_trace(),
        )
