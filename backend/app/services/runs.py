from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.control import ProviderModel, SessionModel
from backend.app.db.models.runtime import (
    ApprovalRequestModel,
    PipelineRunModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    FeedEntryType,
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    SseEventType,
    StageStatus,
    StageType,
    ToolConfirmationStatus,
)
from backend.app.domain.provider_call_policy_snapshot import (
    ProviderCallPolicySnapshot,
    ProviderCallPolicySnapshotBuilder,
    ProviderCallPolicySnapshotBuilderError,
)
from backend.app.domain.provider_snapshot import (
    InternalModelBindingSelection,
    ModelBindingSnapshot,
    ModelBindingSnapshotBuilder,
    ModelBindingSnapshotBuilderError,
    ProviderSnapshot,
    ProviderSnapshotBuilder,
    ProviderSnapshotBuilderError,
)
from backend.app.domain.runtime_limit_snapshot import (
    RuntimeLimitSnapshot,
    RuntimeLimitSnapshotBuilder,
    RuntimeLimitSnapshotBuilderError,
)
from backend.app.domain.runtime_refs import CheckpointRef, GraphThreadRef, GraphThreadStatus
from backend.app.domain.state_machine import (
    InvalidRunStateTransition,
    RunStateMachine,
)
from backend.app.domain.template_snapshot import TemplateSnapshot, TemplateSnapshotBuilder
from backend.app.domain.trace_context import TraceContext
from backend.app.domain.publication_boundary import PublishedStartupVisibility
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.feed import (
    ApprovalRequestFeedEntry,
    SystemStatusFeedEntry,
    ExecutionNodeProjection,
    MessageFeedEntry,
    ToolConfirmationFeedEntry,
)
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
)
from backend.app.repositories.graph import GraphRepository, GraphRepositoryError
from backend.app.repositories.runtime import (
    PipelineRunRepository,
    PipelineRunRepositoryError,
    RuntimeSnapshotRepository,
    RuntimeSnapshotRepositoryError,
    StageRunRepositoryError,
)
from backend.app.schemas.run import RunSummaryProjection
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.graph_compiler import GraphCompiler, GraphCompilerError
from backend.app.services.publication_boundary import (
    PublicationBoundaryService,
    PublicationBoundaryServiceError,
)
from backend.app.services.runtime_orchestration import RuntimeOrchestrationService
from backend.app.services.tool_confirmations import ToolConfirmationService
from backend.app.services.runtime_settings import (
    PlatformRuntimeSettingsService,
    RuntimeSettingsServiceError,
)
from backend.app.services.stages import StageRunService


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class RunPromptValidationService(Protocol):
    def validate_run_prompt_snapshots(
        self,
        *,
        template_snapshot: TemplateSnapshot,
        trace_context: TraceContext,
    ) -> None: ...


class RunLifecycleServiceError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        status_code: int = 409,
        detail_ref: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.status_code = status_code
        self.detail_ref = detail_ref
        super().__init__(message)


class RunPromptValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
    ) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class RunCommandResult:
    session: SessionModel
    run: PipelineRunModel
    stage: StageRunModel | None
    checkpoint_ref: CheckpointRef | None = None


@dataclass(frozen=True)
class RerunSessionState:
    current_run_id: str | None
    status: SessionStatus
    latest_stage_type: StageType | None
    updated_at: datetime


@dataclass(frozen=True)
class TerminalStatusProjector:
    events: EventStore
    now: Callable[[], datetime]
    _USE_DEFAULT_RETRY_ACTION = object()

    def append_terminal_system_status(
        self,
        *,
        domain_event_type: DomainEventType,
        run: PipelineRunModel,
        title: str,
        reason: str,
        trace_context: TraceContext,
        retry_action: str | None | object = _USE_DEFAULT_RETRY_ACTION,
        is_current_tail: bool = False,
        occurred_at: datetime | None = None,
    ) -> None:
        timestamp = occurred_at or self.now()
        resolved_retry_action = (
            (
                f"retry:{run.run_id}"
                if is_current_tail
                else None
            )
            if retry_action is self._USE_DEFAULT_RETRY_ACTION
            else retry_action
        )
        entry = SystemStatusFeedEntry(
            entry_id=f"entry-system-status-{run.run_id}-{domain_event_type.value.lower()}",
            run_id=run.run_id,
            occurred_at=timestamp,
            status=(
                RunStatus.TERMINATED
                if domain_event_type is DomainEventType.RUN_TERMINATED
                else RunStatus.FAILED
            ),
            title=title,
            reason=reason,
            retry_action=resolved_retry_action,
        )
        self.events.append(
            domain_event_type,
            payload={"system_status": entry.model_dump(mode="json")},
            trace_context=trace_context,
            occurred_at=timestamp,
        )


@dataclass(frozen=True)
class StartFirstRunResult:
    session: SessionModel
    run: PipelineRunModel
    stage: StageRunModel
    message_item: MessageFeedEntry


