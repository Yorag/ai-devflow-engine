from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Mapping

import pytest
from pydantic import ValidationError

from backend.app.domain.enums import ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.protocol import (
    ToolAuditRef,
    ToolBindableDescription,
    ToolError,
    ToolInput,
    ToolPermissionBoundary,
    ToolProtocol,
    ToolReconciliationStatus,
    ToolResult,
    ToolResultStatus,
    ToolSideEffectLevel,
)
from backend.app.tools.registry import (
    DuplicateToolRegistrationError,
    InvalidToolDefinitionError,
    ToolRegistry,
    UnknownToolError,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
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
        request_id="request-tool-1",
        trace_id="trace-tool-1",
        correlation_id="correlation-tool-1",
        span_id="span-tool-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


@dataclass(frozen=True)
class FakeTool:
    name: str = "read_file"
    category: str = "workspace"
    description: str = "Read one text file from the current run workspace."
    input_schema: Mapping[str, object] | None = None
    result_schema: Mapping[str, object] | None = None
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
    default_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.input_schema is None:
            object.__setattr__(self, "input_schema", READ_FILE_SCHEMA)
        if self.result_schema is None:
            object.__setattr__(self, "result_schema", READ_FILE_RESULT_SCHEMA)

    def bindable_description(self) -> ToolBindableDescription:
        return ToolBindableDescription(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema or {}),
            result_schema=dict(self.result_schema or {}),
            risk_level=self.default_risk_level,
            risk_categories=list(self.risk_categories),
            schema_version=self.schema_version,
            default_timeout_seconds=self.default_timeout_seconds,
        )

    def execute(self, tool_input: ToolInput) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            call_id=tool_input.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output_payload={"content": "hello"},
            output_preview="hello",
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )


def test_tool_models_preserve_trace_audit_and_side_effect_contract() -> None:
    trace = build_trace()
    audit_ref = ToolAuditRef(
        audit_id="audit-tool-1",
        action="tool.write_file",
        trace_id=trace.trace_id,
        correlation_id=trace.correlation_id,
        metadata_ref="payload-audit-tool-1",
    )
    tool_input = ToolInput(
        tool_name="write_file",
        call_id="tool-call-1",
        input_payload={"path": "src/app.py", "content": "print('ok')"},
        trace_context=trace,
        coordination_key="coordination-tool-call-1",
        side_effect_intent_ref="tool-intent-1",
    )
    result = ToolResult(
        tool_name="write_file",
        call_id=tool_input.call_id,
        status=ToolResultStatus.SUCCEEDED,
        output_payload={"bytes_written": 11},
        output_preview="Wrote src/app.py",
        trace_context=trace,
        coordination_key=tool_input.coordination_key,
        side_effect_refs=["file-edit-trace-1"],
        tool_confirmation_ref="tool-confirmation-1",
        reconciliation_status=ToolReconciliationStatus.RECONCILED,
        audit_ref=audit_ref,
    )
    error = ToolError(
        error_code="tool_workspace_boundary_violation",
        safe_message="Tool target is outside the run workspace.",
        safe_details={"path": "../outside.py"},
        trace_context=trace,
        audit_ref=audit_ref,
    )

    assert tool_input.trace_id == "trace-tool-1"
    assert tool_input.correlation_id == "correlation-tool-1"
    assert tool_input.span_id == "span-tool-1"
    assert result.trace_id == "trace-tool-1"
    assert result.correlation_id == "correlation-tool-1"
    assert result.span_id == "span-tool-1"
    assert result.audit_ref == audit_ref
    assert result.side_effect_refs == ["file-edit-trace-1"]
    assert result.tool_confirmation_ref == "tool-confirmation-1"
    assert result.reconciliation_status is ToolReconciliationStatus.RECONCILED
    assert error.audit_ref == audit_ref

    with pytest.raises(ValidationError, match="free_text_audit_note"):
        ToolAuditRef(
            audit_id="audit-tool-1",
            action="tool.write_file",
            trace_id=trace.trace_id,
            correlation_id=trace.correlation_id,
            free_text_audit_note="not allowed",
        )

    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="write_file",
            call_id="tool-call-1",
            status=ToolResultStatus.SUCCEEDED,
            output_payload={},
            trace_context=trace,
            coordination_key="coordination-tool-call-1",
            side_effect_refs=[""],
        )


