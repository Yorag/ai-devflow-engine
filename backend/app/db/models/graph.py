from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.domain.enums import StageType


JsonObject = dict[str, Any]

GRAPH_THREAD_STATUSES = (
    "pending",
    "running",
    "interrupted",
    "paused",
    "completed",
    "failed",
    "terminated",
)
GRAPH_INTERRUPT_TYPES = (
    "clarification_request",
    "solution_design_approval",
    "code_review_approval",
    "tool_confirmation",
)
GRAPH_INTERRUPT_STATUSES = ("pending", "responded", "cancelled")
GRAPH_RUNTIME_OBJECT_TYPES = (
    "clarification_record",
    "approval_request",
    "tool_confirmation_request",
)


def _contract_enum(enum_type: type, name: str) -> SqlEnum:
    return SqlEnum(
        enum_type,
        values_callable=lambda values: [item.value for item in values],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name,
    )


def _string_enum(name: str, values: tuple[str, ...]) -> SqlEnum:
    return SqlEnum(
        *values,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name,
    )


class GraphBase(DeclarativeBase):
    metadata = ROLE_METADATA[DatabaseRole.GRAPH]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GraphDefinitionModel(GraphBase):
    __tablename__ = "graph_definitions"

    graph_definition_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    template_snapshot_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(120), nullable=False)
    stage_nodes: Mapped[list[JsonObject]] = mapped_column(JSON, nullable=False)
    stage_contracts: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    interrupt_policy: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    retry_policy: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    delivery_routing_policy: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GraphThreadModel(GraphBase, TimestampMixin):
    __tablename__ = "graph_threads"

    graph_thread_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    graph_definition_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("graph_definitions.graph_definition_id"),
        nullable=False,
        index=True,
    )
    checkpoint_namespace: Mapped[str] = mapped_column(String(160), nullable=False)
    current_node_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_interrupt_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        _string_enum("graph_thread_status", GRAPH_THREAD_STATUSES),
        nullable=False,
    )
    last_checkpoint_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)


class GraphCheckpointModel(GraphBase):
    __tablename__ = "graph_checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    graph_thread_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("graph_threads.graph_thread_id"),
        nullable=False,
        index=True,
    )
    checkpoint_ref: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    node_key: Mapped[str] = mapped_column(String(120), nullable=False)
    state_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GraphInterruptModel(GraphBase, TimestampMixin):
    __tablename__ = "graph_interrupts"

    interrupt_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    graph_thread_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("graph_threads.graph_thread_id"),
        nullable=False,
        index=True,
    )
    interrupt_type: Mapped[str] = mapped_column(
        _string_enum("graph_interrupt_type", GRAPH_INTERRUPT_TYPES),
        nullable=False,
    )
    source_stage_type: Mapped[StageType] = mapped_column(
        _contract_enum(StageType, "graph_interrupt_source_stage_type"),
        nullable=False,
    )
    source_node_key: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    runtime_object_ref: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    runtime_object_type: Mapped[str] = mapped_column(
        _string_enum("graph_interrupt_runtime_object_type", GRAPH_RUNTIME_OBJECT_TYPES),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        _string_enum("graph_interrupt_status", GRAPH_INTERRUPT_STATUSES),
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


__all__ = [
    "GRAPH_INTERRUPT_STATUSES",
    "GRAPH_INTERRUPT_TYPES",
    "GRAPH_RUNTIME_OBJECT_TYPES",
    "GRAPH_THREAD_STATUSES",
    "GraphBase",
    "GraphCheckpointModel",
    "GraphDefinitionModel",
    "GraphInterruptModel",
    "GraphThreadModel",
]
