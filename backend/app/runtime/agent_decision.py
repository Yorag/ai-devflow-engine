from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Literal, NoReturn, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic import model_validator

from backend.app.context.schemas import ContextEnvelope
from backend.app.domain.enums import ToolRiskCategory, ToolRiskLevel
from backend.app.providers.langchain_adapter import (
    ModelCallResult,
    ModelCallToolRequest,
)
from backend.app.tools.execution_gate import ToolInputSchemaValidator
from backend.app.tools.protocol import ToolBindableDescription


JsonObject = dict[str, Any]


_ARTIFACT_REQUIRED_FIELDS: Mapping[str, tuple[str, ...]] = {
    "RequirementAnalysisArtifact": (
        "structured_requirement",
        "acceptance_criteria",
        "clarification_summary",
        "assumptions",
        "non_goals",
        "open_questions",
        "source_message_refs",
        "clarification_record_refs",
        "attachment_refs",
        "context_refs",
        "analysis_notes",
    ),
    "SolutionDesignArtifact": (
        "technical_plan",
        "implementation_plan",
        "impacted_files",
        "api_design",
        "data_flow_design",
        "risks",
        "test_strategy",
        "validation_report",
        "requirement_refs",
        "evidence_refs",
    ),
    "CodeGenerationArtifact": (
        "changeset_ref",
        "changed_files",
        "diff_refs",
        "file_edit_trace_refs",
        "implementation_notes",
        "requirement_refs",
        "solution_refs",
    ),
    "TestGenerationExecutionArtifact": (
        "test_changes_ref",
        "test_execution_result",
        "test_gap_report",
        "command_trace_refs",
        "failed_test_refs",
        "acceptance_criteria_refs",
        "changeset_refs",
    ),
    "CodeReviewArtifact": (
        "review_report",
        "issue_list",
        "risk_assessment",
        "regression_decision",
        "fix_requirements",
        "evidence_refs",
        "changeset_refs",
        "test_result_refs",
    ),
}


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _enum_value(value: object) -> str:
    raw_value = getattr(value, "value", value)
    return str(raw_value)


def _validate_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if isfinite(value):
            return
        raise ValueError(f"{path} must be a finite JSON number")
    if isinstance(value, list | tuple):
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


def _validate_non_empty_string_items(value: tuple[str, ...]) -> tuple[str, ...]:
    for item in value:
        if not item.strip():
            raise ValueError("items must be non-empty strings")
    return value


class AgentDecisionType(StrEnum):
    REQUEST_TOOL_CALL = "request_tool_call"
    REQUEST_TOOL_CONFIRMATION = "request_tool_confirmation"
    SUBMIT_STAGE_ARTIFACT = "submit_stage_artifact"
    REQUEST_CLARIFICATION = "request_clarification"
    REPAIR_STRUCTURED_OUTPUT = "repair_structured_output"
    RETRY_WITH_REVISED_PLAN = "retry_with_revised_plan"
    FAIL_STAGE = "fail_stage"


