from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Mapping

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import StageType, ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import (
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolWorkspaceBoundaryError,
)
from backend.app.tools.protocol import (
    ToolAuditRef,
    ToolBindableDescription,
    ToolError,
    ToolInput,
    ToolPermissionBoundary,
    ToolResult,
    ToolResultStatus,
    ToolSideEffectLevel,
)
from backend.app.tools.registry import ToolRegistry


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string", "minLength": 1}},
    "required": ["path"],
    "additionalProperties": False,
}
READ_FILE_RESULT_SCHEMA = {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
    "additionalProperties": False,
}


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-tool-exec-1",
        trace_id="trace-tool-exec-1",
        correlation_id="correlation-tool-exec-1",
        span_id="span-tool-exec-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


@dataclass
class ExecutableFakeTool:
    name: str = "read_file"
    category: str = "workspace"
    description: str = "Read one text file from the current run workspace."
    input_schema: Mapping[str, object] = field(default_factory=lambda: READ_FILE_SCHEMA)
    result_schema: Mapping[str, object] = field(
        default_factory=lambda: READ_FILE_RESULT_SCHEMA
    )
    default_risk_level: ToolRiskLevel = ToolRiskLevel.READ_ONLY
    risk_categories: tuple[ToolRiskCategory, ...] = ()
    permission_boundary: ToolPermissionBoundary = field(
        default_factory=lambda: ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("path",),
        )
    )
    side_effect_level: ToolSideEffectLevel = ToolSideEffectLevel.NONE
    audit_required: bool = False
    schema_version: str = "tool-schema-v1"
    default_timeout_seconds: float | None = 5.0
    calls: list[ToolInput] = field(default_factory=list)
    timeout_error: bool = False
    return_error: bool = False
    returned_audit_ref: ToolAuditRef | None = None
    unexpected_error_message: str | None = None
    return_non_tool_result: bool = False

    def bindable_description(self) -> ToolBindableDescription:
        return ToolBindableDescription(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
            result_schema=dict(self.result_schema),
            risk_level=self.default_risk_level,
            risk_categories=list(self.risk_categories),
            schema_version=self.schema_version,
            default_timeout_seconds=self.default_timeout_seconds,
        )

    def execute(self, tool_input: ToolInput) -> ToolResult:
        self.calls.append(tool_input)
        if self.timeout_error:
            raise TimeoutError("tool execution timed out")
        if self.unexpected_error_message is not None:
            raise RuntimeError(self.unexpected_error_message)
        if self.return_non_tool_result:
            return {"content": "hello"}  # type: ignore[return-value]
        if self.return_error:
            concrete_audit_ref = self.returned_audit_ref
            return ToolResult(
                tool_name=self.name,
                call_id=tool_input.call_id,
                status=ToolResultStatus.FAILED,
                error=ToolError.from_code(
                    ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
                    trace_context=tool_input.trace_context,
                    safe_details={"reason": "concrete_tool_failed"},
                    audit_ref=concrete_audit_ref,
                ),
                audit_ref=concrete_audit_ref,
                trace_context=tool_input.trace_context,
                coordination_key=tool_input.coordination_key,
            )
        return ToolResult(
            tool_name=self.name,
            call_id=tool_input.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output_payload={"content": "hello"},
            output_preview="hello",
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )


class RecordingLog:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record_tool_result(
        self,
        *,
        request: ToolExecutionRequest,
        result: ToolResult,
        duration_ms: int,
    ) -> None:
        self.records.append(
            {
                "tool_name": request.tool_name,
                "status": result.status.value,
                "error_code": result.error.error_code.value if result.error else None,
                "duration_ms": duration_ms,
            }
        )