def test_tool_result_status_and_error_must_be_consistent() -> None:
    trace = build_trace()
    failure_error = ToolError(
        error_code="tool_timeout",
        safe_message="Tool execution timed out.",
        safe_details={"timeout_seconds": 5},
        trace_context=trace,
    )

    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            call_id="tool-call-1",
            status=ToolResultStatus.FAILED,
            trace_context=trace,
            coordination_key="coordination-tool-call-1",
        )

    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            call_id="tool-call-1",
            status=ToolResultStatus.SUCCEEDED,
            error=failure_error,
            trace_context=trace,
            coordination_key="coordination-tool-call-1",
        )


def test_bindable_description_uses_langchain_compatible_schema() -> None:
    description = FakeTool().bindable_description()

    assert description.name == "read_file"
    assert description.input_schema == READ_FILE_SCHEMA
    assert description.result_schema == READ_FILE_RESULT_SCHEMA
    assert description.risk_level is ToolRiskLevel.READ_ONLY
    assert description.schema_version == "tool-schema-v1"
    assert description.default_timeout_seconds is None
    assert description.to_langchain_tool_schema() == {
        "name": "read_file",
        "description": "Read one text file from the current run workspace.",
        "parameters": READ_FILE_SCHEMA,
    }
    assert (
        "Prefer this tool over bash"
        not in description.to_langchain_tool_schema()["description"]
    )
    assert "prompt" not in description.to_langchain_tool_schema()
    assert "result_schema" not in description.to_langchain_tool_schema()
    assert set(description.to_langchain_tool_schema()) == {
        "name",
        "description",
        "parameters",
    }

    with pytest.raises(ValidationError):
        ToolBindableDescription(
            name="ReadFile",
            description="Case drift is not a valid contract name.",
            input_schema=READ_FILE_SCHEMA,
            result_schema=READ_FILE_RESULT_SCHEMA,
            risk_level=ToolRiskLevel.READ_ONLY,
        )


def test_tool_json_objects_reject_non_serializable_values() -> None:
    trace = build_trace()
    non_serializable = object()

    with pytest.raises(ValidationError):
        ToolBindableDescription(
            name="read_file",
            description="Read one text file from the current run workspace.",
            input_schema={"type": "object", "bad": non_serializable},
            result_schema=READ_FILE_RESULT_SCHEMA,
            risk_level=ToolRiskLevel.READ_ONLY,
        )

    with pytest.raises(ValidationError):
        ToolBindableDescription(
            name="read_file",
            description="Read one text file from the current run workspace.",
            input_schema=READ_FILE_SCHEMA,
            result_schema={"type": "object", "bad": non_serializable},
            risk_level=ToolRiskLevel.READ_ONLY,
        )

    with pytest.raises(ValidationError):
        ToolInput(
            tool_name="read_file",
            call_id="tool-call-1",
            input_payload={"path": non_serializable},
            trace_context=trace,
            coordination_key="coordination-tool-call-1",
        )

    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            call_id="tool-call-1",
            status=ToolResultStatus.SUCCEEDED,
            output_payload={"content": non_serializable},
            trace_context=trace,
            coordination_key="coordination-tool-call-1",
        )

    with pytest.raises(ValidationError):
        ToolError(
            error_code="tool_input_invalid",
            safe_message="Tool input is invalid.",
            safe_details={"path": non_serializable},
            trace_context=trace,
        )


def test_registry_registers_resolves_and_lists_bindable_tools_by_category() -> None:
    registry = ToolRegistry()
    read_file = FakeTool()
    read_delivery_snapshot = FakeTool(
        name="read_delivery_snapshot",
        category="delivery",
        description="Read the frozen delivery snapshot for this run.",
        permission_boundary=ToolPermissionBoundary(
            boundary_type="delivery",
            requires_workspace=False,
            resource_scopes=("delivery_channel_snapshot",),
        ),
    )

    registry.register(read_file)
    registry.register(read_delivery_snapshot)

    assert isinstance(read_file, ToolProtocol)
    assert registry.resolve("read_file") is read_file
    assert registry.resolve("read_file", category="workspace") is read_file
    assert registry.resolve("read_delivery_snapshot", category="delivery") is (
        read_delivery_snapshot
    )
    assert [item.name for item in registry.list_bindable_tools()] == [
        "read_delivery_snapshot",
        "read_file",
    ]
    assert [item.name for item in registry.list_bindable_tools(category="workspace")] == [
        "read_file"
    ]


