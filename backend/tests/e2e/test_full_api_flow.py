from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProviderModel
from backend.app.db.models.event import EventBase
from backend.app.db.models.graph import GraphBase
from backend.app.db.models.log import LogBase
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    DeliveryChannelSnapshotModel,
    DeliveryRecordModel,
    ModelBindingSnapshotModel,
    PipelineRunModel,
    ProviderSnapshotModel,
    RuntimeBase,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.delivery.demo import DemoDeliveryAdapter
from backend.app.domain.enums import (
    ApprovalStatus,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    StageStatus,
    StageType,
    ToolRiskCategory,
)
from backend.app.domain.runtime_refs import (
    GraphThreadRef,
    GraphThreadStatus,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.main import create_app
from backend.app.observability.log_writer import LogRecordInput
from backend.app.runtime.base import (
    RuntimeExecutionContext,
    RuntimeInterrupt,
    RuntimeStepResult,
)
from backend.app.runtime.deterministic import (
    DETERMINISTIC_STAGE_SEQUENCE,
    DeterministicRuntimeEngine,
    DeterministicToolConfirmationConfig,
)
from backend.app.schemas import common
from backend.app.schemas.feed import ExecutionNodeProjection, ProviderCallStageItem
from backend.app.services.delivery import DeliveryRecordService, DeliveryService
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.graph_runtime import GraphCheckpointPort, GraphRuntimeCommandPort


NOW = datetime(2026, 5, 5, 9, 0, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def require_audit_record(self, **kwargs: Any) -> object:
        self.records.append({"method": "require_audit_record", **kwargs})
        return SimpleNamespace(audit_id=f"audit-{len(self.records)}")

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return SimpleNamespace(audit_id=f"audit-{len(self.records)}")

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return SimpleNamespace(audit_id=f"audit-{len(self.records)}")

    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_failed_command", **kwargs})
        return SimpleNamespace(audit_id=f"audit-{len(self.records)}")

    def record_blocked_action(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_blocked_action", **kwargs})
        return SimpleNamespace(audit_id=f"audit-{len(self.records)}")


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return SimpleNamespace(log_id=f"log-{len(self.records)}")


@dataclass
class FullFlowFixture:
    app: Any
    client_context: TestClient
    client: TestClient
    session_id: str
    run_id: str
    first_stage_run_id: str
    audit: RecordingAuditService
    log_writer: RecordingRunLogWriter


def seedFullFlowFixture(
    tmp_path: Path,
) -> tuple[
    Any,
    RecordingAuditService,
    RecordingRunLogWriter,
]:
    default_root = tmp_path / "ai-devflow-engine"
    default_root.mkdir()
    app = create_app(
        EnvironmentSettings(
            platform_runtime_root=tmp_path / "runtime",
            default_project_root=default_root,
        )
    )
    ControlBase.metadata.create_all(
        app.state.database_manager.engine(DatabaseRole.CONTROL)
    )
    RuntimeBase.metadata.create_all(
        app.state.database_manager.engine(DatabaseRole.RUNTIME)
    )
    GraphBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.GRAPH))
    EventBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.EVENT))
    LogBase.metadata.create_all(app.state.database_manager.engine(DatabaseRole.LOG))
    audit = RecordingAuditService()
    log_writer = RecordingRunLogWriter()
    app.state.h44_audit_service = audit
    app.state.h44_tool_confirmation_audit_service = audit
    app.state.h44a_audit_service = audit
    app.state.h43_audit_service = audit
    return app, audit, log_writer


def configureRequiredProviders(app: Any) -> None:
    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        providers = (
            session.query(ProviderModel)
            .filter(
                ProviderModel.provider_id.in_(
                    ["provider-deepseek", "provider-volcengine"]
                )
            )
            .all()
        )
        assert {provider.provider_id for provider in providers} == {
            "provider-deepseek",
            "provider-volcengine",
        }
        for provider in providers:
            provider.is_configured = True
            provider.is_enabled = True
            session.add(provider)
        session.commit()


