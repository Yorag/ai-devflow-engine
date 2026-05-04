from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
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
from backend.app.delivery.base import (
    DeliveryAdapterError,
    DeliveryAdapterInput,
    DeliveryAdapterResult,
)
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    StageStatus,
    StageType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.services.delivery import (
    DELIVERY_ADAPTER_NOT_FOUND_MESSAGE,
    DELIVERY_RECORD_STAGE_MISMATCH_MESSAGE,
    DeliveryRecordService,
    DeliveryService,
    DeliveryServiceError,
)


NOW = datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_failed_command", **kwargs})
        return object()


class FailingRequiredAuditService(RecordingAuditService):
    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        raise RuntimeError("required delivery audit unavailable")


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FailingRunLogWriter(RecordingRunLogWriter):
    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        raise RuntimeError("delivery run log unavailable")


class FakeDeliveryAdapter:
    name = "fake_demo_delivery"
    delivery_mode = DeliveryMode.DEMO_DELIVERY

    def deliver(self, delivery_input: DeliveryAdapterInput) -> DeliveryAdapterResult:
        return DeliveryAdapterResult(
            run_id=delivery_input.run_id,
            stage_run_id=delivery_input.stage_run_id,
            delivery_mode=delivery_input.delivery_mode,
            status="succeeded",
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            branch_name="demo/run-1",
            commit_sha=None,
            code_review_url=None,
            audit_refs=["audit-demo-1"],
            log_summary_refs=["log-demo-1"],
            trace_context=delivery_input.trace_context,
        )


class FakeGitDeliveryAdapter(FakeDeliveryAdapter):
    name = "fake_git_auto_delivery"
    delivery_mode = DeliveryMode.GIT_AUTO_DELIVERY


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-delivery-record",
        trace_id="trace-delivery-record",
        correlation_id="correlation-delivery-record",
        span_id="span-delivery-record",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-delivery",
        created_at=NOW,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    return manager


def seed_run_snapshot_and_stage(
    manager: DatabaseManager,
    *,
    stage_type: StageType = StageType.DELIVERY_INTEGRATION,
    delivery_mode: DeliveryMode = DeliveryMode.DEMO_DELIVERY,
    current_stage_run_id: str = "stage-run-delivery",
    snapshot_run_id: str = "run-1",
) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RuntimeLimitSnapshotModel(
                snapshot_id="runtime-limits-1",
                run_id="run-1",
                agent_limits={},
                context_limits={},
                source_config_version="test",
                hard_limits_version="test",
                schema_version="runtime-limit-snapshot-v1",
                created_at=NOW,
            )
        )
        session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id="provider-policy-1",
                run_id="run-1",
                provider_call_policy={},
                source_config_version="test",
                schema_version="provider-call-policy-snapshot-v1",
                created_at=NOW,
            )
        )
        session.add(
            DeliveryChannelSnapshotModel(
                delivery_channel_snapshot_id="delivery-snapshot-1",
                run_id=snapshot_run_id,
                source_delivery_channel_id="delivery-default",
                delivery_mode=delivery_mode,
                scm_provider_type=(
                    ScmProviderType.GITHUB
                    if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
                    else None
                ),
                repository_identifier=(
                    "acme/app"
                    if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
                    else None
                ),
                default_branch=(
                    "main"
                    if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
                    else None
                ),
                code_review_request_type=(
                    CodeReviewRequestType.PULL_REQUEST
                    if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
                    else None
                ),
                credential_ref=(
                    "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
                    if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
                    else None
                ),
                credential_status=CredentialStatus.READY,
                readiness_status=DeliveryReadinessStatus.READY,
                readiness_message="delivery is ready.",
                last_validated_at=NOW,
                schema_version="delivery-channel-snapshot-v1",
                created_at=NOW,
            )
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
                current_stage_run_id=current_stage_run_id,
                trace_id="trace-delivery-record",
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
                stage_type=stage_type,
                status=StageStatus.RUNNING,
                attempt_index=1,
                graph_node_key="delivery_integration.main",
                stage_contract_ref="stage-contract-delivery-integration",
                input_ref="artifact-delivery-input",
                output_ref=None,
                summary="Delivering.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def build_record_service(
    manager: DatabaseManager,
    *,
    audit: RecordingAuditService | None = None,
    log_writer: RecordingRunLogWriter | None = None,
) -> tuple[DeliveryRecordService, RecordingAuditService, RecordingRunLogWriter]:
    resolved_audit = audit or RecordingAuditService()
    resolved_log_writer = log_writer or RecordingRunLogWriter()
    runtime_context = manager.session(DatabaseRole.RUNTIME)
    runtime_session = runtime_context.__enter__()
    service = DeliveryRecordService(
        runtime_session=runtime_session,
        audit_service=resolved_audit,
        log_writer=resolved_log_writer,
        now=lambda: NOW,
    )
    service._test_context = runtime_context
    return service, resolved_audit, resolved_log_writer


