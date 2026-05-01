from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field


_INHERITED_TRACE_FIELDS = frozenset({"request_id", "trace_id", "correlation_id"})


class TraceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    parent_span_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    stage_run_id: str | None = Field(default=None, min_length=1)
    approval_id: str | None = Field(default=None, min_length=1)
    tool_confirmation_id: str | None = Field(default=None, min_length=1)
    delivery_record_id: str | None = Field(default=None, min_length=1)
    graph_thread_id: str | None = Field(default=None, min_length=1)
    created_at: datetime

    def child_span(
        self,
        *,
        span_id: str,
        created_at: datetime,
        **object_updates: Any,
    ) -> Self:
        if inherited_updates := _INHERITED_TRACE_FIELDS.intersection(object_updates):
            names = ", ".join(sorted(inherited_updates))
            raise ValueError(
                f"child span cannot override inherited trace fields: {names}"
            )

        data = self.model_dump()
        data.update(object_updates)
        data["parent_span_id"] = self.span_id
        data["span_id"] = span_id
        data["created_at"] = created_at
        return self.__class__.model_validate(data)


__all__ = ["TraceContext"]