def startDeterministicRunFixture(tmp_path: Path) -> FullFlowFixture:
    app, audit, log_writer = seedFullFlowFixture(tmp_path)
    client_context = TestClient(app)
    client = client_context.__enter__()
    try:
        created = client.post("/api/projects/project-default/sessions")
        assert created.status_code == 201
        configureRequiredProviders(app)
        session_id = created.json()["session_id"]
        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={
                "message_type": "new_requirement",
                "content": "Build a deterministic delivery regression path.",
            },
            headers={
                "X-Request-ID": "req-full-flow-new-requirement",
                "X-Correlation-ID": "corr-full-flow",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["session"]["current_run_id"]
        assert body["session"]["latest_stage_type"] == "requirement_analysis"
        assert body["message_item"]["stage_run_id"]
        return FullFlowFixture(
            app=app,
            client_context=client_context,
            client=client,
            session_id=session_id,
            run_id=body["session"]["current_run_id"],
            first_stage_run_id=body["message_item"]["stage_run_id"],
            audit=audit,
            log_writer=log_writer,
        )
    except Exception:
        client_context.__exit__(None, None, None)
        raise


def assertWorkspaceMatchesRunState(
    *,
    workspace: dict[str, Any],
    timeline: dict[str, Any],
    run: PipelineRunModel,
    delivery_record: DeliveryRecordModel,
) -> None:
    assert workspace["session"]["current_run_id"] == run.run_id
    assert workspace["current_run_id"] == run.run_id
    assert workspace["session"]["status"] == run.status.value
    matching_runs = [item for item in workspace["runs"] if item["run_id"] == run.run_id]
    assert len(matching_runs) == 1
    assert matching_runs[0]["status"] == run.status.value
    assert matching_runs[0]["current_stage_type"] == timeline["current_stage_type"]
    assert workspace["current_stage_type"] == timeline["current_stage_type"]
    assert timeline["run_id"] == run.run_id
    assert timeline["session_id"] == run.session_id
    assert timeline["status"] == run.status.value
    assert any(
        entry["type"] == "delivery_result"
        and entry["delivery_record_id"] == delivery_record.delivery_record_id
        for entry in workspace["narrative_feed"]
    )
    assert any(
        entry["type"] == "delivery_result"
        and entry["delivery_record_id"] == delivery_record.delivery_record_id
        for entry in timeline["entries"]
    )


def _close_fixture(fixture: FullFlowFixture) -> None:
    fixture.client_context.__exit__(None, None, None)


def _clock() -> Callable[[], datetime]:
    ticks = iter(NOW + timedelta(milliseconds=index) for index in range(5000))
    return lambda: next(ticks)


def _build_trace(
    run: PipelineRunModel,
    stage_run_id: str | None = None,
) -> TraceContext:
    return TraceContext(
        request_id=f"request-{run.run_id}",
        trace_id=run.trace_id,
        correlation_id=f"correlation-{run.run_id}",
        span_id=f"span-{run.run_id}",
        parent_span_id=None,
        session_id=run.session_id,
        run_id=run.run_id,
        stage_run_id=stage_run_id,
        graph_thread_id=run.graph_thread_ref,
        created_at=NOW,
    )


def _thread_status(run: PipelineRunModel) -> GraphThreadStatus:
    return GraphThreadStatus(run.status.value)


def _build_context(app: Any, run_id: str) -> RuntimeExecutionContext:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, run_id)
        assert run is not None
        stage = (
            session.get(StageRunModel, run.current_stage_run_id)
            if run.current_stage_run_id is not None
            else None
        )
        provider_refs = [
            snapshot.snapshot_id
            for snapshot in session.query(ProviderSnapshotModel)
            .filter(ProviderSnapshotModel.run_id == run_id)
            .order_by(ProviderSnapshotModel.snapshot_id.asc())
            .all()
        ]
        model_binding_refs = [
            snapshot.snapshot_id
            for snapshot in session.query(ModelBindingSnapshotModel)
            .filter(ModelBindingSnapshotModel.run_id == run_id)
            .order_by(ModelBindingSnapshotModel.snapshot_id.asc())
            .all()
        ]
        assert provider_refs
        assert model_binding_refs
        stage_run_id = stage.stage_run_id if stage is not None else None
        stage_type = stage.stage_type if stage is not None else None
        return RuntimeExecutionContext(
            run_id=run.run_id,
            session_id=run.session_id,
            thread=GraphThreadRef(
                thread_id=run.graph_thread_ref,
                run_id=run.run_id,
                status=_thread_status(run),
                current_stage_run_id=stage_run_id,
                current_stage_type=stage_type,
            ),
            trace_context=_build_trace(run, stage_run_id),
            template_snapshot_ref=run.template_snapshot_ref,
            provider_snapshot_refs=provider_refs,
            model_binding_snapshot_refs=model_binding_refs,
            runtime_limit_snapshot_ref=run.runtime_limit_snapshot_ref,
            provider_call_policy_snapshot_ref=run.provider_call_policy_snapshot_ref,
            graph_definition_ref=run.graph_definition_ref,
            delivery_channel_snapshot_ref=run.delivery_channel_snapshot_ref,
            workspace_snapshot_ref=run.workspace_ref,
        )


