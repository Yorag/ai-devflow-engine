from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.services.approvals import ApprovalService, ApprovalServiceError
from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole, ROLE_METADATA
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ApprovalRequestModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeLimitSnapshotModel,
    StageRunModel,
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
)
from backend.app.domain.runtime_refs import (
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService


NOW = datetime(2026, 5, 3, 9, 0, 0, tzinfo=UTC)


class ApprovalTestDatabaseManager:
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


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FailingRunLogWriter(RecordingRunLogWriter):
    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        raise RuntimeError("run log write failed")


class FakeCheckpointPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def save_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        self.calls.append(("save_checkpoint", kwargs))
        thread = kwargs["thread"]
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{kwargs['payload_ref']}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=kwargs["stage_run_id"],
            stage_type=kwargs["stage_type"],
            purpose=kwargs["purpose"],
            workspace_snapshot_ref=kwargs.get("workspace_snapshot_ref"),
            payload_ref=kwargs["payload_ref"],
        )

    def load_checkpoint(self, **kwargs: Any) -> CheckpointRef:
        self.calls.append(("load_checkpoint", kwargs))
        return kwargs["checkpoint"]


class FakeRuntimePort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        self.calls.append(("create_interrupt", kwargs))
        approval_id = kwargs["approval_id"]
        return GraphInterruptRef(
            interrupt_id=f"interrupt-{approval_id}",
            thread=kwargs["thread"],
            interrupt_type=kwargs["interrupt_type"],
            status=GraphInterruptStatus.PENDING,
            run_id=kwargs["run_id"],
            stage_run_id=kwargs["stage_run_id"],
            stage_type=kwargs["stage_type"],
            payload_ref=kwargs["payload_ref"],
            approval_id=approval_id,
            checkpoint_ref=kwargs["checkpoint"],
        )


class FailingRuntimePort(FakeRuntimePort):
    def create_interrupt(self, **kwargs: Any) -> GraphInterruptRef:
        self.calls.append(("create_interrupt", kwargs))
        raise RuntimeError("runtime interrupt failed")


def build_manager(tmp_path: Path) -> ApprovalTestDatabaseManager:
    return ApprovalTestDatabaseManager(tmp_path)


def build_trace(*, stage_run_id: str) -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="root",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id=stage_run_id,
        created_at=NOW,
    )


def build_service(
    manager: ApprovalTestDatabaseManager,
    *,
    runtime_port: FakeRuntimePort | None = None,
    log_writer: RecordingRunLogWriter | None = None,
) -> tuple[ApprovalService, FakeRuntimePort, RecordingRunLogWriter]:
    resolved_runtime_port = runtime_port or FakeRuntimePort()
    resolved_log_writer = log_writer or RecordingRunLogWriter()
    service = ApprovalService(
        control_session=manager.open_session(DatabaseRole.CONTROL),
        runtime_session=manager.open_session(DatabaseRole.RUNTIME),
        event_session=manager.open_session(DatabaseRole.EVENT),
        runtime_orchestration=RuntimeOrchestrationService(
            runtime_port=resolved_runtime_port,
            checkpoint_port=FakeCheckpointPort(),
            clock=lambda: NOW,
        ),
        log_writer=resolved_log_writer,
        now=lambda: NOW,
    )
    return service, resolved_runtime_port, resolved_log_writer


def seed_running_stage(
    manager: ApprovalTestDatabaseManager,
    *,
    stage_type: StageType,
    latest_stage_type: StageType | None = None,
) -> None:
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
                latest_stage_type=latest_stage_type or stage_type,
                is_visible=True,
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
                    schema_version="1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-policy-1",
                    run_id="run-1",
                    provider_call_policy={},
                    source_config_version="test",
                    schema_version="1",
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
                    graph_thread_ref="thread-1",
                    workspace_ref="workspace-1",
                    runtime_limit_snapshot_ref="runtime-limits-1",
                    provider_call_policy_snapshot_ref="provider-policy-1",
                    delivery_channel_snapshot_ref=None,
                    current_stage_run_id="stage-run-1",
                    trace_id="trace-1",
                    started_at=NOW,
                    ended_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                StageRunModel(
                    stage_run_id="stage-run-1",
                    run_id="run-1",
                    stage_type=stage_type,
                    status=StageStatus.RUNNING,
                    attempt_index=1,
                    graph_node_key=f"{stage_type.value}.main",
                    stage_contract_ref=f"stage-contract-{stage_type.value}",
                    input_ref=None,
                    output_ref=None,
                    summary=None,
                    started_at=NOW,
                    ended_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )


