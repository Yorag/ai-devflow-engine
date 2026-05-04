from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.context.schemas import ContextEnvelope
from backend.app.domain.enums import StageType, ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.providers.langchain_adapter import (
    ModelCallResult,
    ModelCallToolRequest,
    ModelCallTraceSummary,
    ModelCallUsage,
)
from backend.app.schemas.prompts import ModelCallType
from backend.app.tools.protocol import ToolBindableDescription


NOW = datetime(2026, 5, 4, 16, 30, tzinfo=UTC)


def trace_context() -> TraceContext:
    return TraceContext(
        request_id="request-decision-1",
        trace_id="trace-decision-1",
        correlation_id="correlation-decision-1",
        span_id="span-decision-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def tool_description(
    name: str = "read_file",
    schema_version: str = "tool-schema-v1",
) -> ToolBindableDescription:
    return ToolBindableDescription(
        name=name,
        description=f"{name} tool.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.READ_ONLY,
        risk_categories=[],
        schema_version=schema_version,
    )


def context_envelope(
    *,
    available_tools: tuple[ToolBindableDescription, ...] = (tool_description(),),
    stage_type: StageType = StageType.CODE_GENERATION,
) -> ContextEnvelope:
    return ContextEnvelope(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=stage_type,
        template_snapshot_ref="template-snapshot-run-1",
        stage_contract_ref=f"stage-contract-{stage_type.value}",
        provider_snapshot_ref="provider-snapshot-run-1",
        model_binding_snapshot_ref="model-binding-snapshot-run-1",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        runtime_instructions=(),
        stage_contract=(),
        agent_role_prompt=(),
        task_objective=(),
        specified_action=(),
        input_artifact_refs=(),
        context_references=(),
        working_observations=(),
        reasoning_trace=(),
        available_tools=available_tools,
        recent_observations=(),
        response_schema={"type": "object"},
        trace_context=trace_context(),
        built_at=NOW,
    )


def stage_contract(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "stage_responsibility": "Implement code changes.",
        "output_contract": "CodeGenerationArtifact",
        "structured_artifact_required": "CodeGenerationArtifact",
        "allowed_tools": ["read_file"],
    }
    values.update(overrides)
    return values


def model_result(
    *,
    structured_output: dict[str, object] | None = None,
    structured_output_candidates: tuple[dict[str, object], ...] = (),
    tool_call_requests: tuple[ModelCallToolRequest, ...] = (),
    invalid_tool_call_candidates: tuple[dict[str, object], ...] = (),
) -> ModelCallResult:
    return ModelCallResult(
        provider_snapshot_id="provider-snapshot-run-1",
        model_binding_snapshot_id="model-binding-snapshot-run-1",
        model_call_type=ModelCallType.STAGE_EXECUTION,
        structured_output=structured_output,
        structured_output_candidates=structured_output_candidates,
        tool_call_requests=tool_call_requests,
        invalid_tool_call_candidates=invalid_tool_call_candidates,
        usage=ModelCallUsage(input_tokens=10, output_tokens=6, total_tokens=16),
        raw_response_ref="sha256:model-response",
        trace_summary=ModelCallTraceSummary(
            request_id="request-decision-1",
            trace_id="trace-decision-1",
            correlation_id="correlation-decision-1",
            span_id="span-decision-1",
            parent_span_id=None,
            run_id="run-1",
            stage_run_id="stage-run-1",
            provider_snapshot_id="provider-snapshot-run-1",
            model_binding_snapshot_id="model-binding-snapshot-run-1",
            model_call_type=ModelCallType.STAGE_EXECUTION,
            input_summary={"content_hash": "sha256:input"},
            output_summary={"content_hash": "sha256:output"},
        ),
    )


def test_parse_native_tool_call_validates_available_tool_and_schema_version() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionParser,
        AgentDecisionType,
    )

    decision = AgentDecisionParser().parse_model_result(
        model_result(
            tool_call_requests=(
                ModelCallToolRequest(
                    call_id="call-1",
                    tool_name="read_file",
                    input_payload={"path": "src/app.py"},
                    schema_version="tool-schema-v1",
                ),
            )
        ),
        context_envelope=context_envelope(),
        stage_contract=stage_contract(),
    )

    assert decision.decision_type is AgentDecisionType.REQUEST_TOOL_CALL
    assert decision.tool_call is not None
    assert decision.tool_call.tool_name == "read_file"
    assert decision.tool_call.input_payload == {"path": "src/app.py"}
    assert decision.decision_trace.status == "accepted"
    assert decision.decision_trace.model_call_ref == "sha256:model-response"


