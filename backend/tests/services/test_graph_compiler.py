from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import ApprovalType, StageType, TemplateSource
from backend.app.domain.runtime_limit_snapshot import (
    FrozenAgentRuntimeLimits,
    FrozenContextLimits,
    RuntimeLimitSnapshot,
)
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot


NOW = datetime(2026, 5, 3, 16, 0, 0, tzinfo=UTC)
FIXED_STAGES = (
    StageType.REQUIREMENT_ANALYSIS,
    StageType.SOLUTION_DESIGN,
    StageType.CODE_GENERATION,
    StageType.TEST_GENERATION_EXECUTION,
    StageType.CODE_REVIEW,
    StageType.DELIVERY_INTEGRATION,
)


def build_template_snapshot(
    *,
    run_id: str = "run-graph-1",
    fixed_stage_sequence: tuple[StageType, ...] = FIXED_STAGES,
    skip_high_risk_tool_confirmations: bool = False,
) -> TemplateSnapshot:
    return TemplateSnapshot(
        snapshot_ref=f"template-snapshot-{run_id}",
        run_id=run_id,
        source_template_id="template-feature-one",
        source_template_name="Feature One",
        source_template=TemplateSource.SYSTEM_TEMPLATE,
        source_template_updated_at=NOW,
        fixed_stage_sequence=fixed_stage_sequence,
        stage_role_bindings=tuple(
            StageRoleSnapshot(
                stage_type=stage_type,
                role_id=f"role-{stage_type.value}",
                system_prompt=f"prompt:{stage_type.value}",
                provider_id="provider-alpha",
            )
            for stage_type in fixed_stage_sequence
        ),
        approval_checkpoints=(
            ApprovalType.SOLUTION_DESIGN_APPROVAL,
            ApprovalType.CODE_REVIEW_APPROVAL,
        ),
        auto_regression_enabled=True,
        max_auto_regression_retries=2,
        max_react_iterations_per_stage=30,
        max_tool_calls_per_stage=80,
        skip_high_risk_tool_confirmations=skip_high_risk_tool_confirmations,
        created_at=NOW,
    )


def build_runtime_limit_snapshot(*, run_id: str = "run-graph-1") -> RuntimeLimitSnapshot:
    return RuntimeLimitSnapshot(
        snapshot_id=f"runtime-limit-snapshot-{run_id}",
        run_id=run_id,
        agent_limits=FrozenAgentRuntimeLimits(
            max_react_iterations_per_stage=30,
            max_tool_calls_per_stage=80,
            max_file_edit_count=20,
            max_patch_attempts_per_file=3,
            max_structured_output_repair_attempts=3,
            max_auto_regression_retries=2,
            max_clarification_rounds=5,
            max_no_progress_iterations=5,
        ),
        context_limits=FrozenContextLimits(
            tool_output_preview_chars=4000,
            bash_stdout_preview_chars=8000,
            bash_stderr_preview_chars=8000,
            grep_max_results=100,
            file_read_max_chars=50000,
            model_output_log_preview_chars=8000,
            model_output_process_preview_chars=12000,
            compression_threshold_ratio=0.8,
        ),
        source_config_version="runtime-settings-v2",
        hard_limits_version="platform-hard-limits-v1",
        created_at=NOW,
    )