def test_create_solution_design_approval_creates_request_interrupt_event_waiting_state_and_logs(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.SOLUTION_DESIGN)
    service, runtime_port, log_writer = build_service(manager)

    result = service.create_solution_design_approval(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        payload_ref="solution-design-artifact-1",
        approval_object_excerpt="Review the proposed design.",
        risk_excerpt="Touches runtime orchestration.",
        approval_object_preview={"artifact_id": "solution-design-artifact-1"},
        trace_context=build_trace(stage_run_id="stage-run-1"),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, result.approval_id)
        run = session.get(PipelineRunModel, "run-1")
        stage = session.get(StageRunModel, "stage-run-1")
        decision_count = session.query(ApprovalDecisionModel).count()
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.APPROVAL_REQUESTED)
            .one()
        )

    assert approval is not None
    assert approval.approval_type is ApprovalType.SOLUTION_DESIGN_APPROVAL
    assert approval.status is ApprovalStatus.PENDING
    assert approval.run_id == "run-1"
    assert approval.stage_run_id == "stage-run-1"
    assert approval.payload_ref == "solution-design-artifact-1"
    assert approval.graph_interrupt_ref == f"interrupt-{approval.approval_id}"
    assert approval.resolved_at is None
    assert run is not None and run.status is RunStatus.WAITING_APPROVAL
    assert stage is not None and stage.status is StageStatus.WAITING_APPROVAL
    assert control_session is not None
    assert control_session.status is SessionStatus.WAITING_APPROVAL
    assert control_session.latest_stage_type is StageType.SOLUTION_DESIGN
    assert decision_count == 0
    assert runtime_port.calls[0][0] == "create_interrupt"
    assert runtime_port.calls[0][1]["interrupt_type"] is GraphInterruptType.APPROVAL
    assert runtime_port.calls[0][1]["approval_id"] == approval.approval_id
    assert runtime_port.calls[0][1]["payload_ref"] == "solution-design-artifact-1"
    assert runtime_port.calls[0][1]["trace_context"].approval_id == approval.approval_id
    assert runtime_port.calls[0][1]["trace_context"].graph_thread_id == "thread-1"
    assert event.payload["approval_request"]["approval_id"] == approval.approval_id
    assert event.payload["approval_request"]["type"] == "approval_request"
    assert event.payload["approval_request"]["is_actionable"] is True
    assert event.payload["approval_request"]["disabled_reason"] is None
    assert event.payload["approval_request"]["delivery_readiness_status"] is None
    assert event.payload["approval_request"]["open_settings_action"] is None
    assert [record.message for record in log_writer.records] == [
        "Approval interrupt created.",
        "Approval request object created.",
    ]
    assert [record.trace_context.approval_id for record in log_writer.records] == [
        approval.approval_id,
        approval.approval_id,
    ]
    assert [record.trace_context.graph_thread_id for record in log_writer.records] == [
        "thread-1",
        "thread-1",
    ]


def test_create_code_review_approval_uses_code_review_type_and_reject_target_projection(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.CODE_REVIEW)
    service, _runtime_port, _log_writer = build_service(manager)

    result = service.create_code_review_approval(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        payload_ref="code-review-artifact-1",
        approval_object_excerpt="Review code changes and tests.",
        risk_excerpt="One test gap remains documented.",
        approval_object_preview={"artifact_id": "code-review-artifact-1"},
        trace_context=build_trace(stage_run_id="stage-run-1"),
    )

    assert result.approval_request.approval_type is ApprovalType.CODE_REVIEW_APPROVAL
    assert result.approval_request.title == "Review code review result"
    assert result.approval_request.approve_action == "approve"
    assert result.approval_request.reject_action == "reject"

    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, result.approval_id)
    assert approval is not None
    assert approval.approval_type is ApprovalType.CODE_REVIEW_APPROVAL


