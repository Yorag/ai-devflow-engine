from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricSet(_StrictBaseModel):
    duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    attempt_index: int | None = Field(default=None, ge=1)
    context_file_count: int | None = Field(default=None, ge=0)
    reasoning_step_count: int | None = Field(default=None, ge=0)
    tool_call_count: int | None = Field(default=None, ge=0)
    changed_file_count: int | None = Field(default=None, ge=0)
    added_line_count: int | None = Field(default=None, ge=0)
    removed_line_count: int | None = Field(default=None, ge=0)
    generated_test_count: int | None = Field(default=None, ge=0)
    executed_test_count: int | None = Field(default=None, ge=0)
    passed_test_count: int | None = Field(default=None, ge=0)
    failed_test_count: int | None = Field(default=None, ge=0)
    skipped_test_count: int | None = Field(default=None, ge=0)
    test_gap_count: int | None = Field(default=None, ge=0)
    retry_index: int | None = Field(default=None, ge=0)
    source_attempt_index: int | None = Field(default=None, ge=1)
    delivery_artifact_count: int | None = Field(default=None, ge=0)

    @model_serializer(mode="wrap")
    def serialize_applicable_metrics_only(self, handler):
        dumped = handler(self)
        return {
            metric_name: metric_value
            for metric_name, metric_value in dumped.items()
            if metric_value is not None
        }


__all__ = [
    "MetricSet",
]