class RecordingAudit:
    def __init__(
        self,
        *,
        fail_intent: bool = False,
        missing_intent_ref: bool = False,
    ) -> None:
        self.intents: list[str] = []
        self.rejections: list[str] = []
        self.fail_intent = fail_intent
        self.missing_intent_ref = missing_intent_ref

    def record_tool_intent(
        self,
        *,
        request: ToolExecutionRequest,
        tool_name: str,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.intents.append(tool_name)
        if self.fail_intent:
            raise RuntimeError("audit recorder unavailable")
        if self.missing_intent_ref:
            return None  # type: ignore[return-value]
        return ToolAuditRef(
            audit_id=f"audit-{request.call_id}",
            action="tool.intent",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-{request.call_id}",
        )

    def record_tool_rejection(
        self,
        *,
        request: ToolExecutionRequest,
        error_code: ErrorCode,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.rejections.append(error_code.value)
        return ToolAuditRef(
            audit_id=f"audit-reject-{request.call_id}",
            action="tool.rejected",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-reject-{request.call_id}",
        )


class WorkspaceBoundary:
    def __init__(self, blocked_target: str | None = None) -> None:
        self.checked_targets: list[str] = []
        self.blocked_target = blocked_target

    def assert_inside_workspace(
        self,
        target: str,
        *,
        trace_context: TraceContext,
    ) -> None:
        self.checked_targets.append(target)
        if target == self.blocked_target:
            raise ToolWorkspaceBoundaryError(
                "Tool target is outside the run workspace.",
                target=target,
            )


class ExplodingWorkspaceBoundary:
    def assert_inside_workspace(
        self,
        target: str,
        *,
        trace_context: TraceContext,
    ) -> None:
        raise RuntimeError("workspace boundary port unavailable")


class RecordingRiskHook:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def inspect_tool_intent(
        self,
        *,
        request: ToolExecutionRequest,
        tool_name: str,
        trace_context: TraceContext,
    ) -> None:
        self.calls.append(f"{tool_name}:{request.call_id}:{trace_context.span_id}")


class ExplodingRiskHook:
    def inspect_tool_intent(
        self,
        *,
        request: ToolExecutionRequest,
        tool_name: str,
        trace_context: TraceContext,
    ) -> None:
        raise RuntimeError("risk inspection failed")


class ExplodingLog:
    def record_tool_result(
        self,
        *,
        request: ToolExecutionRequest,
        result: ToolResult,
        duration_ms: int,
    ) -> None:
        raise RuntimeError("log recorder unavailable")


def context(
    *,
    allowed_tools: list[str],
    workspace_boundary: WorkspaceBoundary | None = None,
    audit_recorder: RecordingAudit | None = None,
    risk_policy: RecordingRiskHook | None = None,
    log_recorder: RecordingLog | None = None,
    runtime_tool_timeout_seconds: float | None = 5,
    platform_tool_timeout_hard_limit_seconds: float | None = 30,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        stage_type=StageType.CODE_GENERATION,
        stage_contracts={
            StageType.CODE_GENERATION.value: {"allowed_tools": allowed_tools}
        },
        trace_context=build_trace(),
        workspace_boundary=workspace_boundary,
        audit_recorder=audit_recorder,
        risk_policy=risk_policy,
        run_log_recorder=log_recorder or RecordingLog(),
        runtime_tool_timeout_seconds=runtime_tool_timeout_seconds,
        platform_tool_timeout_hard_limit_seconds=platform_tool_timeout_hard_limit_seconds,
    )


def request(
    tool_name: str = "read_file",
    payload: dict[str, object] | None = None,
) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_name=tool_name,
        call_id=f"call-{tool_name.lower().replace('_', '-')}",
        input_payload=payload if payload is not None else {"path": "src/app.py"},
        trace_context=build_trace(),
        coordination_key=f"coordination-{tool_name.lower().replace('_', '-')}",
    )


def test_execute_rejects_unknown_and_case_drift_with_structured_errors() -> None:
    registry = ToolRegistry([ExecutableFakeTool()])
    log = RecordingLog()

    unknown = registry.execute(
        request("grep"),
        context(allowed_tools=["grep"], log_recorder=log),
    )
    case_drift = registry.execute(
        request("ReadFile"),
        context(allowed_tools=["ReadFile"], log_recorder=log),
    )

    assert unknown.status is ToolResultStatus.FAILED
    assert unknown.error is not None
    assert unknown.error.error_code is ErrorCode.TOOL_UNKNOWN
    assert unknown.error.safe_details["requested_tool_name"] == "grep"
    assert case_drift.status is ToolResultStatus.FAILED
    assert case_drift.error is not None
    assert case_drift.error.error_code is ErrorCode.TOOL_UNKNOWN
    assert case_drift.error.safe_details["requested_tool_name"] == "ReadFile"
    assert [record["error_code"] for record in log.records] == [
        "tool_unknown",
        "tool_unknown",
    ]


def test_available_tools_and_execute_respect_stage_allowed_tools() -> None:
    registry = ToolRegistry(
        [
            ExecutableFakeTool(name="read_file"),
            ExecutableFakeTool(name="grep", description="Search files."),
        ]
    )
    current_context = context(allowed_tools=["read_file"])

    assert [tool.name for tool in registry.list_available_tools(current_context)] == [
        "read_file"
    ]

    result = registry.execute(request("grep"), current_context)

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_NOT_ALLOWED
    assert registry.resolve("grep").calls == []


def test_execute_rejects_invalid_input_schema_before_tool_runs() -> None:
    tool = ExecutableFakeTool()
    registry = ToolRegistry([tool])

    missing = registry.execute(request(payload={}), context(allowed_tools=["read_file"]))
    extra = registry.execute(
        request(payload={"path": "src/app.py", "mode": "raw"}),
        context(allowed_tools=["read_file"]),
    )
    wrong_type = registry.execute(
        request(payload={"path": 42}),
        context(allowed_tools=["read_file"]),
    )
    too_short = registry.execute(
        request(payload={"path": ""}),
        context(allowed_tools=["read_file"]),
    )

    assert [
        missing.error.error_code,
        extra.error.error_code,
        wrong_type.error.error_code,
        too_short.error.error_code,
    ] == [
        ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
        ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
        ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
        ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
    ]
    assert tool.calls == []


def test_execute_validates_schema_enum_before_tool_runs() -> None:
    tool = ExecutableFakeTool(
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["text", "binary"]},
            },
            "required": ["path", "mode"],
            "additionalProperties": False,
        }
    )
    registry = ToolRegistry([tool])

    result = registry.execute(
        request(payload={"path": "src/app.py", "mode": "raw"}),
        context(allowed_tools=["read_file"]),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_INPUT_SCHEMA_INVALID
    assert tool.calls == []


def test_execute_validates_array_items_before_tool_runs() -> None:
    tool = ExecutableFakeTool(
        input_schema={
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "mode": {"type": "string", "enum": ["insert", "replace"]},
                        },
                        "required": ["path", "mode"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["edits"],
            "additionalProperties": False,
        }
    )
    registry = ToolRegistry([tool])

    result = registry.execute(
        request(payload={"edits": [{"path": "src/app.py", "mode": "raw"}]}),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=WorkspaceBoundary(),
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_INPUT_SCHEMA_INVALID
    assert tool.calls == []


def test_execute_rejects_non_json_payload_before_tool_runs() -> None:
    tool = ExecutableFakeTool(
        input_schema={
            "type": "object",
            "properties": {"threshold": {"type": "number"}},
            "required": ["threshold"],
            "additionalProperties": False,
        },
        permission_boundary=ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=False,
            resource_scopes=(),
        ),
    )
    registry = ToolRegistry([tool])

    result = registry.execute(
        request(payload={"threshold": float("inf")}),
        context(allowed_tools=["read_file"]),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_INPUT_SCHEMA_INVALID
    assert tool.calls == []


def test_execute_rejects_malformed_property_schema_before_tool_runs() -> None:
    tool = ExecutableFakeTool(
        input_schema={
            "type": "object",
            "properties": {"path": "not-a-schema"},
            "required": ["path"],
            "additionalProperties": False,
        }
    )
    registry = ToolRegistry([tool])

    result = registry.execute(
        request(payload={"path": "src/app.py"}),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=WorkspaceBoundary(),
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_INPUT_SCHEMA_INVALID
    assert tool.calls == []


def test_execute_checks_workspace_boundary_before_tool_runs() -> None:
    tool = ExecutableFakeTool()
    registry = ToolRegistry([tool])
    workspace = WorkspaceBoundary(blocked_target="../outside.py")
    audit = RecordingAudit()

    result = registry.execute(
        request(payload={"path": "../outside.py"}),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=workspace,
            audit_recorder=audit,
        ),
    )

    assert result.status is ToolResultStatus.BLOCKED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert result.error.safe_details["target"] == "../outside.py"
    assert workspace.checked_targets == ["../outside.py"]
    assert audit.rejections == ["tool_workspace_boundary_violation"]
    assert tool.calls == []


def test_execute_checks_nested_workspace_boundary_before_tool_runs() -> None:
    tool = ExecutableFakeTool(
        input_schema={
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["edits"],
            "additionalProperties": False,
        },
        permission_boundary=ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("edits[].path",),
        ),
    )
    registry = ToolRegistry([tool])
    workspace = WorkspaceBoundary(blocked_target="../outside.py")
    audit = RecordingAudit()

    result = registry.execute(
        request(
            payload={
                "edits": [
                    {"path": "../outside.py", "content": "print('blocked')"},
                ]
            }
        ),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=workspace,
            audit_recorder=audit,
        ),
    )

    assert result.status is ToolResultStatus.BLOCKED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert result.error.safe_details["target"] == "../outside.py"
    assert workspace.checked_targets == ["../outside.py"]
    assert audit.rejections == ["tool_workspace_boundary_violation"]
    assert tool.calls == []


