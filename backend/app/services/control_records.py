from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.db.models.runtime import RunControlRecordModel
from backend.app.domain.enums import ControlItemType, RunControlRecordType, StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.feed import ControlItemFeedEntry
from backend.app.services.events import DomainEventType, EventStore


@dataclass(frozen=True)
class RollbackControlResult:
    control_record: RunControlRecordModel
    control_item: ControlItemFeedEntry


@dataclass(frozen=True)
class ToolConfirmationControlResult:
    control_record: RunControlRecordModel


class ControlRecordService:
    def __init__(
        self,
        *,
        runtime_session: Session,
        event_session: Session,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime_session = runtime_session
        self._events = EventStore(event_session, now=now)
        self._now = now or (lambda: datetime.now(UTC))

    def append_rollback_control_item(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        source_stage_type: StageType,
        target_stage_type: StageType,
        payload_ref: str,
        summary: str,
        trace_context: TraceContext,
        occurred_at: datetime | None = None,
    ) -> RollbackControlResult:
        timestamp = occurred_at or self._now()
        control_record = RunControlRecordModel(
            control_record_id=f"control-record-{uuid4().hex}",
            run_id=run_id,
            stage_run_id=stage_run_id,
            control_type=RunControlRecordType.ROLLBACK,
            source_stage_type=source_stage_type,
            target_stage_type=target_stage_type,
            payload_ref=payload_ref,
            graph_interrupt_ref=None,
            occurred_at=timestamp,
            created_at=timestamp,
        )
        self._runtime_session.add(control_record)
        control_item = ControlItemFeedEntry(
            entry_id=f"entry-{control_record.control_record_id}",
            run_id=run_id,
            occurred_at=timestamp,
            control_record_id=control_record.control_record_id,
            control_type=ControlItemType.ROLLBACK,
            source_stage_type=source_stage_type,
            target_stage_type=target_stage_type,
            title=f"Rollback to {target_stage_type.value}",
            summary=summary,
            payload_ref=payload_ref,
        )
        self._events.append(
            DomainEventType.ROLLBACK_TRIGGERED,
            payload={"control_item": control_item.model_dump(mode="json")},
            trace_context=trace_context,
        )
        return RollbackControlResult(
            control_record=control_record,
            control_item=control_item,
        )

    def append_tool_confirmation_control_record(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        source_stage_type: StageType,
        payload_ref: str,
        graph_interrupt_ref: str,
        occurred_at: datetime | None = None,
    ) -> ToolConfirmationControlResult:
        timestamp = occurred_at or self._now()
        control_record = RunControlRecordModel(
            control_record_id=f"control-record-{uuid4().hex}",
            run_id=run_id,
            stage_run_id=stage_run_id,
            control_type=RunControlRecordType.TOOL_CONFIRMATION,
            source_stage_type=source_stage_type,
            target_stage_type=None,
            payload_ref=payload_ref,
            graph_interrupt_ref=graph_interrupt_ref,
            occurred_at=timestamp,
            created_at=timestamp,
        )
        self._runtime_session.add(control_record)
        return ToolConfirmationControlResult(control_record=control_record)


__all__ = [
    "ControlRecordService",
    "RollbackControlResult",
    "ToolConfirmationControlResult",
]
