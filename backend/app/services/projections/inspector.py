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
    ClarificationRecordModel,
    PipelineRunModel,
    RunControlRecordModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import StageType
from backend.app.schemas.feed import (
    ControlItemFeedEntry,
    ExecutionNodeProjection,
    ProviderCallStageItem,
)
from backend.app.schemas.inspector import (
    ControlItemInspectorProjection,
    InspectorSection,
    StageInspectorProjection,
)
from backend.app.schemas.metrics import MetricSet
from backend.app.schemas.run import (
    SolutionDesignArtifactRead,
    SolutionImplementationPlanRead,
)
from backend.app.services.events import EventStore


EXECUTION_NODE_ADAPTER = TypeAdapter(ExecutionNodeProjection)
CONTROL_ITEM_ADAPTER = TypeAdapter(ControlItemFeedEntry)
STAGE_INSPECTOR_NOT_FOUND_MESSAGE = "Stage inspector was not found."
CONTROL_ITEM_INSPECTOR_NOT_FOUND_MESSAGE = "Control item inspector was not found."


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

    def get_control_item_detail(
        self,
        control_record_id: str,
    ) -> ControlItemInspectorProjection:
        control_record, run, source_stage = self._get_visible_control_context(
            control_record_id
        )
        artifacts = self._stage_artifacts_for_control(control_record)
        control_event = self._control_event(run, control_record.control_record_id)
        stage_nodes = (
            self._stage_nodes(run, source_stage) if source_stage is not None else []
        )
        clarification = self._clarification_record(control_record)
        sections = self.build_control_item_sections(
            control_record,
            run,
            source_stage,
            artifacts,
            control_event,
            stage_nodes,
            clarification,
        )

        return ControlItemInspectorProjection(
            control_record_id=control_record.control_record_id,
            run_id=run.run_id,
            control_type=control_record.control_type,
            source_stage_type=control_record.source_stage_type,
            target_stage_type=control_record.target_stage_type,
            occurred_at=self._projection_datetime(control_record.occurred_at),
            identity=sections["identity"],
            input=sections["input"],
            process=sections["process"],
            output=sections["output"],
            artifacts=sections["artifacts"],
            metrics=sections["metrics"],
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

    def build_control_item_sections(
        self,
        control_record: RunControlRecordModel,
        run: PipelineRunModel,
        source_stage: StageRunModel | None,
        artifacts: Sequence[StageArtifactModel],
        control_event: ControlItemFeedEntry | None,
        stage_nodes: Sequence[ExecutionNodeProjection],
        clarification: ClarificationRecordModel | None,
    ) -> dict[str, InspectorSection | MetricSet]:
        artifact_processes = self._artifact_processes(artifacts)
        context_refs: list[str] = []
        control_process_trace_refs: list[str] = []
        history_attempt_refs: list[str] = []
        artifact_refs: list[str] = []
        payload_refs: list[str] = []
        artifact_types: list[str] = []

        for artifact in artifacts:
            artifact_refs.append(artifact.artifact_id)
            payload_refs.append(artifact.payload_ref)
            artifact_types.append(artifact.artifact_type)
        for process in artifact_processes:
            self._extend_unique(context_refs, self._string_list(process.get("context_refs")))
            self._extend_unique(
                control_process_trace_refs,
                self._string_list(process.get("control_process_trace_ref")),
            )
            self._extend_unique(
                control_process_trace_refs,
                self._string_list(process.get("control_process_trace_refs")),
            )
            self._extend_unique(
                control_process_trace_refs,
                self._string_list(process.get("tool_confirmation_trace_ref")),
            )
            self._extend_unique(
                history_attempt_refs,
                self._string_list(process.get("history_attempt_refs")),
            )

        newest_process = artifact_processes[-1] if artifact_processes else None
        result_snapshot = (
            self._scrub_raw_graph_state(newest_process.get("output_snapshot"))
            if newest_process is not None and "output_snapshot" in newest_process
            else None
        )
        trigger_reason = self._control_trigger_reason(
            artifact_processes,
            control_event,
            source_stage,
        )
        stage_status = self._control_stage_status(source_stage, stage_nodes)
        result_status = self._control_result_status(result_snapshot, source_stage, run)
        target_stage_type = self._control_target_stage_type(control_record, result_snapshot)
        stage_node_refs = [node.entry_id for node in stage_nodes]
        clarification_id = clarification.clarification_id if clarification is not None else None
        control_event_payload = (
            self._scrub_raw_graph_state(control_event.model_dump(mode="json"))
            if control_event is not None
            else None
        )
        metrics = self._control_metrics(artifacts)
        log_refs = self._log_refs(artifacts)

        identity = InspectorSection(
            title="identity",
            records={
                "control_record_id": control_record.control_record_id,
                "run_id": run.run_id,
                "control_type": control_record.control_type.value,
                "source_stage_type": control_record.source_stage_type.value,
                "target_stage_type": (
                    control_record.target_stage_type.value
                    if control_record.target_stage_type is not None
                    else None
                ),
                "occurred_at": self._projection_datetime(control_record.occurred_at),
                "stage_run_id": control_record.stage_run_id,
            },
            stable_refs=self._unique_strings(
                [
                    control_record.control_record_id,
                    run.run_id,
                    control_record.stage_run_id,
                ]
            ),
        )
        input_section = InspectorSection(
            title="input",
            records={
                "payload_ref": control_record.payload_ref,
                "trigger_reason": trigger_reason,
                "source_stage_summary": source_stage.summary if source_stage is not None else None,
                "clarification_question": (
                    clarification.question if clarification is not None else None
                ),
                "clarification_answer": (
                    clarification.answer if clarification is not None else None
                ),
                "context_refs": context_refs,
            },
            stable_refs=self._unique_strings(
                [
                    control_record.payload_ref,
                    clarification_id,
                    *context_refs,
                ]
            ),
        )
        process = InspectorSection(
            title="process",
            records={
                "control_event": control_event_payload,
                "control_process_trace_refs": control_process_trace_refs,
                "history_attempt_refs": history_attempt_refs,
                "stage_node_refs": stage_node_refs,
                "stage_status": stage_status,
                "graph_interrupt_ref": control_record.graph_interrupt_ref,
            },
            stable_refs=self._unique_strings(stage_node_refs),
            log_refs=log_refs,
        )
        output = InspectorSection(
            title="output",
            records={
                "target_stage_type": target_stage_type,
                "result_status": result_status,
                "result_snapshot": result_snapshot,
                "terminal_reason": None,
            },
        )
        artifacts_section = InspectorSection(
            title="artifacts",
            records={
                "artifact_refs": artifact_refs,
                "payload_refs": payload_refs,
                "artifact_types": artifact_types,
                "clarification_id": clarification_id,
            },
            stable_refs=self._unique_strings(
                [
                    clarification_id,
                    *artifact_refs,
                    *payload_refs,
                    *context_refs,
                    *self._string_list(control_record.payload_ref),
                ]
            ),
            log_refs=log_refs,
        )
        return {
            "identity": identity,
            "input": input_section,
            "process": process,
            "output": output,
            "artifacts": artifacts_section,
            "metrics": metrics,
        }

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

    def _get_visible_control_context(
        self,
        control_record_id: str,
    ) -> tuple[RunControlRecordModel, PipelineRunModel, StageRunModel | None]:
        control_record = self._runtime_session.get(RunControlRecordModel, control_record_id)
        if control_record is None:
            self._raise_control_item_not_found()
        if control_record.control_type.value == "tool_confirmation":
            self._raise_control_item_not_found()
        run = self._runtime_session.get(PipelineRunModel, control_record.run_id)
        if run is None:
            self._raise_control_item_not_found()
        session = self._control_session.get(SessionModel, run.session_id)
        if session is None or not session.is_visible:
            self._raise_control_item_not_found()
        project = self._control_session.get(ProjectModel, run.project_id)
        if project is None or not project.is_visible:
            self._raise_control_item_not_found()
        if session.project_id != run.project_id:
            self._raise_control_item_not_found()
        source_stage: StageRunModel | None = None
        if control_record.stage_run_id is not None:
            source_stage = self._runtime_session.get(StageRunModel, control_record.stage_run_id)
            if source_stage is None or source_stage.run_id != run.run_id:
                self._raise_control_item_not_found()
        return control_record, run, source_stage

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

    def _stage_artifacts_for_control(
        self,
        control_record: RunControlRecordModel,
    ) -> list[StageArtifactModel]:
        if control_record.stage_run_id is None:
            return []
        statement = (
            select(StageArtifactModel)
            .where(
                StageArtifactModel.run_id == control_record.run_id,
                StageArtifactModel.stage_run_id == control_record.stage_run_id,
                StageArtifactModel.artifact_type == "control_item_trace",
            )
            .order_by(
                StageArtifactModel.created_at.asc(),
                StageArtifactModel.artifact_id.asc(),
            )
        )
        artifacts = list(self._runtime_session.execute(statement).scalars().all())
        matched = [
            artifact
            for artifact in artifacts
            if self._artifact_matches_control_record(artifact, control_record.control_record_id)
        ]
        return matched

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
            try:
                node = EXECUTION_NODE_ADAPTER.validate_python(stage_node)
            except ValidationError:
                continue
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

    def _control_event(
        self,
        run: PipelineRunModel,
        control_record_id: str,
    ) -> ControlItemFeedEntry | None:
        matched: ControlItemFeedEntry | None = None
        for event in self._event_store.list_for_session(run.session_id):
            if event.run_id != run.run_id:
                continue
            payload = event.payload.get("control_item")
            if payload is None:
                continue
            try:
                control_item = CONTROL_ITEM_ADAPTER.validate_python(payload)
            except ValidationError:
                continue
            if control_item.control_record_id == control_record_id:
                matched = control_item
        return matched

    def _clarification_record(
        self,
        control_record: RunControlRecordModel,
    ) -> ClarificationRecordModel | None:
        if control_record.control_type.value != "clarification_wait":
            return None
        if not control_record.payload_ref:
            return None
        clarification = self._runtime_session.get(
            ClarificationRecordModel,
            control_record.payload_ref,
        )
        if clarification is None:
            return None
        if clarification.run_id != control_record.run_id:
            return None
        if (
            control_record.stage_run_id is not None
            and clarification.stage_run_id != control_record.stage_run_id
        ):
            return None
        return clarification

    def _control_metrics(
        self,
        artifacts: Sequence[StageArtifactModel],
    ) -> MetricSet:
        metric_values: dict[str, int] = {}
        allowed_fields = set(MetricSet.model_fields)
        for artifact in artifacts:
            self._merge_known_metrics(metric_values, artifact.metrics, allowed_fields)
            process_metrics = artifact.process.get("metrics")
            if isinstance(process_metrics, Mapping):
                self._merge_known_metrics(metric_values, process_metrics, allowed_fields)
        return MetricSet.model_validate(metric_values)

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
    def _artifact_matches_control_record(
        artifact: StageArtifactModel,
        control_record_id: str,
    ) -> bool:
        if not isinstance(artifact.process, Mapping):
            return False
        process_control_record_id = artifact.process.get("control_record_id")
        return process_control_record_id == control_record_id

    @staticmethod
    def _control_trigger_reason(
        artifact_processes: Sequence[Mapping[str, Any]],
        control_event: ControlItemFeedEntry | None,
        source_stage: StageRunModel | None,
    ) -> str | None:
        for process in reversed(artifact_processes):
            value = process.get("trigger_reason")
            if isinstance(value, str) and value:
                return value
        if control_event is not None:
            return control_event.summary
        if source_stage is not None:
            return source_stage.summary
        return None

    @staticmethod
    def _control_stage_status(
        source_stage: StageRunModel | None,
        stage_nodes: Sequence[ExecutionNodeProjection],
    ) -> str | None:
        if stage_nodes:
            return stage_nodes[-1].status.value
        if source_stage is not None:
            return source_stage.status.value
        return None

    @staticmethod
    def _control_target_stage_type(
        control_record: RunControlRecordModel,
        result_snapshot: Mapping[str, Any] | None,
    ) -> str | None:
        if control_record.target_stage_type is not None:
            return control_record.target_stage_type.value
        if isinstance(result_snapshot, Mapping):
            value = result_snapshot.get("next_stage_type")
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _control_result_status(
        result_snapshot: Mapping[str, Any] | None,
        source_stage: StageRunModel | None,
        run: PipelineRunModel,
    ) -> str:
        if isinstance(result_snapshot, Mapping):
            value = result_snapshot.get("result_status")
            if isinstance(value, str) and value:
                return value
        if source_stage is not None:
            return source_stage.status.value
        return run.status.value

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

    @staticmethod
    def _raise_control_item_not_found() -> None:
        raise InspectorProjectionServiceError(
            ErrorCode.NOT_FOUND,
            CONTROL_ITEM_INSPECTOR_NOT_FOUND_MESSAGE,
            404,
        )


__all__ = [
    "InspectorProjectionService",
    "InspectorProjectionServiceError",
]