def test_parse_rejects_unknown_or_not_allowed_tool_call_as_structured_error() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                tool_call_requests=(
                    ModelCallToolRequest(
                        call_id="call-1",
                        tool_name="bash",
                        input_payload={"path": "src/app.py"},
                        schema_version="tool-schema-v1",
                    ),
                )
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert error.value.error.error_code is AgentDecisionErrorCode.TOOL_NOT_AVAILABLE
    assert error.value.error.decision_trace.status == "rejected"
    assert error.value.error.safe_details["tool_name"] == "bash"


def test_parse_rejects_available_tool_not_allowed_by_stage_contract() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                tool_call_requests=(
                    ModelCallToolRequest(
                        call_id="call-1",
                        tool_name="read_file",
                        input_payload={"path": "src/app.py"},
                        schema_version="tool-schema-v1",
                    ),
                )
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(allowed_tools=["grep"]),
        )

    assert error.value.error.error_code is AgentDecisionErrorCode.TOOL_NOT_AVAILABLE
    assert error.value.error.safe_details["tool_name"] == "read_file"


def test_parse_rejects_tool_schema_version_drift() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                tool_call_requests=(
                    ModelCallToolRequest(
                        call_id="call-1",
                        tool_name="read_file",
                        input_payload={"path": "src/app.py"},
                        schema_version="tool-schema-old",
                    ),
                )
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert error.value.error.error_code is AgentDecisionErrorCode.TOOL_SCHEMA_MISMATCH


def test_parse_rejects_invalid_tool_input_schema_before_execution() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                tool_call_requests=(
                    ModelCallToolRequest(
                        call_id="call-1",
                        tool_name="read_file",
                        input_payload={"target": "src/app.py"},
                        schema_version="tool-schema-v1",
                    ),
                )
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.TOOL_INPUT_SCHEMA_INVALID
    )


def test_parse_structured_tool_confirmation_returns_data_without_creating_confirmation() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionParser,
        AgentDecisionType,
    )

    decision = AgentDecisionParser().parse_model_result(
        model_result(
            structured_output={
                "decision_type": "request_tool_confirmation",
                "tool_name": "read_file",
                "command_summary": "Read src/app.py",
                "target_resource": "src/app.py",
                "risk_level": "high_risk",
                "risk_categories": ["credential_access"],
                "expected_side_effects": ["None; read-only inspection."],
                "alternative_path_summary": "Ask user to paste file excerpt.",
                "input_payload": {"path": "src/app.py"},
            }
        ),
        context_envelope=context_envelope(),
        stage_contract=stage_contract(),
    )

    assert decision.decision_type is AgentDecisionType.REQUEST_TOOL_CONFIRMATION
    assert decision.tool_confirmation is not None
    assert decision.tool_confirmation.risk_level is ToolRiskLevel.HIGH_RISK
    assert decision.tool_confirmation.risk_categories == (
        ToolRiskCategory.CREDENTIAL_ACCESS,
    )


def test_parse_rejects_tool_confirmation_without_alternative_path() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                structured_output={
                    "decision_type": "request_tool_confirmation",
                    "tool_name": "read_file",
                    "command_summary": "Read src/app.py",
                    "target_resource": "src/app.py",
                    "risk_level": "high_risk",
                    "risk_categories": ["credential_access"],
                    "expected_side_effects": ["None; read-only inspection."],
                    "input_payload": {"path": "src/app.py"},
                }
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT
    )


def test_parse_rejects_blank_tool_confirmation_side_effect() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                structured_output={
                    "decision_type": "request_tool_confirmation",
                    "tool_name": "read_file",
                    "command_summary": "Read src/app.py",
                    "target_resource": "src/app.py",
                    "risk_level": "high_risk",
                    "risk_categories": ["credential_access"],
                    "expected_side_effects": [""],
                    "alternative_path_summary": "Ask user to paste file excerpt.",
                    "input_payload": {"path": "src/app.py"},
                }
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT
    )


def test_parse_rejects_structured_tool_call_because_tools_must_be_native() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                structured_output={
                    "decision_type": "request_tool_call",
                    "call_id": "call-structured-1",
                    "tool_name": "read_file",
                    "input_payload": {"path": "src/app.py"},
                }
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT
    )


