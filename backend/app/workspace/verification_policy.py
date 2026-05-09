from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import posixpath
import shlex
from typing import Literal, Sequence


_VERSION_PROBES = {
    ("python", "--version"),
    ("uv", "--version"),
    ("node", "--version"),
    ("npm", "--version"),
    ("git", "--version"),
}
_SHELL_META_TOKENS = {"&&", "||", "|", ";", ">", ">>", "<", "`"}
_SHELL_META_SUBSTRINGS = (";", "|", "&", ">", "<", "`", "$(", "${")
_DEPENDENCY_COMMANDS = {
    "install",
    "i",
    "add",
    "update",
    "upgrade",
    "ci",
}
_REJECTED_EXECUTABLES = {
    "cat",
    "curl",
    "del",
    "grep",
    "iwr",
    "ls",
    "move",
    "mv",
    "rm",
    "rmdir",
    "type",
    "wget",
    "get-content",
    "invoke-webrequest",
    "move-item",
    "remove-item",
}
_DIRECT_READ_ONLY_INSPECTION_EXECUTABLES = {
    "cat",
    "dir",
    "findstr",
    "get-childitem",
    "get-content",
    "grep",
    "ls",
    "rg",
    "select-string",
    "type",
}
_PIPE_SOURCE_EXECUTABLES = {"cat", "get-content", "type"}
_PIPE_FILTER_EXECUTABLES = {"findstr", "grep", "select-string"}
_CREDENTIAL_SEGMENTS = {".ssh", "secrets"}
_CREDENTIAL_FILENAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
_RUNTIME_PREFIXES = {".runtime"}
_GIT_READ_ONLY_SUBCOMMANDS = {"status", "diff"}


@dataclass(frozen=True, slots=True)
class VerificationCommandDecision:
    allowed: bool
    read_only: bool
    reason: str
    argv: tuple[str, ...] = ()
    execution_mode: Literal["argv", "inspection"] = "argv"
    working_directory: Path | None = None


def classify_verification_command(
    command: str,
    *,
    workspace_root: Path | None = None,
) -> VerificationCommandDecision:
    argv = _parse_command(command)
    if not argv:
        return VerificationCommandDecision(
            allowed=False,
            read_only=False,
            reason="command must parse as one shell-free argv vector",
        )

    normalized = _normalize_verification_argv(argv, workspace_root=workspace_root)
    if normalized is not None:
        argv = normalized.argv
        working_directory = normalized.working_directory
    else:
        working_directory = workspace_root

    if _contains_blocked_path_argument(argv):
        return VerificationCommandDecision(
            allowed=False,
            read_only=False,
            reason="command references a blocked workspace path",
            argv=argv,
            working_directory=working_directory,
        )

    read_only_shell_mode = _read_only_shell_execution_mode(argv)
    if read_only_shell_mode is not None and _is_allowed_read_only_inspection_command(argv):
        return VerificationCommandDecision(
            allowed=True,
            read_only=True,
            reason="allowed read-only workspace inspection command",
            argv=argv,
            execution_mode=read_only_shell_mode,
            working_directory=working_directory,
        )

    if _contains_shell_meta(argv):
        return VerificationCommandDecision(
            allowed=False,
            read_only=False,
            reason="shell metacharacters and command chaining are not allowed",
            argv=argv,
            working_directory=working_directory,
        )

    executable = argv[0].lower()
    if executable in _REJECTED_EXECUTABLES:
        return VerificationCommandDecision(
            allowed=False,
            read_only=False,
            reason="direct shell/search/file commands are not verification commands",
            argv=argv,
            working_directory=working_directory,
        )

    if tuple(argv[:2]) in _VERSION_PROBES and len(argv) == 2:
        return VerificationCommandDecision(
            allowed=True,
            read_only=True,
            reason="allowed version probe",
            argv=argv,
            working_directory=working_directory,
        )

    if _is_uv_pytest(argv, workspace_root=workspace_root):
        return VerificationCommandDecision(
            allowed=True,
            read_only=True,
            reason="allowed repo-local pytest command",
            argv=argv,
            working_directory=working_directory,
        )

    if _is_frontend_script(
        argv,
        workspace_root=workspace_root,
        working_directory=working_directory,
    ):
        return VerificationCommandDecision(
            allowed=True,
            read_only=True,
            reason="allowed declared frontend script",
            argv=argv,
            working_directory=working_directory,
        )

    if _is_read_only_git_command(argv):
        return VerificationCommandDecision(
            allowed=True,
            read_only=True,
            reason="allowed read-only git command",
            argv=argv,
            working_directory=working_directory,
        )

    if command in _readme_commands(workspace_root):
        return VerificationCommandDecision(
            allowed=True,
            read_only=True,
            reason="allowed documented project command",
            argv=argv,
            working_directory=working_directory,
        )

    if _is_dependency_command(argv):
        return VerificationCommandDecision(
            allowed=False,
            read_only=False,
            reason="dependency installation or update is not verification",
            argv=argv,
            working_directory=working_directory,
        )

    return VerificationCommandDecision(
        allowed=False,
        read_only=False,
        reason="command is not in the verification allowlist",
        argv=argv,
        working_directory=working_directory,
    )


