from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STORE_RELATIVE_PATH = Path("codex-coordination") / "function-one.sqlite"
ACCELERATION_PLAN_PATH = Path("docs/plans/function-one-acceleration-execution-plan.md")
PLATFORM_PLAN_PATH = Path("docs/plans/function-one-platform-plan.md")
INTEGRATION_BRANCH = "integration/function-one-acceleration"
LANE_ID_PATTERN = r"(?:AL\d+|QA(?:-[A-Z0-9]+)*)"

CLAIM_STATUSES = {
    "claimed",
    "reported",
    "implemented",
    "mock_ready",
    "integrating",
    "integrated",
    "done",
    "blocked",
}

ACTIVE_CLAIM_STATUSES = {"claimed", "reported", "implemented", "mock_ready", "integrating"}
COMPLETE_CLAIM_STATUSES = {"integrated", "done"}
SYNC_BLOCKING_CLAIM_STATUSES = ACTIVE_CLAIM_STATUSES | {"blocked"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def git_common_dir(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=cwd,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SystemExit(f"failed to locate git common dir: {result.stderr.strip()}")
    raw_path = Path(result.stdout.strip())
    if raw_path.is_absolute():
        return raw_path
    return (cwd / raw_path).resolve()


def default_store_path(cwd: Path) -> Path:
    return git_common_dir(cwd) / STORE_RELATIVE_PATH


def current_branch(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=cwd,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SystemExit(f"failed to locate current branch: {result.stderr.strip()}")
    branch = result.stdout.strip()
    if not branch:
        raise SystemExit("failed to locate current branch: detached HEAD")
    return branch


def run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def connect(store_path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        uri = store_path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(store_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            lane_id TEXT NOT NULL,
            branch TEXT NOT NULL,
            status TEXT NOT NULL,
            coordination_base TEXT NOT NULL,
            worker_head TEXT,
            evidence_path TEXT NOT NULL,
            blocker TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS claim_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.commit()


def add_event(
    connection: sqlite3.Connection,
    *,
    claim_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO claim_events (claim_id, event_type, payload_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (claim_id, event_type, json.dumps(payload, sort_keys=True), utc_now()),
    )


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "claim_id": row["claim_id"],
        "task_id": row["task_id"],
        "lane_id": row["lane_id"],
        "branch": row["branch"],
        "status": row["status"],
        "coordination_base": row["coordination_base"],
        "worker_head": row["worker_head"],
        "evidence_path": row["evidence_path"],
        "blocker": row["blocker"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_claim(connection: sqlite3.Connection, claim_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT claim_id, task_id, lane_id, branch, status, coordination_base,
               worker_head, evidence_path, blocker, created_at, updated_at
        FROM claims
        WHERE claim_id = ?
        """,
        (claim_id,),
    ).fetchone()


def fetch_claims_for_branch(
    connection: sqlite3.Connection,
    *,
    branch: str,
    statuses: list[str],
) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in statuses)
    return connection.execute(
        f"""
        SELECT claim_id, task_id, lane_id, branch, status, coordination_base,
               worker_head, evidence_path, blocker, created_at, updated_at
        FROM claims
        WHERE branch = ?
          AND status IN ({placeholders})
        ORDER BY claim_id
        """,
        (branch, *statuses),
    ).fetchall()


def fetch_claims_by_statuses(
    connection: sqlite3.Connection,
    *,
    statuses: list[str],
    claim_ids: list[str],
) -> list[sqlite3.Row]:
    status_placeholders = ", ".join("?" for _ in statuses)
    params: list[str] = [*statuses]
    claim_filter = ""
    if claim_ids:
        claim_placeholders = ", ".join("?" for _ in claim_ids)
        claim_filter = f" AND claim_id IN ({claim_placeholders})"
        params.extend(claim_ids)
    return connection.execute(
        f"""
        SELECT claim_id, task_id, lane_id, branch, status, coordination_base,
               worker_head, evidence_path, blocker, created_at, updated_at
        FROM claims
        WHERE status IN ({status_placeholders})
        {claim_filter}
        ORDER BY claim_id
        """,
        params,
    ).fetchall()


def fetch_claims_for_lane(
    connection: sqlite3.Connection,
    *,
    lane_id: str,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT claim_id, task_id, lane_id, branch, status, coordination_base,
               worker_head, evidence_path, blocker, created_at, updated_at
        FROM claims
        WHERE lane_id = ?
        ORDER BY created_at, claim_id
        """,
        (lane_id,),
    ).fetchall()


def fetch_latest_claim_for_lane(
    connection: sqlite3.Connection,
    *,
    lane_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT claim_id, task_id, lane_id, branch, status, coordination_base,
               worker_head, evidence_path, blocker, created_at, updated_at
        FROM claims
        WHERE lane_id = ?
        ORDER BY updated_at DESC, created_at DESC, claim_id DESC
        LIMIT 1
        """,
        (lane_id,),
    ).fetchone()


def fetch_claims_for_task(
    connection: sqlite3.Connection,
    *,
    task_id: str,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT claim_id, task_id, lane_id, branch, status, coordination_base,
               worker_head, evidence_path, blocker, created_at, updated_at
        FROM claims
        WHERE task_id = ?
        ORDER BY created_at, claim_id
        """,
        (task_id,),
    ).fetchall()


def print_claim(row: sqlite3.Row, *, as_json: bool) -> None:
    payload = row_to_dict(row)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    for key, value in payload.items():
        print(f"{key}: {value if value is not None else '-'}")


def command_store_path(args: argparse.Namespace) -> int:
    print(default_store_path(Path.cwd()))
    return 0


def command_init(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    with connect(store_path) as connection:
        initialize(connection)
    print(store_path)
    return 0


def command_claim(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    now = utc_now()
    with connect(store_path) as connection:
        initialize(connection)
        existing = fetch_claim(connection, args.claim)
        created_at = existing["created_at"] if existing else now
        connection.execute(
            """
            INSERT INTO claims (
                claim_id, task_id, lane_id, branch, status, coordination_base,
                worker_head, evidence_path, blocker, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'claimed', ?, NULL, ?, NULL, ?, ?)
            ON CONFLICT(claim_id) DO UPDATE SET
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                branch = excluded.branch,
                status = 'claimed',
                coordination_base = excluded.coordination_base,
                worker_head = NULL,
                evidence_path = excluded.evidence_path,
                blocker = NULL,
                updated_at = excluded.updated_at
            """,
            (
                args.claim,
                args.task,
                args.lane,
                args.branch,
                args.base,
                args.evidence,
                created_at,
                now,
            ),
        )
        add_event(
            connection,
            claim_id=args.claim,
            event_type="claimed",
            payload={
                "task_id": args.task,
                "lane_id": args.lane,
                "branch": args.branch,
                "coordination_base": args.base,
                "evidence_path": args.evidence,
            },
        )
        connection.commit()
    print(f"claimed {args.claim}")
    return 0


def command_ingest(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    now = utc_now()
    with connect(store_path) as connection:
        initialize(connection)
        row = fetch_claim(connection, args.claim)
        if row is None:
            print(f"unknown claim: {args.claim}", file=sys.stderr)
            return 2
        connection.execute(
            """
            UPDATE claims
            SET status = ?,
                worker_head = COALESCE(?, worker_head),
                blocker = ?,
                updated_at = ?
            WHERE claim_id = ?
            """,
            (args.status, args.worker_head, args.blocker, now, args.claim),
        )
        add_event(
            connection,
            claim_id=args.claim,
            event_type=f"ingest:{args.status}",
            payload={
                "status": args.status,
                "worker_head": args.worker_head,
                "blocker": args.blocker,
            },
        )
        connection.commit()
    print(f"{args.claim} -> {args.status}")
    return 0


def command_show(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path, read_only=True) as connection:
            row = fetch_claim(connection, args.claim)
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not readable: {exc}", file=sys.stderr)
        return 2
    if row is None:
        print(f"unknown claim: {args.claim}", file=sys.stderr)
        return 2
    print_claim(row, as_json=args.json)
    return 0


def command_list(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT claim_id, task_id, lane_id, branch, status, coordination_base,
                       worker_head, evidence_path, blocker, created_at, updated_at
                FROM claims
                ORDER BY claim_id
                """
            ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not readable: {exc}", file=sys.stderr)
        return 2

    payload = [row_to_dict(row) for row in rows]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    for claim in payload:
        worker_head = claim["worker_head"] or "-"
        print(
            f"{claim['claim_id']} {claim['status']} "
            f"{claim['lane_id']} {claim['task_id']} {claim['branch']} {worker_head}"
        )
    return 0


def git_branch_head(branch: str, *, cwd: Path) -> str | None:
    result = run_git(["rev-parse", "--short", branch], cwd=cwd)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_show_text(branch: str, path: str, *, cwd: Path) -> str | None:
    result = run_git(["show", f"{branch}:{path}"], cwd=cwd)
    if result.returncode != 0:
        return None
    return result.stdout


def git_diff_paths(base: str, branch: str, *, cwd: Path) -> list[str] | None:
    result = run_git(["diff", "--name-only", f"{base}..{branch}"], cwd=cwd)
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_ahead_behind(left: str, right: str, *, cwd: Path) -> tuple[int, int] | None:
    result = run_git(["rev-list", "--left-right", "--count", f"{left}...{right}"], cwd=cwd)
    if result.returncode != 0:
        return None
    parts = result.stdout.split()
    if len(parts) != 2:
        return None
    return int(parts[0]), int(parts[1])


def git_worktrees_by_branch(*, cwd: Path) -> dict[str, Path]:
    result = run_git(["worktree", "list", "--porcelain"], cwd=cwd)
    if result.returncode != 0:
        return {}
    worktrees: dict[str, Path] = {}
    current_path: Path | None = None
    for raw_line in result.stdout.splitlines():
        if raw_line.startswith("worktree "):
            current_path = Path(raw_line.removeprefix("worktree ")).resolve()
        elif raw_line.startswith("branch refs/heads/") and current_path is not None:
            branch = raw_line.removeprefix("branch refs/heads/")
            worktrees[branch] = current_path
    return worktrees


def git_worktree_dirty(path: Path) -> bool | None:
    result = run_git(["status", "--short", "--untracked-files=all"], cwd=path)
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def git_ff_only_merge(path: Path, target: str) -> tuple[bool, str]:
    result = run_git(["merge", "--ff-only", target], cwd=path)
    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
    return result.returncode == 0, output


def read_repo_text(path: Path, *, cwd: Path) -> str:
    return (cwd / path).read_text(encoding="utf-8")


def markdown_section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start == -1:
        return ""
    next_heading = text.find("\n## ", start + len(heading))
    if next_heading == -1:
        return text[start:]
    return text[start:next_heading]


def parse_lane_registry(plan_text: str) -> dict[str, dict[str, Any]]:
    section = markdown_section(plan_text, "## 3. Lane Registry")
    registry: dict[str, dict[str, Any]] = {}
    for line in section.splitlines():
        match = re.match(rf"^\|\s*({LANE_ID_PATTERN})\s*\|\s*`([^`]+)`\s*\|\s*([^|]+)\|", line)
        if not match:
            continue
        lane_id, branch, tasks_text = match.groups()
        tasks = [task.strip() for task in tasks_text.split(",") if task.strip()]
        registry[lane_id] = {"branch": branch, "tasks": tasks}
    return registry


def parse_lane_queues(plan_text: str) -> dict[str, list[str]]:
    section = markdown_section(plan_text, "## 7. Lane Queues")
    queues: dict[str, list[str]] = {}
    for line in section.splitlines():
        match = re.match(rf"^\|\s*({LANE_ID_PATTERN})\s*\|\s*([^|]+)\|", line)
        if not match:
            continue
        lane_id, queue_text = match.groups()
        if queue_text.strip() == "Queue":
            continue
        tasks = [task.strip() for task in queue_text.split("->") if task.strip()]
        queues[lane_id] = tasks
    return queues


def parse_platform_tasks(plan_text: str) -> dict[str, dict[str, str]]:
    tasks: dict[str, dict[str, str]] = {}
    for line in plan_text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        task_id = cells[0]
        if not re.match(r"^[A-Z]\d+(?:\.\d+)?[a-z]?$", task_id):
            continue
        link_match = re.search(r"\(([^)]+)\)", cells[5])
        tasks[task_id] = {
            "title": cells[1],
            "status": cells[3],
            "owner": cells[4],
            "link": link_match.group(1) if link_match else "",
        }
    return tasks


def split_task_status(task_meta: dict[str, str], *, cwd: Path) -> str | None:
    link = task_meta.get("link") or ""
    if "#" not in link:
        return None
    file_part, anchor = link.split("#", 1)
    split_path = Path("docs/plans") / Path(file_part)
    full_path = cwd / split_path
    if not full_path.exists():
        return None
    text = full_path.read_text(encoding="utf-8")
    anchor_marker = f'<a id="{anchor}"></a>'
    start = text.find(anchor_marker)
    if start == -1:
        return None
    next_anchor = text.find('\n<a id="', start + len(anchor_marker))
    section = text[start:] if next_anchor == -1 else text[start:next_anchor]
    match = re.search(r"\*\*状态\*\*：`(\[[^\]]+\])`", section)
    return match.group(1) if match else None


def normalize_claim_id(lane_id: str, task_id: str) -> str:
    return f"{lane_id}-{task_id}"


def evidence_path_for_claim(claim_id: str) -> str:
    return f"docs/plans/acceleration/reports/{claim_id}.md"


def lane_has_active_claim(rows: list[sqlite3.Row]) -> bool:
    return any(row["status"] in ACTIVE_CLAIM_STATUSES for row in rows)


def lane_has_sync_blocking_claim(rows: list[sqlite3.Row]) -> bool:
    return any(row["status"] in SYNC_BLOCKING_CLAIM_STATUSES for row in rows)


def describe_claims_by_status(rows: list[sqlite3.Row], statuses: set[str]) -> str:
    return ", ".join(
        f"{row['claim_id']}:{row['status']}"
        for row in rows
        if row["status"] in statuses
    )


def task_has_active_claim(rows: list[sqlite3.Row]) -> bool:
    return any(row["status"] in ACTIVE_CLAIM_STATUSES for row in rows)


def task_has_completed_claim(rows: list[sqlite3.Row]) -> bool:
    return any(row["status"] in COMPLETE_CLAIM_STATUSES for row in rows)


def next_lane_task(
    connection: sqlite3.Connection,
    *,
    lane_id: str,
    queue: list[str],
    platform_tasks: dict[str, dict[str, str]],
    cwd: Path,
) -> tuple[str | None, list[str]]:
    reasons: list[str] = []
    lane_rows = fetch_claims_for_lane(connection, lane_id=lane_id)
    if lane_has_active_claim(lane_rows):
        active = ", ".join(
            f"{row['claim_id']}:{row['status']}"
            for row in lane_rows
            if row["status"] in ACTIVE_CLAIM_STATUSES
        )
        return None, [f"lane has active claim: {active}"]

    for task_id in queue:
        task_rows = fetch_claims_for_task(connection, task_id=task_id)
        if task_has_active_claim(task_rows):
            return None, [f"task has active claim: {task_id}"]
        if task_has_completed_claim(task_rows):
            continue
        if any(row["status"] == "blocked" for row in task_rows):
            return None, [f"task is blocked: {task_id}"]

        task_meta = platform_tasks.get(task_id)
        if task_meta is None:
            return None, [f"task missing from platform plan: {task_id}"]
        platform_status = task_meta["status"]
        split_status = split_task_status(task_meta, cwd=cwd)
        if platform_status == "[x]" or split_status == "[x]":
            continue
        if platform_status not in {"[ ]", "[/]"}:
            return None, [f"unsupported platform status for {task_id}: {platform_status}"]
        if split_status not in {"[ ]", "[/]"}:
            return None, [f"unsupported split status for {task_id}: {split_status}"]
        return task_id, []

    reasons.append("lane queue has no remaining claimable task")
    return None, reasons


def auto_advance_claims(
    connection: sqlite3.Connection,
    *,
    lanes: list[str],
    base: str,
    apply: bool,
    cwd: Path,
) -> list[dict[str, Any]]:
    plan_text = read_repo_text(ACCELERATION_PLAN_PATH, cwd=cwd)
    platform_text = read_repo_text(PLATFORM_PLAN_PATH, cwd=cwd)
    registry = parse_lane_registry(plan_text)
    queues = parse_lane_queues(plan_text)
    platform_tasks = parse_platform_tasks(platform_text)
    worktrees = git_worktrees_by_branch(cwd=cwd)
    selected_lanes = lanes or sorted(queues)
    now = utc_now()
    results: list[dict[str, Any]] = []

    for lane_id in selected_lanes:
        reasons: list[str] = []
        lane_meta = registry.get(lane_id)
        queue = queues.get(lane_id)
        if lane_meta is None:
            results.append({"lane_id": lane_id, "advanced": False, "reasons": ["lane missing from registry"]})
            continue
        if not queue:
            results.append({"lane_id": lane_id, "advanced": False, "branch": lane_meta["branch"], "reasons": ["lane queue missing"]})
            continue

        branch = lane_meta["branch"]
        lane_rows = fetch_claims_for_lane(connection, lane_id=lane_id)
        if lane_has_active_claim(lane_rows):
            active = ", ".join(
                f"{row['claim_id']}:{row['status']}"
                for row in lane_rows
                if row["status"] in ACTIVE_CLAIM_STATUSES
            )
            results.append(
                {
                    "lane_id": lane_id,
                    "branch": branch,
                    "coordination_base": base,
                    "advanced": False,
                    "reasons": [f"lane has active claim: {active}"],
                }
            )
            continue

        branch_head = git_branch_head(branch, cwd=cwd)
        worktree_path = worktrees.get(branch)
        dirty = git_worktree_dirty(worktree_path) if worktree_path else None
        if branch_head is None:
            reasons.append("branch is not readable")
        if worktree_path is None:
            reasons.append("branch has no worktree")
        elif dirty:
            reasons.append("branch worktree is dirty")
        elif dirty is None:
            reasons.append("failed to read branch worktree status")
        if branch_head is not None and branch_head != base:
            reasons.append(f"branch head {branch_head} is not coordination base {base}")

        if reasons:
            results.append(
                {
                    "lane_id": lane_id,
                    "branch": branch,
                    "branch_head": branch_head,
                    "coordination_base": base,
                    "advanced": False,
                    "reasons": reasons,
                }
            )
            continue

        task_id, task_reasons = next_lane_task(
            connection,
            lane_id=lane_id,
            queue=queue,
            platform_tasks=platform_tasks,
            cwd=cwd,
        )
        if task_id is None:
            results.append(
                {
                    "lane_id": lane_id,
                    "branch": branch,
                    "branch_head": branch_head,
                    "coordination_base": base,
                    "advanced": False,
                    "reasons": task_reasons,
                }
            )
            continue

        if task_id not in lane_meta["tasks"]:
            results.append(
                {
                    "lane_id": lane_id,
                    "branch": branch,
                    "branch_head": branch_head,
                    "coordination_base": base,
                    "advanced": False,
                    "reasons": [f"task {task_id} is not in lane registry coverage"],
                }
            )
            continue

        claim_id = normalize_claim_id(lane_id, task_id)
        existing = fetch_claim(connection, claim_id)
        if existing is not None and existing["status"] in ACTIVE_CLAIM_STATUSES:
            results.append(
                {
                    "lane_id": lane_id,
                    "branch": branch,
                    "branch_head": branch_head,
                    "coordination_base": base,
                    "claim_id": claim_id,
                    "task_id": task_id,
                    "advanced": False,
                    "reasons": [f"claim already active: {existing['status']}"],
                }
            )
            continue
        if existing is not None and existing["status"] == "blocked":
            results.append(
                {
                    "lane_id": lane_id,
                    "branch": branch,
                    "branch_head": branch_head,
                    "coordination_base": base,
                    "claim_id": claim_id,
                    "task_id": task_id,
                    "advanced": False,
                    "reasons": ["claim is blocked"],
                }
            )
            continue

        evidence_path = evidence_path_for_claim(claim_id)
        if apply:
            created_at = existing["created_at"] if existing else now
            connection.execute(
                """
                INSERT INTO claims (
                    claim_id, task_id, lane_id, branch, status, coordination_base,
                    worker_head, evidence_path, blocker, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'claimed', ?, NULL, ?, NULL, ?, ?)
                ON CONFLICT(claim_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    lane_id = excluded.lane_id,
                    branch = excluded.branch,
                    status = 'claimed',
                    coordination_base = excluded.coordination_base,
                    worker_head = NULL,
                    evidence_path = excluded.evidence_path,
                    blocker = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    claim_id,
                    task_id,
                    lane_id,
                    branch,
                    base,
                    evidence_path,
                    created_at,
                    now,
                ),
            )
            add_event(
                connection,
                claim_id=claim_id,
                event_type="claimed:auto-advance",
                payload={
                    "task_id": task_id,
                    "lane_id": lane_id,
                    "branch": branch,
                    "coordination_base": base,
                    "evidence_path": evidence_path,
                    "source": "auto-advance-claims",
                },
            )
        results.append(
            {
                "lane_id": lane_id,
                "branch": branch,
                "branch_head": branch_head,
                "coordination_base": base,
                "claim_id": claim_id,
                "task_id": task_id,
                "evidence_path": evidence_path,
                "advanced": apply,
                "would_advance": not apply,
                "reasons": [],
            }
        )

    if apply:
        connection.commit()
    return results


def sync_idle_branches(
    connection: sqlite3.Connection,
    *,
    lanes: list[str],
    target: str,
    target_head: str,
    apply: bool,
    cwd: Path,
) -> list[dict[str, Any]]:
    plan_text = read_repo_text(ACCELERATION_PLAN_PATH, cwd=cwd)
    registry = parse_lane_registry(plan_text)
    worktrees = git_worktrees_by_branch(cwd=cwd)
    selected_lanes = lanes or sorted(registry)
    results: list[dict[str, Any]] = []

    for lane_id in selected_lanes:
        lane_meta = registry.get(lane_id)
        if lane_meta is None:
            results.append({"lane_id": lane_id, "synced": False, "reasons": ["lane missing from registry"]})
            continue

        branch = lane_meta["branch"]
        lane_rows = fetch_claims_for_lane(connection, lane_id=lane_id)
        if lane_has_sync_blocking_claim(lane_rows):
            blocking = describe_claims_by_status(lane_rows, SYNC_BLOCKING_CLAIM_STATUSES)
            results.append(
                {
                    "lane_id": lane_id,
                    "branch": branch,
                    "target": target,
                    "target_head": target_head,
                    "synced": False,
                    "reasons": [f"lane has sync-blocking claim: {blocking}"],
                }
            )
            continue

        reasons: list[str] = []
        branch_head = git_branch_head(branch, cwd=cwd)
        worktree_path = worktrees.get(branch)
        dirty = git_worktree_dirty(worktree_path) if worktree_path else None
        ahead_behind = git_ahead_behind(branch, target, cwd=cwd) if branch_head else None

        if branch_head is None:
            reasons.append("branch is not readable")
        if worktree_path is None:
            reasons.append("branch has no worktree")
        elif dirty:
            reasons.append("branch worktree is dirty")
        elif dirty is None:
            reasons.append("failed to read branch worktree status")
        if ahead_behind is None:
            reasons.append("failed to compare branch with target")
            ahead = None
            behind = None
        else:
            ahead, behind = ahead_behind
            if ahead > 0:
                reasons.append(f"branch has {ahead} unintegrated commit(s)")
            if behind == 0:
                reasons.append("branch is already at target")

        if reasons:
            results.append(
                {
                    "lane_id": lane_id,
                    "branch": branch,
                    "branch_head": branch_head,
                    "target": target,
                    "target_head": target_head,
                    "ahead": ahead,
                    "behind": behind,
                    "synced": False,
                    "reasons": reasons,
                }
            )
            continue

        merge_output = None
        if apply:
            assert worktree_path is not None
            ok, merge_output = git_ff_only_merge(worktree_path, target)
            if not ok:
                results.append(
                    {
                        "lane_id": lane_id,
                        "branch": branch,
                        "branch_head": branch_head,
                        "target": target,
                        "target_head": target_head,
                        "ahead": ahead,
                        "behind": behind,
                        "synced": False,
                        "reasons": ["ff-only merge failed"],
                        "output": merge_output,
                    }
                )
                continue
            branch_head = git_branch_head(branch, cwd=cwd)

        results.append(
            {
                "lane_id": lane_id,
                "branch": branch,
                "branch_head": branch_head,
                "target": target,
                "target_head": target_head,
                "ahead": ahead,
                "behind": behind,
                "synced": apply,
                "would_sync": not apply,
                "reasons": [],
                "output": merge_output,
            }
        )

    return results


def active_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    return [row for row in rows if row["status"] in ACTIVE_CLAIM_STATUSES]


def blocking_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    return [row for row in rows if row["status"] in SYNC_BLOCKING_CLAIM_STATUSES]


def row_brief(row: sqlite3.Row | None) -> str:
    if row is None:
        return "-"
    worker_head = row["worker_head"] or "-"
    return f"{row['claim_id']}:{row['status']}@{worker_head}"


def summarize_lanes(
    connection: sqlite3.Connection,
    *,
    lanes: list[str],
    target: str,
    target_head: str,
    cwd: Path,
) -> list[dict[str, Any]]:
    plan_text = read_repo_text(ACCELERATION_PLAN_PATH, cwd=cwd)
    platform_text = read_repo_text(PLATFORM_PLAN_PATH, cwd=cwd)
    registry = parse_lane_registry(plan_text)
    queues = parse_lane_queues(plan_text)
    platform_tasks = parse_platform_tasks(platform_text)
    worktrees = git_worktrees_by_branch(cwd=cwd)
    selected_lanes = lanes or sorted(registry)
    summaries: list[dict[str, Any]] = []

    for lane_id in selected_lanes:
        lane_meta = registry.get(lane_id)
        if lane_meta is None:
            summaries.append({"lane_id": lane_id, "status": "missing", "next_action": "lane missing from registry"})
            continue

        branch = lane_meta["branch"]
        lane_rows = fetch_claims_for_lane(connection, lane_id=lane_id)
        latest = fetch_latest_claim_for_lane(connection, lane_id=lane_id)
        active = active_rows(lane_rows)
        blocking = blocking_rows(lane_rows)
        branch_head = git_branch_head(branch, cwd=cwd)
        worktree_path = worktrees.get(branch)
        dirty = git_worktree_dirty(worktree_path) if worktree_path else None
        ahead_behind = git_ahead_behind(branch, target, cwd=cwd) if branch_head else None
        ahead = ahead_behind[0] if ahead_behind else None
        behind = ahead_behind[1] if ahead_behind else None
        next_task = None
        next_action = "idle"
        reasons: list[str] = []

        if active:
            claim_ids = [row["claim_id"] for row in active]
            implementation_rows = [
                row for row in active if row["status"] in {"implemented", "mock_ready"}
            ]
            scannable_rows = [
                row for row in active if row["status"] in {"claimed", "reported"}
            ]
            scan_results = scan_worker_claims(scannable_rows, cwd=cwd)
            ready_claims = [result["claim_id"] for result in scan_results if result["ready_to_ingest"]]
            if implementation_rows:
                next_action = "integration candidate: " + ", ".join(claim_ids)
            elif ready_claims:
                next_action = "ingest ready: " + ", ".join(ready_claims)
            else:
                next_action = "worker active: " + ", ".join(claim_ids)
        elif any(row["status"] == "blocked" for row in lane_rows):
            blocked = describe_claims_by_status(lane_rows, {"blocked"})
            next_action = "blocked: " + blocked
        elif worktree_path is None:
            next_action = "create or attach worktree"
        elif dirty:
            next_action = "inspect dirty idle worktree"
        elif branch_head != target_head:
            if ahead_behind is None:
                next_action = "inspect branch comparison"
            elif ahead and ahead > 0:
                next_action = f"inspect {ahead} unintegrated commit(s)"
            elif behind and behind > 0:
                next_action = f"sync idle branch ({behind} behind)"
            else:
                next_action = "inspect branch state"
        else:
            queue = queues.get(lane_id, [])
            task_id, task_reasons = next_lane_task(
                connection,
                lane_id=lane_id,
                queue=queue,
                platform_tasks=platform_tasks,
                cwd=cwd,
            )
            next_task = task_id
            if task_id is None:
                next_action = "no claimable next task"
                reasons = task_reasons
            else:
                next_action = f"auto-advance {normalize_claim_id(lane_id, task_id)}"

        summaries.append(
            {
                "lane_id": lane_id,
                "branch": branch,
                "branch_head": branch_head,
                "target": target,
                "target_head": target_head,
                "ahead": ahead,
                "behind": behind,
                "worktree_path": str(worktree_path) if worktree_path else None,
                "worktree_dirty": dirty,
                "active_claims": [row_to_dict(row) for row in active],
                "blocking_claims": [row_to_dict(row) for row in blocking],
                "latest_claim": row_to_dict(latest) if latest else None,
                "latest": row_brief(latest),
                "next_task": next_task,
                "next_action": next_action,
                "reasons": reasons,
            }
        )

    return summaries


def print_status_summary(summaries: list[dict[str, Any]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(summaries, ensure_ascii=False))
        return
    print("| Lane | Branch | Head | Delta | Dirty | Latest | Next |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for item in summaries:
        ahead = item.get("ahead")
        behind = item.get("behind")
        if ahead is None or behind is None:
            delta = "-"
        else:
            delta = f"+{ahead}/-{behind}"
        dirty_value = item.get("worktree_dirty")
        dirty = "-" if dirty_value is None else ("yes" if dirty_value else "no")
        print(
            f"| {item['lane_id']} | {item.get('branch', '-')} | "
            f"{item.get('branch_head') or '-'} | {delta} | {dirty} | "
            f"{item.get('latest') or '-'} | {item.get('next_action') or '-'} |"
        )


def worker_start_payload(
    connection: sqlite3.Connection,
    *,
    branch: str,
    target: str,
    target_head: str,
    cwd: Path,
) -> tuple[dict[str, Any], int]:
    rows = fetch_claims_for_branch(
        connection,
        branch=branch,
        statuses=["claimed", "reported"],
    )
    branch_head = git_branch_head(branch, cwd=cwd)
    dirty = git_worktree_dirty(cwd)
    ahead_behind = git_ahead_behind(branch, target, cwd=cwd) if branch_head else None
    payload: dict[str, Any] = {
        "branch": branch,
        "branch_head": branch_head,
        "target": target,
        "target_head": target_head,
        "worktree": str(cwd),
        "worktree_dirty": dirty,
        "ahead": ahead_behind[0] if ahead_behind else None,
        "behind": ahead_behind[1] if ahead_behind else None,
        "startable": False,
        "claim": None,
        "reasons": [],
    }
    if len(rows) == 1:
        claim = row_to_dict(rows[0])
        payload["claim"] = claim
        payload["startable"] = True
        if branch_head != claim["coordination_base"]:
            payload["reasons"].append(
                f"branch head {branch_head} differs from claim coordination base {claim['coordination_base']}"
            )
        return payload, 0

    if not rows:
        payload["reasons"].append(
            "no active claim; ask main coordination to run sync-idle-branches --apply and auto-advance-claims --apply"
        )
        return payload, 2

    claim_ids = ", ".join(row["claim_id"] for row in rows)
    payload["reasons"].append(f"multiple active claims: {claim_ids}")
    return payload, 2


def expected_ingest_status(report_text: str) -> str | None:
    for line in report_text.splitlines():
        normalized = line.lower()
        if "ingest" not in normalized:
            continue
        if "expected" not in normalized and "expectation" not in normalized:
            continue
        if re.search(r"\bmock[_-]ready\b", normalized):
            return "mock_ready"
        if re.search(r"\bimplemented\b", normalized):
            return "implemented"
    return None


def report_mentions(report_text: str, value: str) -> bool:
    return value.lower() in report_text.lower()


def scan_worker_claims(
    rows: list[sqlite3.Row],
    *,
    cwd: Path,
) -> list[dict[str, Any]]:
    worktrees = git_worktrees_by_branch(cwd=cwd)
    results: list[dict[str, Any]] = []
    for row in rows:
        claim = row_to_dict(row)
        reasons: list[str] = []
        branch = claim["branch"]
        base = claim["coordination_base"]
        evidence_path = claim["evidence_path"]
        head = git_branch_head(branch, cwd=cwd)
        worktree_path = worktrees.get(branch)
        dirty = None
        if worktree_path is not None:
            dirty = git_worktree_dirty(worktree_path)
            if dirty:
                reasons.append("branch worktree is dirty")
            elif dirty is None:
                reasons.append("failed to read branch worktree status")
        if head is None:
            reasons.append("branch is not readable")

        report_text = None
        expected_status = None
        evidence_in_head = False
        report_metadata_ok = False
        if head is not None:
            report_text = git_show_text(branch, evidence_path, cwd=cwd)
            evidence_in_head = report_text is not None
            if report_text is None:
                reasons.append("evidence report is not committed at branch HEAD")
            else:
                expected_status = expected_ingest_status(report_text)
                if expected_status not in {"implemented", "mock_ready"}:
                    reasons.append("evidence report does not declare an expected ingest result")
                required_values = [
                    claim["claim_id"],
                    claim["task_id"],
                    claim["lane_id"],
                    claim["coordination_base"],
                ]
                missing_values = [
                    value for value in required_values if not report_mentions(report_text, value)
                ]
                report_metadata_ok = not missing_values
                if missing_values:
                    reasons.append(
                        "evidence report is missing metadata: "
                        + ", ".join(missing_values)
                    )

        diff_paths = None
        if head is not None:
            diff_paths = git_diff_paths(base, branch, cwd=cwd)
            if diff_paths is None:
                reasons.append("failed to diff branch against coordination base")
            else:
                if evidence_path not in diff_paths:
                    reasons.append("evidence report is not in branch diff")
                if not any(path.startswith("docs/plans/implementation/") for path in diff_paths):
                    reasons.append("implementation plan is not in branch diff")

        ready = (
            head is not None
            and dirty is not True
            and evidence_in_head
            and report_metadata_ok
            and expected_status in {"implemented", "mock_ready"}
            and diff_paths is not None
            and evidence_path in diff_paths
            and any(path.startswith("docs/plans/implementation/") for path in diff_paths)
        )

        results.append(
            {
                **claim,
                "branch_head": head,
                "worktree_path": str(worktree_path) if worktree_path else None,
                "worktree_dirty": dirty,
                "evidence_in_head": evidence_in_head,
                "expected_ingest_status": expected_status,
                "diff_paths": diff_paths,
                "ready_to_ingest": ready,
                "reasons": reasons,
            }
        )
    return results


def print_scan_results(results: list[dict[str, Any]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(results, ensure_ascii=False))
        return
    for result in results:
        status = "ready" if result["ready_to_ingest"] else "not-ready"
        expected = result["expected_ingest_status"] or "-"
        head = result["branch_head"] or "-"
        reasons = "; ".join(result["reasons"]) if result["reasons"] else "-"
        print(
            f"{result['claim_id']} {status} branch={result['branch']} "
            f"head={head} expected={expected} reasons={reasons}"
        )


def command_scan_worker_commits(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path, read_only=True) as connection:
            rows = fetch_claims_by_statuses(
                connection,
                statuses=args.status,
                claim_ids=args.claim,
            )
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not readable: {exc}", file=sys.stderr)
        return 2
    results = scan_worker_claims(rows, cwd=Path.cwd())
    print_scan_results(results, as_json=args.json)
    return 0


def command_ingest_worker_commits(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path) as connection:
            initialize(connection)
            rows = fetch_claims_by_statuses(
                connection,
                statuses=args.status,
                claim_ids=args.claim,
            )
            results = scan_worker_claims(rows, cwd=Path.cwd())
            ingested: list[dict[str, Any]] = []
            now = utc_now()
            for result in results:
                if not result["ready_to_ingest"]:
                    continue
                connection.execute(
                    """
                    UPDATE claims
                    SET status = ?,
                        worker_head = ?,
                        blocker = NULL,
                        updated_at = ?
                    WHERE claim_id = ?
                    """,
                    (
                        result["expected_ingest_status"],
                        result["branch_head"],
                        now,
                        result["claim_id"],
                    ),
                )
                add_event(
                    connection,
                    claim_id=result["claim_id"],
                    event_type=f"ingest:{result['expected_ingest_status']}",
                    payload={
                        "status": result["expected_ingest_status"],
                        "worker_head": result["branch_head"],
                        "source": "ingest-worker-commits",
                    },
                )
                ingested.append(result)
            connection.commit()
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not writable: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"ingested": ingested, "scanned": results}, ensure_ascii=False))
        return 0
    for result in ingested:
        print(
            f"{result['claim_id']} -> {result['expected_ingest_status']} "
            f"{result['branch_head']}"
        )
    if not ingested:
        print("no ready worker commits to ingest")
    return 0


def command_auto_advance_claims(args: argparse.Namespace) -> int:
    raw_base = args.base or args.integration_branch
    resolved_base = git_branch_head(raw_base, cwd=Path.cwd())
    if resolved_base is None:
        print(f"coordination base is not readable: {raw_base}", file=sys.stderr)
        return 2

    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path) as connection:
            initialize(connection)
            results = auto_advance_claims(
                connection,
                lanes=args.lane,
                base=resolved_base,
                apply=args.apply,
                cwd=Path.cwd(),
            )
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not writable: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"failed to read coordination sources: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "applied": args.apply,
                    "coordination_base": resolved_base,
                    "results": results,
                },
                ensure_ascii=False,
            )
        )
        return 0

    verb = "advanced" if args.apply else "would-advance"
    for result in results:
        reasons = "; ".join(result["reasons"]) if result["reasons"] else "-"
        if result.get("advanced") or result.get("would_advance"):
            print(
                f"{result['lane_id']} {verb} {result['claim_id']} "
                f"task={result['task_id']} branch={result['branch']} "
                f"base={result['coordination_base']}"
            )
        else:
            print(f"{result['lane_id']} skipped reasons={reasons}")
    return 0


def command_sync_idle_branches(args: argparse.Namespace) -> int:
    target = args.target or args.integration_branch
    target_head = git_branch_head(target, cwd=Path.cwd())
    if target_head is None:
        print(f"sync target is not readable: {target}", file=sys.stderr)
        return 2

    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path, read_only=True) as connection:
            results = sync_idle_branches(
                connection,
                lanes=args.lane,
                target=target,
                target_head=target_head,
                apply=args.apply,
                cwd=Path.cwd(),
            )
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not readable: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"failed to read coordination sources: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "applied": args.apply,
                    "target": target,
                    "target_head": target_head,
                    "results": results,
                },
                ensure_ascii=False,
            )
        )
        return 0

    verb = "synced" if args.apply else "would-sync"
    for result in results:
        reasons = "; ".join(result["reasons"]) if result["reasons"] else "-"
        if result.get("synced") or result.get("would_sync"):
            print(
                f"{result['lane_id']} {verb} {result['branch']} "
                f"behind={result['behind']} target={result['target_head']}"
            )
        else:
            print(f"{result['lane_id']} skipped reasons={reasons}")
    return 0


def command_status_summary(args: argparse.Namespace) -> int:
    target = args.target or args.integration_branch
    target_head = git_branch_head(target, cwd=Path.cwd())
    if target_head is None:
        print(f"status target is not readable: {target}", file=sys.stderr)
        return 2

    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path, read_only=True) as connection:
            summaries = summarize_lanes(
                connection,
                lanes=args.lane,
                target=target,
                target_head=target_head,
                cwd=Path.cwd(),
            )
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not readable: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"failed to read coordination sources: {exc}", file=sys.stderr)
        return 2

    print_status_summary(summaries, as_json=args.json)
    return 0