def _build_engine(
    app: Any,
    runtime_session: Session,
    event_session: Session,
    audit: RecordingAuditService,
    log_writer: RecordingRunLogWriter,
) -> tuple[DeterministicRuntimeEngine, Session]:
    control_session = app.state.database_manager.session(DatabaseRole.CONTROL)
    delivery_record_service = DeliveryRecordService(
        runtime_session=runtime_session,
        audit_service=audit,
        log_writer=log_writer,
        auto_commit=False,
        now=_clock(),
    )
    delivery_service = DeliveryService(
        record_service=delivery_record_service,
        adapters=[
            DemoDeliveryAdapter(
                audit_service=audit,
                log_writer=log_writer,
                now=_clock(),
            )
        ],
        event_store=EventStore(event_session, now=_clock()),
        now=_clock(),
    )
    engine = DeterministicRuntimeEngine(
        control_session=control_session,
        runtime_session=runtime_session,
        event_session=event_session,
        audit_service=audit,
        delivery_service=delivery_service,
        log_writer=log_writer,
        now=_clock(),
    )
    return engine, control_session


def _advance_until_interrupt_or_stage_result(
    fixture: FullFlowFixture,
    *,
    configure: Callable[[DeterministicRuntimeEngine], None] | None = None,
) -> RuntimeInterrupt | RuntimeStepResult:
    runtime_session = fixture.app.state.database_manager.session(DatabaseRole.RUNTIME)
    graph_session = fixture.app.state.database_manager.session(DatabaseRole.GRAPH)
    event_session = fixture.app.state.database_manager.session(DatabaseRole.EVENT)
    engine, control_session = _build_engine(
        fixture.app,
        runtime_session,
        event_session,
        fixture.audit,
        fixture.log_writer,
    )
    try:
        if configure is not None:
            configure(engine)
        graph_clock = _clock()
        result = engine.run_next(
            context=_build_context(fixture.app, fixture.run_id),
            runtime_port=GraphRuntimeCommandPort(graph_session, now=graph_clock),
            checkpoint_port=GraphCheckpointPort(graph_session, now=graph_clock),
        )
        runtime_session.commit()
        graph_session.commit()
        event_session.commit()
        control_session.commit()
        assert isinstance(result, (RuntimeInterrupt, RuntimeStepResult))
        return result
    except Exception:
        runtime_session.rollback()
        graph_session.rollback()
        event_session.rollback()
        control_session.rollback()
        raise
    finally:
        runtime_session.close()
        graph_session.close()
        event_session.close()
        control_session.close()


def _approve_pending_approval(
    client: TestClient,
    app: Any,
    run_id: str,
) -> dict[str, Any]:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        approval = (
            session.query(ApprovalRequestModel)
            .filter(
                ApprovalRequestModel.run_id == run_id,
                ApprovalRequestModel.status == ApprovalStatus.PENDING,
            )
            .order_by(ApprovalRequestModel.requested_at.desc())
            .first()
        )
        assert approval is not None
        approval_id = approval.approval_id
    response = client.post(f"/api/approvals/{approval_id}/approve", json={})
    assert response.status_code == 200
    return response.json()