def test_delivery_adapter_models_reject_identity_mismatch_and_invalid_status() -> None:
    with pytest.raises(ValidationError, match="trace_context.run_id"):
        DeliveryAdapterInput(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_channel_snapshot_ref="delivery-snapshot-1",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            trace_context=build_trace().model_copy(update={"run_id": "other-run"}),
        )

    with pytest.raises(ValidationError, match="status"):
        DeliveryAdapterResult(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="unknown",
            trace_context=build_trace(),
        )

    with pytest.raises(ValidationError, match="error"):
        DeliveryAdapterResult(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="failed",
            trace_context=build_trace(),
        )


def test_create_record_persists_delivery_record_from_frozen_snapshot(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    service, audit, log_writer = build_record_service(manager)

    record = service.create_record(
        run_id="run-1",
        stage_run_id="stage-run-delivery",
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        status="succeeded",
        result_ref="delivery-result-demo-1",
        process_ref="delivery-process-demo-1",
        branch_name="demo/run-1",
        commit_sha=None,
        code_review_url=None,
        failure_reason=None,
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        saved = session.get(DeliveryRecordModel, record.delivery_record_id)
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-delivery")

    assert saved is not None
    assert saved.run_id == "run-1"
    assert saved.stage_run_id == "stage-run-delivery"
    assert saved.delivery_channel_snapshot_ref == "delivery-snapshot-1"
    assert saved.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert saved.status == "succeeded"
    assert saved.result_ref == "delivery-result-demo-1"
    assert saved.process_ref == "delivery-process-demo-1"
    assert saved.branch_name == "demo/run-1"
    assert saved.completed_at == NOW.replace(tzinfo=None)
    assert run is not None and run.status is RunStatus.RUNNING
    assert stage is not None and stage.status is StageStatus.RUNNING
    assert audit.records[0]["action"] == "delivery_record.create"
    assert audit.records[0]["target_id"] == record.delivery_record_id
    assert log_writer.records[0].message == "DeliveryRecord created."


def test_create_record_rejects_non_delivery_integration_stage_without_mutation(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager, stage_type=StageType.CODE_REVIEW)
    service, audit, log_writer = build_record_service(manager)

    with pytest.raises(DeliveryServiceError) as exc_info:
        service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="succeeded",
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.message == DELIVERY_RECORD_STAGE_MISMATCH_MESSAGE
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryRecordModel).count() == 0
    assert audit.records[0]["action"] == "delivery_record.create.rejected"
    assert log_writer.records[0].message == "DeliveryRecord creation rejected."


def test_create_record_rejects_mode_mismatch_between_result_and_snapshot(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager, delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY)
    service, audit, _log_writer = build_record_service(manager)

    with pytest.raises(DeliveryServiceError) as exc_info:
        service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="succeeded",
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryRecordModel).count() == 0
    assert audit.records[0]["action"] == "delivery_record.create.rejected"


