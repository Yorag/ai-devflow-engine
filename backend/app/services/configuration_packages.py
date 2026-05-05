from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.models.control import (
    DeliveryChannelModel,
    PipelineTemplateModel,
    ProjectModel,
    ProviderModel,
)
from backend.app.domain.enums import (
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ProviderProtocolType,
    ProviderSource,
    TemplateSource,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.configuration_package import (
    ConfigurationPackageChangedObject,
    ConfigurationPackageDeliveryChannel,
    ConfigurationPackageExport,
    ConfigurationPackageFieldError,
    ConfigurationPackageImportRequest,
    ConfigurationPackageImportResult,
    ConfigurationPackageModelRuntimeCapabilities,
    ConfigurationPackageProvider,
    ConfigurationPackageScope,
    ConfigurationPackageTemplateConfig,
    ConfigurationPackageTemplateSlotConfig,
)
from backend.app.schemas.delivery_channel import ProjectDeliveryChannelUpdateRequest
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
)
from backend.app.schemas.provider import ProviderWriteRequest
from backend.app.schemas.template import (
    FIXED_APPROVAL_CHECKPOINTS,
    FIXED_STAGE_SEQUENCE,
    PipelineTemplateWriteRequest,
)
from backend.app.services.delivery_channels import (
    BLOCKED_CREDENTIAL_REF,
    GIT_REQUIRED_MESSAGE_PREFIX,
    INVALID_CREDENTIAL_REFERENCE_MESSAGE as INVALID_DELIVERY_CREDENTIAL_REFERENCE_MESSAGE,
    UNVALIDATED_READINESS_MESSAGE,
    DeliveryChannelService,
)
from backend.app.services.providers import (
    BUILTIN_PROVIDER_IDS,
    BUILTIN_PROVIDER_SEEDS,
    BUILTIN_IDENTITY_CHANGE_MESSAGE,
    CUSTOM_DISPLAY_NAME_REQUIRED_MESSAGE,
    CUSTOM_PROTOCOL_MISMATCH_MESSAGE,
    DUPLICATE_MODEL_CAPABILITY_MESSAGE,
    EXTRA_MODEL_CAPABILITY_MESSAGE,
    INVALID_CREDENTIAL_REFERENCE_MESSAGE as INVALID_PROVIDER_CREDENTIAL_REFERENCE_MESSAGE,
    INVALID_MODEL_BINDING_MESSAGE,
    MISSING_MODEL_CAPABILITY_MESSAGE,
    ProviderService,
)
from backend.app.services.templates import (
    INVALID_TEMPLATE_MESSAGE,
    UNKNOWN_PROVIDER_MESSAGE,
    TemplateService,
)


PACKAGE_SCHEMA_VERSION = "function-one-config-v1"
API_ACTOR_ID = "api-user"
PROJECT_NOT_FOUND_MESSAGE = "Project was not found."
UNSUPPORTED_PACKAGE_VERSION_MESSAGE = (
    "Unsupported configuration package schema version."
)
SCOPE_MISMATCH_MESSAGE = (
    "Configuration package scope does not match the target Project."
)
TOO_MANY_DELIVERY_CHANNELS_MESSAGE = (
    "Configuration package must contain at most one project DeliveryChannel."
)
SYSTEM_TEMPLATE_IMPORT_MESSAGE = (
    "System templates cannot be overwritten by configuration package import."
)
BLOCKED_API_KEY_REF = "[blocked:api_key_ref]"


class ConfigurationPackageServiceError(RuntimeError):
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


