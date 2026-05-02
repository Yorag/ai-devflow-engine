from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, DeliveryChannelModel, ProjectModel
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ScmProviderType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.delivery_channel import ProjectDeliveryChannelUpdateRequest
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.services.delivery_channels import DEFAULT_DELIVERY_CHANNEL_ID


NOW = datetime(2026, 5, 2, 14, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 2, 14, 15, 0, tzinfo=UTC)


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


class FailingAuditService:
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")

    def record_rejected_command(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-delivery-channel",
        trace_id="trace-delivery-channel",
        correlation_id="correlation-delivery-channel",
        span_id="span-delivery-channel",
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
    return manager


def seed_project_with_channel(
    session,
    *,
    project_id: str = "project-default",
    credential_ref: str | None = None,
) -> ProjectModel:
    project = ProjectModel(
        project_id=project_id,
        name="Platform",
        root_path="C:/workspace/platform",
        default_delivery_channel_id=DEFAULT_DELIVERY_CHANNEL_ID,
        is_default=project_id == "project-default",
        is_visible=True,
        visibility_removed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    channel = DeliveryChannelModel(
        delivery_channel_id=DEFAULT_DELIVERY_CHANNEL_ID,
        project_id=project_id,
        delivery_mode=DeliveryMode.DEMO_DELIVERY,
        scm_provider_type=None,
        repository_identifier=None,
        default_branch=None,
        code_review_request_type=None,
        credential_ref=credential_ref,
        credential_status=CredentialStatus.READY,
        readiness_status=DeliveryReadinessStatus.READY,
        readiness_message=None,
        last_validated_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(project)
    session.flush()
    session.add(channel)
    session.commit()
    return project


def git_request(
    *,
    credential_ref: str | None = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
    repository_identifier: str | None = "acme/app",
    default_branch: str | None = "main",
    code_review_request_type: CodeReviewRequestType | None = (
        CodeReviewRequestType.PULL_REQUEST
    ),
) -> ProjectDeliveryChannelUpdateRequest:
    return ProjectDeliveryChannelUpdateRequest(
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier=repository_identifier,
        default_branch=default_branch,
        code_review_request_type=code_review_request_type,
        credential_ref=credential_ref,
    )


def action_records(audit: RecordingAuditService, action: str) -> list[dict[str, Any]]:
    return [record for record in audit.records if record["action"] == action]


def test_get_project_channel_returns_existing_default_without_creating_second_channel(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        channel = DeliveryChannelService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).get_project_channel(project.project_id, trace_context=build_trace())
        channel_count = session.query(DeliveryChannelModel).count()

    assert channel.delivery_channel_id == DEFAULT_DELIVERY_CHANNEL_ID
    assert channel.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert channel_count == 1
    assert audit.records == []


def test_update_project_channel_saves_git_auto_delivery_and_audits_ref_change(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        updated = DeliveryChannelService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).update_project_channel(
            project.project_id,
            git_request(),
            trace_context=build_trace(),
        )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert saved is not None
    assert updated.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
    assert saved.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
    assert saved.scm_provider_type is ScmProviderType.GITHUB
    assert saved.repository_identifier == "acme/app"
    assert saved.default_branch == "main"
    assert saved.code_review_request_type is CodeReviewRequestType.PULL_REQUEST
    assert saved.credential_ref == "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
    assert saved.credential_status is CredentialStatus.UNBOUND
    assert saved.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert saved.readiness_message == "DeliveryChannel readiness has not been validated."
    assert saved.last_validated_at is None
    assert saved.updated_at == LATER

    records = action_records(audit, "delivery_channel.save")
    assert len(records) == 1
    record = records[0]
    assert record["method"] == "record_command_result"
    assert record["actor_type"] is AuditActorType.USER
    assert record["actor_id"] == "api-user"
    assert record["target_type"] == "delivery_channel"
    assert record["target_id"] == DEFAULT_DELIVERY_CHANNEL_ID
    assert record["result"] is AuditResult.SUCCEEDED
    assert record["metadata"]["project_id"] == project.project_id
    assert record["metadata"]["delivery_mode"] == "git_auto_delivery"
    assert record["metadata"]["repository_identifier"] == "acme/app"
    assert record["metadata"]["ref_transition"] == {
        "changed": True,
        "before_ref": None,
        "after_ref": "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
    }
    assert "raw-secret" not in str(record["metadata"])


def test_update_project_channel_to_demo_clears_git_fields_and_keeps_demo_ready(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        service = DeliveryChannelService(session, audit_service=audit, now=lambda: NOW)
        service.update_project_channel(
            project.project_id,
            git_request(),
            trace_context=build_trace(),
        )
        updated = DeliveryChannelService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).update_project_channel(
            project.project_id,
            ProjectDeliveryChannelUpdateRequest(
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
            ),
            trace_context=build_trace(),
        )

    assert updated.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert updated.scm_provider_type is None
    assert updated.repository_identifier is None
    assert updated.default_branch is None
    assert updated.code_review_request_type is None
    assert updated.credential_ref is None
    assert updated.credential_status is CredentialStatus.READY
    assert updated.readiness_status is DeliveryReadinessStatus.READY
    assert updated.readiness_message is None
    assert updated.last_validated_at is None
    assert updated.updated_at == LATER


def test_demo_delivery_save_ignores_invalid_stale_credential_ref(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        updated = DeliveryChannelService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).update_project_channel(
            project.project_id,
            ProjectDeliveryChannelUpdateRequest(
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
                scm_provider_type=ScmProviderType.GITHUB,
                repository_identifier="acme/app",
                default_branch="main",
                code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
                credential_ref="raw-stale-secret",
            ),
            trace_context=build_trace(),
        )

    assert updated.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert updated.scm_provider_type is None
    assert updated.repository_identifier is None
    assert updated.default_branch is None
    assert updated.code_review_request_type is None
    assert updated.credential_ref is None
    assert action_records(audit, "delivery_channel.save")
    assert not action_records(audit, "delivery_channel.save.rejected")


def test_invalid_credential_ref_is_rejected_without_saving_raw_secret(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import (
        DeliveryChannelService,
        DeliveryChannelServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        with pytest.raises(DeliveryChannelServiceError) as error:
            DeliveryChannelService(
                session,
                audit_service=audit,
                now=lambda: LATER,
            ).update_project_channel(
                project.project_id,
                git_request(credential_ref="raw-secret-value"),
                trace_context=build_trace(),
            )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert error.value.error_code is ErrorCode.CONFIG_INVALID_VALUE
    assert error.value.status_code == 422
    assert error.value.message == (
        "DeliveryChannel credential_ref must use an env: credential reference."
    )
    assert saved is not None
    assert saved.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert saved.credential_ref is None
    records = action_records(audit, "delivery_channel.save.rejected")
    assert len(records) == 1
    assert records[0]["result"] is AuditResult.REJECTED
    assert records[0]["metadata"] == {
        "credential_ref_status": "invalid_reference",
        "error_code": "config_invalid_value",
    }
    assert "raw-secret-value" not in str(records[0]["metadata"])


def test_non_ascii_credential_ref_name_is_rejected_without_saving(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import (
        DeliveryChannelService,
        DeliveryChannelServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        with pytest.raises(DeliveryChannelServiceError) as error:
            DeliveryChannelService(
                session,
                audit_service=audit,
                now=lambda: LATER,
            ).update_project_channel(
                project.project_id,
                git_request(credential_ref="env:AI_DEVFLOW_CREDENTIAL_\u5bc6\u94a5"),
                trace_context=build_trace(),
            )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert error.value.error_code is ErrorCode.CONFIG_INVALID_VALUE
    assert error.value.status_code == 422
    assert saved is not None
    assert saved.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert saved.credential_ref is None
    records = action_records(audit, "delivery_channel.save.rejected")
    assert len(records) == 1
    assert records[0]["metadata"] == {
        "credential_ref_status": "invalid_reference",
        "error_code": "config_invalid_value",
    }


def test_missing_git_fields_are_rejected_and_audited_without_saving(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import (
        DeliveryChannelService,
        DeliveryChannelServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        with pytest.raises(DeliveryChannelServiceError) as error:
            DeliveryChannelService(
                session,
                audit_service=audit,
                now=lambda: LATER,
            ).update_project_channel(
                project.project_id,
                git_request(code_review_request_type=None),
                trace_context=build_trace(),
            )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert error.value.error_code is ErrorCode.CONFIG_INVALID_VALUE
    assert error.value.status_code == 422
    assert error.value.message == (
        "git_auto_delivery requires code_review_request_type"
    )
    assert saved is not None
    assert saved.delivery_mode is DeliveryMode.DEMO_DELIVERY
    records = action_records(audit, "delivery_channel.save.rejected")
    assert len(records) == 1
    assert records[0]["metadata"] == {
        "missing_fields": ["code_review_request_type"],
        "error_code": "config_invalid_value",
    }


def test_whitespace_git_fields_are_rejected_without_saving(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import (
        DeliveryChannelService,
        DeliveryChannelServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        with pytest.raises(DeliveryChannelServiceError) as error:
            DeliveryChannelService(
                session,
                audit_service=audit,
                now=lambda: LATER,
            ).update_project_channel(
                project.project_id,
                git_request(repository_identifier="  ", default_branch=" \t "),
                trace_context=build_trace(),
            )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert error.value.error_code is ErrorCode.CONFIG_INVALID_VALUE
    assert error.value.status_code == 422
    assert error.value.message == (
        "git_auto_delivery requires default_branch, repository_identifier"
    )
    assert saved is not None
    assert saved.delivery_mode is DeliveryMode.DEMO_DELIVERY
    records = action_records(audit, "delivery_channel.save.rejected")
    assert len(records) == 1
    assert records[0]["metadata"] == {
        "missing_fields": ["default_branch", "repository_identifier"],
        "error_code": "config_invalid_value",
    }


def test_git_string_fields_are_stripped_before_saving(tmp_path: Path) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        updated = DeliveryChannelService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).update_project_channel(
            project.project_id,
            git_request(
                repository_identifier="  acme/app  ",
                default_branch="  main  ",
            ),
            trace_context=build_trace(),
        )

    assert updated.repository_identifier == "acme/app"
    assert updated.default_branch == "main"


def test_delivery_channel_service_respects_injected_credential_env_prefixes(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import (
        DeliveryChannelService,
        DeliveryChannelServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        service = DeliveryChannelService(
            session,
            audit_service=audit,
            now=lambda: NOW,
            credential_env_prefixes=("TEAM_DELIVERY_",),
        )
        updated = service.update_project_channel(
            project.project_id,
            git_request(credential_ref="env:TEAM_DELIVERY_TOKEN"),
            trace_context=build_trace(),
        )
        with pytest.raises(DeliveryChannelServiceError):
            service.update_project_channel(
                project.project_id,
                git_request(credential_ref="env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"),
                trace_context=build_trace(),
            )

    assert updated.credential_ref == "env:TEAM_DELIVERY_TOKEN"


def test_success_audit_blocks_preexisting_unsafe_credential_ref(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(
            session,
            credential_ref="raw-legacy-secret",
        )
        DeliveryChannelService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).update_project_channel(
            project.project_id,
            git_request(),
            trace_context=build_trace(),
        )

    records = action_records(audit, "delivery_channel.save")
    assert len(records) == 1
    metadata = records[0]["metadata"]
    assert metadata["credential_ref"] == "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
    assert metadata["ref_transition"] == {
        "changed": True,
        "before_ref": "[blocked:credential_ref]",
        "after_ref": "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
    }
    assert "raw-legacy-secret" not in str(metadata)


def test_update_project_channel_missing_project_returns_not_found(tmp_path: Path) -> None:
    from backend.app.services.delivery_channels import (
        DeliveryChannelService,
        DeliveryChannelServiceError,
    )

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        with pytest.raises(DeliveryChannelServiceError) as error:
            DeliveryChannelService(
                session,
                audit_service=audit,
                now=lambda: NOW,
            ).update_project_channel(
                "project-missing",
                ProjectDeliveryChannelUpdateRequest(
                    delivery_mode=DeliveryMode.DEMO_DELIVERY,
                ),
                trace_context=build_trace(),
            )

    assert error.value.error_code is ErrorCode.NOT_FOUND
    assert error.value.status_code == 404
    assert error.value.message == "Project was not found."
    assert action_records(audit, "delivery_channel.save.rejected")


def test_update_project_channel_rolls_back_when_success_audit_fails(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            DeliveryChannelService(
                session,
                audit_service=FailingAuditService(),
                now=lambda: LATER,
            ).update_project_channel(
                project.project_id,
                git_request(),
                trace_context=build_trace(),
            )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert saved is not None
    assert saved.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert saved.credential_ref is None
    assert saved.updated_at == NOW.replace(tzinfo=None)


def test_update_project_channel_requires_audit_service_before_persisting(
    tmp_path: Path,
) -> None:
    from backend.app.services.delivery_channels import DeliveryChannelService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        project = seed_project_with_channel(session)
        with pytest.raises(RuntimeError, match="audit_service is required"):
            DeliveryChannelService(
                session,
                now=lambda: LATER,
            ).update_project_channel(
                project.project_id,
                git_request(),
                trace_context=build_trace(),
            )
        saved = session.get(DeliveryChannelModel, DEFAULT_DELIVERY_CHANNEL_ID)

    assert saved is not None
    assert saved.delivery_mode is DeliveryMode.DEMO_DELIVERY
    assert saved.credential_ref is None
    assert saved.updated_at == NOW.replace(tzinfo=None)
