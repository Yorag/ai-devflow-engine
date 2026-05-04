from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.base import DatabaseRole, ROLE_METADATA
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.runtime import (
    DeliveryRecordModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    SseEventType,
    StageStatus,
    StageType,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeCommandResult,
    RuntimeCommandType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.runtime import deterministic
from backend.app.runtime.base import (
    RuntimeExecutionContext,
    RuntimeStepResult,
    RuntimeTerminalResult,
)
from backend.app.runtime.deterministic import DeterministicRuntimeEngine


NOW = datetime(2026, 5, 4, 8, 0, 0, tzinfo=UTC)


class RuntimeTerminalTestDatabase:
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
        return SimpleNamespace(log_id=f"log-{len(self.records)}")


class FailingRunLogWriter(RecordingRunLogWriter):
    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        raise RuntimeError("log write failed")


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

    def terminate_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("terminate_thread", kwargs))
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.TERMINATE_THREAD,
            thread=kwargs["thread"].model_copy(
                update={"status": GraphThreadStatus.TERMINATED}
            ),
            trace_context=kwargs["trace_context"],
        )


class FailingTerminateRuntimePort(CapturingRuntimePort):
    def terminate_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("terminate_thread", kwargs))
        raise RuntimeError("runtime terminate failed")


def clock() -> Callable[[], datetime]:
    ticks = iter(NOW + timedelta(milliseconds=index) for index in range(1000))
    return lambda: next(ticks)


def build_manager(tmp_path: Path) -> RuntimeTerminalTestDatabase:
    return RuntimeTerminalTestDatabase(tmp_path)


def seed_run(manager: RuntimeTerminalTestDatabase) -> None:
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


