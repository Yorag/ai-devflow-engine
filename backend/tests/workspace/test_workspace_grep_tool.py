from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import ToolExecutionContext, ToolExecutionRequest
from backend.app.tools.protocol import ToolAuditRef, ToolResultStatus
from backend.app.tools.registry import ToolRegistry
from backend.app.workspace.manager import EnvironmentSettings, RunWorkspace, WorkspaceManager
from backend.app.workspace.tools import GrepTool, WorkspaceGrepOptions


NOW = datetime(2026, 5, 4, 10, 0, 0, tzinfo=UTC)


def _trace() -> TraceContext:
    return TraceContext(
        request_id="request-workspace-grep-1",
        trace_id="trace-workspace-grep-1",
        correlation_id="correlation-workspace-grep-1",
        span_id="span-workspace-grep-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


@dataclass(frozen=True)
class _WorkspaceBoundary:
    manager: WorkspaceManager
    workspace: RunWorkspace

    def assert_inside_workspace(
        self,
        target: str,
        *,
        trace_context: TraceContext,
    ) -> None:
        self.manager.assert_inside_workspace(
            target,
            workspace=self.workspace,
            trace_context=trace_context,
        )


class _RecordingAudit:
    def __init__(self) -> None:
        self.intents: list[str] = []
        self.rejections: list[str] = []

    def record_tool_intent(
        self,
        *,
        request: ToolExecutionRequest,
        tool_name: str,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.intents.append(tool_name)
        return ToolAuditRef(
            audit_id=f"audit-{request.call_id}",
            action="tool.intent",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-{request.call_id}",
        )

    def record_tool_rejection(
        self,
        *,
        request: ToolExecutionRequest,
        error_code: ErrorCode,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.rejections.append(error_code.value)
        return ToolAuditRef(
            audit_id=f"audit-reject-{request.call_id}",
            action="tool.rejected",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-reject-{request.call_id}",
        )


class _RecordingRunLog:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record_tool_result(
        self,
        *,
        request: ToolExecutionRequest,
        result,
        duration_ms: int,
    ) -> None:
        self.records.append(
            {
                "tool_name": request.tool_name,
                "status": result.status,
                "audit_ref": result.audit_ref,
                "error_code": result.error.error_code if result.error else None,
                "duration_ms": duration_ms,
            }
        )


@dataclass(frozen=True)
class _Harness:
    manager: WorkspaceManager
    workspace: RunWorkspace
    registry: ToolRegistry
    trace_context: TraceContext
    audit: _RecordingAudit
    run_log: _RecordingRunLog


def _build_harness(
    tmp_path: Path,
    *,
    options: WorkspaceGrepOptions | None = None,
) -> _Harness:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = WorkspaceManager(
        settings=EnvironmentSettings(
            default_project_root=project_root,
            workspace_root=project_root,
            platform_runtime_root=project_root / ".runtime",
        )
    )
    trace_context = _trace()
    workspace = manager.create_for_run(
        run_id=trace_context.run_id or "run-1",
        workspace_ref="workspace-1",
        trace_context=trace_context,
    )
    audit = _RecordingAudit()
    run_log = _RecordingRunLog()
    registry = ToolRegistry(
        [GrepTool(manager=manager, workspace=workspace, options=options or WorkspaceGrepOptions())]
    )
    return _Harness(
        manager=manager,
        workspace=workspace,
        registry=registry,
        trace_context=trace_context,
        audit=audit,
        run_log=run_log,
    )


def _context(harness: _Harness) -> ToolExecutionContext:
    return ToolExecutionContext(
        stage_type=StageType.CODE_REVIEW,
        stage_contracts={StageType.CODE_REVIEW.value: {"allowed_tools": ["grep"]}},
        trace_context=harness.trace_context,
        workspace_boundary=_WorkspaceBoundary(
            manager=harness.manager,
            workspace=harness.workspace,
        ),
        audit_recorder=harness.audit,
        run_log_recorder=harness.run_log,
        runtime_tool_timeout_seconds=5,
        platform_tool_timeout_hard_limit_seconds=30,
    )


def _request(
    harness: _Harness,
    payload: dict[str, object],
) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_name="grep",
        call_id="call-grep",
        input_payload=payload,
        trace_context=harness.trace_context,
        coordination_key="coordination-grep",
    )


def _match_event(path: str, line_number: int, text: str) -> str:
    return json.dumps(
        {
            "type": "match",
            "data": {
                "path": {"text": path},
                "lines": {"text": text},
                "line_number": line_number,
                "submatches": [],
            },
        }
    )


def test_grep_registers_and_returns_sorted_matches_via_tool_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):  # noqa: ANN001
        captured["args"] = list(args)
        captured["cwd"] = kwargs["cwd"]
        captured["shell"] = kwargs.get("shell")
        captured["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="\n".join(
                [
                    _match_event("src/zeta.py", 8, "match zeta\n"),
                    _match_event("src/alpha.py", 2, "match alpha\n"),
                    _match_event(".runtime/logs/run.jsonl", 1, "private\n"),
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr("backend.app.workspace.tools.shutil.which", lambda name: "C:/rg.exe")
    monkeypatch.setattr("backend.app.workspace.tools.subprocess.run", fake_run)

    result = harness.registry.execute(
        _request(harness, {"pattern": "match", "path": "src"}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "matches": [
            {
                "path": "src/alpha.py",
                "line_number": 2,
                "snippet": "match alpha",
                "snippet_truncated": False,
            },
            {
                "path": "src/zeta.py",
                "line_number": 8,
                "snippet": "match zeta",
                "snippet_truncated": False,
            },
        ],
        "truncated": False,
    }
    assert captured["cwd"] == harness.workspace.root
    assert captured["timeout"] == 5
    assert "--json" in captured["args"]
    assert "src" in captured["args"]
    assert "-g" in captured["args"]
    assert "!.runtime/logs/**" in captured["args"]
    assert captured["shell"] is False
    assert harness.audit.intents == ["grep"]


def test_grep_returns_structured_failure_when_rg_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(tmp_path)
    monkeypatch.setattr("backend.app.workspace.tools.shutil.which", lambda name: None)

    result = harness.registry.execute(
        _request(harness, {"pattern": "match", "path": "."}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.INTERNAL_ERROR
    assert result.error.safe_details == {"path": ".", "reason": "rg_unavailable"}
    assert result.audit_ref is not None
    assert harness.audit.intents == ["grep"]


def test_grep_passes_pattern_and_path_as_positional_operands_not_rg_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):  # noqa: ANN001
        captured["args"] = list(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("backend.app.workspace.tools.shutil.which", lambda name: "C:/rg.exe")
    monkeypatch.setattr("backend.app.workspace.tools.subprocess.run", fake_run)

    result = harness.registry.execute(
        _request(harness, {"pattern": "--context", "path": "src"}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert captured["args"][-4:] == ["-e", "--context", "--", "src"]


def test_grep_reports_workspace_boundary_violation_before_running_rg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(tmp_path)
    called = False

    def fake_run(args, **kwargs):  # noqa: ANN001
        nonlocal called
        called = True
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("backend.app.workspace.tools.subprocess.run", fake_run)

    result = harness.registry.execute(
        _request(harness, {"pattern": "match", "path": "../outside"}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.BLOCKED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert result.error.safe_details == {
        "target": "../outside",
        "requested_tool_name": "grep",
    }
    assert called is False
    assert harness.audit.rejections == ["tool_workspace_boundary_violation"]


def test_grep_truncates_result_count_and_individual_snippets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(
        tmp_path,
        options=WorkspaceGrepOptions(max_results=2, snippet_char_limit=12),
    )
    monkeypatch.setattr("backend.app.workspace.tools.shutil.which", lambda name: "C:/rg.exe")
    monkeypatch.setattr(
        "backend.app.workspace.tools.subprocess.run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="\n".join(
                [
                    _match_event("src/a.py", 1, "01234567890123456789\n"),
                    _match_event("src/b.py", 2, "second\n"),
                    _match_event("src/c.py", 3, "third\n"),
                ]
            ),
            stderr="",
        ),
    )

    result = harness.registry.execute(
        _request(harness, {"pattern": "value", "path": "src"}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["truncated"] is True
    assert result.output_payload["matches"] == [
        {
            "path": "src/a.py",
            "line_number": 1,
            "snippet": "012345678...",
            "snippet_truncated": True,
        },
        {
            "path": "src/b.py",
            "line_number": 2,
            "snippet": "second",
            "snippet_truncated": False,
        },
    ]


def test_grep_blocks_sensitive_match_content_without_leaking_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(tmp_path)
    secret_line = "Authorization: Bearer secret-token\n"

    monkeypatch.setattr("backend.app.workspace.tools.shutil.which", lambda name: "C:/rg.exe")
    monkeypatch.setattr(
        "backend.app.workspace.tools.subprocess.run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=_match_event("src/secrets.txt", 9, secret_line),
            stderr="",
        ),
    )

    result = harness.registry.execute(
        _request(harness, {"pattern": "Authorization", "path": "src"}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.INTERNAL_ERROR
    assert result.error.safe_details == {
        "path": "src/secrets.txt",
        "line_number": 9,
        "reason": "grep_match_blocked",
    }
    assert "secret-token" not in str(result.error.safe_details)
    assert result.audit_ref is not None
    assert harness.run_log.records[-1]["error_code"] is ErrorCode.INTERNAL_ERROR


def test_grep_maps_nonzero_permission_failure_without_echoing_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(tmp_path)

    monkeypatch.setattr("backend.app.workspace.tools.shutil.which", lambda name: "C:/rg.exe")
    monkeypatch.setattr(
        "backend.app.workspace.tools.subprocess.run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=2,
            stdout="",
            stderr="Permission denied (os error 13) while opening secrets.txt",
        ),
    )

    result = harness.registry.execute(
        _request(harness, {"pattern": "needle", "path": "src"}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.safe_details == {
        "path": "src",
        "reason": "rg_permission_denied",
        "returncode": 2,
    }
    assert "secrets.txt" not in result.error.safe_message
    assert "Permission denied" not in str(result.error.safe_details)


def test_grep_treats_rg_exit_code_one_as_empty_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(tmp_path)

    monkeypatch.setattr("backend.app.workspace.tools.shutil.which", lambda name: "C:/rg.exe")
    monkeypatch.setattr(
        "backend.app.workspace.tools.subprocess.run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="",
        ),
    )

    result = harness.registry.execute(
        _request(harness, {"pattern": "needle", "path": "."}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {"matches": [], "truncated": False}


def test_grep_does_not_exclude_non_log_runtime_paths_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build_harness(tmp_path)
    monkeypatch.setattr("backend.app.workspace.tools.shutil.which", lambda name: "C:/rg.exe")
    monkeypatch.setattr(
        "backend.app.workspace.tools.subprocess.run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="\n".join(
                [
                    _match_event(".runtime/cache/index.txt", 4, "visible cache\n"),
                    _match_event(".runtime/logs/run.jsonl", 1, "private\n"),
                ]
            ),
            stderr="",
        ),
    )

    result = harness.registry.execute(
        _request(harness, {"pattern": "visible", "path": "."}),
        _context(harness),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "matches": [
            {
                "path": ".runtime/cache/index.txt",
                "line_number": 4,
                "snippet": "visible cache",
                "snippet_truncated": False,
            }
        ],
        "truncated": False,
    }
