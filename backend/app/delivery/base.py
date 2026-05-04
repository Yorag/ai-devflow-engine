from __future__ import annotations

from typing import Annotated, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.enums import DeliveryMode
from backend.app.domain.trace_context import TraceContext


NonEmptyRef = Annotated[str, Field(min_length=1)]


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeliveryAdapterInput(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    delivery_channel_snapshot_ref: str = Field(min_length=1)
    delivery_mode: DeliveryMode
    requirement_refs: list[NonEmptyRef] = Field(default_factory=list)
    solution_refs: list[NonEmptyRef] = Field(default_factory=list)
    changeset_refs: list[NonEmptyRef] = Field(default_factory=list)
    test_result_refs: list[NonEmptyRef] = Field(default_factory=list)
    review_refs: list[NonEmptyRef] = Field(default_factory=list)
    approval_result_refs: list[NonEmptyRef] = Field(default_factory=list)
    artifact_refs: list[NonEmptyRef] = Field(default_factory=list)
    trace_context: TraceContext

    @model_validator(mode="after")
    def validate_trace_identity(self) -> "DeliveryAdapterInput":
        if self.trace_context.run_id is not None and self.trace_context.run_id != self.run_id:
            raise ValueError("trace_context.run_id must match run_id")
        if (
            self.trace_context.stage_run_id is not None
            and self.trace_context.stage_run_id != self.stage_run_id
        ):
            raise ValueError("trace_context.stage_run_id must match stage_run_id")
        return self


class DeliveryAdapterError(_StrictBaseModel):
    error_code: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)
    safe_details: dict[str, Any] = Field(default_factory=dict)


class DeliveryAdapterResult(_StrictBaseModel):
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    delivery_mode: DeliveryMode
    status: str = Field(pattern="^(succeeded|failed|blocked)$")
    result_ref: str | None = Field(default=None, min_length=1)
    process_ref: str | None = Field(default=None, min_length=1)
    branch_name: str | None = Field(default=None, min_length=1)
    commit_sha: str | None = Field(default=None, min_length=1)
    code_review_url: str | None = Field(default=None, min_length=1)
    audit_refs: list[NonEmptyRef] = Field(default_factory=list)
    log_summary_refs: list[NonEmptyRef] = Field(default_factory=list)
    error: DeliveryAdapterError | None = None
    trace_context: TraceContext

    @model_validator(mode="after")
    def validate_status_payload(self) -> "DeliveryAdapterResult":
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("succeeded delivery results must not include an error")
        if self.status != "succeeded" and self.error is None:
            raise ValueError("non-succeeded delivery results must include an error")
        if self.trace_context.run_id is not None and self.trace_context.run_id != self.run_id:
            raise ValueError("trace_context.run_id must match run_id")
        if (
            self.trace_context.stage_run_id is not None
            and self.trace_context.stage_run_id != self.stage_run_id
        ):
            raise ValueError("trace_context.stage_run_id must match stage_run_id")
        return self


class DeliveryAdapter(Protocol):
    @property
    def delivery_mode(self) -> DeliveryMode: ...

    @property
    def name(self) -> str: ...

    def deliver(self, delivery_input: DeliveryAdapterInput) -> DeliveryAdapterResult: ...


__all__ = [
    "DeliveryAdapter",
    "DeliveryAdapterError",
    "DeliveryAdapterInput",
    "DeliveryAdapterResult",
]
