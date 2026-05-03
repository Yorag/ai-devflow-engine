from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Mapping

from backend.app.domain.enums import ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import (
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


FIXTURE_NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
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


def tool_trace_fixture() -> TraceContext:
    return TraceContext(
        request_id="request-fixture-tool-1",
        trace_id="trace-fixture-tool-1",
        correlation_id="correlation-fixture-tool-1",
        span_id="span-fixture-tool-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=FIXTURE_NOW,
    )


class WorkspaceBoundary:
    def __init__(self, blocked_target: str | None = None) -> None:
        self.checked_targets: list[str] = []
        self.blocked_target = (
            _normalize_workspace_target(blocked_target)
            if blocked_target is not None
            else None
        )

    def assert_inside_workspace(
        self,
        target: str,
        *,
        trace_context: TraceContext,
    ) -> None:
        del trace_context
        normalized_target = _normalize_workspace_target(target)
        self.checked_targets.append(normalized_target)
        if (
            normalized_target == self.blocked_target
            or normalized_target.startswith("../")
            or normalized_target == ".."
            or normalized_target.startswith("/")
            or _looks_like_windows_absolute(normalized_target)
        ):
            raise ToolWorkspaceBoundaryError(
                "Tool target is outside the run workspace.",
                target=target,
            )


def _normalize_workspace_target(target: str) -> str:
    return posixpath.normpath(target.replace("\\", "/"))


def _looks_like_windows_absolute(target: str) -> bool:
    return len(target) >= 3 and target[1] == ":" and target[2] == "/"


@dataclass
class FakeTool:
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
    workspace_boundary: WorkspaceBoundary = field(default_factory=WorkspaceBoundary)
    calls: list[ToolInput] = field(default_factory=list)
    success_payload: Mapping[str, object] = field(
        default_factory=lambda: {"content": "hello"}
    )
    success_preview: str = "hello"
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
                    "internal_error",
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
            output_payload=dict(self.success_payload),
            output_preview=self.success_preview,
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )

    def build_request(
        self,
        *,
        path: str = "src/app.py",
        call_id: str = "fixture-tool-call",
        trace_context: TraceContext | None = None,
    ) -> ToolExecutionRequest:
        return ToolExecutionRequest(
            tool_name=self.name,
            call_id=call_id,
            input_payload={"path": path},
            trace_context=trace_context or tool_trace_fixture(),
            coordination_key=f"fixture-{call_id}",
        )


def workspace_boundary_fixture(blocked_target: str | None = None) -> WorkspaceBoundary:
    return WorkspaceBoundary(blocked_target=blocked_target)


def fake_tool_fixture(**overrides: object) -> FakeTool:
    return FakeTool(**overrides)