def test_registry_rejects_duplicate_unknown_and_case_drift() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool())

    with pytest.raises(DuplicateToolRegistrationError) as duplicate:
        registry.register(FakeTool(description="Same name cannot be rebound."))
    assert duplicate.value.error_code == "tool_registration_duplicate"

    with pytest.raises(DuplicateToolRegistrationError):
        registry.register(FakeTool(category="delivery"))

    with pytest.raises(UnknownToolError) as unknown:
        registry.resolve("grep")
    assert unknown.value.error_code == "tool_unknown"
    assert unknown.value.tool_name == "grep"

    with pytest.raises(UnknownToolError):
        registry.resolve("read_file", category="delivery")

    with pytest.raises(InvalidToolDefinitionError):
        registry.register(FakeTool(name="ReadFile"))

    with pytest.raises(InvalidToolDefinitionError):
        registry.register(FakeTool(category="Workspace"))


def test_registry_rejects_workspace_tool_without_declared_target_paths() -> None:
    registry = ToolRegistry()

    with pytest.raises(InvalidToolDefinitionError) as error:
        registry.register(
            FakeTool(
                permission_boundary=ToolPermissionBoundary(
                    boundary_type="workspace",
                    requires_workspace=True,
                    resource_scopes=("current_run_workspace",),
                )
            )
        )

    assert error.value.field_name == "permission_boundary.workspace_target_paths"


def test_registry_invalid_contract_names_carry_structured_metadata() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool())

    with pytest.raises(InvalidToolDefinitionError) as invalid_tool_name:
        registry.register(FakeTool(name="ReadFile"))
    assert invalid_tool_name.value.tool_name == "ReadFile"
    assert invalid_tool_name.value.category is None
    assert invalid_tool_name.value.field_name == "tool.name"

    with pytest.raises(InvalidToolDefinitionError) as invalid_tool_category:
        registry.register(FakeTool(category="Workspace"))
    assert invalid_tool_category.value.tool_name == "read_file"
    assert invalid_tool_category.value.category == "Workspace"
    assert invalid_tool_category.value.field_name == "tool.category"

    with pytest.raises(InvalidToolDefinitionError) as invalid_resolve_name:
        registry.resolve(123)  # type: ignore[arg-type]
    assert invalid_resolve_name.value.tool_name == 123
    assert invalid_resolve_name.value.category is None
    assert invalid_resolve_name.value.field_name == "name"

    category = object()
    with pytest.raises(InvalidToolDefinitionError) as invalid_resolve_category:
        registry.resolve("read_file", category=category)  # type: ignore[arg-type]
    assert invalid_resolve_category.value.tool_name == "read_file"
    assert invalid_resolve_category.value.category is category
    assert invalid_resolve_category.value.field_name == "category"


def test_registry_rejects_bindable_description_mismatches() -> None:
    class MismatchedNameTool(FakeTool):
        def bindable_description(self) -> ToolBindableDescription:
            return ToolBindableDescription(
                name="other_tool",
                description=self.description,
                input_schema=dict(self.input_schema or {}),
                result_schema=dict(self.result_schema or {}),
                risk_level=self.default_risk_level,
                risk_categories=list(self.risk_categories),
            )

    class MismatchedDescriptionTool(FakeTool):
        def bindable_description(self) -> ToolBindableDescription:
            return ToolBindableDescription(
                name=self.name,
                description="Different description.",
                input_schema=dict(self.input_schema or {}),
                result_schema=dict(self.result_schema or {}),
                risk_level=self.default_risk_level,
                risk_categories=list(self.risk_categories),
            )

    class MismatchedInputSchemaTool(FakeTool):
        def bindable_description(self) -> ToolBindableDescription:
            return ToolBindableDescription(
                name=self.name,
                description=self.description,
                input_schema={"type": "object", "properties": {}},
                result_schema=dict(self.result_schema or {}),
                risk_level=self.default_risk_level,
                risk_categories=list(self.risk_categories),
            )

    class MismatchedResultSchemaTool(FakeTool):
        def bindable_description(self) -> ToolBindableDescription:
            return ToolBindableDescription(
                name=self.name,
                description=self.description,
                input_schema=dict(self.input_schema or {}),
                result_schema={"type": "object", "properties": {}},
                risk_level=self.default_risk_level,
                risk_categories=list(self.risk_categories),
            )

    with pytest.raises(InvalidToolDefinitionError) as error:
        ToolRegistry().register(MismatchedNameTool())

    assert error.value.error_code == "tool_definition_invalid"

    with pytest.raises(InvalidToolDefinitionError) as description_error:
        ToolRegistry().register(MismatchedDescriptionTool())
    assert description_error.value.field_name == "description"

    with pytest.raises(InvalidToolDefinitionError) as input_schema_error:
        ToolRegistry().register(MismatchedInputSchemaTool())
    assert input_schema_error.value.field_name == "input_schema"

    with pytest.raises(InvalidToolDefinitionError) as result_schema_error:
        ToolRegistry().register(MismatchedResultSchemaTool())
    assert result_schema_error.value.field_name == "result_schema"