def test_parse_submit_stage_artifact_validates_stage_contract_and_evidence_refs() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionParser,
        AgentDecisionType,
    )

    decision = AgentDecisionParser().parse_model_result(
        model_result(
            structured_output={
                "decision_type": "submit_stage_artifact",
                "artifact_type": "CodeGenerationArtifact",
                "artifact_payload": {
                    "changeset_ref": "changeset://run-1/code-generation/1",
                    "changed_files": ["backend/app/runtime/agent_decision.py"],
                    "diff_refs": ["diff://run-1/code-generation/1"],
                    "file_edit_trace_refs": ["file-edit://run-1/agent-decision"],
                    "implementation_notes": "Implemented parser.",
                    "requirement_refs": ["requirement://run-1/1"],
                    "solution_refs": ["solution://run-1/1"],
                },
                "evidence_refs": ["stage-process://stage-run-1/tool/read-file"],
                "risk_summary": None,
                "failure_summary": None,
            }
        ),
        context_envelope=context_envelope(),
        stage_contract=stage_contract(),
    )

    assert decision.decision_type is AgentDecisionType.SUBMIT_STAGE_ARTIFACT
    assert decision.stage_artifact is not None
    assert decision.stage_artifact.artifact_type == "CodeGenerationArtifact"
    assert decision.stage_artifact.risk_summary is None


def test_parse_rejects_stage_artifact_missing_output_contract_fields() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": {
                        "changed_files": ["backend/app/runtime/agent_decision.py"],
                        "implementation_notes": "Missing required trace refs.",
                    },
                    "evidence_refs": ["stage-process://stage-run-1/ref"],
                }
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.STAGE_CONTRACT_VIOLATION
    )
    assert error.value.error.safe_details["missing_field"] == "changeset_ref"


def test_parse_rejects_blank_stage_artifact_evidence_ref() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": {
                        "changeset_ref": "changeset://run-1/code-generation/1",
                        "changed_files": ["backend/app/runtime/agent_decision.py"],
                        "diff_refs": ["diff://run-1/code-generation/1"],
                        "file_edit_trace_refs": ["file-edit://run-1/agent-decision"],
                        "implementation_notes": "Implemented parser.",
                        "requirement_refs": ["requirement://run-1/1"],
                        "solution_refs": ["solution://run-1/1"],
                    },
                    "evidence_refs": [""],
                }
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT
    )


def test_parse_rejects_stage_artifact_json_schema_output_contract_violation() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CustomArtifact",
                    "artifact_payload": {"summary": ""},
                    "evidence_refs": ["stage-process://stage-run-1/ref"],
                }
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(
                output_contract={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "minLength": 1},
                    },
                    "required": ["summary"],
                    "additionalProperties": False,
                },
                structured_artifact_required="CustomArtifact",
            ),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.STAGE_CONTRACT_VIOLATION
    )
    assert "minLength" in error.value.error.safe_details["reason"]


def test_parse_stage_artifact_json_schema_overrides_known_artifact_fallback() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionParser,
        AgentDecisionType,
    )

    decision = AgentDecisionParser().parse_model_result(
        model_result(
            structured_output={
                "decision_type": "submit_stage_artifact",
                "artifact_type": "CodeGenerationArtifact",
                "artifact_payload": {"summary": "schema-controlled payload"},
                "evidence_refs": ["stage-process://stage-run-1/ref"],
            }
        ),
        context_envelope=context_envelope(),
        stage_contract=stage_contract(
            output_contract={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "minLength": 1},
                },
                "required": ["summary"],
                "additionalProperties": False,
            },
            structured_artifact_required="CodeGenerationArtifact",
        ),
    )

    assert decision.decision_type is AgentDecisionType.SUBMIT_STAGE_ARTIFACT
    assert decision.stage_artifact is not None
    assert decision.stage_artifact.artifact_payload == {
        "summary": "schema-controlled payload"
    }


def test_parse_rejects_stage_artifact_wrong_contract() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "DeliveryRecord",
                    "artifact_payload": {"summary": "wrong output"},
                    "evidence_refs": ["stage-process://stage-run-1/ref"],
                }
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.STAGE_CONTRACT_VIOLATION
    )


