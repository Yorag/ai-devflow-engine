from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.protocol import (
    ToolAuditRef,
    ToolBindableDescription,
    ToolError,
    ToolInput,
    ToolProtocol,
    ToolResult,
    ToolResultStatus,
    ToolSideEffectLevel,
    _validate_json_object,
)
from backend.app.tools.registry import InvalidToolDefinitionError, UnknownToolError
from backend.app.tools.risk import (
    ToolConfirmationGrant,
    ToolConfirmationRequestPort,
    ToolRiskAssessment,
    ToolRiskClassifier,
)


JsonObject = dict[str, Any]
_CONTRACT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolWorkspaceBoundaryError(ValueError):
    def __init__(self, message: str, *, target: str) -> None:
        super().__init__(message)
        self.target = target


class WorkspaceBoundaryPort(Protocol):
    def assert_inside_workspace(
        self,
        target: str,
        *,
        trace_context: TraceContext,
    ) -> None: ...


class ToolAuditRecorderPort(Protocol):
    def record_tool_intent(
        self,
        *,
        request: "ToolExecutionRequest",
        tool_name: str,
        trace_context: TraceContext,
    ) -> ToolAuditRef: ...

    def record_tool_rejection(
        self,
        *,
        request: "ToolExecutionRequest",
        error_code: ErrorCode,
        trace_context: TraceContext,
    ) -> ToolAuditRef: ...


class ToolRunLogRecorderPort(Protocol):
    def record_tool_result(
        self,
        *,
        request: "ToolExecutionRequest",
        result: ToolResult,
        duration_ms: int,
    ) -> None: ...


class ToolRiskInspectionPort(Protocol):
    def inspect_tool_intent(
        self,
        *,
        request: "ToolExecutionRequest",
        tool_name: str,
        trace_context: TraceContext,
    ) -> None: ...


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolExecutionRequest(_StrictBaseModel):
    tool_name: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    input_payload: JsonObject = Field(default_factory=dict)
    trace_context: TraceContext
    coordination_key: str = Field(min_length=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    confirmation_grant: ToolConfirmationGrant | None = None


@dataclass(frozen=True)
class ToolExecutionContext:
    stage_type: StageType
    stage_contracts: Mapping[str, Any]
    trace_context: TraceContext
    runtime_tool_timeout_seconds: float | None = None
    platform_tool_timeout_hard_limit_seconds: float | None = None
    workspace_boundary: WorkspaceBoundaryPort | None = None
    audit_recorder: ToolAuditRecorderPort | None = None
    run_log_recorder: ToolRunLogRecorderPort | None = None
    risk_policy: ToolRiskInspectionPort | None = None
    confirmation_port: ToolConfirmationRequestPort | None = None

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        contract = self.stage_contracts.get(self.stage_type.value, {})
        if not isinstance(contract, Mapping):
            return ()
        raw_allowed = contract.get("allowed_tools", [])
        if not isinstance(raw_allowed, list):
            return ()
        return tuple(item for item in raw_allowed if isinstance(item, str))


@dataclass(frozen=True)
class _ValidatedExecution:
    tool: ToolProtocol
    audit_ref: ToolAuditRef | None
    timeout_seconds: float | None


class ToolInputSchemaValidator:
    def validate(self, schema: Mapping[str, object], payload: JsonObject) -> None:
        _validate_json_object(payload)
        self._validate_object_schema(schema, payload, path="$")

    def _validate_object_schema(
        self,
        schema: Mapping[str, object],
        payload: JsonObject,
        *,
        path: str,
    ) -> None:
        schema_type = schema.get("type")
        if schema_type not in (None, "object"):
            raise ValueError(f"{path} schema must describe an object input")

        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError(f"{path}.properties must be an object")

        required = schema.get("required", [])
        if not isinstance(required, list) or not all(
            isinstance(item, str) for item in required
        ):
            raise ValueError(f"{path}.required must be a string list")
        for field_name in required:
            if field_name not in payload:
                raise ValueError(f"{path}.{field_name} is required")

        if schema.get("additionalProperties") is False:
            allowed = set(properties)
            extra = sorted(set(payload) - allowed)
            if extra:
                raise ValueError(f"{path}.{extra[0]} is not allowed")

        for field_name, value in payload.items():
            field_schema = properties.get(field_name)
            if field_schema is None:
                continue
            if not isinstance(field_schema, Mapping):
                raise ValueError(f"{path}.{field_name} schema must be an object")
            self._validate_value(field_schema, value, path=f"{path}.{field_name}")

    def _validate_value(
        self,
        schema: Mapping[str, object],
        value: object,
        *,
        path: str,
    ) -> None:
        expected_type = schema.get("type")
        if expected_type is not None:
            self._validate_type(expected_type, value, path=path)

        enum_values = schema.get("enum")
        if enum_values is not None:
            if not isinstance(enum_values, list):
                raise ValueError(f"{path}.enum must be a list")
            if value not in enum_values:
                raise ValueError(f"{path} must match an allowed value")

        min_length = schema.get("minLength")
        if min_length is not None:
            if not isinstance(min_length, int) or min_length < 0:
                raise ValueError(f"{path}.minLength must be a non-negative integer")
            if isinstance(value, str) and len(value) < min_length:
                raise ValueError(f"{path} is shorter than minLength")

        if expected_type == "object":
            if not isinstance(value, dict):
                raise ValueError(f"{path} must be an object")
            self._validate_object_schema(schema, value, path=path)
            return

        if expected_type == "array":
            if not isinstance(value, list):
                raise ValueError(f"{path} must be an array")
            items_schema = schema.get("items")
            if items_schema is None:
                return
            if not isinstance(items_schema, Mapping):
                raise ValueError(f"{path}.items must be an object")
            for index, item in enumerate(value):
                self._validate_value(items_schema, item, path=f"{path}[{index}]")
            return

    def _validate_type(self, expected_type: object, value: object, *, path: str) -> None:
        if expected_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"{path} must be a string")
            return
        if expected_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{path} must be an integer")
            return
        if expected_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{path} must be a number")
            return
        if expected_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{path} must be a boolean")
            return
        if expected_type == "object":
            if not isinstance(value, dict):
                raise ValueError(f"{path} must be an object")
            return
        if expected_type == "array":
            if not isinstance(value, list):
                raise ValueError(f"{path} must be an array")
            return
        if expected_type == "null":
            if value is not None:
                raise ValueError(f"{path} must be null")
            return
        raise ValueError(f"{path} uses an unsupported type")


