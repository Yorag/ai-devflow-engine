from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum, Integer, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.domain.enums import SseEventType


JsonObject = dict[str, Any]


def _contract_enum(enum_type: type, name: str) -> SqlEnum:
    return SqlEnum(
        enum_type,
        values_callable=lambda values: [item.value for item in values],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name,
    )


class EventBase(DeclarativeBase):
    metadata = ROLE_METADATA[DatabaseRole.EVENT]


class DomainEventModel(EventBase):
    __tablename__ = "domain_events"

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    stage_run_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    event_type: Mapped[SseEventType] = mapped_column(
        _contract_enum(SseEventType, "domain_event_type"),
        nullable=False,
        index=True,
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    payload: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        index=True,
    )
    causation_event_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "DomainEventModel",
    "EventBase",
]