def _attach_demo_delivery_snapshot(app: Any, run_id: str) -> str:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, run_id)
        assert run is not None
        if run.delivery_channel_snapshot_ref:
            snapshot = session.get(
                DeliveryChannelSnapshotModel,
                run.delivery_channel_snapshot_ref,
            )
            assert snapshot is not None
            assert snapshot.delivery_mode is DeliveryMode.DEMO_DELIVERY
            return snapshot.delivery_channel_snapshot_id
        snapshot_id = f"delivery-snapshot-{run_id}"
        snapshot = DeliveryChannelSnapshotModel(
            delivery_channel_snapshot_id=snapshot_id,
            run_id=run.run_id,
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
        )
        run.delivery_channel_snapshot_ref = snapshot_id
        session.add_all([snapshot, run])
        session.commit()
        return snapshot_id


def _seed_tool_confirmation_trace(
    app: Any,
    confirmation_id: str,
    *,
    result_status: str,
) -> None:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        confirmation = session.get(ToolConfirmationRequestModel, confirmation_id)
        assert confirmation is not None
        artifact = StageArtifactModel(
            artifact_id=f"artifact-tool-confirmation-{confirmation_id}",
            run_id=confirmation.run_id,
            stage_run_id=confirmation.stage_run_id,
            artifact_type="tool_confirmation_trace",
            payload_ref=f"payload-tool-confirmation-{confirmation_id}",
            process={
                "tool_confirmation_id": confirmation.tool_confirmation_id,
                "confirmation_object_ref": confirmation.confirmation_object_ref,
                "tool_confirmation_trace_ref": (
                    f"process-tool-confirmation-{confirmation_id}"
                ),
                "tool_call_ref": confirmation.confirmation_object_ref,
                "tool_result_ref": f"tool-result-{confirmation_id}",
                "result_snapshot": {
                    "decision": (
                        confirmation.user_decision.value
                        if confirmation.user_decision is not None
                        else None
                    ),
                    "result_status": result_status,
                    "follow_up_result": result_status,
                    "tool_result_ref": f"tool-result-{confirmation_id}",
                },
                "log_refs": [f"log-tool-confirmation-{confirmation_id}"],
            },
            metrics={"tool_call_count": 1},
            created_at=NOW + timedelta(minutes=10),
        )
        confirmation.process_ref = f"process-tool-confirmation-{confirmation_id}"
        session.add_all([artifact, confirmation])
        session.commit()


def _seed_provider_retry_trace(app: Any, run_id: str, stage_run_id: str) -> None:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, stage_run_id)
        assert stage is not None
        artifact = (
            session.query(StageArtifactModel)
            .filter(
                StageArtifactModel.run_id == run_id,
                StageArtifactModel.stage_run_id == stage_run_id,
            )
            .order_by(StageArtifactModel.created_at.asc())
            .first()
        )
        assert artifact is not None
        process = dict(artifact.process)
        process["provider_retry_trace_ref"] = "artifact-provider-retry-trace-full-flow"
        process["provider_circuit_breaker_trace_ref"] = (
            "artifact-provider-circuit-breaker-trace-full-flow"
        )
        artifact.process = process
        session.add(artifact)
        session.commit()

    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, stage_run_id)
        assert stage is not None
        started_at = stage.started_at

    with app.state.database_manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW + timedelta(minutes=11),
        )
        store.append(
            DomainEventType.PROVIDER_CALL_RETRIED,
            payload={
                "stage_node": ExecutionNodeProjection(
                    entry_id="entry-provider-retry-full-flow",
                    run_id=run_id,
                    occurred_at=NOW + timedelta(minutes=11),
                    stage_run_id=stage_run_id,
                    stage_type=common.StageType.CODE_GENERATION,
                    status=common.StageStatus.WAITING_TOOL_CONFIRMATION,
                    attempt_index=1,
                    started_at=started_at,
                    ended_at=None,
                    summary="Code Generation is retrying a provider call.",
                    items=[
                        ProviderCallStageItem(
                            item_id="provider-call-retry-full-flow",
                            type=common.StageItemType.PROVIDER_CALL,
                            occurred_at=NOW + timedelta(minutes=11),
                            title="Provider retry",
                            summary="Network retry scheduled.",
                            content=None,
                            artifact_refs=[
                                "provider-retry-trace-full-flow",
                                "provider-circuit-breaker-trace-full-flow",
                            ],
                            metrics={},
                            provider_id="provider-deepseek",
                            model_id="deepseek-chat",
                            status="retrying",
                            retry_attempt=1,
                            max_retry_attempts=2,
                            backoff_wait_seconds=5,
                            circuit_breaker_status=(
                                common.ProviderCircuitBreakerStatus.CLOSED
                            ),
                            failure_reason="network_error",
                            process_ref="provider-retry-trace-full-flow",
                        )
                    ],
                    metrics={},
                ).model_dump(mode="json")
            },
            trace_context=TraceContext(
                request_id="request-provider-retry-full-flow",
                trace_id=f"trace-provider-retry-{run_id}",
                correlation_id="correlation-provider-retry-full-flow",
                span_id="span-provider-retry-full-flow",
                parent_span_id=None,
                session_id=_session_id_for_run(app, run_id),
                run_id=run_id,
                stage_run_id=stage_run_id,
                created_at=NOW + timedelta(minutes=11),
            ),
            session_id=_session_id_for_run(app, run_id),
            run_id=run_id,
            stage_run_id=stage_run_id,
        )
        session.commit()


