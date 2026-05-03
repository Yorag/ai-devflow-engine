from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, DeliveryChannelModel, ProjectModel
from backend.app.db.models.runtime import (
    DeliveryChannelSnapshotModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    ApprovalType,
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    StageType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.services.delivery_channels import (
    DEFAULT_DELIVERY_CHANNEL_ID,
    DeliveryChannelService,
)
from backend.app.services.delivery_snapshots import (
    DeliverySnapshotService,
    DeliverySnapshotServiceError,
)


NOW = datetime(2026, 5, 3, 10, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 3, 10, 5, 0, tzinfo=UTC)
SAFE_CREDENTIAL_REF = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"


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
        raise RuntimeError("required audit unavailable")


class FailingFailedAuditService(RecordingAuditService):
    def record_failed_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_failed_command", **kwargs})
        raise RuntimeError("failed audit unavailable")


class RecordingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FailingCommitSession:
    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.rollback_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def commit(self) -> None:
        raise RuntimeError("runtime commit unavailable")

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._wrapped.rollback()


class FailingFlushSession:
    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.rollback_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def flush(self) -> None:
        raise RuntimeError("runtime flush unavailable")

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._wrapped.rollback()


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-delivery-snapshot",
        trace_id="trace-delivery-snapshot",
        correlation_id="correlation-delivery-snapshot",
        span_id="span-delivery-snapshot",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
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
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    return manager


def seed_project_with_channel(
    manager: DatabaseManager,
    *,
    delivery_mode: DeliveryMode = DeliveryMode.DEMO_DELIVERY,
    scm_provider_type: ScmProviderType | None = None,
    repository_identifier: str | None = None,
    default_branch: str | None = None,
    code_review_request_type: CodeReviewRequestType | None = None,
    credential_ref: str | None = None,
    credential_status: CredentialStatus = CredentialStatus.READY,
    readiness_status: DeliveryReadinessStatus = DeliveryReadinessStatus.READY,
    readiness_message: str | None = None,
    last_validated_at: datetime | None = None,
) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        project = ProjectModel(
            project_id="project-default",
            name="Platform",
            root_path="C:/workspace/platform",
            default_delivery_channel_id=DEFAULT_DELIVERY_CHANNEL_ID,
            is_default=True,
            is_visible=True,
            visibility_removed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        channel = DeliveryChannelModel(
            delivery_channel_id=DEFAULT_DELIVERY_CHANNEL_ID,
            project_id=project.project_id,
            delivery_mode=delivery_mode,
            scm_provider_type=scm_provider_type,
            repository_identifier=repository_identifier,
            default_branch=default_branch,
            code_review_request_type=code_review_request_type,
            credential_ref=credential_ref,
            credential_status=credential_status,
            readiness_status=readiness_status,
            readiness_message=readiness_message,
            last_validated_at=last_validated_at,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(project)
        session.flush()
        session.add(channel)
        session.commit()


def seed_run(manager: DatabaseManager, *, project_id: str) -> None:
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
        session.commit()
        session.add(
            PipelineRunModel(
                run_id="run-1",
                session_id="session-1",
                project_id=project_id,
                attempt_index=1,
                status=RunStatus.WAITING_APPROVAL,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-1",
                graph_definition_ref="graph-definition-1",
                graph_thread_ref="thread-1",
                workspace_ref="workspace-1",
                runtime_limit_snapshot_ref="runtime-limits-1",
                provider_call_policy_snapshot_ref="provider-policy-1",
                delivery_channel_snapshot_ref=None,
                current_stage_run_id="stage-run-1",
                trace_id="trace-delivery-snapshot",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def build_service(
    manager: DatabaseManager,
    *,
    audit: RecordingAuditService | None = None,
    log_writer: RecordingRunLogWriter | None = None,
    runtime_session_wrapper: type[FailingCommitSession] | type[FailingFlushSession] | None = None,
) -> tuple[DeliverySnapshotService, RecordingAuditService, RecordingRunLogWriter]:
    resolved_audit = audit or RecordingAuditService()
    resolved_log_writer = log_writer or RecordingRunLogWriter()
    control_context = manager.session(DatabaseRole.CONTROL)
    runtime_context = manager.session(DatabaseRole.RUNTIME)
    control_session = control_context.__enter__()
    raw_runtime_session = runtime_context.__enter__()
    runtime_session = (
        runtime_session_wrapper(raw_runtime_session)
        if runtime_session_wrapper is not None
        else raw_runtime_session
    )
    service = DeliverySnapshotService(
        control_session=control_session,
        runtime_session=runtime_session,
        delivery_channel_service=DeliveryChannelService(control_session),
        audit_service=resolved_audit,
        log_writer=resolved_log_writer,
        now=lambda: NOW,
    )
    service._test_contexts = (control_context, runtime_context)
    return service, resolved_audit, resolved_log_writer


def test_prepare_demo_delivery_snapshot_freezes_current_channel_and_attaches_run(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
        readiness_message="demo_delivery is ready.",
        last_validated_at=None,
    )
    seed_run(manager, project_id="project-default")
    service, audit, log_writer = build_service(manager)

    snapshot = service.prepare_delivery_snapshot(
        run_id="run-1",
        project_id="project-default",
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        target_stage_type=StageType.DELIVERY_INTEGRATION,
        trace_context=build_trace(),
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        saved_run = session.get(PipelineRunModel, "run-1")
        saved_snapshot = session.get(
            DeliveryChannelSnapshotModel,
            snapshot.delivery_channel_snapshot_id,
        )

    assert saved_run is not None
    assert saved_snapshot is not None
    assert saved_run.delivery_channel_snapshot_ref == snapshot.delivery_channel_snapshot_id
    assert saved_snapshot.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert saved_snapshot.source_delivery_channel_id == DEFAULT_DELIVERY_CHANNEL_ID
    assert saved_snapshot.scm_provider_type is None
    assert saved_snapshot.repository_identifier is None
    assert saved_snapshot.default_branch is None
    assert saved_snapshot.code_review_request_type is None
    assert saved_snapshot.credential_ref is None
    assert saved_snapshot.credential_status is CredentialStatus.READY
    assert saved_snapshot.readiness_status is DeliveryReadinessStatus.READY
    assert saved_snapshot.readiness_message == "demo_delivery is ready."
    assert saved_snapshot.last_validated_at is None
    assert saved_snapshot.schema_version == "delivery-channel-snapshot-v1"
    assert audit.records[0]["action"] == "delivery_snapshot.prepare"
    assert audit.records[0]["target_id"] == "run-1"
    assert log_writer.records[0].message == "Delivery snapshot prepared."


def test_prepare_git_auto_delivery_snapshot_requires_ready_channel_without_mutating_run(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier="acme/app",
        default_branch="main",
        code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
        credential_ref=SAFE_CREDENTIAL_REF,
        credential_status=CredentialStatus.UNBOUND,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        readiness_message="DeliveryChannel readiness has not been validated.",
        last_validated_at=None,
    )
    seed_run(manager, project_id="project-default")
    service, audit, log_writer = build_service(manager)

    with pytest.raises(DeliverySnapshotServiceError) as exc_info:
        service.prepare_delivery_snapshot(
            run_id="run-1",
            project_id="project-default",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.DELIVERY_SNAPSHOT_NOT_READY
    assert exc_info.value.status_code == 409
    with manager.session(DatabaseRole.RUNTIME) as session:
        saved_run = session.get(PipelineRunModel, "run-1")
        assert saved_run is not None
        assert saved_run.delivery_channel_snapshot_ref is None
        assert session.query(DeliveryChannelSnapshotModel).count() == 0
    assert audit.records[0]["action"] == "delivery_snapshot.prepare.rejected"
    assert log_writer.records[0].message == "Delivery snapshot preparation rejected."


def test_prepare_delivery_snapshot_redacts_unsafe_credential_ref_in_rejection_evidence(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier="acme/app",
        default_branch="main",
        code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
        credential_ref="env:OTHER_SECRET",
        credential_status=CredentialStatus.INVALID,
        readiness_status=DeliveryReadinessStatus.INVALID,
        readiness_message="DeliveryChannel credential_ref is not allowed.",
        last_validated_at=None,
    )
    seed_run(manager, project_id="project-default")
    service, audit, log_writer = build_service(manager)

    with pytest.raises(DeliverySnapshotServiceError):
        service.prepare_delivery_snapshot(
            run_id="run-1",
            project_id="project-default",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )

    assert "env:OTHER_SECRET" not in str(audit.records)
    assert "env:OTHER_SECRET" not in str(log_writer.records[0].payload.summary)
    assert "env:OTHER_SECRET" not in (log_writer.records[0].payload.excerpt or "")


def test_prepare_git_auto_delivery_snapshot_copies_all_ready_fields_and_stays_frozen(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier="acme/app",
        default_branch="main",
        code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
        credential_ref=SAFE_CREDENTIAL_REF,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
        readiness_message="git_auto_delivery is ready.",
        last_validated_at=LATER,
    )
    seed_run(manager, project_id="project-default")
    service, _audit, _log_writer = build_service(manager)

    snapshot = service.prepare_delivery_snapshot(
        run_id="run-1",
        project_id="project-default",
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        target_stage_type=StageType.DELIVERY_INTEGRATION,
        trace_context=build_trace(),
    )
    with manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        assert channel is not None
        channel.repository_identifier = "changed/app"
        channel.default_branch = "develop"
        session.commit()
    reread = service.get_snapshot_for_run(run_id="run-1")

    assert snapshot.delivery_channel_snapshot_id == reread.delivery_channel_snapshot_id
    assert reread.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
    assert reread.scm_provider_type is ScmProviderType.GITHUB
    assert reread.repository_identifier == "acme/app"
    assert reread.default_branch == "main"
    assert reread.code_review_request_type is CodeReviewRequestType.PULL_REQUEST
    assert reread.credential_ref == SAFE_CREDENTIAL_REF
    assert reread.credential_status is CredentialStatus.READY
    assert reread.readiness_status is DeliveryReadinessStatus.READY
    assert reread.readiness_message == "git_auto_delivery is ready."
    assert reread.last_validated_at == LATER.replace(tzinfo=None)


def test_prepare_delivery_snapshot_is_idempotent_and_does_not_recopy_new_channel_values(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier="acme/app",
        default_branch="main",
        code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
        credential_ref=SAFE_CREDENTIAL_REF,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
        readiness_message="git_auto_delivery is ready.",
        last_validated_at=LATER,
    )
    seed_run(manager, project_id="project-default")
    service, _audit, _log_writer = build_service(manager)

    first = service.prepare_delivery_snapshot(
        run_id="run-1",
        project_id="project-default",
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        target_stage_type=StageType.DELIVERY_INTEGRATION,
        trace_context=build_trace(),
    )
    with manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        assert channel is not None
        channel.repository_identifier = "changed/app"
        session.commit()
    second = service.prepare_delivery_snapshot(
        run_id="run-1",
        project_id="project-default",
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        target_stage_type=StageType.DELIVERY_INTEGRATION,
        trace_context=build_trace(),
    )

    assert second.delivery_channel_snapshot_id == first.delivery_channel_snapshot_id
    assert second.repository_identifier == "acme/app"
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryChannelSnapshotModel).count() == 1


def test_prepare_delivery_snapshot_refreshes_stale_run_before_idempotency_check(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier="acme/app",
        default_branch="main",
        code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
        credential_ref=SAFE_CREDENTIAL_REF,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
        readiness_message="git_auto_delivery is ready.",
        last_validated_at=LATER,
    )
    seed_run(manager, project_id="project-default")
    stale_service, _stale_audit, _stale_log_writer = build_service(manager)
    stale_run = stale_service._runtime_session.get(PipelineRunModel, "run-1")
    assert stale_run is not None
    assert stale_run.delivery_channel_snapshot_ref is None

    fresh_service, _fresh_audit, _fresh_log_writer = build_service(manager)
    first = fresh_service.prepare_delivery_snapshot(
        run_id="run-1",
        project_id="project-default",
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        target_stage_type=StageType.DELIVERY_INTEGRATION,
        trace_context=build_trace(),
    )
    with manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        assert channel is not None
        channel.repository_identifier = "changed/app"
        session.commit()

    second = stale_service.prepare_delivery_snapshot(
        run_id="run-1",
        project_id="project-default",
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        target_stage_type=StageType.DELIVERY_INTEGRATION,
        trace_context=build_trace(),
    )

    assert second.delivery_channel_snapshot_id == first.delivery_channel_snapshot_id
    assert second.repository_identifier == "acme/app"
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryChannelSnapshotModel).count() == 1


def test_prepare_delivery_snapshot_refreshes_cached_channel_on_retry(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier="acme/app",
        default_branch="main",
        code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
        credential_ref=SAFE_CREDENTIAL_REF,
        credential_status=CredentialStatus.UNBOUND,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        readiness_message="DeliveryChannel readiness has not been validated.",
        last_validated_at=None,
    )
    seed_run(manager, project_id="project-default")
    service, _audit, _log_writer = build_service(manager)

    with pytest.raises(DeliverySnapshotServiceError):
        service.prepare_delivery_snapshot(
            run_id="run-1",
            project_id="project-default",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )
    with manager.session(DatabaseRole.CONTROL) as session:
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        assert channel is not None
        channel.credential_status = CredentialStatus.READY
        channel.readiness_status = DeliveryReadinessStatus.READY
        channel.readiness_message = "git_auto_delivery is ready."
        channel.last_validated_at = LATER
        session.commit()

    snapshot = service.prepare_delivery_snapshot(
        run_id="run-1",
        project_id="project-default",
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        target_stage_type=StageType.DELIVERY_INTEGRATION,
        trace_context=build_trace(),
    )

    assert snapshot.readiness_status is DeliveryReadinessStatus.READY
    assert snapshot.credential_status is CredentialStatus.READY
    assert snapshot.readiness_message == "git_auto_delivery is ready."
    assert snapshot.last_validated_at == LATER.replace(tzinfo=None)


def test_prepare_delivery_snapshot_rolls_back_without_success_log_when_required_audit_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
    )
    seed_run(manager, project_id="project-default")
    service, audit, log_writer = build_service(
        manager,
        audit=FailingRequiredAuditService(),
    )

    with pytest.raises(RuntimeError, match="required audit unavailable"):
        service.prepare_delivery_snapshot(
            run_id="run-1",
            project_id="project-default",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )

    with manager.session(DatabaseRole.RUNTIME) as session:
        saved_run = session.get(PipelineRunModel, "run-1")
        assert saved_run is not None
        assert saved_run.delivery_channel_snapshot_ref is None
        assert session.query(DeliveryChannelSnapshotModel).count() == 0
    assert [record.message for record in log_writer.records] == [
        "Delivery snapshot preparation failed.",
    ]
    assert [record["action"] for record in audit.records] == [
        "delivery_snapshot.prepare",
        "delivery_snapshot.prepare.failed",
    ]


def test_prepare_delivery_snapshot_rolls_back_without_success_log_when_runtime_commit_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
    )
    seed_run(manager, project_id="project-default")
    service, audit, log_writer = build_service(
        manager,
        runtime_session_wrapper=FailingCommitSession,
    )

    with pytest.raises(RuntimeError, match="runtime commit unavailable"):
        service.prepare_delivery_snapshot(
            run_id="run-1",
            project_id="project-default",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )

    with manager.session(DatabaseRole.RUNTIME) as session:
        saved_run = session.get(PipelineRunModel, "run-1")
        assert saved_run is not None
        assert saved_run.delivery_channel_snapshot_ref is None
        assert session.query(DeliveryChannelSnapshotModel).count() == 0
    assert service._runtime_session.rollback_calls >= 1
    assert [record.message for record in log_writer.records] == [
        "Delivery snapshot preparation failed.",
    ]
    assert [record["action"] for record in audit.records] == [
        "delivery_snapshot.prepare",
        "delivery_snapshot.prepare.failed",
    ]


def test_prepare_delivery_snapshot_rolls_back_and_records_failure_when_flush_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
    )
    seed_run(manager, project_id="project-default")
    service, audit, log_writer = build_service(
        manager,
        runtime_session_wrapper=FailingFlushSession,
    )

    with pytest.raises(RuntimeError, match="runtime flush unavailable"):
        service.prepare_delivery_snapshot(
            run_id="run-1",
            project_id="project-default",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )

    with manager.session(DatabaseRole.RUNTIME) as session:
        saved_run = session.get(PipelineRunModel, "run-1")
        assert saved_run is not None
        assert saved_run.delivery_channel_snapshot_ref is None
        assert session.query(DeliveryChannelSnapshotModel).count() == 0
    assert service._runtime_session.rollback_calls >= 1
    assert [record.message for record in log_writer.records] == [
        "Delivery snapshot preparation failed.",
    ]
    assert [record["action"] for record in audit.records] == [
        "delivery_snapshot.prepare.failed",
    ]


def test_prepare_delivery_snapshot_failure_log_is_attempted_when_failed_audit_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(
        manager,
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
    )
    seed_run(manager, project_id="project-default")
    service, audit, log_writer = build_service(
        manager,
        audit=FailingFailedAuditService(),
        runtime_session_wrapper=FailingCommitSession,
    )

    with pytest.raises(RuntimeError, match="runtime commit unavailable"):
        service.prepare_delivery_snapshot(
            run_id="run-1",
            project_id="project-default",
            approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )

    assert [record.message for record in log_writer.records] == [
        "Delivery snapshot preparation failed.",
    ]
    assert [record["action"] for record in audit.records] == [
        "delivery_snapshot.prepare",
        "delivery_snapshot.prepare.failed",
    ]


def test_prepare_delivery_snapshot_rejects_wrong_gate_context_before_mutation(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(manager, delivery_mode=DeliveryMode.DEMO_DELIVERY)
    seed_run(manager, project_id="project-default")
    service, audit, _log_writer = build_service(manager)

    with pytest.raises(DeliverySnapshotServiceError) as exc_info:
        service.prepare_delivery_snapshot(
            run_id="run-1",
            project_id="project-default",
            approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
            target_stage_type=StageType.DELIVERY_INTEGRATION,
            trace_context=build_trace(),
        )

    assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
    assert "code_review_approval" in exc_info.value.message
    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.query(DeliveryChannelSnapshotModel).count() == 0
        run = session.get(PipelineRunModel, "run-1")
        assert run is not None
        assert run.delivery_channel_snapshot_ref is None
    assert audit.records[0]["action"] == "delivery_snapshot.prepare.rejected"


def test_assert_snapshot_ready_for_delivery_reports_missing_or_not_ready_snapshot(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_project_with_channel(manager, delivery_mode=DeliveryMode.DEMO_DELIVERY)
    seed_run(manager, project_id="project-default")
    service, _audit, _log_writer = build_service(manager)

    with pytest.raises(DeliverySnapshotServiceError) as missing:
        service.assert_snapshot_ready_for_delivery(run_id="run-1")
    assert missing.value.error_code is ErrorCode.DELIVERY_SNAPSHOT_MISSING

    snapshot = service.prepare_delivery_snapshot(
        run_id="run-1",
        project_id="project-default",
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        target_stage_type=StageType.DELIVERY_INTEGRATION,
        trace_context=build_trace(),
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        saved = session.get(
            DeliveryChannelSnapshotModel,
            snapshot.delivery_channel_snapshot_id,
        )
        assert saved is not None
        saved.readiness_status = DeliveryReadinessStatus.INVALID
        session.commit()

    with pytest.raises(DeliverySnapshotServiceError) as not_ready:
        service.assert_snapshot_ready_for_delivery(run_id="run-1")
    assert not_ready.value.error_code is ErrorCode.DELIVERY_SNAPSHOT_NOT_READY
