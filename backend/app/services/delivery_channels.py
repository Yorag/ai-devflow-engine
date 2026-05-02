from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.models.control import DeliveryChannelModel, ProjectModel
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ScmProviderType,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.delivery_channel import ProjectDeliveryChannelUpdateRequest
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
)


DEFAULT_PROJECT_ID = "project-default"
DEFAULT_DELIVERY_CHANNEL_ID = "delivery-default"
API_ACTOR_ID = "api-user"
PROJECT_NOT_FOUND_MESSAGE = "Project was not found."
DELIVERY_CHANNEL_NOT_FOUND_MESSAGE = "DeliveryChannel was not found."
INVALID_CREDENTIAL_REFERENCE_MESSAGE = (
    "DeliveryChannel credential_ref must use an env: credential reference."
)
INVALID_ALLOWED_CREDENTIAL_REFERENCE_MESSAGE = (
    "DeliveryChannel credential_ref must use an allowed env: credential reference."
)
MISSING_ENV_CREDENTIAL_MESSAGE = (
    "DeliveryChannel credential_ref does not resolve to an available credential."
)
EMPTY_ENV_CREDENTIAL_MESSAGE = (
    "DeliveryChannel credential_ref resolves to an empty credential."
)
UNVALIDATED_READINESS_MESSAGE = "DeliveryChannel readiness has not been validated."
DEMO_READY_MESSAGE = "demo_delivery is ready."
GIT_READY_MESSAGE = "git_auto_delivery is ready."
GIT_REQUIRED_MESSAGE_PREFIX = "git_auto_delivery requires "
BLOCKED_CREDENTIAL_REF = "[blocked:credential_ref]"
GIT_VALIDATED_FIELDS = (
    "scm_provider_type",
    "repository_identifier",
    "default_branch",
    "code_review_request_type",
    "credential_ref",
)


def _default_channel_id(project_id: str) -> str:
    if project_id == DEFAULT_PROJECT_ID:
        return DEFAULT_DELIVERY_CHANNEL_ID
    digest = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
    return f"delivery-{digest[:24]}"


class DeliveryChannelServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class DeliveryChannelReadinessResult:
    readiness_status: DeliveryReadinessStatus
    readiness_message: str | None
    credential_status: CredentialStatus
    validated_fields: tuple[str, ...]


@dataclass(frozen=True)
class DeliveryChannelValidationResult:
    readiness_status: DeliveryReadinessStatus
    readiness_message: str | None
    credential_status: CredentialStatus
    validated_fields: tuple[str, ...]
    validated_at: datetime


