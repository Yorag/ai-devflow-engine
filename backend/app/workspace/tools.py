from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import fnmatch
import json
import posixpath
from pathlib import Path
from pathlib import PureWindowsPath
import shutil
import subprocess
from typing import Any

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import ToolRiskCategory, ToolRiskLevel
from backend.app.tools.execution_gate import ToolWorkspaceBoundaryError
from backend.app.tools.protocol import (
    ToolBindableDescription,
    ToolError,
    ToolInput,
    ToolPermissionBoundary,
    ToolResult,
    ToolResultStatus,
    ToolSideEffectLevel,
)
from backend.app.observability.redaction import RedactionPolicy
from backend.app.workspace.manager import RunWorkspace, WorkspaceManager


_READ_FILE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string", "minLength": 1}},
    "required": ["path"],
    "additionalProperties": False,
}
_READ_FILE_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "content": {"type": "string"},
    },
    "required": ["path", "content"],
    "additionalProperties": False,
}
_GLOB_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"pattern": {"type": "string", "minLength": 1}},
    "required": ["pattern"],
    "additionalProperties": False,
}
_GLOB_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "path_type": {"type": "string", "enum": ["file"]},
                },
                "required": ["path", "path_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}
_WRITE_FILE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "content": {"type": "string"},
    },
    "required": ["path", "content"],
    "additionalProperties": False,
}
_WRITE_FILE_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "bytes_written": {"type": "integer"},
    },
    "required": ["path", "bytes_written"],
    "additionalProperties": False,
}
_EDIT_FILE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "old_text": {"type": "string", "minLength": 1},
        "new_text": {"type": "string"},
    },
    "required": ["path", "old_text", "new_text"],
    "additionalProperties": False,
}
_EDIT_FILE_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "replacements": {"type": "integer"},
        "bytes_written": {"type": "integer"},
    },
    "required": ["path", "replacements", "bytes_written"],
    "additionalProperties": False,
}
_GREP_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "minLength": 1},
        "path": {"type": "string", "minLength": 1},
    },
    "required": ["pattern", "path"],
    "additionalProperties": False,
}
_GREP_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line_number": {"type": "integer"},
                    "snippet": {"type": "string"},
                    "snippet_truncated": {"type": "boolean"},
                },
                "required": ["path", "line_number", "snippet", "snippet_truncated"],
                "additionalProperties": False,
            },
        },
        "truncated": {"type": "boolean"},
    },
    "required": ["matches", "truncated"],
    "additionalProperties": False,
}
_PREVIEW_LIMIT = 4096
_PREVIEW_REDACTION = RedactionPolicy(
    max_text_length=_PREVIEW_LIMIT,
    excerpt_length=_PREVIEW_LIMIT,
)
_RICH_MEDIA_SUFFIXES = frozenset({".svg", ".pdf"})
_PLATFORM_PRIVATE_RELATIVE_PATHS = frozenset({".runtime/logs"})


