from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import time
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import PlatformRuntimeSettingsModel
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.repositories.runtime_settings import (
    RUNTIME_SETTINGS_ID,
    PlatformRuntimeSettingsRepository,
    RuntimeSettingsRepositoryError,
    RuntimeSettingsVersionConflict,
)
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
)
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    LogPolicy,
    PlatformHardLimits,
    PlatformRuntimeSettingsRead,
    PlatformRuntimeSettingsUpdate,
    PlatformRuntimeSettingsVersion,
    ProviderCallPolicy,
)


RUNTIME_SETTINGS_SCHEMA_VERSION = "runtime-settings-schema-v1"
INITIAL_RUNTIME_SETTINGS_VERSION = "runtime-settings-v1"
API_ACTOR_ID = "api-user"
SYSTEM_ACTOR_ID = "runtime-settings-seed"
EMPTY_UPDATE_MESSAGE = (
    "PlatformRuntimeSettings update must include at least one settings group."
)
VERSION_CONFLICT_MESSAGE = (
    "PlatformRuntimeSettings expected_config_version does not match the current version."
)
STORAGE_UNAVAILABLE_MESSAGE = "PlatformRuntimeSettings storage is unavailable."
INVALID_PERSISTED_SETTINGS_MESSAGE = "PlatformRuntimeSettings stored payload is invalid."
EFFECTIVE_SCOPE = "future_runs_and_diagnostic_queries"
TARGET_TYPE = "platform_runtime_settings"
LOG_SOURCE = "services.runtime_settings"
LOG_AUDIT_FAILURE_MESSAGE = "PlatformRuntimeSettings observability write failed."


class RuntimeSettingsServiceError(RuntimeError):
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


