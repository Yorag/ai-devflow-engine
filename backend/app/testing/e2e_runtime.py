from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError
from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.runtime import (
    ModelBindingSnapshotModel,
    PipelineRunModel,
    ProviderSnapshotModel,
    StageRunModel,
)
from backend.app.delivery.demo import DemoDeliveryAdapter
from backend.app.domain.enums import (
    RunStatus,
    StageStatus,
    StageType,
    ToolRiskCategory,
)
from backend.app.domain.runtime_refs import (
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.main import create_app
from backend.app.observability.audit import AuditService
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.runtime.base import (
    RuntimeExecutionContext,
    RuntimeInterrupt,
    RuntimeStepResult,
)
from backend.app.runtime.deterministic import (
    DeterministicRuntimeEngine,
    DeterministicToolConfirmationConfig,
)
from backend.app.services.graph_runtime import (
    GraphCheckpointPort,
    GraphRuntimeCommandPort,
)
from backend.app.testing.runtime_ports import (
    InMemoryCheckpointPort,
    InMemoryRuntimeCommandPort,
)
from backend.app.services.delivery import DeliveryRecordService, DeliveryService
from backend.app.services.events import EventStore


_ACTIVE_STAGE_STATUSES = frozenset(
    {
        StageStatus.RUNNING,
        StageStatus.WAITING_CLARIFICATION,
        StageStatus.WAITING_APPROVAL,
        StageStatus.WAITING_TOOL_CONFIRMATION,
    }
)


class AdvanceRuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["next"] = "next"


class AdvanceRuntimeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_id: str
    stage_run_id: str
    stage_type: StageType
    run_status: RunStatus
    result_type: Literal["stage_result", "interrupt"]
    interrupt_type: str | None = None
    approval_id: str | None = None
    tool_confirmation_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    domain_event_refs: list[str] = Field(default_factory=list)
    checkpoint_id: str | None = None


@dataclass
class _OpenSessions:
    control: Session
    runtime: Session
    graph: Session
    event: Session
    log: Session

    def commit(self) -> None:
        self.runtime.commit()
        self.graph.commit()
        self.event.commit()
        self.control.commit()
        self.log.commit()

    def rollback(self) -> None:
        self.runtime.rollback()
        self.graph.rollback()
        self.event.rollback()
        self.control.rollback()
        self.log.rollback()

    def close(self) -> None:
        self.runtime.close()
        self.graph.close()
        self.event.close()
        self.control.close()
        self.log.close()


def create_e2e_test_app(settings: EnvironmentSettings | None = None) -> FastAPI:
    app = create_app(settings)
    app.include_router(
        build_deterministic_runtime_advancement_router(),
        prefix="/__test__/runtime",
        include_in_schema=False,
    )
    return app


def build_deterministic_runtime_advancement_router() -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.post(
        "/runs/{runId}/advance",
        response_model=AdvanceRuntimeResponse,
        include_in_schema=False,
    )
    def advance_runtime(
        runId: str,
        body: AdvanceRuntimeRequest,
        request: Request,
    ) -> AdvanceRuntimeResponse:
        del body
        harness = DeterministicRuntimeAdvancementHarness(request.app)
        return harness.advance_next(runId)

    return router


class DeterministicRuntimeAdvancementHarness:
    def __init__(
        self,
        app: FastAPI,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._app = app
        self._now = now or (lambda: datetime.now(UTC))

    def advance_next(self, run_id: str) -> AdvanceRuntimeResponse:
        sessions = self._open_sessions()
        try:
            run = sessions.runtime.get(PipelineRunModel, run_id)
            if run is None:
                raise ApiError(ErrorCode.NOT_FOUND, "PipelineRun was not found.", 404)
            self._assert_advanceable(run, sessions.runtime)
            engine = self._build_engine(sessions)
            self._configure_engine(engine)
            result = engine.run_next(
                context=self._build_context(run_id, sessions.runtime),
                runtime_port=self._runtime_port(sessions),
                checkpoint_port=self._checkpoint_port(sessions),
            )
            response = self._to_response(result, sessions.runtime)
            sessions.commit()
            return response
        except ApiError:
            sessions.rollback()
            raise
        except ValueError as exc:
            sessions.rollback()
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                409,
            ) from exc
        except Exception:
            sessions.rollback()
            raise
        finally:
            sessions.close()

    def _open_sessions(self) -> _OpenSessions:
        manager = self._app.state.database_manager
        return _OpenSessions(
            control=manager.session(DatabaseRole.CONTROL),
            runtime=manager.session(DatabaseRole.RUNTIME),
            graph=manager.session(DatabaseRole.GRAPH),
            event=manager.session(DatabaseRole.EVENT),
            log=manager.session(DatabaseRole.LOG),
        )

    def _assert_advanceable(
        self,
        run: PipelineRunModel,
        runtime_session: Session,
    ) -> None:
        if run.status is not RunStatus.RUNNING:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "PipelineRun must be running before deterministic advancement.",
                409,
            )
        if run.current_stage_run_id is None:
            return
        stage = runtime_session.get(StageRunModel, run.current_stage_run_id)
        if stage is None:
            raise ApiError(ErrorCode.NOT_FOUND, "Current StageRun was not found.", 404)
        if (
            stage.status in _ACTIVE_STAGE_STATUSES
            and stage.status is not StageStatus.RUNNING
        ):
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "Current StageRun must be running before deterministic advancement.",
                409,
            )

    def _build_context(
        self,
        run_id: str,
        runtime_session: Session,
    ) -> RuntimeExecutionContext:
        run = runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise ApiError(ErrorCode.NOT_FOUND, "PipelineRun was not found.", 404)
        stage = (
            runtime_session.get(StageRunModel, run.current_stage_run_id)
            if run.current_stage_run_id is not None
            else None
        )
        provider_refs = [
            snapshot.snapshot_id
            for snapshot in runtime_session.query(ProviderSnapshotModel)
            .filter(ProviderSnapshotModel.run_id == run_id)
            .order_by(ProviderSnapshotModel.snapshot_id.asc())
            .all()
        ]
        model_binding_refs = [
            snapshot.snapshot_id
            for snapshot in runtime_session.query(ModelBindingSnapshotModel)
            .filter(ModelBindingSnapshotModel.run_id == run_id)
            .order_by(ModelBindingSnapshotModel.snapshot_id.asc())
            .all()
        ]
        if not provider_refs or not model_binding_refs:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "PipelineRun runtime snapshots are incomplete.",
                409,
            )
        stage_run_id = stage.stage_run_id if stage is not None else None
        stage_type = stage.stage_type if stage is not None else None
        return RuntimeExecutionContext(
            run_id=run.run_id,
            session_id=run.session_id,
            thread=GraphThreadRef(
                thread_id=run.graph_thread_ref,
                run_id=run.run_id,
                status=GraphThreadStatus(run.status.value),
                current_stage_run_id=stage_run_id,
                current_stage_type=stage_type,
            ),
            trace_context=self._trace(run, stage_run_id),
            template_snapshot_ref=run.template_snapshot_ref,
            provider_snapshot_refs=provider_refs,
            model_binding_snapshot_refs=model_binding_refs,
            runtime_limit_snapshot_ref=run.runtime_limit_snapshot_ref,
            provider_call_policy_snapshot_ref=run.provider_call_policy_snapshot_ref,
            graph_definition_ref=run.graph_definition_ref,
            delivery_channel_snapshot_ref=run.delivery_channel_snapshot_ref,
            workspace_snapshot_ref=run.workspace_ref,
        )

    def _trace(self, run: PipelineRunModel, stage_run_id: str | None) -> TraceContext:
        return TraceContext(
            request_id=f"test-runtime-advance-{run.run_id}",
            trace_id=run.trace_id,
            correlation_id=f"test-runtime-advance-{run.run_id}",
            span_id=f"test-runtime-advance-{run.run_id}",
            parent_span_id=None,
            session_id=run.session_id,
            run_id=run.run_id,
            stage_run_id=stage_run_id,
            graph_thread_id=run.graph_thread_ref,
            created_at=self._now(),
        )

    def _build_engine(self, sessions: _OpenSessions) -> DeterministicRuntimeEngine:
        settings = self._app.state.environment_settings
        log_writer = JsonlLogWriter(
            RuntimeDataSettings.from_environment_settings(settings)
        )
        audit_service = AuditService(sessions.log, audit_writer=log_writer)
        delivery_record_service = DeliveryRecordService(
            runtime_session=sessions.runtime,
            audit_service=audit_service,
            log_writer=log_writer,
            auto_commit=False,
            now=self._now,
        )
        delivery_service = DeliveryService(
            record_service=delivery_record_service,
            adapters=[
                DemoDeliveryAdapter(
                    audit_service=audit_service,
                    log_writer=log_writer,
                    now=self._now,
                )
            ],
            event_store=EventStore(sessions.event, now=self._now),
            now=self._now,
        )
        return DeterministicRuntimeEngine(
            control_session=sessions.control,
            runtime_session=sessions.runtime,
            event_session=sessions.event,
            audit_service=audit_service,
            delivery_service=delivery_service,
            log_writer=log_writer,
            now=self._now,
        )

    def _configure_engine(self, engine: DeterministicRuntimeEngine) -> None:
        engine.configure_interrupts(
            solution_design_approval=True,
            tool_confirmation=DeterministicToolConfirmationConfig(
                stage_type=StageType.CODE_GENERATION,
                tool_name="bash",
                command_preview="Remove-Item -Recurse build",
                target_summary="Deletes generated build outputs.",
                risk_categories=[ToolRiskCategory.FILE_DELETE_OR_MOVE],
                reason="The deterministic E2E fixture requires high-risk tool confirmation.",
                expected_side_effects=["Deletes generated build outputs."],
                alternative_path_summary="Continue with deterministic fallback output.",
                planned_deny_followup_action="continue_current_stage",
                planned_deny_followup_summary=(
                    "Code Generation will continue with a low-risk fallback."
                ),
            ),
        )

    def _runtime_port(self, sessions: _OpenSessions) -> Any:
        runtime_port = getattr(self._app.state, "h45_runtime_port", None)
        if runtime_port is None:
            runtime_port = getattr(self._app.state, "h41_runtime_port", None)
        if runtime_port is None:
            runtime_port = GraphRuntimeCommandPort(sessions.graph, now=self._now)
        return runtime_port

    def _checkpoint_port(self, sessions: _OpenSessions) -> Any:
        checkpoint_port = getattr(self._app.state, "h45_checkpoint_port", None)
        if checkpoint_port is None:
            checkpoint_port = getattr(self._app.state, "h41_checkpoint_port", None)
        if checkpoint_port is None:
            checkpoint_port = GraphCheckpointPort(sessions.graph, now=self._now)
        return checkpoint_port

    def _to_response(
        self,
        result: RuntimeInterrupt | RuntimeStepResult,
        runtime_session: Session,
    ) -> AdvanceRuntimeResponse:
        run = runtime_session.get(PipelineRunModel, result.run_id)
        if run is None:
            raise ApiError(ErrorCode.NOT_FOUND, "PipelineRun was not found.", 404)
        if isinstance(result, RuntimeStepResult):
            return AdvanceRuntimeResponse(
                run_id=result.run_id,
                session_id=run.session_id,
                stage_run_id=result.stage_run_id,
                stage_type=result.stage_type,
                run_status=run.status,
                result_type="stage_result",
                artifact_refs=list(result.artifact_refs),
                domain_event_refs=list(result.domain_event_refs),
                checkpoint_id=(
                    result.checkpoint_ref.checkpoint_id
                    if result.checkpoint_ref is not None
                    else None
                ),
            )
        return AdvanceRuntimeResponse(
            run_id=result.run_id,
            session_id=run.session_id,
            stage_run_id=result.stage_run_id,
            stage_type=result.stage_type,
            run_status=run.status,
            result_type="interrupt",
            interrupt_type=self._interrupt_type(result),
            approval_id=result.interrupt_ref.approval_id,
            tool_confirmation_id=result.interrupt_ref.tool_confirmation_id,
            artifact_refs=list(result.artifact_refs),
            domain_event_refs=list(result.domain_event_refs),
            checkpoint_id=result.interrupt_ref.checkpoint_ref.checkpoint_id,
        )

    def _interrupt_type(self, result: RuntimeInterrupt) -> str:
        if result.interrupt_ref.interrupt_type is GraphInterruptType.APPROVAL:
            return "approval"
        if result.interrupt_ref.interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
            return "tool_confirmation"
        return result.interrupt_ref.interrupt_type.value


__all__ = [
    "AdvanceRuntimeRequest",
    "AdvanceRuntimeResponse",
    "DeterministicRuntimeAdvancementHarness",
    "build_deterministic_runtime_advancement_router",
    "create_e2e_test_app",
]
