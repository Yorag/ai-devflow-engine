from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from backend.app.context.source_resolver import ContextSourceResolver
from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import (
    ControlBase,
    DeliveryChannelModel,
    PipelineTemplateModel,
    ProjectModel,
    SessionModel,
)
from backend.app.db.models.event import EventBase
from backend.app.db.models.log import AuditLogEntryModel, LogBase
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ApprovalRequestModel,
    DeliveryChannelSnapshotModel,
    DeliveryRecordModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    ProviderSnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    SessionStatus,
    StageStatus,
    StageType,
    TemplateSource,
    ToolConfirmationStatus,
    ToolRiskLevel,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.services.delivery_channels import DEFAULT_PROJECT_ID
from backend.app.services.projects import (
    DEFAULT_PROJECT_REMOVE_BLOCKED_MESSAGE,
    PROJECT_REMOVE_BLOCKED_ERROR_CODE,
    PROJECT_REMOVE_BLOCKED_MESSAGE,
    PROJECT_REMOVE_SUCCESS_MESSAGE,
    ProjectService,
    ProjectServiceError,
)
from backend.app.services.projections.workspace import (
    WorkspaceProjectionService,
    WorkspaceProjectionServiceError,
)
from backend.app.services.sessions import (
    SESSION_DELETE_BLOCKED_ERROR_CODE,
    SESSION_DELETE_BLOCKED_MESSAGE,
    SESSION_DELETE_SUCCESS_MESSAGE,
    SessionService,
    SessionServiceError,
)


NOW = datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append(
            {
                "method": "record_rejected_command",
                "result": AuditResult.REJECTED,
                **kwargs,
            }
        )
        return object()


def _manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    EventBase.metadata.create_all(manager.engine(DatabaseRole.EVENT))
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    return manager


def _settings(tmp_path: Path) -> EnvironmentSettings:
    default_root = tmp_path / "default-project"
    default_root.mkdir(exist_ok=True)
    return EnvironmentSettings(
        platform_runtime_root=tmp_path / "runtime",
        default_project_root=default_root,
    )


def _trace(
    label: str,
    *,
    session_id: str | None = None,
    run_id: str | None = None,
    stage_run_id: str | None = None,
) -> TraceContext:
    return TraceContext(
        request_id=f"req-{label}",
        trace_id=f"trace-{label}",
        correlation_id=f"corr-{label}",
        span_id=f"span-{label}",
        parent_span_id=None,
        session_id=session_id,
        run_id=run_id,
        stage_run_id=stage_run_id,
        created_at=NOW,
    )


