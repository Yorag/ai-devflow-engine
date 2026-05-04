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
    DeliveryChannelSnapshotModel,
    DeliveryRecordModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.delivery.demo import DemoDeliveryAdapter
from backend.app.domain.enums import (
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    SseEventType,
    StageStatus,
    StageType,
)
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphThreadRef,
    GraphThreadStatus,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.runtime.base import RuntimeExecutionContext, RuntimeStepResult
from backend.app.runtime.deterministic import (
    DETERMINISTIC_STAGE_SEQUENCE,
    DeterministicRuntimeEngine,
)
from backend.app.services.delivery import DeliveryRecordService, DeliveryService
from backend.app.services.events import EventStore


NOW = datetime(2026, 5, 4, 10, 30, 0, tzinfo=UTC)
INCOMPATIBLE_DELIVERY_SERVICE_MESSAGE = (
    "Deterministic demo delivery requires a same-session non-autocommit DeliveryService."
)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        return SimpleNamespace(audit_id=f"audit-{len(self.records)}")

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return SimpleNamespace(audit_id=f"audit-{len(self.records)}")

    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_failed_command", **kwargs})
        return SimpleNamespace(audit_id=f"audit-{len(self.records)}")


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return SimpleNamespace(log_id=f"log-{len(self.records)}")


class CapturingCheckpointPort:
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
    def __getattr__(self, name: str) -> Callable[..., object]:
        def _capture(**kwargs: Any) -> object:
            raise AssertionError(f"demo_delivery flow must not call {name}")

        return _capture


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    return manager