def test_parse_request_clarification_requires_stage_contract_permission() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    parser = AgentDecisionParser()
    payload = {
        "decision_type": "request_clarification",
        "question": "Which package should be changed?",
        "missing_facts": ["target package"],
        "impact_scope": "Cannot produce a safe implementation plan.",
        "related_refs": ["message://session-1/1"],
        "fields_to_update": ["target_package"],
    }

    with pytest.raises(AgentDecisionParserError) as error:
        parser.parse_model_result(
            model_result(structured_output=payload),
            context_envelope=context_envelope(stage_type=StageType.REQUIREMENT_ANALYSIS),
            stage_contract=stage_contract(
                allowed_tools=[],
                clarification_allowed=False,
            ),
        )

    assert (
        error.value.error.error_code
        is AgentDecisionErrorCode.CLARIFICATION_NOT_ALLOWED
    )

    decision = parser.parse_model_result(
        model_result(structured_output=payload),
        context_envelope=context_envelope(stage_type=StageType.REQUIREMENT_ANALYSIS),
        stage_contract=stage_contract(allowed_tools=[], clarification_allowed=True),
    )
    assert decision.clarification is not None
    assert decision.clarification.missing_facts == ("target package",)


def test_parse_repair_retry_and_fail_stage_structured_decisions() -> None:
    from backend.app.runtime.agent_decision import AgentDecisionParser, AgentDecisionType

    parser = AgentDecisionParser()

    repair = parser.parse_model_result(
        model_result(
            structured_output={
                "decision_type": "repair_structured_output",
                "parse_error": "missing evidence_refs",
                "repair_instruction": "Return submit_stage_artifact with evidence_refs.",
                "invalid_output_ref": "sha256:model-response",
            }
        ),
        context_envelope=context_envelope(),
        stage_contract=stage_contract(),
    )
    assert repair.decision_type is AgentDecisionType.REPAIR_STRUCTURED_OUTPUT

    retry = parser.parse_model_result(
        model_result(
            structured_output={
                "decision_type": "retry_with_revised_plan",
                "reason": "Tool output was incomplete.",
                "revised_plan_steps": ["Read the smaller file first."],
                "evidence_refs": ["stage-process://stage-run-1/tool/read-file"],
            }
        ),
        context_envelope=context_envelope(),
        stage_contract=stage_contract(),
    )
    assert retry.decision_type is AgentDecisionType.RETRY_WITH_REVISED_PLAN

    failure = parser.parse_model_result(
        model_result(
            structured_output={
                "decision_type": "fail_stage",
                "failure_reason": "Required repository file is unavailable.",
                "evidence_refs": ["stage-process://stage-run-1/tool/read-file"],
                "incomplete_items": ["implementation"],
                "user_visible_summary": (
                    "The stage cannot continue because a required file is unavailable."
                ),
            }
        ),
        context_envelope=context_envelope(),
        stage_contract=stage_contract(),
    )
    assert failure.decision_type is AgentDecisionType.FAIL_STAGE
    assert failure.fail_stage is not None


def test_parse_rejects_invalid_tool_candidates_and_ambiguous_outputs() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    parser = AgentDecisionParser()

    with pytest.raises(AgentDecisionParserError) as invalid_tool:
        parser.parse_model_result(
            model_result(
                invalid_tool_call_candidates=(
                    {
                        "call_id": "invalid-call-1",
                        "tool_name": "read_file",
                        "arguments_text": "{",
                        "error": "json decode error",
                    },
                )
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )
    assert (
        invalid_tool.value.error.error_code
        is AgentDecisionErrorCode.INVALID_TOOL_CALL
    )

    with pytest.raises(AgentDecisionParserError) as ambiguous:
        parser.parse_model_result(
            model_result(
                structured_output={"decision_type": "fail_stage"},
                tool_call_requests=(
                    ModelCallToolRequest(
                        call_id="call-1",
                        tool_name="read_file",
                        input_payload={"path": "src/app.py"},
                        schema_version="tool-schema-v1",
                    ),
                ),
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )
    assert (
        ambiguous.value.error.error_code
        is AgentDecisionErrorCode.AMBIGUOUS_MODEL_DECISION
    )


def test_parse_error_safe_details_bound_model_controlled_strings() -> None:
    from backend.app.runtime.agent_decision import (
        AgentDecisionErrorCode,
        AgentDecisionParser,
        AgentDecisionParserError,
    )

    with pytest.raises(AgentDecisionParserError) as error:
        AgentDecisionParser().parse_model_result(
            model_result(
                structured_output={
                    "decision_type": f"unknown-{'x' * 500}",
                }
            ),
            context_envelope=context_envelope(),
            stage_contract=stage_contract(),
        )

    detail = error.value.error.safe_details["decision_type"]
    assert error.value.error.error_code is AgentDecisionErrorCode.INVALID_STRUCTURED_OUTPUT
    assert isinstance(detail, str)
    assert len(detail) <= 203
    assert detail.endswith("...")