class ConfigurationPackageService:
    def __init__(
        self,
        session: Session,
        *,
        audit_service: Any,
        log_writer: Any,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
        credential_env_prefixes: Iterable[str] | None = None,
    ) -> None:
        self._session = session
        self._audit_service = audit_service
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))
        self._credential_env_prefixes = tuple(
            credential_env_prefixes
            if credential_env_prefixes is not None
            else EnvironmentSettings().credential_env_prefixes
        )

    def export_project_package(
        self,
        project_id: str,
        *,
        trace_context: TraceContext,
    ) -> ConfigurationPackageExport:
        project = self._get_visible_project_or_raise(
            project_id,
            rejected_action="configuration_package.export.rejected",
            trace_context=trace_context,
        )
        try:
            ProviderService(
                self._session,
                audit_service=self._audit_service,
                now=self._now,
                credential_env_prefixes=self._credential_env_prefixes,
            ).seed_builtin_providers(trace_context=trace_context)
            exported_at = self._now()
            export_id = f"config-export-{uuid4().hex}"
            package = ConfigurationPackageExport(
                export_id=export_id,
                exported_at=exported_at,
                package_schema_version=PACKAGE_SCHEMA_VERSION,
                scope=ConfigurationPackageScope(
                    scope_type="project",
                    project_id=project.project_id,
                ),
                providers=[
                    self._provider_to_package(provider)
                    for provider in self._ordered_providers()
                ],
                delivery_channels=self._export_delivery_channels(project),
                pipeline_templates=[
                    self._template_to_package(template)
                    for template in self._ordered_user_templates()
                ],
            )
            metadata = self._package_metadata(
                package_id=export_id,
                project_id=project.project_id,
                providers=[item.provider_id for item in package.providers],
                delivery_channels=[
                    project.default_delivery_channel_id
                    for _item in package.delivery_channels
                    if project.default_delivery_channel_id
                ],
                pipeline_templates=[
                    item.template_id for item in package.pipeline_templates
                ],
            )
            self._record_service_log(
                payload_type="configuration_package_export",
                message="Configuration package exported.",
                metadata=metadata,
                trace_context=trace_context,
                created_at=exported_at,
            )
            self._audit_service.record_command_result(
                actor_type=AuditActorType.USER,
                actor_id=API_ACTOR_ID,
                action="configuration_package.export",
                target_type="project",
                target_id=project.project_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata=metadata,
                trace_context=trace_context,
            )
            return package
        except Exception as exc:
            self._session.rollback()
            self._record_failed_if_possible(
                action="configuration_package.export.failed",
                target_id=project_id,
                reason=str(exc) or type(exc).__name__,
                metadata={
                    "project_id": project_id,
                    "error_type": type(exc).__name__,
                },
                trace_context=trace_context,
            )
            raise

    def import_project_package(
        self,
        project_id: str,
        package: ConfigurationPackageImportRequest,
        *,
        trace_context: TraceContext,
    ) -> ConfigurationPackageImportResult:
        project = self._get_visible_project_or_raise(
            project_id,
            rejected_action="configuration_package.import.rejected",
            trace_context=trace_context,
        )
        package_id = self._package_id_for_import(package)
        scope_errors = self.validate_package_scope(project_id, package)
        if scope_errors:
            result = self._rejected_result(package_id, package, scope_errors)
            self._record_import_rejected_log(
                project_id=project.project_id,
                package_id=package_id,
                field_errors=scope_errors,
                trace_context=trace_context,
            )
            self._record_import_rejected(
                project_id=project.project_id,
                package_id=package_id,
                field_errors=scope_errors,
                trace_context=trace_context,
            )
            return result

        validation_errors = self._validate_import_payload(project, package)
        if validation_errors:
            self._session.rollback()
            result = self._rejected_result(package_id, package, validation_errors)
            self._record_import_rejected_log(
                project_id=project.project_id,
                package_id=package_id,
                field_errors=validation_errors,
                trace_context=trace_context,
            )
            self._record_import_rejected(
                project_id=project.project_id,
                package_id=package_id,
                field_errors=validation_errors,
                trace_context=trace_context,
            )
            return result

        try:
            timestamp = self._now()
            changed_objects = self._apply_validated_package(
                project,
                package,
                timestamp=timestamp,
            )
            changed_count = sum(
                1 for item in changed_objects if item.action != "unchanged"
            )
            result = ConfigurationPackageImportResult(
                package_id=package_id,
                package_schema_version=package.package_schema_version,
                summary=f"Imported {changed_count} configuration objects.",
                changed_objects=changed_objects,
                field_errors=[],
            )
            metadata = self._import_metadata(
                project_id=project.project_id,
                package_id=package_id,
                result=result,
            )
            self._record_service_log(
                payload_type="configuration_package_import",
                message="Configuration package import processed.",
                metadata=metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
            self._audit_service.record_command_result(
                actor_type=AuditActorType.USER,
                actor_id=API_ACTOR_ID,
                action="configuration_package.import",
                target_type="project",
                target_id=project.project_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata=metadata,
                trace_context=trace_context,
                created_at=timestamp,
            )
            self._session.commit()
            return result
        except Exception as exc:
            failed_audit_error: Exception | None = None
            try:
                self._audit_service.record_command_result(
                    actor_type=AuditActorType.USER,
                    actor_id=API_ACTOR_ID,
                    action="configuration_package.import.failed",
                    target_type="project",
                    target_id=project.project_id,
                    result=AuditResult.FAILED,
                    reason=str(exc) or type(exc).__name__,
                    metadata={
                        "project_id": project.project_id,
                        "package_id": package_id,
                        "error_type": type(exc).__name__,
                    },
                    trace_context=trace_context,
                )
            except Exception as audit_exc:
                failed_audit_error = audit_exc
            self._session.rollback()
            if failed_audit_error is not None:
                raise failed_audit_error from exc
            raise

    def validate_package_scope(
        self,
        project_id: str,
        package: ConfigurationPackageImportRequest,
    ) -> list[ConfigurationPackageFieldError]:
        if package.package_schema_version != PACKAGE_SCHEMA_VERSION:
            return [
                self._field_error(
                    "package_schema_version",
                    UNSUPPORTED_PACKAGE_VERSION_MESSAGE,
                )
            ]
        if package.scope.project_id != project_id:
            return [self._field_error("scope.project_id", SCOPE_MISMATCH_MESSAGE)]
        return []

    def _validate_import_payload(
        self,
        project: ProjectModel,
        package: ConfigurationPackageImportRequest,
    ) -> list[ConfigurationPackageFieldError]:
        errors: list[ConfigurationPackageFieldError] = []
        if len(package.delivery_channels) > 1:
            errors.append(
                self._field_error(
                    "delivery_channels",
                    TOO_MANY_DELIVERY_CHANNELS_MESSAGE,
                )
            )

        for index, provider in enumerate(package.providers):
            errors.extend(self._validate_provider(provider, index=index))
        for index, channel in enumerate(package.delivery_channels[:1]):
            errors.extend(self._validate_delivery_channel(project, channel, index=index))
        import_provider_ids = {
            provider.provider_id
            for provider in package.providers
            if provider.is_enabled
        }
        for index, template in enumerate(package.pipeline_templates):
            errors.extend(
                self._validate_template(
                    template,
                    index=index,
                    import_provider_ids=import_provider_ids,
                )
            )
        return errors

    def _validate_provider(
        self,
        provider: ConfigurationPackageProvider,
        *,
        index: int,
    ) -> list[ConfigurationPackageFieldError]:
        errors: list[ConfigurationPackageFieldError] = []
        existing = self._session.get(ProviderModel, provider.provider_id)
        try:
            body = self._provider_write_request(provider)
        except ValidationError as exc:
            return [self._validation_error(f"providers[{index}]", exc)]

        if provider.provider_source is ProviderSource.BUILTIN:
            if existing is None or existing.provider_source is not ProviderSource.BUILTIN:
                return [
                    self._field_error(
                        f"providers[{index}].provider_id",
                        "Built-in Provider was not found.",
                    )
                ]
            if (
                provider.display_name != existing.display_name
                or provider.protocol_type is not existing.protocol_type
            ):
                return [
                    self._field_error(
                        f"providers[{index}].provider_id",
                        BUILTIN_IDENTITY_CHANGE_MESSAGE,
                    )
                ]
        else:
            if existing is not None and existing.provider_source is not ProviderSource.CUSTOM:
                return [
                    self._field_error(
                        f"providers[{index}].provider_id",
                        BUILTIN_IDENTITY_CHANGE_MESSAGE,
                    )
                ]
            if provider.protocol_type is not ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE:
                return [
                    self._field_error(
                        f"providers[{index}].protocol_type",
                        CUSTOM_PROTOCOL_MISMATCH_MESSAGE,
                    )
                ]
            if not provider.display_name:
                return [
                    self._field_error(
                        f"providers[{index}].display_name",
                        CUSTOM_DISPLAY_NAME_REQUIRED_MESSAGE,
                    )
                ]

        errors.extend(self._validate_provider_runtime(body, index=index))
        return errors

    def _validate_provider_runtime(
        self,
        body: ProviderWriteRequest,
        *,
        index: int,
    ) -> list[ConfigurationPackageFieldError]:
        if not self._is_safe_provider_api_key_ref(body.api_key_ref):
            return [
                self._field_error(
                    f"providers[{index}].api_key_ref",
                    INVALID_PROVIDER_CREDENTIAL_REFERENCE_MESSAGE,
                )
            ]
        if body.default_model_id not in body.supported_model_ids:
            return [
                self._field_error(
                    f"providers[{index}].default_model_id",
                    INVALID_MODEL_BINDING_MESSAGE,
                )
            ]

        capability_model_ids = [
            capability.model_id for capability in body.runtime_capabilities
        ]
        duplicate_ids = sorted(
            {
                model_id
                for model_id in capability_model_ids
                if capability_model_ids.count(model_id) > 1
            }
        )
        if duplicate_ids:
            return [
                self._field_error(
                    f"providers[{index}].runtime_capabilities",
                    DUPLICATE_MODEL_CAPABILITY_MESSAGE,
                )
            ]
        capability_id_set = set(capability_model_ids)
        supported_id_set = set(body.supported_model_ids)
        if supported_id_set - capability_id_set:
            return [
                self._field_error(
                    f"providers[{index}].runtime_capabilities",
                    MISSING_MODEL_CAPABILITY_MESSAGE,
                )
            ]
        if capability_id_set - supported_id_set:
            return [
                self._field_error(
                    f"providers[{index}].runtime_capabilities",
                    EXTRA_MODEL_CAPABILITY_MESSAGE,
                )
            ]
        return []

    def _validate_delivery_channel(
        self,
        project: ProjectModel,
        channel: ConfigurationPackageDeliveryChannel,
        *,
        index: int,
    ) -> list[ConfigurationPackageFieldError]:
        if project.default_delivery_channel_id is None:
            return [
                self._field_error(
                    f"delivery_channels[{index}]",
                    "Project default DeliveryChannel was not found.",
                )
            ]
        existing = self._session.get(
            DeliveryChannelModel,
            project.default_delivery_channel_id,
        )
        if existing is None or existing.project_id != project.project_id:
            return [
                self._field_error(
                    f"delivery_channels[{index}]",
                    "Project default DeliveryChannel was not found.",
                )
            ]
        try:
            body = self._delivery_update_request(channel)
        except ValidationError as exc:
            return [self._validation_error(f"delivery_channels[{index}]", exc)]

        if body.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY:
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
                return [
                    self._field_error(
                        f"delivery_channels[{index}].{missing_fields[0]}",
                        f"{GIT_REQUIRED_MESSAGE_PREFIX}{', '.join(sorted(missing_fields))}",
                    )
                ]
            if not self._is_safe_delivery_credential_ref(body.credential_ref):
                return [
                    self._field_error(
                        f"delivery_channels[{index}].credential_ref",
                        INVALID_DELIVERY_CREDENTIAL_REFERENCE_MESSAGE,
                    )
                ]
        return []

    def _validate_template(
        self,
        template: ConfigurationPackageTemplateConfig,
        *,
        index: int,
        import_provider_ids: set[str],
    ) -> list[ConfigurationPackageFieldError]:
        if template.template_source is TemplateSource.SYSTEM_TEMPLATE:
            return [
                self._field_error(
                    f"pipeline_templates[{index}].template_source",
                    SYSTEM_TEMPLATE_IMPORT_MESSAGE,
                )
            ]
        existing = self._session.get(PipelineTemplateModel, template.template_id)
        if existing is not None and existing.template_source is TemplateSource.SYSTEM_TEMPLATE:
            return [
                self._field_error(
                    f"pipeline_templates[{index}].template_source",
                    SYSTEM_TEMPLATE_IMPORT_MESSAGE,
                )
            ]
        try:
            body = self._template_write_request(template)
        except ValidationError as exc:
            return [self._validation_error(f"pipeline_templates[{index}]", exc)]

        template_service = TemplateService(
            self._session,
            audit_service=self._audit_service,
            now=self._now,
        )
        try:
            bindings = template_service.validate_editable_fields(body)
            template_service.validate_template_prompts_before_save(bindings)
        except Exception:
            return [
                self._field_error(
                    f"pipeline_templates[{index}].stage_role_bindings",
                    INVALID_TEMPLATE_MESSAGE,
                )
            ]

        provider_ids = {binding["provider_id"] for binding in bindings}
        existing_provider_ids = {
            provider_id
            for (provider_id,) in self._session.query(ProviderModel.provider_id)
            .filter(ProviderModel.provider_id.in_(provider_ids))
            .filter(ProviderModel.is_configured.is_(True))
            .filter(ProviderModel.is_enabled.is_(True))
            .all()
        }
        missing_provider_ids = provider_ids - existing_provider_ids - import_provider_ids
        if missing_provider_ids:
            return [
                self._field_error(
                    f"pipeline_templates[{index}].stage_role_bindings",
                    UNKNOWN_PROVIDER_MESSAGE,
                )
            ]
        return []

    def _apply_validated_package(
        self,
        project: ProjectModel,
        package: ConfigurationPackageImportRequest,
        *,
        timestamp: datetime,
    ) -> list[ConfigurationPackageChangedObject]:
        changed_objects: list[ConfigurationPackageChangedObject] = []
        provider_id_map: dict[str, str] = {}
        for provider in package.providers:
            changed_object = self._apply_provider(
                provider,
                timestamp=timestamp,
                provider_id_map=provider_id_map,
            )
            changed_objects.append(changed_object)
        for channel in package.delivery_channels:
            changed_objects.append(
                self._apply_delivery_channel(project, channel, timestamp=timestamp)
            )
        for template in package.pipeline_templates:
            changed_objects.append(
                self._apply_template(
                    template,
                    timestamp=timestamp,
                    provider_id_map=provider_id_map,
                )
            )
        self._session.flush()
        return changed_objects

    def _apply_provider(
        self,
        provider: ConfigurationPackageProvider,
        *,
        timestamp: datetime,
        provider_id_map: dict[str, str],
    ) -> ConfigurationPackageChangedObject:
        existing = self._session.get(ProviderModel, provider.provider_id)
        body = self._provider_write_request(provider)
        payload = {
            "base_url": body.base_url,
            "api_key_ref": body.api_key_ref,
            "default_model_id": body.default_model_id,
            "supported_model_ids": list(body.supported_model_ids),
            "is_enabled": body.is_enabled,
            "runtime_capabilities": ProviderService.apply_model_capability_defaults(
                [
                    capability.model_dump(mode="python", exclude_none=True)
                    for capability in body.runtime_capabilities
                ]
            ),
        }

        if existing is None:
            saved = ProviderModel(
                provider_id=provider.provider_id,
                display_name=provider.display_name,
                provider_source=ProviderSource.CUSTOM,
                protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
                is_configured=True,
                created_at=timestamp,
                updated_at=timestamp,
                **payload,
            )
            self._session.add(saved)
            provider_id_map[provider.provider_id] = saved.provider_id
            return self._changed_object(
                object_type="provider",
                object_id=saved.provider_id,
                action="created",
                config_version=timestamp,
            )

        unchanged = (
            existing.display_name == provider.display_name
            and existing.base_url == payload["base_url"]
            and existing.api_key_ref == payload["api_key_ref"]
            and existing.default_model_id == payload["default_model_id"]
            and existing.supported_model_ids == payload["supported_model_ids"]
            and existing.is_configured is True
            and existing.is_enabled == payload["is_enabled"]
            and existing.runtime_capabilities == payload["runtime_capabilities"]
        )
        provider_id_map[provider.provider_id] = existing.provider_id
        if not unchanged:
            if existing.provider_source is ProviderSource.CUSTOM:
                existing.display_name = provider.display_name
            existing.base_url = payload["base_url"]
            existing.api_key_ref = payload["api_key_ref"]
            existing.default_model_id = payload["default_model_id"]
            existing.supported_model_ids = payload["supported_model_ids"]
            existing.is_configured = True
            existing.is_enabled = payload["is_enabled"]
            existing.runtime_capabilities = payload["runtime_capabilities"]
            existing.updated_at = timestamp
            self._session.add(existing)
        return self._changed_object(
            object_type="provider",
            object_id=existing.provider_id,
            action="unchanged" if unchanged else "updated",
            config_version=existing.updated_at if unchanged else timestamp,
        )

    def _apply_delivery_channel(
        self,
        project: ProjectModel,
        channel: ConfigurationPackageDeliveryChannel,
        *,
        timestamp: datetime,
    ) -> ConfigurationPackageChangedObject:
        assert project.default_delivery_channel_id is not None
        existing = self._session.get(
            DeliveryChannelModel,
            project.default_delivery_channel_id,
        )
        if existing is None:
            raise RuntimeError("Project default DeliveryChannel was not found.")
        body = self._delivery_update_request(channel)
        desired = self._delivery_payload(body)
        unchanged = all(getattr(existing, key) == value for key, value in desired.items())
        if not unchanged:
            for key, value in desired.items():
                setattr(existing, key, value)
            existing.updated_at = timestamp
            self._session.add(existing)
        return self._changed_object(
            object_type="delivery_channel",
            object_id=existing.delivery_channel_id,
            action="unchanged" if unchanged else "updated",
            config_version=existing.updated_at if unchanged else timestamp,
        )

    def _apply_template(
        self,
        template: ConfigurationPackageTemplateConfig,
        *,
        timestamp: datetime,
        provider_id_map: dict[str, str],
    ) -> ConfigurationPackageChangedObject:
        existing = self._session.get(PipelineTemplateModel, template.template_id)
        body = self._template_write_request(template)
        bindings = TemplateService(
            self._session,
            audit_service=self._audit_service,
            now=self._now,
        ).validate_editable_fields(body)
        bindings = [
            {
                **binding,
                "provider_id": provider_id_map.get(
                    binding["provider_id"],
                    binding["provider_id"],
                ),
            }
            for binding in bindings
        ]
        payload = {
            "name": body.name,
            "description": body.description,
            "fixed_stage_sequence": [stage.value for stage in FIXED_STAGE_SEQUENCE],
            "stage_role_bindings": bindings,
            "approval_checkpoints": [
                checkpoint.value for checkpoint in FIXED_APPROVAL_CHECKPOINTS
            ],
            "auto_regression_enabled": body.auto_regression_enabled,
            "max_auto_regression_retries": body.max_auto_regression_retries,
        }
        if existing is None:
            saved = PipelineTemplateModel(
                template_id=template.template_id,
                template_source=TemplateSource.USER_TEMPLATE,
                base_template_id=None,
                created_at=timestamp,
                updated_at=timestamp,
                **payload,
            )
            self._session.add(saved)
            return self._changed_object(
                object_type="pipeline_template",
                object_id=saved.template_id,
                action="created",
                config_version=timestamp,
            )

        unchanged = all(getattr(existing, key) == value for key, value in payload.items())
        if not unchanged:
            for key, value in payload.items():
                setattr(existing, key, value)
            existing.updated_at = timestamp
            self._session.add(existing)
        return self._changed_object(
            object_type="pipeline_template",
            object_id=existing.template_id,
            action="unchanged" if unchanged else "updated",
            config_version=existing.updated_at if unchanged else timestamp,
        )

    def _provider_to_package(self, provider: ProviderModel) -> ConfigurationPackageProvider:
        return ConfigurationPackageProvider(
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            provider_source=provider.provider_source,
            protocol_type=provider.protocol_type,
            base_url=provider.base_url,
            api_key_ref=self._api_key_ref_for_export(provider.api_key_ref),
            default_model_id=provider.default_model_id,
            supported_model_ids=list(provider.supported_model_ids),
            is_enabled=provider.is_enabled,
            runtime_capabilities=[
                ConfigurationPackageModelRuntimeCapabilities.model_validate(item)
                for item in provider.runtime_capabilities
            ],
        )

    def _template_to_package(
        self,
        template: PipelineTemplateModel,
    ) -> ConfigurationPackageTemplateConfig:
        return ConfigurationPackageTemplateConfig(
            template_id=template.template_id,
            name=template.name,
            template_source=template.template_source,
            stage_role_bindings=[
                ConfigurationPackageTemplateSlotConfig.model_validate(binding)
                for binding in template.stage_role_bindings
            ],
            auto_regression_enabled=template.auto_regression_enabled,
            max_auto_regression_retries=template.max_auto_regression_retries,
        )

    def _export_delivery_channels(
        self,
        project: ProjectModel,
    ) -> list[ConfigurationPackageDeliveryChannel]:
        if not project.default_delivery_channel_id:
            return []
        channel = self._session.get(
            DeliveryChannelModel,
            project.default_delivery_channel_id,
        )
        if channel is None or channel.project_id != project.project_id:
            return []
        delivery_service = DeliveryChannelService(
            self._session,
            credential_env_prefixes=self._credential_env_prefixes,
        )
        return [
            ConfigurationPackageDeliveryChannel(
                delivery_mode=channel.delivery_mode,
                scm_provider_type=channel.scm_provider_type,
                repository_identifier=channel.repository_identifier,
                default_branch=channel.default_branch,
                code_review_request_type=channel.code_review_request_type,
                credential_ref=delivery_service.credential_ref_for_projection(
                    channel.credential_ref,
                ),
            )
        ]

    def _ordered_providers(self) -> list[ProviderModel]:
        providers = (
            self._session.query(ProviderModel)
            .filter(ProviderModel.is_configured.is_(True))
            .all()
        )
        by_id = {provider.provider_id: provider for provider in providers}
        builtins = [
            by_id[provider_id]
            for provider_id in BUILTIN_PROVIDER_IDS
            if provider_id in by_id
        ]
        seed_order = {seed["provider_id"]: index for index, seed in enumerate(BUILTIN_PROVIDER_SEEDS)}
        builtins.sort(key=lambda provider: seed_order.get(provider.provider_id, 999))
        customs = sorted(
            [
                provider
                for provider in providers
                if provider.provider_id not in BUILTIN_PROVIDER_IDS
            ],
            key=lambda provider: (provider.created_at, provider.provider_id),
        )
        return [*builtins, *customs]

    def _ordered_user_templates(self) -> list[PipelineTemplateModel]:
        return (
            self._session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_source == TemplateSource.USER_TEMPLATE)
            .order_by(
                PipelineTemplateModel.created_at.asc(),
                PipelineTemplateModel.template_id.asc(),
            )
            .all()
        )

    def _get_visible_project_or_raise(
        self,
        project_id: str,
        *,
        rejected_action: str,
        trace_context: TraceContext,
    ) -> ProjectModel:
        project = self._session.get(ProjectModel, project_id)
        if project is not None and project.is_visible:
            return project
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action=rejected_action,
            target_type="project",
            target_id=project_id,
            reason=PROJECT_NOT_FOUND_MESSAGE,
            metadata={"project_id": project_id},
            trace_context=trace_context,
        )
        raise ConfigurationPackageServiceError(
            ErrorCode.NOT_FOUND,
            PROJECT_NOT_FOUND_MESSAGE,
            404,
        )

    def _record_import_rejected(
        self,
        *,
        project_id: str,
        package_id: str,
        field_errors: list[ConfigurationPackageFieldError],
        trace_context: TraceContext,
    ) -> None:
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action="configuration_package.import.rejected",
            target_type="project",
            target_id=project_id,
            reason="Configuration package import was rejected.",
            metadata={
                "project_id": project_id,
                "package_id": package_id,
                "field_errors": [
                    {"field": error.field, "message": error.message}
                    for error in field_errors
                ],
            },
            trace_context=trace_context,
        )

    def _record_import_rejected_log(
        self,
        *,
        project_id: str,
        package_id: str,
        field_errors: list[ConfigurationPackageFieldError],
        trace_context: TraceContext,
    ) -> None:
        self._record_service_log(
            payload_type="configuration_package_import",
            message="Configuration package import processed.",
            metadata={
                "package_id": package_id,
                "project_id": project_id,
                "changed_objects": [],
                "field_error_fields": [error.field for error in field_errors],
                "changed_count": 0,
                "result": AuditResult.REJECTED.value,
            },
            trace_context=trace_context,
            created_at=self._now(),
        )

    def _record_failed_if_possible(
        self,
        *,
        action: str,
        target_id: str,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        try:
            self._audit_service.record_command_result(
                actor_type=AuditActorType.USER,
                actor_id=API_ACTOR_ID,
                action=action,
                target_type="project",
                target_id=target_id,
                result=AuditResult.FAILED,
                reason=reason,
                metadata=metadata,
                trace_context=trace_context,
            )
        except Exception:
            pass

    def _record_service_log(
        self,
        *,
        payload_type: str,
        message: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
        created_at: datetime,
    ) -> None:
        redacted = self._redaction_policy.summarize_payload(
            metadata,
            payload_type=payload_type,
        )
        self._log_writer.write(
            LogRecordInput(
                source="services.configuration_packages",
                category=LogCategory.API,
                level=LogLevel.INFO,
                message=message,
                trace_context=trace_context,
                payload=LogPayloadSummary.from_redacted_payload(
                    payload_type,
                    redacted,
                ),
                created_at=created_at,
            )
        )

    def _provider_write_request(
        self,
        provider: ConfigurationPackageProvider,
    ) -> ProviderWriteRequest:
        return ProviderWriteRequest(
            display_name=provider.display_name,
            protocol_type=provider.protocol_type,
            base_url=provider.base_url,
            api_key_ref=provider.api_key_ref,
            default_model_id=provider.default_model_id,
            supported_model_ids=list(provider.supported_model_ids),
            is_enabled=provider.is_enabled,
            runtime_capabilities=[
                capability.model_dump(mode="python", exclude_none=True)
                for capability in provider.runtime_capabilities
            ],
        )

    def _delivery_update_request(
        self,
        channel: ConfigurationPackageDeliveryChannel,
    ) -> ProjectDeliveryChannelUpdateRequest:
        return ProjectDeliveryChannelUpdateRequest(
            delivery_mode=channel.delivery_mode,
            scm_provider_type=channel.scm_provider_type,
            repository_identifier=channel.repository_identifier,
            default_branch=channel.default_branch,
            code_review_request_type=channel.code_review_request_type,
            credential_ref=channel.credential_ref,
        )

    def _template_write_request(
        self,
        template: ConfigurationPackageTemplateConfig,
    ) -> PipelineTemplateWriteRequest:
        return PipelineTemplateWriteRequest(
            name=template.name,
            description=None,
            fixed_stage_sequence=list(FIXED_STAGE_SEQUENCE),
            stage_role_bindings=[
                binding.model_dump(mode="python")
                for binding in template.stage_role_bindings
            ],
            approval_checkpoints=list(FIXED_APPROVAL_CHECKPOINTS),
            auto_regression_enabled=template.auto_regression_enabled,
            max_auto_regression_retries=template.max_auto_regression_retries,
        )

    def _delivery_payload(
        self,
        body: ProjectDeliveryChannelUpdateRequest,
    ) -> dict[str, Any]:
        if body.delivery_mode is DeliveryMode.DEMO_DELIVERY:
            return {
                "delivery_mode": DeliveryMode.DEMO_DELIVERY,
                "scm_provider_type": None,
                "repository_identifier": None,
                "default_branch": None,
                "code_review_request_type": None,
                "credential_ref": None,
                "credential_status": CredentialStatus.READY,
                "readiness_status": DeliveryReadinessStatus.READY,
                "readiness_message": None,
                "last_validated_at": None,
            }
        return {
            "delivery_mode": DeliveryMode.GIT_AUTO_DELIVERY,
            "scm_provider_type": body.scm_provider_type,
            "repository_identifier": self._required_string(body.repository_identifier),
            "default_branch": self._required_string(body.default_branch),
            "code_review_request_type": body.code_review_request_type,
            "credential_ref": body.credential_ref,
            "credential_status": CredentialStatus.UNBOUND,
            "readiness_status": DeliveryReadinessStatus.UNCONFIGURED,
            "readiness_message": UNVALIDATED_READINESS_MESSAGE,
            "last_validated_at": None,
        }

    def _package_metadata(
        self,
        *,
        package_id: str,
        project_id: str,
        providers: list[str],
        delivery_channels: list[str],
        pipeline_templates: list[str],
    ) -> dict[str, Any]:
        return {
            "package_id": package_id,
            "project_id": project_id,
            "provider_ids": providers,
            "delivery_channel_ids": delivery_channels,
            "pipeline_template_ids": pipeline_templates,
            "counts": {
                "providers": len(providers),
                "delivery_channels": len(delivery_channels),
                "pipeline_templates": len(pipeline_templates),
            },
        }

    def _import_metadata(
        self,
        *,
        project_id: str,
        package_id: str,
        result: ConfigurationPackageImportResult,
    ) -> dict[str, Any]:
        return {
            "package_id": package_id,
            "project_id": project_id,
            "changed_objects": [
                item.model_dump(mode="json") for item in result.changed_objects
            ],
            "field_error_fields": [error.field for error in result.field_errors],
            "changed_count": sum(
                1 for item in result.changed_objects if item.action != "unchanged"
            ),
        }

    def _package_id_for_import(
        self,
        package: ConfigurationPackageImportRequest,
    ) -> str:
        del package
        return f"config-import-{uuid4().hex}"

    def _field_error(
        self,
        field: str,
        message: str,
    ) -> ConfigurationPackageFieldError:
        return ConfigurationPackageFieldError(field=field, message=message)

    def _validation_error(
        self,
        prefix: str,
        exc: ValidationError,
    ) -> ConfigurationPackageFieldError:
        first_error = exc.errors()[0]
        location = ".".join(str(part) for part in first_error.get("loc", ()))
        field = f"{prefix}.{location}" if location else prefix
        return self._field_error(field, str(first_error.get("msg", "Invalid value.")))

    def _rejected_result(
        self,
        package_id: str,
        package: ConfigurationPackageImportRequest,
        field_errors: list[ConfigurationPackageFieldError],
    ) -> ConfigurationPackageImportResult:
        return ConfigurationPackageImportResult(
            package_id=package_id,
            package_schema_version=package.package_schema_version,
            summary="Configuration package import was rejected.",
            changed_objects=[],
            field_errors=field_errors,
        )

    def _changed_object(
        self,
        *,
        object_type: str,
        object_id: str,
        action: str,
        config_version: datetime,
    ) -> ConfigurationPackageChangedObject:
        return ConfigurationPackageChangedObject(
            object_type=object_type,  # type: ignore[arg-type]
            object_id=object_id,
            action=action,  # type: ignore[arg-type]
            config_version=self._version(config_version),
        )

    @staticmethod
    def _version(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()

    @staticmethod
    def _is_blank(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return False

    def _is_safe_provider_api_key_ref(self, value: str | None) -> bool:
        if value is None:
            return True
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

    def _api_key_ref_for_export(self, value: str | None) -> str | None:
        if value is None:
            return None
        if self._is_safe_provider_api_key_ref(value):
            return value
        return BLOCKED_API_KEY_REF

    def _is_safe_delivery_credential_ref(self, value: str | None) -> bool:
        if value is None:
            return False
        if value == BLOCKED_CREDENTIAL_REF:
            return False
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
    def _required_string(value: str | None) -> str:
        if value is None:
            raise AssertionError("ProjectDeliveryChannelUpdateRequest was not validated.")
        stripped = value.strip()
        if not stripped:
            raise AssertionError("ProjectDeliveryChannelUpdateRequest was not validated.")
        return stripped


__all__ = [
    "API_ACTOR_ID",
    "PACKAGE_SCHEMA_VERSION",
    "PROJECT_NOT_FOUND_MESSAGE",
    "SCOPE_MISMATCH_MESSAGE",
    "SYSTEM_TEMPLATE_IMPORT_MESSAGE",
    "TOO_MANY_DELIVERY_CHANNELS_MESSAGE",
    "UNSUPPORTED_PACKAGE_VERSION_MESSAGE",
    "ConfigurationPackageService",
    "ConfigurationPackageServiceError",
]
