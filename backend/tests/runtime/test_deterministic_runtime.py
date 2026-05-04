from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.event import DomainEventModel, EventBase
from backend.app.db.models.runtime import (
    DeliveryRecordModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    RunStatus,
    RunTriggerSource,
    StageStatus,
    StageType,
    SseEventType,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphThreadRef,
    GraphThreadStatus,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.runtime.base import (
    RuntimeExecutionContext,
    RuntimeStepResult,
    RuntimeTerminalResult,
)
from backend.app.runtime.deterministic import DeterministicRuntimeEngine


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EXPECTED_STAGE_SEQUENCE = [
    StageType.REQUIREMENT_ANALYSIS,
    StageType.SOLUTION_DESIGN,
    StageType.CODE_GENERATION,
    StageType.TEST_GENERATION_EXECUTION,
    StageType.CODE_REVIEW,
    StageType.DELIVERY_INTEGRATION,
]


class CapturingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return SimpleNamespace(log_id=f"log-{len(self.records)}")


class FailingRunLogWriter:
    def write_run_log(self, record: LogRecordInput) -> object:
        raise RuntimeError("log sink unavailable")


class CapturingCheckpointPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def save_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        purpose: CheckpointPurpose,
        trace_context: TraceContext,
        stage_run_id: str | None = None,
        stage_type: StageType | None = None,
        workspace_snapshot_ref: str | None = None,
        payload_ref: str | None = None,
    ) -> CheckpointRef:
        call = {
            "thread": thread,
            "purpose": purpose,
            "trace_context": trace_context,
            "stage_run_id": stage_run_id,
            "stage_type": stage_type,
            "workspace_snapshot_ref": workspace_snapshot_ref,
            "payload_ref": payload_ref,
        }
        self.calls.append(call)
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{stage_run_id}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            purpose=purpose,
            workspace_snapshot_ref=workspace_snapshot_ref,
            payload_ref=payload_ref,
        )

    def load_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> CheckpointRef:
        return checkpoint


class CapturingRuntimeCommandPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., object]:
        def _capture(**kwargs: Any) -> object:
            self.calls.append((name, kwargs))
            raise AssertionError(f"A4.2 deterministic runtime must not call {name}")

        return _capture


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    return manager


