from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import (
    PipelineTemplateModel,
    PlatformRuntimeSettingsModel,
    ProviderModel,
    SessionModel,
)
from backend.app.domain.enums import SessionStatus, StageType, TemplateSource
from backend.app.domain.trace_context import TraceContext
from backend.app.prompts.definitions import expected_source_ref
from backend.app.runtime.prompt_validation import (
    PromptValidationError,
    PromptValidationService,
)
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptAssetRead,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptSectionRead,
    PromptType,
)
from backend.app.schemas.template import (
    FIXED_APPROVAL_CHECKPOINTS,
    FIXED_STAGE_SEQUENCE,
    PipelineTemplateWriteRequest,
)
from backend.app.services.providers import ProviderService
from backend.app.services.runtime_settings import (
    PlatformRuntimeSettingsService,
)


ROLE_ASSET_DIR = Path(__file__).resolve().parents[1] / "prompts" / "assets" / "roles"
SYSTEM_TEMPLATE_IDS = ("template-bugfix", "template-feature", "template-refactor")
DEFAULT_TEMPLATE_ID = "template-feature"
SEED_ACTOR_ID = "control-plane-seed"
API_ACTOR_ID = "api-user"

TEMPLATE_NOT_FOUND_MESSAGE = "Pipeline template was not found."
INVALID_TEMPLATE_MESSAGE = "Pipeline template contains invalid editable fields."
UNKNOWN_PROVIDER_MESSAGE = "Pipeline template references an unknown Provider."
PATCH_SYSTEM_TEMPLATE_MESSAGE = "System templates cannot be overwritten."
DELETE_SYSTEM_TEMPLATE_MESSAGE = "System templates cannot be deleted."
DELETE_STARTED_SESSION_MESSAGE = (
    "Pipeline template is selected by a Session that has already started."
)
DELETE_BASE_TEMPLATE_MESSAGE = (
    "Pipeline template is used as a base template by another template."
)

ROLE_ASSET_FILES = {
    "role-requirement-analyst": "requirement_analyst.md",
    "role-solution-designer": "solution_designer.md",
    "role-code-generator": "code_generator.md",
    "role-test-runner": "test_runner.md",
    "role-code-reviewer": "code_reviewer.md",
}

STAGE_ROLE_IDS = {
    StageType.REQUIREMENT_ANALYSIS: "role-requirement-analyst",
    StageType.SOLUTION_DESIGN: "role-solution-designer",
    StageType.CODE_GENERATION: "role-code-generator",
    StageType.TEST_GENERATION_EXECUTION: "role-test-runner",
    StageType.CODE_REVIEW: "role-code-reviewer",
    StageType.DELIVERY_INTEGRATION: "role-code-reviewer",
}

ROLE_STAGE_TYPES = {
    "role-requirement-analyst": [StageType.REQUIREMENT_ANALYSIS],
    "role-solution-designer": [StageType.SOLUTION_DESIGN],
    "role-code-generator": [StageType.CODE_GENERATION],
    "role-test-runner": [StageType.TEST_GENERATION_EXECUTION],
    "role-code-reviewer": [
        StageType.CODE_REVIEW,
        StageType.DELIVERY_INTEGRATION,
    ],
}

TEMPLATE_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "template_id": "template-bugfix",
        "name": "Bug 修复流程",
        "description": None,
        "provider_by_stage": {
            StageType.REQUIREMENT_ANALYSIS: "provider-deepseek",
            StageType.SOLUTION_DESIGN: "provider-deepseek",
            StageType.CODE_GENERATION: "provider-volcengine",
            StageType.TEST_GENERATION_EXECUTION: "provider-volcengine",
            StageType.CODE_REVIEW: "provider-deepseek",
            StageType.DELIVERY_INTEGRATION: "provider-deepseek",
        },
        "auto_regression_enabled": True,
        "max_auto_regression_retries": 2,
    },
    {
        "template_id": "template-feature",
        "name": "新功能开发流程",
        "description": None,
        "provider_by_stage": {
            StageType.REQUIREMENT_ANALYSIS: "provider-deepseek",
            StageType.SOLUTION_DESIGN: "provider-deepseek",
            StageType.CODE_GENERATION: "provider-volcengine",
            StageType.TEST_GENERATION_EXECUTION: "provider-volcengine",
            StageType.CODE_REVIEW: "provider-deepseek",
            StageType.DELIVERY_INTEGRATION: "provider-deepseek",
        },
        "auto_regression_enabled": True,
        "max_auto_regression_retries": 1,
    },
    {
        "template_id": "template-refactor",
        "name": "重构流程",
        "description": None,
        "provider_by_stage": {
            StageType.REQUIREMENT_ANALYSIS: "provider-deepseek",
            StageType.SOLUTION_DESIGN: "provider-deepseek",
            StageType.CODE_GENERATION: "provider-volcengine",
            StageType.TEST_GENERATION_EXECUTION: "provider-volcengine",
            StageType.CODE_REVIEW: "provider-deepseek",
            StageType.DELIVERY_INTEGRATION: "provider-deepseek",
        },
        "auto_regression_enabled": True,
        "max_auto_regression_retries": 2,
    },
)


