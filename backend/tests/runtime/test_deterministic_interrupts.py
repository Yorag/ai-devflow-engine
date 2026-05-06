from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.base import DatabaseRole, ROLE_METADATA
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.graph import GraphDefinitionModel
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    ClarificationRecordModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    SseEventType,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeCommandResult,
    RuntimeCommandType,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.runtime import deterministic
from backend.app.runtime.base import RuntimeExecutionContext, RuntimeInterrupt, RuntimeStepResult
from backend.app.runtime.deterministic import DeterministicRuntimeEngine


NOW = datetime(2026, 5, 4, 8, 0, 0, tzinfo=UTC)


class RuntimeInterruptTestDatabase:
    def __init__(self, root: Path) -> None:
        self._engines = {
            role: create_engine(f"sqlite:///{root / f'{role.value}.sqlite'}", future=True)
            for role in DatabaseRole
        }
        for role, metadata in ROLE_METADATA.items():
            metadata.create_all(self._engines[role])
        self._sessionmakers = {
            role: sessionmaker(bind=engine, expire_on_commit=False, future=True)
            for role, engine in self._engines.items()
        }

    @contextmanager
    def session(self, role: DatabaseRole) -> Iterator[Session]:
        session = self.open_session(role)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def open_session(self, role: DatabaseRole) -> Session:
        return self._sessionmakers[role]()


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return type("LogWriteResult", (), {"log_id": f"log-{len(self.records)}"})()


class FailingRunLogWriter(RecordingRunLogWriter):
    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        raise RuntimeError("log write failed")


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_failed_command", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return object()

    def record_blocked_action(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_blocked_action", **kwargs})
        return object()


class CapturingCheckpointPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def save_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        self.calls.append(kwargs)
        thread = kwargs["thread"]
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{kwargs.get('payload_ref') or kwargs['purpose'].value}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=kwargs.get("stage_run_id"),
            stage_type=kwargs.get("stage_type"),
            purpose=kwargs["purpose"],
            workspace_snapshot_ref=kwargs.get("workspace_snapshot_ref"),
            payload_ref=kwargs.get("payload_ref"),
        )

    def load_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        return kwargs["checkpoint"]


