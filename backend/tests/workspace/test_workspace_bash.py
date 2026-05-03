from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import StageType, ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import ToolExecutionContext, ToolExecutionRequest
from backend.app.tools.protocol import ToolAuditRef, ToolInput, ToolResultStatus
from backend.app.tools.registry import ToolRegistry
from backend.app.tools.risk import ToolConfirmationGrant, ToolConfirmationRequestRecord
from backend.app.workspace.bash import BashTool, run_bash_command
from backend.app.workspace.manager import EnvironmentSettings, RunWorkspace, WorkspaceManager


NOW = datetime(2026, 5, 4, 11, 0, 0, tzinfo=UTC)


def _trace() -> TraceContext:
    return TraceContext(
        request_id="request-workspace-bash-1",
        trace_id="trace-workspace-bash-1",
        correlation_id="correlation-workspace-bash-1",
        span_id="span-workspace-bash-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


class _RecordingAudit:
    def __init__(self) -> None:
        self.intents: list[dict[str, object]] = []
        self.rejections: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []
        self.errors: list[dict[str, object]] = []

    def record_tool_intent(self, **kwargs: object) -> ToolAuditRef:
        self.intents.append(dict(kwargs))
        trace_context = kwargs["trace_context"]
        request = kwargs["request"]
        return ToolAuditRef(
            audit_id=f"audit-intent-{request.call_id}",
            action="tool.intent",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-intent-{request.call_id}",
        )

    def record_tool_rejection(self, **kwargs: object) -> ToolAuditRef:
        self.rejections.append(dict(kwargs))
        trace_context = kwargs["trace_context"]
        request = kwargs["request"]
        return ToolAuditRef(
            audit_id=f"audit-reject-{request.call_id}",
            action="tool.rejected",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-reject-{request.call_id}",
        )

    def record_tool_call(self, **kwargs: object) -> ToolAuditRef:
        self.calls.append(dict(kwargs))
        trace_context = kwargs["trace_context"]
        return ToolAuditRef(
            audit_id="audit-bash-success",
            action="tool.bash.succeeded",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref="payload-bash-success",
        )

    def record_tool_error(self, **kwargs: object) -> ToolAuditRef:
        self.errors.append(dict(kwargs))
        trace_context = kwargs["trace_context"]
        return ToolAuditRef(
            audit_id="audit-bash-error",
            action="tool.bash.failed",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref="payload-bash-error",
        )


class _RecordingConfirmationPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_request(self, **kwargs: object) -> ToolConfirmationRequestRecord:
        self.calls.append(dict(kwargs))
        return ToolConfirmationRequestRecord(
            tool_confirmation_id="tool-confirmation-1",
            confirmation_object_ref=str(kwargs["confirmation_object_ref"]),
        )


class _RecordingRunner:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.calls: list[dict[str, object]] = []

    def __call__(self, argv: list[str], *, cwd: Path, timeout: float | None):
        self.calls.append({"argv": list(argv), "cwd": cwd, "timeout": timeout})
        (self.workspace_root / "frontend" / "dist").mkdir(parents=True, exist_ok=True)
        (self.workspace_root / "frontend" / "dist" / "app.js").write_text(
            "console.log('built');\n",
            encoding="utf-8",
        )
        return {
            "returncode": 0,
            "stdout": "vite build completed\n",
            "stderr": "",
        }


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


def _build_workspace(tmp_path: Path) -> tuple[WorkspaceManager, RunWorkspace]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = WorkspaceManager(
        settings=EnvironmentSettings(
            default_project_root=project_root,
            workspace_root=project_root,
            platform_runtime_root=project_root / ".runtime",
        )
    )
    workspace = manager.create_for_run(
        run_id="run-1",
        workspace_ref="workspace-1",
        trace_context=_trace(),
    )
    (workspace.root / "README.md").write_text(
        "```powershell\nuv run pytest backend/tests -q\n```\n",
        encoding="utf-8",
    )
    (workspace.root / "README.zh.md").write_text(
        "```powershell\nuv run pytest backend/tests/workspace/test_workspace_bash.py -v\n```\n",
        encoding="utf-8",
    )
    (workspace.root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = [\"backend/tests\"]\n",
        encoding="utf-8",
    )
    frontend = workspace.root / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        '{"scripts":{"build":"vite build","test":"vitest run"}}\n',
        encoding="utf-8",
    )
    return manager, workspace


def _context(
    manager: WorkspaceManager,
    workspace: RunWorkspace,
    audit: _RecordingAudit,
    confirmations: _RecordingConfirmationPort,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        stage_type=StageType.CODE_GENERATION,
        stage_contracts={StageType.CODE_GENERATION.value: {"allowed_tools": ["bash"]}},
        trace_context=_trace(),
        workspace_boundary=_WorkspaceBoundary(manager=manager, workspace=workspace),
        audit_recorder=audit,
        confirmation_port=confirmations,
        runtime_tool_timeout_seconds=5,
        platform_tool_timeout_hard_limit_seconds=30,
    )


def _request(command: str) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_name="bash",
        call_id="call-bash",
        input_payload={"command": command},
        trace_context=_trace(),
        coordination_key="coordination-bash",
    )