@dataclass(frozen=True)
class AgentRoleSeed:
    role_id: str
    role_name: str
    asset: PromptAssetRead


class TemplateServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int = 422,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def parse_front_matter(markdown: str) -> tuple[dict[str, str], str]:
    normalized = markdown.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("Prompt asset is missing YAML front matter.")
    closing_index = normalized.find("\n---\n", len("---\n"))
    if closing_index == -1:
        raise ValueError("Prompt asset front matter is not closed.")
    front_matter_text = normalized[len("---\n") : closing_index]
    body = normalized[closing_index + len("\n---\n") :].strip()
    metadata: dict[str, str] = {}
    for raw_line in front_matter_text.splitlines():
        if not raw_line.strip():
            continue
        key, separator, value = raw_line.partition(":")
        if separator != ":":
            raise ValueError(f"Invalid front matter line: {raw_line}")
        metadata[key.strip()] = value.strip().strip('"')
    return metadata, body


def build_agent_role_seed_asset(
    *,
    markdown: str,
    source_file_name: str,
    applies_to_stage_types: Iterable[StageType],
) -> PromptAssetRead:
    metadata, body = parse_front_matter(markdown)
    expected_ref = expected_source_ref(
        ROLE_ASSET_DIR.parent,
        ROLE_ASSET_DIR / source_file_name,
    )
    if metadata["source_ref"] != expected_ref:
        raise ValueError("Agent role seed source_ref does not match asset path.")
    return PromptAssetRead(
        prompt_id=metadata["prompt_id"],
        prompt_version=metadata["prompt_version"],
        prompt_type=PromptType(metadata["prompt_type"]),
        authority_level=PromptAuthorityLevel(metadata["authority_level"]),
        model_call_type=ModelCallType(metadata["model_call_type"]),
        cache_scope=PromptCacheScope(metadata["cache_scope"]),
        source_ref=metadata["source_ref"],
        content_hash=PromptAssetRead.calculate_content_hash(markdown),
        sections=[
            PromptSectionRead(
                section_id=metadata["role_id"],
                title=metadata["role_name"],
                body=body,
                cache_scope=PromptCacheScope(metadata["cache_scope"]),
            )
        ],
        applies_to_stage_types=list(applies_to_stage_types),
    )


def load_agent_role_seed_asset(path: Path) -> PromptAssetRead:
    role_id = _role_id_for_file_name(path.name)
    return build_agent_role_seed_asset(
        markdown=path.read_text(encoding="utf-8"),
        source_file_name=path.name,
        applies_to_stage_types=ROLE_STAGE_TYPES[role_id],
    )


def load_default_agent_role_seed_assets() -> dict[str, PromptAssetRead]:
    return {
        role_id: load_agent_role_seed_asset(ROLE_ASSET_DIR / file_name)
        for role_id, file_name in ROLE_ASSET_FILES.items()
    }


def resolve_default_agent_role_prompt(role_id: str) -> str:
    assets = load_default_agent_role_seed_assets()
    return assets[role_id].sections[0].body


def _role_id_for_file_name(file_name: str) -> str:
    for role_id, candidate in ROLE_ASSET_FILES.items():
        if candidate == file_name:
            return role_id
    raise ValueError(f"Unknown role asset file: {file_name}")