class CapturingRuntimePort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        self.calls.append(("create_interrupt", kwargs))
        return GraphInterruptRef(
            interrupt_id=(
                f"interrupt-{kwargs.get('clarification_id') or kwargs.get('approval_id') or kwargs.get('tool_confirmation_id')}"
            ),
            thread=kwargs["thread"].model_copy(
                update={"status": _waiting_status(kwargs["interrupt_type"])}
            ),
            interrupt_type=kwargs["interrupt_type"],
            status=GraphInterruptStatus.PENDING,
            run_id=kwargs["run_id"],
            stage_run_id=kwargs["stage_run_id"],
            stage_type=kwargs["stage_type"],
            payload_ref=kwargs["payload_ref"],
            clarification_id=kwargs.get("clarification_id"),
            approval_id=kwargs.get("approval_id"),
            tool_confirmation_id=kwargs.get("tool_confirmation_id"),
            tool_action_ref=kwargs.get("tool_action_ref"),
            checkpoint_ref=kwargs["checkpoint"],
        )

    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_interrupt", kwargs))
        interrupt = kwargs["interrupt"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_INTERRUPT,
            thread=interrupt.thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            interrupt_ref=interrupt.model_copy(update={"status": GraphInterruptStatus.RESUMED}),
            payload_ref=kwargs["resume_payload"].payload_ref,
            trace_context=kwargs["trace_context"],
        )

    def resume_tool_confirmation(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_tool_confirmation", kwargs))
        interrupt = kwargs["interrupt"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_TOOL_CONFIRMATION,
            thread=interrupt.thread.model_copy(update={"status": GraphThreadStatus.RUNNING}),
            interrupt_ref=interrupt.model_copy(update={"status": GraphInterruptStatus.RESUMED}),
            payload_ref=kwargs["resume_payload"].payload_ref,
            trace_context=kwargs["trace_context"],
        )


class FailingResumeRuntimePort(CapturingRuntimePort):
    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_interrupt", kwargs))
        raise RuntimeError("runtime resume failed")


class UniqueCheckpointPort(CapturingCheckpointPort):
    def save_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        self.calls.append(kwargs)
        thread = kwargs["thread"]
        return CheckpointRef(
            checkpoint_id=f"stored-checkpoint-{len(self.calls)}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=kwargs.get("stage_run_id"),
            stage_type=kwargs.get("stage_type"),
            purpose=kwargs["purpose"],
            workspace_snapshot_ref=kwargs.get("workspace_snapshot_ref"),
            payload_ref=kwargs.get("payload_ref"),
        )


def _waiting_status(interrupt_type: GraphInterruptType) -> GraphThreadStatus:
    if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
        return GraphThreadStatus.WAITING_CLARIFICATION
    if interrupt_type is GraphInterruptType.APPROVAL:
        return GraphThreadStatus.WAITING_APPROVAL
    if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
        return GraphThreadStatus.WAITING_TOOL_CONFIRMATION
    raise AssertionError(f"unexpected interrupt type: {interrupt_type}")


def clock() -> Callable[[], datetime]:
    ticks = iter(NOW + timedelta(milliseconds=index) for index in range(1000))
    return lambda: next(ticks)


def build_manager(tmp_path: Path) -> RuntimeInterruptTestDatabase:
    return RuntimeInterruptTestDatabase(tmp_path)


def seed_run(manager: RuntimeInterruptTestDatabase) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Project",
                root_path="C:/repo/project",
                default_delivery_channel_id=None,
                is_default=True,
                is_visible=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            SessionModel(
                session_id="session-1",
                project_id="project-1",
                display_name="Session",
                status=SessionStatus.RUNNING,
                selected_template_id="template-1",
                current_run_id="run-1",
                latest_stage_type=StageType.REQUIREMENT_ANALYSIS,
                is_visible=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-1",
                    run_id="run-1",
                    agent_limits={"max_react_iterations_per_stage": 30},
                    context_limits={"grep_max_results": 20},
                    source_config_version="test",
                    hard_limits_version="test",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="policy-1",
                    run_id="run-1",
                    provider_call_policy={"network_error_max_retries": 2},
                    source_config_version="test",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
                PipelineRunModel(
                    run_id="run-1",
                    session_id="session-1",
                    project_id="project-1",
                    attempt_index=1,
                    status=RunStatus.RUNNING,
                    trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                    template_snapshot_ref="template-snapshot-1",
                    graph_definition_ref="graph-definition-1",
                    graph_thread_ref="graph-thread-1",
                    workspace_ref="workspace-1",
                    runtime_limit_snapshot_ref="runtime-limit-1",
                    provider_call_policy_snapshot_ref="policy-1",
                    delivery_channel_snapshot_ref=None,
                    current_stage_run_id=None,
                    trace_id="trace-1",
                    started_at=NOW,
                    ended_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )


def build_trace(
    *,
    stage_run_id: str | None = None,
    graph_thread_id: str = "graph-thread-1",
) -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="span-root",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id=stage_run_id,
        graph_thread_id=graph_thread_id,
        created_at=NOW,
    )


def build_context(
    *,
    stage_run_id: str | None = None,
    stage_type: StageType | None = None,
    status: GraphThreadStatus = GraphThreadStatus.RUNNING,
) -> RuntimeExecutionContext:
    thread = GraphThreadRef(
        thread_id="graph-thread-1",
        run_id="run-1",
        status=status,
        current_stage_run_id=stage_run_id,
        current_stage_type=stage_type,
    )
    return RuntimeExecutionContext(
        run_id="run-1",
        session_id="session-1",
        thread=thread,
        trace_context=build_trace(stage_run_id=stage_run_id),
        template_snapshot_ref="template-snapshot-1",
        provider_snapshot_refs=["provider-snapshot-1"],
        model_binding_snapshot_refs=["model-binding-snapshot-1"],
        runtime_limit_snapshot_ref="runtime-limit-1",
        provider_call_policy_snapshot_ref="policy-1",
        graph_definition_ref="graph-definition-1",
        delivery_channel_snapshot_ref=None,
        workspace_snapshot_ref="workspace-1",
    )


def build_context_for_current_thread(
    manager: RuntimeInterruptTestDatabase,
    *,
    status: GraphThreadStatus = GraphThreadStatus.RUNNING,
) -> RuntimeExecutionContext:
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        stage = (
            session.get(StageRunModel, run.current_stage_run_id)
            if run.current_stage_run_id is not None
            else None
        )
        stage_run_id = stage.stage_run_id if stage is not None else None
        stage_type = stage.stage_type if stage is not None else None
    return build_context(stage_run_id=stage_run_id, stage_type=stage_type, status=status)


def build_engine(
    manager: RuntimeInterruptTestDatabase,
    *,
    log_writer: RecordingRunLogWriter | None = None,
    with_graph_session: bool = False,
) -> tuple[
    DeterministicRuntimeEngine,
    CapturingRuntimePort,
    CapturingCheckpointPort,
    RecordingRunLogWriter,
]:
    resolved_log_writer = log_writer or RecordingRunLogWriter()
    engine = DeterministicRuntimeEngine(
        control_session=manager.open_session(DatabaseRole.CONTROL),
        runtime_session=manager.open_session(DatabaseRole.RUNTIME),
        event_session=manager.open_session(DatabaseRole.EVENT),
        graph_session=(
            manager.open_session(DatabaseRole.GRAPH) if with_graph_session else None
        ),
        audit_service=RecordingAuditService(),
        log_writer=resolved_log_writer,
        now=clock(),
    )
    return engine, CapturingRuntimePort(), CapturingCheckpointPort(), resolved_log_writer


def advance_to_stage(
    engine: DeterministicRuntimeEngine,
    target_stage_type: StageType,
    runtime_port: CapturingRuntimePort,
    checkpoint_port: CapturingCheckpointPort,
    manager: RuntimeInterruptTestDatabase,
) -> None:
    for stage_type in deterministic.DETERMINISTIC_STAGE_SEQUENCE:
        if stage_type is target_stage_type:
            return
        result = engine.run_next(
            context=build_context_for_current_thread(manager),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
        assert isinstance(result, RuntimeStepResult)
        assert result.stage_type is stage_type
        assert result.status is StageStatus.COMPLETED
    raise AssertionError(f"target stage was not in deterministic sequence: {target_stage_type}")


def runtime_log_records(log_writer: RecordingRunLogWriter) -> list[LogRecordInput]:
    return [
        record
        for record in log_writer.records
        if record.source == "runtime.deterministic"
        and record.payload.summary.get("action") == "deterministic_interrupt_requested"
    ]


def seed_stale_event_from_other_run(manager: RuntimeInterruptTestDatabase) -> None:
    with manager.session(DatabaseRole.EVENT) as session:
        session.add(
            DomainEventModel(
                event_id="event-stale-other-run",
                session_id="session-stale",
                run_id="run-stale",
                stage_run_id="stage-run-stale",
                event_type=SseEventType.CLARIFICATION_REQUESTED,
                sequence_index=999,
                occurred_at=NOW,
                payload={"control_item": {"payload_ref": "stale"}},
                correlation_id="correlation-stale",
                causation_event_id=None,
                created_at=NOW,
            )
        )


def seed_graph_definition(
    manager: RuntimeInterruptTestDatabase,
    *,
    skip_high_risk_tool_confirmations: bool,
) -> None:
    with manager.session(DatabaseRole.GRAPH) as session:
        session.add(
            GraphDefinitionModel(
                graph_definition_id="graph-definition-1",
                run_id="run-1",
                template_snapshot_ref="template-snapshot-1",
                graph_version="function-one-mainline-v1",
                stage_nodes=[
                    {"node_key": stage.value, "stage_type": stage.value}
                    for stage in deterministic.DETERMINISTIC_STAGE_SEQUENCE
                ],
                stage_contracts={
                    stage.value: {
                        "stage_type": stage.value,
                        "stage_contract_ref": stage.value,
                        "allowed_tools": [],
                        "runtime_limits": {
                            "skip_high_risk_tool_confirmations": (
                                skip_high_risk_tool_confirmations
                            )
                        },
                    }
                    for stage in deterministic.DETERMINISTIC_STAGE_SEQUENCE
                },
                interrupt_policy={"approval_interrupts": []},
                retry_policy={"max_auto_regression_retries": 1},
                delivery_routing_policy={"stage": "delivery_integration"},
                schema_version="graph-definition-v1",
                created_at=NOW,
            )
        )


def test_configured_clarification_interrupt_persists_record_event_waiting_state_and_log(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, log_writer = build_engine(manager)
    engine.configure_interrupts(clarification=True)

    result = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeInterrupt)
    assert result.interrupt_ref.interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST
    assert result.stage_type is StageType.REQUIREMENT_ANALYSIS
    assert result.artifact_refs
    with manager.session(DatabaseRole.RUNTIME) as session:
        clarification = session.query(ClarificationRecordModel).one()
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, result.stage_run_id)
        approval_count = session.query(ApprovalRequestModel).count()
        tool_confirmation_count = session.query(ToolConfirmationRequestModel).count()
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.CLARIFICATION_REQUESTED)
            .one()
        )

    assert clarification.answer is None
    assert clarification.payload_ref == result.artifact_refs[0]
    assert clarification.graph_interrupt_ref == result.interrupt_ref.interrupt_id
    assert result.interrupt_ref.clarification_id == clarification.clarification_id
    assert approval_count == 0
    assert tool_confirmation_count == 0
    assert run is not None and run.status is RunStatus.WAITING_CLARIFICATION
    assert stage is not None and stage.status is StageStatus.WAITING_CLARIFICATION
    assert control_session is not None
    assert control_session.status is SessionStatus.WAITING_CLARIFICATION
    assert event.payload["control_item"]["payload_ref"] == clarification.clarification_id
    assert checkpoint_port.calls[-1]["purpose"] is CheckpointPurpose.WAITING_CLARIFICATION
    assert runtime_log_records(log_writer)[-1].payload.summary["interrupt_type"] == (
        GraphInterruptType.CLARIFICATION_REQUEST.value
    )