def seed_running_stage_with_artifact(
    manager: RuntimeTerminalTestDatabase,
    *,
    stage_run_id: str = "stage-run-current",
    stage_type: StageType = StageType.SOLUTION_DESIGN,
    artifact_id: str = "artifact-current",
    stage_status: StageStatus = StageStatus.RUNNING,
    run_status: RunStatus = RunStatus.RUNNING,
    session_status: SessionStatus = SessionStatus.RUNNING,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        control_session.status = session_status
        control_session.latest_stage_type = stage_type
        control_session.updated_at = NOW
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        run.status = run_status
        run.current_stage_run_id = stage_run_id
        run.updated_at = NOW
        stage = StageRunModel(
            stage_run_id=stage_run_id,
            run_id="run-1",
            stage_type=stage_type,
            status=stage_status,
            attempt_index=1,
            graph_node_key=stage_type.value,
            stage_contract_ref=stage_type.value,
            input_ref=artifact_id,
            output_ref=artifact_id,
            summary="Seeded non-terminal current stage.",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        artifact = StageArtifactModel(
            artifact_id=artifact_id,
            run_id="run-1",
            stage_run_id=stage_run_id,
            artifact_type=f"{stage_type.value}_deterministic_stage",
            payload_ref=f"deterministic://run-1/{stage_type.value}/output",
            process={
                "input_snapshot": {"stage_type": stage_type.value},
                "input_refs": [],
                "output_snapshot": {"stage_type": stage_type.value},
                "output_refs": [],
            },
            metrics={},
            created_at=NOW,
        )
        session.add_all([stage, artifact])


def seed_running_stage_without_artifact(
    manager: RuntimeTerminalTestDatabase,
    *,
    stage_run_id: str = "stage-run-current",
    stage_type: StageType = StageType.SOLUTION_DESIGN,
) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        run.current_stage_run_id = stage_run_id
        run.updated_at = NOW
        session.add(
            StageRunModel(
                stage_run_id=stage_run_id,
                run_id="run-1",
                stage_type=stage_type,
                status=StageStatus.RUNNING,
                attempt_index=1,
                graph_node_key=stage_type.value,
                stage_contract_ref=stage_type.value,
                input_ref=None,
                output_ref=None,
                summary="Seeded non-terminal current stage without artifact.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def seed_mismatched_stage_artifact(
    manager: RuntimeTerminalTestDatabase,
    *,
    stage_run_id: str = "stage-run-other",
    stage_type: StageType = StageType.CODE_REVIEW,
    artifact_id: str = "artifact-other",
) -> StageArtifactModel:
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = StageRunModel(
            stage_run_id=stage_run_id,
            run_id="run-1",
            stage_type=stage_type,
            status=StageStatus.RUNNING,
            attempt_index=1,
            graph_node_key=stage_type.value,
            stage_contract_ref=stage_type.value,
            input_ref=artifact_id,
            output_ref=artifact_id,
            summary="Seeded mismatched stage.",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        artifact = StageArtifactModel(
            artifact_id=artifact_id,
            run_id="run-1",
            stage_run_id=stage_run_id,
            artifact_type=f"{stage_type.value}_deterministic_stage",
            payload_ref=f"deterministic://run-1/{stage_type.value}/output",
            process={
                "input_snapshot": {"stage_type": stage_type.value},
                "input_refs": [],
                "output_snapshot": {"stage_type": stage_type.value},
                "output_refs": [],
            },
            metrics={},
            created_at=NOW,
        )
        session.add_all([stage, artifact])
        session.flush()
        return artifact


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
    manager: RuntimeTerminalTestDatabase,
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
    manager: RuntimeTerminalTestDatabase,
    *,
    log_writer: RecordingRunLogWriter | None = None,
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
        log_writer=resolved_log_writer,
        now=clock(),
    )
    return engine, CapturingRuntimePort(), CapturingCheckpointPort(), resolved_log_writer


def advance_to_stage(
    engine: DeterministicRuntimeEngine,
    target_stage_type: StageType,
    runtime_port: CapturingRuntimePort,
    checkpoint_port: CapturingCheckpointPort,
    manager: RuntimeTerminalTestDatabase,
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


def terminal_log_records(
    log_writer: RecordingRunLogWriter,
    action: str,
) -> list[LogRecordInput]:
    return [
        record
        for record in log_writer.records
        if record.source == "runtime.deterministic"
        and record.payload.summary.get("action") == action
    ]


def test_configured_failure_marks_run_stage_session_failed_and_appends_system_status(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, log_writer = build_engine(manager)
    engine.configure_terminal_control(
        fail_at_stage=StageType.CODE_GENERATION,
        failure_reason="Deterministic fixture failed at code generation.",
    )

    advance_to_stage(engine, StageType.CODE_GENERATION, runtime_port, checkpoint_port, manager)
    result = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeTerminalResult)
    assert result.status is GraphThreadStatus.FAILED
    assert result.thread.status is GraphThreadStatus.FAILED
    assert result.result_ref == "deterministic://run-1/terminal/failed"
    assert result.artifact_refs
    assert result.domain_event_refs
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, result.thread.current_stage_run_id)
        assert run is not None and run.status is RunStatus.FAILED
        assert stage is not None and stage.status is StageStatus.FAILED
        assert run.ended_at is not None
        assert session.query(DeliveryRecordModel).count() == 0
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None and control_session.status is SessionStatus.FAILED
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SYSTEM_STATUS)
            .one()
        )
        started = (
            session.query(DomainEventModel)
            .filter(
                DomainEventModel.event_type == SseEventType.STAGE_STARTED,
                DomainEventModel.stage_run_id == result.thread.current_stage_run_id,
            )
            .one()
        )
        assert event.payload["system_status"]["status"] == "failed"
        assert event.payload["system_status"]["retry_action"] == "retry:run-1"
        assert started.event_id in result.domain_event_refs
    terminal_logs = terminal_log_records(log_writer, "deterministic_terminal_failed")
    assert terminal_logs[-1].payload.summary["direct_failure_point"] == "code_generation"
    assert terminal_logs[-1].payload.summary["retry_action"] == "retry:run-1"
    assert started.event_id in terminal_logs[-1].payload.summary["event_refs"]


def test_configured_termination_uses_runtime_boundary_and_appends_system_status(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    engine.configure_terminal_control(
        terminate_at_stage=StageType.TEST_GENERATION_EXECUTION,
        termination_reason="Deterministic fixture terminated by runtime control.",
    )

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

    assert isinstance(result, RuntimeTerminalResult)
    assert result.status is GraphThreadStatus.TERMINATED
    assert runtime_port.calls[-1][0] == "terminate_thread"
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, result.thread.current_stage_run_id)
        assert run is not None and run.status is RunStatus.TERMINATED
        assert stage is not None and stage.status is StageStatus.TERMINATED
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SYSTEM_STATUS)
            .one()
        )
        assert event.payload["system_status"]["status"] == "terminated"
        assert event.payload["system_status"]["retry_action"] == "retry:run-1"