class ToolTimeoutPolicy:
    def resolve_timeout(
        self,
        *,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
        tool: ToolProtocol,
    ) -> float | None:
        candidates = (
            request.timeout_seconds,
            context.runtime_tool_timeout_seconds,
            tool.default_timeout_seconds,
        )
        resolved = next((value for value in candidates if value is not None), None)
        hard_limit = context.platform_tool_timeout_hard_limit_seconds
        if resolved is None:
            return hard_limit
        if hard_limit is None:
            return resolved
        return min(resolved, hard_limit)


class ToolAuditPolicy:
    def requires_audit(self, tool: ToolProtocol) -> bool:
        return (
            tool.audit_required
            or tool.side_effect_level != ToolSideEffectLevel.NONE
        )


class ToolExecutionGate:
    def __init__(self, registry: object) -> None:
        self._registry = registry
        self._schema_validator = ToolInputSchemaValidator()
        self._timeout_policy = ToolTimeoutPolicy()
        self._audit_policy = ToolAuditPolicy()
        self._risk_classifier = ToolRiskClassifier()

    def available_tools(
        self,
        context: ToolExecutionContext,
    ) -> tuple[ToolBindableDescription, ...]:
        allowed = set(context.allowed_tools)
        return tuple(
            description
            for description in self._registry.list_bindable_tools()
            if description.name in allowed
        )

    def execute(
        self,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
    ) -> ToolResult:
        started = time.monotonic()
        validation = self.validate(request, context)
        if isinstance(validation, ToolResult):
            self._record_log(request=request, result=validation, started=started, context=context)
            return validation

        try:
            tool_input = ToolInput(
                tool_name=validation.tool.name,
                call_id=request.call_id,
                input_payload=dict(request.input_payload),
                trace_context=request.trace_context,
                coordination_key=request.coordination_key,
                side_effect_intent_ref=(
                    validation.audit_ref.audit_id if validation.audit_ref is not None else None
                ),
                timeout_seconds=validation.timeout_seconds,
            )
        except ValidationError as exc:
            result = self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
                tool_name=validation.tool.name,
                safe_details={"reason": str(exc.errors()[0]["msg"])},
                audit_ref=validation.audit_ref,
            )
            self._record_log(request=request, result=result, started=started, context=context)
            return result
        try:
            result = validation.tool.execute(tool_input)
        except TimeoutError:
            result = self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_TIMEOUT,
                tool_name=validation.tool.name,
                safe_details={"timeout_seconds": validation.timeout_seconds},
            )
        except Exception:
            result = self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.INTERNAL_ERROR,
                tool_name=validation.tool.name,
                safe_details={"reason": "tool_execution_failed"},
                audit_ref=validation.audit_ref,
            )

        if not isinstance(result, ToolResult):
            result = self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.INTERNAL_ERROR,
                tool_name=validation.tool.name,
                safe_details={"reason": "tool_result_invalid"},
                audit_ref=validation.audit_ref,
            )

        if validation.audit_ref is not None:
            normalized_error = result.error
            if normalized_error is not None and normalized_error.audit_ref != validation.audit_ref:
                normalized_error = normalized_error.model_copy(
                    update={"audit_ref": validation.audit_ref}
                )
            if result.audit_ref != validation.audit_ref or normalized_error is not result.error:
                result = result.model_copy(
                    update={
                        "audit_ref": validation.audit_ref,
                        "error": normalized_error,
                    }
                )
        self._record_log(request=request, result=result, started=started, context=context)
        return result

    def validate(
        self,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
    ) -> _ValidatedExecution | ToolResult:
        if not _CONTRACT_NAME_PATTERN.fullmatch(request.tool_name):
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_UNKNOWN,
                tool_name="unknown_tool",
                safe_details={"requested_tool_name": request.tool_name},
            )

        try:
            tool = self._registry.resolve(request.tool_name)
        except (InvalidToolDefinitionError, UnknownToolError):
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_UNKNOWN,
                tool_name=request.tool_name,
                safe_details={"requested_tool_name": request.tool_name},
            )

        if tool.name not in context.allowed_tools:
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_NOT_ALLOWED,
                tool_name=tool.name,
                safe_details={
                    "requested_tool_name": request.tool_name,
                    "stage_type": context.stage_type.value,
                },
            )

        try:
            self._schema_validator.validate(tool.input_schema, request.input_payload)
        except ValueError as exc:
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
                tool_name=tool.name,
                safe_details={"reason": str(exc)},
            )

        boundary_result = self._validate_workspace_boundary(
            request=request,
            context=context,
            tool=tool,
        )
        if boundary_result is not None:
            return boundary_result

        timeout_seconds = self._timeout_policy.resolve_timeout(
            request=request,
            context=context,
            tool=tool,
        )

        audit_ref = self._record_audit_intent(
            request=request,
            context=context,
            tool=tool,
        )
        if isinstance(audit_ref, ToolResult):
            return audit_ref

        if context.risk_policy is not None:
            try:
                context.risk_policy.inspect_tool_intent(
                    request=request,
                    tool_name=tool.name,
                    trace_context=request.trace_context,
                )
            except Exception:
                return self._error_result(
                    request=request,
                    context=context,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    tool_name=tool.name,
                    safe_details={"reason": "risk_policy_failed"},
                    audit_ref=audit_ref,
                )

        assessment = self._risk_classifier.classify(tool=tool, request=request)
        risk_result = self._validate_risk_confirmation(
            request=request,
            context=context,
            tool=tool,
            assessment=assessment,
            audit_ref=audit_ref,
        )
        if risk_result is not None:
            return risk_result

        return _ValidatedExecution(
            tool=tool,
            audit_ref=audit_ref,
            timeout_seconds=timeout_seconds,
        )

    def _validate_risk_confirmation(
        self,
        *,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
        tool: ToolProtocol,
        assessment: ToolRiskAssessment,
        audit_ref: ToolAuditRef | None,
    ) -> ToolResult | None:
        if assessment.is_blocked:
            rejection_audit_ref = self._record_rejection_audit(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_RISK_BLOCKED,
            )
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_RISK_BLOCKED,
                status=ToolResultStatus.BLOCKED,
                tool_name=tool.name,
                safe_details=self._risk_safe_details(assessment),
                audit_ref=rejection_audit_ref,
            )

        if not assessment.requires_confirmation:
            return None

        if self._grant_matches(
            request.confirmation_grant,
            assessment,
            request=request,
            tool_name=tool.name,
        ):
            return None

        return self._build_waiting_confirmation_result(
            request=request,
            context=context,
            tool_name=tool.name,
            assessment=assessment,
            audit_ref=audit_ref,
        )

    def _grant_matches(
        self,
        grant: ToolConfirmationGrant | None,
        assessment: ToolRiskAssessment,
        *,
        request: ToolExecutionRequest,
        tool_name: str,
    ) -> bool:
        if grant is None:
            return False
        return (
            request.trace_context.tool_confirmation_id == grant.tool_confirmation_id
            and grant.tool_name == tool_name
            and grant.confirmation_object_ref == assessment.confirmation_object_ref
            and grant.input_digest == assessment.input_digest
            and grant.target_summary == assessment.target_summary
            and grant.risk_level is assessment.risk_level
            and list(grant.risk_categories) == list(assessment.risk_categories)
        )

    def _build_waiting_confirmation_result(
        self,
        *,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
        tool_name: str,
        assessment: ToolRiskAssessment,
        audit_ref: ToolAuditRef | None,
    ) -> ToolResult:
        if context.confirmation_port is None:
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.INTERNAL_ERROR,
                tool_name=tool_name,
                safe_details={"reason": "confirmation_port_unavailable"},
                audit_ref=audit_ref,
            )

        session_id = request.trace_context.session_id
        run_id = request.trace_context.run_id
        stage_run_id = request.trace_context.stage_run_id
        if session_id is None or run_id is None or stage_run_id is None:
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.INTERNAL_ERROR,
                tool_name=tool_name,
                safe_details={"reason": "confirmation_target_missing"},
                audit_ref=audit_ref,
            )

        try:
            created = context.confirmation_port.create_request(
                session_id=session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                confirmation_object_ref=assessment.confirmation_object_ref,
                tool_name=tool_name,
                command_preview=assessment.command_preview,
                target_summary=assessment.target_summary,
                risk_level=assessment.risk_level,
                risk_categories=list(assessment.risk_categories),
                reason=assessment.reason,
                expected_side_effects=list(assessment.expected_side_effects),
                alternative_path_summary=assessment.alternative_path_summary,
                trace_context=request.trace_context,
            )
        except Exception:
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.INTERNAL_ERROR,
                tool_name=tool_name,
                safe_details={"reason": "confirmation_request_failed"},
                audit_ref=audit_ref,
            )

        tool_confirmation_id = getattr(created, "tool_confirmation_id", None)
        if not isinstance(tool_confirmation_id, str) or not tool_confirmation_id:
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.INTERNAL_ERROR,
                tool_name=tool_name,
                safe_details={"reason": "confirmation_request_invalid"},
                audit_ref=audit_ref,
            )

        return self._error_result(
            request=request,
            context=context,
            error_code=ErrorCode.TOOL_CONFIRMATION_REQUIRED,
            status=ToolResultStatus.WAITING_CONFIRMATION,
            tool_name=tool_name,
            safe_details=self._risk_safe_details(assessment, include_digest=True),
            audit_ref=audit_ref,
            tool_confirmation_ref=tool_confirmation_id,
        )

    def _risk_safe_details(
        self,
        assessment: ToolRiskAssessment,
        *,
        include_digest: bool = False,
    ) -> JsonObject:
        details: JsonObject = {
            "risk_level": assessment.risk_level.value,
            "risk_categories": [
                category.value for category in assessment.risk_categories
            ],
            "target_summary": assessment.target_summary,
        }
        if include_digest:
            details["input_digest"] = assessment.input_digest
        return details

    def _validate_workspace_boundary(
        self,
        *,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
        tool: ToolProtocol,
    ) -> ToolResult | None:
        if not tool.permission_boundary.requires_workspace:
            return None

        targets = self._workspace_targets(
            request.input_payload,
            tool=tool,
        )
        if context.workspace_boundary is None:
            return self._workspace_boundary_result(
                request=request,
                context=context,
                tool_name=tool.name,
                safe_details={
                    "requested_tool_name": request.tool_name,
                    "reason": "workspace_boundary_unavailable",
                },
            )

        for target in targets:
            try:
                context.workspace_boundary.assert_inside_workspace(
                    target,
                    trace_context=request.trace_context,
                )
            except ToolWorkspaceBoundaryError as exc:
                return self._workspace_boundary_result(
                    request=request,
                    context=context,
                    tool_name=tool.name,
                    safe_details={
                        "target": exc.target,
                        "requested_tool_name": request.tool_name,
                    },
                )
            except Exception:
                return self._error_result(
                    request=request,
                    context=context,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    tool_name=tool.name,
                    safe_details={"reason": "workspace_boundary_check_failed"},
                )
        return None

    def _workspace_boundary_result(
        self,
        *,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
        tool_name: str,
        safe_details: JsonObject,
    ) -> ToolResult:
        audit_ref = self._record_rejection_audit(
            request=request,
            context=context,
            error_code=ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION,
        )
        return self._error_result(
            request=request,
            context=context,
            error_code=ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION,
            status=ToolResultStatus.BLOCKED,
            tool_name=tool_name,
            safe_details=safe_details,
            audit_ref=audit_ref,
        )

    def _workspace_targets(
        self,
        payload: JsonObject,
        *,
        tool: ToolProtocol,
    ) -> tuple[str, ...]:
        targets: list[str] = []
        for selector in tool.permission_boundary.workspace_target_paths:
            self._collect_declared_workspace_targets(
                payload,
                selector=selector,
                targets=targets,
            )
        return tuple(targets)

    def _collect_declared_workspace_targets(
        self,
        value: object,
        *,
        selector: str,
        targets: list[str],
    ) -> None:
        segments = selector.split(".")
        self._walk_workspace_target_selector(value, segments=segments, targets=targets)

    def _walk_workspace_target_selector(
        self,
        value: object,
        *,
        segments: list[str],
        targets: list[str],
    ) -> None:
        if not segments:
            if isinstance(value, str):
                targets.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        targets.append(item)
            return
        head, *tail = segments
        if head.endswith("[]"):
            field_name = head[:-2]
            if not isinstance(value, Mapping):
                return
            child = value.get(field_name)
            if not isinstance(child, list):
                return
            for item in child:
                self._walk_workspace_target_selector(item, segments=tail, targets=targets)
            return
        if not isinstance(value, Mapping):
            return
        child = value.get(head)
        if child is None:
            return
        self._walk_workspace_target_selector(child, segments=tail, targets=targets)

    def _record_audit_intent(
        self,
        *,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
        tool: ToolProtocol,
    ) -> ToolAuditRef | ToolResult | None:
        if not self._audit_policy.requires_audit(tool):
            return None
        if context.audit_recorder is None:
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                tool_name=tool.name,
                safe_details={"requested_tool_name": request.tool_name},
            )
        try:
            audit_ref = context.audit_recorder.record_tool_intent(
                request=request,
                tool_name=tool.name,
                trace_context=request.trace_context,
            )
        except Exception:
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                tool_name=tool.name,
                safe_details={"requested_tool_name": request.tool_name},
            )
        if not isinstance(audit_ref, ToolAuditRef):
            return self._error_result(
                request=request,
                context=context,
                error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                tool_name=tool.name,
                safe_details={"requested_tool_name": request.tool_name},
            )
        return audit_ref

    def _record_rejection_audit(
        self,
        *,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
        error_code: ErrorCode,
    ) -> ToolAuditRef | None:
        if context.audit_recorder is None:
            return None
        try:
            audit_ref = context.audit_recorder.record_tool_rejection(
                request=request,
                error_code=error_code,
                trace_context=request.trace_context,
            )
            if isinstance(audit_ref, ToolAuditRef):
                return audit_ref
            return None
        except Exception:
            return None

    def _error_result(
        self,
        *,
        request: ToolExecutionRequest,
        context: ToolExecutionContext,
        error_code: ErrorCode,
        tool_name: str,
        safe_details: JsonObject,
        status: ToolResultStatus = ToolResultStatus.FAILED,
        audit_ref: ToolAuditRef | None = None,
        tool_confirmation_ref: str | None = None,
    ) -> ToolResult:
        try:
            error = ToolError.from_code(
                error_code,
                trace_context=context.trace_context,
                safe_details=safe_details,
                audit_ref=audit_ref,
            )
        except ValidationError:
            error = ToolError.from_code(
                error_code,
                trace_context=context.trace_context,
                safe_details={"detail_redacted": True},
                audit_ref=audit_ref,
            )
        return ToolResult(
            tool_name=tool_name,
            call_id=request.call_id,
            status=status,
            error=error,
            audit_ref=audit_ref,
            trace_context=context.trace_context,
            coordination_key=request.coordination_key,
            tool_confirmation_ref=tool_confirmation_ref,
        )

    def _record_log(
        self,
        *,
        request: ToolExecutionRequest,
        result: ToolResult,
        started: float,
        context: ToolExecutionContext,
    ) -> None:
        if context.run_log_recorder is None:
            return
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        try:
            context.run_log_recorder.record_tool_result(
                request=request,
                result=result,
                duration_ms=duration_ms,
            )
        except Exception:
            return


__all__ = [
    "ToolAuditPolicy",
    "ToolAuditRecorderPort",
    "ToolConfirmationRequestPort",
    "ToolExecutionContext",
    "ToolExecutionGate",
    "ToolExecutionRequest",
    "ToolInputSchemaValidator",
    "ToolRiskInspectionPort",
    "ToolRunLogRecorderPort",
    "ToolTimeoutPolicy",
    "ToolWorkspaceBoundaryError",
    "WorkspaceBoundaryPort",
]