def _execute_confirmed(
    registry: ToolRegistry,
    request: ToolExecutionRequest,
    context: ToolExecutionContext,
    confirmations: _RecordingConfirmationPort,
) -> object:
    pending = registry.execute(request, context)
    assert pending.status is ToolResultStatus.WAITING_CONFIRMATION
    assert pending.error is not None
    confirmed_trace = request.trace_context.model_copy(
        update={"tool_confirmation_id": pending.tool_confirmation_ref}
    )
    confirmed_request = ToolExecutionRequest(
        tool_name=request.tool_name,
        call_id=request.call_id,
        input_payload=request.input_payload,
        trace_context=confirmed_trace,
        coordination_key=request.coordination_key,
        confirmation_grant=ToolConfirmationGrant(
            tool_confirmation_id=str(pending.tool_confirmation_ref),
            confirmation_object_ref=str(confirmations.calls[-1]["confirmation_object_ref"]),
            tool_name="bash",
            input_digest=str(pending.error.safe_details["input_digest"]),
            target_summary=str(pending.error.safe_details["target_summary"]),
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
        ),
    )
    return registry.execute(confirmed_request, context)


def test_bash_executes_allowlisted_build_command_shell_free_and_tracks_changed_files(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("npm --prefix frontend run build"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["exit_code"] == 0
    assert result.output_payload["argv"] == ["npm", "--prefix", "frontend", "run", "build"]
    assert result.output_payload["changed_files"] == ["frontend/dist/app.js"]
    assert result.side_effect_refs == [
        "command_trace:run-1:call-bash",
        "file_edit_trace:run-1:call-bash:frontend/dist/app.js",
    ]
    assert result.audit_ref is not None
    assert result.audit_ref.action == "tool.intent"
    assert audit.calls[0]["tool_name"] == "bash"
    assert audit.calls[0]["intent_audit_id"] == "audit-intent-call-bash"
    assert runner.calls == [
        {
            "argv": ["npm", "--prefix", "frontend", "run", "build"],
            "cwd": workspace.root,
            "timeout": 5,
        }
    ]


def test_bash_rejects_non_allowlisted_command_with_structured_error(tmp_path: Path) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("echo hacked"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert result.error.safe_details["command"] == "echo hacked"
    assert audit.errors[0]["error_code"] == ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert runner.calls == []


def test_bash_rejects_shell_chaining_without_invoking_subprocess(tmp_path: Path) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest && whoami"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert runner.calls == []


def test_bash_truncates_secret_bearing_output_without_leaking_token(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()

    def runner(argv: list[str], *, cwd: Path, timeout: float | None):
        return {
            "returncode": 0,
            "stdout": "ok\n" + ("x" * 9000),
            "stderr": "Authorization: Bearer secret-token\n",
        }

    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest backend/tests -q"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["stdout_truncated"] is True
    assert result.output_payload["stderr_truncated"] is False
    assert "secret-token" not in result.output_payload["stderr_excerpt"]
    assert "Authorization:" not in result.output_payload["stderr_excerpt"]
    assert "secret-token" not in (result.output_preview or "")


def test_bash_returns_structured_failure_when_audit_write_is_required_but_unavailable(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    confirmations = _RecordingConfirmationPort()

    class _FailingAudit(_RecordingAudit):
        def record_tool_call(self, **kwargs: object) -> ToolAuditRef:
            raise RuntimeError("audit ledger unavailable")

        def record_tool_error(self, **kwargs: object) -> ToolAuditRef:
            raise RuntimeError("audit ledger unavailable")

    audit = _FailingAudit()
    registry = ToolRegistry(
        [
            BashTool(
                manager=manager,
                workspace=workspace,
                audit_service=audit,
                runner=lambda argv, *, cwd, timeout: {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                },
            )
        ]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest backend/tests -q"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED


def test_bash_failed_command_keeps_side_effect_refs_for_changed_files(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()

    def runner(argv: list[str], *, cwd: Path, timeout: float | None):
        changed = workspace.root / "frontend" / "dist" / "failed.js"
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_text("console.log('failed build');\n", encoding="utf-8")
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "build failed\n",
        }

    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("npm --prefix frontend run build"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.side_effect_refs == [
        "command_trace:run-1:call-bash",
        "file_edit_trace:run-1:call-bash:frontend/dist/failed.js",
    ]
    assert result.reconciliation_status.name == "PENDING"
    assert audit.errors[0]["metadata"]["changed_files"] == ["frontend/dist/failed.js"]


def test_bash_rejects_output_redirection_form_without_invoking_subprocess(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest backend/tests -q > out.txt"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert runner.calls == []


def test_bash_rejects_inline_redirection_without_invoking_subprocess(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest backend/tests -q 2>out.txt"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert runner.calls == []


def test_bash_rejects_option_shaped_workspace_escape_without_invoking_subprocess(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest --rootdir=.. backend/tests -q"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert runner.calls == []


def test_bash_rejects_pytest_override_option_workspace_escape(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest -o cache_dir=../outside backend/tests -q"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert runner.calls == []


def test_bash_rejects_pytest_override_ini_workspace_escape(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest --override-ini=cache_dir=../outside backend/tests -q"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert runner.calls == []


def test_bash_rejects_command_substitution_without_invoking_subprocess(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    runner = _RecordingRunner(workspace.root)
    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest $(whoami)"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert runner.calls == []


def test_bash_rejects_sensitive_command_without_internal_error(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()

    result = run_bash_command(
        manager,
        workspace,
        "echo password=secret123",
        audit_service=audit,
        tool_input=ToolInput(
            tool_name="bash",
            call_id="call-bash",
            input_payload={"command": "echo password=secret123"},
            trace_context=_trace(),
            coordination_key="coordination-bash",
            side_effect_intent_ref="audit-intent-call-bash",
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.BASH_COMMAND_NOT_ALLOWED
    assert result.error.safe_details["command"] == "[redacted]"
    assert audit.errors[0]["command"] == "[redacted]"


def test_bash_redacts_cookie_and_password_output(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()

    def runner(argv: list[str], *, cwd: Path, timeout: float | None):
        return {
            "returncode": 0,
            "stdout": "password=secret123\n",
            "stderr": "Cookie: session=abc\n",
        }

    registry = ToolRegistry(
        [BashTool(manager=manager, workspace=workspace, audit_service=audit, runner=runner)]
    )

    result = _execute_confirmed(
        registry,
        _request("uv run pytest backend/tests -q"),
        _context(manager, workspace, audit, confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["stdout_excerpt"] == "[redacted]"
    assert result.output_payload["stderr_excerpt"] == "[redacted]"
    assert "secret123" not in (result.output_preview or "")
    assert "session=abc" not in (result.output_preview or "")
    assert "[redacted]" in (result.output_preview or "")


def test_bash_redacts_space_separated_secret_flags_and_output(
    tmp_path: Path,
) -> None:
    manager, workspace = _build_workspace(tmp_path)
    audit = _RecordingAudit()

    result = run_bash_command(
        manager,
        workspace,
        "uv run pytest --token raw-secret backend/tests -q",
        audit_service=audit,
        runner=lambda argv, *, cwd, timeout: {
            "returncode": 0,
            "stdout": "password raw-secret\n",
            "stderr": "token raw-secret\n",
        },
        tool_input=ToolInput(
            tool_name="bash",
            call_id="call-bash",
            input_payload={"command": "uv run pytest --token raw-secret backend/tests -q"},
            trace_context=_trace(),
            coordination_key="coordination-bash",
            side_effect_intent_ref="audit-intent-call-bash",
        ),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["command"] == "[redacted]"
    assert result.output_payload["argv"] == ["[redacted]"]
    assert result.output_payload["stdout_excerpt"] == "[redacted]"
    assert result.output_payload["stderr_excerpt"] == "[redacted]"
    assert "raw-secret" not in (result.output_preview or "")
    assert audit.calls[0]["command"] == "[redacted]"