def _api_get(client: TestClient, path: str) -> dict[str, Any]:
    response = client.get(path)
    assert response.status_code == 200
    return response.json()


def _latest_delivery_record(app: Any, run_id: str) -> DeliveryRecordModel:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        record = (
            session.query(DeliveryRecordModel)
            .filter(DeliveryRecordModel.run_id == run_id)
            .order_by(DeliveryRecordModel.created_at.desc())
            .first()
        )
        assert record is not None
        session.expunge(record)
        return record


def _session_id_for_run(app: Any, run_id: str) -> str:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, run_id)
        assert run is not None
        return run.session_id


def _run(app: Any, run_id: str) -> PipelineRunModel:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        run = session.get(PipelineRunModel, run_id)
        assert run is not None
        session.expunge(run)
        return run


def _assert_feed_contains_types(entries: list[dict[str, Any]], types: set[str]) -> None:
    present = {entry["type"] for entry in entries}
    assert types <= present


def _configure_full_path(engine: DeterministicRuntimeEngine) -> None:
    engine.configure_interrupts(
        solution_design_approval=True,
        code_review_approval=True,
        tool_confirmation=DeterministicToolConfirmationConfig(
            stage_type=StageType.CODE_GENERATION,
            tool_name="bash",
            command_preview="Remove-Item -Recurse build",
            target_summary="Deletes generated build outputs.",
            risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE],
            reason="The deterministic fixture requires a high-risk command.",
            expected_side_effects=["Deletes generated build outputs."],
            alternative_path_summary="Continue with deterministic fallback output.",
            planned_deny_followup_action="continue_current_stage",
            planned_deny_followup_summary=(
                "Code Generation will continue with a low-risk fallback."
            ),
        ),
    )


def _configure_tool_only(engine: DeterministicRuntimeEngine) -> None:
    engine.configure_interrupts(
        tool_confirmation=DeterministicToolConfirmationConfig(
            stage_type=StageType.CODE_GENERATION,
            tool_name="bash",
            command_preview="Remove-Item -Recurse build",
            target_summary="Deletes generated build outputs.",
            risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE],
            reason="The deterministic fixture requires a high-risk command.",
            expected_side_effects=["Deletes generated build outputs."],
            alternative_path_summary="Continue with deterministic fallback output.",
            planned_deny_followup_action="continue_current_stage",
            planned_deny_followup_summary=(
                "Code Generation will continue with a low-risk fallback."
            ),
        )
    )