def agent_decision_response_schema() -> JsonObject:
    string_array_schema: JsonObject = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "minItems": 1,
    }
    json_object_schema: JsonObject = {
        "type": "object",
        "additionalProperties": True,
    }

    def decision_schema(
        decision_type: AgentDecisionType,
        *,
        properties: JsonObject,
        required: list[str],
    ) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "decision_type": {"const": decision_type.value},
                **properties,
            },
            "required": ["decision_type", *required],
            "additionalProperties": False,
        }

    return {
        "title": "AgentDecision",
        "type": "object",
        "properties": {
            "decision_type": {
                "type": "string",
                "enum": [
                    AgentDecisionType.REQUEST_TOOL_CONFIRMATION.value,
                    AgentDecisionType.SUBMIT_STAGE_ARTIFACT.value,
                    AgentDecisionType.REQUEST_CLARIFICATION.value,
                    AgentDecisionType.REPAIR_STRUCTURED_OUTPUT.value,
                    AgentDecisionType.RETRY_WITH_REVISED_PLAN.value,
                    AgentDecisionType.FAIL_STAGE.value,
                ],
            },
            "tool_name": {"type": "string", "minLength": 1},
            "command_summary": {"type": "string", "minLength": 1},
            "target_resource": {"type": "string", "minLength": 1},
            "risk_level": {
                "type": "string",
                "enum": [item.value for item in ToolRiskLevel],
            },
            "risk_categories": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [item.value for item in ToolRiskCategory],
                },
                "minItems": 1,
            },
            "expected_side_effects": string_array_schema,
            "alternative_path_summary": {"type": "string", "minLength": 1},
            "input_payload": json_object_schema,
            "artifact_type": {"type": "string", "minLength": 1},
            "artifact_payload": json_object_schema,
            "evidence_refs": string_array_schema,
            "risk_summary": json_object_schema,
            "failure_summary": json_object_schema,
            "question": {"type": "string", "minLength": 1},
            "missing_facts": string_array_schema,
            "impact_scope": {"type": "string", "minLength": 1},
            "related_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "fields_to_update": string_array_schema,
            "parse_error": {"type": "string", "minLength": 1},
            "repair_instruction": {"type": "string", "minLength": 1},
            "invalid_output_ref": {"type": "string", "minLength": 1},
            "reason": {"type": "string", "minLength": 1},
            "revised_plan_steps": string_array_schema,
            "failure_reason": {"type": "string", "minLength": 1},
            "incomplete_items": string_array_schema,
            "user_visible_summary": {"type": "string", "minLength": 1},
        },
        "required": ["decision_type"],
        "additionalProperties": False,
        "oneOf": [
            decision_schema(
                AgentDecisionType.REQUEST_TOOL_CONFIRMATION,
                properties={
                    "tool_name": {"type": "string", "minLength": 1},
                    "command_summary": {"type": "string", "minLength": 1},
                    "target_resource": {"type": "string", "minLength": 1},
                    "risk_level": {
                        "type": "string",
                        "enum": [item.value for item in ToolRiskLevel],
                    },
                    "risk_categories": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [item.value for item in ToolRiskCategory],
                        },
                        "minItems": 1,
                    },
                    "expected_side_effects": string_array_schema,
                    "alternative_path_summary": {"type": "string", "minLength": 1},
                    "input_payload": json_object_schema,
                },
                required=[
                    "tool_name",
                    "command_summary",
                    "target_resource",
                    "risk_level",
                    "risk_categories",
                    "expected_side_effects",
                    "alternative_path_summary",
                ],
            ),
            decision_schema(
                AgentDecisionType.SUBMIT_STAGE_ARTIFACT,
                properties={
                    "artifact_type": {"type": "string", "minLength": 1},
                    "artifact_payload": json_object_schema,
                    "evidence_refs": string_array_schema,
                    "risk_summary": json_object_schema,
                    "failure_summary": json_object_schema,
                },
                required=[
                    "artifact_type",
                    "artifact_payload",
                    "evidence_refs",
                ],
            ),
            decision_schema(
                AgentDecisionType.REQUEST_CLARIFICATION,
                properties={
                    "question": {"type": "string", "minLength": 1},
                    "missing_facts": string_array_schema,
                    "impact_scope": {"type": "string", "minLength": 1},
                    "related_refs": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "fields_to_update": string_array_schema,
                },
                required=[
                    "question",
                    "missing_facts",
                    "impact_scope",
                    "fields_to_update",
                ],
            ),
            decision_schema(
                AgentDecisionType.REPAIR_STRUCTURED_OUTPUT,
                properties={
                    "parse_error": {"type": "string", "minLength": 1},
                    "repair_instruction": {"type": "string", "minLength": 1},
                    "invalid_output_ref": {"type": "string", "minLength": 1},
                },
                required=[
                    "parse_error",
                    "repair_instruction",
                    "invalid_output_ref",
                ],
            ),
            decision_schema(
                AgentDecisionType.RETRY_WITH_REVISED_PLAN,
                properties={
                    "reason": {"type": "string", "minLength": 1},
                    "revised_plan_steps": string_array_schema,
                    "evidence_refs": string_array_schema,
                },
                required=[
                    "reason",
                    "revised_plan_steps",
                    "evidence_refs",
                ],
            ),
            decision_schema(
                AgentDecisionType.FAIL_STAGE,
                properties={
                    "failure_reason": {"type": "string", "minLength": 1},
                    "evidence_refs": string_array_schema,
                    "incomplete_items": string_array_schema,
                    "user_visible_summary": {"type": "string", "minLength": 1},
                },
                required=[
                    "failure_reason",
                    "evidence_refs",
                    "incomplete_items",
                    "user_visible_summary",
                ],
            ),
        ],
    }