def command_worker_start(args: argparse.Namespace) -> int:
    target = args.target or args.integration_branch
    target_head = git_branch_head(target, cwd=Path.cwd())
    if target_head is None:
        print(f"worker target is not readable: {target}", file=sys.stderr)
        return 2
    branch = args.branch or current_branch(Path.cwd())

    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path, read_only=True) as connection:
            payload, exit_code = worker_start_payload(
                connection,
                branch=branch,
                target=target,
                target_head=target_head,
                cwd=Path.cwd(),
            )
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not readable: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    elif payload["startable"]:
        claim = payload["claim"] or {}
        print(
            f"startable {claim.get('claim_id')} task={claim.get('task_id')} "
            f"lane={claim.get('lane_id')} base={claim.get('coordination_base')} "
            f"evidence={claim.get('evidence_path')}"
        )
        if payload["reasons"]:
            print("warnings=" + "; ".join(payload["reasons"]))
    else:
        print("not-startable reasons=" + "; ".join(payload["reasons"]), file=sys.stderr)
    return exit_code


def command_post_checkpoint(args: argparse.Namespace) -> int:
    target = args.target or args.integration_branch
    target_head = git_branch_head(target, cwd=Path.cwd())
    if target_head is None:
        print(f"post-checkpoint target is not readable: {target}", file=sys.stderr)
        return 2

    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path) as connection:
            initialize(connection)
            ingest_rows = fetch_claims_by_statuses(
                connection,
                statuses=args.status,
                claim_ids=args.claim,
            )
            scan_results = scan_worker_claims(ingest_rows, cwd=Path.cwd())
            ingested: list[dict[str, Any]] = []
            now = utc_now()
            if args.apply:
                for result in scan_results:
                    if not result["ready_to_ingest"]:
                        continue
                    connection.execute(
                        """
                        UPDATE claims
                        SET status = ?,
                            worker_head = ?,
                            blocker = NULL,
                            updated_at = ?
                        WHERE claim_id = ?
                        """,
                        (
                            result["expected_ingest_status"],
                            result["branch_head"],
                            now,
                            result["claim_id"],
                        ),
                    )
                    add_event(
                        connection,
                        claim_id=result["claim_id"],
                        event_type=f"ingest:{result['expected_ingest_status']}",
                        payload={
                            "status": result["expected_ingest_status"],
                            "worker_head": result["branch_head"],
                            "source": "post-checkpoint",
                        },
                    )
                    ingested.append(result)
                connection.commit()

            sync_results = sync_idle_branches(
                connection,
                lanes=args.lane,
                target=target,
                target_head=target_head,
                apply=args.apply and args.sync,
                cwd=Path.cwd(),
            )
            advance_results = auto_advance_claims(
                connection,
                lanes=args.lane,
                base=target_head,
                apply=args.apply and args.advance,
                cwd=Path.cwd(),
            )
            summaries = summarize_lanes(
                connection,
                lanes=args.lane,
                target=target,
                target_head=target_head,
                cwd=Path.cwd(),
            )
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not writable: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"failed to read coordination sources: {exc}", file=sys.stderr)
        return 2

    payload = {
        "applied": args.apply,
        "sync_enabled": args.sync,
        "advance_enabled": args.advance,
        "target": target,
        "target_head": target_head,
        "scan": scan_results,
        "ingested": ingested,
        "sync": sync_results,
        "advance": advance_results,
        "summary": summaries,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    print("Scan/Ingest:")
    print_scan_results(scan_results, as_json=False)
    if args.apply:
        if ingested:
            for result in ingested:
                print(f"ingested {result['claim_id']} -> {result['expected_ingest_status']} {result['branch_head']}")
        else:
            print("ingested none")
    print("Sync:")
    verb = "synced" if args.apply and args.sync else "would-sync"
    for result in sync_results:
        reasons = "; ".join(result["reasons"]) if result["reasons"] else "-"
        if result.get("synced") or result.get("would_sync"):
            print(f"{result['lane_id']} {verb} {result['branch']} behind={result['behind']}")
        else:
            print(f"{result['lane_id']} skipped reasons={reasons}")
    print("Auto-Advance:")
    verb = "advanced" if args.apply and args.advance else "would-advance"
    for result in advance_results:
        reasons = "; ".join(result["reasons"]) if result["reasons"] else "-"
        if result.get("advanced") or result.get("would_advance"):
            print(f"{result['lane_id']} {verb} {result['claim_id']} task={result['task_id']}")
        else:
            print(f"{result['lane_id']} skipped reasons={reasons}")
    print("Summary:")
    print_status_summary(summaries, as_json=False)
    return 0


def command_current_worker(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    branch = args.branch or current_branch(Path.cwd())
    statuses = args.status
    try:
        with connect(store_path, read_only=True) as connection:
            rows = fetch_claims_for_branch(
                connection,
                branch=branch,
                statuses=statuses,
            )
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not readable: {exc}", file=sys.stderr)
        return 2

    if len(rows) == 1:
        print_claim(rows[0], as_json=args.json)
        return 0

    expected = ", ".join(sorted(statuses))
    if not rows:
        print(
            f"no active claim for branch {branch}; expected one of {expected}",
            file=sys.stderr,
        )
        return 2

    claim_ids = ", ".join(row["claim_id"] for row in rows)
    print(
        f"multiple active claims for branch {branch}; expected exactly one, got {claim_ids}",
        file=sys.stderr,
    )
    return 2


def command_validate_worker(args: argparse.Namespace) -> int:
    store_path = default_store_path(Path.cwd())
    try:
        with connect(store_path, read_only=True) as connection:
            row = fetch_claim(connection, args.claim)
    except sqlite3.OperationalError as exc:
        print(f"coordination store is not readable: {exc}", file=sys.stderr)
        return 2

    if row is None:
        print(f"unknown claim: {args.claim}", file=sys.stderr)
        return 2
    if row["branch"] != args.branch:
        print(
            f"branch mismatch: claim expects {row['branch']}, got {args.branch}",
            file=sys.stderr,
        )
        return 2
    allowed_statuses = set(args.status)
    if row["status"] not in allowed_statuses:
        expected = ", ".join(sorted(allowed_statuses))
        print(
            f"status mismatch: claim is {row['status']}, expected one of {expected}",
            file=sys.stderr,
        )
        return 2
    print_claim(row, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Coordinate function-one acceleration claims in a shared git-common-dir SQLite store."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    store_path = subparsers.add_parser("store-path")
    store_path.set_defaults(func=command_store_path)

    init = subparsers.add_parser("init")
    init.set_defaults(func=command_init)

    claim = subparsers.add_parser("claim")
    claim.add_argument("--claim", required=True, dest="claim")
    claim.add_argument("--lane", required=True, dest="lane")
    claim.add_argument("--task", required=True, dest="task")
    claim.add_argument("--branch", required=True)
    claim.add_argument("--base", required=True)
    claim.add_argument("--evidence", required=True)
    claim.set_defaults(func=command_claim)

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--claim", required=True, dest="claim")
    ingest.add_argument("--status", required=True, choices=sorted(CLAIM_STATUSES))
    ingest.add_argument("--worker-head")
    ingest.add_argument("--blocker")
    ingest.set_defaults(func=command_ingest)

    show = subparsers.add_parser("show")
    show.add_argument("--claim", required=True, dest="claim")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=command_show)

    list_claims = subparsers.add_parser("list")
    list_claims.add_argument("--json", action="store_true")
    list_claims.set_defaults(func=command_list)

    scan_worker_commits = subparsers.add_parser("scan-worker-commits")
    scan_worker_commits.add_argument("--claim", action="append", default=[])
    scan_worker_commits.add_argument(
        "--status",
        action="append",
        default=[],
        choices=sorted(CLAIM_STATUSES),
        help="Claim status to scan. Repeat to allow multiple statuses.",
    )
    scan_worker_commits.add_argument("--json", action="store_true")
    scan_worker_commits.set_defaults(func=command_scan_worker_commits)

    ingest_worker_commits = subparsers.add_parser("ingest-worker-commits")
    ingest_worker_commits.add_argument("--claim", action="append", default=[])
    ingest_worker_commits.add_argument(
        "--status",
        action="append",
        default=[],
        choices=sorted(CLAIM_STATUSES),
        help="Claim status to scan. Repeat to allow multiple statuses.",
    )
    ingest_worker_commits.add_argument("--json", action="store_true")
    ingest_worker_commits.set_defaults(func=command_ingest_worker_commits)

    auto_advance_claims = subparsers.add_parser("auto-advance-claims")
    auto_advance_claims.add_argument("--lane", action="append", default=[])
    auto_advance_claims.add_argument("--base")
    auto_advance_claims.add_argument(
        "--integration-branch",
        default=INTEGRATION_BRANCH,
        help="Branch used as the coordination base when --base is omitted.",
    )
    auto_advance_claims.add_argument(
        "--apply",
        action="store_true",
        help="Write claimed rows. Omit for dry-run.",
    )
    auto_advance_claims.add_argument("--json", action="store_true")
    auto_advance_claims.set_defaults(func=command_auto_advance_claims)

    sync_idle_branches = subparsers.add_parser("sync-idle-branches")
    sync_idle_branches.add_argument("--lane", action="append", default=[])
    sync_idle_branches.add_argument("--target")
    sync_idle_branches.add_argument(
        "--integration-branch",
        default=INTEGRATION_BRANCH,
        help="Branch used as the sync target when --target is omitted.",
    )
    sync_idle_branches.add_argument(
        "--apply",
        action="store_true",
        help="Run ff-only merge in eligible idle worktrees. Omit for dry-run.",
    )
    sync_idle_branches.add_argument("--json", action="store_true")
    sync_idle_branches.set_defaults(func=command_sync_idle_branches)

    status_summary = subparsers.add_parser("status-summary")
    status_summary.add_argument("--lane", action="append", default=[])
    status_summary.add_argument("--target")
    status_summary.add_argument(
        "--integration-branch",
        default=INTEGRATION_BRANCH,
        help="Branch used as the status target when --target is omitted.",
    )
    status_summary.add_argument("--json", action="store_true")
    status_summary.set_defaults(func=command_status_summary)

    worker_start = subparsers.add_parser("worker-start")
    worker_start.add_argument("--branch")
    worker_start.add_argument("--target")
    worker_start.add_argument(
        "--integration-branch",
        default=INTEGRATION_BRANCH,
        help="Branch used as the worker target when --target is omitted.",
    )
    worker_start.add_argument("--json", action="store_true")
    worker_start.set_defaults(func=command_worker_start)

    post_checkpoint = subparsers.add_parser("post-checkpoint")
    post_checkpoint.add_argument("--claim", action="append", default=[])
    post_checkpoint.add_argument("--lane", action="append", default=[])
    post_checkpoint.add_argument("--target")
    post_checkpoint.add_argument(
        "--integration-branch",
        default=INTEGRATION_BRANCH,
        help="Branch used as the sync and auto-advance target when --target is omitted.",
    )
    post_checkpoint.add_argument(
        "--status",
        action="append",
        default=[],
        choices=sorted(CLAIM_STATUSES),
        help="Claim status to scan for ingest. Repeat to allow multiple statuses.",
    )
    post_checkpoint.add_argument(
        "--apply",
        action="store_true",
        help="Apply ingest, idle sync, and auto-advance writes. Omit for dry-run.",
    )
    post_checkpoint.add_argument(
        "--no-sync",
        action="store_false",
        dest="sync",
        default=True,
        help="Skip sync-idle-branches in this wrapper.",
    )
    post_checkpoint.add_argument(
        "--no-advance",
        action="store_false",
        dest="advance",
        default=True,
        help="Skip auto-advance-claims in this wrapper.",
    )
    post_checkpoint.add_argument("--json", action="store_true")
    post_checkpoint.set_defaults(func=command_post_checkpoint)

    current_worker = subparsers.add_parser("current-worker")
    current_worker.add_argument("--branch")
    current_worker.add_argument(
        "--status",
        action="append",
        default=[],
        choices=sorted(CLAIM_STATUSES),
        help="Allowed claim status. Repeat to allow multiple statuses.",
    )
    current_worker.add_argument("--json", action="store_true")
    current_worker.set_defaults(func=command_current_worker)

    validate_worker = subparsers.add_parser("validate-worker")
    validate_worker.add_argument("--claim", required=True, dest="claim")
    validate_worker.add_argument("--branch", required=True)
    validate_worker.add_argument(
        "--status",
        action="append",
        default=[],
        choices=sorted(CLAIM_STATUSES),
        help="Allowed claim status. Repeat to allow multiple statuses.",
    )
    validate_worker.add_argument("--json", action="store_true")
    validate_worker.set_defaults(func=command_validate_worker)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command in {"current-worker", "validate-worker"} and not args.status:
        args.status = ["claimed", "reported"]
    if args.command in {"scan-worker-commits", "ingest-worker-commits", "post-checkpoint"} and not args.status:
        args.status = ["claimed", "reported"]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
