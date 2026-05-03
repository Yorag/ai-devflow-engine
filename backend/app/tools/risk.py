from __future__ import annotations

import hashlib
import json
import posixpath
import re
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.enums import ToolRiskCategory, ToolRiskLevel

if TYPE_CHECKING:
    from backend.app.domain.trace_context import TraceContext
    from backend.app.tools.execution_gate import ToolExecutionRequest
    from backend.app.tools.protocol import ToolProtocol


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolConfirmationGrant(_StrictBaseModel):
    tool_confirmation_id: str = Field(min_length=1)
    confirmation_object_ref: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    input_digest: str = Field(min_length=1)
    target_summary: str = Field(min_length=1)
    risk_level: ToolRiskLevel
    risk_categories: list[ToolRiskCategory] = Field(default_factory=list)


class ToolConfirmationRequestRecord(_StrictBaseModel):
    tool_confirmation_id: str = Field(min_length=1)
    confirmation_object_ref: str = Field(min_length=1)


class ToolRiskAssessment(_StrictBaseModel):
    risk_level: ToolRiskLevel
    risk_categories: list[ToolRiskCategory] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    command_preview: str | None = None
    target_summary: str = Field(min_length=1)
    expected_side_effects: list[str] = Field(default_factory=list)
    alternative_path_summary: str | None = None
    input_digest: str = Field(min_length=1)
    confirmation_object_ref: str = Field(min_length=1)

    @property
    def requires_confirmation(self) -> bool:
        return self.risk_level is ToolRiskLevel.HIGH_RISK

    @property
    def is_blocked(self) -> bool:
        return self.risk_level is ToolRiskLevel.BLOCKED


class ToolConfirmationRequestPort(Protocol):
    def create_request(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        confirmation_object_ref: str,
        tool_name: str,
        command_preview: str | None,
        target_summary: str,
        risk_level: ToolRiskLevel,
        risk_categories: list[ToolRiskCategory],
        reason: str,
        expected_side_effects: list[str],
        alternative_path_summary: str | None,
        planned_deny_followup_action: str | None = None,
        planned_deny_followup_summary: str | None = None,
        trace_context: TraceContext,
    ) -> Any: ...


_READ_ONLY_TOOLS = frozenset({"read_file", "glob", "grep"})
_WRITE_TOOLS = frozenset({"write_file", "edit_file"})
_MANIFEST_FILENAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "setup.cfg",
        "cargo.toml",
        "go.mod",
    }
)
_LOCKFILE_FILENAMES = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "uv.lock",
        "poetry.lock",
        "cargo.lock",
        "go.sum",
    }
)
_CREDENTIAL_FILENAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)
_PATH_KEYS = ("path", "target_path", "file_path", "destination", "dest", "source")
_PATH_LIST_KEYS = ("paths", "target_paths", "files", "file_paths")
_DEPENDENCY_COMMAND_PATTERN = re.compile(
    r"\b(?:npm|pnpm|yarn)\s+(?:install|i|add|update|upgrade)\b"
    r"|\b(?:pip|pip3)\s+install\b"
    r"|\buv\s+(?:add|pip\s+install|sync)\b"
    r"|\bpoetry\s+(?:add|install|update)\b"
    r"|\b(?:install|update|upgrade)\b.*\b(?:dependency|dependencies|package|packages)\b",
    re.IGNORECASE,
)
_NETWORK_DOWNLOAD_COMMAND_PATTERN = re.compile(
    r"\b(?:curl|wget|Invoke-WebRequest|iwr)\b", re.IGNORECASE
)
_DELETE_MOVE_COMMAND_PATTERN = re.compile(
    r"\b(?:rm|del|rmdir|mv|move|Remove-Item|Move-Item)\b", re.IGNORECASE
)
_MIGRATION_COMMAND_PATTERN = re.compile(
    r"\b(?:migrate|migration|alembic\s+upgrade|prisma\s+migrate)\b",
    re.IGNORECASE,
)
_READ_COMMAND_PATTERN = re.compile(
    r"\b(?:printenv|cat|type|Get-Content)\b",
    re.IGNORECASE,
)
_CREDENTIAL_COMMAND_PATTERN = re.compile(
    r"\b(?:printenv|cat|type|Get-Content)\b.*(?:\.env|\.npmrc|api[_-]?key|apikey|secret|token|password|private[_-]?key)"
    r"|(?:/etc/passwd|~/.ssh|id_rsa)",
    re.IGNORECASE,
)
_COMMAND_TOKEN_PATTERN = re.compile(r'''[^\s'"]+|'[^']*'|"[^"]*"''')