def test_compile_builds_fixed_six_stage_graph_definition() -> None:
    from backend.app.services.graph_compiler import GraphCompiler

    definition = GraphCompiler().compile(
        template_snapshot=build_template_snapshot(),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    assert definition.run_id == "run-graph-1"
    assert definition.template_snapshot_ref == "template-snapshot-run-graph-1"
    assert definition.runtime_limit_snapshot_ref == "runtime-limit-snapshot-run-graph-1"
    assert definition.runtime_limit_source_config_version == "runtime-settings-v2"
    assert definition.graph_version == "function-one-mainline-v1"
    assert definition.schema_version == "graph-definition-v1"
    assert [node["stage_type"] for node in definition.stage_nodes] == [
        stage.value for stage in FIXED_STAGES
    ]
    assert definition.interrupt_policy["approval_interrupts"] == [
        "solution_design_approval",
        "code_review_approval",
    ]
    assert definition.retry_policy["max_auto_regression_retries"] == 2
    assert (
        definition.delivery_routing_policy["mode_routes"]["demo_delivery"]
        == "demo_delivery_adapter"
    )
    assert (
        definition.delivery_routing_policy["mode_routes"]["git_auto_delivery"]
        == "git_auto_delivery_adapter"
    )


def test_compile_records_solution_validation_as_internal_solution_design_group() -> None:
    from backend.app.services.graph_compiler import GraphCompiler

    definition = GraphCompiler().compile(
        template_snapshot=build_template_snapshot(),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    solution_node = next(
        node
        for node in definition.stage_nodes
        if node["stage_type"] == StageType.SOLUTION_DESIGN.value
    )

    assert solution_node["node_groups"] == [
        "solution_design_authoring",
        "solution_validation",
    ]
    assert solution_node["entry_node_key"] == "solution_design.authoring"
    assert solution_node["success_node_key"] == "solution_design.approval_gate"
    assert solution_node["failure_route"]["from"] == "solution_validation"
    assert solution_node["failure_route"]["to"] == "solution_design_authoring"
    assert "solution_validation" in definition.source_node_group_map
    assert (
        definition.source_node_group_map["solution_validation"]
        == StageType.SOLUTION_DESIGN.value
    )
    assert all(node["stage_type"] != "solution_validation" for node in definition.stage_nodes)


def test_compile_preserves_code_review_approval_path_and_conditional_regression_route() -> None:
    from backend.app.services.graph_compiler import GraphCompiler

    definition = GraphCompiler().compile(
        template_snapshot=build_template_snapshot(),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    code_review_node = next(
        node for node in definition.stage_nodes if node["stage_type"] == StageType.CODE_REVIEW.value
    )

    assert code_review_node["success_node_key"] == "code_review.approval_gate"
    assert code_review_node["conditional_routes"] == [
        {
            "route_key": "review_regression_retry",
            "condition": {
                "regression_decision": "changes_requested",
                "auto_regression_enabled": True,
            },
            "evidence_source": "code_review_artifact",
            "to": "code_generation",
        }
    ]


def test_compile_maps_all_referenced_node_keys_to_formal_stage_types() -> None:
    from backend.app.services.graph_compiler import GraphCompiler

    definition = GraphCompiler().compile(
        template_snapshot=build_template_snapshot(),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    expected_keys = {
        "requirement_analysis",
        "solution_design_authoring",
        "solution_design.authoring",
        "solution_validation",
        "solution_design.approval_gate",
        "code_generation",
        "test_generation_execution",
        "code_review",
        "code_review.approval_gate",
        "delivery_integration",
        "delivery_complete",
    }

    assert expected_keys <= set(definition.source_node_group_map)
    assert (
        definition.source_node_group_map["solution_design.authoring"]
        == StageType.SOLUTION_DESIGN.value
    )
    assert (
        definition.source_node_group_map["solution_design.approval_gate"]
        == StageType.SOLUTION_DESIGN.value
    )
    assert (
        definition.source_node_group_map["code_review.approval_gate"]
        == StageType.CODE_REVIEW.value
    )
    assert (
        definition.source_node_group_map["delivery_complete"]
        == StageType.DELIVERY_INTEGRATION.value
    )


def test_compile_returns_deeply_immutable_definition_payloads() -> None:
    from backend.app.services.graph_compiler import GraphCompiler

    definition = GraphCompiler().compile(
        template_snapshot=build_template_snapshot(),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    requirement_contract = definition.stage_contracts[StageType.REQUIREMENT_ANALYSIS.value]
    code_review_contract = definition.stage_contracts[StageType.CODE_REVIEW.value]
    runtime_limits = requirement_contract["runtime_limits"]

    assert (
        requirement_contract["runtime_limits"]
        is not code_review_contract["runtime_limits"]
    )

    with pytest.raises(TypeError):
        definition.stage_nodes[0]["success_node_key"] = "mutated"

    with pytest.raises(TypeError):
        definition.stage_contracts[StageType.SOLUTION_DESIGN.value]["allowed_tools"].append(
            "bash"
        )

    with pytest.raises(TypeError):
        runtime_limits |= {"max_tool_calls_per_stage": 999}

    with pytest.raises(TypeError):
        requirement_contract["runtime_limits"]["max_tool_calls_per_stage"] = 999


def test_compile_populates_stage_contracts_with_fixed_allowed_tools_and_runtime_limits() -> None:
    from backend.app.services.graph_compiler import GraphCompiler

    definition = GraphCompiler().compile(
        template_snapshot=build_template_snapshot(),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    assert definition.stage_contracts[StageType.REQUIREMENT_ANALYSIS.value]["allowed_tools"] == []
    assert definition.stage_contracts[StageType.SOLUTION_DESIGN.value]["allowed_tools"] == [
        "read_file",
        "glob",
        "grep",
    ]
    assert definition.stage_contracts[StageType.CODE_GENERATION.value]["allowed_tools"] == [
        "read_file",
        "glob",
        "grep",
        "write_file",
        "edit_file",
    ]
    assert definition.stage_contracts[
        StageType.TEST_GENERATION_EXECUTION.value
    ]["allowed_tools"] == [
        "read_file",
        "glob",
        "grep",
        "write_file",
        "edit_file",
        "bash",
    ]
    assert definition.stage_contracts[StageType.CODE_REVIEW.value]["allowed_tools"] == [
        "read_file",
        "glob",
        "grep",
    ]
    assert definition.stage_contracts[
        StageType.DELIVERY_INTEGRATION.value
    ]["allowed_tools"] == [
        "read_delivery_snapshot",
        "prepare_branch",
        "create_commit",
        "push_branch",
        "create_code_review_request",
    ]
    code_review_contract = definition.stage_contracts[StageType.CODE_REVIEW.value]
    assert (
        code_review_contract["runtime_limits"]["runtime_limit_snapshot_ref"]
        == "runtime-limit-snapshot-run-graph-1"
    )
    assert code_review_contract["runtime_limits"]["max_auto_regression_retries"] == 2
    assert code_review_contract["runtime_limits"]["max_react_iterations_per_stage"] == 30
    assert code_review_contract["runtime_limits"]["max_tool_calls_per_stage"] == 80
    assert (
        code_review_contract["runtime_limits"]["skip_high_risk_tool_confirmations"]
        is False
    )
    assert definition.stage_contracts[StageType.REQUIREMENT_ANALYSIS.value][
        "stage_responsibility"
    ] == "Understand the requirement, resolve scope ambiguity, and produce the requirement analysis artifact."
    assert definition.stage_contracts[StageType.SOLUTION_DESIGN.value][
        "stage_responsibility"
    ] == "Design the solution, run internal solution validation, and prepare the approval-ready solution design artifact."
    assert definition.stage_contracts[StageType.CODE_GENERATION.value][
        "stage_responsibility"
    ] == "Implement the approved solution changes and produce the code generation artifact."
    assert definition.stage_contracts[StageType.TEST_GENERATION_EXECUTION.value][
        "stage_responsibility"
    ] == "Create and execute verification coverage, then record the test generation and execution artifact."
    assert definition.stage_contracts[StageType.CODE_REVIEW.value][
        "stage_responsibility"
    ] == "Review the implementation result, decide approval versus regression, and produce the code review artifact."
    assert definition.stage_contracts[StageType.DELIVERY_INTEGRATION.value][
        "stage_responsibility"
    ] == "Assemble the delivery record and route delivery through the configured integration path."


def test_compile_carries_template_skip_high_risk_confirmation_policy() -> None:
    from backend.app.services.graph_compiler import GraphCompiler

    definition = GraphCompiler().compile(
        template_snapshot=build_template_snapshot(
            skip_high_risk_tool_confirmations=True
        ),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    for contract in definition.stage_contracts.values():
        assert (
            contract["runtime_limits"]["skip_high_risk_tool_confirmations"]
            is True
        )


def test_compile_rejects_template_and_runtime_limit_run_id_mismatch() -> None:
    from backend.app.services.graph_compiler import GraphCompiler, GraphCompilerError

    with pytest.raises(GraphCompilerError) as error:
        GraphCompiler().compile(
            template_snapshot=build_template_snapshot(run_id="run-template"),
            runtime_limit_snapshot=build_runtime_limit_snapshot(run_id="run-runtime"),
        )

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert "run_id" in error.value.message


def test_compile_rejects_non_fixed_stage_sequence() -> None:
    from backend.app.services.graph_compiler import GraphCompiler, GraphCompilerError

    invalid_template = build_template_snapshot().model_copy(
        update={
            "fixed_stage_sequence": (
                StageType.REQUIREMENT_ANALYSIS,
                StageType.CODE_GENERATION,
                StageType.SOLUTION_DESIGN,
                StageType.TEST_GENERATION_EXECUTION,
                StageType.CODE_REVIEW,
                StageType.DELIVERY_INTEGRATION,
            ),
            "stage_role_bindings": (
                StageRoleSnapshot(
                    stage_type=StageType.REQUIREMENT_ANALYSIS,
                    role_id="role-requirement_analysis",
                    system_prompt="prompt:requirement_analysis",
                    provider_id="provider-alpha",
                ),
                StageRoleSnapshot(
                    stage_type=StageType.CODE_GENERATION,
                    role_id="role-code_generation",
                    system_prompt="prompt:code_generation",
                    provider_id="provider-alpha",
                ),
                StageRoleSnapshot(
                    stage_type=StageType.SOLUTION_DESIGN,
                    role_id="role-solution_design",
                    system_prompt="prompt:solution_design",
                    provider_id="provider-alpha",
                ),
                StageRoleSnapshot(
                    stage_type=StageType.TEST_GENERATION_EXECUTION,
                    role_id="role-test_generation_execution",
                    system_prompt="prompt:test_generation_execution",
                    provider_id="provider-alpha",
                ),
                StageRoleSnapshot(
                    stage_type=StageType.CODE_REVIEW,
                    role_id="role-code_review",
                    system_prompt="prompt:code_review",
                    provider_id="provider-alpha",
                ),
                StageRoleSnapshot(
                    stage_type=StageType.DELIVERY_INTEGRATION,
                    role_id="role-delivery_integration",
                    system_prompt="prompt:delivery_integration",
                    provider_id="provider-alpha",
                ),
            ),
        }
    )

    with pytest.raises(GraphCompilerError) as error:
        GraphCompiler().compile(
            template_snapshot=invalid_template,
            runtime_limit_snapshot=build_runtime_limit_snapshot(),
        )

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert "fixed_stage_sequence" in error.value.message


def test_compile_rejects_retry_setting_drift_between_template_and_runtime_limit() -> None:
    from backend.app.services.graph_compiler import GraphCompiler, GraphCompilerError

    mismatched_runtime_limit_snapshot = build_runtime_limit_snapshot().model_copy(
        update={
            "agent_limits": build_runtime_limit_snapshot().agent_limits.model_copy(
                update={"max_auto_regression_retries": 1}
            )
        }
    )

    with pytest.raises(GraphCompilerError) as error:
        GraphCompiler().compile(
            template_snapshot=build_template_snapshot(),
            runtime_limit_snapshot=mismatched_runtime_limit_snapshot,
        )

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert "max_auto_regression_retries" in error.value.message


@pytest.mark.parametrize(
    ("field_name", "mismatched_value"),
    [
        ("max_react_iterations_per_stage", 29),
        ("max_tool_calls_per_stage", 79),
    ],
)
def test_compile_rejects_template_runtime_limit_drift_for_template_overrides(
    field_name: str,
    mismatched_value: int,
) -> None:
    from backend.app.services.graph_compiler import GraphCompiler, GraphCompilerError

    mismatched_runtime_limit_snapshot = build_runtime_limit_snapshot().model_copy(
        update={
            "agent_limits": build_runtime_limit_snapshot().agent_limits.model_copy(
                update={field_name: mismatched_value}
            )
        }
    )

    with pytest.raises(GraphCompilerError) as error:
        GraphCompiler().compile(
            template_snapshot=build_template_snapshot(),
            runtime_limit_snapshot=mismatched_runtime_limit_snapshot,
        )

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert field_name in error.value.message


def test_compile_emits_log_summary_for_success_and_failure() -> None:
    from backend.app.services.graph_compiler import GraphCompiler, GraphCompilerError

    records: list[dict[str, object]] = []

    def record(summary: dict[str, object]) -> None:
        records.append(summary)

    compiler = GraphCompiler(now=lambda: NOW, log_summary_recorder=record)

    definition = compiler.compile(
        template_snapshot=build_template_snapshot(),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    assert definition.graph_definition_id == "graph-definition-run-graph-1"

    with pytest.raises(GraphCompilerError):
        compiler.compile(
            template_snapshot=build_template_snapshot(run_id="run-template"),
            runtime_limit_snapshot=build_runtime_limit_snapshot(run_id="run-runtime"),
        )

    assert records[0] == {
        "category": "runtime",
        "status": "succeeded",
        "run_id": "run-graph-1",
        "graph_definition_id": "graph-definition-run-graph-1",
    }
    assert records[1]["category"] == "runtime"
    assert records[1]["status"] == "failed"
    assert records[1]["run_id"] == "run-runtime"
    assert records[1]["reason"] == "run_id_mismatch"
    assert records[1]["error_code"] == ErrorCode.VALIDATION_ERROR.value


def test_compile_ignores_log_summary_recorder_failure_on_success() -> None:
    from backend.app.services.graph_compiler import GraphCompiler

    def record(_: dict[str, object]) -> None:
        raise RuntimeError("log sink unavailable")

    definition = GraphCompiler(log_summary_recorder=record).compile(
        template_snapshot=build_template_snapshot(),
        runtime_limit_snapshot=build_runtime_limit_snapshot(),
    )

    assert definition.run_id == "run-graph-1"


def test_compile_preserves_validation_error_when_log_summary_recorder_fails() -> None:
    from backend.app.services.graph_compiler import GraphCompiler, GraphCompilerError

    def record(_: dict[str, object]) -> None:
        raise RuntimeError("log sink unavailable")

    with pytest.raises(GraphCompilerError) as error:
        GraphCompiler(log_summary_recorder=record).compile(
            template_snapshot=build_template_snapshot(run_id="run-template"),
            runtime_limit_snapshot=build_runtime_limit_snapshot(run_id="run-runtime"),
        )

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert "run_id" in error.value.message