class AgentDecisionErrorCode(StrEnum):
    PROVIDER_CALL_FAILED = "provider_call_failed"
    INVALID_TOOL_CALL = "invalid_tool_call"
    TOOL_NOT_AVAILABLE = "tool_not_available"
    TOOL_SCHEMA_MISMATCH = "tool_schema_mismatch"
    TOOL_INPUT_SCHEMA_INVALID = "tool_input_schema_invalid"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    AMBIGUOUS_MODEL_DECISION = "ambiguous_model_decision"
    STAGE_CONTRACT_VIOLATION = "stage_contract_violation"
    CLARIFICATION_NOT_ALLOWED = "clarification_not_allowed"


class AgentDecisionTrace(_StrictBaseModel):
    trace_ref: str = Field(min_length=1)
    status: Literal["accepted", "rejected"]
    decision_type: AgentDecisionType | None = None
    model_call_ref: str = Field(min_length=1)
    provider_snapshot_id: str = Field(min_length=1)
    model_binding_snapshot_id: str = Field(min_length=1)
    model_call_type: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    parent_span_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    stage_run_id: str | None = Field(default=None, min_length=1)
    reason: str | None = Field(default=None, min_length=1)


class AgentDecisionModelCallError(_StrictBaseModel):
    error_code: AgentDecisionErrorCode
    safe_message: str = Field(min_length=1)
    safe_details: JsonObject = Field(default_factory=dict)
    decision_trace: AgentDecisionTrace

    _validate_safe_details = field_validator("safe_details")(_validate_json_object)


class AgentDecisionParserError(RuntimeError):
    def __init__(self, error: AgentDecisionModelCallError) -> None:
        super().__init__(error.safe_message)
        self.error = error


class ToolCallDecision(_StrictBaseModel):
    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    input_payload: JsonObject = Field(default_factory=dict)
    schema_version: str | None = Field(default=None, min_length=1)
    model_call_ref: str = Field(min_length=1)

    _validate_input_payload = field_validator("input_payload")(_validate_json_object)


class ToolConfirmationDecision(_StrictBaseModel):
    tool_name: str = Field(min_length=1)
    command_summary: str = Field(min_length=1)
    target_resource: str = Field(min_length=1)
    risk_level: ToolRiskLevel
    risk_categories: tuple[ToolRiskCategory, ...] = Field(min_length=1)
    expected_side_effects: tuple[str, ...] = Field(min_length=1)
    alternative_path_summary: str = Field(min_length=1)
    input_payload: JsonObject = Field(default_factory=dict)

    _validate_input_payload = field_validator("input_payload")(_validate_json_object)
    _validate_expected_side_effects = field_validator("expected_side_effects")(
        _validate_non_empty_string_items
    )


class SubmitStageArtifactDecision(_StrictBaseModel):
    artifact_type: str = Field(min_length=1)
    artifact_payload: JsonObject = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    risk_summary: JsonObject | None = None
    failure_summary: JsonObject | None = None

    _validate_artifact_payload = field_validator("artifact_payload")(
        _validate_json_object
    )
    _validate_risk_summary = field_validator("risk_summary")(_validate_json_object)
    _validate_failure_summary = field_validator("failure_summary")(
        _validate_json_object
    )
    _validate_evidence_refs = field_validator("evidence_refs")(
        _validate_non_empty_string_items
    )


class ClarificationDecision(_StrictBaseModel):
    question: str = Field(min_length=1)
    missing_facts: tuple[str, ...] = Field(min_length=1)
    impact_scope: str = Field(min_length=1)
    related_refs: tuple[str, ...] = Field(default_factory=tuple)
    fields_to_update: tuple[str, ...] = Field(min_length=1)

    _validate_missing_facts = field_validator("missing_facts")(
        _validate_non_empty_string_items
    )
    _validate_related_refs = field_validator("related_refs")(
        _validate_non_empty_string_items
    )
    _validate_fields_to_update = field_validator("fields_to_update")(
        _validate_non_empty_string_items
    )


class StructuredRepairDecision(_StrictBaseModel):
    parse_error: str = Field(min_length=1)
    repair_instruction: str = Field(min_length=1)
    invalid_output_ref: str = Field(min_length=1)


class RetryWithRevisedPlanDecision(_StrictBaseModel):
    reason: str = Field(min_length=1)
    revised_plan_steps: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    _validate_revised_plan_steps = field_validator("revised_plan_steps")(
        _validate_non_empty_string_items
    )
    _validate_evidence_refs = field_validator("evidence_refs")(
        _validate_non_empty_string_items
    )