class TemplateService:
    def __init__(
        self,
        session: Session,
        *,
        audit_service: Any,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._audit_service = audit_service
        self._now = now or (lambda: datetime.now(UTC))

    def resolve_default_agent_role_prompt(self, role_id: str) -> str:
        return resolve_default_agent_role_prompt(role_id)

    def seed_system_templates(
        self,
        *,
        trace_context: TraceContext,
    ) -> list[PipelineTemplateModel]:
        existing_ids = {
            template_id
            for (template_id,) in self._session.query(PipelineTemplateModel.template_id)
            .filter(PipelineTemplateModel.template_id.in_(SYSTEM_TEMPLATE_IDS))
            .all()
        }
        missing_seeds = [
            seed for seed in TEMPLATE_SEEDS if seed["template_id"] not in existing_ids
        ]
        if not missing_seeds:
            return self._ordered_system_templates()

        assets = load_default_agent_role_seed_assets()
        timestamp = self._now()
        created: list[PipelineTemplateModel] = []
        for seed in missing_seeds:
            template = PipelineTemplateModel(
                template_id=seed["template_id"],
                name=seed["name"],
                description=seed["description"],
                template_source=TemplateSource.SYSTEM_TEMPLATE,
                base_template_id=None,
                fixed_stage_sequence=[stage.value for stage in FIXED_STAGE_SEQUENCE],
                stage_role_bindings=_stage_role_bindings(
                    assets=assets,
                    provider_by_stage=seed["provider_by_stage"],
                ),
                approval_checkpoints=[
                    checkpoint.value for checkpoint in FIXED_APPROVAL_CHECKPOINTS
                ],
                auto_regression_enabled=seed["auto_regression_enabled"],
                max_auto_regression_retries=seed["max_auto_regression_retries"],
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._session.add(template)
            self._session.flush()
            created.append(template)

        if created:
            try:
                self._record_seed_audit(
                    templates=created,
                    trace_context=trace_context,
                )
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise

        return self._ordered_system_templates()

    def list_templates(
        self,
        *,
        trace_context: TraceContext,
    ) -> list[PipelineTemplateModel]:
        system_templates = self.seed_system_templates(trace_context=trace_context)
        user_templates = (
            self._session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_source == TemplateSource.USER_TEMPLATE)
            .order_by(
                PipelineTemplateModel.created_at.asc(),
                PipelineTemplateModel.template_id.asc(),
            )
            .all()
        )
        return [*system_templates, *user_templates]

    def get_default_template(
        self,
        *,
        trace_context: TraceContext,
    ) -> PipelineTemplateModel:
        template = self.get_template(
            DEFAULT_TEMPLATE_ID,
            trace_context=trace_context,
        )
        if template is None:
            raise RuntimeError("Default pipeline template seed was not created.")
        return template

    def get_template(
        self,
        template_id: str,
        *,
        trace_context: TraceContext,
    ) -> PipelineTemplateModel | None:
        self.seed_system_templates(trace_context=trace_context)
        return self._session.get(PipelineTemplateModel, template_id)

    def save_as_user_template(
        self,
        *,
        source_template_id: str | None,
        body: PipelineTemplateWriteRequest,
        trace_context: TraceContext,
    ) -> PipelineTemplateModel:
        source_template = None
        if source_template_id is not None:
            source_template = self.get_template(
                source_template_id,
                trace_context=trace_context,
            )
            if source_template is None:
                self._record_rejected(
                    action="template.save_as.rejected",
                    target_id=source_template_id,
                    reason=TEMPLATE_NOT_FOUND_MESSAGE,
                    metadata={
                        "source_template_id": source_template_id,
                    },
                    trace_context=trace_context,
                )
                raise TemplateServiceError(
                    ErrorCode.NOT_FOUND,
                    TEMPLATE_NOT_FOUND_MESSAGE,
                    404,
                )
        else:
            self.seed_system_templates(trace_context=trace_context)

        try:
            bindings = self._validated_bindings(body, trace_context=trace_context)
        except TemplateServiceError as exc:
            self._record_rejected(
                action="template.save_as.rejected",
                target_id=source_template_id or "new-user-template",
                reason=exc.message,
                metadata={
                    "source_template_id": source_template_id,
                    "error_code": exc.error_code.value,
                },
                trace_context=trace_context,
            )
            raise

        timestamp = self._now()
        template = PipelineTemplateModel(
            template_id=f"template-user-{uuid4().hex}",
            name=body.name,
            description=body.description,
            template_source=TemplateSource.USER_TEMPLATE,
            base_template_id=source_template.template_id if source_template else None,
            fixed_stage_sequence=[stage.value for stage in body.fixed_stage_sequence],
            stage_role_bindings=bindings,
            approval_checkpoints=[
                checkpoint.value for checkpoint in body.approval_checkpoints
            ],
            auto_regression_enabled=body.auto_regression_enabled,
            max_auto_regression_retries=body.max_auto_regression_retries,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._session.add(template)
        self._session.flush()
        try:
            self._record_success(
                action="template.save_as",
                template=template,
                trace_context=trace_context,
                metadata=self._template_audit_metadata(
                    template,
                    source_template_id=source_template_id,
                ),
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return template

    def patch_user_template(
        self,
        *,
        template_id: str,
        body: PipelineTemplateWriteRequest,
        trace_context: TraceContext,
    ) -> PipelineTemplateModel:
        template = self.get_template(template_id, trace_context=trace_context)
        if template is None:
            self._record_rejected(
                action="template.patch.rejected",
                target_id=template_id,
                reason=TEMPLATE_NOT_FOUND_MESSAGE,
                metadata={
                    "template_id": template_id,
                },
                trace_context=trace_context,
            )
            raise TemplateServiceError(ErrorCode.NOT_FOUND, TEMPLATE_NOT_FOUND_MESSAGE, 404)
        if template.template_source is TemplateSource.SYSTEM_TEMPLATE:
            self._record_rejected(
                action="template.patch.rejected",
                target_id=template_id,
                reason=PATCH_SYSTEM_TEMPLATE_MESSAGE,
                metadata={
                    "template_id": template_id,
                    "template_source": template.template_source.value,
                },
                trace_context=trace_context,
            )
            raise TemplateServiceError(
                ErrorCode.VALIDATION_ERROR,
                PATCH_SYSTEM_TEMPLATE_MESSAGE,
                409,
            )

        try:
            bindings = self._validated_bindings(body, trace_context=trace_context)
        except TemplateServiceError as exc:
            self._record_rejected(
                action="template.patch.rejected",
                target_id=template_id,
                reason=exc.message,
                metadata={
                    "template_id": template_id,
                    "error_code": exc.error_code.value,
                },
                trace_context=trace_context,
            )
            raise

        template.name = body.name
        template.description = body.description
        template.fixed_stage_sequence = [stage.value for stage in body.fixed_stage_sequence]
        template.stage_role_bindings = bindings
        template.approval_checkpoints = [
            checkpoint.value for checkpoint in body.approval_checkpoints
        ]
        template.auto_regression_enabled = body.auto_regression_enabled
        template.max_auto_regression_retries = body.max_auto_regression_retries
        template.updated_at = self._now()
        self._session.add(template)
        self._session.flush()
        try:
            self._record_success(
                action="template.patch",
                template=template,
                trace_context=trace_context,
                metadata=self._template_audit_metadata(
                    template,
                    source_template_id=None,
                ),
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return template

    def delete_user_template(
        self,
        *,
        template_id: str,
        trace_context: TraceContext,
    ) -> None:
        template = self.get_template(template_id, trace_context=trace_context)
        if template is None:
            self._record_rejected(
                action="template.delete.rejected",
                target_id=template_id,
                reason=TEMPLATE_NOT_FOUND_MESSAGE,
                metadata={
                    "template_id": template_id,
                },
                trace_context=trace_context,
            )
            raise TemplateServiceError(ErrorCode.NOT_FOUND, TEMPLATE_NOT_FOUND_MESSAGE, 404)
        if template.template_source is TemplateSource.SYSTEM_TEMPLATE:
            self._record_rejected(
                action="template.delete.rejected",
                target_id=template_id,
                reason=DELETE_SYSTEM_TEMPLATE_MESSAGE,
                metadata={
                    "template_id": template_id,
                    "template_source": template.template_source.value,
                },
                trace_context=trace_context,
            )
            raise TemplateServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELETE_SYSTEM_TEMPLATE_MESSAGE,
                409,
            )

        child_template_ids = [
            child_template_id
            for (child_template_id,) in self._session.query(
                PipelineTemplateModel.template_id
            )
            .filter(PipelineTemplateModel.base_template_id == template_id)
            .order_by(PipelineTemplateModel.template_id.asc())
            .all()
        ]
        if child_template_ids:
            self._record_rejected(
                action="template.delete.rejected",
                target_id=template_id,
                reason=DELETE_BASE_TEMPLATE_MESSAGE,
                metadata={
                    "template_id": template_id,
                    "child_template_ids": child_template_ids,
                },
                trace_context=trace_context,
            )
            raise TemplateServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELETE_BASE_TEMPLATE_MESSAGE,
                409,
            )

        referencing_sessions = (
            self._session.query(SessionModel)
            .filter(SessionModel.selected_template_id == template_id)
            .order_by(SessionModel.session_id.asc())
            .all()
        )
        blocked_sessions = [
            session
            for session in referencing_sessions
            if session.status is not SessionStatus.DRAFT
            or session.current_run_id is not None
        ]
        if blocked_sessions:
            self._record_rejected(
                action="template.delete.rejected",
                target_id=template_id,
                reason=DELETE_STARTED_SESSION_MESSAGE,
                metadata={
                    "template_id": template_id,
                    "blocked_session_ids": [
                        session.session_id for session in blocked_sessions
                    ],
                },
                trace_context=trace_context,
            )
            raise TemplateServiceError(
                ErrorCode.VALIDATION_ERROR,
                DELETE_STARTED_SESSION_MESSAGE,
                409,
            )

        timestamp = self._now()
        fallback_session_ids: list[str] = []
        for session in referencing_sessions:
            session.selected_template_id = DEFAULT_TEMPLATE_ID
            session.updated_at = timestamp
            fallback_session_ids.append(session.session_id)
            self._session.add(session)
        self._session.delete(template)
        self._session.flush()
        try:
            self._audit_service.record_command_result(
                actor_type=AuditActorType.USER,
                actor_id=API_ACTOR_ID,
                action="template.delete",
                target_type="pipeline_template",
                target_id=template_id,
                result=AuditResult.SUCCEEDED,
                reason=None,
                metadata={
                    "template_id": template_id,
                    "template_source": TemplateSource.USER_TEMPLATE.value,
                    "fallback_template_id": DEFAULT_TEMPLATE_ID,
                    "fallback_session_ids": fallback_session_ids,
                },
                trace_context=trace_context,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def validate_editable_fields(
        self,
        body: PipelineTemplateWriteRequest,
    ) -> list[dict[str, str]]:
        expected_stages = list(FIXED_STAGE_SEQUENCE)
        if [binding.stage_type for binding in body.stage_role_bindings] != expected_stages:
            raise TemplateServiceError(
                ErrorCode.VALIDATION_ERROR,
                INVALID_TEMPLATE_MESSAGE,
            )

        bindings: list[dict[str, str]] = []
        for binding in body.stage_role_bindings:
            applicable_stage_types = ROLE_STAGE_TYPES.get(binding.role_id, [])
            if binding.stage_type not in applicable_stage_types:
                raise TemplateServiceError(
                    ErrorCode.VALIDATION_ERROR,
                    INVALID_TEMPLATE_MESSAGE,
                )
            prompt = binding.system_prompt.strip()
            bindings.append(
                {
                    "stage_type": binding.stage_type.value,
                    "role_id": binding.role_id,
                    "system_prompt": prompt,
                    "provider_id": binding.provider_id,
                }
            )
        return bindings

    def validate_template_prompts_before_save(
        self,
        bindings: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        try:
            validator = PromptValidationService(
                settings_read=self._prompt_validation_settings_read()
            )
            return validator.validate_template_prompts_before_save(bindings)
        except PromptValidationError as exc:
            message = (
                INVALID_TEMPLATE_MESSAGE
                if "blank_prompt" in exc.rule_ids
                else exc.message
            )
            raise TemplateServiceError(
                ErrorCode.VALIDATION_ERROR,
                message,
            ) from exc

    def _ordered_system_templates(self) -> list[PipelineTemplateModel]:
        templates = (
            self._session.query(PipelineTemplateModel)
            .filter(PipelineTemplateModel.template_id.in_(SYSTEM_TEMPLATE_IDS))
            .all()
        )
        by_id = {template.template_id: template for template in templates}
        return [
            by_id[template_id]
            for template_id in SYSTEM_TEMPLATE_IDS
            if template_id in by_id
        ]

    def _record_seed_audit(
        self,
        *,
        templates: list[PipelineTemplateModel],
        trace_context: TraceContext,
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.SYSTEM,
            actor_id=SEED_ACTOR_ID,
            action="template.seed_system",
            target_type="pipeline_template",
            target_id="system-template-seed",
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata={
                "template_ids": [
                    template.template_id
                    for template in templates
                ],
                "template_names": [
                    template.name
                    for template in templates
                ],
                "template_source": TemplateSource.SYSTEM_TEMPLATE.value,
                "role_ids": _unique_ordered(
                    binding["role_id"]
                    for template in templates
                    for binding in template.stage_role_bindings
                ),
                "provider_ids": _unique_ordered(
                    binding["provider_id"]
                    for template in templates
                    for binding in template.stage_role_bindings
                ),
            },
            trace_context=trace_context,
        )

    def _validated_bindings(
        self,
        body: PipelineTemplateWriteRequest,
        *,
        trace_context: TraceContext,
    ) -> list[dict[str, str]]:
        ProviderService(
            self._session,
            audit_service=self._audit_service,
            now=self._now,
        ).seed_builtin_providers(trace_context=trace_context)
        bindings = self.validate_editable_fields(body)
        bindings = self.validate_template_prompts_before_save(bindings)
        provider_ids = {binding["provider_id"] for binding in bindings}
        existing_provider_ids = {
            provider_id
            for (provider_id,) in self._session.query(ProviderModel.provider_id)
            .filter(ProviderModel.provider_id.in_(provider_ids))
            .all()
        }
        if provider_ids - existing_provider_ids:
            raise TemplateServiceError(
                ErrorCode.VALIDATION_ERROR,
                UNKNOWN_PROVIDER_MESSAGE,
            )
        return bindings

    def _template_audit_metadata(
        self,
        template: PipelineTemplateModel,
        *,
        source_template_id: str | None,
    ) -> dict[str, Any]:
        role_ids = _unique_ordered(
            binding["role_id"] for binding in template.stage_role_bindings
        )
        provider_ids = _unique_ordered(
            binding["provider_id"] for binding in template.stage_role_bindings
        )
        return {
            "template_id": template.template_id,
            "source_template_id": source_template_id,
            "base_template_id": template.base_template_id,
            "template_source": template.template_source.value,
            "stage_types": list(template.fixed_stage_sequence),
            "role_ids": role_ids,
            "provider_ids": provider_ids,
            "auto_regression_enabled": template.auto_regression_enabled,
            "max_auto_regression_retries": template.max_auto_regression_retries,
        }

    def _record_success(
        self,
        *,
        action: str,
        template: PipelineTemplateModel,
        trace_context: TraceContext,
        metadata: dict[str, Any],
    ) -> None:
        self._audit_service.record_command_result(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action=action,
            target_type="pipeline_template",
            target_id=template.template_id,
            result=AuditResult.SUCCEEDED,
            reason=None,
            metadata=metadata,
            trace_context=trace_context,
        )

    def _record_rejected(
        self,
        *,
        action: str,
        target_id: str,
        reason: str,
        metadata: dict[str, Any],
        trace_context: TraceContext,
    ) -> None:
        self._audit_service.record_rejected_command(
            actor_type=AuditActorType.USER,
            actor_id=API_ACTOR_ID,
            action=action,
            target_type="pipeline_template",
            target_id=target_id,
            reason=reason,
            metadata=metadata,
            trace_context=trace_context,
        )

    def _prompt_validation_settings_read(self):
        trace_context = TraceContext(
            request_id="template-prompt-validation",
            trace_id="template-prompt-validation",
            correlation_id="template-prompt-validation",
            span_id="template-prompt-validation",
            parent_span_id=None,
            created_at=self._now(),
        )
        service = PlatformRuntimeSettingsService(
            self._session,
            audit_service=self._audit_service,
            log_writer=_NoopSettingsLogWriter(),
            now=self._now,
        )
        model = self._session.get(
            PlatformRuntimeSettingsModel,
            "platform-runtime-settings",
        )
        if model is None:
            model = service._default_model(trace_context=trace_context)
        return service._to_read(model)


def _stage_role_bindings(
    *,
    assets: dict[str, PromptAssetRead],
    provider_by_stage: dict[StageType, str],
) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    for stage_type in FIXED_STAGE_SEQUENCE:
        role_id = STAGE_ROLE_IDS[stage_type]
        bindings.append(
            {
                "stage_type": stage_type.value,
                "role_id": role_id,
                "system_prompt": assets[role_id].sections[0].body,
                "provider_id": provider_by_stage[stage_type],
            }
        )
    return bindings


def _unique_ordered(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


class _NoopSettingsLogWriter:
    def write(self, record) -> object:  # noqa: ANN001
        return object()


__all__ = [
    "AgentRoleSeed",
    "DEFAULT_TEMPLATE_ID",
    "ROLE_ASSET_DIR",
    "ROLE_ASSET_FILES",
    "STAGE_ROLE_IDS",
    "SYSTEM_TEMPLATE_IDS",
    "TEMPLATE_SEEDS",
    "TemplateService",
    "TemplateServiceError",
    "build_agent_role_seed_asset",
    "load_agent_role_seed_asset",
    "load_default_agent_role_seed_assets",
    "parse_front_matter",
    "resolve_default_agent_role_prompt",
]
