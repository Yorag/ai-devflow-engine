from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)


class SQLiteLangGraphCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(
        self,
        db_path: Path,
        *,
        serde: Any | None = None,
    ) -> None:
        super().__init__(serde=serde)
        self._db_path = db_path.expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = str(config["configurable"].get("checkpoint_ns", ""))
        checkpoint_id = get_checkpoint_id(config)
        with self._connect() as connection:
            if checkpoint_id:
                row = connection.execute(
                    """
                    SELECT checkpoint_id, checkpoint_type, checkpoint_blob,
                           metadata_type, metadata_blob, parent_checkpoint_id
                    FROM checkpoints
                    WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
                    """,
                    (thread_id, checkpoint_ns, checkpoint_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT checkpoint_id, checkpoint_type, checkpoint_blob,
                           metadata_type, metadata_blob, parent_checkpoint_id
                    FROM checkpoints
                    WHERE thread_id = ? AND checkpoint_ns = ?
                    ORDER BY checkpoint_id DESC
                    LIMIT 1
                    """,
                    (thread_id, checkpoint_ns),
                ).fetchone()
            if row is None:
                return None
            return self._row_to_tuple(
                connection,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                row=row,
                config=config if checkpoint_id else None,
            )

    def list(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        thread_ids = None
        checkpoint_ns = None
        checkpoint_id = None
        if config is not None:
            thread_ids = (str(config["configurable"]["thread_id"]),)
            checkpoint_ns = config["configurable"].get("checkpoint_ns")
            checkpoint_id = get_checkpoint_id(config)
        before_checkpoint_id = get_checkpoint_id(before) if before else None
        yielded = 0
        with self._connect() as connection:
            if thread_ids is None:
                thread_ids = tuple(
                    row["thread_id"]
                    for row in connection.execute(
                        "SELECT DISTINCT thread_id FROM checkpoints"
                    )
                )
            for thread_id in thread_ids:
                rows = connection.execute(
                    """
                    SELECT checkpoint_id, checkpoint_ns, checkpoint_type,
                           checkpoint_blob, metadata_type, metadata_blob,
                           parent_checkpoint_id
                    FROM checkpoints
                    WHERE thread_id = ?
                    ORDER BY checkpoint_id DESC
                    """,
                    (thread_id,),
                ).fetchall()
                for row in rows:
                    row_ns = str(row["checkpoint_ns"])
                    row_checkpoint_id = str(row["checkpoint_id"])
                    if checkpoint_ns is not None and row_ns != checkpoint_ns:
                        continue
                    if checkpoint_id is not None and row_checkpoint_id != checkpoint_id:
                        continue
                    if (
                        before_checkpoint_id is not None
                        and row_checkpoint_id >= before_checkpoint_id
                    ):
                        continue
                    metadata = self.serde.loads_typed(
                        (row["metadata_type"], row["metadata_blob"])
                    )
                    if filter and not all(
                        metadata.get(key) == value for key, value in filter.items()
                    ):
                        continue
                    if limit is not None and yielded >= limit:
                        return
                    yielded += 1
                    yield self._row_to_tuple(
                        connection,
                        thread_id=thread_id,
                        checkpoint_ns=row_ns,
                        row=row,
                        config=None,
                        metadata=metadata,
                    )

    def put(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, str],
    ) -> dict[str, Any]:
        checkpoint_copy = checkpoint.copy()
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = str(config["configurable"].get("checkpoint_ns", ""))
        values = checkpoint_copy.pop("channel_values", {})
        checkpoint_id = str(checkpoint["id"])
        with self._connect() as connection:
            for channel, version in new_versions.items():
                if channel in values:
                    blob_type, blob = self.serde.dumps_typed(values[channel])
                else:
                    blob_type, blob = "empty", b""
                connection.execute(
                    """
                    INSERT OR REPLACE INTO checkpoint_blobs
                    (thread_id, checkpoint_ns, channel, version, blob_type, blob)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (thread_id, checkpoint_ns, channel, str(version), blob_type, blob),
                )
            checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint_copy)
            metadata_type, metadata_blob = self.serde.dumps_typed(
                get_checkpoint_metadata(config, metadata)
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO checkpoints
                (thread_id, checkpoint_ns, checkpoint_id, checkpoint_type,
                 checkpoint_blob, metadata_type, metadata_blob, parent_checkpoint_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    checkpoint_type,
                    checkpoint_blob,
                    metadata_type,
                    metadata_blob,
                    config["configurable"].get("checkpoint_id"),
                ),
            )
            connection.commit()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = str(config["configurable"].get("checkpoint_ns", ""))
        checkpoint_id = str(config["configurable"]["checkpoint_id"])
        with self._connect() as connection:
            for index, (channel, value) in enumerate(writes):
                write_index = WRITES_IDX_MAP.get(channel, index)
                if write_index >= 0:
                    existing = connection.execute(
                        """
                        SELECT 1 FROM checkpoint_writes
                        WHERE thread_id = ? AND checkpoint_ns = ?
                          AND checkpoint_id = ? AND task_id = ?
                          AND write_index = ?
                        """,
                        (
                            thread_id,
                            checkpoint_ns,
                            checkpoint_id,
                            task_id,
                            write_index,
                        ),
                    ).fetchone()
                    if existing is not None:
                        continue
                blob_type, blob = self.serde.dumps_typed(value)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO checkpoint_writes
                    (thread_id, checkpoint_ns, checkpoint_id, task_id, write_index,
                     channel, blob_type, blob, task_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        task_id,
                        write_index,
                        channel,
                        blob_type,
                        blob,
                        task_path,
                    ),
                )
            connection.commit()

    def delete_thread(self, thread_id: str) -> None:
        with self._connect() as connection:
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                connection.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
            connection.commit()

    def _row_to_tuple(
        self,
        connection: sqlite3.Connection,
        *,
        thread_id: str,
        checkpoint_ns: str,
        row: sqlite3.Row,
        config: dict[str, Any] | None,
        metadata: dict[str, Any] | None = None,
    ) -> CheckpointTuple:
        checkpoint_id = str(row["checkpoint_id"])
        checkpoint = self.serde.loads_typed(
            (row["checkpoint_type"], row["checkpoint_blob"])
        )
        metadata = metadata or self.serde.loads_typed(
            (row["metadata_type"], row["metadata_blob"])
        )
        checkpoint = {
            **checkpoint,
            "channel_values": self._load_blobs(
                connection,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                versions=checkpoint["channel_versions"],
            ),
        }
        parent_checkpoint_id = row["parent_checkpoint_id"]
        return CheckpointTuple(
            config=config
            or {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_checkpoint_id,
                    }
                }
                if parent_checkpoint_id
                else None
            ),
            pending_writes=self._load_writes(
                connection,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
            ),
        )

    def _load_blobs(
        self,
        connection: sqlite3.Connection,
        *,
        thread_id: str,
        checkpoint_ns: str,
        versions: dict[str, Any],
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for channel, version in versions.items():
            row = connection.execute(
                """
                SELECT blob_type, blob FROM checkpoint_blobs
                WHERE thread_id = ? AND checkpoint_ns = ? AND channel = ?
                  AND version = ?
                """,
                (thread_id, checkpoint_ns, channel, str(version)),
            ).fetchone()
            if row is None or row["blob_type"] == "empty":
                continue
            values[channel] = self.serde.loads_typed((row["blob_type"], row["blob"]))
        return values

    def _load_writes(
        self,
        connection: sqlite3.Connection,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> list[tuple[str, str, Any]]:
        rows = connection.execute(
            """
            SELECT task_id, channel, blob_type, blob FROM checkpoint_writes
            WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
            ORDER BY task_id ASC, write_index ASC
            """,
            (thread_id, checkpoint_ns, checkpoint_id),
        ).fetchall()
        return [
            (
                str(row["task_id"]),
                str(row["channel"]),
                self.serde.loads_typed((row["blob_type"], row["blob"])),
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    checkpoint_type TEXT NOT NULL,
                    checkpoint_blob BLOB NOT NULL,
                    metadata_type TEXT NOT NULL,
                    metadata_blob BLOB NOT NULL,
                    parent_checkpoint_id TEXT,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                );
                CREATE TABLE IF NOT EXISTS checkpoint_blobs (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    version TEXT NOT NULL,
                    blob_type TEXT NOT NULL,
                    blob BLOB NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
                );
                CREATE TABLE IF NOT EXISTS checkpoint_writes (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    write_index INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    blob_type TEXT NOT NULL,
                    blob BLOB NOT NULL,
                    task_path TEXT NOT NULL,
                    PRIMARY KEY (
                        thread_id, checkpoint_ns, checkpoint_id, task_id, write_index
                    )
                );
                """
            )
            connection.commit()


__all__ = ["SQLiteLangGraphCheckpointSaver"]
