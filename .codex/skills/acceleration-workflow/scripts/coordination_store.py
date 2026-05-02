from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STORE_RELATIVE_PATH = Path("codex-coordination") / "function-one.sqlite"

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


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def git_common_dir(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=cwd,
        check=False,
        text=True,
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
    if args.command == "validate-worker" and not args.status:
        args.status = ["claimed", "reported"]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
