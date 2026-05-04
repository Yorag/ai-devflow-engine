from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.event import DomainEventModel, EventBase
from backend.app.db.models.runtime import (
    DeliveryChannelSnapshotModel,
    DeliveryRecordModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.delivery.base import DeliveryAdapterInput
from backend.app.delivery.demo import DEMO_DELIVERY_SUMMARY, DemoDeliveryAdapter
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
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.services.delivery import (
    DELIVERY_RESULT_RECORD_INVALID_MESSAGE,
    DeliveryRecordService,
    DeliveryService,
    DeliveryServiceError,
)
from backend.app.services.events import EventStore


NOW = datetime(2026, 5, 4, 10, 0, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append(kwargs)
        return SimpleNamespace(audit_id=f"audit-demo-{len(self.records)}")


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return SimpleNamespace(log_id=f"log-demo-{len(self.records)}")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-demo-delivery",
        trace_id="trace-demo-delivery",
        correlation_id="correlation-demo-delivery",
        span_id="span-demo-delivery",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-delivery",
        created_at=NOW,
    )


def build_input(**overrides: Any) -> DeliveryAdapterInput:
    values: dict[str, Any] = {
        "run_id": "run-1",
        "stage_run_id": "stage-run-delivery",
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "delivery_mode": DeliveryMode.DEMO_DELIVERY,
        "requirement_refs": ["artifact-requirement"],
        "solution_refs": ["artifact-solution"],
        "changeset_refs": ["artifact-code"],
        "test_result_refs": ["artifact-test"],
        "review_refs": ["artifact-review"],
        "approval_result_refs": ["approval-result-1"],
        "artifact_refs": ["artifact-delivery"],
        "trace_context": build_trace(),
    }
    values.update(overrides)
    return DeliveryAdapterInput(**values)


def test_demo_delivery_adapter_returns_display_result_without_git_writes() -> None:
    audit = RecordingAuditService()
    log_writer = RecordingRunLogWriter()
    adapter = DemoDeliveryAdapter(
        audit_service=audit,
        log_writer=log_writer,
        now=lambda: NOW,
    )

    result = adapter.deliver(build_input())

    assert result.status == "succeeded"
    assert result.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert result.result_ref == "demo-delivery-result:run-1"
    assert result.process_ref == "demo-delivery-process:run-1"
    assert result.branch_name == "demo/run-1"
    assert result.commit_sha is None
    assert result.code_review_url is None
    assert result.audit_refs == ["audit-demo-1"]
    assert result.log_summary_refs == ["log-demo-1"]
    assert audit.records[0]["action"] == "delivery.demo.succeeded"
    assert audit.records[0]["target_id"] == "demo_delivery:run-1"
    assert audit.records[0]["metadata"]["no_git_actions"] is True
    assert audit.records[0]["metadata"]["git_write_actions"] == []
    assert log_writer.records[0].message == DEMO_DELIVERY_SUMMARY
    assert log_writer.records[0].payload.summary["no_git_actions"] is True
    assert log_writer.records[0].payload.summary["git_write_actions"] == []


def test_demo_delivery_adapter_rejects_non_demo_mode() -> None:
    adapter = DemoDeliveryAdapter(now=lambda: NOW)

    with pytest.raises(ValueError, match="demo_delivery"):
        adapter.deliver(
            build_input(delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY)
        )


def test_demo_delivery_log_summary_does_not_reintroduce_sensitive_metadata() -> None:
    log_writer = RecordingRunLogWriter()
    adapter = DemoDeliveryAdapter(
        log_writer=log_writer,
        now=lambda: NOW,
    )

    adapter.deliver(build_input(requirement_refs=["sk-secret-demo-ref"]))

    summary = log_writer.records[0].payload.summary
    assert summary["blocked_reason"] == "sensitive_text_pattern"
    assert "sk-secret-demo-ref" not in str(summary)
    assert "requirement_refs" not in summary


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    return manager


def seed_run_snapshot_and_stage(manager: DatabaseManager) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limits-1",
                    run_id="run-1",
                    agent_limits={},
                    context_limits={},
                    source_config_version="test",
                    hard_limits_version="test",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-policy-1",
                    run_id="run-1",
                    provider_call_policy={},
                    source_config_version="test",
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
                    readiness_message="demo delivery is ready.",
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
                project_id="project-default",
                attempt_index=1,
                status=RunStatus.RUNNING,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-1",
                graph_definition_ref="graph-definition-1",
                graph_thread_ref="thread-1",
                workspace_ref="workspace-1",
                runtime_limit_snapshot_ref="runtime-limits-1",
                provider_call_policy_snapshot_ref="provider-policy-1",
                delivery_channel_snapshot_ref="delivery-snapshot-1",
                current_stage_run_id="stage-run-delivery",
                trace_id="trace-demo-delivery",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            StageRunModel(
                stage_run_id="stage-run-delivery",
                run_id="run-1",
                stage_type=StageType.DELIVERY_INTEGRATION,
                status=StageStatus.RUNNING,
                attempt_index=1,
                graph_node_key="delivery_integration",
                stage_contract_ref="delivery_integration",
                input_ref=None,
                output_ref=None,
                summary="Delivering.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def test_create_demo_record_and_append_delivery_result_event(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    audit = RecordingAuditService()
    log_writer = RecordingRunLogWriter()

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        record_service = DeliveryRecordService(
            runtime_session=runtime_session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: NOW,
        )
        delivery_service = DeliveryService(
            record_service=record_service,
            adapters=[
                DemoDeliveryAdapter(
                    audit_service=audit,
                    log_writer=log_writer,
                    now=lambda: NOW,
                )
            ],
            event_store=EventStore(event_session, now=lambda: NOW),
            now=lambda: NOW,
        )
        adapter = delivery_service.get_adapter(
            DeliveryMode.DEMO_DELIVERY,
            trace_context=build_trace(),
        )
        adapter_result = adapter.deliver(build_input())
        record = record_service.create_demo_record(adapter_result=adapter_result)
        event = delivery_service.append_delivery_result(
            record=record,
            trace_context=build_trace(),
        )
        runtime_session.commit()
        event_session.commit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        saved = session.get(DeliveryRecordModel, record.delivery_record_id)
    with manager.session(DatabaseRole.EVENT) as session:
        saved_event = session.get(DomainEventModel, event.event_id)

    assert saved is not None
    assert saved.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert saved.status == "succeeded"
    assert saved.branch_name == "demo/run-1"
    assert saved.commit_sha is None
    assert saved.code_review_url is None
    assert saved_event is not None
    assert saved_event.event_type is SseEventType.DELIVERY_RESULT
    assert saved_event.payload["delivery_result"]["delivery_record_id"] == (
        record.delivery_record_id
    )
    assert saved_event.payload["delivery_result"]["delivery_mode"] == "demo_delivery"
    assert saved_event.payload["delivery_result"]["status"] == "succeeded"
    assert saved_event.payload["delivery_result"]["summary"] == DEMO_DELIVERY_SUMMARY
    assert saved_event.payload["delivery_result"]["commit_sha"] is None
    assert saved_event.payload["delivery_result"]["code_review_url"] is None


def test_append_delivery_result_rejects_failed_record_without_event(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)

    with (
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        record_service = DeliveryRecordService(
            runtime_session=runtime_session,
            now=lambda: NOW,
        )
        record = record_service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="failed",
            result_ref=None,
            process_ref="demo-delivery-process:run-1",
            failure_reason="Demo delivery failed.",
            trace_context=build_trace(),
        )
        service = DeliveryService(
            record_service=record_service,
            event_store=EventStore(event_session, now=lambda: NOW),
            now=lambda: NOW,
        )
        with pytest.raises(DeliveryServiceError) as exc_info:
            service.append_delivery_result(
                record=record,
                trace_context=build_trace(),
            )
        runtime_session.commit()
        event_session.commit()

    assert exc_info.value.message == DELIVERY_RESULT_RECORD_INVALID_MESSAGE
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
