from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
from typing import Any, Literal, Protocol

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.observability import AuditResult
from backend.app.tools.protocol import (
    ToolAuditRef,
    ToolBindableDescription,
    ToolError,
    ToolInput,
    ToolPermissionBoundary,
    ToolReconciliationStatus,
    ToolResult,
    ToolResultStatus,
    ToolSideEffectLevel,
)
from backend.app.workspace.manager import RunWorkspace, WorkspaceManager
from backend.app.workspace.verification_policy import classify_verification_command


_BASH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"command": {"type": "string", "minLength": 1}},
    "required": ["command"],
    "additionalProperties": False,
}
_BASH_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "argv": {"type": "array", "items": {"type": "string"}},
        "exit_code": {"type": "integer"},
        "duration_ms": {"type": "integer"},
        "stdout_excerpt": {"type": "string"},
        "stderr_excerpt": {"type": "string"},
        "stdout_truncated": {"type": "boolean"},
        "stderr_truncated": {"type": "boolean"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "command",
        "argv",
        "exit_code",
        "duration_ms",
        "stdout_excerpt",
        "stderr_excerpt",
        "stdout_truncated",
        "stderr_truncated",
        "changed_files",
    ],
    "additionalProperties": False,
}
_OUTPUT_PREVIEW_LIMIT = 4096
_EXCLUDED_PATH_PREFIXES = (
    ".runtime/logs",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "coverage",
    "__pycache__",
)
_EXCLUDED_PATH_SEGMENTS = frozenset(
    {
        "node_modules",
    }
)
_BASH_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"Authorization:", re.IGNORECASE),
    re.compile(r"Cookie:", re.IGNORECASE),
    re.compile(r"Set-Cookie:", re.IGNORECASE),
    re.compile(
        r"(?<![A-Za-z0-9_])(?:api[_-]?key|password|secret|token)\s*(?:[:=]|\s)\s*\S+",
        re.IGNORECASE,
    ),
)


class BashAuditPort(Protocol):
    def record_tool_call(self, **kwargs: object) -> object: ...

    def record_tool_error(self, **kwargs: object) -> object: ...


BashRunner = Callable[
    [object],
    object,
]


@dataclass(frozen=True, slots=True)
class BashExecutionResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    stdout_truncated: bool
    stderr_truncated: bool
    changed_files: list[str]


@dataclass(frozen=True, slots=True)
class BashCommandAllowlist:
    workspace_root: Path

    def allows(self, argv: Sequence[str]) -> bool:
        command = shlex.join(list(argv))
        return classify_verification_command(
            command,
            workspace_root=self.workspace_root,
        ).allowed