def test_execute_checks_declared_source_path_workspace_boundary_before_tool_runs() -> None:
    tool = ExecutableFakeTool(
        input_schema={
            "type": "object",
            "properties": {"source_path": {"type": "string", "minLength": 1}},
            "required": ["source_path"],
            "additionalProperties": False,
        },
        permission_boundary=ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("source_path",),
        ),
    )
    registry = ToolRegistry([tool])
    workspace = WorkspaceBoundary(blocked_target="../outside.py")

    result = registry.execute(
        request(payload={"source_path": "../outside.py"}),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=workspace,
        ),
    )

    assert result.status is ToolResultStatus.BLOCKED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert result.error.safe_details["target"] == "../outside.py"
    assert workspace.checked_targets == ["../outside.py"]
    assert tool.calls == []


def test_execute_checks_declared_string_array_workspace_targets_before_tool_runs() -> None:
    tool = ExecutableFakeTool(
        input_schema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                }
            },
            "required": ["paths"],
            "additionalProperties": False,
        },
        permission_boundary=ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("paths[]",),
        ),
    )
    registry = ToolRegistry([tool])
    workspace = WorkspaceBoundary(blocked_target="../outside.py")

    result = registry.execute(
        request(payload={"paths": ["src/app.py", "../outside.py"]}),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=workspace,
        ),
    )

    assert result.status is ToolResultStatus.BLOCKED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert result.error.safe_details["target"] == "../outside.py"
    assert workspace.checked_targets == ["src/app.py", "../outside.py"]
    assert tool.calls == []


