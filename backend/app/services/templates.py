from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models.control import PipelineTemplateModel
from backend.app.domain.enums import StageType, TemplateSource
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptAssetRead,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptSectionRead,
    PromptType,
)
from backend.app.schemas.template import FIXED_APPROVAL_CHECKPOINTS, FIXED_STAGE_SEQUENCE


ROLE_ASSET_DIR = Path(__file__).resolve().parents[1] / "prompts" / "assets" / "roles"
SYSTEM_TEMPLATE_IDS = ("template-bugfix", "template-feature", "template-refactor")
DEFAULT_TEMPLATE_ID = "template-feature"
SEED_ACTOR_ID = "control-plane-seed"

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
    return PromptAssetRead(
        prompt_id=metadata["prompt_id"],
        prompt_version=metadata["prompt_version"],
        prompt_type=PromptType.AGENT_ROLE_SEED,
        authority_level=PromptAuthorityLevel.AGENT_ROLE_PROMPT,
        model_call_type=ModelCallType.STAGE_EXECUTION,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
        source_ref=f"backend://prompts/roles/{source_file_name}",
        content_hash=PromptAssetRead.calculate_content_hash(markdown),
        sections=[
            PromptSectionRead(
                section_id=metadata["role_id"],
                title=metadata["role_name"],
                body=body,
                cache_scope=PromptCacheScope.GLOBAL_STATIC,
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
        return self.seed_system_templates(trace_context=trace_context)

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


__all__ = [
    "AgentRoleSeed",
    "DEFAULT_TEMPLATE_ID",
    "ROLE_ASSET_DIR",
    "ROLE_ASSET_FILES",
    "STAGE_ROLE_IDS",
    "SYSTEM_TEMPLATE_IDS",
    "TEMPLATE_SEEDS",
    "TemplateService",
    "build_agent_role_seed_asset",
    "load_agent_role_seed_asset",
    "load_default_agent_role_seed_assets",
    "parse_front_matter",
    "resolve_default_agent_role_prompt",
]