@dataclass(frozen=True, slots=True)
class BashTool:
    manager: WorkspaceManager
    workspace: RunWorkspace
    audit_service: BashAuditPort | None
    runner: Callable[..., object] | None = None

    @property
    def name(self) -> str:
        return "bash"

    @property
    def category(self) -> str:
        return "workspace"

    @property
    def description(self) -> str:
        return "Execute one allowlisted workspace command without shell semantics."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _BASH_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _BASH_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.HIGH_RISK

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return (ToolRiskCategory.UNKNOWN_COMMAND,)

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=False,
            resource_scopes=("current_run_workspace",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.PROCESS_EXECUTION

    @property
    def audit_required(self) -> bool:
        return True

    @property
    def schema_version(self) -> str:
        return "tool-schema-v1"

    @property
    def default_timeout_seconds(self) -> float | None:
        return 30.0

    def bindable_description(self) -> ToolBindableDescription:
        return ToolBindableDescription(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
            result_schema=dict(self.result_schema),
            risk_level=self.default_risk_level,
            risk_categories=list(self.risk_categories),
            schema_version=self.schema_version,
            default_timeout_seconds=self.default_timeout_seconds,
        )

    def execute(self, tool_input: ToolInput) -> ToolResult:
        return run_bash_command(
            self.manager,
            self.workspace,
            str(tool_input.input_payload["command"]),
            audit_service=self.audit_service,
            runner=self.runner,
            tool_input=tool_input,
        )


def run_bash_command(
    manager: WorkspaceManager,
    workspace: RunWorkspace,
    command: str,
    *,
    audit_service: BashAuditPort | None,
    runner: Callable[..., object] | None = None,
    tool_input: ToolInput,
) -> ToolResult:
    command = command.strip()
    decision = classify_verification_command(command, workspace_root=workspace.root)
    argv = list(decision.argv)
    if not decision.allowed:
        result = _tool_error_result(
            tool_input,
            error_code=ErrorCode.BASH_COMMAND_NOT_ALLOWED,
            safe_details={"command": _safe_command_detail(command)},
        )
        audit_failure = _record_tool_error(
            audit_service,
            tool_input=tool_input,
            command=command,
            error_code=ErrorCode.BASH_COMMAND_NOT_ALLOWED,
            result=AuditResult.BLOCKED,
            reason="Command is not allowlisted.",
            metadata={},
            workspace=None,
            changed_files=(),
        )
        return audit_failure or result
    execution_mode = decision.execution_mode
    cwd = decision.working_directory or workspace.root

    before = _workspace_snapshot(workspace)
    started = time.monotonic()
    try:
        raw = _run_command(
            command if execution_mode == "inspection" else argv,
            execution_mode=execution_mode,
            cwd=cwd,
            timeout=tool_input.timeout_seconds,
            runner=runner,
        )
    except subprocess.TimeoutExpired:
        changed_files = _changed_files(before, _workspace_snapshot(workspace))
        result = _tool_error_result(
            tool_input,
            error_code=ErrorCode.TOOL_TIMEOUT,
            safe_details={"timeout_seconds": tool_input.timeout_seconds or 0},
            workspace=workspace,
            changed_files=changed_files,
        )
        audit_failure = _record_tool_error(
            audit_service,
            tool_input=tool_input,
            command=command,
            error_code=ErrorCode.TOOL_TIMEOUT,
            result=AuditResult.FAILED,
            reason="Command timed out.",
            metadata={
                "timeout_seconds": tool_input.timeout_seconds or 0,
                "changed_files": list(changed_files),
            },
            workspace=workspace,
            changed_files=changed_files,
        )
        return audit_failure or result
    except OSError:
        result = _tool_error_result(
            tool_input,
            error_code=ErrorCode.INTERNAL_ERROR,
            safe_details={"reason": "bash_command_failed"},
        )
        audit_failure = _record_tool_error(
            audit_service,
            tool_input=tool_input,
            command=command,
            error_code=ErrorCode.INTERNAL_ERROR,
            result=AuditResult.FAILED,
            reason="Command failed to start.",
            metadata={},
            workspace=None,
            changed_files=(),
        )
        return audit_failure or result

    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    safe_command = _safe_command_detail(command)
    safe_argv = _safe_argv(argv)
    stdout, stdout_truncated = _truncate_output(raw["stdout"], _OUTPUT_PREVIEW_LIMIT)
    stderr, stderr_truncated = _truncate_output(raw["stderr"], _OUTPUT_PREVIEW_LIMIT)
    changed_files = _changed_files(before, _workspace_snapshot(workspace))
    execution = BashExecutionResult(
        argv=list(argv),
        returncode=int(raw["returncode"]),
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        changed_files=changed_files,
    )

    if execution.returncode != 0:
        result = ToolResult(
            tool_name="bash",
            call_id=tool_input.call_id,
            status=ToolResultStatus.FAILED,
            output_payload={
                "command": safe_command,
                "argv": safe_argv,
                "exit_code": execution.returncode,
                "duration_ms": execution.duration_ms,
                "stdout_excerpt": stdout,
                "stderr_excerpt": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "changed_files": list(changed_files),
            },
            output_preview=_preview_bash(command, stdout, stderr),
            error=ToolError.from_code(
                ErrorCode.INTERNAL_ERROR,
                trace_context=tool_input.trace_context,
                safe_details={
                    "command": safe_command,
                    "exit_code": execution.returncode,
                    "stdout_excerpt": stdout,
                    "stderr_excerpt": stderr,
                },
            ),
            side_effect_refs=_side_effect_refs(workspace, tool_input, changed_files),
            reconciliation_status=(
                ToolReconciliationStatus.PENDING
                if changed_files
                else ToolReconciliationStatus.NOT_REQUIRED
            ),
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )
        audit_failure = _record_tool_error(
            audit_service,
            tool_input=tool_input,
            command=command,
            error_code=ErrorCode.INTERNAL_ERROR,
            result=AuditResult.FAILED,
            reason="Command exited with a non-zero status.",
            metadata={
                "exit_code": execution.returncode,
                "duration_ms": execution.duration_ms,
                "changed_files": list(changed_files),
                "stdout_excerpt": stdout,
                "stderr_excerpt": stderr,
            },
            workspace=workspace,
            changed_files=changed_files,
        )
        return audit_failure or result

    audit_failure = _record_tool_call(
        audit_service,
        tool_input=tool_input,
        command=command,
        execution=execution,
        workspace=workspace,
    )
    if audit_failure is not None:
        return audit_failure

    return ToolResult(
        tool_name="bash",
        call_id=tool_input.call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={
            "command": safe_command,
            "argv": safe_argv,
            "exit_code": execution.returncode,
            "duration_ms": execution.duration_ms,
            "stdout_excerpt": stdout,
            "stderr_excerpt": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "changed_files": list(changed_files),
        },
        output_preview=_preview_bash(command, stdout, stderr),
        side_effect_refs=_side_effect_refs(workspace, tool_input, changed_files),
        reconciliation_status=(
            ToolReconciliationStatus.PENDING
            if changed_files
            else ToolReconciliationStatus.NOT_REQUIRED
        ),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def _run_command(
    command_or_argv: object,
    *,
    execution_mode: Literal["argv", "inspection"],
    cwd: Path,
    timeout: float | None,
    runner: Callable[..., object] | None,
) -> dict[str, object]:
    if runner is not None:
        return _coerce_runner_result(runner(command_or_argv, cwd=cwd, timeout=timeout))
    if execution_mode == "inspection":
        completed = _run_inspection_command(
            str(command_or_argv),
            cwd=cwd,
            timeout=timeout,
        )
    else:
        argv = list(command_or_argv)
        resolved_executable = shutil.which(str(argv[0]))
        if resolved_executable:
            argv[0] = resolved_executable
        completed = subprocess.run(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _run_inspection_command(
    command: str,
    *,
    cwd: Path,
    timeout: float | None,
) -> subprocess.CompletedProcess[str]:
    working_directory = cwd
    pipeline = command
    tokens = shlex.split(command, posix=True)
    shell_segments = _split_tokens(tokens, "&&")
    if len(shell_segments) == 2 and shell_segments[0][:1] == ("cd",):
        working_directory = (cwd / shell_segments[0][1]).resolve(strict=False)
        pipeline = shlex.join(list(shell_segments[1]))
    script = f"""
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath '{_escape_powershell_single_quoted(working_directory)}'
{_inspection_command_to_powershell(pipeline)}
"""
    return subprocess.run(
        [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        shell=False,
    )


def _inspection_command_to_powershell(command: str) -> str:
    tokens = shlex.split(command, posix=True)
    pipeline_segments = _split_tokens(tokens, "|")
    rendered_segments = [_inspection_segment_to_powershell(segment) for segment in pipeline_segments]
    return " | ".join(rendered_segments)


def _inspection_segment_to_powershell(argv: tuple[str, ...]) -> str:
    executable = argv[0].lower()
    if executable in {"cat", "type", "get-content"}:
        return _render_get_content(argv)
    if executable in {"grep", "findstr", "select-string", "rg"}:
        return _render_select_string(argv)
    if executable in {"ls", "dir", "get-childitem"}:
        return _render_get_child_item(argv)
    raise ValueError(f"Unsupported inspection executable: {argv[0]}")


def _render_get_content(argv: tuple[str, ...]) -> str:
    paths = [token for token in argv[1:] if not token.startswith("-")]
    rendered = " ".join(
        f"-LiteralPath '{_escape_powershell_single_quoted(path)}'"
        for path in paths
    )
    return f"Get-Content {rendered}"


def _render_select_string(argv: tuple[str, ...]) -> str:
    executable = argv[0].lower()
    values = [token for token in argv[1:] if not token.startswith("-")]
    if not values:
        raise ValueError("Missing pattern")
    pattern = values[0]
    path_tokens = values[1:]
    case_sensitive = "-CaseSensitive" if any(
        token in {"-n", "-N"} for token in argv[1:]
    ) else ""
    path_args = ""
    if path_tokens:
        path_args = " " + " ".join(
            f"-Path '{_escape_powershell_single_quoted(path)}'" for path in path_tokens
        )
    if executable == "rg":
        case_sensitive = ""
    return (
        f"Select-String -Pattern '{_escape_powershell_single_quoted(pattern)}'"
        f"{path_args} {case_sensitive}".rstrip()
    )


def _render_get_child_item(argv: tuple[str, ...]) -> str:
    paths = [token for token in argv[1:] if not token.startswith("-")]
    rendered = " ".join(
        f"-LiteralPath '{_escape_powershell_single_quoted(path)}'"
        for path in paths
    )
    return f"Get-ChildItem {rendered}"


def _split_tokens(
    argv: Sequence[str],
    separator: str,
) -> list[tuple[str, ...]]:
    segments: list[list[str]] = [[]]
    for token in argv:
        if token == separator:
            segments.append([])
            continue
        segments[-1].append(token)
    return [tuple(segment) for segment in segments if segment]


def _escape_powershell_single_quoted(value: object) -> str:
    return str(value).replace("'", "''")


def _coerce_runner_result(result: object) -> dict[str, object]:
    if isinstance(result, Mapping):
        return {
            "returncode": int(result.get("returncode", 0)),
            "stdout": str(result.get("stdout", "")),
            "stderr": str(result.get("stderr", "")),
        }
    return {
        "returncode": int(getattr(result, "returncode", 0)),
        "stdout": str(getattr(result, "stdout", "")),
        "stderr": str(getattr(result, "stderr", "")),
    }


def _truncate_output(text: str, limit: int) -> tuple[str, bool]:
    if _contains_sensitive_bash_text(text):
        return "[redacted]", False
    redacted = RedactionPolicy(
        max_text_length=max(limit, 32),
        excerpt_length=max(limit, 32),
    ).summarize_text(
        text,
        payload_type="bash_output_preview",
    )
    if redacted.redaction_status.value == "blocked":
        return "[redacted]", False
    visible = str(redacted.redacted_payload or "")
    return visible, visible != text


def _contains_sensitive_bash_text(text: str) -> bool:
    return any(pattern.search(text) is not None for pattern in _BASH_SENSITIVE_TEXT_PATTERNS)


def _workspace_snapshot(workspace: RunWorkspace) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in workspace.root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace.root).as_posix()
        if _is_snapshot_excluded(relative, workspace):
            continue
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _is_snapshot_excluded(relative: str, workspace: RunWorkspace) -> bool:
    prefixes = (*workspace.excluded_relative_paths, *_EXCLUDED_PATH_PREFIXES)
    if any(relative == prefix or relative.startswith(f"{prefix}/") for prefix in prefixes):
        return True
    parts = tuple(Path(relative).parts)
    return any(part in _EXCLUDED_PATH_SEGMENTS for part in parts)


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def _side_effect_refs(
    workspace: RunWorkspace,
    tool_input: ToolInput,
    changed_files: Sequence[str],
) -> list[str]:
    refs = [f"command_trace:{workspace.run_id}:{tool_input.call_id}"]
    refs.extend(
        f"file_edit_trace:{workspace.run_id}:{tool_input.call_id}:{relative_path}"
        for relative_path in changed_files
    )
    return refs


def _preview_bash(command: str, stdout: str, stderr: str) -> str:
    parts = [f"$ {_safe_command_detail(command)}"]
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(stderr)
    preview, _ = _truncate_output("\n".join(parts), _OUTPUT_PREVIEW_LIMIT)
    return preview or "(no output)"


def _safe_command_detail(command: str, *, limit: int = 512) -> str:
    visible, _ = _truncate_output(command, limit)
    return visible or "[redacted]"


def _safe_argv(argv: Sequence[str]) -> list[str]:
    if _contains_sensitive_bash_text(" ".join(argv)):
        return ["[redacted]"]
    return list(argv)


def _record_tool_call(
    audit_service: BashAuditPort | None,
    *,
    tool_input: ToolInput,
    command: str,
    execution: BashExecutionResult,
    workspace: RunWorkspace,
) -> ToolResult | None:
    if audit_service is None:
        return _tool_error_result(
            tool_input,
            error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
            safe_details={"command": _safe_command_detail(command)},
            workspace=workspace,
            changed_files=execution.changed_files,
        )
    try:
        audit_service.record_tool_call(
            tool_name="bash",
            command=_safe_command_detail(command),
            exit_code=execution.returncode,
            duration_ms=execution.duration_ms,
            changed_files=list(execution.changed_files),
            stdout_excerpt=execution.stdout,
            stderr_excerpt=execution.stderr,
            intent_audit_id=tool_input.side_effect_intent_ref,
            trace_context=tool_input.trace_context,
        )
        return None
    except Exception:
        return _tool_error_result(
            tool_input,
            error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
            safe_details={"command": _safe_command_detail(command)},
            workspace=workspace,
            changed_files=execution.changed_files,
        )


def _record_tool_error(
    audit_service: BashAuditPort | None,
    *,
    tool_input: ToolInput,
    command: str,
    error_code: ErrorCode,
    result: AuditResult,
    reason: str,
    metadata: dict[str, object],
    workspace: RunWorkspace | None,
    changed_files: Sequence[str],
) -> ToolResult | None:
    if audit_service is None:
        return _tool_error_result(
            tool_input,
            error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
            safe_details={"command": _safe_command_detail(command)},
            workspace=workspace,
            changed_files=changed_files,
        )
    try:
        audit_service.record_tool_error(
            tool_name="bash",
            command=_safe_command_detail(command),
            error_code=error_code,
            result=result,
            reason=reason,
            metadata=metadata,
            intent_audit_id=tool_input.side_effect_intent_ref,
            trace_context=tool_input.trace_context,
        )
        return None
    except Exception:
        return _tool_error_result(
            tool_input,
            error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
            safe_details={"command": _safe_command_detail(command)},
            workspace=workspace,
            changed_files=changed_files,
        )


def _tool_error_result(
    tool_input: ToolInput,
    *,
    error_code: ErrorCode,
    safe_details: dict[str, object],
    workspace: RunWorkspace | None = None,
    changed_files: Sequence[str] = (),
) -> ToolResult:
    side_effect_refs = (
        _side_effect_refs(workspace, tool_input, changed_files)
        if workspace is not None
        else []
    )
    return ToolResult(
        tool_name="bash",
        call_id=tool_input.call_id,
        status=ToolResultStatus.FAILED,
        error=ToolError.from_code(
            error_code,
            trace_context=tool_input.trace_context,
            safe_details=safe_details,
        ),
        side_effect_refs=side_effect_refs,
        reconciliation_status=(
            ToolReconciliationStatus.PENDING
            if changed_files
            else ToolReconciliationStatus.NOT_REQUIRED
        ),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


__all__ = [
    "BashCommandAllowlist",
    "BashExecutionResult",
    "BashTool",
    "run_bash_command",
]