def test_create_solution_design_approval_rejects_wrong_stage_before_interrupt(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.CODE_GENERATION)
    service, runtime_port, log_writer = build_service(manager)

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.create_solution_design_approval(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            payload_ref="solution-design-artifact-1",
            approval_object_excerpt="Review the proposed design.",
            risk_excerpt=None,
            approval_object_preview={},
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.status_code == 409
    assert "solution_design" in exc_info.value.message
    assert runtime_port.calls == []
    assert log_writer.records == []


def test_create_approval_rolls_back_when_runtime_interrupt_fails_and_logs_failure(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.SOLUTION_DESIGN)
    service, runtime_port, log_writer = build_service(
        manager,
        runtime_port=FailingRuntimePort(),
    )

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.create_solution_design_approval(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            payload_ref="solution-design-artifact-1",
            approval_object_excerpt="Review the proposed design.",
            risk_excerpt=None,
            approval_object_preview={},
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    assert runtime_port.calls[0][0] == "create_interrupt"
    assert [record.message for record in log_writer.records] == [
        "Approval interrupt creation failed.",
    ]
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(ApprovalRequestModel).count() == 0
        assert session.get(PipelineRunModel, "run-1").status is RunStatus.RUNNING
        assert session.get(StageRunModel, "stage-run-1").status is StageStatus.RUNNING
    with manager.session(DatabaseRole.EVENT) as session:
        assert session.query(DomainEventModel).count() == 0


def test_create_approval_keeps_stable_error_when_failure_log_write_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.SOLUTION_DESIGN)
    service, _runtime_port, log_writer = build_service(
        manager,
        runtime_port=FailingRuntimePort(),
        log_writer=FailingRunLogWriter(),
    )

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.create_solution_design_approval(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            payload_ref="solution-design-artifact-1",
            approval_object_excerpt="Review the proposed design.",
            risk_excerpt=None,
            approval_object_preview={},
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR
    assert exc_info.value.message == "runtime interrupt failed for approval request."
    assert [record.message for record in log_writer.records] == [
        "Approval interrupt creation failed.",
    ]
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(ApprovalRequestModel).count() == 0
        assert session.get(PipelineRunModel, "run-1").status is RunStatus.RUNNING
        assert session.get(StageRunModel, "stage-run-1").status is StageStatus.RUNNING


def test_create_approval_does_not_rollback_domain_state_when_success_log_write_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.SOLUTION_DESIGN)
    service, _runtime_port, log_writer = build_service(
        manager,
        log_writer=FailingRunLogWriter(),
    )

    result = service.create_solution_design_approval(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        payload_ref="solution-design-artifact-1",
        approval_object_excerpt="Review the proposed design.",
        risk_excerpt=None,
        approval_object_preview={},
        trace_context=build_trace(stage_run_id="stage-run-1"),
    )

    assert [record.message for record in log_writer.records] == [
        "Approval interrupt created.",
        "Approval request object created.",
    ]
    with manager.session(DatabaseRole.RUNTIME) as session:
        approval = session.get(ApprovalRequestModel, result.approval_id)
        assert approval is not None
        assert approval.status is ApprovalStatus.PENDING
        assert session.get(PipelineRunModel, "run-1").status is (
            RunStatus.WAITING_APPROVAL
        )
        assert session.get(StageRunModel, "stage-run-1").status is (
            StageStatus.WAITING_APPROVAL
        )
    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        assert control_session.status is SessionStatus.WAITING_APPROVAL
    with manager.session(DatabaseRole.EVENT) as session:
        event = (
            session.query(DomainEventModel)
            .filter(DomainEventModel.event_type == SseEventType.APPROVAL_REQUESTED)
            .one()
        )
        assert event.payload["approval_request"]["approval_id"] == result.approval_id


def test_create_approval_rejects_duplicate_pending_approval_for_same_stage(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_running_stage(manager, stage_type=StageType.SOLUTION_DESIGN)
    service, _runtime_port, _log_writer = build_service(manager)

    service.create_solution_design_approval(
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        payload_ref="solution-design-artifact-1",
        approval_object_excerpt="Review the proposed design.",
        risk_excerpt=None,
        approval_object_preview={},
        trace_context=build_trace(stage_run_id="stage-run-1"),
    )

    with pytest.raises(ApprovalServiceError) as exc_info:
        service.create_solution_design_approval(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            payload_ref="solution-design-artifact-2",
            approval_object_excerpt="Review again.",
            risk_excerpt=None,
            approval_object_preview={},
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    assert exc_info.value.status_code == 409
    assert "pending approval" in exc_info.value.message