def seed_run(manager: DatabaseManager) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-1",
                    run_id="run-1",
                    agent_limits={},
                    context_limits={},
                    source_config_version="runtime-settings-frozen",
                    hard_limits_version="platform-hard-limits-v1",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="policy-1",
                    run_id="run-1",
                    provider_call_policy={},
                    source_config_version="runtime-settings-frozen",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
                DeliveryChannelSnapshotModel(
                    delivery_channel_snapshot_id="delivery-snapshot-1",
                    run_id="run-1",
                    source_delivery_channel_id="delivery-default",
                    delivery_mode=DeliveryMode.DEMO_DELIVERY,
                    scm_provider_type=None,
                    repository_identifier=None,
                    default_branch=None,
                    code_review_request_type=None,
                    credential_ref=None,
                    credential_status=CredentialStatus.READY,
                    readiness_status=DeliveryReadinessStatus.READY,
                    readiness_message="demo delivery ready",
                    last_validated_at=NOW,
                    schema_version="delivery-channel-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
        session.add(
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
                delivery_channel_snapshot_ref="delivery-snapshot-1",
                current_stage_run_id=None,
                trace_id="trace-1",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
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
    values: dict[str, Any] = {
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
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "workspace_snapshot_ref": "workspace-1",
    }
    values.update(overrides)
    return RuntimeExecutionContext(**values)


def build_engine(
    manager: DatabaseManager,
    runtime_session: Session,
    event_session: Session,
    audit: RecordingAuditService,
    log_writer: RecordingRunLogWriter,
    *,
    auto_commit: bool = False,
    delivery_event_session: Session | None = None,
) -> DeterministicRuntimeEngine:
    delivery_record_service = DeliveryRecordService(
        runtime_session=runtime_session,
        audit_service=audit,
        log_writer=log_writer,
        auto_commit=auto_commit,
        now=lambda: NOW,
    )
    delivery_service = DeliveryService(
        record_service=delivery_record_service,
        adapters=[
            DemoDeliveryAdapter(
                audit_service=audit,
                log_writer=log_writer,
                now=lambda: NOW,
            )
        ],
        event_store=EventStore(delivery_event_session or event_session, now=lambda: NOW),
        now=lambda: NOW,
    )
    return DeterministicRuntimeEngine(
        runtime_session=runtime_session,
        event_session=event_session,
        delivery_service=delivery_service,
        log_writer=log_writer,
        now=_clock(),
    )


def _clock() -> Callable[[], datetime]:
    ticks = iter(NOW + timedelta(milliseconds=index) for index in range(1000))
    return lambda: next(ticks)


def test_deterministic_runtime_runs_six_stages_to_demo_delivery_result(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    audit = RecordingAuditService()
    log_writer = RecordingRunLogWriter()

    runtime_context = manager.session(DatabaseRole.RUNTIME)
    event_context = manager.session(DatabaseRole.EVENT)
    runtime_session = runtime_context.__enter__()
    event_session = event_context.__enter__()
    try:
        engine = build_engine(
            manager,
            runtime_session,
            event_session,
            audit,
            log_writer,
        )
        results = [
            engine.run_next(
                context=build_context(),
                runtime_port=CapturingRuntimeCommandPort(),
                checkpoint_port=CapturingCheckpointPort(),
            )
            for _ in range(6)
        ]
        runtime_session.commit()
        event_session.commit()
    finally:
        runtime_context.__exit__(None, None, None)
        event_context.__exit__(None, None, None)

    assert all(isinstance(result, RuntimeStepResult) for result in results)
    assert [result.stage_type for result in results] == list(
        DETERMINISTIC_STAGE_SEQUENCE
    )
    delivery_result = results[-1]
    assert delivery_result.stage_type is StageType.DELIVERY_INTEGRATION
    with manager.session(DatabaseRole.RUNTIME) as session:
        records = session.query(DeliveryRecordModel).all()
        delivery_artifact = session.get(
            StageArtifactModel,
            delivery_result.artifact_refs[0],
        )
        delivery_stage = session.get(StageRunModel, delivery_result.stage_run_id)
    with manager.session(DatabaseRole.EVENT) as session:
        events = (
            session.query(DomainEventModel)
            .order_by(DomainEventModel.sequence_index)
            .all()
        )

    assert len(records) == 1
    record = records[0]
    assert record.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert record.status == "succeeded"
    assert record.result_ref == "demo-delivery-result:run-1"
    assert record.process_ref == "demo-delivery-process:run-1"
    assert record.branch_name == "demo/run-1"
    assert record.commit_sha is None
    assert record.code_review_url is None
    delivery_events = [
        event for event in events if event.event_type is SseEventType.DELIVERY_RESULT
    ]
    assert len(delivery_events) == 1
    assert delivery_events[0].payload["delivery_result"]["delivery_record_id"] == (
        record.delivery_record_id
    )
    assert delivery_events[0].payload["delivery_result"]["status"] == "succeeded"
    assert delivery_result.domain_event_refs[-1] == delivery_events[0].event_id
    assert delivery_artifact is not None
    assert delivery_artifact.process["demo_delivery"]["delivery_record_id"] == (
        record.delivery_record_id
    )
    delivery_summary = delivery_artifact.process["output_snapshot"]["summary"]
    assert "later demo_delivery slice" not in delivery_summary
    assert "demo_delivery" in delivery_summary
    assert delivery_artifact.process["demo_delivery"]["no_git_actions"] is True
    assert delivery_artifact.process["demo_delivery"]["git_write_actions"] == []
    assert delivery_artifact.process["demo_delivery"]["audit_refs"]
    assert delivery_artifact.process["demo_delivery"]["log_summary_refs"]
    assert delivery_stage is not None and delivery_stage.status is StageStatus.COMPLETED
    assert "delivery.demo.succeeded" in [row["action"] for row in audit.records]
    assert any(
        record.message == "Demo delivery completed without Git writes."
        for record in log_writer.records
    )
    demo_log = next(record for record in log_writer.records if record.source == "delivery.demo")
    demo_artifact_refs = demo_log.payload.summary["artifact_refs"]
    assert len(demo_artifact_refs) == len(set(demo_artifact_refs))
    assert demo_artifact_refs.count(delivery_artifact.artifact_id) == 1


def test_deterministic_runtime_rejects_autocommit_delivery_service_before_side_effects(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    audit = RecordingAuditService()
    log_writer = RecordingRunLogWriter()

    runtime_context = manager.session(DatabaseRole.RUNTIME)
    event_context = manager.session(DatabaseRole.EVENT)
    runtime_session = runtime_context.__enter__()
    event_session = event_context.__enter__()
    try:
        engine = build_engine(
            manager,
            runtime_session,
            event_session,
            audit,
            log_writer,
            auto_commit=True,
        )
        for _ in range(5):
            engine.run_next(
                context=build_context(),
                runtime_port=CapturingRuntimeCommandPort(),
                checkpoint_port=CapturingCheckpointPort(),
            )
        with pytest.raises(ValueError, match=INCOMPATIBLE_DELIVERY_SERVICE_MESSAGE):
            engine.run_next(
                context=build_context(),
                runtime_port=CapturingRuntimeCommandPort(),
                checkpoint_port=CapturingCheckpointPort(),
            )
        runtime_session.rollback()
        event_session.rollback()
    finally:
        runtime_context.__exit__(None, None, None)
        event_context.__exit__(None, None, None)

    with manager.session(DatabaseRole.RUNTIME) as session:
        records = session.query(DeliveryRecordModel).all()
        artifacts = session.query(StageArtifactModel).all()
    with manager.session(DatabaseRole.EVENT) as session:
        delivery_events = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.DELIVERY_RESULT)
            .all()
        )

    assert records == []
    assert delivery_events == []
    assert all("demo_delivery" not in artifact.process for artifact in artifacts)
