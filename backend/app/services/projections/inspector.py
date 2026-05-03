from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ApprovalRequestModel,
    PipelineRunModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import StageType
from backend.app.schemas.feed import ExecutionNodeProjection, ProviderCallStageItem
from backend.app.schemas.inspector import InspectorSection, StageInspectorProjection
from backend.app.schemas.metrics import MetricSet
from backend.app.schemas.run import (
    SolutionDesignArtifactRead,
    SolutionImplementationPlanRead,
)
from backend.app.services.events import EventStore


EXECUTION_NODE_ADAPTER = TypeAdapter(ExecutionNodeProjection)
STAGE_INSPECTOR_NOT_FOUND_MESSAGE = "Stage inspector was not found."


class InspectorProjectionServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class InspectorProjectionService:
    def __init__(
        self,
        control_session: Session,
        runtime_session: Session,
        event_session: Session,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_store = EventStore(event_session)

    def get_stage_inspector(self, stage_run_id: str) -> StageInspectorProjection:
        stage, run = self._get_visible_stage_context(stage_run_id)
        artifacts = self._stage_artifacts(stage)
        stage_nodes = self._stage_nodes(run, stage)
        tool_confirmations = self._tool_confirmations(stage)
        approval_requests = self._approval_requests(stage)
        approval_decisions = self._approval_decisions(run, approval_requests)
        solution_artifacts = (
            self._solution_design_artifacts(artifacts)
            if stage.stage_type is StageType.SOLUTION_DESIGN
            else []
        )
        implementation_plan = (
            self._implementation_plan(artifacts, solution_artifacts)
            if stage.stage_type is StageType.SOLUTION_DESIGN
            else None
        )
        provider_retry_trace_refs = self._provider_retry_trace_refs(
            artifacts,
            stage_nodes,
        )
        provider_circuit_breaker_trace_refs = (
            self._provider_circuit_breaker_trace_refs(artifacts, stage_nodes)
        )
        tool_confirmation_trace_refs = self._tool_confirmation_trace_refs(
            artifacts,
            tool_confirmations,
        )
        approval_result_refs = [decision.decision_id for decision in approval_decisions]

        return StageInspectorProjection(
            stage_run_id=stage.stage_run_id,
            run_id=run.run_id,
            stage_type=stage.stage_type,
            status=stage.status,
            attempt_index=stage.attempt_index,
            started_at=self._projection_datetime(stage.started_at),
            ended_at=self._projection_datetime(stage.ended_at),
            identity=self.build_stage_identity(stage, run),
            input=self._build_input_section(stage, artifacts),
            process=self._build_process_section(
                artifacts,
                stage_nodes,
                tool_confirmations,
                provider_retry_trace_refs=provider_retry_trace_refs,
                provider_circuit_breaker_trace_refs=provider_circuit_breaker_trace_refs,
                tool_confirmation_trace_refs=tool_confirmation_trace_refs,
            ),
            output=self._build_output_section(
                stage,
                artifacts,
                implementation_plan,
            ),
            artifacts=self._build_artifacts_section(
                artifacts,
                solution_artifacts,
                approval_requests,
                approval_decisions,
            ),
            metrics=self.build_metric_section(stage, artifacts, stage_nodes),
            implementation_plan=implementation_plan,
            tool_confirmation_trace_refs=tool_confirmation_trace_refs,
            provider_retry_trace_refs=provider_retry_trace_refs,
            provider_circuit_breaker_trace_refs=provider_circuit_breaker_trace_refs,
            approval_result_refs=approval_result_refs,
        )

    def build_stage_identity(
        self,
        stage: StageRunModel,
        run: PipelineRunModel,
    ) -> InspectorSection:
        return InspectorSection(
            title="identity",
            records={
                "stage_run_id": stage.stage_run_id,
                "run_id": run.run_id,
                "stage_type": stage.stage_type.value,
                "status": stage.status.value,
                "attempt_index": stage.attempt_index,
                "run_attempt_index": run.attempt_index,
                "run_status": run.status.value,
                "trigger_source": run.trigger_source.value,
                "started_at": self._projection_datetime(stage.started_at),
                "ended_at": self._projection_datetime(stage.ended_at),
                "input_ref": stage.input_ref,
                "output_ref": stage.output_ref,
                "summary": stage.summary,
            },
            stable_refs=self._unique_strings([stage.stage_run_id, run.run_id]),
        )

    def build_metric_section(
        self,
        stage: StageRunModel,
        artifacts: Sequence[StageArtifactModel],
        stage_nodes: Sequence[ExecutionNodeProjection],
    ) -> MetricSet:
        metric_values: dict[str, int] = {}
        allowed_fields = set(MetricSet.model_fields)
        for node in stage_nodes:
            self._merge_known_metrics(metric_values, node.metrics, allowed_fields)
        for artifact in artifacts:
            self._merge_known_metrics(metric_values, artifact.metrics, allowed_fields)
        metric_values["attempt_index"] = stage.attempt_index
        if "duration_ms" not in metric_values and stage.ended_at is not None:
            duration = self._projection_datetime(stage.ended_at) - self._projection_datetime(
                stage.started_at
            )
            metric_values["duration_ms"] = max(
                0,
                int(duration.total_seconds() * 1000),
            )
        return MetricSet.model_validate(metric_values)

    def _get_visible_stage_context(
        self,
        stage_run_id: str,
    ) -> tuple[StageRunModel, PipelineRunModel]:
        stage = self._runtime_session.get(StageRunModel, stage_run_id)
        if stage is None:
            self._raise_not_found()
        run = self._runtime_session.get(PipelineRunModel, stage.run_id)
        if run is None:
            self._raise_not_found()
        session = self._control_session.get(SessionModel, run.session_id)
        if session is None or not session.is_visible:
            self._raise_not_found()
        project = self._control_session.get(ProjectModel, run.project_id)
        if project is None or not project.is_visible:
            self._raise_not_found()
        if session.project_id != run.project_id:
            self._raise_not_found()
        return stage, run

    def _stage_artifacts(
        self,
        stage: StageRunModel,
    ) -> list[StageArtifactModel]:
        statement = (
            select(StageArtifactModel)
            .where(
                StageArtifactModel.run_id == stage.run_id,
                StageArtifactModel.stage_run_id == stage.stage_run_id,
            )
            .order_by(
                StageArtifactModel.created_at.asc(),
                StageArtifactModel.artifact_id.asc(),
            )
        )
        return list(self._runtime_session.execute(statement).scalars().all())

    def _stage_nodes(
        self,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> list[ExecutionNodeProjection]:
        nodes: list[ExecutionNodeProjection] = []
        for event in self._event_store.list_for_session(run.session_id):
            if event.run_id != run.run_id or event.stage_run_id != stage.stage_run_id:
                continue
            stage_node = event.payload.get("stage_node")
            if stage_node is None:
                continue
            node = EXECUTION_NODE_ADAPTER.validate_python(stage_node)
            if node.run_id == run.run_id and node.stage_run_id == stage.stage_run_id:
                nodes.append(node)
        return nodes

    def _tool_confirmations(
        self,
        stage: StageRunModel,
    ) -> list[ToolConfirmationRequestModel]:
        statement = (
            select(ToolConfirmationRequestModel)
            .where(
                ToolConfirmationRequestModel.run_id == stage.run_id,
                ToolConfirmationRequestModel.stage_run_id == stage.stage_run_id,
            )
            .order_by(
                ToolConfirmationRequestModel.requested_at.asc(),
                ToolConfirmationRequestModel.tool_confirmation_id.asc(),
            )
        )
        return list(self._runtime_session.execute(statement).scalars().all())

    def _approval_requests(
        self,
        stage: StageRunModel,
    ) -> list[ApprovalRequestModel]:
        statement = (
            select(ApprovalRequestModel)
            .where(
                ApprovalRequestModel.run_id == stage.run_id,
                ApprovalRequestModel.stage_run_id == stage.stage_run_id,
            )
            .order_by(
                ApprovalRequestModel.requested_at.asc(),
                ApprovalRequestModel.approval_id.asc(),
            )
        )
        return list(self._runtime_session.execute(statement).scalars().all())

    def _approval_decisions(
        self,
        run: PipelineRunModel,
        approval_requests: Sequence[ApprovalRequestModel],
    ) -> list[ApprovalDecisionModel]:
        approval_ids = [request.approval_id for request in approval_requests]
        if not approval_ids:
            return []
        statement = (
            select(ApprovalDecisionModel)
            .where(
                ApprovalDecisionModel.run_id == run.run_id,
                ApprovalDecisionModel.approval_id.in_(approval_ids),
            )
            .order_by(
                ApprovalDecisionModel.created_at.asc(),
                ApprovalDecisionModel.decision_id.asc(),
            )
        )
        return list(self._runtime_session.execute(statement).scalars().all())

    def _build_input_section(
        self,
        stage: StageRunModel,
        artifacts: Sequence[StageArtifactModel],
    ) -> InspectorSection:
        input_snapshots = [
            process["input_snapshot"]
            for process in self._artifact_processes(artifacts)
            if "input_snapshot" in process
        ]
        context_refs: list[str] = []
        for process in self._artifact_processes(artifacts):
            self._extend_unique(
                context_refs,
                self._string_list(process.get("context_refs")),
            )
        records: dict[str, Any] = {
            "input_ref": stage.input_ref,
            "input_snapshot": (
                self._scrub_raw_graph_state(input_snapshots[-1])
                if input_snapshots
                else None
            ),
            "context_refs": context_refs,
        }
        return InspectorSection(
            title="input",
            records=records,
            stable_refs=self._unique_strings([stage.input_ref, *context_refs]),
        )

    def _build_process_section(
        self,
        artifacts: Sequence[StageArtifactModel],
        stage_nodes: Sequence[ExecutionNodeProjection],
        tool_confirmations: Sequence[ToolConfirmationRequestModel],
        *,
        provider_retry_trace_refs: Sequence[str],
        provider_circuit_breaker_trace_refs: Sequence[str],
        tool_confirmation_trace_refs: Sequence[str],
    ) -> InspectorSection:
        log_refs = self._log_refs(artifacts)
        records = {
            "provider_calls": self._provider_call_records(stage_nodes),
            "provider_retry_trace_refs": list(provider_retry_trace_refs),
            "provider_circuit_breaker_trace_refs": list(
                provider_circuit_breaker_trace_refs
            ),
            "tool_confirmation_trace_refs": list(tool_confirmation_trace_refs),
            "tool_confirmation_requests": [
                {
                    "tool_confirmation_id": confirmation.tool_confirmation_id,
                    "status": confirmation.status.value,
                    "confirmation_object_ref": confirmation.confirmation_object_ref,
                    "process_ref": confirmation.process_ref,
                }
                for confirmation in tool_confirmations
            ],
        }
        return InspectorSection(
            title="process",
            records=records,
            stable_refs=self._unique_strings(
                [
                    *provider_retry_trace_refs,
                    *provider_circuit_breaker_trace_refs,
                    *tool_confirmation_trace_refs,
                ]
            ),
            log_refs=log_refs,
        )

    def _build_output_section(
        self,
        stage: StageRunModel,
        artifacts: Sequence[StageArtifactModel],
        implementation_plan: SolutionImplementationPlanRead | None,
    ) -> InspectorSection:
        output_snapshots = [
            process["output_snapshot"]
            for process in self._artifact_processes(artifacts)
            if "output_snapshot" in process
        ]
        records: dict[str, Any] = {
            "output_ref": stage.output_ref,
            "output_snapshot": (
                self._scrub_raw_graph_state(output_snapshots[-1])
                if output_snapshots
                else None
            ),
            "implementation_plan_id": (
                implementation_plan.plan_id if implementation_plan is not None else None
            ),
        }
        return InspectorSection(
            title="output",
            records=records,
            stable_refs=self._unique_strings([stage.output_ref]),
        )

    def _build_artifacts_section(
        self,
        artifacts: Sequence[StageArtifactModel],
        solution_artifacts: Sequence[SolutionDesignArtifactRead],
        approval_requests: Sequence[ApprovalRequestModel],
        approval_decisions: Sequence[ApprovalDecisionModel],
    ) -> InspectorSection:
        artifact_refs = [artifact.artifact_id for artifact in artifacts]
        payload_refs = [artifact.payload_ref for artifact in artifacts]
        records: dict[str, Any] = {
            "artifact_refs": artifact_refs,
            "payload_refs": payload_refs,
            "artifact_types": [artifact.artifact_type for artifact in artifacts],
            "approval_requests": [
                {
                    "approval_id": request.approval_id,
                    "approval_type": request.approval_type.value,
                    "status": request.status.value,
                    "payload_ref": request.payload_ref,
                }
                for request in approval_requests
            ],
            "approval_decisions": [
                {
                    "decision_id": decision.decision_id,
                    "approval_id": decision.approval_id,
                    "decision": decision.decision.value,
                }
                for decision in approval_decisions
            ],
        }
        if solution_artifacts:
            records["solution_design_artifact"] = self._scrub_raw_graph_state(
                solution_artifacts[-1].model_dump(mode="json")
            )
        return InspectorSection(
            title="artifacts",
            records=records,
            stable_refs=self._unique_strings(
                [
                    *artifact_refs,
                    *payload_refs,
                    *[request.approval_id for request in approval_requests],
                    *[decision.decision_id for decision in approval_decisions],
                ]
            ),
        )

    def _solution_design_artifacts(
        self,
        artifacts: Sequence[StageArtifactModel],
    ) -> list[SolutionDesignArtifactRead]:
        parsed: list[SolutionDesignArtifactRead] = []
        for process in self._artifact_processes(artifacts):
            value = process.get("solution_design_artifact")
            if value is None:
                continue
            try:
                parsed.append(SolutionDesignArtifactRead.model_validate(value))
            except ValidationError:
                continue
        return parsed

    def _implementation_plan(
        self,
        artifacts: Sequence[StageArtifactModel],
        solution_artifacts: Sequence[SolutionDesignArtifactRead],
    ) -> SolutionImplementationPlanRead | None:
        if solution_artifacts:
            return solution_artifacts[-1].implementation_plan
        for process in self._artifact_processes(artifacts):
            for key in ("implementation_plan", "solution_implementation_plan"):
                value = process.get(key)
                if value is None:
                    continue
                try:
                    return SolutionImplementationPlanRead.model_validate(value)
                except ValidationError:
                    continue
        return None

    def _provider_call_records(
        self,
        stage_nodes: Sequence[ExecutionNodeProjection],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for node in stage_nodes:
            for item in node.items:
                if isinstance(item, ProviderCallStageItem):
                    records.append(item.model_dump(mode="json"))
        return records

    def _provider_retry_trace_refs(
        self,
        artifacts: Sequence[StageArtifactModel],
        stage_nodes: Sequence[ExecutionNodeProjection],
    ) -> list[str]:
        refs: list[str] = []
        for process in self._artifact_processes(artifacts):
            self._extend_unique(refs, self._string_list(process.get("provider_retry_trace_ref")))
            self._extend_unique(refs, self._string_list(process.get("provider_retry_trace_refs")))
        for provider_call in self._provider_call_records(stage_nodes):
            is_retry_related = provider_call.get("status") == "retrying" or provider_call.get(
                "retry_attempt", 0
            ) > 0
            if is_retry_related:
                self._extend_unique(
                    refs,
                    self._string_list(provider_call.get("process_ref")),
                )
                self._extend_unique(
                    refs,
                    [
                        value
                        for value in self._string_list(
                            provider_call.get("artifact_refs")
                        )
                        if "retry" in value
                    ],
                )
        return refs

    def _provider_circuit_breaker_trace_refs(
        self,
        artifacts: Sequence[StageArtifactModel],
        stage_nodes: Sequence[ExecutionNodeProjection],
    ) -> list[str]:
        refs: list[str] = []
        for process in self._artifact_processes(artifacts):
            self._extend_unique(
                refs,
                self._string_list(process.get("provider_circuit_breaker_trace_ref")),
            )
            self._extend_unique(
                refs,
                self._string_list(process.get("provider_circuit_breaker_trace_refs")),
            )
        for provider_call in self._provider_call_records(stage_nodes):
            self._extend_unique(
                refs,
                [
                    value
                    for value in self._string_list(provider_call.get("process_ref"))
                    if "circuit" in value
                ],
            )
            self._extend_unique(
                refs,
                [
                    value
                    for value in self._string_list(provider_call.get("artifact_refs"))
                    if "circuit" in value
                ],
            )
        return refs

    def _tool_confirmation_trace_refs(
        self,
        artifacts: Sequence[StageArtifactModel],
        tool_confirmations: Sequence[ToolConfirmationRequestModel],
    ) -> list[str]:
        refs: list[str] = []
        self._extend_unique(
            refs,
            [confirmation.process_ref for confirmation in tool_confirmations],
        )
        for process in self._artifact_processes(artifacts):
            self._extend_unique(
                refs,
                self._string_list(process.get("tool_confirmation_trace_ref")),
            )
            self._extend_unique(
                refs,
                self._string_list(process.get("tool_confirmation_trace_refs")),
            )
        return refs

    def _log_refs(
        self,
        artifacts: Sequence[StageArtifactModel],
    ) -> list[str]:
        refs: list[str] = []
        for process in self._artifact_processes(artifacts):
            self._extend_unique(refs, self._string_list(process.get("log_ref")))
            self._extend_unique(refs, self._string_list(process.get("log_refs")))
        return refs

    @staticmethod
    def _artifact_processes(
        artifacts: Sequence[StageArtifactModel],
    ) -> list[Mapping[str, Any]]:
        return [
            artifact.process
            for artifact in artifacts
            if isinstance(artifact.process, Mapping)
        ]

    @staticmethod
    def _merge_known_metrics(
        target: dict[str, int],
        source: Mapping[str, Any],
        allowed_fields: set[str],
    ) -> None:
        for key, value in source.items():
            if key in allowed_fields and isinstance(value, int) and not isinstance(value, bool):
                target[key] = value

    @classmethod
    def _scrub_raw_graph_state(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: cls._scrub_raw_graph_state(item)
                for key, item in value.items()
                if key not in {"graph_thread_ref", "graph_thread_id"}
            }
        if isinstance(value, list):
            return [cls._scrub_raw_graph_state(item) for item in value]
        return value

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if isinstance(value, str) and value:
            return [value]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [item for item in value if isinstance(item, str) and item]
        return []

    @classmethod
    def _unique_strings(cls, values: Sequence[str | None]) -> list[str]:
        result: list[str] = []
        cls._extend_unique(result, values)
        return result

    @staticmethod
    def _extend_unique(
        target: list[str],
        values: Sequence[str | None],
    ) -> None:
        for value in values:
            if isinstance(value, str) and value and value not in target:
                target.append(value)

    @staticmethod
    def _projection_datetime(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)

    @staticmethod
    def _raise_not_found() -> None:
        raise InspectorProjectionServiceError(
            ErrorCode.NOT_FOUND,
            STAGE_INSPECTOR_NOT_FOUND_MESSAGE,
            404,
        )


__all__ = [
    "InspectorProjectionService",
    "InspectorProjectionServiceError",
]