def _seed_system_templates(session) -> None:  # noqa: ANN001
    for template_id in ("template-bugfix", "template-feature", "template-refactor"):
        if session.get(PipelineTemplateModel, template_id) is not None:
            continue
        session.add(
            PipelineTemplateModel(
                template_id=template_id,
                name=template_id,
                description=None,
                template_source=TemplateSource.SYSTEM_TEMPLATE,
                base_template_id=None,
                fixed_stage_sequence=[],
                stage_role_bindings=[],
                approval_checkpoints=[],
                auto_regression_enabled=True,
                max_auto_regression_retries=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _seed_project(
    manager: DatabaseManager,
    *,
    project_id: str,
    root_path: Path,
    is_default: bool = False,
    is_visible: bool = True,
    removed_at: datetime | None = None,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        _seed_system_templates(session)
        session.add(
            ProjectModel(
                project_id=project_id,
                name=root_path.name,
                root_path=str(root_path.resolve(strict=False)),
                default_delivery_channel_id=f"delivery-{project_id}",
                is_default=is_default,
                is_visible=is_visible,
                visibility_removed_at=removed_at,
                created_at=NOW,
                updated_at=removed_at or NOW,
            )
        )
        session.flush()
        session.add(
            DeliveryChannelModel(
                delivery_channel_id=f"delivery-{project_id}",
                project_id=project_id,
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
                scm_provider_type=None,
                repository_identifier=None,
                default_branch=None,
                code_review_request_type=None,
                credential_ref=None,
                credential_status=CredentialStatus.READY,
                readiness_status=DeliveryReadinessStatus.READY,
                readiness_message=None,
                last_validated_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def _seed_session(
    manager: DatabaseManager,
    *,
    project_id: str,
    session_id: str,
    status: SessionStatus = SessionStatus.DRAFT,
    current_run_id: str | None = None,
    is_visible: bool = True,
    removed_at: datetime | None = None,
    updated_at: datetime = NOW,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            SessionModel(
                session_id=session_id,
                project_id=project_id,
                display_name=session_id,
                status=status,
                selected_template_id="template-feature",
                current_run_id=current_run_id,
                latest_stage_type=None,
                is_visible=is_visible,
                visibility_removed_at=removed_at,
                created_at=NOW,
                updated_at=updated_at,
            )
        )
        session.commit()


def _seed_runtime_truth(
    manager: DatabaseManager,
    *,
    project_id: str,
    session_id: str,
    run_id: str,
    run_status: RunStatus,
    attempt_index: int = 1,
    include_history_facts: bool = True,
) -> None:
    stage_run_id = f"stage-{run_id}"
    runtime_limit_ref = f"runtime-limit-{run_id}"
    provider_policy_ref = f"provider-policy-{run_id}"
    delivery_snapshot_ref = (
        f"delivery-snapshot-{run_id}" if include_history_facts else None
    )
    is_terminal = run_status in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.TERMINATED,
    }

    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RuntimeLimitSnapshotModel(
                snapshot_id=runtime_limit_ref,
                run_id=run_id,
                agent_limits={"max_react_iterations_per_stage": 5},
                context_limits={"compression_threshold_ratio": 0.8},
                source_config_version="runtime-config-v1",
                hard_limits_version="hard-limits-v1",
                schema_version="runtime-limit-snapshot-v1",
                created_at=NOW,
            )
        )
        session.add(
            ProviderCallPolicySnapshotModel(
                snapshot_id=provider_policy_ref,
                run_id=run_id,
                provider_call_policy={"network_error_max_retries": 2},
                source_config_version="runtime-config-v1",
                schema_version="provider-call-policy-snapshot-v1",
                created_at=NOW,
            )
        )
        if delivery_snapshot_ref is not None:
            session.add(
                DeliveryChannelSnapshotModel(
                    delivery_channel_snapshot_id=delivery_snapshot_ref,
                    run_id=run_id,
                    source_delivery_channel_id=f"delivery-{project_id}",
                    delivery_mode=DeliveryMode.DEMO_DELIVERY,
                    scm_provider_type=ScmProviderType.GITHUB,
                    repository_identifier="example/project",
                    default_branch="main",
                    code_review_request_type=None,
                    credential_ref=None,
                    credential_status=CredentialStatus.READY,
                    readiness_status=DeliveryReadinessStatus.READY,
                    readiness_message="Ready.",
                    last_validated_at=NOW,
                    schema_version="delivery-channel-snapshot-v1",
                    created_at=NOW,
                )
            )
        session.commit()
        session.add(
            PipelineRunModel(
                run_id=run_id,
                session_id=session_id,
                project_id=project_id,
                attempt_index=attempt_index,
                status=run_status,
                trigger_source=(
                    RunTriggerSource.INITIAL_REQUIREMENT
                    if attempt_index == 1
                    else RunTriggerSource.RETRY
                ),
                template_snapshot_ref=f"template-snapshot-{run_id}",
                graph_definition_ref=f"graph-definition-{run_id}",
                graph_thread_ref=f"graph-thread-{run_id}",
                workspace_ref=f"workspace-{run_id}",
                runtime_limit_snapshot_ref=runtime_limit_ref,
                provider_call_policy_snapshot_ref=provider_policy_ref,
                delivery_channel_snapshot_ref=delivery_snapshot_ref,
                current_stage_run_id=stage_run_id,
                trace_id=f"trace-{run_id}",
                started_at=NOW + timedelta(minutes=attempt_index),
                ended_at=None if not is_terminal else NOW + timedelta(minutes=4),
                created_at=NOW + timedelta(minutes=attempt_index),
                updated_at=NOW + timedelta(minutes=4),
            )
        )
        session.commit()
        session.add(
            ProviderSnapshotModel(
                snapshot_id=f"provider-snapshot-{run_id}",
                run_id=run_id,
                provider_id="provider-deepseek",
                display_name="DeepSeek",
                provider_source=ProviderSource.BUILTIN,
                protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
                base_url="https://api.deepseek.com",
                api_key_ref="env:DEEPSEEK_API_KEY",
                model_id="deepseek-chat",
                capabilities={
                    "context_window_tokens": 128000,
                    "max_output_tokens": 8192,
                },
                source_config_version="provider-config-v1",
                schema_version="provider-snapshot-v1",
                created_at=NOW,
            )
        )
        session.add(
            StageRunModel(
                stage_run_id=stage_run_id,
                run_id=run_id,
                stage_type=StageType.CODE_GENERATION,
                status=StageStatus.COMPLETED if is_terminal else StageStatus.RUNNING,
                attempt_index=1,
                graph_node_key="code_generation.main",
                stage_contract_ref="stage-contract-code-generation",
                input_ref=None,
                output_ref=f"artifact-{run_id}" if include_history_facts else None,
                summary="Code generation stage.",
                started_at=NOW + timedelta(minutes=2),
                ended_at=None if not is_terminal else NOW + timedelta(minutes=3),
                created_at=NOW + timedelta(minutes=2),
                updated_at=NOW + timedelta(minutes=3),
            )
        )
        session.commit()
        if not include_history_facts:
            return
        session.add(
            StageArtifactModel(
                artifact_id=f"artifact-{run_id}",
                run_id=run_id,
                stage_run_id=stage_run_id,
                artifact_type="code_generation",
                payload_ref=f"payload-{run_id}",
                process={
                    "provider_call_ref": f"provider-call://{run_id}/{stage_run_id}/1",
                    "model_call_ref": f"model-call://{run_id}/{stage_run_id}/1",
                    "tool_confirmation_trace_ref": (
                        f"tool-confirmation://{run_id}/{stage_run_id}/1"
                    ),
                    "process_ref": f"process://{run_id}/{stage_run_id}/context",
                },
                metrics={},
                created_at=NOW + timedelta(minutes=3),
            )
        )
        session.add(
            ApprovalRequestModel(
                approval_id=f"approval-{run_id}",
                run_id=run_id,
                stage_run_id=stage_run_id,
                approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
                status=ApprovalStatus.APPROVED,
                payload_ref=f"approval-payload-{run_id}",
                graph_interrupt_ref=f"approval-interrupt-{run_id}",
                requested_at=NOW + timedelta(minutes=2),
                resolved_at=NOW + timedelta(minutes=3),
                created_at=NOW + timedelta(minutes=2),
                updated_at=NOW + timedelta(minutes=3),
            )
        )
        session.flush()
        session.add(
            ApprovalDecisionModel(
                decision_id=f"approval-decision-{run_id}",
                approval_id=f"approval-{run_id}",
                run_id=run_id,
                decision=ApprovalStatus.APPROVED,
                reason="Approved previous run plan.",
                decided_by_actor_id="user-1",
                decided_at=NOW + timedelta(minutes=3),
                created_at=NOW + timedelta(minutes=3),
            )
        )
        session.add(
            ToolConfirmationRequestModel(
                tool_confirmation_id=f"tool-confirmation-{run_id}",
                run_id=run_id,
                stage_run_id=stage_run_id,
                confirmation_object_ref=f"tool-call-{run_id}",
                tool_name="bash",
                command_preview="pytest -q",
                target_summary="backend tests",
                risk_level=ToolRiskLevel.HIGH_RISK,
                risk_categories=["unknown_command"],
                reason="Command requires user approval.",
                expected_side_effects=[],
                alternative_path_summary=None,
                planned_deny_followup_action=None,
                planned_deny_followup_summary=None,
                deny_followup_action=None,
                deny_followup_summary=None,
                user_decision=ToolConfirmationStatus.ALLOWED,
                status=ToolConfirmationStatus.ALLOWED,
                graph_interrupt_ref=f"tool-interrupt-{run_id}",
                audit_log_ref=f"audit-tool-{run_id}",
                process_ref=f"process://{run_id}/{stage_run_id}/tool-confirmation",
                requested_at=NOW + timedelta(minutes=2),
                responded_at=NOW + timedelta(minutes=3),
                created_at=NOW + timedelta(minutes=2),
                updated_at=NOW + timedelta(minutes=3),
            )
        )
        session.add(
            DeliveryRecordModel(
                delivery_record_id=f"delivery-record-{run_id}",
                run_id=run_id,
                stage_run_id=stage_run_id,
                delivery_channel_snapshot_ref=delivery_snapshot_ref,
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
                status="succeeded",
                branch_name="main",
                commit_sha="abc123",
                code_review_url=None,
                result_ref=f"delivery-result-{run_id}",
                process_ref=f"delivery-process://{run_id}",
                failure_reason=None,
                created_at=NOW + timedelta(minutes=4),
                completed_at=NOW + timedelta(minutes=4),
            )
        )
        session.commit()


def _seed_audit_fact(
    manager: DatabaseManager,
    *,
    audit_id: str,
    session_id: str,
    run_id: str,
) -> None:
    with manager.session(DatabaseRole.LOG) as session:
        session.add(
            AuditLogEntryModel(
                audit_id=audit_id,
                actor_type=AuditActorType.SYSTEM,
                actor_id="runtime",
                action="runtime.fact.recorded",
                target_type="run",
                target_id=run_id,
                session_id=session_id,
                run_id=run_id,
                stage_run_id=f"stage-{run_id}",
                approval_id=f"approval-{run_id}",
                tool_confirmation_id=f"tool-confirmation-{run_id}",
                delivery_record_id=f"delivery-record-{run_id}",
                request_id=f"req-{run_id}",
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata_ref=None,
                metadata_excerpt="Runtime fact remains audit history.",
                correlation_id=f"corr-{run_id}",
                trace_id=f"trace-{run_id}",
                span_id=f"span-{run_id}",
                audit_file_ref=None,
                audit_file_generation=None,
                audit_file_write_failed=False,
                created_at=NOW,
            )
        )
        session.commit()


def test_new_session_does_not_read_other_session_history_as_context(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    default_root = tmp_path / "default-project"
    default_root.mkdir()
    _seed_project(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        root_path=default_root,
        is_default=True,
    )
    _seed_session(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        session_id="session-existing",
        status=SessionStatus.COMPLETED,
        current_run_id="run-session-a-2",
    )
    _seed_runtime_truth(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        session_id="session-existing",
        run_id="run-session-a-1",
        run_status=RunStatus.COMPLETED,
    )
    _seed_runtime_truth(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        session_id="session-existing",
        run_id="run-session-a-2",
        run_status=RunStatus.COMPLETED,
        attempt_index=2,
    )

    with manager.session(DatabaseRole.CONTROL) as control_session:
        created = SessionService(
            control_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).create_session(
            project_id=DEFAULT_PROJECT_ID,
            trace_context=_trace("session-create"),
        )
        new_session_id = created.session_id
        assert created.status is SessionStatus.DRAFT
        assert created.current_run_id is None

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        new_session = control_session.get(SessionModel, new_session_id)
        assert new_session is not None
        assert new_session.status is SessionStatus.DRAFT
        assert new_session.current_run_id is None

        workspace = WorkspaceProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_session_workspace(new_session_id)
        dumped = workspace.model_dump(mode="json")
        assert dumped["runs"] == []
        assert dumped["narrative_feed"] == []
        assert dumped["current_run_id"] is None
        assert dumped["composer_state"] == {
            "mode": "draft",
            "is_input_enabled": True,
            "primary_action": "send",
            "secondary_actions": [],
            "bound_run_id": None,
        }
        assert (
            runtime_session.query(PipelineRunModel)
            .filter(PipelineRunModel.session_id == new_session_id)
            .count()
            == 0
        )
        serialized = str(dumped)
        for forbidden_ref in (
            "run-session-a-1",
            "artifact-run-session-a-1",
            "approval-run-session-a-1",
            "tool-confirmation-run-session-a-1",
            "provider-call://run-session-a-1",
            "process://run-session-a-1",
        ):
            assert forbidden_ref not in serialized

        historical_artifacts = (
            runtime_session.query(StageArtifactModel)
            .filter(StageArtifactModel.run_id == "run-session-a-1")
            .all()
        )
        historical_approval_decisions = (
            runtime_session.query(ApprovalDecisionModel)
            .filter(ApprovalDecisionModel.run_id == "run-session-a-1")
            .all()
        )

    resolver = ContextSourceResolver()
    same_session_rerun = resolver.resolve_context_references(
        session_id="session-existing",
        run_id="run-session-a-2",
        stage_run_id="stage-run-session-a-2",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=historical_artifacts,
        context_references=(),
        change_sets=(),
        clarifications=(),
        approval_decisions=historical_approval_decisions,
        allowed_context_run_ids=("run-session-a-1", "run-session-a-2"),
        built_at=NOW,
    )
    same_session_summary = " ".join(
        block.summary
        for block in (
            *same_session_rerun.working_observations,
            *same_session_rerun.recent_observations,
        )
    )
    assert "provider-call://run-session-a-1" in same_session_summary
    assert "tool-confirmation://run-session-a-1" in same_session_summary
    assert "Approved previous run plan." in same_session_summary

    new_session_context = resolver.resolve_context_references(
        session_id=new_session_id,
        run_id="run-new-session-draft",
        stage_run_id="stage-new-session-draft",
        stage_type=StageType.CODE_GENERATION,
        stage_artifacts=historical_artifacts,
        context_references=(),
        change_sets=(),
        clarifications=(),
        approval_decisions=historical_approval_decisions,
        allowed_context_run_ids=("run-new-session-draft",),
        built_at=NOW,
    )
    assert new_session_context.context_references == ()
    assert new_session_context.working_observations == ()
    assert new_session_context.reasoning_trace == ()
    assert new_session_context.recent_observations == ()


def test_session_delete_and_project_remove_hide_history_without_deleting_runtime_truth(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    default_root = tmp_path / "default-project"
    project_root = tmp_path / "loaded-project"
    default_root.mkdir()
    project_root.mkdir()
    _seed_project(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        root_path=default_root,
        is_default=True,
    )
    _seed_project(manager, project_id="project-loaded", root_path=project_root)
    _seed_session(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        session_id="session-delete",
        status=SessionStatus.COMPLETED,
        current_run_id="run-session-delete",
    )
    _seed_runtime_truth(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        session_id="session-delete",
        run_id="run-session-delete",
        run_status=RunStatus.COMPLETED,
    )
    _seed_audit_fact(
        manager,
        audit_id="audit-session-delete-runtime",
        session_id="session-delete",
        run_id="run-session-delete",
    )
    _seed_session(
        manager,
        project_id="project-loaded",
        session_id="session-project-visible",
        status=SessionStatus.COMPLETED,
        current_run_id="run-project-visible",
    )
    _seed_session(
        manager,
        project_id="project-loaded",
        session_id="session-project-hidden",
        is_visible=False,
        removed_at=NOW,
    )
    _seed_runtime_truth(
        manager,
        project_id="project-loaded",
        session_id="session-project-visible",
        run_id="run-project-visible",
        run_status=RunStatus.COMPLETED,
    )
    _seed_audit_fact(
        manager,
        audit_id="audit-project-visible-runtime",
        session_id="session-project-visible",
        run_id="run-project-visible",
    )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        session_delete = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).delete_session(
            session_id="session-delete",
            trace_context=_trace("session-delete", session_id="session-delete"),
        )
        listed = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).list_visible_sessions(
            project_id=DEFAULT_PROJECT_ID,
            trace_context=_trace("session-list"),
        )
        with pytest.raises(WorkspaceProjectionServiceError) as workspace_error:
            WorkspaceProjectionService(
                control_session,
                runtime_session,
                event_session,
            ).get_session_workspace("session-delete")
        saved_session = control_session.get(SessionModel, "session-delete")
        run = runtime_session.get(PipelineRunModel, "run-session-delete")
        runtime_snapshot = runtime_session.get(
            RuntimeLimitSnapshotModel,
            "runtime-limit-run-session-delete",
        )
        provider_policy = runtime_session.get(
            ProviderCallPolicySnapshotModel,
            "provider-policy-run-session-delete",
        )
        delivery_record = runtime_session.get(
            DeliveryRecordModel,
            "delivery-record-run-session-delete",
        )
        stage_artifact = runtime_session.get(
            StageArtifactModel,
            "artifact-run-session-delete",
        )
        approval_request = runtime_session.get(
            ApprovalRequestModel,
            "approval-run-session-delete",
        )
        approval_decision = runtime_session.get(
            ApprovalDecisionModel,
            "approval-decision-run-session-delete",
        )
        tool_confirmation = runtime_session.get(
            ToolConfirmationRequestModel,
            "tool-confirmation-run-session-delete",
        )

    assert session_delete.visibility_removed is True
    assert session_delete.blocked_by_active_run is False
    assert session_delete.message == SESSION_DELETE_SUCCESS_MESSAGE
    assert [session.session_id for session in listed] == []
    assert workspace_error.value.status_code == 404
    assert workspace_error.value.message == "Session workspace was not found."
    assert saved_session is not None
    assert saved_session.is_visible is False
    assert saved_session.visibility_removed_at == LATER.replace(tzinfo=None)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert runtime_snapshot is not None
    assert provider_policy is not None
    assert delivery_record is not None
    assert stage_artifact is not None
    assert approval_request is not None
    assert approval_decision is not None
    assert tool_confirmation is not None

    with manager.session(DatabaseRole.LOG) as log_session:
        assert (
            log_session.get(AuditLogEntryModel, "audit-session-delete-runtime")
            is not None
        )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        project_remove = ProjectService(
            control_session,
            settings=_settings(tmp_path),
            runtime_session=runtime_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).remove_project(
            project_id="project-loaded",
            trace_context=_trace("project-remove"),
        )
        removed_project = control_session.get(ProjectModel, "project-loaded")
        visible_session = control_session.get(SessionModel, "session-project-visible")
        already_hidden_session = control_session.get(
            SessionModel,
            "session-project-hidden",
        )
        visible_projects = ProjectService(
            control_session,
            settings=_settings(tmp_path),
            runtime_session=runtime_session,
            audit_service=RecordingAuditService(),
            now=lambda: LATER,
        ).list_projects(trace_context=_trace("project-list"))
        with pytest.raises(SessionServiceError) as list_removed_error:
            SessionService(
                control_session,
                runtime_session=runtime_session,
                audit_service=RecordingAuditService(),
                now=lambda: LATER,
            ).list_visible_sessions(
                project_id="project-loaded",
                trace_context=_trace("removed-project-sessions"),
            )
        project_run = runtime_session.get(PipelineRunModel, "run-project-visible")
        project_delivery_record = runtime_session.get(
            DeliveryRecordModel,
            "delivery-record-run-project-visible",
        )
        project_stage_artifact = runtime_session.get(
            StageArtifactModel,
            "artifact-run-project-visible",
        )
        project_approval_request = runtime_session.get(
            ApprovalRequestModel,
            "approval-run-project-visible",
        )
        project_approval_decision = runtime_session.get(
            ApprovalDecisionModel,
            "approval-decision-run-project-visible",
        )
        project_tool_confirmation = runtime_session.get(
            ToolConfirmationRequestModel,
            "tool-confirmation-run-project-visible",
        )
        project_runtime_rows = (
            runtime_session.query(PipelineRunModel)
            .filter(PipelineRunModel.project_id == "project-loaded")
            .count()
        )

    assert project_remove.visibility_removed is True
    assert project_remove.blocked_by_active_run is False
    assert project_remove.message == PROJECT_REMOVE_SUCCESS_MESSAGE
    assert removed_project is not None
    assert removed_project.is_visible is False
    assert removed_project.visibility_removed_at == LATER.replace(tzinfo=None)
    assert visible_session is not None
    assert visible_session.is_visible is False
    assert visible_session.visibility_removed_at == LATER.replace(tzinfo=None)
    assert already_hidden_session is not None
    assert already_hidden_session.is_visible is False
    assert already_hidden_session.visibility_removed_at == NOW.replace(tzinfo=None)
    assert [project.project_id for project in visible_projects] == [DEFAULT_PROJECT_ID]
    assert list_removed_error.value.status_code == 404
    assert project_run is not None
    assert project_run.status is RunStatus.COMPLETED
    assert project_delivery_record is not None
    assert project_stage_artifact is not None
    assert project_approval_request is not None
    assert project_approval_decision is not None
    assert project_tool_confirmation is not None
    assert project_runtime_rows == 1

    with manager.session(DatabaseRole.LOG) as log_session:
        assert (
            log_session.get(AuditLogEntryModel, "audit-project-visible-runtime")
            is not None
        )


def test_active_run_blocks_session_delete_and_project_remove(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    default_root = tmp_path / "default-project"
    active_project_root = tmp_path / "active-project"
    default_root.mkdir()
    active_project_root.mkdir()
    _seed_project(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        root_path=default_root,
        is_default=True,
    )
    _seed_project(
        manager,
        project_id="project-active",
        root_path=active_project_root,
    )
    _seed_session(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        session_id="session-active-delete",
        status=SessionStatus.RUNNING,
        current_run_id="run-active-delete",
    )
    _seed_runtime_truth(
        manager,
        project_id=DEFAULT_PROJECT_ID,
        session_id="session-active-delete",
        run_id="run-active-delete",
        run_status=RunStatus.RUNNING,
        include_history_facts=False,
    )
    _seed_session(
        manager,
        project_id="project-active",
        session_id="session-active-project",
        status=SessionStatus.RUNNING,
        current_run_id="run-active-project",
    )
    _seed_runtime_truth(
        manager,
        project_id="project-active",
        session_id="session-active-project",
        run_id="run-active-project",
        run_status=RunStatus.RUNNING,
        include_history_facts=False,
    )

    session_audit = RecordingAuditService()
    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        session_delete = SessionService(
            control_session,
            runtime_session=runtime_session,
            audit_service=session_audit,
            now=lambda: LATER,
        ).delete_session(
            session_id="session-active-delete",
            trace_context=_trace(
                "active-session-delete",
                session_id="session-active-delete",
                run_id="run-active-delete",
            ),
        )
        active_session = control_session.get(SessionModel, "session-active-delete")
        active_run = runtime_session.get(PipelineRunModel, "run-active-delete")

    assert session_delete.visibility_removed is False
    assert session_delete.blocked_by_active_run is True
    assert session_delete.blocking_run_id == "run-active-delete"
    assert session_delete.error_code == SESSION_DELETE_BLOCKED_ERROR_CODE
    assert session_delete.message == SESSION_DELETE_BLOCKED_MESSAGE
    assert active_session is not None
    assert active_session.is_visible is True
    assert active_session.status is SessionStatus.RUNNING
    assert active_session.current_run_id == "run-active-delete"
    assert active_run is not None
    assert active_run.status is RunStatus.RUNNING
    assert session_audit.records[-1]["result"] is AuditResult.BLOCKED

    project_audit = RecordingAuditService()
    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        project_remove = ProjectService(
            control_session,
            settings=_settings(tmp_path),
            runtime_session=runtime_session,
            audit_service=project_audit,
            now=lambda: LATER,
        ).remove_project(
            project_id="project-active",
            trace_context=_trace("active-project-remove"),
        )
        active_project = control_session.get(ProjectModel, "project-active")
        active_project_session = control_session.get(
            SessionModel,
            "session-active-project",
        )
        project_run = runtime_session.get(PipelineRunModel, "run-active-project")

    assert project_remove.visibility_removed is False
    assert project_remove.blocked_by_active_run is True
    assert project_remove.blocking_run_id == "run-active-project"
    assert project_remove.error_code == PROJECT_REMOVE_BLOCKED_ERROR_CODE
    assert project_remove.message == PROJECT_REMOVE_BLOCKED_MESSAGE
    assert active_project is not None
    assert active_project.is_visible is True
    assert active_project_session is not None
    assert active_project_session.is_visible is True
    assert active_project_session.status is SessionStatus.RUNNING
    assert active_project_session.current_run_id == "run-active-project"
    assert project_run is not None
    assert project_run.status is RunStatus.RUNNING
    assert project_audit.records[-1]["result"] is AuditResult.BLOCKED

    default_project_audit = RecordingAuditService()
    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
    ):
        service = ProjectService(
            control_session,
            settings=_settings(tmp_path),
            runtime_session=runtime_session,
            audit_service=default_project_audit,
            now=lambda: LATER,
        )
        with pytest.raises(ProjectServiceError) as default_error:
            service.remove_project(
                project_id=DEFAULT_PROJECT_ID,
                trace_context=_trace("default-project-remove"),
            )
        default_project = control_session.get(ProjectModel, DEFAULT_PROJECT_ID)

    assert default_error.value.status_code == 409
    assert default_error.value.message == DEFAULT_PROJECT_REMOVE_BLOCKED_MESSAGE
    assert default_project is not None
    assert default_project.is_visible is True
    assert default_project_audit.records[-1]["action"] == "project.remove.rejected"