def test_execute_blocks_audit_required_side_effect_without_audit_recorder() -> None:
    tool = ExecutableFakeTool(
        name="write_file",
        description="Write one file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"bytes_written": {"type": "integer"}},
            "required": ["bytes_written"],
            "additionalProperties": False,
        },
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
        audit_required=True,
    )
    registry = ToolRegistry([tool])

    result = registry.execute(
        request("write_file", {"path": "src/app.py", "content": "print('ok')"}),
        context(
            allowed_tools=["write_file"],
            workspace_boundary=WorkspaceBoundary(),
            audit_recorder=None,
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert tool.calls == []


def test_execute_blocks_side_effect_when_audit_intent_recording_fails() -> None:
    tool = ExecutableFakeTool(
        name="write_file",
        description="Write one file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
        audit_required=True,
    )
    registry = ToolRegistry([tool])
    audit = RecordingAudit(fail_intent=True)

    result = registry.execute(
        request("write_file", {"path": "src/app.py", "content": "print('ok')"}),
        context(
            allowed_tools=["write_file"],
            workspace_boundary=WorkspaceBoundary(),
            audit_recorder=audit,
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert audit.intents == ["write_file"]
    assert tool.calls == []


def test_execute_blocks_side_effect_when_audit_intent_ref_is_missing() -> None:
    tool = ExecutableFakeTool(
        name="write_file",
        description="Write one file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
        audit_required=True,
    )
    registry = ToolRegistry([tool])

    result = registry.execute(
        request("write_file", {"path": "src/app.py", "content": "print('ok')"}),
        context(
            allowed_tools=["write_file"],
            workspace_boundary=WorkspaceBoundary(),
            audit_recorder=RecordingAudit(missing_intent_ref=True),
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert tool.calls == []


def test_execute_records_audit_intent_runs_risk_hook_and_returns_tool_result() -> None:
    tool = ExecutableFakeTool(
        name="write_file",
        description="Write one file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
        audit_required=True,
    )
    registry = ToolRegistry([tool])
    audit = RecordingAudit()
    risk_hook = RecordingRiskHook()
    log = RecordingLog()

    result = registry.execute(
        request("write_file", {"path": "src/app.py", "content": "print('ok')"}),
        context(
            allowed_tools=["write_file"],
            workspace_boundary=WorkspaceBoundary(),
            audit_recorder=audit,
            risk_policy=risk_hook,
            log_recorder=log,
        ),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.audit_ref is not None
    assert result.audit_ref.action == "tool.intent"
    assert tool.calls[0].side_effect_intent_ref == result.audit_ref.audit_id
    assert audit.intents == ["write_file"]
    assert risk_hook.calls == ["write_file:call-write-file:span-tool-exec-1"]
    assert log.records[-1]["status"] == "succeeded"


def test_execute_normalizes_mismatched_concrete_audit_ref_to_gate_intent() -> None:
    concrete_audit_ref = ToolAuditRef(
        audit_id="audit-concrete-drift",
        action="tool.intent",
        trace_id="trace-concrete-drift",
        correlation_id="correlation-concrete-drift",
        metadata_ref="payload-concrete-drift",
    )
    tool = ExecutableFakeTool(
        name="write_file",
        description="Write one file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
        audit_required=True,
        return_error=True,
        returned_audit_ref=concrete_audit_ref,
    )
    registry = ToolRegistry([tool])
    audit = RecordingAudit()

    result = registry.execute(
        request("write_file", {"path": "src/app.py", "content": "print('ok')"}),
        context(
            allowed_tools=["write_file"],
            workspace_boundary=WorkspaceBoundary(),
            audit_recorder=audit,
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.audit_ref is not None
    assert result.audit_ref.audit_id == "audit-call-write-file"
    assert result.audit_ref != concrete_audit_ref
    assert result.error is not None
    assert result.error.audit_ref == result.audit_ref


def test_execute_converts_tool_timeout_to_structured_error() -> None:
    tool = ExecutableFakeTool(timeout_error=True)
    registry = ToolRegistry([tool])

    result = registry.execute(
        request(),
        context(allowed_tools=["read_file"], workspace_boundary=WorkspaceBoundary()),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_TIMEOUT
    assert tool.calls


def test_execute_converts_unexpected_tool_exception_to_structured_internal_error_and_logs() -> None:
    tool = ExecutableFakeTool(unexpected_error_message="boom")
    registry = ToolRegistry([tool])
    log = RecordingLog()

    result = registry.execute(
        request(),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=WorkspaceBoundary(),
            log_recorder=log,
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.INTERNAL_ERROR
    assert result.error.safe_details["reason"] == "tool_execution_failed"
    assert tool.calls
    assert log.records[-1]["error_code"] == "internal_error"


def test_execute_rejects_non_tool_result_with_structured_internal_error() -> None:
    tool = ExecutableFakeTool(return_non_tool_result=True)
    registry = ToolRegistry([tool])
    log = RecordingLog()

    result = registry.execute(
        request(),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=WorkspaceBoundary(),
            log_recorder=log,
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.INTERNAL_ERROR
    assert result.error.safe_details["reason"] == "tool_result_invalid"
    assert tool.calls
    assert log.records[-1]["error_code"] == "internal_error"


def test_execute_converts_risk_hook_failure_to_structured_internal_error() -> None:
    tool = ExecutableFakeTool()
    registry = ToolRegistry([tool])
    log = RecordingLog()

    result = registry.execute(
        request(),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=WorkspaceBoundary(),
            risk_policy=ExplodingRiskHook(),
            log_recorder=log,
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.INTERNAL_ERROR
    assert result.error.safe_details["reason"] == "risk_policy_failed"
    assert tool.calls == []
    assert log.records[-1]["error_code"] == "internal_error"


def test_execute_converts_unexpected_workspace_boundary_failure_to_structured_internal_error() -> None:
    tool = ExecutableFakeTool()
    registry = ToolRegistry([tool])
    log = RecordingLog()

    result = registry.execute(
        request(),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=ExplodingWorkspaceBoundary(),
            log_recorder=log,
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.INTERNAL_ERROR
    assert result.error.safe_details["reason"] == "workspace_boundary_check_failed"
    assert tool.calls == []
    assert log.records[-1]["error_code"] == "internal_error"


def test_execute_ignores_run_log_recorder_failure_and_preserves_tool_result() -> None:
    tool = ExecutableFakeTool()
    registry = ToolRegistry([tool])

    result = registry.execute(
        request(),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=WorkspaceBoundary(),
            log_recorder=ExplodingLog(),
        ),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.error is None
    assert tool.calls


def test_execute_falls_back_when_safe_details_contain_sensitive_content() -> None:
    registry = ToolRegistry([ExecutableFakeTool()])

    result = registry.execute(
        request("Bearer secret-token"),
        context(allowed_tools=["read_file"]),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_UNKNOWN
    assert result.error.safe_details == {"detail_redacted": True}


def test_execute_passes_resolved_timeout_capped_by_platform_hard_limit() -> None:
    tool = ExecutableFakeTool(default_timeout_seconds=25.0)
    registry = ToolRegistry([tool])

    result = registry.execute(
        request(payload={"path": "src/app.py"}),
        context(
            allowed_tools=["read_file"],
            workspace_boundary=WorkspaceBoundary(),
            runtime_tool_timeout_seconds=None,
            platform_tool_timeout_hard_limit_seconds=10,
        ),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert tool.calls[0].timeout_seconds == 10