@dataclass(frozen=True, slots=True)
class NormalizedVerificationCommand:
    argv: tuple[str, ...]
    working_directory: Path | None


def _normalize_verification_argv(
    argv: tuple[str, ...],
    *,
    workspace_root: Path | None,
) -> NormalizedVerificationCommand | None:
    if not argv:
        return None
    working_directory = workspace_root
    tokens = list(argv)

    shell_segments = _split_tokens(tokens, "&&")
    if len(shell_segments) == 2 and _is_safe_cd_segment(shell_segments[0]):
        if workspace_root is None:
            return None
        target = (workspace_root / shell_segments[0][1]).resolve(strict=False)
        if not target.is_relative_to(workspace_root):
            return None
        working_directory = target
        tokens = list(shell_segments[1])
    elif len(shell_segments) > 1:
        return None

    if tokens and tokens[-1] == "2>&1":
        tokens = tokens[:-1]

    if not tokens:
        return None

    if any(token in {"&&", "||", "|", ";", ">", ">>", "<", "`"} for token in tokens):
        return None
    if any(
        any(fragment in token for fragment in ("2>", "1>", "&>", "$(", "${"))
        for token in tokens
    ):
        return None

    return NormalizedVerificationCommand(
        argv=tuple(tokens),
        working_directory=working_directory,
    )


def _parse_command(command: str) -> tuple[str, ...]:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return ()
    return tuple(argv)


def _contains_shell_meta(argv: Sequence[str]) -> bool:
    return any(
        token in _SHELL_META_TOKENS
        or any(fragment in token for fragment in _SHELL_META_SUBSTRINGS)
        for token in argv
    )


def _read_only_shell_execution_mode(
    argv: tuple[str, ...],
) -> Literal["argv", "inspection"] | None:
    if not argv:
        return None
    if any(token in {"||", ";", ">", ">>", "<", "`"} for token in argv):
        return None
    if any("$(" in token or "${" in token for token in argv):
        return None
    if any(token in {"&&", "|"} for token in argv):
        return "inspection"
    if argv[0].lower() in _DIRECT_READ_ONLY_INSPECTION_EXECUTABLES - {"rg"}:
        return "inspection"
    if argv[0].lower() == "rg":
        return "argv"
    return None


def _is_uv_pytest(argv: tuple[str, ...], *, workspace_root: Path | None) -> bool:
    if len(argv) < 3 or argv[:3] != ("uv", "run", "pytest"):
        return False
    if not _has_pytest_config(workspace_root):
        return False
    return _pytest_options_safe(argv[3:])


def _pytest_options_safe(args: Sequence[str]) -> bool:
    iterator = iter(range(len(args)))
    for index in iterator:
        token = args[index]
        if token in {"-o", "--override-ini", "--rootdir"}:
            return False
        if token.startswith(("-o=", "--override-ini=", "--rootdir=")):
            return False
        if token == "--token" or token.startswith("--token="):
            return False
    return True