def test_interrupt_event_refs_ignore_stale_same_type_events_from_other_runs(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    seed_stale_event_from_other_run(manager)
    engine, runtime_port, checkpoint_port, log_writer = build_engine(manager)
    engine.configure_interrupts(clarification=True)

    result = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeInterrupt)
    assert "event-stale-other-run" not in result.domain_event_refs
    interrupt_log = runtime_log_records(log_writer)[-1]
    assert "event-stale-other-run" not in interrupt_log.payload.summary["event_refs"]


def test_interrupt_preserves_checkpoint_ref_returned_by_runtime_boundary(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, _checkpoint_port, _log_writer = build_engine(manager)
    checkpoint_port = UniqueCheckpointPort()
    engine.configure_interrupts(clarification=True)

    result = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeInterrupt)
    assert result.interrupt_ref.checkpoint_ref.checkpoint_id == "stored-checkpoint-1"


def test_configured_solution_design_approval_interrupt_persists_top_level_approval_request(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    engine.configure_interrupts(solution_design_approval=True)

    advance_to_stage(
        engine,
        StageType.SOLUTION_DESIGN,
        runtime_port,
        checkpoint_port,
        manager,
    )
    result = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeInterrupt)
    assert result.interrupt_ref.interrupt_type is GraphInterruptType.APPROVAL
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.query(ApprovalRequestModel).one()
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, result.stage_run_id)
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.APPROVAL_REQUESTED)
            .one()
        )

    assert approval.approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL
    assert approval.status is ApprovalStatus.PENDING
    assert approval.payload_ref == result.artifact_refs[0]
    assert approval.graph_interrupt_ref == result.interrupt_ref.interrupt_id
    assert run is not None and run.status is RunStatus.WAITING_APPROVAL
    assert stage is not None and stage.status is StageStatus.WAITING_APPROVAL
    assert event.payload["approval_request"]["type"] == "approval_request"
    assert event.payload["approval_request"]["approval_id"] == approval.approval_id
    assert checkpoint_port.calls[-1]["purpose"] is CheckpointPurpose.WAITING_APPROVAL


