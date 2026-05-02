from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, DeliveryChannelModel, ProjectModel
from backend.app.db.models.runtime import DeliveryChannelSnapshotModel, RuntimeBase
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ScmProviderType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import JsonlWriteResult
from backend.app.schemas.observability import AuditActorType, AuditResult, LogCategory
from backend.app.services.delivery_channels import DEFAULT_DELIVERY_CHANNEL_ID


NOW = datetime(2026, 5, 2, 15, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 2, 15, 10, 0, tzinfo=UTC)
SAFE_CREDENTIAL_REF = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
RAW_CREDENTIAL_REF = "raw-secret-value"
SECRET_VALUE = "super-secret-token"
WRAPPED_SECRET_VALUE = "  super-secret-token  "
EMPTY_CREDENTIAL_VALUE = " \t "
MISSING_ENV_CREDENTIAL_MESSAGE = (
    "DeliveryChannel credential_ref does not resolve to an available credential."
)
EMPTY_ENV_CREDENTIAL_MESSAGE = (
    "DeliveryChannel credential_ref resolves to an empty credential."
)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append(
            {"method": "record_rejected_command", "result": AuditResult.REJECTED, **kwargs}
        )
        return object()


class FailingAuditService:
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")

    def record_rejected_command(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


class RecordingLogWriter:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def write(self, record: Any) -> JsonlWriteResult:
        self.records.append(record)
        return JsonlWriteResult(
            log_id=record.log_id or "log-delivery-readiness",
            log_file_ref="logs/app.jsonl",
            line_offset=0,
            line_number=1,
            log_file_generation="app",
            created_at=record.created_at or LATER,
        )


class FailingLogWriter:
    def write(self, record: Any) -> JsonlWriteResult:
        raise OSError("log path unavailable")


class FailingCommitSession:
    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def commit(self) -> None:
        raise RuntimeError("control commit unavailable")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-delivery-readiness",
        trace_id="trace-delivery-readiness",
        correlation_id="correlation-delivery-readiness",
        span_id="span-delivery-readiness",
        parent_span_id=None,
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
    session,
    *,
    delivery_mode: DeliveryMode = DeliveryMode.DEMO_DELIVERY,
    scm_provider_type: ScmProviderType | None = None,
    repository_identifier: str | None = None,
    default_branch: str | None = None,
    code_review_request_type: CodeReviewRequestType | None = None,
    credential_ref: str | None = None,
    credential_status: CredentialStatus = CredentialStatus.UNBOUND,
    readiness_status: DeliveryReadinessStatus = DeliveryReadinessStatus.UNCONFIGURED,
    readiness_message: str | None = "DeliveryChannel readiness has not been validated.",
    last_validated_at: datetime | None = None,
) -> ProjectModel:
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
    return project


def seed_git_channel(session, **overrides: Any) -> ProjectModel:
    values: dict[str, Any] = {
        "delivery_mode": DeliveryMode.GIT_AUTO_DELIVERY,
        "scm_provider_type": ScmProviderType.GITHUB,
        "repository_identifier": "acme/app",
        "default_branch": "main",
        "code_review_request_type": CodeReviewRequestType.PULL_REQUEST,
        "credential_ref": SAFE_CREDENTIAL_REF,
        "credential_status": CredentialStatus.UNBOUND,
        "readiness_status": DeliveryReadinessStatus.UNCONFIGURED,
        "readiness_message": "DeliveryChannel readiness has not been validated.",
    }
    values.update(overrides)
    return seed_project_with_channel(session, **values)


def action_records(audit: RecordingAuditService, action: str) -> list[dict[str, Any]]:
    return [record for record in audit.records if record["action"] == action]


