from __future__ import annotations

from dataclasses import dataclass


PUBLICATION_STATE_PENDING = "pending"
PUBLICATION_STATE_PUBLISHED = "published"
PUBLICATION_STATE_ABORTED = "aborted"


@dataclass(frozen=True)
class PublishedStartupVisibility:
    publication_id: str
    session_id: str
    run_id: str
    stage_run_id: str


__all__ = [
    "PUBLICATION_STATE_ABORTED",
    "PUBLICATION_STATE_PENDING",
    "PUBLICATION_STATE_PUBLISHED",
    "PublishedStartupVisibility",
]