@dataclass(frozen=True, slots=True)
class FileReadTool:
    manager: WorkspaceManager
    workspace: RunWorkspace

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def category(self) -> str:
        return "workspace"

    @property
    def description(self) -> str:
        return "Read one UTF-8 text file from the current run workspace."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _READ_FILE_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _READ_FILE_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.READ_ONLY

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return ()

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("path",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.NONE

    @property
    def audit_required(self) -> bool:
        return False

    @property
    def schema_version(self) -> str:
        return "tool-schema-v1"

    @property
    def default_timeout_seconds(self) -> float | None:
        return 5.0

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
        path = str(tool_input.input_payload["path"])
        return read_file(
            self.manager,
            self.workspace,
            path,
            tool_input=tool_input,
        )


@dataclass(frozen=True, slots=True)
class GlobTool:
    manager: WorkspaceManager
    workspace: RunWorkspace

    @property
    def name(self) -> str:
        return "glob"

    @property
    def category(self) -> str:
        return "workspace"

    @property
    def description(self) -> str:
        return "List workspace-relative file paths matching one glob pattern."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _GLOB_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _GLOB_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.READ_ONLY

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return ()

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("pattern",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.NONE

    @property
    def audit_required(self) -> bool:
        return False

    @property
    def schema_version(self) -> str:
        return "tool-schema-v1"

    @property
    def default_timeout_seconds(self) -> float | None:
        return 5.0

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
        pattern = str(tool_input.input_payload["pattern"])
        return glob(
            self.manager,
            self.workspace,
            pattern,
            tool_input=tool_input,
        )


@dataclass(frozen=True, slots=True)
class FileWriteTool:
    manager: WorkspaceManager
    workspace: RunWorkspace

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def category(self) -> str:
        return "workspace"

    @property
    def description(self) -> str:
        return "Create or fully overwrite one UTF-8 text file in the current run workspace."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _WRITE_FILE_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _WRITE_FILE_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.LOW_RISK_WRITE

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return ()

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("path",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.WORKSPACE_WRITE

    @property
    def audit_required(self) -> bool:
        return True

    @property
    def schema_version(self) -> str:
        return "tool-schema-v1"

    @property
    def default_timeout_seconds(self) -> float | None:
        return 5.0

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
        return write_file(
            self.manager,
            self.workspace,
            str(tool_input.input_payload["path"]),
            str(tool_input.input_payload["content"]),
            tool_input=tool_input,
        )


@dataclass(frozen=True, slots=True)
class FileEditTool:
    manager: WorkspaceManager
    workspace: RunWorkspace

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def category(self) -> str:
        return "workspace"

    @property
    def description(self) -> str:
        return "Replace one exact string occurrence in one UTF-8 workspace text file."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _EDIT_FILE_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _EDIT_FILE_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.LOW_RISK_WRITE

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return ()

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("path",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.WORKSPACE_WRITE

    @property
    def audit_required(self) -> bool:
        return True

    @property
    def schema_version(self) -> str:
        return "tool-schema-v1"

    @property
    def default_timeout_seconds(self) -> float | None:
        return 5.0

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
        return edit_file(
            self.manager,
            self.workspace,
            str(tool_input.input_payload["path"]),
            str(tool_input.input_payload["old_text"]),
            str(tool_input.input_payload["new_text"]),
            tool_input=tool_input,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceGrepOptions:
    executable: str = "rg"
    max_results: int = 100
    snippet_char_limit: int = 240
    excluded_globs: tuple[str, ...] = (
        ".runtime/logs/**",
        "node_modules/**",
        ".venv/**",
        "venv/**",
        "dist/**",
        "build/**",
        "coverage/**",
        "__pycache__/**",
    )


@dataclass(frozen=True, slots=True)
class GrepResultItem:
    path: str
    line_number: int
    snippet: str
    snippet_truncated: bool

    def as_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line_number": self.line_number,
            "snippet": self.snippet,
            "snippet_truncated": self.snippet_truncated,
        }


@dataclass(frozen=True, slots=True)
class GrepTool:
    manager: WorkspaceManager
    workspace: RunWorkspace
    options: WorkspaceGrepOptions = WorkspaceGrepOptions()

    @property
    def name(self) -> str:
        return "grep"

    @property
    def category(self) -> str:
        return "workspace"

    @property
    def description(self) -> str:
        return "Search workspace text content with local ripgrep."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _GREP_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _GREP_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.READ_ONLY

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return ()

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("path",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.WORKSPACE_READ

    @property
    def audit_required(self) -> bool:
        return False

    @property
    def schema_version(self) -> str:
        return "tool-schema-v1"

    @property
    def default_timeout_seconds(self) -> float | None:
        return 5.0

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
        return grep(
            self.manager,
            self.workspace,
            str(tool_input.input_payload["pattern"]),
            str(tool_input.input_payload["path"]),
            options=self.options,
            tool_input=tool_input,
        )


def read_file(
    manager: WorkspaceManager,
    workspace: RunWorkspace,
    path: str,
    *,
    tool_input: ToolInput,
) -> ToolResult:
    try:
        resolved = manager.assert_inside_workspace(
            path,
            workspace=workspace,
            trace_context=tool_input.trace_context,
        )
    except ToolWorkspaceBoundaryError as exc:
        return _workspace_boundary_failed_result(
            tool_input,
            tool_name="read_file",
            target=exc.target,
        )
    normalized_path = _relative_path(workspace, resolved)
    if _is_excluded_path(normalized_path, workspace):
        return _failed_result(
            tool_input,
            tool_name="read_file",
            path=normalized_path,
            reason="workspace_path_excluded",
        )
    if resolved.suffix.lower() in _RICH_MEDIA_SUFFIXES:
        return _failed_result(
            tool_input,
            tool_name="read_file",
            path=normalized_path,
            reason="unsupported_file_type",
        )
    try:
        raw_content = resolved.read_bytes()
    except OSError:
        return _failed_result(
            tool_input,
            tool_name="read_file",
            path=normalized_path,
            reason="file_unreadable",
        )
    if b"\0" in raw_content:
        return _failed_result(
            tool_input,
            tool_name="read_file",
            path=normalized_path,
            reason="not_utf8_text",
        )
    try:
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        return _failed_result(
            tool_input,
            tool_name="read_file",
            path=normalized_path,
            reason="not_utf8_text",
        )
    return ToolResult(
        tool_name="read_file",
        call_id=tool_input.call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={"path": normalized_path, "content": content},
        output_preview=_preview(f"{normalized_path}\n{content}"),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def glob(
    manager: WorkspaceManager,
    workspace: RunWorkspace,
    pattern: str,
    *,
    tool_input: ToolInput,
) -> ToolResult:
    if not _is_safe_glob_pattern(pattern):
        return _failed_result(
            tool_input,
            tool_name="glob",
            path=pattern,
            reason="invalid_glob_pattern",
            target_key="pattern",
        )
    try:
        manager.assert_inside_workspace(
            pattern,
            workspace=workspace,
            trace_context=tool_input.trace_context,
        )
    except ToolWorkspaceBoundaryError as exc:
        return _workspace_boundary_failed_result(
            tool_input,
            tool_name="glob",
            target=exc.target,
        )
    matched_paths: list[str] = []
    for candidate in workspace.root.glob(pattern):
        if not candidate.is_file():
            continue
        try:
            relative_candidate = candidate.relative_to(workspace.root).as_posix()
        except ValueError:
            return _failed_result(
                tool_input,
                tool_name="glob",
                path=str(candidate),
                reason="workspace_candidate_outside",
            )
        try:
            manager.assert_inside_workspace(
                relative_candidate,
                workspace=workspace,
                trace_context=tool_input.trace_context,
            )
        except ToolWorkspaceBoundaryError as exc:
            return _workspace_boundary_failed_result(
                tool_input,
                tool_name="glob",
                target=exc.target,
            )
        if _is_excluded_path(relative_candidate, workspace):
            continue
        matched_paths.append(relative_candidate)

    matches = [
        {"path": path, "path_type": "file"}
        for path in sorted(
            matched_paths
        )
    ]
    return ToolResult(
        tool_name="glob",
        call_id=tool_input.call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={"matches": matches},
        output_preview=_preview("\n".join(item["path"] for item in matches)),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def write_file(
    manager: WorkspaceManager,
    workspace: RunWorkspace,
    path: str,
    content: str,
    *,
    tool_input: ToolInput,
) -> ToolResult:
    try:
        resolved = manager.assert_inside_workspace(
            path,
            workspace=workspace,
            trace_context=tool_input.trace_context,
        )
    except ToolWorkspaceBoundaryError as exc:
        return _workspace_boundary_failed_result(
            tool_input,
            tool_name="write_file",
            target=exc.target,
        )
    normalized_path = _relative_path(workspace, resolved)
    if _is_excluded_path(normalized_path, workspace):
        return _failed_result(
            tool_input,
            tool_name="write_file",
            path=normalized_path,
            reason="workspace_path_excluded",
        )
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(content.encode("utf-8"))
    except OSError:
        return _failed_result(
            tool_input,
            tool_name="write_file",
            path=normalized_path,
            reason="file_unwritable",
        )
    bytes_written = len(content.encode("utf-8"))
    return ToolResult(
        tool_name="write_file",
        call_id=tool_input.call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={"path": normalized_path, "bytes_written": bytes_written},
        output_preview=_write_file_preview(normalized_path, bytes_written, content),
        side_effect_refs=[_file_edit_trace_ref(workspace, tool_input, normalized_path)],
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def edit_file(
    manager: WorkspaceManager,
    workspace: RunWorkspace,
    path: str,
    old_text: str,
    new_text: str,
    *,
    tool_input: ToolInput,
) -> ToolResult:
    try:
        resolved = manager.assert_inside_workspace(
            path,
            workspace=workspace,
            trace_context=tool_input.trace_context,
        )
    except ToolWorkspaceBoundaryError as exc:
        return _workspace_boundary_failed_result(
            tool_input,
            tool_name="edit_file",
            target=exc.target,
        )
    normalized_path = _relative_path(workspace, resolved)
    if _is_excluded_path(normalized_path, workspace):
        return _failed_result(
            tool_input,
            tool_name="edit_file",
            path=normalized_path,
            reason="workspace_path_excluded",
        )
    try:
        content = resolved.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return _failed_result(
            tool_input,
            tool_name="edit_file",
            path=normalized_path,
            reason="not_utf8_text",
        )
    except OSError:
        return _failed_result(
            tool_input,
            tool_name="edit_file",
            path=normalized_path,
            reason="file_unreadable",
        )

    replacements = _count_exact_matches(content, old_text)
    if replacements == 0:
        return _failed_result(
            tool_input,
            tool_name="edit_file",
            path=normalized_path,
            reason="edit_target_missing",
        )
    if replacements > 1:
        return _failed_result(
            tool_input,
            tool_name="edit_file",
            path=normalized_path,
            reason="edit_target_not_unique",
        )

    updated_content = content.replace(old_text, new_text, 1)
    try:
        resolved.write_bytes(updated_content.encode("utf-8"))
    except OSError:
        return _failed_result(
            tool_input,
            tool_name="edit_file",
            path=normalized_path,
            reason="file_unwritable",
        )
    bytes_written = len(updated_content.encode("utf-8"))
    return ToolResult(
        tool_name="edit_file",
        call_id=tool_input.call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={
            "path": normalized_path,
            "replacements": 1,
            "bytes_written": bytes_written,
        },
        output_preview=_edit_file_preview(
            normalized_path,
            bytes_written,
            updated_content,
        ),
        side_effect_refs=[_file_edit_trace_ref(workspace, tool_input, normalized_path)],
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def grep(
    manager: WorkspaceManager,
    workspace: RunWorkspace,
    pattern: str,
    path: str,
    *,
    options: WorkspaceGrepOptions,
    tool_input: ToolInput,
) -> ToolResult:
    try:
        resolved = manager.assert_inside_workspace(
            path,
            workspace=workspace,
            trace_context=tool_input.trace_context,
        )
    except ToolWorkspaceBoundaryError as exc:
        return _workspace_boundary_failed_result(
            tool_input,
            tool_name="grep",
            target=exc.target,
        )

    normalized_path = _relative_path(workspace, resolved) or "."
    executable = shutil.which(options.executable)
    if executable is None:
        return _tool_error_result(
            tool_input,
            tool_name="grep",
            error_code=ErrorCode.INTERNAL_ERROR,
            safe_details={"path": normalized_path, "reason": "rg_unavailable"},
        )

    command = [
        executable,
        "--json",
        "--line-number",
        "--color",
        "never",
        "--hidden",
        "--no-messages",
    ]
    for glob_pattern in options.excluded_globs:
        command.extend(["-g", f"!{glob_pattern}"])
    # Use -e/-- so user-controlled pattern/path cannot be parsed as rg options.
    command.extend(["-e", pattern, "--", normalized_path])

    try:
        completed = subprocess.run(
            command,
            cwd=workspace.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=tool_input.timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return _tool_error_result(
            tool_input,
            tool_name="grep",
            error_code=ErrorCode.TOOL_TIMEOUT,
            safe_details={"timeout_seconds": tool_input.timeout_seconds},
        )
    except OSError:
        return _tool_error_result(
            tool_input,
            tool_name="grep",
            error_code=ErrorCode.INTERNAL_ERROR,
            safe_details={"path": normalized_path, "reason": "rg_failed"},
        )

    if completed.returncode == 1:
        return _grep_success_result(
            tool_input,
            matches=[],
            truncated=False,
        )
    if completed.returncode != 0:
        reason = (
            "rg_permission_denied"
            if "permission denied" in completed.stderr.lower()
            else "rg_failed"
        )
        return _tool_error_result(
            tool_input,
            tool_name="grep",
            error_code=ErrorCode.INTERNAL_ERROR,
            safe_details={
                "path": normalized_path,
                "reason": reason,
                "returncode": completed.returncode,
            },
        )

    matches: list[GrepResultItem] = []
    truncated = False
    for raw_line in completed.stdout.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            return _tool_error_result(
                tool_input,
                tool_name="grep",
                error_code=ErrorCode.INTERNAL_ERROR,
                safe_details={"path": normalized_path, "reason": "rg_json_invalid"},
            )
        if event.get("type") != "match":
            continue
        item_or_error = _grep_result_item(
            event,
            workspace=workspace,
            options=options,
            tool_input=tool_input,
        )
        if isinstance(item_or_error, ToolResult):
            return item_or_error
        if item_or_error is None:
            continue
        if len(matches) >= options.max_results:
            truncated = True
            break
        matches.append(item_or_error)

    ordered_matches = sorted(
        matches,
        key=lambda item: (item.path, item.line_number, item.snippet),
    )
    return _grep_success_result(
        tool_input,
        matches=ordered_matches,
        truncated=truncated,
    )


def _failed_result(
    tool_input: ToolInput,
    *,
    tool_name: str,
    path: str,
    reason: str,
    target_key: str = "path",
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        call_id=tool_input.call_id,
        status=ToolResultStatus.FAILED,
        error=ToolError.from_code(
            ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
            trace_context=tool_input.trace_context,
            safe_details={target_key: path, "reason": reason},
        ),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def _tool_error_result(
    tool_input: ToolInput,
    *,
    tool_name: str,
    error_code: ErrorCode,
    safe_details: dict[str, object],
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        call_id=tool_input.call_id,
        status=ToolResultStatus.FAILED,
        error=ToolError.from_code(
            error_code,
            trace_context=tool_input.trace_context,
            safe_details=safe_details,
        ),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def _workspace_boundary_failed_result(
    tool_input: ToolInput,
    *,
    tool_name: str,
    target: str,
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        call_id=tool_input.call_id,
        status=ToolResultStatus.FAILED,
        error=ToolError.from_code(
            ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION,
            trace_context=tool_input.trace_context,
            safe_details={"target": target},
        ),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def _grep_success_result(
    tool_input: ToolInput,
    *,
    matches: Sequence[GrepResultItem],
    truncated: bool,
) -> ToolResult:
    payload_matches = [item.as_payload() for item in matches]
    return ToolResult(
        tool_name="grep",
        call_id=tool_input.call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={"matches": payload_matches, "truncated": truncated},
        output_preview=_preview(
            "\n".join(
                f"{item['path']}:{item['line_number']}:{item['snippet']}"
                for item in payload_matches
            )
        ),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def _grep_result_item(
    event: object,
    *,
    workspace: RunWorkspace,
    options: WorkspaceGrepOptions,
    tool_input: ToolInput,
) -> GrepResultItem | ToolResult | None:
    if not isinstance(event, Mapping):
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    path_data = data.get("path")
    lines_data = data.get("lines")
    line_number = data.get("line_number")
    if not isinstance(path_data, Mapping) or not isinstance(lines_data, Mapping):
        return None
    relative_path = str(path_data.get("text", "")).replace("\\", "/")
    if _is_excluded_path(relative_path, workspace):
        return None
    if _is_grep_glob_excluded(relative_path, options.excluded_globs):
        return None
    snippet, snippet_truncated, blocked = _grep_snippet(
        str(lines_data.get("text", "")).rstrip("\r\n"),
        limit=options.snippet_char_limit,
    )
    if blocked:
        return _tool_error_result(
            tool_input,
            tool_name="grep",
            error_code=ErrorCode.INTERNAL_ERROR,
            safe_details={
                "path": relative_path,
                "line_number": int(line_number or 0),
                "reason": "grep_match_blocked",
            },
        )
    return GrepResultItem(
        path=relative_path,
        line_number=int(line_number or 0),
        snippet=snippet,
        snippet_truncated=snippet_truncated,
    )


def _grep_snippet(text: str, *, limit: int) -> tuple[str, bool, bool]:
    redacted = RedactionPolicy(
        max_text_length=max(len(text), limit, 32),
        excerpt_length=max(len(text), limit, 32),
    ).summarize_text(
        text,
        payload_type="grep_match",
    )
    if redacted.redaction_status.value == "blocked":
        return "", False, True
    visible = str(redacted.redacted_payload or "")
    if len(visible) <= limit:
        return visible, False, False
    if limit <= 3:
        return "." * max(limit, 0), True, False
    return f"{visible[: limit - 3]}...", True, False


def _is_grep_glob_excluded(
    relative_path: str,
    excluded_globs: Sequence[str],
) -> bool:
    normalized_path = _normalize_relative_path(relative_path)
    return any(
        fnmatch.fnmatchcase(normalized_path, glob_pattern.rstrip("/"))
        or (
            glob_pattern.endswith("/**")
            and (
                normalized_path == glob_pattern[:-3].rstrip("/")
                or normalized_path.startswith(f"{glob_pattern[:-3].rstrip('/')}/")
            )
        )
        for glob_pattern in excluded_globs
    )


def _relative_path(workspace: RunWorkspace, path: Path) -> str:
    return path.resolve(strict=False).relative_to(workspace.root).as_posix()


def _is_excluded_path(relative_path: str, workspace: RunWorkspace) -> bool:
    normalized_path = _normalize_relative_path(relative_path)
    excluded_paths = (
        *(_normalize_relative_path(path) for path in workspace.excluded_relative_paths),
        *_PLATFORM_PRIVATE_RELATIVE_PATHS,
    )
    return any(
        normalized_path == excluded or normalized_path.startswith(f"{excluded}/")
        for excluded in excluded_paths
    )


def _is_safe_glob_pattern(pattern: str) -> bool:
    normalized = pattern.replace("\\", "/")
    if "\0" in normalized or normalized.startswith(("/", "\\")):
        return False
    if PureWindowsPath(pattern).drive:
        return False
    return ".." not in _normalize_relative_path(normalized).split("/")


def _normalize_relative_path(path: str) -> str:
    normalized = posixpath.normpath(path.replace("\\", "/").strip())
    if normalized == ".":
        return ""
    return normalized.rstrip("/")


def _count_exact_matches(content: str, target: str) -> int:
    count = 0
    start = 0
    while True:
        position = content.find(target, start)
        if position == -1:
            return count
        count += 1
        start = position + 1


def _file_edit_trace_ref(
    workspace: RunWorkspace,
    tool_input: ToolInput,
    normalized_path: str,
) -> str:
    return f"file_edit_trace:{workspace.run_id}:{tool_input.call_id}:{normalized_path}"


def _write_file_preview(
    normalized_path: str,
    bytes_written: int,
    content: str,
) -> str:
    summary = f"Wrote {normalized_path} ({bytes_written} bytes)"
    if len(content) <= _PREVIEW_LIMIT:
        return summary
    return _preview(f"{summary}\n{content}")


def _edit_file_preview(
    normalized_path: str,
    bytes_written: int,
    updated_content: str,
) -> str:
    summary = f"Edited {normalized_path} (1 replacement, {bytes_written} bytes)"
    if len(updated_content) <= _PREVIEW_LIMIT:
        return summary
    return _preview(f"{summary}\n{updated_content}")


def _preview(value: str) -> str:
    if not value:
        return "(no output)"
    redacted = _PREVIEW_REDACTION.summarize_text(
        value,
        payload_type="workspace_tool_preview",
    )
    if isinstance(redacted.redacted_payload, str) and redacted.redacted_payload:
        return redacted.redacted_payload
    return redacted.excerpt or "[redacted]"


__all__ = [
    "FileEditTool",
    "FileReadTool",
    "FileWriteTool",
    "GrepResultItem",
    "GrepTool",
    "GlobTool",
    "WorkspaceGrepOptions",
    "edit_file",
    "grep",
    "glob",
    "read_file",
    "write_file",
]
