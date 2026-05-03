from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import posixpath
import re
import shlex
import subprocess
import time
from typing import Any, Protocol

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
_SHELL_META_TOKENS = {"&&", "||", "|", ";", ">", ">>", "<", "`"}
_SHELL_META_SUBSTRINGS = (";", "|", "&", ">", "<", "`", "$(", "${")
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
_VERSION_PROBES = {
    ("python", "--version"),
    ("uv", "--version"),
    ("node", "--version"),
    ("npm", "--version"),
    ("git", "--version"),
    ("rg", "--version"),
}
_RESTRICTED_RUNTIME_PREFIXES = (".runtime",)
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
    [list[str]],
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
        if not argv:
            return False
        if tuple(argv[:2]) in _VERSION_PROBES and len(argv) == 2:
            return True
        command = " ".join(argv)
        if command in self._readme_commands():
            return True
        return self._allows_pytest(argv) or self._allows_frontend_script(argv)

    def _allows_pytest(self, argv: Sequence[str]) -> bool:
        if not self._has_pytest_config():
            return False
        return len(argv) >= 3 and list(argv[:3]) == ["uv", "run", "pytest"]

    def _allows_frontend_script(self, argv: Sequence[str]) -> bool:
        scripts = self._frontend_scripts()
        if not scripts:
            return False
        if len(argv) >= 5 and list(argv[:3]) == ["npm", "--prefix", "frontend"]:
            if argv[3] == "run" and argv[4] in scripts:
                return True
            if argv[3] in scripts:
                return True
        return False

    def _has_pytest_config(self) -> bool:
        pyproject = self.workspace_root / "pyproject.toml"
        if not pyproject.is_file():
            return False
        try:
            content = pyproject.read_text(encoding="utf-8")
        except OSError:
            return False
        return "pytest" in content

    def _frontend_scripts(self) -> set[str]:
        package_json = self.workspace_root / "frontend" / "package.json"
        if not package_json.is_file():
            return set()
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        scripts = data.get("scripts")
        if not isinstance(scripts, dict):
            return set()
        return {name for name in scripts if isinstance(name, str)}

    def _readme_commands(self) -> set[str]:
        commands: set[str] = set()
        for filename in ("README.md", "README.zh.md"):
            path = self.workspace_root / filename
            if not path.is_file():
                continue
            try:
                commands.update(_fenced_command_lines(path.read_text(encoding="utf-8")))
            except OSError:
                continue
        return commands


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
    argv = _parse_command(command)
    if _contains_blocked_path_argument(argv) or not BashCommandAllowlist(workspace.root).allows(argv):
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

    before = _workspace_snapshot(workspace)
    started = time.monotonic()
    try:
        raw = _run_command(argv, cwd=workspace.root, timeout=tool_input.timeout_seconds, runner=runner)
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
        result = _tool_error_result(
            tool_input,
            error_code=ErrorCode.INTERNAL_ERROR,
            safe_details={"exit_code": execution.returncode},
            workspace=workspace,
            changed_files=changed_files,
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


def _parse_command(command: str) -> list[str]:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return []
    if not argv:
        return []
    if any(_token_has_shell_meta(token) for token in argv):
        return []
    return argv


def _contains_blocked_path_argument(argv: Sequence[str]) -> bool:
    for token in argv[1:]:
        if token.startswith("-"):
            _, separator, value = token.partition("=")
            if separator and _is_blocked_argument_path(value):
                return True
            continue
        if _is_blocked_argument_path(token):
            return True
    return False


def _token_has_shell_meta(token: str) -> bool:
    return token in _SHELL_META_TOKENS or any(fragment in token for fragment in _SHELL_META_SUBSTRINGS)


def _is_blocked_argument_path(token: str) -> bool:
    for candidate in _path_value_candidates(token):
        if _is_single_blocked_path(candidate):
            return True
    return False


def _is_single_blocked_path(token: str) -> bool:
    if not _looks_like_path_argument(token):
        return False
    normalized = _normalize_argument_path(token)
    return (
        normalized == ".."
        or normalized.startswith("../")
        or normalized.startswith("/")
        or (len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/")
        or normalized == ".runtime"
        or normalized.startswith(".runtime/")
    )


def _path_value_candidates(token: str) -> tuple[str, ...]:
    candidate = token.strip()
    if not candidate:
        return ()
    if "=" not in candidate:
        return (candidate,)
    parts = [part.strip() for part in candidate.split("=") if part.strip()]
    if len(parts) <= 1:
        return (candidate,)
    return tuple(parts[1:]) + (candidate,)


def _looks_like_path_argument(token: str) -> bool:
    candidate = token.strip()
    if not candidate:
        return False
    lowered = candidate.replace("\\", "/").lower()
    return (
        lowered == ".."
        or lowered.startswith("../")
        or lowered.startswith("/")
        or lowered.startswith(".")
        or "/" in lowered
        or (len(lowered) >= 3 and lowered[1] == ":" and lowered[2] == "/")
    )


def _normalize_argument_path(token: str) -> str:
    normalized = posixpath.normpath(token.strip().replace("\\", "/"))
    if normalized == ".":
        return ""
    return normalized.lower()


def _run_command(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float | None,
    runner: Callable[..., object] | None,
) -> dict[str, object]:
    if runner is not None:
        return _coerce_runner_result(runner(argv, cwd=cwd, timeout=timeout))
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
    return any(relative == prefix or relative.startswith(f"{prefix}/") for prefix in prefixes)


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


def _fenced_command_lines(content: str) -> set[str]:
    commands: set[str] = set()
    in_fence = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence or not line or line.startswith("#"):
            continue
        commands.add(line)
    return commands


__all__ = [
    "BashCommandAllowlist",
    "BashExecutionResult",
    "BashTool",
    "run_bash_command",
]