def assert_success_observability(
    *,
    audit: RecordingAuditService,
    log_writer: RecordingLogWriter,
    readiness_status: DeliveryReadinessStatus,
    credential_status: CredentialStatus,
    readiness_message: str,
    validated_fields: tuple[str, ...],
    credential_ref_text: str | None = None,
) -> None:
    records = action_records(audit, "delivery_channel.validate")
    assert len(records) == 1
    record = records[0]
    assert record["method"] == "record_command_result"
    assert record["actor_type"] is AuditActorType.USER
    assert record["actor_id"] == "api-user"
    assert record["target_type"] == "delivery_channel"
    assert record["target_id"] == DEFAULT_DELIVERY_CHANNEL_ID
    assert record["result"] is AuditResult.SUCCEEDED
    assert record["trace_context"].request_id == "request-delivery-readiness"
    metadata = record["metadata"]
    assert metadata["project_id"] == "project-default"
    assert metadata["delivery_channel_id"] == DEFAULT_DELIVERY_CHANNEL_ID
    assert metadata["readiness_status"] == readiness_status.value
    assert metadata["credential_status"] == credential_status.value
    assert metadata["readiness_message"] == readiness_message
    assert metadata["validated_fields"] == list(validated_fields)
    assert metadata["validated_at"] == LATER.isoformat()
    if credential_ref_text is not None:
        assert credential_ref_text in str(metadata)
    assert RAW_CREDENTIAL_REF not in str(metadata)

    assert len(log_writer.records) == 1
    log_record = log_writer.records[0]
    assert log_record.source == "services.delivery_channels"
    assert log_record.category is LogCategory.DELIVERY
    assert log_record.message == "DeliveryChannel readiness validation result computed."
    assert log_record.trace_context.request_id == "request-delivery-readiness"
    assert log_record.trace_context.trace_id == "trace-delivery-readiness"
    assert log_record.payload.summary["payload_type"] == "delivery_channel_validation"
    assert log_record.payload.redaction_status.value == "not_required"
    assert readiness_status.value in log_record.payload.excerpt
    assert credential_status.value in log_record.payload.excerpt
    assert RAW_CREDENTIAL_REF not in str(log_record.payload.summary)
    assert RAW_CREDENTIAL_REF not in (log_record.payload.excerpt or "")


def test_compute_readiness_returns_ready_for_demo_delivery(tmp_path: Path) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        seed_project_with_channel(
            session,
            credential_status=CredentialStatus.READY,
            readiness_status=DeliveryReadinessStatus.READY,
            readiness_message=None,
        )
        channel = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)
        assert channel is not None
        result = DeliveryChannelService(session).compute_readiness(channel)

    assert result.readiness_status is DeliveryReadinessStatus.READY
    assert result.credential_status is CredentialStatus.READY
    assert result.readiness_message == "demo_delivery is ready."
    assert result.validated_fields == ("delivery_mode",)