@pytest.mark.parametrize(
    ("status", "failure_reason"),
    [
        ("unknown", None),
        ("succeeded", "Success must not have a failure reason."),
        ("failed", None),
        ("blocked", None),
    ],
)
def test_create_record_rejects_invalid_status_payload_without_mutation(
    tmp_path: Path,
    status: str,
    failure_reason: str | None,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    service, audit, log_writer = build_record_service(manager)

    with pytest.raises(DeliveryServiceError) as exc_info:
        service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status=status,
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            failure_reason=failure_reason,
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryRecordModel).count() == 0
    assert audit.records[0]["action"] == "delivery_record.create.rejected"
    assert log_writer.records[0].message == "DeliveryRecord creation rejected."


def test_create_record_rejects_non_current_delivery_stage_without_mutation(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager, current_stage_run_id="stage-run-other")
    service, audit, _log_writer = build_record_service(manager)

    with pytest.raises(DeliveryServiceError) as exc_info:
        service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="succeeded",
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryRecordModel).count() == 0
    assert audit.records[0]["action"] == "delivery_record.create.rejected"


def test_create_record_rejects_snapshot_that_belongs_to_another_run(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager, snapshot_run_id="other-run")
    service, audit, _log_writer = build_record_service(manager)

    with pytest.raises(DeliveryServiceError) as exc_info:
        service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="succeeded",
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.DELIVERY_SNAPSHOT_MISSING
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryRecordModel).count() == 0
    assert audit.records[0]["action"] == "delivery_record.create.rejected"


def test_create_record_rejects_trace_identity_mismatch_without_mutation(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    service, audit, _log_writer = build_record_service(manager)

    with pytest.raises(DeliveryServiceError) as exc_info:
        service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="succeeded",
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            trace_context=build_trace().model_copy(update={"run_id": "other-run"}),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryRecordModel).count() == 0
    assert audit.records[0]["action"] == "delivery_record.create.rejected"


