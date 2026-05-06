from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.graph_definition import (
    GraphDefinition,
    build_fixed_stage_sequence,
    build_interrupt_policy,
    build_solution_design_node_group,
    stage_allowed_tools,
)
from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshot
from backend.app.domain.template_snapshot import TemplateSnapshot


class GraphCompilerError(ValueError):
    def __init__(self, error_code: ErrorCode, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class GraphCompiler:
    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        log_summary_recorder: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._log_summary_recorder = log_summary_recorder

    def compile(
        self,
        *,
        template_snapshot: TemplateSnapshot,
        runtime_limit_snapshot: RuntimeLimitSnapshot,
    ) -> GraphDefinition:
        if template_snapshot.run_id != runtime_limit_snapshot.run_id:
            self._record(
                status="failed",
                run_id=runtime_limit_snapshot.run_id,
                error_code=ErrorCode.VALIDATION_ERROR.value,
                reason="run_id_mismatch",
            )
            raise GraphCompilerError(
                ErrorCode.VALIDATION_ERROR,
                "TemplateSnapshot and RuntimeLimitSnapshot run_id must match.",
            )

        if tuple(template_snapshot.fixed_stage_sequence) != build_fixed_stage_sequence():
            self._record(
                status="failed",
                run_id=template_snapshot.run_id,
                error_code=ErrorCode.VALIDATION_ERROR.value,
                reason="fixed_stage_sequence_mismatch",
            )
            raise GraphCompilerError(
                ErrorCode.VALIDATION_ERROR,
                "TemplateSnapshot.fixed_stage_sequence must match the Function One fixed stage order.",
            )

        for field_name in (
            "max_auto_regression_retries",
            "max_react_iterations_per_stage",
            "max_tool_calls_per_stage",
        ):
            template_value = getattr(template_snapshot, field_name)
            runtime_value = getattr(runtime_limit_snapshot.agent_limits, field_name)
            if template_value == runtime_value:
                continue
            self._record(
                status="failed",
                run_id=template_snapshot.run_id,
                error_code=ErrorCode.VALIDATION_ERROR.value,
                reason=f"{field_name}_mismatch",
            )
            raise GraphCompilerError(
                ErrorCode.VALIDATION_ERROR,
                f"TemplateSnapshot.{field_name} must match "
                f"RuntimeLimitSnapshot.agent_limits.{field_name}.",
            )

        definition = GraphDefinition(
            graph_definition_id=_graph_definition_id(template_snapshot.run_id),
            run_id=template_snapshot.run_id,
            template_snapshot_ref=template_snapshot.snapshot_ref,
            runtime_limit_snapshot_ref=runtime_limit_snapshot.snapshot_id,
            runtime_limit_source_config_version=runtime_limit_snapshot.source_config_version,
            stage_nodes=tuple(
                self._build_stage_nodes(template_snapshot.auto_regression_enabled)
            ),
            stage_contracts=self._build_stage_contracts(
                runtime_limit_snapshot,
                template_snapshot=template_snapshot,
            ),
            interrupt_policy=self._build_interrupt_policy(),
            retry_policy=self._build_retry_policy(
                template_snapshot,
                runtime_limit_snapshot,
            ),
            delivery_routing_policy=self._build_delivery_routing_policy(),
            source_node_group_map=self._build_source_node_group_map(),
            created_at=self._now(),
        )
        self._record(
            status="succeeded",
            run_id=definition.run_id,
            graph_definition_id=definition.graph_definition_id,
        )
        return definition

    def _build_stage_nodes(self, auto_regression_enabled: bool) -> list[dict[str, object]]:
        code_review_node: dict[str, object] = {
            "node_key": "code_review",
            "stage_type": "code_review",
            "node_groups": ["code_review"],
            "entry_node_key": "code_review",
            "success_node_key": "code_review.approval_gate",
            "conditional_routes": [],
        }
        if auto_regression_enabled:
            code_review_node["conditional_routes"] = [
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
        return [
            {
                "node_key": "requirement_analysis",
                "stage_type": "requirement_analysis",
                "node_groups": ["requirement_analysis"],
                "entry_node_key": "requirement_analysis",
                "success_node_key": "solution_design.authoring",
            },
            build_solution_design_node_group(),
            {
                "node_key": "code_generation",
                "stage_type": "code_generation",
                "node_groups": ["code_generation"],
                "entry_node_key": "code_generation",
                "success_node_key": "test_generation_execution",
            },
            {
                "node_key": "test_generation_execution",
                "stage_type": "test_generation_execution",
                "node_groups": ["test_generation_execution"],
                "entry_node_key": "test_generation_execution",
                "success_node_key": "code_review",
            },
            code_review_node,
            {
                "node_key": "delivery_integration",
                "stage_type": "delivery_integration",
                "node_groups": ["delivery_integration"],
                "entry_node_key": "delivery_integration",
                "success_node_key": "delivery_complete",
            },
        ]

    def _build_stage_contracts(
        self,
        runtime_limit_snapshot: RuntimeLimitSnapshot,
        *,
        template_snapshot: TemplateSnapshot,
    ) -> dict[str, dict[str, object]]:
        def build_runtime_limits() -> dict[str, object]:
            return {
                "runtime_limit_snapshot_ref": runtime_limit_snapshot.snapshot_id,
                "source_config_version": runtime_limit_snapshot.source_config_version,
                "max_react_iterations_per_stage": runtime_limit_snapshot.agent_limits.max_react_iterations_per_stage,
                "max_tool_calls_per_stage": runtime_limit_snapshot.agent_limits.max_tool_calls_per_stage,
                "max_structured_output_repair_attempts": runtime_limit_snapshot.agent_limits.max_structured_output_repair_attempts,
                "max_auto_regression_retries": runtime_limit_snapshot.agent_limits.max_auto_regression_retries,
                "max_clarification_rounds": runtime_limit_snapshot.agent_limits.max_clarification_rounds,
                "max_no_progress_iterations": runtime_limit_snapshot.agent_limits.max_no_progress_iterations,
                "skip_high_risk_tool_confirmations": template_snapshot.skip_high_risk_tool_confirmations,
            }

        allowed_tools = stage_allowed_tools()
        fixed_stage_sequence = build_fixed_stage_sequence()
        return {
            "requirement_analysis": {
                "stage_responsibility": (
                    "Understand the requirement, resolve scope ambiguity, and "
                    "produce the requirement analysis artifact."
                ),
                "input_contract": "RequirementAnalysisInput",
                "output_contract": "RequirementAnalysisArtifact",
                "structured_artifact_required": "RequirementAnalysisArtifact",
                "allowed_tools": list(allowed_tools[fixed_stage_sequence[0]]),
                "runtime_limits": build_runtime_limits(),
            },
            "solution_design": {
                "stage_responsibility": (
                    "Design the solution, run internal solution validation, and "
                    "prepare the approval-ready solution design artifact."
                ),
                "input_contract": "SolutionDesignInput",
                "output_contract": "SolutionDesignArtifact",
                "structured_artifact_required": "SolutionDesignArtifact",
                "allowed_tools": list(allowed_tools[fixed_stage_sequence[1]]),
                "runtime_limits": build_runtime_limits(),
                "validation_pass": {
                    "node_group": "solution_validation",
                    "reenter_node_group": "solution_design_authoring",
                },
            },
            "code_generation": {
                "stage_responsibility": (
                    "Implement the approved solution changes and produce the code "
                    "generation artifact."
                ),
                "input_contract": "CodeGenerationInput",
                "output_contract": "CodeGenerationArtifact",
                "structured_artifact_required": "CodeGenerationArtifact",
                "allowed_tools": list(allowed_tools[fixed_stage_sequence[2]]),
                "runtime_limits": build_runtime_limits(),
            },
            "test_generation_execution": {
                "stage_responsibility": (
                    "Create and execute verification coverage, then record the "
                    "test generation and execution artifact."
                ),
                "input_contract": "TestGenerationExecutionInput",
                "output_contract": "TestGenerationExecutionArtifact",
                "structured_artifact_required": "TestGenerationExecutionArtifact",
                "allowed_tools": list(allowed_tools[fixed_stage_sequence[3]]),
                "runtime_limits": build_runtime_limits(),
            },
            "code_review": {
                "stage_responsibility": (
                    "Review the implementation result, decide approval versus "
                    "regression, and produce the code review artifact."
                ),
                "input_contract": "CodeReviewInput",
                "output_contract": "CodeReviewArtifact",
                "structured_artifact_required": "CodeReviewArtifact",
                "allowed_tools": list(allowed_tools[fixed_stage_sequence[4]]),
                "runtime_limits": build_runtime_limits(),
            },
            "delivery_integration": {
                "stage_responsibility": (
                    "Assemble the delivery record and route delivery through the "
                    "configured integration path."
                ),
                "input_contract": "DeliveryIntegrationInput",
                "output_contract": "DeliveryRecord",
                "structured_artifact_required": "DeliveryRecord",
                "allowed_tools": list(allowed_tools[fixed_stage_sequence[5]]),
                "runtime_limits": build_runtime_limits(),
            },
        }

    def _build_interrupt_policy(self) -> dict[str, object]:
        return build_interrupt_policy()

    def _build_retry_policy(
        self,
        template_snapshot: TemplateSnapshot,
        runtime_limit_snapshot: RuntimeLimitSnapshot,
    ) -> dict[str, object]:
        return {
            "max_auto_regression_retries": template_snapshot.max_auto_regression_retries,
            "runtime_limit_snapshot_ref": runtime_limit_snapshot.snapshot_id,
            "auto_regression_enabled": template_snapshot.auto_regression_enabled,
            "return_stage_on_review_regression": "code_generation",
        }

    def _build_delivery_routing_policy(self) -> dict[str, object]:
        return {
            "mode_routes": {
                "demo_delivery": "demo_delivery_adapter",
                "git_auto_delivery": "git_auto_delivery_adapter",
            },
            "stage": "delivery_integration",
        }

    def _build_source_node_group_map(self) -> dict[str, str]:
        return {
            "requirement_analysis": "requirement_analysis",
            "solution_design_authoring": "solution_design",
            "solution_design.authoring": "solution_design",
            "solution_validation": "solution_design",
            "solution_design.approval_gate": "solution_design",
            "code_generation": "code_generation",
            "test_generation_execution": "test_generation_execution",
            "code_review": "code_review",
            "code_review.approval_gate": "code_review",
            "delivery_integration": "delivery_integration",
            "delivery_complete": "delivery_integration",
        }

    def _record(self, **payload: object) -> None:
        if self._log_summary_recorder is None:
            return
        summary = {"category": "runtime", **payload}
        try:
            self._log_summary_recorder(summary)
        except Exception:
            return


def _graph_definition_id(run_id: str) -> str:
    candidate = f"graph-definition-{run_id}"
    if len(candidate) <= 80:
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"graph-definition-{digest}"


__all__ = [
    "GraphCompiler",
    "GraphCompilerError",
]