def test_configured_code_review_approval_interrupt_uses_code_review_type(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    engine.configure_interrupts(code_review_approval=True)

    advance_to_stage(
        engine,
        StageType.CODE_REVIEW,
        runtime_port,
        checkpoint_port,
        manager,
    )
    result = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeInterrupt)
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.query(ApprovalRequestModel).one()

    assert approval.approval_type is ApprovalType.CODE_REVIEW_APPROVAL
    assert approval.status is ApprovalStatus.PENDING
    assert result.interrupt_ref.approval_id == approval.approval_id
    assert checkpoint_port.calls[-1]["purpose"] is CheckpointPurpose.WAITING_APPROVAL


def test_configured_tool_confirmation_interrupt_persists_distinct_high_risk_confirmation(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    tool_config = deterministic.DeterministicToolConfirmationConfig(
        stage_type=StageType.TEST_GENERATION_EXECUTION,
        tool_name="bash",
        command_preview="Remove-Item -Recurse build",
        target_summary="Deletes generated build outputs.",
        risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE],
        reason="The deterministic fixture requires a high-risk command.",
        expected_side_effects=["Deletes generated build outputs."],
        alternative_path_summary="Continue with deterministic fallback output.",
        planned_deny_followup_action="continue_current_stage",
        planned_deny_followup_summary="Continue current stage with fixture output.",
    )
    engine.configure_interrupts(tool_confirmation=tool_config)

    advance_to_stage(
        engine,
        StageType.TEST_GENERATION_EXECUTION,
        runtime_port,
        checkpoint_port,
        manager,
    )
    result = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeInterrupt)
    assert result.interrupt_ref.interrupt_type is GraphInterruptType.TOOL_CONFIRMATION
    with manager.session(DatabaseRole.RUNTIME) as session:
        request = session.query(ToolConfirmationRequestModel).one()
        approval_count = session.query(ApprovalRequestModel).count()
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, result.stage_run_id)
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.TOOL_CONFIRMATION_REQUESTED)
            .one()
        )

    assert request.status is ToolConfirmationStatus.PENDING
    assert request.risk_level is ToolRiskLevel.HIGH_RISK
    assert request.risk_categories == [ToolRiskCategory.FILE_DELETE_OR_MOVE.value]
    assert request.confirmation_object_ref == result.artifact_refs[0]
    assert request.planned_deny_followup_action == "continue_current_stage"
    assert result.interrupt_ref.tool_confirmation_id == request.tool_confirmation_id
    assert approval_count == 0
    assert run is not None and run.status is RunStatus.WAITING_TOOL_CONFIRMATION
    assert stage is not None and stage.status is StageStatus.WAITING_TOOL_CONFIRMATION
    assert event.payload["tool_confirmation"]["type"] == "tool_confirmation"
    assert "approval_id" not in event.payload["tool_confirmation"]
    assert checkpoint_port.calls[-1]["purpose"] is CheckpointPurpose.WAITING_TOOL_CONFIRMATION