def test_create_delivery_record_from_adapter_result_uses_registered_adapter_result(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    record_service, _audit, _log_writer = build_record_service(manager)
    delivery_service = DeliveryService(
        record_service=record_service,
        adapters=[FakeDeliveryAdapter()],
    )
    adapter = delivery_service.get_adapter(
        DeliveryMode.DEMO_DELIVERY,
        trace_context=build_trace(),
    )
    delivery_input = DeliveryAdapterInput(
        run_id="run-1",
        stage_run_id="stage-run-delivery",
        delivery_channel_snapshot_ref="delivery-snapshot-1",
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        requirement_refs=["artifact-requirement-1"],
        solution_refs=["artifact-solution-1"],
        changeset_refs=["changeset-1"],
        test_result_refs=["test-result-1"],
        review_refs=["review-1"],
        approval_result_refs=["approval-result-1"],
        trace_context=build_trace(),
    )

    record = delivery_service.create_delivery_record_from_adapter_result(
        adapter_result=adapter.deliver(delivery_input),
    )

    assert record.status == "succeeded"
    assert record.result_ref == "delivery-result-demo-1"
    assert record.process_ref == "delivery-process-demo-1"
    assert record.branch_name == "demo/run-1"


def test_get_adapter_requires_trace_context() -> None:
    record_service = DeliveryRecordService(runtime_session=object())  # type: ignore[arg-type]
    delivery_service = DeliveryService(record_service=record_service, adapters=[])

    with pytest.raises(TypeError, match="trace_context"):
        delivery_service.get_adapter(DeliveryMode.DEMO_DELIVERY)


def test_get_adapter_records_missing_adapter_rejection_with_trace_context() -> None:
    audit = RecordingAuditService()
    log_writer = RecordingRunLogWriter()
    record_service = DeliveryRecordService(
        runtime_session=object(),  # type: ignore[arg-type]
        audit_service=audit,
        log_writer=log_writer,
        now=lambda: NOW,
    )
    delivery_service = DeliveryService(record_service=record_service, adapters=[])

    with pytest.raises(DeliveryServiceError):
        delivery_service.get_adapter(
            DeliveryMode.DEMO_DELIVERY,
            trace_context=build_trace(),
        )

    assert audit.records[0]["action"] == "delivery_adapter.select.rejected"
    assert audit.records[0]["target_id"] == DeliveryMode.DEMO_DELIVERY.value
    assert log_writer.records[0].message == "Delivery adapter selection rejected."


def test_delivery_service_rejects_duplicate_adapter_registration() -> None:
    record_service = DeliveryRecordService(runtime_session=object())  # type: ignore[arg-type]

    with pytest.raises(DeliveryServiceError) as exc_info:
        DeliveryService(
            record_service=record_service,
            adapters=[FakeDeliveryAdapter(), FakeDeliveryAdapter()],
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    assert "adapter registry" in exc_info.value.message
    assert "duplicate" in exc_info.value.message


def test_delivery_service_rejects_mapping_key_adapter_mode_mismatch() -> None:
    record_service = DeliveryRecordService(runtime_session=object())  # type: ignore[arg-type]

    with pytest.raises(DeliveryServiceError) as exc_info:
        DeliveryService(
            record_service=record_service,
            adapters={DeliveryMode.DEMO_DELIVERY: FakeGitDeliveryAdapter()},
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    assert "adapter registry" in exc_info.value.message
    assert "does not match" in exc_info.value.message


def test_get_record_reports_not_found(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    service, _audit, _log_writer = build_record_service(manager)

    with pytest.raises(DeliveryServiceError) as exc_info:
        service.get_record("delivery-record-missing")

    assert exc_info.value.error_code is ErrorCode.NOT_FOUND
    assert exc_info.value.status_code == 404


def test_create_record_rolls_back_when_required_audit_fails(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    service, audit, log_writer = build_record_service(
        manager,
        audit=FailingRequiredAuditService(),
    )

    with pytest.raises(RuntimeError, match="required delivery audit unavailable"):
        service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="succeeded",
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            trace_context=build_trace(),
        )

    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryRecordModel).count() == 0
    assert [record["action"] for record in audit.records] == [
        "delivery_record.create",
        "delivery_record.create.failed",
    ]
    assert [record.message for record in log_writer.records] == [
        "DeliveryRecord creation failed.",
    ]


def test_create_record_preserves_audit_failure_when_failure_log_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    service, audit, log_writer = build_record_service(
        manager,
        audit=FailingRequiredAuditService(),
        log_writer=FailingRunLogWriter(),
    )

    with pytest.raises(RuntimeError, match="required delivery audit unavailable"):
        service.create_record(
            run_id="run-1",
            stage_run_id="stage-run-delivery",
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="succeeded",
            result_ref="delivery-result-demo-1",
            process_ref="delivery-process-demo-1",
            trace_context=build_trace(),
        )

    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryRecordModel).count() == 0
    assert [record["action"] for record in audit.records] == [
        "delivery_record.create",
        "delivery_record.create.failed",
    ]
    assert [record.message for record in log_writer.records] == [
        "DeliveryRecord creation failed.",
    ]


def test_create_failed_record_uses_adapter_error_safe_message(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    seed_run_snapshot_and_stage(manager)
    record_service, _audit, _log_writer = build_record_service(manager)
    delivery_service = DeliveryService(record_service=record_service, adapters=[])
    adapter_result = DeliveryAdapterResult(
        run_id="run-1",
        stage_run_id="stage-run-delivery",
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        status="failed",
        process_ref="delivery-process-demo-1",
        error=DeliveryAdapterError(
            error_code="demo_delivery_failed",
            safe_message="Demo delivery failed.",
        ),
        trace_context=build_trace(),
    )

    record = delivery_service.create_delivery_record_from_adapter_result(
        adapter_result=adapter_result,
    )

    assert record.status == "failed"
    assert record.failure_reason == "Demo delivery failed."