def seed_run(manager: DatabaseManager, *, run_id: str = "run-1") -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        runtime_limit = RuntimeLimitSnapshotModel(
            snapshot_id="runtime-limit-1",
            run_id=run_id,
            agent_limits={"max_react_iterations_per_stage": 30},
            context_limits={"grep_max_results": 20},
            source_config_version="runtime-settings-frozen",
            hard_limits_version="platform-hard-limits-v1",
            schema_version="runtime-limit-snapshot-v1",
            created_at=NOW,
        )
        provider_policy = ProviderCallPolicySnapshotModel(
            snapshot_id="policy-1",
            run_id=run_id,
            provider_call_policy={"network_error_max_retries": 2},
            source_config_version="runtime-settings-frozen",
            schema_version="provider-call-policy-snapshot-v1",
            created_at=NOW,
        )
        run = PipelineRunModel(
            run_id=run_id,
            session_id="session-1",
            project_id="project-1",
            attempt_index=1,
            status=RunStatus.RUNNING,
            trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
            template_snapshot_ref="template-snapshot-1",
            graph_definition_ref="graph-definition-1",
            graph_thread_ref="graph-thread-1",
            workspace_ref="workspace-1",
            runtime_limit_snapshot_ref=runtime_limit.snapshot_id,
            provider_call_policy_snapshot_ref=provider_policy.snapshot_id,
            delivery_channel_snapshot_ref=None,
            current_stage_run_id=None,
            trace_id="trace-1",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([runtime_limit, provider_policy])
        session.flush()
        session.add(run)
        session.commit()


def build_trace(**overrides: Any) -> TraceContext:
    values = {
        "request_id": "request-1",
        "trace_id": "trace-1",
        "correlation_id": "correlation-1",
        "span_id": "span-root",
        "parent_span_id": None,
        "session_id": "session-1",
        "run_id": "run-1",
        "stage_run_id": None,
        "graph_thread_id": "graph-thread-1",
        "created_at": NOW,
    }
    values.update(overrides)
    return TraceContext(**values)


def build_context(**overrides: Any) -> RuntimeExecutionContext:
    values = {
        "run_id": "run-1",
        "session_id": "session-1",
        "thread": GraphThreadRef(
            thread_id="graph-thread-1",
            run_id="run-1",
            status=GraphThreadStatus.RUNNING,
            current_stage_run_id=None,
            current_stage_type=None,
        ),
        "trace_context": build_trace(),
        "template_snapshot_ref": "template-snapshot-1",
        "provider_snapshot_refs": ["provider-snapshot-1"],
        "model_binding_snapshot_refs": ["model-binding-1"],
        "runtime_limit_snapshot_ref": "runtime-limit-1",
        "provider_call_policy_snapshot_ref": "policy-1",
        "graph_definition_ref": "graph-definition-1",
        "delivery_channel_snapshot_ref": None,
        "workspace_snapshot_ref": "workspace-1",
    }
    values.update(overrides)
    return RuntimeExecutionContext(**values)


def build_context_for_run(run_id: str) -> RuntimeExecutionContext:
    thread = GraphThreadRef(
        thread_id="graph-thread-1",
        run_id=run_id,
        status=GraphThreadStatus.RUNNING,
        current_stage_run_id=None,
        current_stage_type=None,
    )
    return build_context(
        run_id=run_id,
        thread=thread,
        trace_context=build_trace(run_id=run_id),
    )


def build_engine(
    manager: DatabaseManager,
    log_writer: CapturingRunLogWriter | FailingRunLogWriter,
    *,
    now: Callable[[], datetime] | None = None,
) -> tuple[DeterministicRuntimeEngine, Session, Session]:
    runtime_session = manager.session(DatabaseRole.RUNTIME)
    event_session = manager.session(DatabaseRole.EVENT)
    engine = DeterministicRuntimeEngine(
        runtime_session=runtime_session,
        event_session=event_session,
        log_writer=log_writer,
        now=now or _clock(),
    )
    return engine, runtime_session, event_session


def _clock() -> Callable[[], datetime]:
    ticks = iter(NOW + timedelta(milliseconds=index) for index in range(500))
    return lambda: next(ticks)


def test_deterministic_runtime_advances_all_six_business_stages(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    runtime_log_writer = CapturingRunLogWriter()
    checkpoint_port = CapturingCheckpointPort()
    engine, runtime_session, event_session = build_engine(manager, runtime_log_writer)
    context = build_context()

    try:
        results = [
            engine.run_next(
                context=context,
                runtime_port=CapturingRuntimeCommandPort(),
                checkpoint_port=checkpoint_port,
            )
            for _ in range(6)
        ]
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    assert all(isinstance(result, RuntimeStepResult) for result in results)
    assert [result.stage_type for result in results] == EXPECTED_STAGE_SEQUENCE
    assert all(result.status is StageStatus.COMPLETED for result in results)
    assert all(result.artifact_refs for result in results)
    assert all(result.domain_event_refs for result in results)
    assert all(result.log_summary_refs for result in results)
    assert all(result.checkpoint_ref is not None for result in results)
    assert [call["stage_type"] for call in checkpoint_port.calls] == EXPECTED_STAGE_SEQUENCE
    deterministic_logs = [
        record
        for record in runtime_log_writer.records
        if record.source == "runtime.deterministic"
    ]
    assert [record.payload.summary["stage_type"] for record in deterministic_logs] == [
        stage.value for stage in EXPECTED_STAGE_SEQUENCE
    ]
    assert all(record.trace_context.span_id for record in deterministic_logs)


def test_deterministic_runtime_completes_existing_running_initial_stage(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    existing_stage_id = "stage-run-existing-requirement-analysis"
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = StageRunModel(
            stage_run_id=existing_stage_id,
            run_id="run-1",
            stage_type=StageType.REQUIREMENT_ANALYSIS,
            status=StageStatus.RUNNING,
            attempt_index=1,
            graph_node_key="requirement_analysis",
            stage_contract_ref="requirement_analysis",
            input_ref=None,
            output_ref=None,
            summary="Requirement Analysis started from the first user requirement.",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        run.current_stage_run_id = existing_stage_id
        session.add(stage)
        session.commit()
    engine, runtime_session, event_session = build_engine(
        manager,
        CapturingRunLogWriter(),
    )
    context = build_context(
        thread=GraphThreadRef(
            thread_id="graph-thread-1",
            run_id="run-1",
            status=GraphThreadStatus.RUNNING,
            current_stage_run_id=existing_stage_id,
            current_stage_type=StageType.REQUIREMENT_ANALYSIS,
        ),
    )

    try:
        result = engine.run_next(
            context=context,
            runtime_port=CapturingRuntimeCommandPort(),
            checkpoint_port=CapturingCheckpointPort(),
        )
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    assert result.stage_run_id == existing_stage_id
    assert result.stage_type is StageType.REQUIREMENT_ANALYSIS
    assert result.status is StageStatus.COMPLETED
    with manager.session(DatabaseRole.RUNTIME) as session:
        stages = session.query(StageRunModel).order_by(StageRunModel.started_at).all()
    assert [stage.stage_run_id for stage in stages] == [existing_stage_id]
    assert stages[0].output_ref == result.artifact_refs[0]


def test_deterministic_runtime_uses_frozen_stage_contract_keys(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_session, event_session = build_engine(
        manager,
        CapturingRunLogWriter(),
    )
    context = build_context()

    try:
        for _ in range(6):
            engine.run_next(
                context=context,
                runtime_port=CapturingRuntimeCommandPort(),
                checkpoint_port=CapturingCheckpointPort(),
            )
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    with manager.session(DatabaseRole.RUNTIME) as session:
        stages = session.query(StageRunModel).order_by(StageRunModel.started_at).all()
    assert [stage.stage_contract_ref for stage in stages] == [
        "requirement_analysis",
        "solution_design",
        "code_generation",
        "test_generation_execution",
        "code_review",
        "delivery_integration",
    ]
    assert [stage.graph_node_key for stage in stages] == [
        "requirement_analysis",
        "solution_design",
        "code_generation",
        "test_generation_execution",
        "code_review",
        "delivery_integration",
    ]


def test_deterministic_runtime_bounds_stage_and_artifact_ids(
    tmp_path: Path,
) -> None:
    run_id = "run-" + ("x" * 76)
    manager = build_manager(tmp_path)
    seed_run(manager, run_id=run_id)
    engine, runtime_session, event_session = build_engine(
        manager,
        CapturingRunLogWriter(),
    )
    context = build_context_for_run(run_id)

    try:
        result = engine.run_next(
            context=context,
            runtime_port=CapturingRuntimeCommandPort(),
            checkpoint_port=CapturingCheckpointPort(),
        )
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    assert len(result.stage_run_id) <= 80
    assert all(len(artifact_ref) <= 80 for artifact_ref in result.artifact_refs)
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, result.stage_run_id)
        artifact = session.get(StageArtifactModel, result.artifact_refs[0])
    assert stage is not None
    assert artifact is not None
    assert len(stage.stage_run_id) <= 80
    assert len(artifact.artifact_id) <= 80


def test_deterministic_runtime_rejects_out_of_order_active_stage(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    active_stage_id = "stage-run-active-code-generation"
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = StageRunModel(
            stage_run_id=active_stage_id,
            run_id="run-1",
            stage_type=StageType.CODE_GENERATION,
            status=StageStatus.RUNNING,
            attempt_index=1,
            graph_node_key="code_generation",
            stage_contract_ref="code_generation",
            input_ref=None,
            output_ref=None,
            summary="Code Generation is already active.",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        run.current_stage_run_id = active_stage_id
        session.add(stage)
        session.commit()
    engine, runtime_session, event_session = build_engine(
        manager,
        CapturingRunLogWriter(),
    )
    context = build_context(
        thread=GraphThreadRef(
            thread_id="graph-thread-1",
            run_id="run-1",
            status=GraphThreadStatus.RUNNING,
            current_stage_run_id=active_stage_id,
            current_stage_type=StageType.CODE_GENERATION,
        ),
    )

    try:
        with pytest.raises(ValueError, match="out of order"):
            engine.run_next(
                context=context,
                runtime_port=CapturingRuntimeCommandPort(),
                checkpoint_port=CapturingCheckpointPort(),
            )
        runtime_session.rollback()
        event_session.rollback()
    finally:
        runtime_session.close()
        event_session.close()

    with manager.session(DatabaseRole.RUNTIME) as session:
        stages = session.query(StageRunModel).order_by(StageRunModel.started_at).all()
        run = session.get(PipelineRunModel, "run-1")
    assert [stage.stage_run_id for stage in stages] == [active_stage_id]
    assert run is not None
    assert run.current_stage_run_id == active_stage_id


def test_deterministic_runtime_rejects_out_of_order_waiting_stage(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    waiting_stage_id = "stage-run-waiting-code-review"
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = StageRunModel(
            stage_run_id=waiting_stage_id,
            run_id="run-1",
            stage_type=StageType.CODE_REVIEW,
            status=StageStatus.WAITING_APPROVAL,
            attempt_index=1,
            graph_node_key="code_review",
            stage_contract_ref="code_review",
            input_ref=None,
            output_ref=None,
            summary="Code Review is waiting for approval.",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        run.current_stage_run_id = waiting_stage_id
        session.add(stage)
        session.commit()
    engine, runtime_session, event_session = build_engine(
        manager,
        CapturingRunLogWriter(),
    )

    try:
        with pytest.raises(ValueError, match="out of order"):
            engine.run_next(
                context=build_context(),
                runtime_port=CapturingRuntimeCommandPort(),
                checkpoint_port=CapturingCheckpointPort(),
            )
        runtime_session.rollback()
        event_session.rollback()
    finally:
        runtime_session.close()
        event_session.close()

    with manager.session(DatabaseRole.RUNTIME) as session:
        stages = session.query(StageRunModel).order_by(StageRunModel.started_at).all()
        run = session.get(PipelineRunModel, "run-1")
    assert [stage.stage_run_id for stage in stages] == [waiting_stage_id]
    assert run is not None
    assert run.current_stage_run_id == waiting_stage_id


def test_deterministic_runtime_persists_stage_runs_artifacts_and_stage_events(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_session, event_session = build_engine(
        manager,
        CapturingRunLogWriter(),
    )
    context = build_context()

    try:
        for _ in range(6):
            engine.run_next(
                context=context,
                runtime_port=CapturingRuntimeCommandPort(),
                checkpoint_port=CapturingCheckpointPort(),
            )
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        stages = (
            runtime_session.query(StageRunModel)
            .order_by(StageRunModel.started_at)
            .all()
        )
        artifacts = (
            runtime_session.query(StageArtifactModel)
            .order_by(StageArtifactModel.created_at)
            .all()
        )

    with manager.session(DatabaseRole.EVENT) as event_session:
        events = (
            event_session.query(DomainEventModel)
            .filter(DomainEventModel.run_id == "run-1")
            .order_by(DomainEventModel.sequence_index)
            .all()
        )

    assert [stage.stage_type for stage in stages] == EXPECTED_STAGE_SEQUENCE
    assert all(stage.status is StageStatus.COMPLETED for stage in stages)
    assert [artifact.stage_run_id for artifact in artifacts] == [
        stage.stage_run_id for stage in stages
    ]
    assert {event.event_type for event in events}.issuperset(
        {SseEventType.STAGE_STARTED, SseEventType.STAGE_UPDATED}
    )
    assert "raw_graph_state" not in str([artifact.process for artifact in artifacts])


def test_solution_validation_is_internal_to_solution_design(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_session, event_session = build_engine(manager, CapturingRunLogWriter())
    context = build_context()

    try:
        engine.run_next(
            context=context,
            runtime_port=CapturingRuntimeCommandPort(),
            checkpoint_port=CapturingCheckpointPort(),
        )
        solution_result = engine.run_next(
            context=context,
            runtime_port=CapturingRuntimeCommandPort(),
            checkpoint_port=CapturingCheckpointPort(),
        )
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        stages = runtime_session.query(StageRunModel).all()
        artifact = runtime_session.get(StageArtifactModel, solution_result.artifact_refs[0])

    assert [stage.stage_type for stage in stages] == [
        StageType.REQUIREMENT_ANALYSIS,
        StageType.SOLUTION_DESIGN,
    ]
    assert artifact is not None
    assert artifact.process["solution_validation"]["status"] == "completed"
    assert artifact.process["solution_validation"]["business_stage_type"] == (
        StageType.SOLUTION_DESIGN.value
    )
    assert "solution_validation" not in {stage.stage_type.value for stage in stages}


def test_deterministic_runtime_uses_frozen_context_snapshots_not_latest_settings(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_session, event_session = build_engine(manager, CapturingRunLogWriter())
    context = build_context(
        template_snapshot_ref="template-frozen",
        provider_snapshot_refs=["provider-frozen"],
        model_binding_snapshot_refs=["model-binding-frozen"],
        runtime_limit_snapshot_ref="runtime-limit-frozen",
        provider_call_policy_snapshot_ref="policy-frozen",
        graph_definition_ref="graph-frozen",
        delivery_channel_snapshot_ref="delivery-frozen",
        workspace_snapshot_ref="workspace-frozen",
    )

    try:
        result = engine.run_next(
            context=context,
            runtime_port=CapturingRuntimeCommandPort(),
            checkpoint_port=CapturingCheckpointPort(),
        )
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        artifact = runtime_session.get(StageArtifactModel, result.artifact_refs[0])

    assert artifact is not None
    snapshot_refs = artifact.process["input_snapshot"]["snapshot_refs"]
    assert snapshot_refs == {
        "template_snapshot_ref": "template-frozen",
        "provider_snapshot_refs": ["provider-frozen"],
        "model_binding_snapshot_refs": ["model-binding-frozen"],
        "runtime_limit_snapshot_ref": "runtime-limit-frozen",
        "provider_call_policy_snapshot_ref": "policy-frozen",
        "graph_definition_ref": "graph-frozen",
        "delivery_channel_snapshot_ref": "delivery-frozen",
        "workspace_snapshot_ref": "workspace-frozen",
    }
    assert "latest-config" not in str(artifact.process)


def test_deterministic_runtime_does_not_execute_tools_or_terminal_delivery_scope(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    runtime_port = CapturingRuntimeCommandPort()
    engine, runtime_session, event_session = build_engine(manager, CapturingRunLogWriter())
    context = build_context()

    try:
        for _ in range(6):
            result = engine.run_next(
                context=context,
                runtime_port=runtime_port,
                checkpoint_port=CapturingCheckpointPort(),
            )
            assert not isinstance(result, RuntimeTerminalResult)
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        artifacts = runtime_session.query(StageArtifactModel).all()
        delivery_records = runtime_session.query(DeliveryRecordModel).all()

    assert runtime_port.calls == []
    assert delivery_records == []
    assert all(artifact.process["tool_calls"] == [] for artifact in artifacts)


def test_deterministic_runtime_keeps_domain_facts_when_runtime_log_write_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    engine, runtime_session, event_session = build_engine(manager, FailingRunLogWriter())
    context = build_context()

    try:
        result = engine.run_next(
            context=context,
            runtime_port=CapturingRuntimeCommandPort(),
            checkpoint_port=CapturingCheckpointPort(),
        )
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_session.close()
        event_session.close()

    assert result.artifact_refs
    assert result.domain_event_refs
    assert result.log_summary_refs == []
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        assert runtime_session.get(StageRunModel, result.stage_run_id) is not None
        assert runtime_session.get(StageArtifactModel, result.artifact_refs[0]) is not None
