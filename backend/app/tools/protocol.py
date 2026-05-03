from __future__ import annotations

from enum import StrEnum
from math import isfinite
import re
from typing import Annotated, Any, Mapping, Protocol, Self, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.api.error_codes import (
    ErrorCode,
    assert_error_code_registered,
    lookup_error_code,
)
from backend.app.domain.enums import ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext


NonEmptyRef = Annotated[str, Field(min_length=1)]
JsonObject = dict[str, Any]
ToolName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=1)]
ToolCategoryName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=1)]


class ToolSideEffectLevel(StrEnum):
    NONE = "none"
    WORKSPACE_READ = "workspace_read"
    WORKSPACE_WRITE = "workspace_write"
    PROCESS_EXECUTION = "process_execution"
    GIT_WRITE = "git_write"
    REMOTE_DELIVERY_WRITE = "remote_delivery_write"
    CONFIGURATION_WRITE = "configuration_write"


class ToolResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING_CONFIRMATION = "waiting_confirmation"


class ToolReconciliationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    RECONCILED = "reconciled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if isfinite(value):
            return
        raise ValueError(f"{path} must be a finite JSON number")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} must be JSON-serializable")


def _validate_json_object(value: JsonObject) -> JsonObject:
    _validate_json_value(value, path="$")
    return value


_SENSITIVE_DETAIL_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "api_key",
        "apikey",
        "private_key",
        "secret",
        "token",
        "password",
    }
)
_SENSITIVE_DETAIL_VALUE_PATTERNS = (
    re.compile(r"Traceback"),
    re.compile(r"Authorization:", re.IGNORECASE),
    re.compile(r"Cookie:", re.IGNORECASE),
    re.compile(r"API Key", re.IGNORECASE),
    re.compile(r"private key", re.IGNORECASE),
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(
        r"(?<![A-Za-z0-9_])(?:api_key|password|secret|token)\s*=\s*\S+",
        re.IGNORECASE,
    ),
)


def _normalize_sensitive_key(key: str) -> str:
    return key.lower().replace("-", "_").replace(" ", "_")


def _validate_safe_detail_content(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = _normalize_sensitive_key(key)
            if normalized_key in _SENSITIVE_DETAIL_KEYS:
                raise ValueError(f"{path}.{key} contains sensitive detail")
            _validate_safe_detail_content(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_safe_detail_content(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in _SENSITIVE_DETAIL_VALUE_PATTERNS):
            raise ValueError(f"{path} contains sensitive detail")


class ToolPermissionBoundary(_StrictBaseModel):
    boundary_type: ToolCategoryName
    requires_workspace: bool
    resource_scopes: tuple[NonEmptyRef, ...] = Field(default_factory=tuple)
    external_access: bool = False


class ToolAuditRef(_StrictBaseModel):
    audit_id: NonEmptyRef
    action: NonEmptyRef
    trace_id: NonEmptyRef
    correlation_id: NonEmptyRef
    metadata_ref: NonEmptyRef | None = None


class ToolBindableDescription(_StrictBaseModel):
    name: ToolName
    description: str = Field(min_length=1)
    input_schema: JsonObject
    result_schema: JsonObject
    risk_level: ToolRiskLevel
    risk_categories: list[ToolRiskCategory] = Field(default_factory=list)

    _validate_schema_objects = field_validator("input_schema", "result_schema")(
        _validate_json_object
    )

    def to_langchain_tool_schema(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }


class ToolInput(_StrictBaseModel):
    tool_name: ToolName
    call_id: NonEmptyRef
    input_payload: JsonObject = Field(default_factory=dict)
    trace_context: TraceContext
    coordination_key: NonEmptyRef
    side_effect_intent_ref: NonEmptyRef | None = None

    _validate_input_payload = field_validator("input_payload")(_validate_json_object)

    @property
    def trace_id(self) -> str:
        return self.trace_context.trace_id

    @property
    def correlation_id(self) -> str:
        return self.trace_context.correlation_id

    @property
    def span_id(self) -> str:
        return self.trace_context.span_id


class ToolError(_StrictBaseModel):
    error_code: ErrorCode
    safe_message: str = Field(min_length=1)
    safe_details: JsonObject = Field(default_factory=dict)
    trace_context: TraceContext
    audit_ref: ToolAuditRef | None = None

    @field_validator("error_code")
    @classmethod
    def _validate_error_code(cls, value: ErrorCode) -> ErrorCode:
        return assert_error_code_registered(value)

    @field_validator("safe_details")
    @classmethod
    def _validate_safe_details(cls, value: JsonObject) -> JsonObject:
        _validate_json_object(value)
        _validate_safe_detail_content(value, path="safe_details")
        return value

    @field_validator("safe_message")
    @classmethod
    def _validate_safe_message(cls, value: str) -> str:
        _validate_safe_detail_content(value, path="safe_message")
        return value

    @classmethod
    def from_code(
        cls,
        error_code: ErrorCode | str,
        *,
        trace_context: TraceContext,
        safe_message: str | None = None,
        safe_details: JsonObject | None = None,
        audit_ref: ToolAuditRef | None = None,
    ) -> Self:
        entry = lookup_error_code(error_code)
        return cls(
            error_code=entry.error_code,
            safe_message=(
                entry.default_safe_message if safe_message is None else safe_message
            ),
            safe_details=safe_details or {},
            trace_context=trace_context,
            audit_ref=audit_ref,
        )

    @property
    def trace_id(self) -> str:
        return self.trace_context.trace_id

    @property
    def correlation_id(self) -> str:
        return self.trace_context.correlation_id

    @property
    def span_id(self) -> str:
        return self.trace_context.span_id


class ToolResult(_StrictBaseModel):
    tool_name: ToolName
    call_id: NonEmptyRef
    status: ToolResultStatus
    output_payload: JsonObject = Field(default_factory=dict)
    output_preview: str | None = Field(default=None, min_length=1)
    error: ToolError | None = None
    artifact_refs: list[NonEmptyRef] = Field(default_factory=list)
    side_effect_refs: list[NonEmptyRef] = Field(default_factory=list)
    tool_confirmation_ref: NonEmptyRef | None = None
    reconciliation_status: ToolReconciliationStatus = (
        ToolReconciliationStatus.NOT_REQUIRED
    )
    audit_ref: ToolAuditRef | None = None
    trace_context: TraceContext
    coordination_key: NonEmptyRef

    _validate_output_payload = field_validator("output_payload")(_validate_json_object)

    @property
    def trace_id(self) -> str:
        return self.trace_context.trace_id

    @property
    def correlation_id(self) -> str:
        return self.trace_context.correlation_id

    @property
    def span_id(self) -> str:
        return self.trace_context.span_id


@runtime_checkable
class ToolProtocol(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def category(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> Mapping[str, object]: ...

    @property
    def result_schema(self) -> Mapping[str, object]: ...

    @property
    def default_risk_level(self) -> ToolRiskLevel: ...

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]: ...

    @property
    def permission_boundary(self) -> ToolPermissionBoundary: ...

    @property
    def side_effect_level(self) -> ToolSideEffectLevel: ...

    @property
    def audit_required(self) -> bool: ...

    def bindable_description(self) -> ToolBindableDescription: ...


__all__ = [
    "ToolAuditRef",
    "ToolBindableDescription",
    "ToolCategoryName",
    "ToolError",
    "ToolInput",
    "ToolName",
    "ToolPermissionBoundary",
    "ToolProtocol",
    "ToolReconciliationStatus",
    "ToolResult",
    "ToolResultStatus",
    "ToolRiskCategory",
    "ToolRiskLevel",
    "ToolSideEffectLevel",
]
