from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.db.models.runtime import PipelineRunModel
from backend.app.domain.template_snapshot import TemplateSnapshot


class RunLifecycleService:
    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))

    def attach_template_snapshot(
        self,
        run: PipelineRunModel,
        snapshot: TemplateSnapshot,
    ) -> PipelineRunModel:
        if run.run_id != snapshot.run_id:
            raise ValueError("template snapshot run_id must match PipelineRun.run_id")
        run.template_snapshot_ref = snapshot.snapshot_ref
        run.updated_at = self._now()
        self._session.add(run)
        return run


__all__ = ["RunLifecycleService"]