def test_configured_tool_confirmation_interrupt_is_skipped_by_graph_runtime_policy(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    seed_graph_definition(manager, skip_high_risk_tool_confirmations=True)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(
        manager,
        with_graph_session=True,
    )
    tool_config = deterministic.DeterministicToolConfirmationConfig(
        stage_type=StageType.TEST_GENERATION_EXECUTION,
        tool_name="bash",
        command_preview="Remove-Item -Recurse build",
        target_summary="Deletes generated build outputs.",
        risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE],
    )
    engine.configure_interrupts(tool_confirmation=tool_config)

    advance_to_stage(
        engine,
        StageType.TEST_GENERATION_EXECUTION,
        runtime_port,
        checkpoint_port,
        manager,
    )
    result = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.status is StageStatus.COMPLETED
    assert result.stage_type is StageType.TEST_GENERATION_EXECUTION
    assert [call[0] for call in runtime_port.calls] == []
    confirmation_count = engine._runtime_session.query(
        ToolConfirmationRequestModel
    ).count()
    run = engine._runtime_session.get(PipelineRunModel, "run-1")
    stage = engine._runtime_session.get(StageRunModel, result.stage_run_id)
    assert confirmation_count == 0
    assert run is not None and run.status is RunStatus.RUNNING
    assert stage is not None and stage.status is StageStatus.COMPLETED