def test_configured_termination_boundary_failure_rolls_back_pending_stage_facts(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, _runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    runtime_port = FailingTerminateRuntimePort()
    engine.configure_terminal_control(
        terminate_at_stage=StageType.REQUIREMENT_ANALYSIS,
        termination_reason="Deterministic fixture terminate boundary failed.",
    )

    with pytest.raises(RuntimeError, match="runtime terminate failed"):
        engine.run_next(
            context=build_context(),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
    engine._runtime_session.commit()
    engine._event_session.commit()
    if engine._control_session is not None:
        engine._control_session.commit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None and run.status is RunStatus.RUNNING
        assert run.current_stage_run_id is None
        assert session.query(StageRunModel).count() == 0
        assert session.query(StageArtifactModel).count() == 0
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_configured_completion_after_six_stages_marks_run_completed_without_system_status_or_delivery_record(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    engine.configure_terminal_control(complete_after_stages=True)

    for _ in range(6):
        step = engine.run_next(
            context=build_context_for_current_thread(manager),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
        assert isinstance(step, RuntimeStepResult)
    result = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeTerminalResult)
    assert result.status is GraphThreadStatus.COMPLETED
    assert result.result_ref == "deterministic://run-1/terminal/completed"
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None and run.status is RunStatus.COMPLETED
        assert session.query(DeliveryRecordModel).count() == 0
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None and control_session.status is SessionStatus.COMPLETED
    with manager.session(DatabaseRole.EVENT) as session:
        assert (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SYSTEM_STATUS)
            .count()
            == 0
        )
        changed = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SESSION_STATUS_CHANGED)
            .one()
        )
        assert changed.payload["status"] == "completed"