class ToolRiskClassifier:
    def classify(
        self,
        *,
        tool: ToolProtocol,
        request: ToolExecutionRequest,
    ) -> ToolRiskAssessment:
        input_digest = _input_digest(request.input_payload)
        confirmation_object_ref = (
            f"tool-call:{tool.name}:{request.call_id}:{input_digest[:12]}"
        )
        command = _command_preview(request.input_payload)
        targets = _request_targets(request.input_payload)
        target_summary = _target_summary(command=command, targets=targets, tool_name=tool.name)

        blocked_categories = _blocked_categories(
            command=command,
            targets=targets,
            tool_name=tool.name,
        )
        if blocked_categories:
            return _assessment(
                risk_level=ToolRiskLevel.BLOCKED,
                risk_categories=blocked_categories,
                reason="Tool action targets blocked platform or credential boundaries.",
                command_preview=command,
                target_summary=target_summary,
                input_digest=input_digest,
                confirmation_object_ref=confirmation_object_ref,
                expected_side_effects=["Action is blocked before execution."],
            )

        high_risk_categories = _high_risk_categories(
            command=command,
            payload=request.input_payload,
            targets=targets,
            tool_name=tool.name,
        )
        if high_risk_categories:
            return _assessment(
                risk_level=ToolRiskLevel.HIGH_RISK,
                risk_categories=high_risk_categories,
                reason="Tool action requires confirmation before execution.",
                command_preview=command,
                target_summary=target_summary,
                input_digest=input_digest,
                confirmation_object_ref=confirmation_object_ref,
                expected_side_effects=_side_effects_for(high_risk_categories),
                alternative_path_summary=_alternative_path_summary_for(
                    high_risk_categories
                ),
            )

        if tool.name in _READ_ONLY_TOOLS:
            return _assessment(
                risk_level=ToolRiskLevel.READ_ONLY,
                risk_categories=[],
                reason="Tool action is read-only.",
                command_preview=command,
                target_summary=target_summary,
                input_digest=input_digest,
                confirmation_object_ref=confirmation_object_ref,
            )

        if _is_precise_single_file_edit(tool_name=tool.name, payload=request.input_payload):
            return _assessment(
                risk_level=ToolRiskLevel.LOW_RISK_WRITE,
                risk_categories=[],
                reason="Tool action edits one explicit workspace file.",
                command_preview=command,
                target_summary=target_summary,
                input_digest=input_digest,
                confirmation_object_ref=confirmation_object_ref,
                expected_side_effects=["Modify one workspace file."],
            )

        if getattr(tool, "side_effect_level", None) is not None and str(
            tool.side_effect_level
        ) != "none":
            return _assessment(
                risk_level=ToolRiskLevel.HIGH_RISK,
                risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
                reason="Side-effecting tool action has no narrower low-risk classification.",
                command_preview=command,
                target_summary=target_summary,
                input_digest=input_digest,
                confirmation_object_ref=confirmation_object_ref,
                expected_side_effects=["May change workspace or external state."],
            )

        return _assessment(
            risk_level=ToolRiskLevel.READ_ONLY,
            risk_categories=[],
            reason="Tool action has no declared side effects.",
            command_preview=command,
            target_summary=target_summary,
            input_digest=input_digest,
            confirmation_object_ref=confirmation_object_ref,
        )


def _assessment(
    *,
    risk_level: ToolRiskLevel,
    risk_categories: list[ToolRiskCategory],
    reason: str,
    command_preview: str | None,
    target_summary: str,
    expected_side_effects: list[str] | None = None,
    alternative_path_summary: str | None = None,
    input_digest: str,
    confirmation_object_ref: str,
) -> ToolRiskAssessment:
    return ToolRiskAssessment(
        risk_level=risk_level,
        risk_categories=_dedupe_categories(risk_categories),
        reason=reason,
        command_preview=command_preview,
        target_summary=target_summary,
        expected_side_effects=expected_side_effects or [],
        alternative_path_summary=alternative_path_summary,
        input_digest=input_digest,
        confirmation_object_ref=confirmation_object_ref,
    )