class FailStageDecision(_StrictBaseModel):
    failure_reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    incomplete_items: tuple[str, ...] = Field(min_length=1)
    user_visible_summary: str = Field(min_length=1)

    _validate_evidence_refs = field_validator("evidence_refs")(
        _validate_non_empty_string_items
    )
    _validate_incomplete_items = field_validator("incomplete_items")(
        _validate_non_empty_string_items
    )


class AgentDecision(_StrictBaseModel):
    decision_type: AgentDecisionType
    decision_trace: AgentDecisionTrace
    tool_call: ToolCallDecision | None = None
    tool_confirmation: ToolConfirmationDecision | None = None
    stage_artifact: SubmitStageArtifactDecision | None = None
    clarification: ClarificationDecision | None = None
    structured_repair: StructuredRepairDecision | None = None
    retry: RetryWithRevisedPlanDecision | None = None
    fail_stage: FailStageDecision | None = None

    @model_validator(mode="after")
    def validate_single_payload(self) -> Self:
        payloads = {
            AgentDecisionType.REQUEST_TOOL_CALL: self.tool_call,
            AgentDecisionType.REQUEST_TOOL_CONFIRMATION: self.tool_confirmation,
            AgentDecisionType.SUBMIT_STAGE_ARTIFACT: self.stage_artifact,
            AgentDecisionType.REQUEST_CLARIFICATION: self.clarification,
            AgentDecisionType.REPAIR_STRUCTURED_OUTPUT: self.structured_repair,
            AgentDecisionType.RETRY_WITH_REVISED_PLAN: self.retry,
            AgentDecisionType.FAIL_STAGE: self.fail_stage,
        }
        if payloads[self.decision_type] is None:
            raise ValueError("decision payload must match decision_type")
        extra_payloads = [
            decision_type.value
            for decision_type, payload in payloads.items()
            if decision_type is not self.decision_type and payload is not None
        ]
        if extra_payloads:
            raise ValueError("only one decision payload may be set")
        return self