def test_validate_project_channel_persists_demo_ready_and_records_log_and_audit(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(
            session,
            credential_status=CredentialStatus.UNBOUND,
            readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        )
        result = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: SECRET_VALUE,
        ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert result.readiness_status is DeliveryReadinessStatus.READY
    assert result.credential_status is CredentialStatus.READY
    assert result.readiness_message == "demo_delivery is ready."
    assert result.validated_fields == ("delivery_mode",)
    assert result.validated_at == LATER
    assert saved is not None
    assert saved.readiness_status is DeliveryReadinessStatus.READY
    assert saved.credential_status is CredentialStatus.READY
    assert saved.readiness_message == "demo_delivery is ready."
    assert saved.last_validated_at == LATER.replace(tzinfo=None)
    assert saved.updated_at == LATER.replace(tzinfo=None)
    assert_success_observability(
        audit=audit,
        log_writer=log_writer,
        readiness_status=DeliveryReadinessStatus.READY,
        credential_status=CredentialStatus.READY,
        readiness_message="demo_delivery is ready.",
        validated_fields=("delivery_mode",),
    )


def test_validate_git_auto_delivery_reports_missing_fields_without_ready_status(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(
            session,
            scm_provider_type=None,
            repository_identifier=" ",
            default_branch=None,
        )
        result = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: SECRET_VALUE,
        ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    expected_fields = (
        "scm_provider_type",
        "repository_identifier",
        "default_branch",
        "code_review_request_type",
        "credential_ref",
    )
    assert result.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert result.credential_status is CredentialStatus.UNBOUND
    assert result.readiness_message == (
        "git_auto_delivery requires default_branch, repository_identifier, "
        "scm_provider_type"
    )
    assert result.validated_fields == expected_fields
    assert saved is not None
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_message == result.readiness_message
    assert saved.last_validated_at == LATER.replace(tzinfo=None)
    assert_success_observability(
        audit=audit,
        log_writer=log_writer,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        credential_status=CredentialStatus.UNBOUND,
        readiness_message=result.readiness_message,
        validated_fields=expected_fields,
        credential_ref_text=SAFE_CREDENTIAL_REF,
    )


def test_validate_git_auto_delivery_reports_unbound_missing_credential_ref(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=" ")
        result = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
        ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert result.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert result.credential_status is CredentialStatus.UNBOUND
    assert result.readiness_message == "git_auto_delivery requires credential_ref"
    assert saved is not None
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_message == "git_auto_delivery requires credential_ref"


def test_validate_git_auto_delivery_reports_unbound_unset_env_credential(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        service = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: None,
        )
        assert service.resolve_credential_status(SAFE_CREDENTIAL_REF) is (
            CredentialStatus.UNBOUND
        )
        result = service.validate_project_channel(
            project.project_id,
            trace_context=build_trace(),
        )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert result.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert result.credential_status is CredentialStatus.UNBOUND
    assert result.readiness_message == MISSING_ENV_CREDENTIAL_MESSAGE
    assert saved is not None
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_message == MISSING_ENV_CREDENTIAL_MESSAGE
    assert_success_observability(
        audit=audit,
        log_writer=log_writer,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        credential_status=CredentialStatus.UNBOUND,
        readiness_message=MISSING_ENV_CREDENTIAL_MESSAGE,
        validated_fields=(
            "scm_provider_type",
            "repository_identifier",
            "default_branch",
            "code_review_request_type",
            "credential_ref",
        ),
        credential_ref_text=SAFE_CREDENTIAL_REF,
    )


def test_validate_git_auto_delivery_reports_invalid_empty_env_credential(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        service = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: EMPTY_CREDENTIAL_VALUE,
        )
        assert service.resolve_credential_status(SAFE_CREDENTIAL_REF) is (
            CredentialStatus.INVALID
        )
        result = service.validate_project_channel(
            project.project_id,
            trace_context=build_trace(),
        )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert result.readiness_status is DeliveryReadinessStatus.INVALID
    assert result.credential_status is CredentialStatus.INVALID
    assert result.readiness_message == EMPTY_ENV_CREDENTIAL_MESSAGE
    assert saved is not None
    assert saved.readiness_status is DeliveryReadinessStatus.INVALID
    assert saved.credential_status is CredentialStatus.INVALID
    assert saved.readiness_message == EMPTY_ENV_CREDENTIAL_MESSAGE
    assert SECRET_VALUE not in str(audit.records)
    assert SECRET_VALUE not in str(log_writer.records[0].payload.summary)


def test_validate_git_auto_delivery_reports_invalid_disallowed_credential_ref(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=RAW_CREDENTIAL_REF)
        result = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: SECRET_VALUE,
        ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert result.readiness_status is DeliveryReadinessStatus.INVALID
    assert result.credential_status is CredentialStatus.INVALID
    assert result.readiness_message == (
        "DeliveryChannel credential_ref must use an allowed env: credential reference."
    )
    assert saved is not None
    assert saved.readiness_status is DeliveryReadinessStatus.INVALID
    assert saved.credential_status is CredentialStatus.INVALID
    assert saved.readiness_message == result.readiness_message
    records = action_records(audit, "delivery_channel.validate")
    assert len(records) == 1
    assert records[0]["metadata"]["credential_ref"] == "[blocked:credential_ref]"
    assert RAW_CREDENTIAL_REF not in str(records[0]["metadata"])
    assert RAW_CREDENTIAL_REF not in str(log_writer.records[0].payload.summary)
    assert RAW_CREDENTIAL_REF not in log_writer.records[0].payload.excerpt


def test_validate_git_auto_delivery_reports_invalid_spaced_env_credential_ref(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()
    spaced_ref = f" {SAFE_CREDENTIAL_REF} "

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=spaced_ref)
        service = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: SECRET_VALUE,
        )
        assert service.resolve_credential_status(spaced_ref) is CredentialStatus.INVALID
        result = service.validate_project_channel(
            project.project_id,
            trace_context=build_trace(),
        )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert result.readiness_status is DeliveryReadinessStatus.INVALID
    assert result.credential_status is CredentialStatus.INVALID
    assert result.readiness_message == (
        "DeliveryChannel credential_ref must use an allowed env: credential reference."
    )
    assert saved is not None
    assert saved.readiness_status is DeliveryReadinessStatus.INVALID
    assert saved.credential_status is CredentialStatus.INVALID
    assert action_records(audit, "delivery_channel.validate")
    assert SECRET_VALUE not in str(audit.records)
    assert SECRET_VALUE not in log_writer.records[0].payload.excerpt


def test_validate_git_auto_delivery_marks_whitespace_wrapped_env_credential_ready_without_leak(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        result = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: WRAPPED_SECRET_VALUE,
        ).validate_project_channel(project.project_id, trace_context=build_trace())

    assert result.readiness_status is DeliveryReadinessStatus.READY
    assert result.credential_status is CredentialStatus.READY
    assert result.readiness_message == "git_auto_delivery is ready."
    assert SECRET_VALUE not in str(audit.records)
    assert SECRET_VALUE not in str(log_writer.records[0].payload.summary)
    assert SECRET_VALUE not in log_writer.records[0].payload.excerpt


def test_validate_git_auto_delivery_marks_existing_env_credential_ready(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        service = DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: (
                SECRET_VALUE if name == "AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN" else None
            ),
        )
        assert service.resolve_credential_status(None) is CredentialStatus.UNBOUND
        assert service.resolve_credential_status(" ") is CredentialStatus.UNBOUND
        assert service.resolve_credential_status(SAFE_CREDENTIAL_REF) is (
            CredentialStatus.READY
        )
        assert service.resolve_credential_status(RAW_CREDENTIAL_REF) is (
            CredentialStatus.INVALID
        )
        result = service.validate_project_channel(
            project.project_id,
            trace_context=build_trace(),
        )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert result.readiness_status is DeliveryReadinessStatus.READY
    assert result.credential_status is CredentialStatus.READY
    assert result.readiness_message == "git_auto_delivery is ready."
    assert saved is not None
    assert saved.readiness_status is DeliveryReadinessStatus.READY
    assert saved.credential_status is CredentialStatus.READY
    assert saved.readiness_message == "git_auto_delivery is ready."
    assert SECRET_VALUE not in str(audit.records)
    assert SECRET_VALUE not in str(log_writer.records[0].payload.summary)
    assert SECRET_VALUE not in log_writer.records[0].payload.excerpt


def test_validate_project_channel_does_not_mutate_runtime_delivery_snapshot(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        runtime_session.add(
            DeliveryChannelSnapshotModel(
                delivery_channel_snapshot_id="delivery-snapshot-1",
                run_id="run-1",
                source_delivery_channel_id=DEFAULT_DELIVERY_CHANNEL_ID,
                delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
                scm_provider_type=ScmProviderType.GITHUB,
                repository_identifier="old/app",
                default_branch="old-main",
                code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
                credential_ref="env:AI_DEVFLOW_CREDENTIAL_OLD",
                credential_status=CredentialStatus.UNBOUND,
                readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
                readiness_message="snapshot stays frozen",
                last_validated_at=None,
                schema_version="delivery-channel-snapshot-v1",
                created_at=NOW,
            )
        )
        runtime_session.commit()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        DeliveryChannelService(
            session,
            audit_service=audit,
            log_writer=log_writer,
            now=lambda: LATER,
            credential_resolver=lambda name: SECRET_VALUE,
        ).validate_project_channel(project.project_id, trace_context=build_trace())

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        snapshot = runtime_session.get(
            DeliveryChannelSnapshotModel,
            "delivery-snapshot-1",
        )

    assert snapshot is not None
    assert snapshot.credential_status is CredentialStatus.UNBOUND
    assert snapshot.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert snapshot.readiness_message == "snapshot stays frozen"
    assert snapshot.last_validated_at is None
    assert snapshot.repository_identifier == "old/app"


def test_validate_project_channel_resolver_failure_audits_failed_and_rolls_back(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    def failing_resolver(name: str) -> str | None:
        raise RuntimeError("credential resolver unavailable")

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        with pytest.raises(RuntimeError, match="credential resolver unavailable"):
            DeliveryChannelService(
                session,
                audit_service=audit,
                log_writer=log_writer,
                now=lambda: LATER,
                credential_resolver=failing_resolver,
            ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert saved is not None
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.readiness_message == "DeliveryChannel readiness has not been validated."
    assert saved.last_validated_at is None
    assert saved.updated_at == NOW.replace(tzinfo=None)
    failed_records = action_records(audit, "delivery_channel.validate.failed")
    assert len(failed_records) == 1
    assert failed_records[0]["result"] is AuditResult.FAILED
    assert failed_records[0]["reason"] == "credential resolver unavailable"
    assert failed_records[0]["metadata"]["error_type"] == "RuntimeError"
    assert failed_records[0]["metadata"]["credential_ref"] == SAFE_CREDENTIAL_REF
    assert log_writer.records == []


def test_validate_project_channel_missing_project_returns_not_found_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import (
        DeliveryChannelService,
        DeliveryChannelServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        with pytest.raises(DeliveryChannelServiceError) as error:
            DeliveryChannelService(
                session,
                audit_service=audit,
                log_writer=log_writer,
                now=lambda: LATER,
            ).validate_project_channel(
                "project-missing",
                trace_context=build_trace(),
            )

    assert error.value.error_code is ErrorCode.NOT_FOUND
    assert error.value.status_code == 404
    assert error.value.message == "Project was not found."
    records = action_records(audit, "delivery_channel.validate.rejected")
    assert len(records) == 1
    assert records[0]["target_id"] == "project:project-missing"
    assert records[0]["reason"] == "Project was not found."
    assert records[0]["metadata"]["project_id"] == "project-missing"
    assert records[0]["trace_context"].request_id == "request-delivery-readiness"
    assert log_writer.records == []


def test_validate_project_channel_rolls_back_when_audit_fails(tmp_path: Path) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            DeliveryChannelService(
                session,
                audit_service=FailingAuditService(),
                log_writer=log_writer,
                now=lambda: LATER,
                credential_resolver=lambda name: SECRET_VALUE,
            ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert saved is not None
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.readiness_message == "DeliveryChannel readiness has not been validated."
    assert saved.last_validated_at is None
    assert saved.updated_at == NOW.replace(tzinfo=None)
    assert len(log_writer.records) == 1
    assert log_writer.records[0].message == (
        "DeliveryChannel readiness validation result computed."
    )
    assert log_writer.records[0].message != "DeliveryChannel readiness validated."


def test_validate_project_channel_rolls_back_when_log_write_fails_and_audits_failed_result(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        with pytest.raises(OSError, match="log path unavailable"):
            DeliveryChannelService(
                session,
                audit_service=audit,
                log_writer=FailingLogWriter(),
                now=lambda: LATER,
                credential_resolver=lambda name: SECRET_VALUE,
            ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert saved is not None
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.readiness_message == "DeliveryChannel readiness has not been validated."
    assert saved.last_validated_at is None
    assert saved.updated_at == NOW.replace(tzinfo=None)
    failed_records = action_records(audit, "delivery_channel.validate.failed")
    assert len(failed_records) == 1
    assert failed_records[0]["method"] == "record_command_result"
    assert failed_records[0]["result"] is AuditResult.FAILED
    assert failed_records[0]["target_id"] == DEFAULT_DELIVERY_CHANNEL_ID
    assert failed_records[0]["reason"] == "log path unavailable"
    assert failed_records[0]["metadata"]["error_type"] == "OSError"
    assert failed_records[0]["metadata"]["readiness_status"] == "ready"
    assert SECRET_VALUE not in str(failed_records[0]["metadata"])


def test_validate_project_channel_control_commit_failure_audits_failed_and_rolls_back(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        failing_session = FailingCommitSession(session)
        with pytest.raises(RuntimeError, match="control commit unavailable"):
            DeliveryChannelService(
                failing_session,
                audit_service=audit,
                log_writer=log_writer,
                now=lambda: LATER,
                credential_resolver=lambda name: SECRET_VALUE,
            ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert saved is not None
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.readiness_message == "DeliveryChannel readiness has not been validated."
    assert saved.last_validated_at is None
    assert saved.updated_at == NOW.replace(tzinfo=None)
    assert len(action_records(audit, "delivery_channel.validate")) == 1
    failed_records = action_records(audit, "delivery_channel.validate.failed")
    assert len(failed_records) == 1
    assert failed_records[0]["result"] is AuditResult.FAILED
    assert failed_records[0]["reason"] == "control commit unavailable"
    assert failed_records[0]["metadata"]["error_type"] == "RuntimeError"
    assert failed_records[0]["metadata"]["readiness_status"] == "ready"
    assert SECRET_VALUE not in str(failed_records[0]["metadata"])


def test_validate_project_channel_rolls_back_and_propagates_audit_failure_after_log_failure(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        with pytest.raises(RuntimeError, match="audit ledger unavailable") as error:
            DeliveryChannelService(
                session,
                audit_service=FailingAuditService(),
                log_writer=FailingLogWriter(),
                now=lambda: LATER,
                credential_resolver=lambda name: SECRET_VALUE,
            ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert isinstance(error.value.__cause__, OSError)
    assert saved is not None
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.readiness_message == "DeliveryChannel readiness has not been validated."
    assert saved.last_validated_at is None
    assert saved.updated_at == NOW.replace(tzinfo=None)


def test_validate_project_channel_requires_audit_and_log_writer_before_persisting(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        with pytest.raises(RuntimeError, match="audit_service is required"):
            DeliveryChannelService(
                session,
                log_writer=RecordingLogWriter(),
                now=lambda: LATER,
                credential_resolver=lambda name: SECRET_VALUE,
            ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved_after_audit_failure = session.get(
            DeliveryChannelModel,
            DEFAULT_DELIVERY_CHANNEL_ID,
        )

    assert saved_after_audit_failure is not None
    assert saved_after_audit_failure.credential_status is CredentialStatus.UNBOUND
    assert saved_after_audit_failure.last_validated_at is None

    manager = build_manager(tmp_path / "missing-log-writer")
    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_git_channel(session, credential_ref=SAFE_CREDENTIAL_REF)
        with pytest.raises(RuntimeError, match="log_writer is required"):
            DeliveryChannelService(
                session,
                audit_service=RecordingAuditService(),
                now=lambda: LATER,
                credential_resolver=lambda name: SECRET_VALUE,
            ).validate_project_channel(project.project_id, trace_context=build_trace())
        saved_after_log_failure = session.get(
            DeliveryChannelModel,
            DEFAULT_DELIVERY_CHANNEL_ID,
        )

    assert saved_after_log_failure is not None
    assert saved_after_log_failure.credential_status is CredentialStatus.UNBOUND
    assert saved_after_log_failure.last_validated_at is None
