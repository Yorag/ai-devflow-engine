from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole, ROLE_METADATA
from backend.app.db.models.control import DeliveryChannelModel, ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ApprovalRequestModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RunControlRecordModel,
    RuntimeLimitSnapshotModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    CodeReviewRequestType,
    ControlItemType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    SessionStatus,
    StageStatus,
    StageType,
)
from backend.app.domain.runtime_refs import (
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeCommandResult,
    RuntimeCommandType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.feed import ApprovalRequestFeedEntry
from backend.app.schemas.observability import AuditActorType
from backend.app.services.approvals import ApprovalService, ApprovalServiceError
from backend.app.services.delivery_snapshots import DeliverySnapshotServiceError
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


NOW = datetime(2026, 5, 3, 11, 0, 0, tzinfo=UTC)


class ApprovalCommandTestDatabaseManager:
    def __init__(self, root: Path) -> None:
        self._engines = {
            role: create_engine(
                f"sqlite:///{root / f'{role.value}.sqlite'}",
                future=True,
            )
            for role in DatabaseRole
        }
        for role, metadata in ROLE_METADATA.items():
            metadata.create_all(self._engines[role])
        self._sessionmakers = {
            role: sessionmaker(
                bind=engine,
                expire_on_commit=False,
                future=True,
            )
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


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return object()

    def record_blocked_action(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_blocked_action", **kwargs})
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_failed_command", **kwargs})
        return object()


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FakeCheckpointPort:
    def save_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        thread = kwargs["thread"]
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{thread.thread_id}",
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


class FakeRuntimePort:
    def __init__(self, *, fail_on_resume: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail_on_resume = fail_on_resume

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        raise AssertionError("create_interrupt is not used in approval command tests")

    def resume_interrupt(self, **kwargs: Any) -> RuntimeCommandResult:
        self.calls.append(("resume_interrupt", kwargs))
        if self._fail_on_resume:
            raise RuntimeError("runtime resume failed")
        interrupt = kwargs["interrupt"]
        return RuntimeCommandResult(
            command_type=RuntimeCommandType.RESUME_INTERRUPT,
            thread=interrupt.thread.model_copy(
                update={"status": GraphThreadStatus.RUNNING}
            ),
            interrupt_ref=interrupt.model_copy(
                update={"status": GraphInterruptStatus.RESUMED}
            ),
            payload_ref=kwargs["resume_payload"].payload_ref,
            trace_context=kwargs["trace_context"],
        )

    def resume_tool_confirmation(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("tool confirmation resume is not used in approval tests")

    def pause_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("pause_thread is not used in approval tests")

    def resume_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("resume_thread is not used in approval tests")

    def terminate_thread(self, **kwargs: Any) -> RuntimeCommandResult:
        raise AssertionError("terminate_thread is not used in approval tests")

    def assert_thread_terminal(self, **kwargs: Any) -> GraphThreadRef:
        raise AssertionError("assert_thread_terminal is not used in approval tests")


class RecordingDeliverySnapshotService:
    def __init__(
        self,
        runtime_session: Session,
        *,
        event_session: Session | None = None,
        runtime_port: FakeRuntimePort | None = None,
        assert_before_events_and_resume: bool = False,
    ) -> None:
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._runtime_port = runtime_port
        self._assert_before_events_and_resume = assert_before_events_and_resume
        self.calls: list[dict[str, Any]] = []

    def prepare_delivery_snapshot(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self._assert_before_events_and_resume:
            assert self._event_session is not None
            assert self._runtime_port is not None
            assert self._event_session.query(DomainEventModel).count() == 0
            assert self._runtime_port.calls == []
        run = self._runtime_session.get(PipelineRunModel, kwargs["run_id"])
        assert run is not None
        run.delivery_channel_snapshot_ref = "delivery-snapshot-1"
        run.updated_at = NOW
        self._runtime_session.flush()
        return type(
            "DeliverySnapshotStub",
            (),
            {"delivery_channel_snapshot_id": "delivery-snapshot-1"},
        )()


class DomainErrorDeliverySnapshotService:
    def prepare_delivery_snapshot(self, **kwargs: Any) -> object:
        raise DeliverySnapshotServiceError(
            ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
            "DeliveryChannel is not ready for delivery snapshot.",
            409,
        )


def build_manager(tmp_path: Path) -> ApprovalCommandTestDatabaseManager:
    return ApprovalCommandTestDatabaseManager(tmp_path)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-approval-command",
        trace_id="trace-approval-command",
        correlation_id="correlation-approval-command",
        span_id="root-span",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def build_service(
    manager: ApprovalCommandTestDatabaseManager,
    *,
    runtime_port: FakeRuntimePort | None = None,
    audit_service: RecordingAuditService | None = None,
    log_writer: RecordingRunLogWriter | None = None,
    delivery_snapshot_service: RecordingDeliverySnapshotService | None = None,
) -> tuple[
    ApprovalService,
    FakeRuntimePort,
    RecordingAuditService,
    RecordingRunLogWriter,
    RecordingDeliverySnapshotService,
]:
    control_session = manager.open_session(DatabaseRole.CONTROL)
    runtime_session = manager.open_session(DatabaseRole.RUNTIME)
    event_session = manager.open_session(DatabaseRole.EVENT)
    resolved_runtime_port = runtime_port or FakeRuntimePort()
    resolved_audit_service = audit_service or RecordingAuditService()
    resolved_log_writer = log_writer or RecordingRunLogWriter()
    resolved_snapshot_service = delivery_snapshot_service or RecordingDeliverySnapshotService(
        runtime_session
    )
    service = ApprovalService(
        control_session=control_session,
        runtime_session=runtime_session,
        event_session=event_session,
        runtime_orchestration=RuntimeOrchestrationService(
            runtime_port=resolved_runtime_port,
            checkpoint_port=FakeCheckpointPort(),
            clock=lambda: NOW,
        ),
        audit_service=resolved_audit_service,
        delivery_snapshot_service=resolved_snapshot_service,
        log_writer=resolved_log_writer,
        now=lambda: NOW,
    )
    return (
        service,
        resolved_runtime_port,
        resolved_audit_service,
        resolved_log_writer,
        resolved_snapshot_service,
    )


def seed_waiting_approval(
    manager: ApprovalCommandTestDatabaseManager,
    *,
    approval_type: ApprovalType,
    stage_type: StageType,
    run_status: RunStatus = RunStatus.WAITING_APPROVAL,
    session_status: SessionStatus = SessionStatus.WAITING_APPROVAL,
    delivery_mode: DeliveryMode = DeliveryMode.DEMO_DELIVERY,
    readiness_status: DeliveryReadinessStatus = DeliveryReadinessStatus.READY,
    credential_status: CredentialStatus = CredentialStatus.READY,
) -> str:
    approval_id = "approval-1"
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProjectModel(
                project_id="project-1",
                name="Approval Project",
                root_path="C:/repo/approval-project",
                default_delivery_channel_id="delivery-channel-1",
                is_default=True,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            DeliveryChannelModel(
                delivery_channel_id="delivery-channel-1",
                project_id="project-1",
                delivery_mode=delivery_mode,
                scm_provider_type=ScmProviderType.GITHUB,
                repository_identifier="acme/approval-project",
                default_branch="main",
                code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
                credential_ref="env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
                credential_status=credential_status,
                readiness_status=readiness_status,
                readiness_message=(
                    "Delivery channel requires configuration."
                    if readiness_status is not DeliveryReadinessStatus.READY
                    else "Delivery channel is ready."
                ),
                last_validated_at=NOW if readiness_status is DeliveryReadinessStatus.READY else None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            SessionModel(
                session_id="session-1",
                project_id="project-1",
                display_name="Approval session",
                status=session_status,
                selected_template_id="template-1",
                current_run_id="run-1",
                latest_stage_type=stage_type,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )

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
                PipelineRunModel(
                    run_id="run-1",
                    session_id="session-1",
                    project_id="project-1",
                    attempt_index=1,
                    status=run_status,
                    trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                    template_snapshot_ref="template-snapshot-1",
                    graph_definition_ref="graph-definition-1",
                    graph_thread_ref="thread-1",
                    workspace_ref="workspace-1",
                    runtime_limit_snapshot_ref="runtime-limits-1",
                    provider_call_policy_snapshot_ref="provider-policy-1",
                    delivery_channel_snapshot_ref=None,
                    current_stage_run_id="stage-run-1",
                    trace_id="trace-approval-command",
                    started_at=NOW,
                    ended_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                StageRunModel(
                    stage_run_id="stage-run-1",
                    run_id="run-1",
                    stage_type=stage_type,
                    status=StageStatus.WAITING_APPROVAL,
                    attempt_index=1,
                    input_ref=None,
                    output_ref=None,
                    summary="Waiting for approval.",
                    started_at=NOW,
                    ended_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                ApprovalRequestModel(
                    approval_id=approval_id,
                    run_id="run-1",
                    stage_run_id="stage-run-1",
                    approval_type=approval_type,
                    status=ApprovalStatus.PENDING,
                    payload_ref="approval-payload-1",
                    graph_interrupt_ref="interrupt-approval-1",
                    requested_at=NOW,
                    resolved_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
    return approval_id


def seed_approval_request_event(
    manager: ApprovalCommandTestDatabaseManager,
    *,
    approval_id: str,
    approval_type: ApprovalType,
) -> None:
    with manager.session(DatabaseRole.EVENT) as session:
        projection = ApprovalRequestFeedEntry(
            entry_id=f"entry-{approval_id}",
            run_id="run-1",
            occurred_at=NOW,
            approval_id=approval_id,
            approval_type=approval_type,
            status=ApprovalStatus.PENDING,
            title=(
                "Review solution design"
                if approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL
                else "Review code review result"
            ),
            approval_object_excerpt="Review the approval object.",
            risk_excerpt="One risk remains.",
            approval_object_preview={"payload_ref": "approval-payload-1"},
            approve_action="approve",
            reject_action="reject",
            is_actionable=True,
            requested_at=NOW,
            delivery_readiness_status=None,
            delivery_readiness_message=None,
            open_settings_action=None,
            disabled_reason=None,
        )
        EventStore(session, now=lambda: NOW, id_factory=lambda: "event-approval-request").append(
            DomainEventType.APPROVAL_REQUESTED,
            payload={"approval_request": projection.model_dump(mode="json")},
            trace_context=build_trace(),
        )


def test_approve_solution_design_creates_decision_approval_result_and_resumes_runtime(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
        stage_type=StageType.SOLUTION_DESIGN,
    )
    service, runtime_port, audit, log_writer, _snapshot_service = build_service(manager)

    result = service.approve(
        approval_id=approval_id,
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert result.approval_result.decision is ApprovalStatus.APPROVED
    assert result.approval_result.next_stage_type is StageType.CODE_GENERATION
    assert result.control_item is None
    assert runtime_port.calls[-1][0] == "resume_interrupt"
    assert runtime_port.calls[-1][1]["resume_payload"].values == {
        "decision": "approved",
        "reason": None,
        "approval_id": approval_id,
        "next_stage_type": "code_generation",
    }
    assert log_writer.records[-1].duration_ms == 0
    assert log_writer.records[-1].payload.excerpt is not None
    assert '"result_status":"accepted"' in log_writer.records[-1].payload.excerpt
    assert f'"approval_id":"{approval_id}"' in log_writer.records[-1].payload.excerpt
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, approval_id)
        decision = session.query(ApprovalDecisionModel).one()
        assert approval is not None
        assert approval.status is ApprovalStatus.APPROVED
        assert approval.resolved_at == NOW.replace(tzinfo=None)
        assert decision.reason is None
    with manager.session(DatabaseRole.EVENT) as session:
        event = session.query(DomainEventModel).one()
        assert event.payload["approval_result"]["decision"] == "approved"
    assert audit.records[0]["method"] == "require_audit_record"
    assert audit.records[0]["action"] == "approval.approve"


def test_reject_code_review_creates_decision_approval_result_rollback_and_resumes_runtime(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
    )
    service, runtime_port, audit, _log_writer, _snapshot_service = build_service(manager)

    result = service.reject(
        approval_id=approval_id,
        reason="Tests are incomplete and one risk is unresolved.",
        actor_id="session-user",
        trace_context=build_trace(),
    )

    assert (
        result.approval_result.reason
        == "Tests are incomplete and one risk is unresolved."
    )
    assert result.approval_result.next_stage_type is StageType.CODE_GENERATION
    assert result.control_item is not None
    assert result.control_item.control_type is ControlItemType.ROLLBACK
    assert (
        result.control_item.summary
        == "Rejected approval: Tests are incomplete and one risk is unresolved. Continue in code_generation."
    )
    assert runtime_port.calls[-1][1]["resume_payload"].values == {
        "decision": "rejected",
        "reason": "Tests are incomplete and one risk is unresolved.",
        "approval_id": approval_id,
        "next_stage_type": "code_generation",
    }
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(ApprovalDecisionModel).count() == 1
        assert session.query(RunControlRecordModel).count() == 1
    assert audit.records[0]["action"] == "approval.reject"


def test_approve_code_review_blocks_when_git_delivery_not_ready_and_refreshes_projection(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        credential_status=CredentialStatus.UNBOUND,
    )
    seed_approval_request_event(
        manager,
        approval_id=approval_id,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
    )
    service, runtime_port, audit, log_writer, _snapshot_service = build_service(manager)

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.approve(
            approval_id=approval_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.DELIVERY_SNAPSHOT_NOT_READY
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail_ref == approval_id
    assert exc_info.value.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert exc_info.value.open_settings_action == "open_delivery_settings"
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, approval_id)
        run = session.get(PipelineRunModel, "run-1")
        assert approval is not None and approval.status is ApprovalStatus.PENDING
        assert session.query(ApprovalDecisionModel).count() == 0
        assert run is not None and run.delivery_channel_snapshot_ref is None
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .order_by(DomainEventModel.sequence_index.desc())
            .first()
        )
        assert event is not None
        payload = event.payload["approval_request"]
        assert payload["delivery_readiness_status"] == "unconfigured"
        assert payload["delivery_readiness_message"] is not None
        assert payload["open_settings_action"] == "open_delivery_settings"
    assert runtime_port.calls == []
    assert audit.records[0]["method"] == "record_blocked_action"
    assert audit.records[0]["action"] == "approval.approve.blocked"
    assert log_writer.records[-1].duration_ms == 0
    assert log_writer.records[-1].payload.excerpt is not None
    assert '"result_status":"blocked"' in log_writer.records[-1].payload.excerpt
    assert (
        '"blocked_reason":"DeliveryChannel is not ready for approval."'
        in log_writer.records[-1].payload.excerpt
    )


def test_approve_code_review_prepares_snapshot_before_decision_event_and_runtime_resume(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
    )
    runtime_port = FakeRuntimePort()
    runtime_session = manager.open_session(DatabaseRole.RUNTIME)
    event_session = manager.open_session(DatabaseRole.EVENT)
    snapshot_service = RecordingDeliverySnapshotService(
        runtime_session,
        event_session=event_session,
        runtime_port=runtime_port,
        assert_before_events_and_resume=True,
    )
    control_session = manager.open_session(DatabaseRole.CONTROL)
    audit = RecordingAuditService()
    log_writer = RecordingRunLogWriter()
    service = ApprovalService(
        control_session=control_session,
        runtime_session=runtime_session,
        event_session=event_session,
        runtime_orchestration=RuntimeOrchestrationService(
            runtime_port=runtime_port,
            checkpoint_port=FakeCheckpointPort(),
            clock=lambda: NOW,
        ),
        audit_service=audit,
        delivery_snapshot_service=snapshot_service,
        log_writer=log_writer,
        now=lambda: NOW,
    )

    result = service.approve(
        approval_id=approval_id,
        actor_id="session-user",
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None and run.delivery_channel_snapshot_ref == "delivery-snapshot-1"
    assert snapshot_service.calls[0]["approval_type"] is ApprovalType.CODE_REVIEW_APPROVAL
    assert snapshot_service.calls[0]["target_stage_type"] is StageType.DELIVERY_INTEGRATION
    assert result.approval_result.next_stage_type is StageType.DELIVERY_INTEGRATION


def test_approval_commands_reject_paused_runs_without_creating_decision(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
        stage_type=StageType.SOLUTION_DESIGN,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
    )
    service, _runtime_port, _audit, _log_writer, _snapshot_service = build_service(manager)

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.approve(
            approval_id=approval_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    assert "paused" in exc_info.value.message
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, approval_id)
        assert approval is not None and approval.status is ApprovalStatus.PENDING
        assert session.query(ApprovalDecisionModel).count() == 0


def test_approval_commands_reject_mismatched_session_current_run_without_creating_decision(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
        stage_type=StageType.SOLUTION_DESIGN,
    )
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        control_session.current_run_id = "run-stale"
    service, _runtime_port, _audit, _log_writer, _snapshot_service = build_service(manager)

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.approve(
            approval_id=approval_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    assert "current_run_id does not match run" in exc_info.value.message
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, approval_id)
        assert approval is not None and approval.status is ApprovalStatus.PENDING
        assert session.query(ApprovalDecisionModel).count() == 0


def test_reject_blank_reason_is_rejected_without_creating_decision(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
    )
    service, _runtime_port, _audit, _log_writer, _snapshot_service = build_service(manager)

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.reject(
            approval_id=approval_id,
            reason="   ",
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "Reject reason must not be blank."
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, approval_id)
        assert approval is not None and approval.status is ApprovalStatus.PENDING
        assert session.query(ApprovalDecisionModel).count() == 0


def test_approve_maps_delivery_snapshot_domain_error_without_creating_decision(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
    )
    service, _runtime_port, _audit, _log_writer, _snapshot_service = build_service(
        manager,
        delivery_snapshot_service=DomainErrorDeliverySnapshotService(),
    )

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.approve(
            approval_id=approval_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.DELIVERY_SNAPSHOT_NOT_READY
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "DeliveryChannel is not ready for delivery snapshot."
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, approval_id)
        run = session.get(PipelineRunModel, "run-1")
        assert approval is not None and approval.status is ApprovalStatus.PENDING
        assert run is not None and run.delivery_channel_snapshot_ref is None
        assert session.query(ApprovalDecisionModel).count() == 0


def test_approve_rolls_back_decision_snapshot_and_events_when_runtime_resume_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    approval_id = seed_waiting_approval(
        manager,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
    )
    runtime_port = FakeRuntimePort(fail_on_resume=True)
    runtime_session = manager.open_session(DatabaseRole.RUNTIME)
    event_session = manager.open_session(DatabaseRole.EVENT)
    snapshot_service = RecordingDeliverySnapshotService(runtime_session)
    control_session = manager.open_session(DatabaseRole.CONTROL)
    audit = RecordingAuditService()
    log_writer = RecordingRunLogWriter()
    service = ApprovalService(
        control_session=control_session,
        runtime_session=runtime_session,
        event_session=event_session,
        runtime_orchestration=RuntimeOrchestrationService(
            runtime_port=runtime_port,
            checkpoint_port=FakeCheckpointPort(),
            clock=lambda: NOW,
        ),
        audit_service=audit,
        delivery_snapshot_service=snapshot_service,
        log_writer=log_writer,
        now=lambda: NOW,
    )

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.approve(
            approval_id=approval_id,
            actor_id="session-user",
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, approval_id)
        run = session.get(PipelineRunModel, "run-1")
        assert approval is not None and approval.status is ApprovalStatus.PENDING
        assert session.query(ApprovalDecisionModel).count() == 0
        assert run is not None and run.delivery_channel_snapshot_ref is None
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0
    assert audit.records[-1]["action"] == "approval.approve.failed"