def _input_digest(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _command_preview(payload: dict[str, Any]) -> str | None:
    command = payload.get("command")
    if isinstance(command, str) and command.strip():
        return command.strip()
    return None


def _request_targets(payload: dict[str, Any]) -> tuple[str, ...]:
    targets: list[str] = []
    for key in _PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            targets.append(value.strip())
    for key in _PATH_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            targets.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
    return tuple(targets)


def _target_summary(
    *,
    command: str | None,
    targets: tuple[str, ...],
    tool_name: str,
) -> str:
    if command is not None:
        return f"command: {command}"
    if len(targets) == 1:
        return f"path: {targets[0]}"
    if targets:
        return f"paths: {', '.join(targets)}"
    return f"tool: {tool_name}"


def _blocked_categories(
    *,
    command: str | None,
    targets: tuple[str, ...],
    tool_name: str,
) -> list[ToolRiskCategory]:
    categories: list[ToolRiskCategory] = []
    if any(_is_platform_runtime_path(target) for target in targets):
        categories.append(ToolRiskCategory.PLATFORM_RUNTIME_MUTATION)
    if any(_is_path_escape(target) for target in targets):
        categories.append(ToolRiskCategory.PATH_ESCAPE)
    if tool_name in _READ_ONLY_TOOLS and any(_is_credential_path(target) for target in targets):
        categories.append(ToolRiskCategory.CREDENTIAL_ACCESS)
    if command is not None:
        command_targets = _command_targets(command)
        if any(_is_platform_runtime_path(target) for target in command_targets):
            categories.append(ToolRiskCategory.PLATFORM_RUNTIME_MUTATION)
        if any(_is_path_escape(target) for target in command_targets):
            categories.append(ToolRiskCategory.PATH_ESCAPE)
        if _command_reads_credential(command, command_targets):
            categories.append(ToolRiskCategory.CREDENTIAL_ACCESS)
    return _dedupe_categories(categories)


def _high_risk_categories(
    *,
    command: str | None,
    payload: dict[str, Any],
    targets: tuple[str, ...],
    tool_name: str,
) -> list[ToolRiskCategory]:
    categories: list[ToolRiskCategory] = []
    if tool_name in _WRITE_TOOLS:
        for target in targets:
            normalized = _normalize_path(target)
            basename = normalized.rsplit("/", 1)[-1]
            if _is_env_path(normalized):
                categories.append(ToolRiskCategory.ENVIRONMENT_CONFIG_CHANGE)
            if basename in _LOCKFILE_FILENAMES:
                categories.append(ToolRiskCategory.LOCKFILE_CHANGE)
            if basename in _MANIFEST_FILENAMES:
                categories.append(ToolRiskCategory.DEPENDENCY_CHANGE)
            if _is_migration_path(normalized):
                categories.append(ToolRiskCategory.DATABASE_MIGRATION)
            if _is_broad_target(normalized):
                categories.append(ToolRiskCategory.BROAD_WRITE)

        if _is_broad_payload(payload=payload, targets=targets, tool_name=tool_name):
            categories.append(ToolRiskCategory.BROAD_WRITE)

    if command is not None:
        if _DEPENDENCY_COMMAND_PATTERN.search(command):
            categories.append(ToolRiskCategory.DEPENDENCY_CHANGE)
        if _NETWORK_DOWNLOAD_COMMAND_PATTERN.search(command):
            categories.append(ToolRiskCategory.NETWORK_DOWNLOAD)
        if _DELETE_MOVE_COMMAND_PATTERN.search(command):
            categories.append(ToolRiskCategory.FILE_DELETE_OR_MOVE)
        if _MIGRATION_COMMAND_PATTERN.search(command):
            categories.append(ToolRiskCategory.DATABASE_MIGRATION)
        if _mentions_lockfile(command):
            categories.append(ToolRiskCategory.LOCKFILE_CHANGE)
        if _mentions_env_mutation(command):
            categories.append(ToolRiskCategory.ENVIRONMENT_CONFIG_CHANGE)

    return _dedupe_categories(categories)


def _is_precise_single_file_edit(*, tool_name: str, payload: dict[str, Any]) -> bool:
    path = payload.get("path")
    old_text = payload.get("old_text")
    new_text = payload.get("new_text")
    return (
        tool_name == "edit_file"
        and isinstance(path, str)
        and path.strip() != ""
        and isinstance(old_text, str)
        and old_text != ""
        and isinstance(new_text, str)
        and not _is_root_like_target(path)
        and not _is_broad_target(_normalize_path(path))
    )


def _is_broad_payload(
    *,
    payload: dict[str, Any],
    targets: tuple[str, ...],
    tool_name: str,
) -> bool:
    if tool_name not in _WRITE_TOOLS:
        return False
    if len(targets) != 1:
        return True
    if _is_root_like_target(targets[0]):
        return True
    return any(isinstance(payload.get(key), list) for key in _PATH_LIST_KEYS)


def _is_platform_runtime_path(target: str) -> bool:
    normalized = _normalize_path(target)
    return normalized == ".runtime" or normalized.startswith(".runtime/")


def _is_path_escape(target: str) -> bool:
    normalized = _normalize_path(target)
    return (
        normalized == ".."
        or normalized.startswith("../")
        or normalized.startswith("/")
        or (len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/")
    )


def _is_env_path(normalized_path: str) -> bool:
    return normalized_path == ".env" or "/.env" in normalized_path or normalized_path.startswith(".env.")


def _is_credential_path(target: str) -> bool:
    normalized = _normalize_path(target)
    basename = normalized.rsplit("/", 1)[-1]
    return (
        basename in _CREDENTIAL_FILENAMES
        or basename.startswith(".env.")
        or basename.endswith(".pem")
        or basename.endswith(".key")
        or "/.ssh/" in f"/{normalized}/"
        or "/secrets/" in f"/{normalized}/"
    )


def _is_migration_path(normalized_path: str) -> bool:
    segments = normalized_path.split("/")
    return any(
        segment in {"migrations", "migration", "alembic", "versions"}
        for segment in segments
    ) or "migration" in segments[-1]


def _is_broad_target(normalized_path: str) -> bool:
    return _is_root_like_target(normalized_path) or any(
        marker in normalized_path for marker in ("*", "?", "[", "]")
    )


def _is_root_like_target(target: str) -> bool:
    normalized = _normalize_path(target)
    return normalized in {"", "."}


def _mentions_lockfile(command: str) -> bool:
    lowered = command.lower()
    return any(filename in lowered for filename in _LOCKFILE_FILENAMES)


def _mentions_env_mutation(command: str) -> bool:
    lowered = command.lower()
    return ".env" in lowered and any(operator in command for operator in (">", ">>", "set "))


def _command_reads_credential(command: str, targets: tuple[str, ...]) -> bool:
    return bool(_CREDENTIAL_COMMAND_PATTERN.search(command)) or (
        bool(_READ_COMMAND_PATTERN.search(command))
        and any(_is_credential_path(target) for target in targets)
    )


def _command_targets(command: str) -> tuple[str, ...]:
    targets: list[str] = []
    for token in _COMMAND_TOKEN_PATTERN.findall(command):
        cleaned = token.strip("\"'")
        if _looks_like_path_token(cleaned):
            targets.append(cleaned)
    return tuple(targets)


def _looks_like_path_token(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    lowered = token.lower().replace("\\", "/")
    return (
        "/" in lowered
        or lowered.startswith(".")
        or lowered in _CREDENTIAL_FILENAMES
        or lowered.startswith(".env.")
        or lowered.endswith((".pem", ".key"))
    )


def _normalize_path(target: str) -> str:
    normalized = posixpath.normpath(target.strip().replace("\\", "/"))
    if normalized == ".":
        return ""
    return normalized.lower()


def _side_effects_for(categories: list[ToolRiskCategory]) -> list[str]:
    effects: list[str] = []
    if ToolRiskCategory.DEPENDENCY_CHANGE in categories:
        effects.append("May install, upgrade, or alter project dependencies.")
    if ToolRiskCategory.LOCKFILE_CHANGE in categories:
        effects.append("May modify dependency lockfiles.")
    if ToolRiskCategory.ENVIRONMENT_CONFIG_CHANGE in categories:
        effects.append("May alter environment or configuration files.")
    if ToolRiskCategory.DATABASE_MIGRATION in categories:
        effects.append("May alter database migration state.")
    if ToolRiskCategory.BROAD_WRITE in categories:
        effects.append("May modify multiple files or broad path targets.")
    if ToolRiskCategory.FILE_DELETE_OR_MOVE in categories:
        effects.append("May delete or move files.")
    if ToolRiskCategory.NETWORK_DOWNLOAD in categories:
        effects.append("May download content from the network.")
    if not effects:
        effects.append("May change workspace or external state.")
    return effects


def _alternative_path_summary_for(
    categories: list[ToolRiskCategory],
) -> str | None:
    no_safe_fallback = {
        ToolRiskCategory.DEPENDENCY_CHANGE,
        ToolRiskCategory.LOCKFILE_CHANGE,
        ToolRiskCategory.ENVIRONMENT_CONFIG_CHANGE,
        ToolRiskCategory.DATABASE_MIGRATION,
        ToolRiskCategory.FILE_DELETE_OR_MOVE,
        ToolRiskCategory.NETWORK_DOWNLOAD,
        ToolRiskCategory.UNKNOWN_COMMAND,
    }
    if any(category in no_safe_fallback for category in categories):
        return None
    if ToolRiskCategory.BROAD_WRITE in categories:
        return "Use a narrower edit scope or a read-only inspection when possible."
    return None


def _dedupe_categories(
    categories: list[ToolRiskCategory],
) -> list[ToolRiskCategory]:
    seen: set[ToolRiskCategory] = set()
    deduped: list[ToolRiskCategory] = []
    for category in categories:
        if category not in seen:
            deduped.append(category)
            seen.add(category)
    return deduped


__all__ = [
    "ToolConfirmationGrant",
    "ToolConfirmationRequestPort",
    "ToolConfirmationRequestRecord",
    "ToolRiskAssessment",
    "ToolRiskClassifier",
]