class PlatformRuntimeSettingsService:
    def __init__(
        self,
        session: Session,
        *,
        audit_service: Any,
        log_writer: Any,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._repository = PlatformRuntimeSettingsRepository(session)
        self._audit_service = audit_service
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))

    def ensure_initialized(
        self,
        trace_context: TraceContext,
    ) -> PlatformRuntimeSettingsRead:
        try:
            current = self._repository.get_current()
        except RuntimeSettingsRepositoryError as exc:
            raise self._storage_error() from exc

        if current is not None:
            return self._to_read(current)

        model = self._default_model(trace_context=trace_context)
        try:
            self._repository.save_new_version(model)
            self._session.commit()
            self._record_settings_log(
                message="PlatformRuntimeSettings initialized.",
                payload_type="runtime_settings_initialize",
                metadata=self._settings_metadata(
                    model,
                    changed_groups=[
                        "agent_limits",
                        "provider_call_policy",
                        "context_limits",
                        "log_policy",
                    ],
                ),
                trace_context=trace_context,
                created_at=model.updated_at,
            )
            self._record_initialize_audit(model, trace_context=trace_context)
        except RuntimeSettingsRepositoryError as exc:
            self._session.rollback()
            raise self._storage_error() from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise self._storage_error() from exc
        except Exception as exc:
            self._session.rollback()
            raise self._storage_error(LOG_AUDIT_FAILURE_MESSAGE) from exc
        return self._to_read(model)

    def get_current_settings(
        self,
        *,
        trace_context: TraceContext,
    ) -> PlatformRuntimeSettingsRead:
        return self.ensure_initialized(trace_context=trace_context)

    def current_version(self, *, trace_context: TraceContext) -> str:
        return self.ensure_initialized(trace_context=trace_context).version.config_version

    def update_settings(
        self,
        body: PlatformRuntimeSettingsUpdate,
        *,
        trace_context: TraceContext,
    ) -> PlatformRuntimeSettingsRead:
        current = self.ensure_initialized(trace_context=trace_context)
        try:
            model = self._repository.get_current()
        except RuntimeSettingsRepositoryError as exc:
            raise self._storage_error() from exc
        if model is None:
            raise self._storage_error()

        if self._is_empty_update(body):
            self._raise_rejected(
                message=EMPTY_UPDATE_MESSAGE,
                error_code=ErrorCode.CONFIG_INVALID_VALUE,
                status_code=422,
                metadata={
                    "submitted_groups": [],
                    "current_config_version": current.version.config_version,
                },
                trace_context=trace_context,
            )

        if body.expected_config_version != current.version.config_version:
            self._raise_rejected(
                message=VERSION_CONFLICT_MESSAGE,
                error_code=ErrorCode.CONFIG_VERSION_CONFLICT,
                status_code=409,
                metadata={
                    "expected_config_version": body.expected_config_version,
                    "current_config_version": current.version.config_version,
                },
                trace_context=trace_context,
            )

        try:
            merged = self._merged_settings_dicts(current, body)
            validated = {
                "agent_limits": AgentRuntimeLimits.model_validate(
                    merged["agent_limits"],
                ),
                "provider_call_policy": ProviderCallPolicy.model_validate(
                    merged["provider_call_policy"],
                ),
                "context_limits": ContextLimits.model_validate(
                    merged["context_limits"],
                ),
                "log_policy": LogPolicy.model_validate(merged["log_policy"]),
            }
        except ValidationError as exc:
            self._raise_rejected(
                message=INVALID_PERSISTED_SETTINGS_MESSAGE,
                error_code=ErrorCode.CONFIG_INVALID_VALUE,
                status_code=422,
                metadata={
                    "expected_config_version": body.expected_config_version,
                    "current_config_version": current.version.config_version,
                    "validation_error_count": len(exc.errors()),
                },
                trace_context=trace_context,
            )

        try:
            self.validate_against_hard_limits(
                agent_limits=validated["agent_limits"],
                provider_call_policy=validated["provider_call_policy"],
                context_limits=validated["context_limits"],
                log_policy=validated["log_policy"],
            )
        except RuntimeSettingsServiceError as exc:
            self._raise_rejected(
                message=exc.message,
                error_code=exc.error_code,
                status_code=exc.status_code,
                metadata={
                    "expected_config_version": body.expected_config_version,
                    "current_config_version": current.version.config_version,
                    "violation": exc.message,
                },
                trace_context=trace_context,
            )

        changed_fields = self._changed_fields(current, merged)
        changed_groups = self._changed_groups(body)
        previous_config_version = current.version.config_version
        new_config_version = self._next_config_version(previous_config_version)
        timestamp = self._now()
        hard_limits = PlatformHardLimits()

        model.agent_limits = validated["agent_limits"].model_dump(mode="python")
        model.provider_call_policy = validated["provider_call_policy"].model_dump(
            mode="python",
        )
        model.context_limits = validated["context_limits"].model_dump(mode="python")
        model.log_policy = validated["log_policy"].model_dump(mode="python")
        model.config_version = new_config_version
        model.schema_version = RUNTIME_SETTINGS_SCHEMA_VERSION
        model.hard_limits_version = hard_limits.hard_limits_version
        model.updated_by_actor_id = API_ACTOR_ID
        model.last_trace_id = trace_context.trace_id
        model.updated_at = timestamp

        metadata = self._update_metadata(
            current=current,
            model=model,
            changed_groups=changed_groups,
            changed_fields=changed_fields,
        )
        try:
            saved_model = self._repository.save_new_version(
                model,
                expected_config_version=previous_config_version,
            )
            self._session.commit()
            self._record_settings_log(
                message="PlatformRuntimeSettings updated.",
                payload_type="runtime_settings_update",
                metadata=metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
            self._record_update_success_audit(
                metadata=metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
        except RuntimeSettingsVersionConflict as exc:
            self._session.rollback()
            self._record_update_rejected_audit_safely(
                reason=VERSION_CONFLICT_MESSAGE,
                metadata={
                    **metadata,
                    "error_code": ErrorCode.CONFIG_VERSION_CONFLICT.value,
                },
                trace_context=trace_context,
                created_at=timestamp,
            )
            raise RuntimeSettingsServiceError(
                ErrorCode.CONFIG_VERSION_CONFLICT,
                VERSION_CONFLICT_MESSAGE,
                409,
            ) from exc
        except RuntimeSettingsRepositoryError as exc:
            self._session.rollback()
            self._record_update_failed_audit_safely(
                reason=STORAGE_UNAVAILABLE_MESSAGE,
                metadata=metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
            raise self._storage_error() from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            self._record_update_failed_audit_safely(
                reason=STORAGE_UNAVAILABLE_MESSAGE,
                metadata=metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
            raise self._storage_error() from exc
        except Exception as exc:
            self._session.rollback()
            self._record_update_failed_audit_safely(
                reason=LOG_AUDIT_FAILURE_MESSAGE,
                metadata=metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
            raise self._storage_error(LOG_AUDIT_FAILURE_MESSAGE) from exc

        return self._to_read(saved_model)

    def validate_against_hard_limits(
        self,
        *,
        agent_limits: AgentRuntimeLimits,
        provider_call_policy: ProviderCallPolicy,
        context_limits: ContextLimits,
        log_policy: LogPolicy,
    ) -> None:
        hard_limits = PlatformHardLimits()
        self._assert_group_le(
            "agent_limits",
            agent_limits.model_dump(mode="python"),
            hard_limits.agent_limits.model_dump(mode="python"),
        )
        self._assert_group_le(
            "provider_call_policy",
            provider_call_policy.model_dump(mode="python"),
            hard_limits.provider_call_policy.model_dump(mode="python"),
        )
        self._assert_group_le(
            "context_limits",
            context_limits.model_dump(
                mode="python",
                exclude={"compression_threshold_ratio"},
            ),
            hard_limits.context_limits.model_dump(mode="python"),
        )
        self._assert_group_le(
            "log_policy",
            {
                "run_log_retention_days": log_policy.run_log_retention_days,
                "audit_log_retention_days": log_policy.audit_log_retention_days,
                "log_rotation_max_bytes": log_policy.log_rotation_max_bytes,
                "log_query_max_limit": log_policy.log_query_max_limit,
            },
            hard_limits.log_policy.model_dump(mode="python"),
        )
        self._assert_le(
            "log_policy.log_query_default_limit",
            log_policy.log_query_default_limit,
            min(
                log_policy.log_query_max_limit,
                hard_limits.log_policy.log_query_max_limit,
            ),
        )

    def _default_model(
        self,
        *,
        trace_context: TraceContext,
    ) -> PlatformRuntimeSettingsModel:
        timestamp = self._now()
        hard_limits = PlatformHardLimits()
        return PlatformRuntimeSettingsModel(
            settings_id=RUNTIME_SETTINGS_ID,
            config_version=INITIAL_RUNTIME_SETTINGS_VERSION,
            schema_version=RUNTIME_SETTINGS_SCHEMA_VERSION,
            hard_limits_version=hard_limits.hard_limits_version,
            agent_limits=AgentRuntimeLimits().model_dump(mode="python"),
            provider_call_policy=ProviderCallPolicy().model_dump(mode="python"),
            context_limits=ContextLimits().model_dump(mode="python"),
            log_policy=LogPolicy().model_dump(mode="python"),
            created_by_actor_id=SYSTEM_ACTOR_ID,
            updated_by_actor_id=SYSTEM_ACTOR_ID,
            last_trace_id=trace_context.trace_id,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _to_read(
        self,
        model: PlatformRuntimeSettingsModel,
    ) -> PlatformRuntimeSettingsRead:
        try:
            return PlatformRuntimeSettingsRead(
                settings_id=model.settings_id,
                version=PlatformRuntimeSettingsVersion(
                    config_version=model.config_version,
                    schema_version=model.schema_version,
                    hard_limits_version=model.hard_limits_version,
                    updated_at=self._ensure_utc(model.updated_at),
                ),
                agent_limits=AgentRuntimeLimits.model_validate(model.agent_limits),
                provider_call_policy=ProviderCallPolicy.model_validate(
                    model.provider_call_policy,
                ),
                context_limits=ContextLimits.model_validate(model.context_limits),
                log_policy=LogPolicy.model_validate(model.log_policy),
                hard_limits=PlatformHardLimits(),
            )
        except ValidationError as exc:
            raise RuntimeSettingsServiceError(
                ErrorCode.CONFIG_INVALID_VALUE,
                INVALID_PERSISTED_SETTINGS_MESSAGE,
                422,
            ) from exc

    def _merged_settings_dicts(
        self,
        current: PlatformRuntimeSettingsRead,
        body: PlatformRuntimeSettingsUpdate,
    ) -> dict[str, dict[str, Any]]:
        merged = {
            "agent_limits": current.agent_limits.model_dump(mode="python"),
            "provider_call_policy": current.provider_call_policy.model_dump(
                mode="python",
            ),
            "context_limits": current.context_limits.model_dump(mode="python"),
            "log_policy": current.log_policy.model_dump(mode="python"),
        }
        if body.agent_limits is not None:
            merged["agent_limits"].update(
                body.agent_limits.model_dump(mode="python", exclude_unset=True),
            )
        if body.provider_call_policy is not None:
            merged["provider_call_policy"].update(
                body.provider_call_policy.model_dump(
                    mode="python",
                    exclude_unset=True,
                ),
            )
        if body.context_limits is not None:
            merged["context_limits"].update(
                body.context_limits.model_dump(mode="python", exclude_unset=True),
            )
        if body.log_policy is not None:
            merged["log_policy"].update(
                body.log_policy.model_dump(mode="python", exclude_unset=True),
            )
        return merged

    def _changed_fields(
        self,
        current: PlatformRuntimeSettingsRead,
        merged: dict[str, dict[str, Any]],
    ) -> list[str]:
        current_groups = {
            "agent_limits": current.agent_limits.model_dump(mode="python"),
            "provider_call_policy": current.provider_call_policy.model_dump(
                mode="python",
            ),
            "context_limits": current.context_limits.model_dump(mode="python"),
            "log_policy": current.log_policy.model_dump(mode="python"),
        }
        changed: list[str] = []
        for group_name, current_values in current_groups.items():
            for field_name, current_value in current_values.items():
                if merged[group_name][field_name] != current_value:
                    changed.append(f"{group_name}.{field_name}")
        return changed

    def _changed_groups(self, body: PlatformRuntimeSettingsUpdate) -> list[str]:
        changed_groups: list[str] = []
        if body.agent_limits is not None:
            changed_groups.append("agent_limits")
        if body.provider_call_policy is not None:
            changed_groups.append("provider_call_policy")
        if body.context_limits is not None:
            changed_groups.append("context_limits")
        if body.log_policy is not None:
            changed_groups.append("log_policy")
        return changed_groups

    @staticmethod
    def _is_empty_update(body: PlatformRuntimeSettingsUpdate) -> bool:
        return (
            body.agent_limits is None
            and body.provider_call_policy is None
            and body.context_limits is None
            and body.log_policy is None
        )

    @staticmethod
    def _next_config_version(current_version: str) -> str:
        prefix = "runtime-settings-v"
        if current_version.startswith(prefix):
            suffix = current_version.removeprefix(prefix)
            try:
                return f"{prefix}{int(suffix) + 1}"
            except ValueError:
                pass
        return f"{prefix}{int(time() * 1_000_000)}"

    def _raise_rejected(
        self,
        *,
        message: str,
        error_code: ErrorCode,
        status_code: int,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        full_metadata = {
            **metadata,
            "settings_id": RUNTIME_SETTINGS_ID,
            "error_code": error_code.value,
            "effective_scope": EFFECTIVE_SCOPE,
        }
        timestamp = self._now()
        try:
            self._record_settings_log(
                message="PlatformRuntimeSettings update rejected.",
                payload_type="runtime_settings_update_rejected",
                metadata=full_metadata,
                trace_context=trace_context,
                created_at=timestamp,
                level=LogLevel.WARNING,
                error_code=error_code.value,
            )
            self._record_update_rejected_audit(
                reason=message,
                metadata=full_metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
        except Exception as exc:
            raise self._storage_error(LOG_AUDIT_FAILURE_MESSAGE) from exc
        finally:
            self._session.rollback()
        raise RuntimeSettingsServiceError(error_code, message, status_code)

    def _assert_group_le(
        self,
        group_name: str,
        values: dict[str, int | float],
        limits: dict[str, int | float],
    ) -> None:
        for field_name, value in values.items():
            self._assert_le(
                f"{group_name}.{field_name}",
                value,
                limits[field_name],
            )

    def _assert_le(
        self,
        field_path: str,
        value: int | float,
        limit: int | float,
    ) -> None:
        if value > limit:
            raise RuntimeSettingsServiceError(
                ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED,
                f"{field_path} exceeds platform hard limit {limit}.",
                422,
            )

    def _record_settings_log(
        self,
        *,
        message: str,
        payload_type: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
        level: LogLevel = LogLevel.INFO,
        error_code: str | None = None,
    ) -> None:
        redacted = self._redaction_policy.summarize_payload(
            metadata,
            payload_type=payload_type,
        )
        self._log_writer.write(
            LogRecordInput(
                source=LOG_SOURCE,
                category=LogCategory.API,
                level=level,
                message=message,
                trace_context=trace_context,
                payload=LogPayloadSummary.from_redacted_payload(
                    payload_type,
                    redacted,
                ),
                created_at=created_at,
                error_code=error_code,
            )
        )

    def _record_initialize_audit(
        self,
        model: PlatformRuntimeSettingsModel,
        *,
        trace_context: TraceContext,
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.SYSTEM,
            actor_id=SYSTEM_ACTOR_ID,
            action="runtime_settings.initialize",
            target_type=TARGET_TYPE,
            target_id=RUNTIME_SETTINGS_ID,
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata=self._settings_metadata(
                model,
                changed_groups=[
                    "agent_limits",
                    "provider_call_policy",
                    "context_limits",
                    "log_policy",
                ],
            ),
            trace_context=trace_context,
            created_at=model.updated_at,
        )

    def _record_update_success_audit(
        self,
        *,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="runtime_settings.update",
            target_type=TARGET_TYPE,
            target_id=RUNTIME_SETTINGS_ID,
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata=metadata,
            trace_context=trace_context,
            created_at=created_at,
        )

    def _record_update_rejected_audit(
        self,
        *,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
    ) -> None:
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="runtime_settings.update.rejected",
            target_type=TARGET_TYPE,
            target_id=RUNTIME_SETTINGS_ID,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
            created_at=created_at,
        )

    def _record_update_rejected_audit_safely(
        self,
        *,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
    ) -> None:
        try:
            self._record_update_rejected_audit(
                reason=reason,
                metadata=metadata,
                trace_context=trace_context,
                created_at=created_at,
            )
        except Exception:
            pass

    def _record_update_failed_audit_safely(
        self,
        *,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
    ) -> None:
        try:
            self._record_update_failed_audit(
                reason=reason,
                metadata=metadata,
                trace_context=trace_context,
                created_at=created_at,
            )
        except Exception:
            pass

    def _record_update_failed_audit(
        self,
        *,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="runtime_settings.update.failed",
            target_type=TARGET_TYPE,
            target_id=RUNTIME_SETTINGS_ID,
            result=AuditResult.FAILED,
            reason=reason,
            metadata={
                **metadata,
                "error_code": ErrorCode.CONFIG_STORAGE_UNAVAILABLE.value,
            },
            trace_context=trace_context,
            created_at=created_at,
        )

    def _settings_metadata(
        self,
        model: PlatformRuntimeSettingsModel,
        *,
        changed_groups: list[str],
    ) -> dict[str, Any]:
        return {
            "settings_id": model.settings_id,
            "config_version": model.config_version,
            "schema_version": model.schema_version,
            "hard_limits_version": model.hard_limits_version,
            "changed_groups": changed_groups,
            "effective_scope": EFFECTIVE_SCOPE,
        }

    def _update_metadata(
        self,
        *,
        current: PlatformRuntimeSettingsRead,
        model: PlatformRuntimeSettingsModel,
        changed_groups: list[str],
        changed_fields: list[str],
    ) -> dict[str, Any]:
        previous_values = {
            "agent_limits": current.agent_limits.model_dump(mode="python"),
            "provider_call_policy": current.provider_call_policy.model_dump(
                mode="python",
            ),
            "context_limits": current.context_limits.model_dump(mode="python"),
            "log_policy": current.log_policy.model_dump(mode="python"),
        }
        new_values = {
            "agent_limits": dict(model.agent_limits),
            "provider_call_policy": dict(model.provider_call_policy),
            "context_limits": dict(model.context_limits),
            "log_policy": dict(model.log_policy),
        }
        return {
            "settings_id": model.settings_id,
            "previous_config_version": current.version.config_version,
            "new_config_version": model.config_version,
            "schema_version": model.schema_version,
            "hard_limits_version": model.hard_limits_version,
            "changed_groups": changed_groups,
            "changed_fields": changed_fields,
            "old_value_summary": {
                field_path: self._field_value(previous_values, field_path)
                for field_path in changed_fields
            },
            "new_value_summary": {
                field_path: self._field_value(new_values, field_path)
                for field_path in changed_fields
            },
            "effective_scope": EFFECTIVE_SCOPE,
        }

    @staticmethod
    def _field_value(groups: dict[str, dict[str, Any]], field_path: str) -> Any:
        group_name, field_name = field_path.split(".", 1)
        return groups[group_name][field_name]

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @staticmethod
    def _storage_error(
        message: str = STORAGE_UNAVAILABLE_MESSAGE,
    ) -> RuntimeSettingsServiceError:
        return RuntimeSettingsServiceError(
            ErrorCode.CONFIG_STORAGE_UNAVAILABLE,
            message,
            503,
        )


__all__ = [
    "API_ACTOR_ID",
    "EMPTY_UPDATE_MESSAGE",
    "INITIAL_RUNTIME_SETTINGS_VERSION",
    "INVALID_PERSISTED_SETTINGS_MESSAGE",
    "LOG_AUDIT_FAILURE_MESSAGE",
    "PlatformRuntimeSettingsService",
    "RUNTIME_SETTINGS_SCHEMA_VERSION",
    "RuntimeSettingsServiceError",
    "STORAGE_UNAVAILABLE_MESSAGE",
    "SYSTEM_ACTOR_ID",
    "VERSION_CONFLICT_MESSAGE",
]