def test_full_api_flow_reaches_delivery_result_and_keeps_projections_consistent(
    tmp_path: Path,
) -> None:
    fixture = startDeterministicRunFixture(tmp_path)
    try:
        with fixture.app.state.database_manager.session(
            DatabaseRole.RUNTIME
        ) as session:
            first_stage = session.get(StageRunModel, fixture.first_stage_run_id)
            assert first_stage is not None
            assert first_stage.stage_type is StageType.REQUIREMENT_ANALYSIS

        requirement_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(requirement_result, RuntimeStepResult)
        assert requirement_result.stage_type is StageType.REQUIREMENT_ANALYSIS
        solution_interrupt = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(solution_interrupt, RuntimeInterrupt)
        assert solution_interrupt.stage_type is StageType.SOLUTION_DESIGN

        solution_approval = _approve_pending_approval(
            fixture.client,
            fixture.app,
            fixture.run_id,
        )
        assert solution_approval["approval_result"]["decision"] == "approved"

        solution_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(solution_result, RuntimeStepResult)
        assert solution_result.stage_type is StageType.SOLUTION_DESIGN
        tool_interrupt = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(tool_interrupt, RuntimeInterrupt)
        assert tool_interrupt.stage_type is StageType.CODE_GENERATION
        tool_confirmation_id = tool_interrupt.interrupt_ref.tool_confirmation_id
        assert tool_confirmation_id is not None

        workspace_waiting = _api_get(
            fixture.client,
            f"/api/sessions/{fixture.session_id}/workspace",
        )
        timeline_waiting = _api_get(
            fixture.client,
            f"/api/runs/{fixture.run_id}/timeline",
        )
        pending_tool_entries = [
            entry
            for entry in workspace_waiting["narrative_feed"]
            if entry["type"] == "tool_confirmation"
            and entry["tool_confirmation_id"] == tool_confirmation_id
        ]
        assert len(pending_tool_entries) == 1
        assert pending_tool_entries[0]["status"] == "pending"
        assert any(
            entry["type"] == "tool_confirmation"
            and entry["tool_confirmation_id"] == tool_confirmation_id
            for entry in timeline_waiting["entries"]
        )

        allow_response = fixture.client.post(
            f"/api/tool-confirmations/{tool_confirmation_id}/allow",
            json={},
        )
        assert allow_response.status_code == 200
        allowed = allow_response.json()["tool_confirmation"]
        assert allowed["status"] == "allowed"
        assert allowed["decision"] == "allowed"
        _seed_tool_confirmation_trace(
            fixture.app,
            tool_confirmation_id,
            result_status="allowed",
        )
        allowed_detail = _api_get(
            fixture.client,
            f"/api/tool-confirmations/{tool_confirmation_id}",
        )
        assert allowed_detail["tool_confirmation_id"] == tool_confirmation_id
        assert allowed_detail["run_id"] == fixture.run_id
        assert allowed_detail["stage_run_id"] == tool_interrupt.stage_run_id
        assert allowed_detail["status"] == "allowed"
        assert allowed_detail["decision"] == "allowed"
        assert allowed_detail["input"]["records"]["risk_level"] == "high_risk"
        assert "file_delete_or_move" in allowed_detail["input"]["records"][
            "risk_categories"
        ]
        assert (
            f"process-tool-confirmation-{tool_confirmation_id}"
            in allowed_detail["process"]["records"]["tool_confirmation_trace_refs"]
        )
        assert allowed_detail["process"]["records"]["tool_result_refs"] == [
            f"tool-result-{tool_confirmation_id}"
        ]
        assert allowed_detail["output"]["records"]["tool_result_refs"] == [
            f"tool-result-{tool_confirmation_id}"
        ]
        assert allowed_detail["output"]["records"]["result_status"] == "allowed"

        code_generation_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(code_generation_result, RuntimeStepResult)
        assert code_generation_result.stage_type is StageType.CODE_GENERATION
        test_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(test_result, RuntimeStepResult)
        assert test_result.stage_type is StageType.TEST_GENERATION_EXECUTION
        review_interrupt = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(review_interrupt, RuntimeInterrupt)
        assert review_interrupt.stage_type is StageType.CODE_REVIEW

        review_approval = _approve_pending_approval(
            fixture.client,
            fixture.app,
            fixture.run_id,
        )
        assert review_approval["approval_result"]["decision"] == "approved"
        _attach_demo_delivery_snapshot(fixture.app, fixture.run_id)

        review_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(review_result, RuntimeStepResult)
        assert review_result.stage_type is StageType.CODE_REVIEW
        delivery_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(delivery_result, RuntimeStepResult)
        assert delivery_result.stage_type is StageType.DELIVERY_INTEGRATION

        delivery_record = _latest_delivery_record(fixture.app, fixture.run_id)
        assert delivery_record.delivery_mode is DeliveryMode.DEMO_DELIVERY
        assert delivery_record.status == "succeeded"
        assert delivery_record.commit_sha is None
        assert delivery_record.code_review_url is None

        with fixture.app.state.database_manager.session(
            DatabaseRole.RUNTIME
        ) as session:
            stages = (
                session.query(StageRunModel)
                .filter(StageRunModel.run_id == fixture.run_id)
                .all()
            )
            stages_by_type = {stage.stage_type: stage for stage in stages}
            assert len(stages_by_type) == len(DETERMINISTIC_STAGE_SEQUENCE)
            assert set(stages_by_type) == set(DETERMINISTIC_STAGE_SEQUENCE)
            for stage_type in DETERMINISTIC_STAGE_SEQUENCE:
                assert stages_by_type[stage_type].status is StageStatus.COMPLETED

        workspace = _api_get(
            fixture.client,
            f"/api/sessions/{fixture.session_id}/workspace",
        )
        timeline = _api_get(fixture.client, f"/api/runs/{fixture.run_id}/timeline")
        delivery_detail = _api_get(
            fixture.client,
            f"/api/delivery-records/{delivery_record.delivery_record_id}",
        )
        delivery_stage_inspector = _api_get(
            fixture.client,
            f"/api/stages/{delivery_result.stage_run_id}/inspector",
        )

        _assert_feed_contains_types(
            workspace["narrative_feed"],
            {
                "approval_request",
                "approval_result",
                "tool_confirmation",
                "delivery_result",
            },
        )
        _assert_feed_contains_types(
            timeline["entries"],
            {
                "approval_request",
                "approval_result",
                "tool_confirmation",
                "delivery_result",
            },
        )
        assertWorkspaceMatchesRunState(
            workspace=workspace,
            timeline=timeline,
            run=_run(fixture.app, fixture.run_id),
            delivery_record=delivery_record,
        )
        assert delivery_detail["delivery_record_id"] == (
            delivery_record.delivery_record_id
        )
        assert delivery_detail["run_id"] == fixture.run_id
        assert delivery_detail["delivery_mode"] == "demo_delivery"
        assert delivery_detail["status"] == "succeeded"
        assert (
            delivery_detail["process"]["records"]["delivery_process"][
                "delivery_record_id"
            ]
            == delivery_record.delivery_record_id
        )
        assert delivery_detail["process"]["records"]["no_git_actions"] is True
        snapshot = delivery_detail["input"]["records"]["delivery_channel_snapshot"]
        assert snapshot["delivery_mode"] == "demo_delivery"
        assert snapshot["scm_provider_type"] is None
        assert snapshot["repository_identifier"] is None
        assert snapshot["default_branch"] is None
        assert snapshot["code_review_request_type"] is None

        assert delivery_stage_inspector["stage_run_id"] == delivery_result.stage_run_id
        assert delivery_stage_inspector["run_id"] == fixture.run_id
        assert delivery_stage_inspector["stage_type"] == "delivery_integration"
        assert delivery_stage_inspector["status"] == "completed"
        assert delivery_stage_inspector["identity"]["records"]["output_ref"] == (
            delivery_result.artifact_refs[0]
        )
        assert delivery_stage_inspector["output"]["records"]["output_ref"] == (
            delivery_result.artifact_refs[0]
        )
        assert delivery_stage_inspector["artifacts"]["records"]["artifact_refs"] == (
            delivery_result.artifact_refs
        )
    finally:
        _close_fixture(fixture)