class AgentDecisionParser:
    def __init__(self) -> None:
        self._tool_input_validator = ToolInputSchemaValidator()

    def parse_model_result(
        self,
        model_result: ModelCallResult,
        *,
        context_envelope: ContextEnvelope,
        stage_contract: dict[str, object],
    ) -> AgentDecision:
        if model_result.provider_error_code is not None:
            self._raise_error(
                AgentDecisionErrorCode.PROVIDER_CALL_FAILED,
                "Provider call failed before an AgentDecision could be parsed.",
                model_result=model_result,
                safe_details={
                    "provider_error_code": _enum_value(
                        model_result.provider_error_code
                    )
                },
            )
        if model_result.invalid_tool_call_candidates:
            candidate = model_result.invalid_tool_call_candidates[0]
            self._raise_error(
                AgentDecisionErrorCode.INVALID_TOOL_CALL,
                "Model returned an invalid native tool-call candidate.",
                model_result=model_result,
                safe_details=_safe_candidate_details(candidate),
            )

        has_structured = (
            model_result.structured_output is not None
            or bool(model_result.structured_output_candidates)
        )
        has_tool_calls = bool(model_result.tool_call_requests)
        if has_structured and has_tool_calls:
            self._raise_error(
                AgentDecisionErrorCode.AMBIGUOUS_MODEL_DECISION,
                "Model returned both structured decision output and native tool calls.",
                model_result=model_result,
                safe_details={"tool_call_count": len(model_result.tool_call_requests)},
            )
        if has_tool_calls:
            if len(model_result.tool_call_requests) != 1:
                self._raise_error(
                    AgentDecisionErrorCode.AMBIGUOUS_MODEL_DECISION,
                    "Model returned multiple native tool calls for a single decision.",
                    model_result=model_result,
                    safe_details={
                        "tool_call_count": len(model_result.tool_call_requests)
                    },
                )
            return self.validate_against_stage_contract(
                self._decision_from_tool_call(
                    model_result.tool_call_requests[0],
                    model_result=model_result,
                ),
                context_envelope=context_envelope,
                stage_contract=stage_contract,
            )

        structured = self._selected_structured_output(model_result)
        return self.validate_against_stage_contract(
            self._decision_from_structured_output(
                structured,
                model_result=model_result,
            ),
            context_envelope=context_envelope,
            stage_contract=stage_contract,
        )

    def validate_against_stage_contract(
        self,
        decision: AgentDecision,
        *,
        context_envelope: ContextEnvelope,
        stage_contract: dict[str, object],
    ) -> AgentDecision:
        if decision.tool_call is not None:
            self._validate_tool_call(
                decision.tool_call,
                model_result_context=decision.decision_trace,
                context_envelope=context_envelope,
                stage_contract=stage_contract,
            )
        if decision.tool_confirmation is not None:
            self._validate_tool_available_and_allowed(
                decision.tool_confirmation.tool_name,
                model_result_context=decision.decision_trace,
                context_envelope=context_envelope,
                stage_contract=stage_contract,
            )
        if decision.stage_artifact is not None:
            self._validate_stage_artifact(
                decision.stage_artifact,
                model_result_context=decision.decision_trace,
                stage_contract=stage_contract,
            )
        if decision.clarification is not None:
            allowed = (
                stage_contract.get("clarification_allowed") is True
                or stage_contract.get("can_request_clarification") is True
            )
            if not allowed:
                self._raise_error_from_trace(
                    AgentDecisionErrorCode.CLARIFICATION_NOT_ALLOWED,
                    "The current stage contract does not allow clarification requests.",
                    trace=decision.decision_trace,
                    safe_details={},
                )
        return decision

    def _validate_tool_call(
        self,
        decision: ToolCallDecision,
        *,
        model_result_context: AgentDecisionTrace,
        context_envelope: ContextEnvelope,
        stage_contract: dict[str, object],
    ) -> None:
        tool = self._validate_tool_available_and_allowed(
            decision.tool_name,
            model_result_context=model_result_context,
            context_envelope=context_envelope,
            stage_contract=stage_contract,
        )
        if (
            decision.schema_version is not None
            and decision.schema_version != tool.schema_version
        ):
            self._raise_error_from_trace(
                AgentDecisionErrorCode.TOOL_SCHEMA_MISMATCH,
                "Tool call schema version does not match the current available tool schema.",
                trace=model_result_context,
                safe_details={
                    "tool_name": decision.tool_name,
                    "schema_version": decision.schema_version,
                    "expected_schema_version": tool.schema_version,
                },
            )
        try:
            self._tool_input_validator.validate(
                tool.input_schema,
                decision.input_payload,
            )
        except ValueError as exc:
            self._raise_error_from_trace(
                AgentDecisionErrorCode.TOOL_INPUT_SCHEMA_INVALID,
                "Tool call input does not match the registered schema.",
                trace=model_result_context,
                safe_details={"tool_name": decision.tool_name, "reason": str(exc)},
            )

    def _validate_stage_artifact(
        self,
        decision: SubmitStageArtifactDecision,
        *,
        model_result_context: AgentDecisionTrace,
        stage_contract: dict[str, object],
    ) -> None:
        expected = stage_contract.get("structured_artifact_required")
        if isinstance(expected, str) and expected:
            if decision.artifact_type != expected:
                self._raise_error_from_trace(
                    AgentDecisionErrorCode.STAGE_CONTRACT_VIOLATION,
                    "Stage artifact type does not match the stage contract.",
                    trace=model_result_context,
                    safe_details={
                        "artifact_type": decision.artifact_type,
                        "expected_artifact_type": expected,
                    },
                )

        output_contract = stage_contract.get("output_contract")
        if isinstance(output_contract, Mapping):
            try:
                self._tool_input_validator.validate(
                    output_contract,
                    decision.artifact_payload,
                )
            except ValueError as exc:
                self._raise_error_from_trace(
                    AgentDecisionErrorCode.STAGE_CONTRACT_VIOLATION,
                    "Stage artifact payload does not match the stage output contract.",
                    trace=model_result_context,
                    safe_details={
                        "artifact_type": decision.artifact_type,
                        "reason": str(exc),
                    },
                )
            return

        for field_name in _artifact_required_fields(stage_contract, decision):
            if field_name not in decision.artifact_payload:
                self._raise_error_from_trace(
                    AgentDecisionErrorCode.STAGE_CONTRACT_VIOLATION,
                    "Stage artifact payload is missing a required output field.",
                    trace=model_result_context,
                    safe_details={
                        "artifact_type": decision.artifact_type,
                        "missing_field": field_name,
                    },
                )

    def _validate_tool_available_and_allowed(
        self,
        tool_name: str,
        *,
        model_result_context: AgentDecisionTrace,
        context_envelope: ContextEnvelope,
        stage_contract: dict[str, object],
    ) -> ToolBindableDescription:
        available = {tool.name: tool for tool in context_envelope.available_tools}
        tool = available.get(tool_name)
        if tool is None:
            self._raise_error_from_trace(
                AgentDecisionErrorCode.TOOL_NOT_AVAILABLE,
                "Tool call references a tool that is not available in the current context.",
                trace=model_result_context,
                safe_details={"tool_name": tool_name},
            )
        allowed_tools = _allowed_tool_names(stage_contract.get("allowed_tools"))
        if allowed_tools is not None and tool_name not in allowed_tools:
            self._raise_error_from_trace(
                AgentDecisionErrorCode.TOOL_NOT_AVAILABLE,
                "Tool call references a tool that is not allowed for the current stage.",
                trace=model_result_context,
                safe_details={"tool_name": tool_name},
            )
        return tool

    def _selected_structured_output(
        self,
        model_result: ModelCallResult,
    ) -> JsonObject:
        if model_result.structured_output is not None:
            return dict(model_result.structured_output)
        if len(model_result.structured_output_candidates) == 1:
            return dict(model_result.structured_output_candidates[0])
        if len(model_result.structured_output_candidates) > 1:
            self._raise_error(
                AgentDecisionErrorCode.AMBIGUOUS_MODEL_DECISION,
                "Model returned multiple structured decision candidates.",
                model_result=model_result,
                safe_details={
                    "structured_candidate_count": len(
                        model_result.structured_output_candidates
                    )
                },
            )
        self._raise_error(
            AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT,
            "Model did not return a structured AgentDecision.",
            model_result=model_result,
            safe_details={},
        )

    def _decision_from_tool_call(
        self,
        tool_call: ModelCallToolRequest,
        *,
        model_result: ModelCallResult,
    ) -> AgentDecision:
        model_call_ref = self._model_call_ref(model_result)
        decision_type = AgentDecisionType.REQUEST_TOOL_CALL
        trace = self._trace_from_model_result(
            model_result,
            status="accepted",
            decision_type=decision_type,
        )
        return AgentDecision(
            decision_type=decision_type,
            decision_trace=trace,
            tool_call=ToolCallDecision(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                input_payload=dict(tool_call.input_payload),
                schema_version=tool_call.schema_version,
                model_call_ref=model_call_ref,
            ),
        )

    def _decision_from_structured_output(
        self,
        structured: JsonObject,
        *,
        model_result: ModelCallResult,
    ) -> AgentDecision:
        decision_type = self._structured_decision_type(
            structured,
            model_result=model_result,
        )
        if decision_type is AgentDecisionType.REQUEST_TOOL_CALL:
            self._raise_error(
                AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT,
                "request_tool_call must be provided as a native tool call request.",
                model_result=model_result,
                decision_type=decision_type,
                safe_details={"decision_type": decision_type.value},
            )
        payload = {
            key: value
            for key, value in structured.items()
            if key != "decision_type"
        }
        trace = self._trace_from_model_result(
            model_result,
            status="accepted",
            decision_type=decision_type,
        )
        try:
            return self._build_structured_decision(
                decision_type,
                payload=payload,
                trace=trace,
                model_call_ref=self._model_call_ref(model_result),
            )
        except ValidationError as exc:
            self._raise_error(
                AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT,
                "Structured AgentDecision payload is invalid.",
                model_result=model_result,
                decision_type=decision_type,
                safe_details={
                    "decision_type": decision_type.value,
                    "reason": _validation_reason(exc),
                },
            )

    def _structured_decision_type(
        self,
        structured: JsonObject,
        *,
        model_result: ModelCallResult,
    ) -> AgentDecisionType:
        raw_decision_type = structured.get("decision_type")
        try:
            return AgentDecisionType(raw_decision_type)
        except ValueError:
            self._raise_error(
                AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT,
                "Structured AgentDecision payload has an invalid decision_type.",
                model_result=model_result,
                safe_details={
                    "decision_type": (
                        raw_decision_type
                        if isinstance(raw_decision_type, str)
                        else "missing_or_invalid"
                    )
                },
            )

    def _build_structured_decision(
        self,
        decision_type: AgentDecisionType,
        *,
        payload: JsonObject,
        trace: AgentDecisionTrace,
        model_call_ref: str,
    ) -> AgentDecision:
        if decision_type is AgentDecisionType.REQUEST_TOOL_CALL:
            raise ValueError("request_tool_call requires a native tool call request")
        if decision_type is AgentDecisionType.REQUEST_TOOL_CONFIRMATION:
            return AgentDecision(
                decision_type=decision_type,
                decision_trace=trace,
                tool_confirmation=ToolConfirmationDecision.model_validate(payload),
            )
        if decision_type is AgentDecisionType.SUBMIT_STAGE_ARTIFACT:
            return AgentDecision(
                decision_type=decision_type,
                decision_trace=trace,
                stage_artifact=SubmitStageArtifactDecision.model_validate(payload),
            )
        if decision_type is AgentDecisionType.REQUEST_CLARIFICATION:
            return AgentDecision(
                decision_type=decision_type,
                decision_trace=trace,
                clarification=ClarificationDecision.model_validate(payload),
            )
        if decision_type is AgentDecisionType.REPAIR_STRUCTURED_OUTPUT:
            return AgentDecision(
                decision_type=decision_type,
                decision_trace=trace,
                structured_repair=StructuredRepairDecision.model_validate(payload),
            )
        if decision_type is AgentDecisionType.RETRY_WITH_REVISED_PLAN:
            return AgentDecision(
                decision_type=decision_type,
                decision_trace=trace,
                retry=RetryWithRevisedPlanDecision.model_validate(payload),
            )
        return AgentDecision(
            decision_type=decision_type,
            decision_trace=trace,
            fail_stage=FailStageDecision.model_validate(payload),
        )

    def _raise_error(
        self,
        error_code: AgentDecisionErrorCode,
        safe_message: str,
        *,
        model_result: ModelCallResult,
        safe_details: JsonObject,
        decision_type: AgentDecisionType | None = None,
    ) -> NoReturn:
        trace = self._trace_from_model_result(
            model_result,
            status="rejected",
            decision_type=decision_type,
            reason=error_code.value,
        )
        raise AgentDecisionParserError(
            AgentDecisionModelCallError(
                error_code=error_code,
                safe_message=safe_message,
                safe_details=_safe_details(safe_details),
                decision_trace=trace,
            )
        )

    def _raise_error_from_trace(
        self,
        error_code: AgentDecisionErrorCode,
        safe_message: str,
        *,
        trace: AgentDecisionTrace,
        safe_details: JsonObject,
    ) -> NoReturn:
        rejected_trace = self._rejected_trace_from_accepted_trace(
            trace,
            reason=error_code.value,
        )
        raise AgentDecisionParserError(
            AgentDecisionModelCallError(
                error_code=error_code,
                safe_message=safe_message,
                safe_details=_safe_details(safe_details),
                decision_trace=rejected_trace,
            )
        )

    def _trace_from_model_result(
        self,
        model_result: ModelCallResult,
        *,
        status: Literal["accepted", "rejected"],
        decision_type: AgentDecisionType | None = None,
        reason: str | None = None,
    ) -> AgentDecisionTrace:
        model_call_ref = self._model_call_ref(model_result)
        trace_summary = model_result.trace_summary
        trace_ref = _trace_ref(
            model_call_ref=model_call_ref,
            decision_type=decision_type,
            status=status,
            reason=reason,
            provider_snapshot_id=model_result.provider_snapshot_id,
            model_binding_snapshot_id=model_result.model_binding_snapshot_id,
            trace_id=trace_summary.trace_id,
            stage_run_id=trace_summary.stage_run_id,
        )
        return AgentDecisionTrace(
            trace_ref=trace_ref,
            status=status,
            decision_type=decision_type,
            model_call_ref=model_call_ref,
            provider_snapshot_id=model_result.provider_snapshot_id,
            model_binding_snapshot_id=model_result.model_binding_snapshot_id,
            model_call_type=_enum_value(model_result.model_call_type),
            request_id=trace_summary.request_id,
            trace_id=trace_summary.trace_id,
            correlation_id=trace_summary.correlation_id,
            span_id=trace_summary.span_id,
            parent_span_id=trace_summary.parent_span_id,
            run_id=trace_summary.run_id,
            stage_run_id=trace_summary.stage_run_id,
            reason=reason,
        )

    def _rejected_trace_from_accepted_trace(
        self,
        trace: AgentDecisionTrace,
        *,
        reason: str,
    ) -> AgentDecisionTrace:
        trace_ref = _trace_ref(
            model_call_ref=trace.model_call_ref,
            decision_type=trace.decision_type,
            status="rejected",
            reason=reason,
            provider_snapshot_id=trace.provider_snapshot_id,
            model_binding_snapshot_id=trace.model_binding_snapshot_id,
            trace_id=trace.trace_id,
            stage_run_id=trace.stage_run_id,
        )
        return trace.model_copy(
            update={
                "trace_ref": trace_ref,
                "status": "rejected",
                "reason": reason,
            }
        )

    def _model_call_ref(self, model_result: ModelCallResult) -> str:
        if model_result.raw_response_ref:
            return model_result.raw_response_ref
        source = {
            "provider_snapshot_id": model_result.provider_snapshot_id,
            "model_binding_snapshot_id": model_result.model_binding_snapshot_id,
            "model_call_type": _enum_value(model_result.model_call_type),
            "request_id": model_result.trace_summary.request_id,
            "trace_id": model_result.trace_summary.trace_id,
            "stage_run_id": model_result.trace_summary.stage_run_id,
        }
        encoded = json.dumps(source, sort_keys=True, separators=(",", ":"))
        return f"model-call:{sha256(encoded.encode('utf-8')).hexdigest()}"