class RunLifecycleService:
    def __init__(
        self,
        session: Session | None = None,
        runtime_session: Session | None = None,
        *,
        control_session: Session | None = None,
        event_session: Session | None = None,
        graph_session: Session | None = None,
        runtime_orchestration: RuntimeOrchestrationService | None = None,
        audit_service: Any | None = None,
        log_writer: RunLogWriter | None = None,
        prompt_validation_service: RunPromptValidationService | None = None,
        credential_env_prefixes: Iterable[str] | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if control_session is None:
            control_session = session if runtime_session is not None else None
        if runtime_session is None:
            runtime_session = session
        if runtime_session is None:
            raise TypeError("runtime_session or session is required")
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_session = event_session
        self._graph_session = graph_session
        self._runtime_orchestration = runtime_orchestration
        self._audit_service = audit_service or _NoopAuditService()
        self._log_writer = log_writer or _NoopRunLogWriter()
        self._prompt_validation_service = (
            prompt_validation_service or _NoopRunPromptValidationService()
        )
        self._credential_env_prefixes = (
            tuple(credential_env_prefixes)
            if credential_env_prefixes is not None
            else None
        )
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))
        self._events = (
            EventStore(event_session, now=self._now)
            if event_session is not None
            else None
        )
        self._publication_boundary: PublicationBoundaryService | None = None

    def start_first_run(
        self,
        *,
        session: SessionModel,
        template: Any,
        content: str,
        trace_context: TraceContext,
        runtime_settings_service: PlatformRuntimeSettingsService,
    ) -> StartFirstRunResult:
        started_at = self._now()
        session = self._load_visible_session_for_start(session.session_id)
        command_trace = trace_context.child_span(
            span_id=f"session-message-new-requirement-{session.session_id}",
            created_at=started_at,
            session_id=session.session_id,
        )
        try:
            RunStateMachine.assert_can_start_first_run(
                session_status=session.status,
                current_run_id=session.current_run_id,
            )
        except InvalidRunStateTransition as exc:
            self._record_start_rejected(
                session=session,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            raise RunLifecycleServiceError(
                str(exc),
                error_code=ErrorCode.VALIDATION_ERROR,
                status_code=409,
                detail_ref=session.session_id,
            ) from exc

        try:
            graph_session = self._require_graph_session()
            run_id = _bounded_id("run", uuid4().hex)
            stage_run_id = _bounded_id("stage-run", uuid4().hex)
            graph_thread_id = _graph_thread_id(run_id)
            workspace_ref = _workspace_ref(run_id)
            publication = None
            run_trace = _fork_trace(
                command_trace,
                trace_id=_trace_id(),
                span_id=f"run-start-{run_id}",
                created_at=started_at,
                run_id=run_id,
                stage_run_id=stage_run_id,
                graph_thread_id=graph_thread_id,
            )
            try:
                publication = self._begin_startup_publication(
                    session_id=session.session_id,
                    run_id=run_id,
                    stage_run_id=stage_run_id,
                    started_at=started_at,
                    trace_context=command_trace,
                )
            except RunLifecycleServiceError as exc:
                self._rollback_all()
                try:
                    graph_session.rollback()
                except Exception:
                    pass
                self._record_start_rejected(
                    session=session,
                    reason=str(exc),
                    trace_context=command_trace,
                    started_at=started_at,
                )
                raise
            settings_read = runtime_settings_service.get_current_settings(
                trace_context=run_trace
            )

            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action="session.message.new_requirement.accepted",
                target_type="session",
                target_id=session.session_id,
                result=AuditResult.ACCEPTED,
                reason="First run startup accepted.",
                metadata={
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "selected_template_id": template.template_id,
                    "run_id": run_id,
                    "stage_run_id": stage_run_id,
                    "graph_thread_ref": graph_thread_id,
                    "result_status": "accepted",
                },
                trace_context=run_trace,
                rollback=self._rollback_all,
                created_at=started_at,
            )
            self._record_run_log(
                payload_type="run_start_accepted",
                message="First run startup accepted.",
                metadata={
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "selected_template_id": template.template_id,
                    "run_id": run_id,
                    "stage_run_id": stage_run_id,
                    "graph_thread_ref": graph_thread_id,
                    "result_status": "accepted",
                },
                trace_context=run_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )

            try:
                template_snapshot = TemplateSnapshotBuilder.build_for_run(
                    template,
                    run_id=run_id,
                    created_at=started_at,
                )
            except (ValidationError, ValueError) as exc:
                raise RunPromptValidationError(str(exc)) from exc
            self._prompt_validation_service.validate_run_prompt_snapshots(
                template_snapshot=template_snapshot,
                trace_context=run_trace,
            )
            runtime_limit_snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
                settings_read,
                template_snapshot=template_snapshot,
                run_id=run_id,
                created_at=started_at,
            )
            provider_call_policy_snapshot = ProviderCallPolicySnapshotBuilder.build_for_run(
                settings_read,
                run_id=run_id,
                created_at=started_at,
            )
            required_providers = self._load_required_providers(
                template_snapshot=template_snapshot,
                settings_read=settings_read,
            )
            provider_snapshots = ProviderSnapshotBuilder.build_for_run(
                required_providers,
                run_id=run_id,
                required_provider_ids=self._required_provider_ids(
                    template_snapshot,
                    settings_read,
                ),
                required_model_ids_by_provider=self._required_model_ids_by_provider(
                    settings_read
                ),
                created_at=started_at,
                credential_env_prefixes=self._credential_env_prefixes,
            )
            model_binding_snapshots = ModelBindingSnapshotBuilder.build_for_run(
                template_snapshot,
                provider_snapshots=provider_snapshots,
                internal_bindings=self._internal_bindings_from_settings(settings_read),
                run_id=run_id,
                created_at=started_at,
            )
            graph_definition = GraphCompiler(now=lambda: started_at).compile(
                template_snapshot=template_snapshot,
                runtime_limit_snapshot=runtime_limit_snapshot,
            )

            RuntimeSnapshotRepository(self._runtime_session).save_runtime_limit_snapshot(
                runtime_limit_snapshot
            )
            RuntimeSnapshotRepository(
                self._runtime_session
            ).save_provider_call_policy_snapshot(provider_call_policy_snapshot)
            GraphRepository(graph_session).save_definition(graph_definition)

            run = PipelineRunRepository(self._runtime_session).create_run(
                run_id=run_id,
                session_id=session.session_id,
                project_id=session.project_id,
                attempt_index=1,
                status=RunStatus.RUNNING,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref=template_snapshot.snapshot_ref,
                graph_definition_ref=graph_definition.graph_definition_id,
                graph_thread_ref=graph_thread_id,
                workspace_ref=workspace_ref,
                runtime_limit_snapshot_ref=runtime_limit_snapshot.snapshot_id,
                provider_call_policy_snapshot_ref=provider_call_policy_snapshot.snapshot_id,
                delivery_channel_snapshot_ref=None,
                current_stage_run_id=stage_run_id,
                trace_id=run_trace.trace_id,
                started_at=started_at,
                ended_at=None,
                created_at=started_at,
                updated_at=started_at,
            )
            self.attach_provider_snapshots(
                run,
                provider_snapshots=provider_snapshots,
                model_binding_snapshots=model_binding_snapshots,
            )
            GraphRepository(graph_session).save_thread(
                thread_id=graph_thread_id,
                run_id=run_id,
                graph_definition_id=graph_definition.graph_definition_id,
                current_node_key="requirement_analysis",
                created_at=started_at,
            )
            stage_trace = run_trace.child_span(
                span_id=f"stage-start-{stage_run_id}",
                created_at=started_at,
                run_id=run_id,
                stage_run_id=stage_run_id,
                graph_thread_id=graph_thread_id,
            )
            stage = StageRunService(
                runtime_session=self._runtime_session,
                log_writer=self._log_writer,
                redaction_policy=self._redaction_policy,
                now=self._now,
            ).start_stage(
                run_id=run_id,
                stage_run_id=stage_run_id,
                stage_type=StageType.REQUIREMENT_ANALYSIS,
                attempt_index=1,
                graph_node_key="requirement_analysis",
                stage_contract_ref="requirement_analysis",
                input_ref=None,
                summary="Requirement Analysis started from the first user requirement.",
                trace_context=stage_trace,
            )
            event_trace = run_trace.child_span(
                span_id=f"event-run-created-{run_id}",
                created_at=started_at,
                run_id=run_id,
                stage_run_id=stage_run_id,
                graph_thread_id=graph_thread_id,
            )
            run_summary = RunSummaryProjection(
                run_id=run.run_id,
                attempt_index=run.attempt_index,
                status=run.status,
                trigger_source=run.trigger_source,
                started_at=run.started_at,
                ended_at=run.ended_at,
                current_stage_type=StageType.REQUIREMENT_ANALYSIS,
                is_active=True,
            )
            self._require_events().append(
                DomainEventType.PIPELINE_RUN_CREATED,
                payload={"run": run_summary.model_dump(mode="json")},
                trace_context=event_trace,
                session_id=session.session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                occurred_at=started_at,
            )
            self._append_run_status_event(
                DomainEventType.RUN_RESUMED,
                session=self._published_session_view(
                    session=session,
                    run_id=run_id,
                    occurred_at=started_at,
                ),
                run=run,
                trace_context=event_trace,
                occurred_at=started_at,
            )
            stage_node = self._build_stage_started_projection(
                run_id=run_id,
                stage=stage,
                occurred_at=started_at,
            )
            self._require_events().append(
                DomainEventType.STAGE_STARTED,
                payload={"stage_node": stage_node.model_dump(mode="json")},
                trace_context=event_trace,
                session_id=session.session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                occurred_at=started_at,
            )
            message_item = MessageFeedEntry(
                entry_id=_bounded_id("entry", uuid4().hex),
                run_id=run_id,
                type=FeedEntryType.USER_MESSAGE,
                occurred_at=started_at,
                message_id=_bounded_id("message", uuid4().hex),
                author="user",
                content=content,
                stage_run_id=stage_run_id,
            )
            self._require_events().append(
                DomainEventType.SESSION_MESSAGE_APPENDED,
                payload={"message_item": message_item.model_dump(mode="json")},
                trace_context=event_trace,
                session_id=session.session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                occurred_at=started_at,
            )

            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action="session.message.new_requirement",
                target_type="session",
                target_id=session.session_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_definition_ref": run.graph_definition_ref,
                    "graph_thread_ref": run.graph_thread_ref,
                    "workspace_ref": run.workspace_ref,
                    "result_status": "succeeded",
                },
                trace_context=run_trace,
                rollback=self._rollback_all,
                created_at=started_at,
            )
            self._commit_first_run_startup(
                session_id=session.session_id,
                run_id=run.run_id,
                stage_run_id=stage.stage_run_id,
                publication_id=publication.publication_id if publication else None,
                trace_context=run_trace,
                occurred_at=started_at,
            )
            session = self._load_visible_session_for_start(session.session_id)
            self._record_run_log(
                payload_type="run_start_completed",
                message="First run startup completed.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_definition_ref": run.graph_definition_ref,
                    "graph_thread_ref": run.graph_thread_ref,
                    "workspace_ref": run.workspace_ref,
                    "result_status": "succeeded",
                },
                trace_context=run_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            return StartFirstRunResult(
                session=session,
                run=run,
                stage=stage,
                message_item=message_item,
            )
        except (
            RuntimeSettingsServiceError,
            RuntimeLimitSnapshotBuilderError,
            ProviderCallPolicySnapshotBuilderError,
            ProviderSnapshotBuilderError,
            ModelBindingSnapshotBuilderError,
            RunPromptValidationError,
            GraphCompilerError,
            GraphRepositoryError,
            PipelineRunRepositoryError,
            RuntimeSnapshotRepositoryError,
            StageRunRepositoryError,
            PublicationBoundaryServiceError,
        ) as exc:
            self._abort_startup_if_needed(
                publication_id=publication.publication_id if publication else None,
                session_id=session.session_id,
                run_id=run_id,
                reason=getattr(exc, "message", str(exc)),
                trace_context=run_trace,
                occurred_at=started_at,
            )
            self._record_start_failed(
                session=session,
                reason=getattr(exc, "message", str(exc)),
                trace_context=run_trace,
                started_at=started_at,
                error_code=getattr(exc, "error_code", ErrorCode.CONFIG_STORAGE_UNAVAILABLE),
            )
            error_code = getattr(exc, "error_code", ErrorCode.CONFIG_STORAGE_UNAVAILABLE)
            status_code = 503
            if error_code in {
                ErrorCode.VALIDATION_ERROR,
                ErrorCode.CONFIG_INVALID_VALUE,
                ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED,
                ErrorCode.CONFIG_CREDENTIAL_ENV_NOT_ALLOWED,
            }:
                status_code = 422
            raise RunLifecycleServiceError(
                getattr(exc, "message", str(exc)),
                error_code=error_code,
                status_code=status_code,
                detail_ref=session.session_id,
            ) from exc
        except RunLifecycleServiceError:
            raise
        except Exception as exc:
            self._abort_startup_if_needed(
                publication_id=publication.publication_id if publication else None,
                session_id=session.session_id,
                run_id=run_id,
                reason=str(exc),
                trace_context=run_trace,
                occurred_at=started_at,
            )
            self._record_start_failed(
                session=session,
                reason=str(exc),
                trace_context=run_trace,
                started_at=started_at,
                error_code=ErrorCode.INTERNAL_ERROR,
            )
            raise RunLifecycleServiceError(
                "first run startup failed.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=session.session_id,
            ) from exc

    def pause_run(
        self,
        *,
        run_id: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> RunCommandResult:
        started_at = self._now()
        session, run, stage = self._load_active_run_context(run_id)
        command_trace = self._command_trace(
            trace_context,
            span_id=f"runtime-pause-{run.run_id}",
            session=session,
            run=run,
            stage=stage,
        )
        try:
            self._assert_can_pause(session=session, run=run)
        except RunLifecycleServiceError as exc:
            self._record_rejected_command(
                action="runtime.pause.rejected",
                message="Run pause command rejected.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            raise

        status_before = run.status
        try:
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action="runtime.pause",
                target_type="run",
                target_id=run.run_id,
                result=AuditResult.ACCEPTED,
                reason="Pause accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "status_before": status_before.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                rollback=self._rollback_all,
                created_at=started_at,
            )
            self._record_run_log(
                payload_type="runtime_pause_accepted",
                message="Run pause command accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "status_before": status_before.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            runtime_result = self._require_runtime_orchestration().pause_thread(
                thread=self._build_thread_ref(run=run, stage=stage),
                stage_run_id=stage.stage_run_id,
                stage_type=stage.stage_type,
                workspace_snapshot_ref=run.workspace_ref,
                trace_context=command_trace,
            )
            checkpoint = runtime_result.checkpoint_ref
            self._persist_recovery_checkpoint(
                control_session=session,
                run=run,
                stage=stage,
                checkpoint=checkpoint,
                saved_at=started_at,
            )
            run.status = RunStatus.PAUSED
            run.updated_at = started_at
            session.status = SessionStatus.PAUSED
            session.updated_at = started_at
            self._runtime_session.add(run)
            self._require_control_session().add(session)
            self._append_run_status_event(
                DomainEventType.RUN_PAUSED,
                session=session,
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._refresh_pending_wait_entry_for_pause(
                pre_pause_status=status_before,
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._commit_all()
            self._record_run_log(
                payload_type="runtime_pause_completed",
                message="Run pause completed.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "checkpoint_id": checkpoint.checkpoint_id if checkpoint else None,
                    "status_before": status_before.value,
                    "status_after": run.status.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            return RunCommandResult(
                session=session,
                run=run,
                stage=stage,
                checkpoint_ref=checkpoint,
            )
        except Exception as exc:
            self._rollback_all()
            self._record_failed_command(
                action="runtime.pause.failed",
                message="Run pause failed.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            if isinstance(exc, RunLifecycleServiceError):
                raise
            raise RunLifecycleServiceError(
                "runtime pause command failed.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run.run_id,
            ) from exc

    def resume_run(
        self,
        *,
        run_id: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> RunCommandResult:
        started_at = self._now()
        session, run, stage = self._load_active_run_context(run_id)
        command_trace = self._command_trace(
            trace_context,
            span_id=f"runtime-resume-{run.run_id}",
            session=session,
            run=run,
            stage=stage,
        )
        try:
            self._assert_can_resume(session=session, run=run)
        except RunLifecycleServiceError as exc:
            self._record_rejected_command(
                action="runtime.resume.rejected",
                message="Run resume command rejected.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            raise

        try:
            checkpoint_artifact = self._latest_recovery_checkpoint(run_id=run.run_id)
            checkpoint = CheckpointRef.model_validate(
                checkpoint_artifact.process["checkpoint"]
            )
            self._validate_recovery_checkpoint(
                artifact=checkpoint_artifact,
                checkpoint=checkpoint,
                run=run,
                stage=stage,
            )
            pre_pause_status = RunStatus(
                checkpoint_artifact.process["run_status_before_pause"]
            )
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action="runtime.resume",
                target_type="run",
                target_id=run.run_id,
                result=AuditResult.ACCEPTED,
                reason="Resume accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "status_before": run.status.value,
                    "status_after": pre_pause_status.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                rollback=self._rollback_all,
                created_at=started_at,
            )
            self._record_run_log(
                payload_type="runtime_resume_accepted",
                message="Run resume command accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "status_before": run.status.value,
                    "status_after": pre_pause_status.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            self._require_runtime_orchestration().resume_thread(
                thread=self._build_thread_ref(run=run, stage=stage, paused=True),
                checkpoint=checkpoint,
                trace_context=command_trace,
            )
            run.status = pre_pause_status
            run.updated_at = started_at
            session.status = RunStateMachine.project_session_status(pre_pause_status)
            session.updated_at = started_at
            self._runtime_session.add(run)
            self._require_control_session().add(session)
            self._append_run_status_event(
                DomainEventType.RUN_RESUMED,
                session=session,
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._refresh_pending_wait_entry_for_resume(
                pre_pause_status=pre_pause_status,
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._commit_all()
            self._record_run_log(
                payload_type="runtime_resume_completed",
                message="Run resume completed.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "status_before": RunStatus.PAUSED.value,
                    "status_after": run.status.value,
                    "result_status": "accepted",
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            return RunCommandResult(
                session=session,
                run=run,
                stage=stage,
                checkpoint_ref=checkpoint,
            )
        except Exception as exc:
            self._rollback_all()
            self._record_failed_command(
                action="runtime.resume.failed",
                message="Run resume failed.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            if isinstance(exc, RunLifecycleServiceError):
                raise
            raise RunLifecycleServiceError(
                "runtime resume command failed.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run.run_id,
            ) from exc

    def terminate_run(
        self,
        *,
        run_id: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> RunCommandResult:
        started_at = self._now()
        session, run, stage = self._load_active_run_context(run_id)
        command_trace = self._command_trace(
            trace_context,
            span_id=f"runtime-terminate-{run.run_id}",
            session=session,
            run=run,
            stage=stage,
        )
        try:
            self._assert_can_terminate(session=session, run=run)
        except RunLifecycleServiceError as exc:
            self._record_rejected_command(
                action="runtime.terminate.rejected",
                message="Run terminate command rejected.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            raise

        status_before = run.status
        terminal_reason = "Run was terminated by user request."
        try:
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action="runtime.terminate",
                target_type="run",
                target_id=run.run_id,
                result=AuditResult.ACCEPTED,
                reason="Terminate accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "status_before": status_before.value,
                    "result_status": "accepted",
                    "terminal_reason": terminal_reason,
                },
                trace_context=command_trace,
                rollback=self._rollback_all,
                created_at=started_at,
            )
            self._record_run_log(
                payload_type="runtime_terminate_accepted",
                message="Run terminate command accepted.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "status_before": status_before.value,
                    "result_status": "accepted",
                    "terminal_reason": terminal_reason,
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            self._require_runtime_orchestration().terminate_thread(
                thread=self._build_thread_ref(
                    run=run,
                    stage=stage,
                    paused=status_before is RunStatus.PAUSED,
                ),
                trace_context=command_trace,
            )
            self._cancel_pending_tool_confirmations_for_terminal_run(
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._mark_terminal(
                session=session,
                run=run,
                stage=stage,
                terminal_status=RunStatus.TERMINATED,
                occurred_at=started_at,
            )
            self._refresh_pending_wait_entry_for_terminate(
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            TerminalStatusProjector(
                events=self._require_events(),
                now=self._now,
            ).append_terminal_system_status(
                domain_event_type=DomainEventType.RUN_TERMINATED,
                run=run,
                title="Run terminated",
                reason=terminal_reason,
                is_current_tail=session.current_run_id == run.run_id,
                trace_context=command_trace,
                occurred_at=started_at,
            )
            self._commit_all()
            self._record_run_log(
                payload_type="runtime_terminate_completed",
                message="Run terminate completed.",
                metadata={
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id,
                    "graph_thread_id": run.graph_thread_ref,
                    "status_before": status_before.value,
                    "status_after": run.status.value,
                    "result_status": "accepted",
                    "terminal_reason": terminal_reason,
                },
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
                duration_ms=self._duration_ms(started_at, started_at),
            )
            return RunCommandResult(session=session, run=run, stage=stage)
        except Exception as exc:
            self._rollback_all()
            self._record_failed_command(
                action="runtime.terminate.failed",
                message="Run terminate failed.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            if isinstance(exc, RunLifecycleServiceError):
                raise
            raise RunLifecycleServiceError(
                "runtime terminate command failed.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run.run_id,
            ) from exc

    def create_rerun(
        self,
        *,
        session_id: str,
        actor_id: str,
        trace_context: TraceContext,
    ) -> RunCommandResult:
        started_at = self._now()
        try:
            session, run, stage = self._load_current_session_run_tail(session_id)
        except RunLifecycleServiceError as exc:
            if exc.error_code in {
                ErrorCode.VALIDATION_ERROR,
                ErrorCode.RUN_COMMAND_NOT_ACTIONABLE,
            }:
                self._record_rejected_session_command(
                    action="runtime.rerun.rejected",
                    message="Run rerun command rejected.",
                    actor_id=actor_id,
                    session_id=session_id,
                    reason=str(exc),
                    trace_context=trace_context,
                    started_at=started_at,
                )
            raise
        command_trace = self._command_trace(
            trace_context,
            span_id=f"runtime-rerun-{run.run_id}",
            session=session,
            run=run,
            stage=stage,
        )
        try:
            self._assert_can_create_rerun(session=session, run=run)
        except RunLifecycleServiceError as exc:
            self._record_rejected_command(
                action="runtime.rerun.rejected",
                message="Run rerun command rejected.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            raise

        old_trace_id = run.trace_id
        session_snapshot = RerunSessionState(
            current_run_id=session.current_run_id,
            status=session.status,
            latest_stage_type=session.latest_stage_type,
            updated_at=session.updated_at,
        )
        try:
            terminal_thread = (
                self._require_runtime_orchestration().assert_thread_terminal_for_rerun(
                    thread=self._build_thread_ref(run=run, stage=stage),
                    trace_context=command_trace,
                )
            )
            if terminal_thread.status not in {
                GraphThreadStatus.COMPLETED,
                GraphThreadStatus.FAILED,
                GraphThreadStatus.TERMINATED,
            }:
                raise _RejectedRunLifecycleServiceError(
                    "The current run thread must be terminal before rerun."
                )

            accepted_metadata = self._rerun_log_metadata(
                session=session,
                old_run=run,
                old_stage=stage,
                new_run=None,
                old_trace_id=old_trace_id,
                result_status="accepted",
            )
            self._audit_service.require_audit_record(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action="runtime.rerun",
                target_type="run",
                target_id=run.run_id,
                result=AuditResult.ACCEPTED,
                reason="Rerun accepted.",
                metadata=accepted_metadata,
                trace_context=command_trace,
                rollback=self._rollback_all,
                created_at=started_at,
            )
            self._record_run_log(
                payload_type="runtime_rerun_accepted",
                message="Run rerun command accepted.",
                metadata=accepted_metadata,
                trace_context=command_trace,
                created_at=started_at,
                level=LogLevel.INFO,
            )
            new_run = self._build_rerun(
                session=session,
                source_run=run,
                started_at=started_at,
            )
            session.current_run_id = new_run.run_id
            session.status = SessionStatus.RUNNING
            session.latest_stage_type = StageType.REQUIREMENT_ANALYSIS
            session.updated_at = started_at
            self._runtime_session.add(new_run)
            self._require_control_session().add(session)
            self._append_latest_terminal_system_status_retry_action(
                run=run,
                trace_context=command_trace,
                occurred_at=started_at,
            )

            event_trace = command_trace.child_span(
                span_id=f"runtime-rerun-created-{new_run.run_id}",
                created_at=started_at,
                run_id=new_run.run_id,
                stage_run_id=None,
                graph_thread_id=new_run.graph_thread_ref,
            )
            self._require_events().append(
                DomainEventType.PIPELINE_RUN_CREATED,
                payload={
                    "run": self._run_summary_projection(
                        new_run,
                        current_stage_type=StageType.REQUIREMENT_ANALYSIS,
                        is_active=True,
                    ).model_dump(mode="json")
                },
                trace_context=event_trace,
                occurred_at=started_at,
            )
            self._append_run_status_event(
                DomainEventType.RUN_RESUMED,
                session=session,
                run=new_run,
                trace_context=event_trace,
                occurred_at=started_at,
            )
            self._commit_rerun_all(
                session_id=session.session_id,
                session_snapshot=session_snapshot,
                new_run_id=new_run.run_id,
            )
            self._record_run_log(
                payload_type="runtime_rerun_completed",
                message="Run rerun command completed.",
                metadata=self._rerun_log_metadata(
                    session=session,
                    old_run=run,
                    old_stage=stage,
                    new_run=new_run,
                    old_trace_id=old_trace_id,
                    result_status="accepted",
                ),
                trace_context=event_trace,
                created_at=started_at,
                level=LogLevel.INFO,
                duration_ms=self._duration_ms(started_at, started_at),
            )
            return RunCommandResult(session=session, run=new_run, stage=None)
        except _RejectedRunLifecycleServiceError as exc:
            self._rollback_all()
            self._record_rejected_command(
                action="runtime.rerun.rejected",
                message="Run rerun command rejected.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            raise RunLifecycleServiceError(
                str(exc),
                error_code=ErrorCode.RUN_COMMAND_NOT_ACTIONABLE,
                status_code=409,
                detail_ref=run.run_id,
            ) from exc
        except Exception as exc:
            self._rollback_all()
            self._record_failed_command(
                action="runtime.rerun.failed",
                message="Run rerun command failed.",
                actor_id=actor_id,
                run=run,
                stage=stage,
                reason=str(exc),
                trace_context=command_trace,
                started_at=started_at,
            )
            if isinstance(exc, RunLifecycleServiceError):
                raise
            raise RunLifecycleServiceError(
                "runtime rerun command failed.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run.run_id,
            ) from exc

    def build_rerun_trigger_metadata(
        self,
        *,
        old_run: PipelineRunModel,
        new_run: PipelineRunModel,
        old_trace_id: str,
    ) -> dict[str, Any]:
        return {
            "trigger_source": RunTriggerSource.RETRY.value,
            "source_run_id": old_run.run_id,
            "new_run_id": new_run.run_id,
            "source_attempt_index": old_run.attempt_index,
            "attempt_index": new_run.attempt_index,
            "source_trace_id": old_trace_id,
            "trace_id": new_run.trace_id,
        }

    def attach_template_snapshot(
        self,
        run: PipelineRunModel,
        snapshot: TemplateSnapshot,
    ) -> PipelineRunModel:
        if run.run_id != snapshot.run_id:
            raise ValueError("template snapshot run_id must match PipelineRun.run_id")
        run.template_snapshot_ref = snapshot.snapshot_ref
        run.updated_at = self._now()
        self._runtime_session.add(run)
        return run

    def attach_provider_snapshots(
        self,
        run: PipelineRunModel,
        *,
        provider_snapshots: tuple[ProviderSnapshot, ...],
        model_binding_snapshots: tuple[ModelBindingSnapshot, ...],
    ) -> PipelineRunModel:
        if not provider_snapshots:
            raise ValueError("provider_snapshots must not be empty")
        if not model_binding_snapshots:
            raise ValueError("model_binding_snapshots must not be empty")
        for snapshot in provider_snapshots:
            if run.run_id != snapshot.run_id:
                raise ValueError(
                    "provider snapshot run_id must match PipelineRun.run_id"
                )
        provider_snapshot_ids = {
            snapshot.snapshot_id for snapshot in provider_snapshots
        }
        for snapshot in model_binding_snapshots:
            if run.run_id != snapshot.run_id:
                raise ValueError(
                    "model binding snapshot run_id must match PipelineRun.run_id"
                )
            if snapshot.provider_snapshot_id not in provider_snapshot_ids:
                raise ValueError(
                    "model binding snapshot provider_snapshot_id must reference "
                    "attached provider_snapshots"
                )

        repository = RuntimeSnapshotRepository(self._runtime_session)
        for snapshot in provider_snapshots:
            repository.save_provider_snapshot(snapshot)
        for snapshot in model_binding_snapshots:
            repository.save_model_binding_snapshot(snapshot)

        run.updated_at = self._now()
        self._runtime_session.add(run)
        return run

    def attach_runtime_limit_snapshot(
        self,
        run: PipelineRunModel,
        snapshot: RuntimeLimitSnapshot,
    ) -> PipelineRunModel:
        if run.run_id != snapshot.run_id:
            raise ValueError(
                "runtime limit snapshot run_id must match PipelineRun.run_id"
            )
        RuntimeSnapshotRepository(self._runtime_session).save_runtime_limit_snapshot(
            snapshot
        )
        run.runtime_limit_snapshot_ref = snapshot.snapshot_id
        run.updated_at = self._now()
        self._runtime_session.add(run)
        return run

    def attach_provider_call_policy_snapshot(
        self,
        run: PipelineRunModel,
        snapshot: ProviderCallPolicySnapshot,
    ) -> PipelineRunModel:
        if run.run_id != snapshot.run_id:
            raise ValueError(
                "provider call policy snapshot run_id must match PipelineRun.run_id"
            )
        RuntimeSnapshotRepository(
            self._runtime_session
        ).save_provider_call_policy_snapshot(snapshot)
        run.provider_call_policy_snapshot_ref = snapshot.snapshot_id
        run.updated_at = self._now()
        self._runtime_session.add(run)
        return run

    def mark_waiting_clarification(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        self.assert_can_request_clarification(session=session, run=run, stage=stage)

        timestamp = self._now()
        run.status = RunStatus.WAITING_CLARIFICATION
        run.updated_at = timestamp
        stage.status = StageStatus.WAITING_CLARIFICATION
        stage.updated_at = timestamp
        session.status = SessionStatus.WAITING_CLARIFICATION
        session.updated_at = timestamp
        self._runtime_session.add_all([run, stage])
        self._require_control_session().add(session)

    def assert_can_request_clarification(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        self._assert_requirement_analysis_tail(session=session, run=run, stage=stage)
        if run.status is not RunStatus.RUNNING:
            raise RunLifecycleServiceError(
                "Clarification can be requested only from a running run."
            )
        if stage.status is not StageStatus.RUNNING:
            raise RunLifecycleServiceError(
                "Clarification can be requested only from a running stage."
            )
        if session.status is not SessionStatus.RUNNING:
            raise RunLifecycleServiceError(
                "Clarification can be requested only from a running Session."
            )

    def mark_running_after_clarification_reply(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        self._assert_requirement_analysis_tail(session=session, run=run, stage=stage)
        if run.status is not RunStatus.WAITING_CLARIFICATION:
            raise RunLifecycleServiceError(
                "clarification_reply requires a run in waiting_clarification."
            )
        if stage.status is not StageStatus.WAITING_CLARIFICATION:
            raise RunLifecycleServiceError(
                "clarification_reply requires a stage in waiting_clarification."
            )
        if session.status is not SessionStatus.WAITING_CLARIFICATION:
            raise RunLifecycleServiceError(
                "clarification_reply requires a Session in waiting_clarification."
            )

        timestamp = self._now()
        run.status = RunStatus.RUNNING
        run.updated_at = timestamp
        stage.status = StageStatus.RUNNING
        stage.updated_at = timestamp
        session.status = SessionStatus.RUNNING
        session.updated_at = timestamp
        self._runtime_session.add_all([run, stage])
        self._require_control_session().add(session)

    def _require_control_session(self) -> Session:
        if self._control_session is None:
            raise RunLifecycleServiceError(
                "control_session is required for Session state changes."
            )
        return self._control_session

    @staticmethod
    def _assert_requirement_analysis_tail(
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        if session.current_run_id != run.run_id:
            raise RunLifecycleServiceError("Session current_run_id must match the run.")
        if run.session_id != session.session_id:
            raise RunLifecycleServiceError("Run session_id must match the Session.")
        if run.current_stage_run_id != stage.stage_run_id:
            raise RunLifecycleServiceError(
                "Run current_stage_run_id must match the stage."
            )
        if stage.run_id != run.run_id:
            raise RunLifecycleServiceError("Stage run_id must match the run.")
        if stage.stage_type is not StageType.REQUIREMENT_ANALYSIS:
            raise RunLifecycleServiceError(
                "Clarification is only valid in requirement_analysis."
            )
        if session.latest_stage_type is not StageType.REQUIREMENT_ANALYSIS:
            raise RunLifecycleServiceError(
                "Session latest_stage_type must be requirement_analysis."
            )

    def _load_active_run_context(
        self,
        run_id: str,
    ) -> tuple[SessionModel, PipelineRunModel, StageRunModel]:
        run = self._runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise RunLifecycleServiceError(
                "PipelineRun was not found.",
                error_code=ErrorCode.NOT_FOUND,
                status_code=404,
                detail_ref=run_id,
            )
        control_session = self._require_control_session().get(
            SessionModel,
            run.session_id,
        )
        stage = (
            self._runtime_session.get(StageRunModel, run.current_stage_run_id)
            if run.current_stage_run_id is not None
            else None
        )
        if control_session is None or stage is None or not control_session.is_visible:
            raise RunLifecycleServiceError(
                "Active run context was not found.",
                error_code=ErrorCode.NOT_FOUND,
                status_code=404,
                detail_ref=run_id,
            )
        if control_session.current_run_id != run.run_id:
            self._raise_validation("Pause/resume target must be the current active run.")
        if run.session_id != control_session.session_id:
            self._raise_validation("Run does not belong to the Session.")
        if run.current_stage_run_id != stage.stage_run_id:
            self._raise_validation("Run current_stage_run_id must match the stage.")
        if stage.run_id != run.run_id:
            self._raise_validation("StageRun does not belong to the run.")
        return control_session, run, stage

    def _load_current_session_run_tail(
        self,
        session_id: str,
    ) -> tuple[SessionModel, PipelineRunModel, StageRunModel | None]:
        control_session = self._require_control_session().get(SessionModel, session_id)
        if control_session is None or not control_session.is_visible:
            raise RunLifecycleServiceError(
                "Session was not found.",
                error_code=ErrorCode.NOT_FOUND,
                status_code=404,
                detail_ref=session_id,
            )
        if control_session.current_run_id is None:
            self._raise_validation("A rerun requires an existing current run tail.")
        run = self._runtime_session.get(PipelineRunModel, control_session.current_run_id)
        stage = (
            self._runtime_session.get(StageRunModel, run.current_stage_run_id)
            if run is not None and run.current_stage_run_id is not None
            else None
        )
        if run is None:
            raise RunLifecycleServiceError(
                "Active run context was not found.",
                error_code=ErrorCode.NOT_FOUND,
                status_code=404,
                detail_ref=session_id,
            )
        if run.session_id != control_session.session_id:
            self._raise_validation("Run does not belong to the Session.")
        if run.current_stage_run_id is not None and stage is None:
            raise RunLifecycleServiceError(
                "Active run context was not found.",
                error_code=ErrorCode.NOT_FOUND,
                status_code=404,
                detail_ref=session_id,
            )
        if stage is not None and stage.run_id != run.run_id:
            self._raise_validation("StageRun does not belong to the run.")
        return control_session, run, stage

    def _assert_can_pause(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
    ) -> None:
        if run.status not in {
            RunStatus.RUNNING,
            RunStatus.WAITING_CLARIFICATION,
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_TOOL_CONFIRMATION,
        }:
            self._raise_validation("Run cannot be paused from its current status.")
        if session.status is not RunStateMachine.project_session_status(run.status):
            self._raise_validation("Session status must match run status before pause.")

    def _assert_can_resume(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
    ) -> None:
        if run.status is not RunStatus.PAUSED or session.status is not SessionStatus.PAUSED:
            self._raise_validation("Run can be resumed only when it is paused.")

    def _assert_can_terminate(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
    ) -> None:
        if run.status not in {
            RunStatus.RUNNING,
            RunStatus.WAITING_CLARIFICATION,
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_TOOL_CONFIRMATION,
            RunStatus.PAUSED,
        }:
            self._raise_validation("Run cannot be terminated from its current status.")
        if session.status is not RunStateMachine.project_session_status(run.status):
            self._raise_validation("Session status must match run status before terminate.")

    def _assert_can_create_rerun(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
    ) -> None:
        try:
            RunStateMachine.assert_can_create_rerun(
                session_status=session.status,
                current_run_id=session.current_run_id,
                current_run_status=run.status,
            )
        except InvalidRunStateTransition as exc:
            self._raise_validation(str(exc))

    def _build_rerun(
        self,
        *,
        session: SessionModel,
        source_run: PipelineRunModel,
        started_at: datetime,
    ) -> PipelineRunModel:
        return PipelineRunModel(
            run_id=f"run-{uuid4().hex}",
            session_id=session.session_id,
            project_id=source_run.project_id,
            attempt_index=source_run.attempt_index + 1,
            status=RunStatus.RUNNING,
            trigger_source=RunTriggerSource.RETRY,
            template_snapshot_ref=source_run.template_snapshot_ref,
            graph_definition_ref=source_run.graph_definition_ref,
            graph_thread_ref=f"thread-{uuid4().hex}",
            workspace_ref=source_run.workspace_ref,
            runtime_limit_snapshot_ref=source_run.runtime_limit_snapshot_ref,
            provider_call_policy_snapshot_ref=(
                source_run.provider_call_policy_snapshot_ref
            ),
            delivery_channel_snapshot_ref=source_run.delivery_channel_snapshot_ref,
            current_stage_run_id=None,
            trace_id=f"trace-{uuid4().hex}",
            started_at=started_at,
            ended_at=None,
            created_at=started_at,
            updated_at=started_at,
        )

    def _run_summary_projection(
        self,
        run: PipelineRunModel,
        *,
        current_stage_type: StageType | None,
        is_active: bool,
    ) -> RunSummaryProjection:
        return RunSummaryProjection(
            run_id=run.run_id,
            attempt_index=run.attempt_index,
            status=run.status,
            trigger_source=run.trigger_source,
            started_at=run.started_at,
            ended_at=run.ended_at,
            current_stage_type=current_stage_type,
            is_active=is_active,
        )

    def _append_latest_terminal_system_status_retry_action(
        self,
        *,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        event = (
            self._require_event_session()
            .query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == run.run_id,
                DomainEventModel.event_type == SseEventType.SYSTEM_STATUS,
            )
            .order_by(
                DomainEventModel.sequence_index.desc(),
                DomainEventModel.event_id.desc(),
            )
            .first()
        )
        if event is None:
            return
        system_status = event.payload.get("system_status")
        if not isinstance(system_status, dict):
            return
        if system_status.get("retry_action") is not None:
            return
        status = RunStatus(system_status["status"])
        domain_event_type = (
            DomainEventType.RUN_TERMINATED
            if status is RunStatus.TERMINATED
            else DomainEventType.RUN_FAILED
        )
        terminal_trace = trace_context.child_span(
            span_id=f"runtime-rerun-retry-action-{run.run_id}",
            created_at=occurred_at,
            run_id=run.run_id,
            stage_run_id=trace_context.stage_run_id,
            graph_thread_id=run.graph_thread_ref,
        )
        TerminalStatusProjector(
            events=self._require_events(),
            now=self._now,
        ).append_terminal_system_status(
            domain_event_type=domain_event_type,
            run=run,
            title=system_status["title"],
            reason=system_status["reason"],
            retry_action=f"retry:{run.run_id}",
            trace_context=terminal_trace,
            occurred_at=occurred_at,
        )

    def _record_rejected_session_command(
        self,
        *,
        action: str,
        message: str,
        actor_id: str,
        session_id: str,
        reason: str,
        trace_context: TraceContext,
        started_at: datetime | None = None,
    ) -> None:
        recorded_at = self._now()
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            action=action,
            target_type="session",
            target_id=session_id,
            reason=reason,
            metadata={
                "session_id": session_id,
                "result_status": "rejected",
                "rejected_reason": reason,
            },
            trace_context=trace_context,
            created_at=recorded_at,
        )
        self._record_run_log(
            payload_type="runtime_command_rejected",
            message=message,
            metadata={
                "session_id": session_id,
                "reason": reason,
                "result_status": "rejected",
            },
            trace_context=trace_context,
            created_at=recorded_at,
            level=LogLevel.WARNING,
            error_code=ErrorCode.VALIDATION_ERROR.value,
            duration_ms=self._duration_ms(started_at, recorded_at),
        )

    def _rerun_log_metadata(
        self,
        *,
        session: SessionModel,
        old_run: PipelineRunModel,
        old_stage: StageRunModel | None,
        new_run: PipelineRunModel | None,
        old_trace_id: str,
        result_status: str,
    ) -> dict[str, Any]:
        metadata = {
            "session_id": session.session_id,
            "old_run_id": old_run.run_id,
            "new_run_id": new_run.run_id if new_run is not None else None,
            "stage_run_id": old_stage.stage_run_id if old_stage is not None else None,
            "old_graph_thread_id": old_run.graph_thread_ref,
            "new_graph_thread_id": (
                new_run.graph_thread_ref if new_run is not None else None
            ),
            "old_trace_id": old_trace_id,
            "new_trace_id": new_run.trace_id if new_run is not None else None,
            "trigger_source": RunTriggerSource.RETRY.value,
            "old_attempt_index": old_run.attempt_index,
            "new_attempt_index": (
                new_run.attempt_index if new_run is not None else old_run.attempt_index + 1
            ),
            "result_status": result_status,
        }
        if new_run is not None:
            metadata.update(
                self.build_rerun_trigger_metadata(
                    old_run=old_run,
                    new_run=new_run,
                    old_trace_id=old_trace_id,
                )
            )
        return metadata

    def _mark_terminal(
        self,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        terminal_status: RunStatus,
        occurred_at: datetime,
    ) -> None:
        run.status = terminal_status
        run.ended_at = occurred_at
        run.updated_at = occurred_at
        stage.status = StageStatus.TERMINATED
        stage.ended_at = occurred_at
        stage.updated_at = occurred_at
        session.status = RunStateMachine.project_session_status(terminal_status)
        session.updated_at = occurred_at
        self._runtime_session.add_all([run, stage])
        self._require_control_session().add(session)

    def _persist_recovery_checkpoint(
        self,
        *,
        control_session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel,
        checkpoint: CheckpointRef | None,
        saved_at: datetime,
    ) -> StageArtifactModel:
        if checkpoint is None:
            raise RunLifecycleServiceError(
                "pause checkpoint is required before persisting recovery state.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run.run_id,
            )
        artifact = StageArtifactModel(
            artifact_id=f"artifact-recovery-{uuid4().hex}",
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id,
            artifact_type="recovery_checkpoint",
            payload_ref=checkpoint.checkpoint_id,
            process={
                "checkpoint": checkpoint.model_dump(mode="json"),
                "graph_thread_ref": run.graph_thread_ref,
                "workspace_snapshot_ref": checkpoint.workspace_snapshot_ref,
                "run_status_before_pause": run.status.value,
                "session_status_before_pause": control_session.status.value,
                "stage_status_before_pause": stage.status.value,
            },
            metrics={},
            created_at=saved_at,
        )
        self._runtime_session.add(artifact)
        return artifact

    def _latest_recovery_checkpoint(self, *, run_id: str) -> StageArtifactModel:
        artifact = (
            self._runtime_session.execute(
                select(StageArtifactModel)
                .where(
                    StageArtifactModel.run_id == run_id,
                    StageArtifactModel.artifact_type == "recovery_checkpoint",
                )
                .order_by(
                    StageArtifactModel.created_at.desc(),
                    StageArtifactModel.artifact_id.desc(),
                )
                .execution_options(populate_existing=True)
            )
            .scalars()
            .first()
        )
        if artifact is None:
            raise RunLifecycleServiceError(
                "recovery checkpoint was not found.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
                detail_ref=run_id,
            )
        return artifact

    def _validate_recovery_checkpoint(
        self,
        *,
        artifact: StageArtifactModel,
        checkpoint: CheckpointRef,
        run: PipelineRunModel,
        stage: StageRunModel,
    ) -> None:
        process = artifact.process
        if artifact.artifact_type != "recovery_checkpoint":
            self._raise_checkpoint_error(run.run_id)
        if artifact.run_id != run.run_id or artifact.stage_run_id != stage.stage_run_id:
            self._raise_checkpoint_error(run.run_id)
        if artifact.payload_ref != checkpoint.checkpoint_id:
            self._raise_checkpoint_error(run.run_id)
        if process.get("graph_thread_ref") != run.graph_thread_ref:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.run_id != run.run_id:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.thread_id != run.graph_thread_ref:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.stage_run_id != stage.stage_run_id:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.stage_type is not stage.stage_type:
            self._raise_checkpoint_error(run.run_id)
        if checkpoint.purpose.value != "pause":
            self._raise_checkpoint_error(run.run_id)
        pre_pause_status = RunStatus(process.get("run_status_before_pause"))
        if pre_pause_status not in {
            RunStatus.RUNNING,
            RunStatus.WAITING_CLARIFICATION,
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_TOOL_CONFIRMATION,
        }:
            self._raise_checkpoint_error(run.run_id)
        if process.get("session_status_before_pause") != (
            RunStateMachine.project_session_status(pre_pause_status).value
        ):
            self._raise_checkpoint_error(run.run_id)
        if process.get("stage_status_before_pause") != stage.status.value:
            self._raise_checkpoint_error(run.run_id)

    @staticmethod
    def _raise_checkpoint_error(run_id: str) -> None:
        raise RunLifecycleServiceError(
            "recovery checkpoint metadata is invalid for this run.",
            error_code=ErrorCode.INTERNAL_ERROR,
            status_code=500,
            detail_ref=run_id,
        )

    def _append_run_status_event(
        self,
        domain_event_type: DomainEventType,
        *,
        session: SessionModel,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        self._require_events().append(
            domain_event_type,
            payload={
                "session_id": session.session_id,
                "status": session.status.value,
                "current_run_id": run.run_id,
                "current_stage_type": session.latest_stage_type.value
                if session.latest_stage_type is not None
                else None,
            },
            trace_context=trace_context,
            occurred_at=occurred_at,
        )

    def _refresh_pending_wait_entry_for_pause(
        self,
        *,
        pre_pause_status: RunStatus,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        if pre_pause_status is RunStatus.WAITING_APPROVAL:
            projection = self._latest_approval_request_projection(run_id=run.run_id)
            if projection is None:
                return
            paused = projection.model_copy(
                update={
                    "occurred_at": occurred_at,
                    "is_actionable": False,
                    "disabled_reason": (
                        "Current run is paused; resume it to continue approval."
                    ),
                }
            )
            self._require_events().append(
                DomainEventType.APPROVAL_REQUESTED,
                payload={"approval_request": paused.model_dump(mode="json")},
                trace_context=trace_context,
                occurred_at=occurred_at,
            )
        if pre_pause_status is RunStatus.WAITING_TOOL_CONFIRMATION:
            projection = self._latest_tool_confirmation_projection(run_id=run.run_id)
            if projection is None:
                return
            paused = projection.model_copy(
                update={
                    "occurred_at": occurred_at,
                    "is_actionable": False,
                    "disabled_reason": (
                        "Current run is paused; resume it to continue tool confirmation."
                    ),
                }
            )
            self._require_events().append(
                DomainEventType.TOOL_CONFIRMATION_REQUESTED,
                payload={"tool_confirmation": paused.model_dump(mode="json")},
                trace_context=trace_context,
                occurred_at=occurred_at,
            )

    def _refresh_pending_wait_entry_for_resume(
        self,
        *,
        pre_pause_status: RunStatus,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        if pre_pause_status is RunStatus.WAITING_APPROVAL:
            projection = self._latest_approval_request_projection(run_id=run.run_id)
            if projection is None:
                return
            resumed = projection.model_copy(
                update={
                    "occurred_at": occurred_at,
                    "is_actionable": True,
                    "disabled_reason": None,
                }
            )
            self._require_events().append(
                DomainEventType.APPROVAL_REQUESTED,
                payload={"approval_request": resumed.model_dump(mode="json")},
                trace_context=trace_context,
                occurred_at=occurred_at,
            )
        if pre_pause_status is RunStatus.WAITING_TOOL_CONFIRMATION:
            projection = self._latest_tool_confirmation_projection(run_id=run.run_id)
            if projection is None:
                return
            resumed = projection.model_copy(
                update={
                    "occurred_at": occurred_at,
                    "is_actionable": True,
                    "disabled_reason": None,
                }
            )
            self._require_events().append(
                DomainEventType.TOOL_CONFIRMATION_REQUESTED,
                payload={"tool_confirmation": resumed.model_dump(mode="json")},
                trace_context=trace_context,
                occurred_at=occurred_at,
            )

    def _refresh_pending_wait_entry_for_terminate(
        self,
        *,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        projection = self._latest_approval_request_projection(run_id=run.run_id)
        if projection is None:
            return
        terminated = projection.model_copy(
            update={
                "occurred_at": occurred_at,
                "is_actionable": False,
                "disabled_reason": (
                    "Current run is terminated; this approval remains as history only."
                ),
            }
        )
        self._require_events().append(
            DomainEventType.APPROVAL_REQUESTED,
            payload={"approval_request": terminated.model_dump(mode="json")},
            trace_context=trace_context,
            occurred_at=occurred_at,
        )

    def _cancel_pending_tool_confirmations_for_terminal_run(
        self,
        *,
        run: PipelineRunModel,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        result = self._tool_confirmation_service().cancel_for_terminal_run(
            run_id=run.run_id,
            trace_context=trace_context,
            commit=False,
        )
        for projection in result.cancelled_confirmations:
            self._append_cancelled_tool_confirmation_projection(
                projection=projection,
                trace_context=trace_context,
                occurred_at=occurred_at,
            )

    def _append_cancelled_tool_confirmation_projection(
        self,
        *,
        projection: ToolConfirmationFeedEntry,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        self._require_events().append(
            DomainEventType.TOOL_CONFIRMATION_REQUESTED,
            payload={"tool_confirmation": projection.model_dump(mode="json")},
            trace_context=trace_context,
            occurred_at=occurred_at,
        )

    def _tool_confirmation_service(self) -> ToolConfirmationService:
        return ToolConfirmationService(
            control_session=self._require_control_session(),
            runtime_session=self._runtime_session,
            event_session=self._require_event_session(),
            runtime_orchestration=self._require_runtime_orchestration(),
            audit_service=self._audit_service,
            log_writer=self._log_writer,
            redaction_policy=self._redaction_policy,
            now=self._now,
        )

    def _latest_approval_request_projection(
        self,
        *,
        run_id: str,
    ) -> ApprovalRequestFeedEntry | None:
        pending_ids = {
            approval.approval_id
            for approval in self._runtime_session.execute(
                select(ApprovalRequestModel).where(
                    ApprovalRequestModel.run_id == run_id,
                    ApprovalRequestModel.status == ApprovalStatus.PENDING,
                )
            )
            .scalars()
            .all()
        }
        if not pending_ids:
            return None
        events = (
            self._require_event_session()
            .query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == run_id,
                DomainEventModel.event_type == SseEventType.APPROVAL_REQUESTED,
            )
            .order_by(
                DomainEventModel.sequence_index.desc(),
                DomainEventModel.event_id.desc(),
            )
            .all()
        )
        for event in events:
            payload = event.payload.get("approval_request")
            if isinstance(payload, dict) and payload.get("approval_id") in pending_ids:
                return ApprovalRequestFeedEntry.model_validate(payload)
        return None

    def _latest_tool_confirmation_projection(
        self,
        *,
        run_id: str,
    ) -> ToolConfirmationFeedEntry | None:
        pending_ids = {
            request.tool_confirmation_id
            for request in self._runtime_session.execute(
                select(ToolConfirmationRequestModel).where(
                    ToolConfirmationRequestModel.run_id == run_id,
                    ToolConfirmationRequestModel.status == ToolConfirmationStatus.PENDING,
                )
            )
            .scalars()
            .all()
        }
        if not pending_ids:
            return None
        events = (
            self._require_event_session()
            .query(DomainEventModel)
            .filter(
                DomainEventModel.run_id == run_id,
                DomainEventModel.event_type == SseEventType.TOOL_CONFIRMATION_REQUESTED,
            )
            .order_by(
                DomainEventModel.sequence_index.desc(),
                DomainEventModel.event_id.desc(),
            )
            .all()
        )
        for event in events:
            payload = event.payload.get("tool_confirmation")
            if (
                isinstance(payload, dict)
                and payload.get("tool_confirmation_id") in pending_ids
            ):
                return ToolConfirmationFeedEntry.model_validate(payload)
        return None

    def _build_thread_ref(
        self,
        *,
        run: PipelineRunModel,
        stage: StageRunModel | None,
        paused: bool = False,
    ) -> GraphThreadRef:
        return GraphThreadRef(
            thread_id=run.graph_thread_ref,
            run_id=run.run_id,
            status=GraphThreadStatus.PAUSED if paused else GraphThreadStatus(run.status.value),
            current_stage_run_id=stage.stage_run_id if stage is not None else None,
            current_stage_type=stage.stage_type if stage is not None else None,
        )

    def _command_trace(
        self,
        trace_context: TraceContext,
        *,
        span_id: str,
        session: SessionModel,
        run: PipelineRunModel,
        stage: StageRunModel | None,
    ) -> TraceContext:
        return trace_context.child_span(
            span_id=span_id,
            created_at=self._now(),
            session_id=session.session_id,
            run_id=run.run_id,
            stage_run_id=stage.stage_run_id if stage is not None else None,
            graph_thread_id=run.graph_thread_ref,
        )

    def _record_rejected_command(
        self,
        *,
        action: str,
        message: str,
        actor_id: str,
        run: PipelineRunModel,
        stage: StageRunModel | None,
        reason: str,
        trace_context: TraceContext,
        started_at: datetime | None = None,
    ) -> None:
        recorded_at = self._now()
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            action=action,
            target_type="run",
            target_id=run.run_id,
            reason=reason,
            metadata={
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id if stage is not None else None,
                "result_status": "rejected",
                "rejected_reason": reason,
            },
            trace_context=trace_context,
            created_at=recorded_at,
        )
        self._record_run_log(
            payload_type="runtime_command_rejected",
            message=message,
            metadata={
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id if stage is not None else None,
                "reason": reason,
                "result_status": "rejected",
            },
            trace_context=trace_context,
            created_at=recorded_at,
            level=LogLevel.WARNING,
            error_code=ErrorCode.VALIDATION_ERROR.value,
            duration_ms=self._duration_ms(started_at, recorded_at),
        )

    def _record_failed_command(
        self,
        *,
        action: str,
        message: str,
        actor_id: str,
        run: PipelineRunModel,
        stage: StageRunModel | None,
        reason: str,
        trace_context: TraceContext,
        started_at: datetime | None = None,
    ) -> None:
        recorded_at = self._now()
        try:
            self._audit_service.record_failed_command(
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                action=action,
                target_type="run",
                target_id=run.run_id,
                reason=reason,
                metadata={
                    "run_id": run.run_id,
                    "stage_run_id": stage.stage_run_id if stage is not None else None,
                    "result_status": "failed",
                },
                trace_context=trace_context,
                created_at=recorded_at,
            )
        except Exception:
            pass
        self._record_run_log(
            payload_type="runtime_command_failed",
            message=message,
            metadata={
                "run_id": run.run_id,
                "stage_run_id": stage.stage_run_id if stage is not None else None,
                "reason": reason,
                "result_status": "failed",
            },
            trace_context=trace_context,
            created_at=recorded_at,
            level=LogLevel.ERROR,
            error_code=ErrorCode.INTERNAL_ERROR.value,
            duration_ms=self._duration_ms(started_at, recorded_at),
        )

    def _record_run_log(
        self,
        *,
        payload_type: str,
        message: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
        level: LogLevel,
        error_code: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        redacted_payload = self._redaction_policy.summarize_payload(
            metadata,
            payload_type=payload_type,
        )
        try:
            record = LogRecordInput(
                source="services.runs",
                category=LogCategory.RUNTIME,
                level=level,
                message=message,
                trace_context=trace_context,
                payload=LogPayloadSummary.from_redacted_payload(
                    payload_type,
                    redacted_payload,
                ),
                created_at=created_at,
                duration_ms=duration_ms,
                error_code=error_code,
            )
            if trace_context.run_id is not None:
                self._log_writer.write_run_log(record)
            elif hasattr(self._log_writer, "write"):
                self._log_writer.write(record)
            else:
                self._log_writer.write_run_log(record)
        except Exception:
            pass

    @staticmethod
    def _duration_ms(started_at: datetime | None, ended_at: datetime) -> int | None:
        if started_at is None:
            return None
        return max(0, int((ended_at - started_at).total_seconds() * 1000))

    def _commit_all(self) -> None:
        self._runtime_session.commit()
        self._require_control_session().commit()
        self._require_event_session().commit()
        if self._graph_session is not None:
            self._graph_session.commit()

    def _commit_first_run_startup(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        publication_id: str | None,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> PublishedStartupVisibility:
        if publication_id is None:
            raise RunLifecycleServiceError(
                "startup publication is required for first run startup.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
            )

        self._runtime_session.commit()
        self._require_event_session().commit()
        if self._graph_session is not None:
            self._graph_session.commit()
        return self._publication_boundary_service().publish_startup_visibility(
            publication_id=publication_id,
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            trace_context=trace_context,
            published_at=occurred_at,
        )

    def _commit_rerun_all(
        self,
        *,
        session_id: str,
        session_snapshot: RerunSessionState,
        new_run_id: str,
    ) -> None:
        runtime_committed = False
        control_committed = False
        try:
            self._runtime_session.commit()
            runtime_committed = True
            self._require_control_session().commit()
            control_committed = True
            self._require_event_session().commit()
        except Exception:
            self._rollback_all()
            self._compensate_rerun_partial_commit(
                session_id=session_id,
                session_snapshot=session_snapshot,
                new_run_id=new_run_id,
                runtime_committed=runtime_committed,
                control_committed=control_committed,
            )
            raise

    def _compensate_rerun_partial_commit(
        self,
        *,
        session_id: str,
        session_snapshot: RerunSessionState,
        new_run_id: str,
        runtime_committed: bool,
        control_committed: bool,
    ) -> None:
        control_restored = not control_committed
        control_error: Exception | None = None
        runtime_error: Exception | None = None

        if control_committed:
            try:
                control_session = self._require_control_session()
                control_session.rollback()
                session = control_session.get(SessionModel, session_id)
                if session is None:
                    raise RuntimeError("rerun compensation could not reload the session.")
                session.current_run_id = session_snapshot.current_run_id
                session.status = session_snapshot.status
                session.latest_stage_type = session_snapshot.latest_stage_type
                session.updated_at = session_snapshot.updated_at
                control_session.add(session)
                control_session.commit()
                control_restored = True
            except Exception as exc:
                control_error = exc

        if runtime_committed and control_restored:
            try:
                self._runtime_session.rollback()
                run = self._runtime_session.get(PipelineRunModel, new_run_id)
                if run is not None:
                    self._runtime_session.delete(run)
                    self._runtime_session.commit()
            except Exception as exc:
                runtime_error = exc

        if control_error is not None or runtime_error is not None:
            self._rollback_all()
            detail = str(control_error or runtime_error)
            raise RuntimeError(
                f"rerun compensation failed after partial commit: {detail}"
            ) from (control_error or runtime_error)

    def _rollback_all(self) -> None:
        self._runtime_session.rollback()
        if self._control_session is not None:
            self._control_session.rollback()
        if self._event_session is not None:
            self._event_session.rollback()
        if self._graph_session is not None:
            self._graph_session.rollback()

    def _require_event_session(self) -> Session:
        if self._event_session is None:
            raise RunLifecycleServiceError(
                "event_session is required for run lifecycle events.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
            )
        return self._event_session

    def _require_graph_session(self) -> Session:
        if self._graph_session is None:
            raise RunLifecycleServiceError(
                "graph_session is required for first run startup.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
            )
        return self._graph_session

    def _require_events(self) -> EventStore:
        if self._events is None:
            raise RunLifecycleServiceError(
                "event_session is required for run lifecycle events.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
            )
        return self._events

    def _require_runtime_orchestration(self) -> RuntimeOrchestrationService:
        if self._runtime_orchestration is None:
            raise RunLifecycleServiceError(
                "runtime_orchestration is required for pause/resume commands.",
                error_code=ErrorCode.INTERNAL_ERROR,
                status_code=500,
            )
        return self._runtime_orchestration

    @staticmethod
    def _raise_validation(message: str) -> None:
        raise RunLifecycleServiceError(
            message,
            error_code=ErrorCode.RUN_COMMAND_NOT_ACTIONABLE,
            status_code=409,
        )

    def _load_visible_session_for_start(self, session_id: str) -> SessionModel:
        session = (
            self._require_control_session()
            .query(SessionModel)
            .filter(
                SessionModel.session_id == session_id,
                SessionModel.is_visible.is_(True),
            )
            .populate_existing()
            .one_or_none()
        )
        if session is None:
            raise RunLifecycleServiceError(
                "Session was not found.",
                error_code=ErrorCode.NOT_FOUND,
                status_code=404,
                detail_ref=session_id,
            )
        return session

    def _begin_startup_publication(
        self,
        *,
        session_id: str,
        run_id: str,
        stage_run_id: str,
        started_at: datetime,
        trace_context: TraceContext,
    ):
        del started_at
        try:
            return self._publication_boundary_service().begin_startup_publication(
                session_id=session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                trace_context=trace_context,
            )
        except PublicationBoundaryServiceError as exc:
            raise RunLifecycleServiceError(
                exc.message,
                error_code=exc.error_code,
                status_code=exc.status_code,
                detail_ref=session_id,
            ) from exc

    def _abort_startup_if_needed(
        self,
        *,
        publication_id: str | None,
        session_id: str,
        run_id: str,
        reason: str,
        trace_context: TraceContext,
        occurred_at: datetime,
    ) -> None:
        if publication_id is None:
            self._rollback_all()
            return
        try:
            self._publication_boundary_service().abort_startup_publication(
                publication_id=publication_id,
                session_id=session_id,
                run_id=run_id,
                reason=reason,
                trace_context=trace_context,
                aborted_at=occurred_at,
            )
        except PublicationBoundaryServiceError:
            self._rollback_all()

    def _published_session_view(
        self,
        *,
        session: SessionModel,
        run_id: str,
        occurred_at: datetime,
    ):
        return SimpleNamespace(
            session_id=session.session_id,
            status=SessionStatus.RUNNING,
            current_run_id=run_id,
            latest_stage_type=StageType.REQUIREMENT_ANALYSIS,
            updated_at=occurred_at,
        )

    def _publication_boundary_service(self) -> PublicationBoundaryService:
        if self._publication_boundary is None:
            self._publication_boundary = PublicationBoundaryService(
                control_session=self._require_control_session(),
                runtime_session=self._runtime_session,
                graph_session=self._graph_session,
                event_session=self._event_session,
                audit_service=self._audit_service,
                log_writer=self._log_writer,
                now=self._now,
            )
        return self._publication_boundary

    def _build_stage_started_projection(
        self,
        *,
        run_id: str,
        stage: StageRunModel,
        occurred_at: datetime,
    ) -> ExecutionNodeProjection:
        return ExecutionNodeProjection(
            entry_id=_bounded_id("entry", stage.stage_run_id),
            run_id=run_id,
            occurred_at=occurred_at,
            stage_run_id=stage.stage_run_id,
            stage_type=stage.stage_type,
            status=stage.status,
            attempt_index=stage.attempt_index,
            started_at=stage.started_at,
            ended_at=stage.ended_at,
            summary=stage.summary or f"{stage.stage_type.value} started.",
            items=[],
            metrics={},
        )

    def _load_required_providers(
        self,
        *,
        template_snapshot: TemplateSnapshot,
        settings_read,
    ) -> list[ProviderModel]:
        provider_ids = self._required_provider_ids(template_snapshot, settings_read)
        control_session = self._require_control_session()
        providers: list[ProviderModel] = []
        missing: list[str] = []
        for provider_id in provider_ids:
            provider = control_session.get(ProviderModel, provider_id)
            if provider is None:
                missing.append(provider_id)
                continue
            if not provider.is_configured or not provider.is_enabled:
                missing.append(provider_id)
                continue
            providers.append(provider)
        if missing:
            raise ProviderSnapshotBuilderError(
                ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
                "Required Provider configuration is unavailable: "
                + ", ".join(missing)
                + ".",
            )
        return providers

    @staticmethod
    def _required_provider_ids(template_snapshot: TemplateSnapshot, settings_read) -> tuple[str, ...]:
        provider_ids = {
            binding.provider_id for binding in template_snapshot.stage_role_bindings
        }
        bindings = settings_read.internal_model_bindings.model_dump(mode="python")
        for binding in bindings.values():
            provider_ids.add(binding["provider_id"])
        return tuple(sorted(provider_ids))

    @staticmethod
    def _required_model_ids_by_provider(settings_read) -> dict[str, tuple[str, ...]]:
        by_provider: dict[str, list[str]] = {}
        bindings = settings_read.internal_model_bindings.model_dump(mode="python")
        for binding in bindings.values():
            by_provider.setdefault(binding["provider_id"], []).append(binding["model_id"])
        return {
            provider_id: tuple(dict.fromkeys(model_ids))
            for provider_id, model_ids in by_provider.items()
        }

    @staticmethod
    def _internal_bindings_from_settings(settings_read) -> tuple[InternalModelBindingSelection, ...]:
        bindings = settings_read.internal_model_bindings.model_dump(mode="python")
        return tuple(
            InternalModelBindingSelection(
                binding_type=binding_type,
                provider_id=binding["provider_id"],
                model_id=binding["model_id"],
                model_parameters=dict(binding["model_parameters"]),
            )
            for binding_type, binding in bindings.items()
        )

    def _record_start_rejected(
        self,
        *,
        session: SessionModel,
        reason: str,
        trace_context: TraceContext,
        started_at: datetime,
    ) -> None:
        try:
            self._audit_service.record_rejected_command(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action="session.message.new_requirement.rejected",
                target_type="session",
                target_id=session.session_id,
                reason=reason,
                metadata={
                    "session_id": session.session_id,
                    "status": session.status.value,
                    "current_run_id": session.current_run_id,
                    "result_status": "rejected",
                },
                trace_context=trace_context,
                created_at=started_at,
            )
        except Exception:
            pass
        self._record_run_log(
            payload_type="run_start_rejected",
            message="First run startup rejected.",
            metadata={
                "session_id": session.session_id,
                "reason": reason,
                "result_status": "rejected",
            },
            trace_context=trace_context,
            created_at=started_at,
            level=LogLevel.WARNING,
            error_code=ErrorCode.VALIDATION_ERROR.value,
        )

    def _record_start_failed(
        self,
        *,
        session: SessionModel,
        reason: str,
        trace_context: TraceContext,
        started_at: datetime,
        error_code: ErrorCode,
    ) -> None:
        try:
            self._audit_service.record_failed_command(
                actor_type=AuditActorType.USER,
                actor_id="api-user",
                action="session.message.new_requirement.failed",
                target_type="session",
                target_id=session.session_id,
                reason=reason,
                metadata={
                    "session_id": session.session_id,
                    "result_status": "failed",
                },
                trace_context=trace_context,
                created_at=started_at,
            )
        except Exception:
            pass
        self._record_run_log(
            payload_type="run_start_failed",
            message="First run startup failed.",
            metadata={
                "session_id": session.session_id,
                "reason": reason,
                "result_status": "failed",
            },
            trace_context=trace_context,
            created_at=started_at,
            level=LogLevel.ERROR,
            error_code=error_code.value,
        )


class _NoopAuditService:
    def require_audit_record(self, **kwargs: Any) -> object:
        return object()

    def record_command_result(self, **kwargs: Any) -> object:
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        return object()

    def record_failed_command(self, **kwargs: Any) -> object:
        return object()


class _NoopRunLogWriter:
    def write_run_log(self, record: LogRecordInput) -> object:
        return object()


class _RejectedRunLifecycleServiceError(RunLifecycleServiceError):
    pass


class _NoopRunPromptValidationService:
    def validate_run_prompt_snapshots(
        self,
        *,
        template_snapshot: TemplateSnapshot,
        trace_context: TraceContext,
    ) -> None:
        return None


__all__ = [
    "RunCommandResult",
    "RunLifecycleService",
    "RunLifecycleServiceError",
    "TerminalStatusProjector",
    "RunPromptValidationError",
    "StartFirstRunResult",
]


def _bounded_id(prefix: str, suffix: str) -> str:
    candidate = f"{prefix}-{suffix}"
    if len(candidate) <= 80:
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _graph_thread_id(run_id: str) -> str:
    return _bounded_id("graph-thread", run_id)


def _workspace_ref(run_id: str) -> str:
    return f"workspace-{run_id}"


def _trace_id() -> str:
    return _bounded_id("trace", uuid4().hex)


def _fork_trace(
    parent: TraceContext,
    *,
    trace_id: str | None = None,
    span_id: str,
    created_at: datetime,
    **object_updates: Any,
) -> TraceContext:
    data = parent.model_dump()
    data.update(object_updates)
    if trace_id is not None:
        data["trace_id"] = trace_id
    data["parent_span_id"] = parent.span_id
    data["span_id"] = span_id
    data["created_at"] = created_at
    return TraceContext.model_validate(data)