def test_full_api_flow_covers_tool_confirmation_deny_and_provider_retry_inspector(
    tmp_path: Path,
) -> None:
    fixture = startDeterministicRunFixture(tmp_path)
    try:
        requirement_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_tool_only,
        )
        assert isinstance(requirement_result, RuntimeStepResult)
        solution_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_tool_only,
        )
        assert isinstance(solution_result, RuntimeStepResult)
        tool_interrupt = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_tool_only,
        )
        assert isinstance(tool_interrupt, RuntimeInterrupt)
        assert tool_interrupt.stage_type is StageType.CODE_GENERATION
        tool_confirmation_id = tool_interrupt.interrupt_ref.tool_confirmation_id
        assert tool_confirmation_id is not None

        _seed_provider_retry_trace(
            fixture.app,
            fixture.run_id,
            tool_interrupt.stage_run_id,
        )

        deny_response = fixture.client.post(
            f"/api/tool-confirmations/{tool_confirmation_id}/deny",
            json={"reason": "Risk is not acceptable."},
        )
        assert deny_response.status_code == 200
        denied = deny_response.json()["tool_confirmation"]
        assert denied["status"] == "denied"
        assert denied["decision"] == "denied"
        assert denied["deny_followup_action"] == "continue_current_stage"
        assert denied["deny_followup_summary"] == (
            "Code Generation will continue with a low-risk fallback."
        )
        _seed_tool_confirmation_trace(
            fixture.app,
            tool_confirmation_id,
            result_status="denied",
        )

        workspace = _api_get(
            fixture.client,
            f"/api/sessions/{fixture.session_id}/workspace",
        )
        timeline = _api_get(fixture.client, f"/api/runs/{fixture.run_id}/timeline")
        workspace_tool_confirmation = next(
            entry
            for entry in workspace["narrative_feed"]
            if entry["type"] == "tool_confirmation"
            and entry["tool_confirmation_id"] == tool_confirmation_id
        )
        timeline_tool_confirmation = next(
            entry
            for entry in timeline["entries"]
            if entry["type"] == "tool_confirmation"
            and entry["tool_confirmation_id"] == tool_confirmation_id
        )
        for entry in (workspace_tool_confirmation, timeline_tool_confirmation):
            assert entry["status"] == "denied"
            assert entry["decision"] == "denied"
            assert entry["deny_followup_action"] == "continue_current_stage"
            assert entry["deny_followup_summary"] == (
                "Code Generation will continue with a low-risk fallback."
            )

        denied_detail = _api_get(
            fixture.client,
            f"/api/tool-confirmations/{tool_confirmation_id}",
        )
        assert denied_detail["tool_confirmation_id"] == tool_confirmation_id
        assert denied_detail["run_id"] == fixture.run_id
        assert denied_detail["stage_run_id"] == tool_interrupt.stage_run_id
        assert denied_detail["status"] == "denied"
        assert denied_detail["decision"] == "denied"
        assert denied_detail["input"]["records"]["risk_level"] == "high_risk"
        assert "file_delete_or_move" in denied_detail["input"]["records"][
            "risk_categories"
        ]
        assert (
            f"process-tool-confirmation-{tool_confirmation_id}"
            in denied_detail["process"]["records"]["tool_confirmation_trace_refs"]
        )
        assert denied_detail["process"]["records"]["tool_result_refs"] == [
            f"tool-result-{tool_confirmation_id}"
        ]
        assert denied_detail["output"]["records"]["tool_result_refs"] == [
            f"tool-result-{tool_confirmation_id}"
        ]
        assert denied_detail["output"]["records"]["result_status"] == "denied"

        inspector = _api_get(
            fixture.client,
            f"/api/stages/{tool_interrupt.stage_run_id}/inspector",
        )
        assert "artifact-provider-retry-trace-full-flow" in inspector[
            "provider_retry_trace_refs"
        ]
        assert "provider-retry-trace-full-flow" in inspector[
            "provider_retry_trace_refs"
        ]
        assert "artifact-provider-circuit-breaker-trace-full-flow" in inspector[
            "provider_circuit_breaker_trace_refs"
        ]
        assert "provider-circuit-breaker-trace-full-flow" in inspector[
            "provider_circuit_breaker_trace_refs"
        ]
        provider_call = next(
            call
            for call in inspector["process"]["records"]["provider_calls"]
            if call["item_id"] == "provider-call-retry-full-flow"
        )
        assert provider_call["status"] == "retrying"
        assert provider_call["retry_attempt"] == 1
        assert provider_call["max_retry_attempts"] == 2
        assert provider_call["failure_reason"] == "network_error"
    finally:
        _close_fixture(fixture)
