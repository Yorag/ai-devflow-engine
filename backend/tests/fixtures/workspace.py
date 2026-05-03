from __future__ import annotations

import subprocess
from dataclasses import dataclass
import os
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from backend.tests.fixtures.delivery import MockRemoteDeliveryClient


@dataclass(frozen=True, slots=True)
class FixtureWorkspaceRepo:
    root: Path
    baseline_file: Path
    workspace_change_file: Path
    runtime_log_sample: Path


@dataclass(frozen=True, slots=True)
class FixtureGitRepository:
    root: Path
    git_dir: Path
    baseline_file: Path
    workspace_change_file: Path
    runtime_log_sample: Path
    remote_path: Path
    remote_url: str
    remote_name: str
    branch: str
    current_branch: str
    head: str
    head_commit: str
    has_committed_baseline: bool
    remote_client: MockRemoteDeliveryClient


def _resolve_under_tmp_path(tmp_path: Path, name: str) -> Path:
    base = tmp_path.resolve()
    candidate = Path(name)
    if candidate.is_absolute():
        raise ValueError("fixture repository paths must stay under tmp_path")
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("fixture repository paths must stay under tmp_path")
    return resolved


def _run_git(repo_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
        env=_fixture_git_env(),
    )
    return completed.stdout.strip()


def _fixture_git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.pop("GIT_CONFIG_GLOBAL", None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_COUNT"] = "4"
    env["GIT_CONFIG_KEY_0"] = "core.hooksPath"
    env["GIT_CONFIG_VALUE_0"] = os.devnull
    env["GIT_CONFIG_KEY_1"] = "commit.gpgsign"
    env["GIT_CONFIG_VALUE_1"] = "false"
    env["GIT_CONFIG_KEY_2"] = "tag.gpgsign"
    env["GIT_CONFIG_VALUE_2"] = "false"
    env["GIT_CONFIG_KEY_3"] = "init.templateDir"
    env["GIT_CONFIG_VALUE_3"] = os.devnull
    return env


def _create_workspace_tree(
    root: Path,
    *,
    include_workspace_change: bool,
    include_runtime_log: bool,
) -> FixtureWorkspaceRepo:
    root.mkdir(parents=True, exist_ok=True)
    src_dir = root / "src"
    tests_dir = root / "tests"
    logs_dir = root / ".runtime" / "logs"
    src_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    baseline_file = root / "README.md"
    workspace_change_file = src_dir / "workspace_change.txt"
    runtime_log_sample = logs_dir / "run-1.jsonl"

    baseline_file.write_text("# Fixture Repo\n", encoding="ascii")
    (src_dir / "app.py").write_text("print('fixture')\n", encoding="ascii")
    (tests_dir / "test_app.py").write_text(
        "def test_placeholder() -> None:\n    assert True\n",
        encoding="ascii",
    )
    if include_workspace_change:
        workspace_change_file.write_text("pending workspace change\n", encoding="ascii")
    if include_runtime_log:
        runtime_log_sample.write_text('{"event":"fixture"}\n', encoding="ascii")

    return FixtureWorkspaceRepo(
        root=root,
        baseline_file=baseline_file,
        workspace_change_file=workspace_change_file,
        runtime_log_sample=runtime_log_sample,
    )


def fixture_workspace_repo(
    tmp_path: Path,
    *,
    repo_name: str = "fixture-workspace",
) -> FixtureWorkspaceRepo:
    root = _resolve_under_tmp_path(tmp_path, repo_name)
    return _create_workspace_tree(
        root,
        include_workspace_change=True,
        include_runtime_log=True,
    )


def fixture_git_repository(
    tmp_path: Path,
    *,
    repo_name: str = "fixture-git-repo",
) -> FixtureGitRepository:
    from backend.tests.fixtures.delivery import mock_remote_delivery_client

    root = _resolve_under_tmp_path(tmp_path, repo_name)
    workspace = _create_workspace_tree(
        root,
        include_workspace_change=False,
        include_runtime_log=False,
    )
    remote_path = _resolve_under_tmp_path(tmp_path, f"{repo_name}-remote.git")
    remote_client = mock_remote_delivery_client()
    (root / ".gitignore").write_text(".runtime/\n", encoding="ascii")

    git_env = _fixture_git_env()
    subprocess.run(
        ["git", "init", "--bare", str(remote_path)],
        check=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=root,
        check=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Fixture User"],
        cwd=root,
        check=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.test"],
        cwd=root,
        check=True,
        env=git_env,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True, env=git_env)
    subprocess.run(
        ["git", "commit", "-m", "fixture baseline"],
        cwd=root,
        check=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_path)],
        cwd=root,
        check=True,
        env=git_env,
    )

    workspace.workspace_change_file.write_text(
        "pending workspace change\n",
        encoding="ascii",
    )
    workspace.runtime_log_sample.write_text('{"event":"fixture"}\n', encoding="ascii")

    branch = _run_git(root, "branch", "--show-current")
    head = _run_git(root, "rev-parse", "HEAD")
    remote_url = _run_git(root, "remote", "get-url", "origin")
    return FixtureGitRepository(
        root=root,
        git_dir=root / ".git",
        baseline_file=workspace.baseline_file,
        workspace_change_file=workspace.workspace_change_file,
        runtime_log_sample=workspace.runtime_log_sample,
        remote_path=remote_path,
        remote_url=remote_url,
        remote_name="origin",
        branch=branch,
        current_branch=branch,
        head=head,
        head_commit=head,
        has_committed_baseline=bool(head),
        remote_client=remote_client,
    )
