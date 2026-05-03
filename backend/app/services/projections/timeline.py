from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.runtime import PipelineRunModel, StageRunModel
from backend.app.schemas.feed import ApprovalResultFeedEntry, TopLevelFeedEntry
from backend.app.schemas.run import RunTimelineProjection
from backend.app.services.events import DomainEvent, EventStore


TOP_LEVEL_FEED_ENTRY_ADAPTER = TypeAdapter(TopLevelFeedEntry)
RUN_TIMELINE_NOT_FOUND_MESSAGE = "Run timeline was not found."


class TimelineProjectionServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class TimelineProjectionService:
    def __init__(
        self,
        control_session: Session,
        runtime_session: Session,
        event_session: Session,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_store = EventStore(event_session)

    def get_run_timeline(self, run_id: str) -> RunTimelineProjection:
        run = self._get_visible_run(run_id)
        return RunTimelineProjection(
            run_id=run.run_id,
            session_id=run.session_id,
            attempt_index=run.attempt_index,
            trigger_source=run.trigger_source,
            status=run.status,
            started_at=self._projection_datetime(run.started_at),
            ended_at=self._projection_datetime(run.ended_at),
            current_stage_type=self._stage_type_for_run(run),
            entries=self.build_timeline_entries(run.run_id, run.session_id),
        )

    def build_timeline_entries(
        self,
        run_id: str,
        session_id: str,
    ) -> list[TopLevelFeedEntry]:
        entries: list[TopLevelFeedEntry] = []
        for event in self._event_store.list_for_session(session_id):
            if event.run_id != run_id:
                continue
            entry = self._entry_from_event(event)
            if entry is None or entry.run_id != run_id:
                continue
            entries = self._upsert_feed_entry(entries, entry)
        return sorted(entries, key=lambda entry: entry.occurred_at)

    def _get_visible_run(self, run_id: str) -> PipelineRunModel:
        run = self._runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            self._raise_not_found()
        session = self._control_session.get(SessionModel, run.session_id)
        if session is None or not session.is_visible:
            self._raise_not_found()
        project = self._control_session.get(ProjectModel, run.project_id)
        if project is None or not project.is_visible:
            self._raise_not_found()
        if session.project_id != project.project_id:
            self._raise_not_found()
        return run

    def _entry_from_event(self, event: DomainEvent) -> TopLevelFeedEntry | None:
        for key in (
            "message_item",
            "stage_node",
            "control_item",
            "approval_request",
            "approval_result",
            "tool_confirmation",
            "delivery_result",
            "system_status",
        ):
            value: Any = event.payload.get(key)
            if value is not None:
                return TOP_LEVEL_FEED_ENTRY_ADAPTER.validate_python(value)
        return None

    def _upsert_feed_entry(
        self,
        entries: list[TopLevelFeedEntry],
        incoming: TopLevelFeedEntry,
    ) -> list[TopLevelFeedEntry]:
        if isinstance(incoming, ApprovalResultFeedEntry):
            entries = self._apply_approval_result(entries, incoming)
        incoming_identity = self._feed_identity(incoming)
        for index, entry in enumerate(entries):
            if self._feed_identity(entry) == incoming_identity:
                return entries[:index] + [incoming] + entries[index + 1 :]
        return [*entries, incoming]

    def _apply_approval_result(
        self,
        entries: list[TopLevelFeedEntry],
        approval_result: ApprovalResultFeedEntry,
    ) -> list[TopLevelFeedEntry]:
        return [
            entry.model_copy(
                update={
                    "status": approval_result.decision,
                    "is_actionable": False,
                },
            )
            if (
                entry.type == "approval_request"
                and entry.approval_id == approval_result.approval_id
            )
            else entry
            for entry in entries
        ]

    @staticmethod
    def _feed_identity(entry: TopLevelFeedEntry) -> str:
        if entry.type == "user_message":
            return f"{entry.type}:{entry.message_id}"
        if entry.type == "stage_node":
            return f"{entry.type}:{entry.stage_run_id}"
        if entry.type == "approval_request":
            return f"{entry.type}:{entry.approval_id}"
        if entry.type == "tool_confirmation":
            return f"{entry.type}:{entry.tool_confirmation_id}"
        if entry.type == "control_item":
            return f"{entry.type}:{entry.control_record_id}"
        if entry.type == "approval_result":
            return f"{entry.type}:{entry.approval_id}"
        if entry.type == "delivery_result":
            return f"{entry.type}:{entry.delivery_record_id}"
        return f"{entry.type}:{entry.run_id}:{entry.status}"

    def _stage_type_for_run(self, run: PipelineRunModel):
        if run.current_stage_run_id is None:
            return None
        stage = self._runtime_session.get(StageRunModel, run.current_stage_run_id)
        if stage is None:
            return None
        if stage.run_id != run.run_id:
            return None
        return stage.stage_type

    @staticmethod
    def _projection_datetime(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)

    @staticmethod
    def _raise_not_found() -> None:
        raise TimelineProjectionServiceError(
            ErrorCode.NOT_FOUND,
            RUN_TIMELINE_NOT_FOUND_MESSAGE,
            404,
        )


__all__ = [
    "TimelineProjectionService",
    "TimelineProjectionServiceError",
]