def _trace_ref(
    *,
    model_call_ref: str,
    decision_type: AgentDecisionType | None,
    status: str,
    reason: str | None,
    provider_snapshot_id: str,
    model_binding_snapshot_id: str,
    trace_id: str,
    stage_run_id: str | None,
) -> str:
    source = {
        "model_call_ref": model_call_ref,
        "decision_type": decision_type.value if decision_type is not None else None,
        "status": status,
        "reason": reason,
        "provider_snapshot_id": provider_snapshot_id,
        "model_binding_snapshot_id": model_binding_snapshot_id,
        "trace_id": trace_id,
        "stage_run_id": stage_run_id,
    }
    encoded = json.dumps(source, sort_keys=True, separators=(",", ":"))
    digest = sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"agent-decision-trace-{digest}"


def _allowed_tool_names(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return ()
    if not isinstance(value, Sequence):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _artifact_required_fields(
    stage_contract: Mapping[str, object],
    decision: SubmitStageArtifactDecision,
) -> tuple[str, ...]:
    candidates: list[str] = []
    output_contract = stage_contract.get("output_contract")
    if isinstance(output_contract, str) and output_contract:
        candidates.append(output_contract)
    structured_artifact_required = stage_contract.get("structured_artifact_required")
    if isinstance(structured_artifact_required, str) and structured_artifact_required:
        candidates.append(structured_artifact_required)
    candidates.append(decision.artifact_type)

    for candidate in candidates:
        required = _ARTIFACT_REQUIRED_FIELDS.get(candidate)
        if required is not None:
            return required
    return ()


def _safe_candidate_details(candidate: Mapping[str, object]) -> JsonObject:
    details: JsonObject = {}
    for key in ("call_id", "tool_name", "error"):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            details[key] = _bounded_string(value)
    if "arguments_text" in candidate:
        details["arguments_text_present"] = candidate.get("arguments_text") is not None
    return details


def _safe_details(details: Mapping[str, Any]) -> JsonObject:
    return {
        _bounded_string(key): _safe_detail_value(value)
        for key, value in details.items()
    }


def _safe_detail_value(value: Any) -> Any:
    if isinstance(value, str):
        return _bounded_string(value)
    if isinstance(value, list | tuple):
        return [_safe_detail_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _bounded_string(str(key)): _safe_detail_value(item)
            for key, item in value.items()
        }
    return value


def _bounded_string(value: str, *, limit: int = 200) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _validation_reason(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "validation_failed"
    first = errors[0]
    location = ".".join(str(item) for item in first.get("loc", ()))
    message = str(first.get("msg", "validation_failed"))
    if location:
        return f"{location}: {message}"
    return message


__all__ = [
    "AgentDecision",
    "AgentDecisionErrorCode",
    "AgentDecisionModelCallError",
    "AgentDecisionParser",
    "AgentDecisionParserError",
    "AgentDecisionTrace",
    "AgentDecisionType",
    "ClarificationDecision",
    "FailStageDecision",
    "RetryWithRevisedPlanDecision",
    "StructuredRepairDecision",
    "SubmitStageArtifactDecision",
    "ToolCallDecision",
    "ToolConfirmationDecision",
]