def _is_frontend_script(
    argv: tuple[str, ...],
    *,
    workspace_root: Path | None,
    working_directory: Path | None,
) -> bool:
    scripts = _frontend_scripts(workspace_root)
    if not scripts:
        return False
    if len(argv) >= 5 and argv[:3] == ("npm", "--prefix", "frontend"):
        if argv[3] == "run":
            return argv[4] in scripts
        return argv[3] in scripts and argv[3] not in _DEPENDENCY_COMMANDS
    if (
        len(argv) >= 4
        and argv[0] == "npx"
        and argv[1] == "vitest"
        and argv[2] == "run"
        and working_directory is not None
        and workspace_root is not None
        and working_directory == (workspace_root / "frontend").resolve(strict=False)
    ):
        return True
    return False


def _is_allowed_read_only_inspection_command(argv: tuple[str, ...]) -> bool:
    if not argv:
        return False
    if any(token in {"||", ";", ">", ">>", "<", "`"} for token in argv):
        return False
    if any("$(" in token or "${" in token for token in argv):
        return False

    shell_segments = _split_tokens(argv, "&&")
    if len(shell_segments) > 2:
        return False
    if len(shell_segments) == 2:
        if not _is_safe_cd_segment(shell_segments[0]):
            return False
        command_tokens = shell_segments[1]
    else:
        command_tokens = shell_segments[0]

    if not command_tokens:
        return False

    pipeline_segments = _split_tokens(command_tokens, "|")
    if len(pipeline_segments) == 1:
        return _is_safe_direct_inspection_segment(pipeline_segments[0])
    if len(pipeline_segments) == 2:
        return _is_safe_pipeline(pipeline_segments[0], pipeline_segments[1])
    return False


def _split_tokens(
    argv: Sequence[str],
    separator: str,
) -> list[tuple[str, ...]]:
    segments: list[list[str]] = [[]]
    for token in argv:
        if token == separator:
            if not segments[-1]:
                return []
            segments.append([])
            continue
        segments[-1].append(token)
    if not segments or not segments[-1]:
        return []
    return [tuple(segment) for segment in segments]


def _is_safe_cd_segment(argv: tuple[str, ...]) -> bool:
    return len(argv) == 2 and argv[0].lower() == "cd" and _is_safe_inspection_path(argv[1])


def _is_safe_pipeline(
    source_segment: tuple[str, ...],
    filter_segment: tuple[str, ...],
) -> bool:
    return _is_safe_cat_segment(source_segment) and _is_safe_filter_segment(
        filter_segment,
        allow_pathless=True,
    )


def _is_safe_direct_inspection_segment(argv: tuple[str, ...]) -> bool:
    if not argv:
        return False
    executable = argv[0].lower()
    if executable in _PIPE_SOURCE_EXECUTABLES:
        return _is_safe_cat_segment(argv)
    if executable in _PIPE_FILTER_EXECUTABLES:
        return _is_safe_filter_segment(argv, allow_pathless=False)
    if executable == "rg":
        return _is_safe_filter_segment(argv, allow_pathless=False)
    if executable in {"dir", "get-childitem", "ls"}:
        return _is_safe_list_segment(argv)
    return False


def _is_safe_cat_segment(argv: tuple[str, ...]) -> bool:
    if not argv or argv[0].lower() not in _PIPE_SOURCE_EXECUTABLES:
        return False
    paths = [token for token in argv[1:] if not token.startswith("-")]
    return bool(paths) and all(_is_safe_inspection_path(path) for path in paths)


def _is_safe_filter_segment(
    argv: tuple[str, ...],
    *,
    allow_pathless: bool,
) -> bool:
    if not argv:
        return False
    executable = argv[0].lower()
    if executable not in (*_PIPE_FILTER_EXECUTABLES, "rg"):
        return False
    values = [token for token in argv[1:] if not token.startswith("-")]
    if allow_pathless:
        if len(values) < 1:
            return False
        return all(_is_safe_inspection_path(path) for path in values[1:])
    if len(values) < 2:
        return False
    return all(_is_safe_inspection_path(path) for path in values[1:])