def test_direct_terminate_marks_current_stage_terminated(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    seed_running_stage_with_artifact(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)

    result = engine.terminate(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert result.status is GraphThreadStatus.TERMINATED
    assert runtime_port.calls[-1][0] == "terminate_thread"
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, result.thread.current_stage_run_id)
        assert stage is not None and stage.status is StageStatus.TERMINATED


def test_direct_terminate_preserves_waiting_thread_status_for_runtime_boundary(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    seed_running_stage_with_artifact(
        manager,
        stage_status=StageStatus.WAITING_APPROVAL,
        run_status=RunStatus.WAITING_APPROVAL,
        session_status=SessionStatus.WAITING_APPROVAL,
    )
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)

    result = engine.terminate(
        context=build_context_for_current_thread(
            manager,
            status=GraphThreadStatus.WAITING_APPROVAL,
        ),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert result.status is GraphThreadStatus.TERMINATED
    assert runtime_port.calls[-1][1]["thread"].status is GraphThreadStatus.WAITING_APPROVAL


def test_direct_terminate_creates_missing_source_artifact_for_running_stage(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    seed_running_stage_without_artifact(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)

    result = engine.terminate(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert result.status is GraphThreadStatus.TERMINATED
    assert result.artifact_refs
    with manager.session(DatabaseRole.RUNTIME) as session:
        artifact = session.get(StageArtifactModel, result.artifact_refs[0])
        stage = session.get(StageRunModel, result.thread.current_stage_run_id)
        assert artifact is not None
        assert stage is not None and stage.output_ref == artifact.artifact_id


def test_direct_terminate_rejects_completed_current_stage_without_runtime_boundary(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    step = engine.run_next(
        context=build_context_for_current_thread(manager),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    assert isinstance(step, RuntimeStepResult)
    engine._runtime_session.commit()

    with pytest.raises(ValueError, match="non-terminal current stage"):
        engine.terminate(
            context=build_context_for_current_thread(manager),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    assert runtime_port.calls == []
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, step.stage_run_id)
        assert stage is not None and stage.status is StageStatus.COMPLETED


def test_emit_terminal_result_rejects_mismatched_artifact_without_terminal_mutation(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    seed_running_stage_with_artifact(manager)
    mismatched_artifact = seed_mismatched_stage_artifact(manager)
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, "stage-run-current")
        artifact = session.get(StageArtifactModel, mismatched_artifact.artifact_id)
        assert stage is not None and artifact is not None

    with pytest.raises(ValueError, match="terminal source identity"):
        engine.emit_terminal_result(
            context=build_context_for_current_thread(manager),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            terminal_status=GraphThreadStatus.FAILED,
            run_status=RunStatus.FAILED,
            stage=stage,
            artifact=artifact,
            reason="Mismatched terminal artifact.",
            direct_failure_point=stage.stage_type.value,
            trace_context=build_trace(stage_run_id=stage.stage_run_id),
        )

    assert runtime_port.calls == []
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        current_stage = session.get(StageRunModel, "stage-run-current")
        other_artifact = session.get(StageArtifactModel, mismatched_artifact.artifact_id)
        assert run is not None and run.status is RunStatus.RUNNING
        assert current_stage is not None and current_stage.status is StageStatus.RUNNING
        assert other_artifact is not None
        assert "terminal_result" not in other_artifact.process
    with manager.session(DatabaseRole.EVENT) as session:
        assert (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SYSTEM_STATUS)
            .count()
            == 0
        )


def test_emit_terminal_result_rejects_non_current_stage_without_terminal_mutation(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    seed_running_stage_with_artifact(manager, stage_run_id="stage-run-current")
    seed_running_stage_with_artifact(
        manager,
        stage_run_id="stage-run-non-current",
        artifact_id="artifact-non-current",
        stage_type=StageType.CODE_REVIEW,
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        run.current_stage_run_id = "stage-run-current"
    engine, runtime_port, checkpoint_port, _log_writer = build_engine(manager)
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, "stage-run-non-current")
        artifact = session.get(StageArtifactModel, "artifact-non-current")
        assert stage is not None and artifact is not None

    with pytest.raises(ValueError, match="terminal source identity"):
        engine.emit_terminal_result(
            context=build_context_for_current_thread(manager),
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
            terminal_status=GraphThreadStatus.FAILED,
            run_status=RunStatus.FAILED,
            stage=stage,
            artifact=artifact,
            reason="Non-current terminal stage.",
            direct_failure_point=stage.stage_type.value,
            trace_context=build_trace(stage_run_id=stage.stage_run_id),
        )

    assert runtime_port.calls == []
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, "stage-run-non-current")
        assert stage is not None and stage.status is StageStatus.RUNNING


def test_terminal_log_failure_does_not_remove_terminal_domain_facts(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_port, checkpoint_port, log_writer = build_engine(
        manager,
        log_writer=FailingRunLogWriter(),
    )
    engine.configure_terminal_control(fail_at_stage=StageType.REQUIREMENT_ANALYSIS)

    result = engine.run_next(
        context=build_context(),
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeTerminalResult)
    assert result.log_summary_refs == []
    assert log_writer.records
    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, result.thread.current_stage_run_id)
        assert run is not None and run.status is RunStatus.FAILED
        assert stage is not None and stage.status is StageStatus.FAILED
    with manager.session(DatabaseRole.EVENT) as session:
        assert (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.SYSTEM_STATUS)
            .count()
            == 1
        )