def test_resume_from_clarification_interrupt_uses_runtime_boundary_and_continues_source_stage(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    engine.configure_interrupts(clarification=True)
    interrupt = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    assert isinstance(interrupt, RuntimeInterrupt)

    result = engine.resume_from_interrupt(
        context=build_context_for_current_thread(
            manager,
            status=GraphThreadStatus.WAITING_CLARIFICATION,
        ),
        interrupt=interrupt,
        resume_payload=RuntimeResumePayload(
            resume_id="resume-clarification-1",
            payload_ref="clarification-answer-1",
            values={"answer": "Use the existing deterministic fixture."},
        ),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.status is StageStatus.RUNNING
    assert result.stage_type is StageType.REQUIREMENT_ANALYSIS
    assert runtime_port.calls[-1][0] == "resume_interrupt"
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, interrupt.stage_run_id)
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
    assert run is not None and run.status is RunStatus.RUNNING
    assert stage is not None and stage.status is StageStatus.RUNNING
    assert control_session is not None and control_session.status is SessionStatus.RUNNING


def test_resumed_clarification_stage_advances_without_reemitting_interrupt_or_artifact(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    engine.configure_interrupts(clarification=True)
    interrupt = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    assert isinstance(interrupt, RuntimeInterrupt)
    engine.resume_from_interrupt(
        context=build_context_for_current_thread(
            manager,
            status=GraphThreadStatus.WAITING_CLARIFICATION,
        ),
        interrupt=interrupt,
        resume_payload=RuntimeResumePayload(
            resume_id="resume-clarification-advance",
            payload_ref="clarification-answer-advance",
            values={"answer": "Continue."},
        ),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    result = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.status is StageStatus.COMPLETED
    assert result.stage_run_id == interrupt.stage_run_id
    assert result.artifact_refs == interrupt.artifact_refs
    assert [call[0] for call in runtime_port.calls].count("create_interrupt") == 1
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(StageArtifactModel).count() == 1


def test_resume_runtime_failure_logs_and_leaves_waiting_state(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, log_writer = build_engine(manager)
    engine.configure_interrupts(clarification=True)
    interrupt = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    assert isinstance(interrupt, RuntimeInterrupt)
    failing_runtime_port = FailingResumeRuntimePort()

    with pytest.raises(RuntimeError, match="runtime resume failed"):
        engine.resume_from_interrupt(
            context=build_context_for_current_thread(
                manager,
                status=GraphThreadStatus.WAITING_CLARIFICATION,
            ),
            interrupt=interrupt,
            resume_payload=RuntimeResumePayload(
                resume_id="resume-clarification-fails",
                payload_ref="clarification-answer-fails",
                values={"answer": "Continue."},
            ),
            runtime_port=failing_runtime_port,
            checkpoint_port=checkpoint_port,
        )

    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, interrupt.stage_run_id)
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
    assert run is not None and run.status is RunStatus.WAITING_CLARIFICATION
    assert stage is not None and stage.status is StageStatus.WAITING_CLARIFICATION
    assert control_session is not None
    assert control_session.status is SessionStatus.WAITING_CLARIFICATION
    failure_logs = [
        record
        for record in log_writer.records
        if record.source == "runtime.deterministic"
        and record.payload.summary.get("action")
        == "deterministic_interrupt_resume_failed"
    ]
    assert failure_logs


def test_resume_from_tool_confirmation_uses_tool_confirmation_runtime_boundary(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    tool_config = deterministic.DeterministicToolConfirmationConfig(
        stage_type=StageType.TEST_GENERATION_EXECUTION
    )
    engine.configure_interrupts(tool_confirmation=tool_config)
    advance_to_stage(
        engine,
        StageType.TEST_GENERATION_EXECUTION,
        runtime_port,
        checkpoint_port,
        manager,
    )
    interrupt = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    assert isinstance(interrupt, RuntimeInterrupt)

    result = engine.resume_from_interrupt(
        context=build_context_for_current_thread(
            manager,
            status=GraphThreadStatus.WAITING_TOOL_CONFIRMATION,
        ),
        interrupt=interrupt,
        resume_payload=RuntimeResumePayload(
            resume_id="resume-tool-confirmation-1",
            payload_ref=interrupt.payload_ref,
            values={
                "decision": "allowed",
                "tool_confirmation_id": interrupt.interrupt_ref.tool_confirmation_id,
            },
        ),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert runtime_port.calls[-1][0] == "resume_tool_confirmation"
    assert result.status is StageStatus.RUNNING


def test_resume_from_rejected_code_review_approval_reports_code_generation_target(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    engine.configure_interrupts(code_review_approval=True)
    advance_to_stage(
        engine,
        StageType.CODE_REVIEW,
        runtime_port,
        checkpoint_port,
        manager,
    )
    interrupt = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    assert isinstance(interrupt, RuntimeInterrupt)

    result = engine.resume_from_interrupt(
        context=build_context_for_current_thread(
            manager,
            status=GraphThreadStatus.WAITING_APPROVAL,
        ),
        interrupt=interrupt,
        resume_payload=RuntimeResumePayload(
            resume_id="resume-code-review-rejected",
            payload_ref="approval-decision-rejected",
            values={
                "decision": "rejected",
                "reason": "Need safer tests.",
                "approval_id": interrupt.interrupt_ref.approval_id,
                "next_stage_type": "code_generation",
            },
        ),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.stage_type is StageType.CODE_GENERATION
    assert result.status is StageStatus.RUNNING
    assert runtime_port.calls[-1][0] == "resume_interrupt"


def test_default_deterministic_runtime_still_completes_stages_without_interrupts(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)

    result = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.status is StageStatus.COMPLETED
    assert runtime_port.calls == []
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(ClarificationRecordModel).count() == 0
        assert session.query(ApprovalRequestModel).count() == 0
        assert session.query(ToolConfirmationRequestModel).count() == 0


def test_configured_interrupt_requires_control_session(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    runtime_session = manager.open_session(DatabaseRole.RUNTIME)
    event_session = manager.open_session(DatabaseRole.EVENT)
    try:
        engine = DeterministicRuntimeEngine(
            runtime_session=runtime_session,
            event_session=event_session,
            log_writer=RecordingRunLogWriter(),
            now=clock(),
        )
        engine.configure_interrupts(clarification=True)
        try:
            engine.run_next(
                context=build_context(),
                runtime_port=CapturingRuntimePort(),
                checkpoint_port=CapturingCheckpointPort(),
            )
        except ValueError as exc:
            assert "control_session" in str(exc)
        else:
            raise AssertionError("configured interrupt without control_session must fail")
    finally:
        runtime_session.close()
        event_session.close()


def test_interrupt_log_failure_does_not_remove_domain_facts(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, log_writer = build_engine(
        manager,
        log_writer=FailingRunLogWriter(),
    )
    engine.configure_interrupts(clarification=True)

    result = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeInterrupt)
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(ClarificationRecordModel).count() == 1
        stage = session.get(StageRunModel, result.stage_run_id)
        assert stage is not None and stage.status is StageStatus.WAITING_CLARIFICATION
    assert log_writer.records