def _is_safe_list_segment(argv: tuple[str, ...]) -> bool:
    if not argv or argv[0].lower() not in {"dir", "get-childitem", "ls"}:
        return False
    paths = [token for token in argv[1:] if not token.startswith("-")]
    return bool(paths) and all(_is_safe_inspection_path(path) for path in paths)


def _is_safe_inspection_path(token: str) -> bool:
    candidate = token.strip()
    if not candidate or candidate in {".", "./", ".\\"}:
        return False
    return not _is_blocked_argument_path(candidate)


def _is_read_only_git_command(argv: tuple[str, ...]) -> bool:
    if len(argv) < 2 or argv[0] != "git":
        return False
    subcommand = argv[1]
    if subcommand not in _GIT_READ_ONLY_SUBCOMMANDS:
        return False
    if subcommand == "status":
        return all(token in {"--short", "-s", "--porcelain", "--porcelain=v1"} for token in argv[2:])
    if subcommand == "diff":
        return _git_diff_args_safe(argv[2:])
    return False


def _git_diff_args_safe(args: Sequence[str]) -> bool:
    if not args:
        return True
    allowed_options = {"--", "--stat", "--name-only", "--name-status", "--check"}
    for token in args:
        if token in allowed_options:
            continue
        if token.startswith("-"):
            return False
        if _is_blocked_argument_path(token):
            return False
    return True


def _is_dependency_command(argv: tuple[str, ...]) -> bool:
    if not argv:
        return False
    command = argv[0].lower()
    if command == "npm" and len(argv) >= 2:
        return argv[1].lower() in _DEPENDENCY_COMMANDS
    if command in {"pnpm", "yarn"} and len(argv) >= 2:
        return argv[1].lower() in _DEPENDENCY_COMMANDS
    if command in {"pip", "pip3"} and len(argv) >= 2:
        return argv[1].lower() == "install"
    if command == "uv" and len(argv) >= 2:
        return argv[1].lower() in {"add", "sync"} or tuple(argv[1:3]) == (
            "pip",
            "install",
        )
    return False


def _has_pytest_config(workspace_root: Path | None) -> bool:
    if workspace_root is None:
        return False
    pyproject = workspace_root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return "pytest" in content


def _frontend_scripts(workspace_root: Path | None) -> set[str]:
    if workspace_root is None:
        return set()
    package_json = workspace_root / "frontend" / "package.json"
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


def _readme_commands(workspace_root: Path | None) -> set[str]:
    if workspace_root is None:
        return set()
    commands: set[str] = set()
    for filename in ("README.md", "README.zh.md"):
        path = workspace_root / filename
        if not path.is_file():
            continue
        try:
            commands.update(_fenced_command_lines(path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return commands


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


def _is_blocked_argument_path(token: str) -> bool:
    for candidate in _path_value_candidates(token):
        if _is_single_blocked_path(candidate):
            return True
    return False


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


def _is_single_blocked_path(token: str) -> bool:
    candidate = token.strip()
    if not candidate:
        return False
    normalized = posixpath.normpath(candidate.replace("\\", "/")).lower()
    if normalized == ".":
        return False
    basename = normalized.rsplit("/", 1)[-1]
    segments = set(normalized.split("/"))
    return (
        normalized == ".."
        or normalized.startswith("../")
        or normalized.startswith("/")
        or (len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/")
        or normalized in _RUNTIME_PREFIXES
        or any(normalized.startswith(f"{prefix}/") for prefix in _RUNTIME_PREFIXES)
        or basename in _CREDENTIAL_FILENAMES
        or basename.startswith(".env.")
        or basename.endswith(".pem")
        or basename.endswith(".key")
        or bool(segments & _CREDENTIAL_SEGMENTS)
    )


__all__ = [
    "VerificationCommandDecision",
    "classify_verification_command",
]