class DeliveryChannelService:
    def __init__(
        self,
        session: Session,
        *,
        audit_service: Any | None = None,
        log_writer: Any | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
        credential_env_prefixes: Iterable[str] | None = None,
        credential_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._session = session
        self._audit_service = audit_service
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))
        self._credential_resolver = credential_resolver or os.environ.get
        self._credential_env_prefixes = tuple(
            credential_env_prefixes
            if credential_env_prefixes is not None
            else EnvironmentSettings().credential_env_prefixes
        )

    def ensure_default_channel(self, project_id: str) -> DeliveryChannelModel:
        delivery_channel_id = _default_channel_id(project_id)
        existing = self._session.get(DeliveryChannelModel, delivery_channel_id)
        if existing is not None:
            return existing

        timestamp = self._now()
        channel = DeliveryChannelModel(
            delivery_channel_id=delivery_channel_id,
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
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._session.add(channel)
        self._session.flush()
        return channel

    def get_project_channel(
        self,
        project_id: str,
        *,
        trace_context: TraceContext,
    ) -> DeliveryChannelModel:
        del trace_context
        project = self._get_visible_project(project_id)
        channel = self._get_default_channel(project)
        if channel is None:
            raise DeliveryChannelServiceError(
                ErrorCode.NOT_FOUND,
                DELIVERY_CHANNEL_NOT_FOUND_MESSAGE,
                404,
            )
        return channel

    def credential_ref_for_projection(self, value: str | None) -> str | None:
        return self._audit_credential_ref(value)

    def resolve_credential_status(self, credential_ref: str | None) -> CredentialStatus:
        if self._is_blank(credential_ref):
            return CredentialStatus.UNBOUND
        if not isinstance(credential_ref, str) or not self._is_safe_credential_ref(
            credential_ref,
        ):
            return CredentialStatus.INVALID
        credential_value = self._credential_resolver(
            self._credential_env_name(credential_ref),
        )
        if credential_value is None:
            return CredentialStatus.UNBOUND
        if self._is_blank(credential_value):
            return CredentialStatus.INVALID
        return CredentialStatus.READY

    def compute_readiness(
        self,
        channel: DeliveryChannelModel,
    ) -> DeliveryChannelReadinessResult:
        if channel.delivery_mode is DeliveryMode.DEMO_DELIVERY:
            return DeliveryChannelReadinessResult(
                readiness_status=DeliveryReadinessStatus.READY,
                readiness_message=DEMO_READY_MESSAGE,
                credential_status=CredentialStatus.READY,
                validated_fields=("delivery_mode",),
            )

        missing_git_fields = [
            field for field in GIT_VALIDATED_FIELDS[:-1] if self._is_blank(getattr(channel, field))
        ]
        if missing_git_fields:
            return DeliveryChannelReadinessResult(
                readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
                readiness_message=(
                    f"{GIT_REQUIRED_MESSAGE_PREFIX}{', '.join(sorted(missing_git_fields))}"
                ),
                credential_status=CredentialStatus.UNBOUND,
                validated_fields=GIT_VALIDATED_FIELDS,
            )

        if self._is_blank(channel.credential_ref):
            return DeliveryChannelReadinessResult(
                readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
                readiness_message=f"{GIT_REQUIRED_MESSAGE_PREFIX}credential_ref",
                credential_status=CredentialStatus.UNBOUND,
                validated_fields=GIT_VALIDATED_FIELDS,
            )

        credential_ref = channel.credential_ref
        if not self._is_safe_credential_ref(credential_ref):
            return DeliveryChannelReadinessResult(
                readiness_status=DeliveryReadinessStatus.INVALID,
                readiness_message=INVALID_ALLOWED_CREDENTIAL_REFERENCE_MESSAGE,
                credential_status=CredentialStatus.INVALID,
                validated_fields=GIT_VALIDATED_FIELDS,
            )

        credential_status = self.resolve_credential_status(credential_ref)
        if credential_status is CredentialStatus.UNBOUND:
            return DeliveryChannelReadinessResult(
                readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
                readiness_message=MISSING_ENV_CREDENTIAL_MESSAGE,
                credential_status=credential_status,
                validated_fields=GIT_VALIDATED_FIELDS,
            )
        if credential_status is CredentialStatus.INVALID:
            return DeliveryChannelReadinessResult(
                readiness_status=DeliveryReadinessStatus.INVALID,
                readiness_message=EMPTY_ENV_CREDENTIAL_MESSAGE,
                credential_status=credential_status,
                validated_fields=GIT_VALIDATED_FIELDS,
            )
        return DeliveryChannelReadinessResult(
            readiness_status=DeliveryReadinessStatus.READY,
            readiness_message=GIT_READY_MESSAGE,
            credential_status=credential_status,
            validated_fields=GIT_VALIDATED_FIELDS,
        )

    def update_project_channel(
        self,
        project_id: str,
        body: ProjectDeliveryChannelUpdateRequest,
        *,
        trace_context: TraceContext,
    ) -> DeliveryChannelModel:
        self._require_audit_service()
        project = self._get_visible_project_for_update(
            project_id,
            trace_context=trace_context,
        )
        channel = self._get_default_channel(project)
        if channel is None:
            self._record_rejected(
                target_id=f"project:{project_id}",
                reason=DELIVERY_CHANNEL_NOT_FOUND_MESSAGE,
                metadata={"project_id": project_id},
                trace_context=trace_context,
            )
            raise DeliveryChannelServiceError(
                ErrorCode.NOT_FOUND,
                DELIVERY_CHANNEL_NOT_FOUND_MESSAGE,
                404,
            )

        try:
            self._validate_update_request(
                body,
                target_id=channel.delivery_channel_id,
                trace_context=trace_context,
            )
        except Exception:
            self._session.rollback()
            raise

        old_credential_ref = channel.credential_ref
        self._apply_update(channel, body)
        channel.updated_at = self._now()
        self._session.add(channel)
        self._session.flush()
        try:
            self._record_success(
                channel=channel,
                old_credential_ref=old_credential_ref,
                trace_context=trace_context,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return channel

    def validate_project_channel(
        self,
        project_id: str,
        *,
        trace_context: TraceContext,
    ) -> DeliveryChannelValidationResult:
        self._require_audit_service()
        self._require_log_writer()
        channel: DeliveryChannelModel | None = None
        result: DeliveryChannelValidationResult | None = None
        should_record_failed = False
        recording_success_audit = False
        try:
            project = self._get_visible_project_for_validation(
                project_id,
                trace_context=trace_context,
            )
            channel = self._get_default_channel(project)
            if channel is None:
                self._record_validation_rejected(
                    target_id=f"project:{project_id}",
                    reason=DELIVERY_CHANNEL_NOT_FOUND_MESSAGE,
                    metadata={
                        "project_id": project_id,
                        "delivery_channel_id": project.default_delivery_channel_id,
                    },
                    trace_context=trace_context,
                )
                raise DeliveryChannelServiceError(
                    ErrorCode.NOT_FOUND,
                    DELIVERY_CHANNEL_NOT_FOUND_MESSAGE,
                    404,
                )

            should_record_failed = True
            readiness = self.compute_readiness(channel)
            validated_at = self._now()
            channel.credential_status = readiness.credential_status
            channel.readiness_status = readiness.readiness_status
            channel.readiness_message = readiness.readiness_message
            channel.last_validated_at = validated_at
            channel.updated_at = validated_at
            self._session.add(channel)
            self._session.flush()

            result = DeliveryChannelValidationResult(
                readiness_status=readiness.readiness_status,
                readiness_message=readiness.readiness_message,
                credential_status=readiness.credential_status,
                validated_fields=readiness.validated_fields,
                validated_at=validated_at,
            )
            self._record_validation_log(
                channel=channel,
                result=result,
                trace_context=trace_context,
            )
            recording_success_audit = True
            self._record_validation_success(
                channel=channel,
                result=result,
                trace_context=trace_context,
            )
            recording_success_audit = False
            self._session.commit()
            should_record_failed = False
            return result
        except DeliveryChannelServiceError:
            self._session.rollback()
            raise
        except Exception as exc:
            failed_audit_error: Exception | None = None
            if should_record_failed and not recording_success_audit and channel is not None:
                try:
                    self._record_validation_failed(
                        channel=channel,
                        result=result,
                        error=exc,
                        trace_context=trace_context,
                    )
                except Exception as audit_exc:
                    failed_audit_error = audit_exc
            self._session.rollback()
            if failed_audit_error is not None:
                raise failed_audit_error from exc
            raise

    def _get_visible_project(self, project_id: str) -> ProjectModel:
        project = self._session.get(ProjectModel, project_id)
        if project is None or not project.is_visible:
            raise DeliveryChannelServiceError(
                ErrorCode.NOT_FOUND,
                PROJECT_NOT_FOUND_MESSAGE,
                404,
        )
        return project

    def _get_visible_project_for_update(
        self,
        project_id: str,
        *,
        trace_context: TraceContext,
    ) -> ProjectModel:
        try:
            return self._get_visible_project(project_id)
        except DeliveryChannelServiceError:
            self._record_rejected(
                target_id=f"project:{project_id}",
                reason=PROJECT_NOT_FOUND_MESSAGE,
                metadata={"project_id": project_id},
                trace_context=trace_context,
            )
            raise

    def _get_visible_project_for_validation(
        self,
        project_id: str,
        *,
        trace_context: TraceContext,
    ) -> ProjectModel:
        try:
            return self._get_visible_project(project_id)
        except DeliveryChannelServiceError:
            self._record_validation_rejected(
                target_id=f"project:{project_id}",
                reason=PROJECT_NOT_FOUND_MESSAGE,
                metadata={"project_id": project_id},
                trace_context=trace_context,
            )
            raise

    def _get_default_channel(
        self,
        project: ProjectModel,
    ) -> DeliveryChannelModel | None:
        if not project.default_delivery_channel_id:
            return None
        channel = self._session.get(
            DeliveryChannelModel,
            project.default_delivery_channel_id,
        )
        if channel is None or channel.project_id != project.project_id:
            return None
        return channel

    def _validate_credential_ref(
        self,
        value: str | None,
        *,
        target_id: str,
        trace_context: TraceContext,
    ) -> None:
        if value is None:
            return
        if self._is_safe_credential_ref(value):
            return

        self._record_rejected(
            target_id=target_id,
            reason=INVALID_CREDENTIAL_REFERENCE_MESSAGE,
            metadata={
                "credential_ref_status": "invalid_reference",
                "error_code": ErrorCode.CONFIG_INVALID_VALUE.value,
            },
            trace_context=trace_context,
        )
        raise DeliveryChannelServiceError(
            ErrorCode.CONFIG_INVALID_VALUE,
            INVALID_CREDENTIAL_REFERENCE_MESSAGE,
            422,
        )

    def _validate_update_request(
        self,
        body: ProjectDeliveryChannelUpdateRequest,
        *,
        target_id: str,
        trace_context: TraceContext,
    ) -> None:
        if body.delivery_mode is DeliveryMode.DEMO_DELIVERY:
            return

        git_fields = {
            "scm_provider_type": body.scm_provider_type,
            "repository_identifier": body.repository_identifier,
            "default_branch": body.default_branch,
            "code_review_request_type": body.code_review_request_type,
            "credential_ref": body.credential_ref,
        }
        missing_fields = [
            field for field, value in git_fields.items() if self._is_blank(value)
        ]
        if missing_fields:
            message = f"{GIT_REQUIRED_MESSAGE_PREFIX}{', '.join(sorted(missing_fields))}"
            self._record_rejected(
                target_id=target_id,
                reason=message,
                metadata={
                    "missing_fields": sorted(missing_fields),
                    "error_code": ErrorCode.CONFIG_INVALID_VALUE.value,
                },
                trace_context=trace_context,
            )
            raise DeliveryChannelServiceError(
                ErrorCode.CONFIG_INVALID_VALUE,
                message,
                422,
            )

        self._validate_credential_ref(
            body.credential_ref,
            target_id=target_id,
            trace_context=trace_context,
        )

    def _apply_update(
        self,
        channel: DeliveryChannelModel,
        body: ProjectDeliveryChannelUpdateRequest,
    ) -> None:
        channel.delivery_mode = body.delivery_mode
        channel.last_validated_at = None
        if body.delivery_mode is DeliveryMode.DEMO_DELIVERY:
            channel.scm_provider_type = None
            channel.repository_identifier = None
            channel.default_branch = None
            channel.code_review_request_type = None
            channel.credential_ref = None
            channel.credential_status = CredentialStatus.READY
            channel.readiness_status = DeliveryReadinessStatus.READY
            channel.readiness_message = None
            return

        channel.scm_provider_type = self._required(body.scm_provider_type)
        channel.repository_identifier = self._required_string(
            body.repository_identifier,
        )
        channel.default_branch = self._required_string(body.default_branch)
        channel.code_review_request_type = self._required(body.code_review_request_type)
        channel.credential_ref = self._required(body.credential_ref)
        channel.credential_status = CredentialStatus.UNBOUND
        channel.readiness_status = DeliveryReadinessStatus.UNCONFIGURED
        channel.readiness_message = UNVALIDATED_READINESS_MESSAGE

    def _record_success(
        self,
        *,
        channel: DeliveryChannelModel,
        old_credential_ref: str | None,
        trace_context: TraceContext,
    ) -> None:
        self._require_audit_service()
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="delivery_channel.save",
            target_type="delivery_channel",
            target_id=channel.delivery_channel_id,
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata=self._audit_metadata(
                channel,
                old_credential_ref=old_credential_ref,
            ),
            trace_context=trace_context,
        )

    def _record_rejected(
        self,
        *,
        target_id: str,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        self._require_audit_service()
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="delivery_channel.save.rejected",
            target_type="delivery_channel",
            target_id=target_id,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
        )

    def _record_validation_log(
        self,
        *,
        channel: DeliveryChannelModel,
        result: DeliveryChannelValidationResult,
        trace_context: TraceContext,
    ) -> None:
        self._require_log_writer()
        redacted = self._redaction_policy.summarize_payload(
            self._validation_metadata(channel, result=result),
            payload_type="delivery_channel_validation",
        )
        self._log_writer.write(
            LogRecordInput(
                source="services.delivery_channels",
                category=LogCategory.DELIVERY,
                level=LogLevel.INFO,
                message="DeliveryChannel readiness validation result computed.",
                trace_context=trace_context,
                payload=LogPayloadSummary.from_redacted_payload(
                    "delivery_channel_validation",
                    redacted,
                ),
                created_at=result.validated_at,
            )
        )

    def _record_validation_success(
        self,
        *,
        channel: DeliveryChannelModel,
        result: DeliveryChannelValidationResult,
        trace_context: TraceContext,
    ) -> None:
        self._require_audit_service()
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="delivery_channel.validate",
            target_type="delivery_channel",
            target_id=channel.delivery_channel_id,
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata=self._validation_metadata(channel, result=result),
            trace_context=trace_context,
        )

    def _record_validation_rejected(
        self,
        *,
        target_id: str,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        self._require_audit_service()
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="delivery_channel.validate.rejected",
            target_type="delivery_channel",
            target_id=target_id,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
        )

    def _record_validation_failed(
        self,
        *,
        channel: DeliveryChannelModel,
        result: DeliveryChannelValidationResult | None,
        error: Exception,
        trace_context: TraceContext,
    ) -> None:
        self._require_audit_service()
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="delivery_channel.validate.failed",
            target_type="delivery_channel",
            target_id=channel.delivery_channel_id,
            result=AuditResult.FAILED,
            reason=str(error) or type(error).__name__,
            metadata=self._validation_failure_metadata(
                channel,
                result=result,
                error=error,
            ),
            trace_context=trace_context,
        )

    def _audit_metadata(
        self,
        channel: DeliveryChannelModel,
        *,
        old_credential_ref: str | None,
    ) -> dict[str, Any]:
        return {
            "project_id": channel.project_id,
            "delivery_channel_id": channel.delivery_channel_id,
            "delivery_mode": channel.delivery_mode.value,
            "scm_provider_type": self._enum_value(channel.scm_provider_type),
            "repository_identifier": channel.repository_identifier,
            "default_branch": channel.default_branch,
            "code_review_request_type": self._enum_value(
                channel.code_review_request_type,
            ),
            "credential_ref": self._audit_credential_ref(channel.credential_ref),
            "credential_status": channel.credential_status.value,
            "readiness_status": channel.readiness_status.value,
            "ref_transition": {
                "changed": old_credential_ref != channel.credential_ref,
                "before_ref": self._audit_credential_ref(old_credential_ref),
                "after_ref": self._audit_credential_ref(channel.credential_ref),
            },
        }

    def _validation_metadata(
        self,
        channel: DeliveryChannelModel,
        *,
        result: DeliveryChannelValidationResult,
    ) -> dict[str, Any]:
        return {
            "project_id": channel.project_id,
            "delivery_channel_id": channel.delivery_channel_id,
            "delivery_mode": channel.delivery_mode.value,
            "scm_provider_type": self._enum_value(channel.scm_provider_type),
            "repository_identifier": channel.repository_identifier,
            "default_branch": channel.default_branch,
            "code_review_request_type": self._enum_value(
                channel.code_review_request_type,
            ),
            "credential_ref": self._audit_credential_ref(channel.credential_ref),
            "credential_status": result.credential_status.value,
            "readiness_status": result.readiness_status.value,
            "readiness_message": result.readiness_message,
            "validated_fields": list(result.validated_fields),
            "validated_at": result.validated_at.isoformat(),
        }

    def _validation_failure_metadata(
        self,
        channel: DeliveryChannelModel,
        *,
        result: DeliveryChannelValidationResult | None,
        error: Exception,
    ) -> dict[str, Any]:
        if result is None:
            metadata = {
                "project_id": channel.project_id,
                "delivery_channel_id": channel.delivery_channel_id,
                "delivery_mode": channel.delivery_mode.value,
                "credential_ref": self._audit_credential_ref(channel.credential_ref),
            }
        else:
            metadata = self._validation_metadata(channel, result=result)
        metadata["error_type"] = type(error).__name__
        return metadata

    @staticmethod
    def _enum_value(
        value: ScmProviderType | CodeReviewRequestType | None,
    ) -> str | None:
        if value is None:
            return None
        return value.value

    @staticmethod
    def _required(value: Any) -> Any:
        if value is None:
            raise AssertionError("ProjectDeliveryChannelUpdateRequest was not validated.")
        return value

    @staticmethod
    def _required_string(value: str | None) -> str:
        if value is None:
            raise AssertionError("ProjectDeliveryChannelUpdateRequest was not validated.")
        stripped = value.strip()
        if not stripped:
            raise AssertionError("ProjectDeliveryChannelUpdateRequest was not validated.")
        return stripped

    def _require_audit_service(self) -> None:
        if self._audit_service is None:
            raise RuntimeError("audit_service is required for DeliveryChannel writes.")

    def _require_log_writer(self) -> None:
        if self._log_writer is None:
            raise RuntimeError("log_writer is required for DeliveryChannel validation.")

    @staticmethod
    def _is_blank(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return False

    def _is_safe_credential_ref(self, value: str) -> bool:
        env_name = value.removeprefix("env:")
        env_name_has_valid_chars = all(
            char == "_" or char.isascii() and char.isalnum() for char in env_name
        )
        env_name_has_allowed_prefix = any(
            env_name.startswith(prefix) for prefix in self._credential_env_prefixes
        )
        return (
            value.startswith("env:")
            and bool(env_name)
            and env_name_has_valid_chars
            and env_name_has_allowed_prefix
        )

    @staticmethod
    def _credential_env_name(value: str) -> str:
        return value.removeprefix("env:")

    def _audit_credential_ref(self, value: str | None) -> str | None:
        if value is None:
            return None
        if self._is_safe_credential_ref(value):
            return value
        return BLOCKED_CREDENTIAL_REF


__all__ = [
    "API_ACTOR_ID",
    "BLOCKED_CREDENTIAL_REF",
    "DEFAULT_DELIVERY_CHANNEL_ID",
    "DEFAULT_PROJECT_ID",
    "DEMO_READY_MESSAGE",
    "DeliveryChannelReadinessResult",
    "DeliveryChannelService",
    "DeliveryChannelServiceError",
    "DeliveryChannelValidationResult",
    "EMPTY_ENV_CREDENTIAL_MESSAGE",
    "GIT_READY_MESSAGE",
    "INVALID_CREDENTIAL_REFERENCE_MESSAGE",
    "INVALID_ALLOWED_CREDENTIAL_REFERENCE_MESSAGE",
    "GIT_REQUIRED_MESSAGE_PREFIX",
    "GIT_VALIDATED_FIELDS",
    "MISSING_ENV_CREDENTIAL_MESSAGE",
    "PROJECT_NOT_FOUND_MESSAGE",
    "DELIVERY_CHANNEL_NOT_FOUND_MESSAGE",
    "UNVALIDATED_READINESS_MESSAGE",
]