def test_registry_lists_cached_bindable_descriptions_after_registration() -> None:
    @dataclass(frozen=True)
    class DriftingDescriptionTool(FakeTool):
        drifted: bool = False

        def bindable_description(self) -> ToolBindableDescription:
            description = (
                "Drifted bindable description."
                if self.drifted
                else self.description
            )
            return ToolBindableDescription(
                name=self.name,
                description=description,
                input_schema=dict(self.input_schema or {}),
                result_schema=dict(self.result_schema or {}),
                risk_level=self.default_risk_level,
                risk_categories=list(self.risk_categories),
            )

    registry = ToolRegistry()
    tool = DriftingDescriptionTool()

    registry.register(tool)
    object.__setattr__(tool, "drifted", True)

    [description] = registry.list_bindable_tools()
    assert description.description == "Read one text file from the current run workspace."


def test_registry_snapshots_retained_bindable_descriptions_at_registration() -> None:
    @dataclass(frozen=True)
    class RetainedDescriptionTool(FakeTool):
        retained_description: ToolBindableDescription = field(
            default_factory=lambda: ToolBindableDescription(
                name="read_file",
                description="Read one text file from the current run workspace.",
                input_schema=deepcopy(READ_FILE_SCHEMA),
                result_schema=deepcopy(READ_FILE_RESULT_SCHEMA),
                risk_level=ToolRiskLevel.READ_ONLY,
            )
        )

        def bindable_description(self) -> ToolBindableDescription:
            return self.retained_description

    registry = ToolRegistry()
    tool = RetainedDescriptionTool()

    registry.register(tool)
    tool.retained_description.description = "Mutated retained description."
    tool.retained_description.input_schema["properties"]["path"]["type"] = "integer"

    [description] = registry.list_bindable_tools()
    assert description.description == "Read one text file from the current run workspace."
    assert description.input_schema == READ_FILE_SCHEMA


def test_registry_list_bindable_tools_returns_defensive_copies() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool())

    [listed_description] = registry.list_bindable_tools()
    listed_description.description = "Mutated listed description."
    listed_description.input_schema["properties"]["path"]["type"] = "integer"

    [description] = registry.list_bindable_tools()
    assert description.description == "Read one text file from the current run workspace."
    assert description.input_schema == READ_FILE_SCHEMA


def test_registry_rejects_bindable_risk_metadata_mismatches() -> None:
    class MismatchedRiskLevelTool(FakeTool):
        def bindable_description(self) -> ToolBindableDescription:
            return ToolBindableDescription(
                name=self.name,
                description=self.description,
                input_schema=dict(self.input_schema or {}),
                result_schema=dict(self.result_schema or {}),
                risk_level=ToolRiskLevel.HIGH_RISK,
                risk_categories=list(self.risk_categories),
            )

    class MismatchedRiskCategoriesTool(FakeTool):
        def bindable_description(self) -> ToolBindableDescription:
            return ToolBindableDescription(
                name=self.name,
                description=self.description,
                input_schema=dict(self.input_schema or {}),
                result_schema=dict(self.result_schema or {}),
                risk_level=self.default_risk_level,
                risk_categories=[],
            )

    with pytest.raises(InvalidToolDefinitionError) as risk_level_error:
        ToolRegistry().register(MismatchedRiskLevelTool())
    assert risk_level_error.value.error_code == "tool_definition_invalid"

    with pytest.raises(InvalidToolDefinitionError) as risk_categories_error:
        ToolRegistry().register(
            MismatchedRiskCategoriesTool(
                risk_categories=(ToolRiskCategory.DEPENDENCY_CHANGE,)
            )
        )
    assert risk_categories_error.value.error_code == "tool_definition_invalid"
