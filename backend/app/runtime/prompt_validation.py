from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import ApprovalType, StageType, TemplateSource
from backend.app.domain.graph_definition import build_fixed_stage_sequence
from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshotBuilder
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot
from backend.app.schemas.runtime_settings import PlatformRuntimeSettingsRead
from backend.app.services.graph_compiler import GraphCompiler


DEFAULT_MAX_PROMPT_CHARS = 12000
_VALIDATION_RUN_ID = "prompt-validation-stage-contracts"
_VALIDATION_CREATED_AT_FALLBACK = datetime.fromisoformat("2026-01-01T00:00:00+00:00")


@dataclass(frozen=True, slots=True)
class PromptValidationRule:
    rule_id: str
    message: str


@dataclass(frozen=True, slots=True)
class PromptValidationResult:
    accepted: bool
    normalized_prompt: str
    error_code: ErrorCode | None
    rule_ids: list[str]
    message: str | None = None


class PromptValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        rule_ids: Iterable[str],
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
    ) -> None:
        self.message = message
        self.rule_ids = list(rule_ids)
        self.error_code = error_code
        super().__init__(message)


class PromptValidationService:
    def __init__(
        self,
        *,
        settings_read: PlatformRuntimeSettingsRead,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    ) -> None:
        self._settings_read = settings_read
        self._max_prompt_chars = max_prompt_chars
        self._stage_contracts = self._load_stage_contracts()

    def validate_system_prompt(
        self,
        *,
        prompt_text: str,
        stage_type: StageType,
    ) -> PromptValidationResult:
        normalized = prompt_text.strip()
        lowered = _normalize_for_matching(normalized)
        rule_ids = self._collect_rule_ids(
            normalized=normalized,
            lowered=lowered,
            stage_type=stage_type,
        )
        if rule_ids:
            raise PromptValidationError(
                "System prompt conflicts with platform prompt validation rules.",
                rule_ids=rule_ids,
            )
        return PromptValidationResult(
            accepted=True,
            normalized_prompt=normalized,
            error_code=None,
            rule_ids=[],
        )

    def validate_template_prompts_before_save(
        self,
        bindings: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        validated: list[dict[str, str]] = []
        for binding in bindings:
            result = self.validate_system_prompt(
                prompt_text=binding["system_prompt"],
                stage_type=StageType(binding["stage_type"]),
            )
            validated.append({**binding, "system_prompt": result.normalized_prompt})
        return validated

    def validate_run_prompt_snapshots(
        self,
        *,
        template_snapshot: TemplateSnapshot,
    ) -> None:
        for binding in template_snapshot.stage_role_bindings:
            self.validate_system_prompt(
                prompt_text=binding.system_prompt,
                stage_type=binding.stage_type,
            )

    def _collect_rule_ids(
        self,
        *,
        normalized: str,
        lowered: str,
        stage_type: StageType,
    ) -> list[str]:
        rule_ids: list[str] = []
        if not normalized:
            rule_ids.append("blank_prompt")
        if len(normalized) > self._max_prompt_chars:
            rule_ids.append("prompt_length_exceeded")
        if len(normalized) > self._context_prompt_budget_chars():
            rule_ids.append("context_budget_exceeded")
        if _contains_non_negated_any(
            lowered,
            (
                r"\bignore\b.*\bplatform instructions?\b",
                r"\boverride\b.*\bplatform\b",
                r"\bbypass\b.*\bplatform\b",
            ),
        ):
            rule_ids.append("platform_instruction_override")
        if _contains_any(
            lowered,
            (
                r"\bany tool you want\b",
                r"\btools? are unrestricted\b",
                r"\bunauthorized tools?\b",
                r"\bignore\b.*\ballowed_tools\b",
                r"\bnot in allowed_tools\b",
            ),
        ):
            rule_ids.append("unauthorized_tool_override")
        if _contains_any(
            lowered,
            (
                r"\bskip approval\b",
                r"\bbypass approval\b",
                r"\bignore approval\b",
                r"\bauto-?approve\b",
            ),
        ):
            rule_ids.append("approval_boundary_override")
        if _contains_any(
            lowered,
            (
                r"\bdisable structured output\b",
                r"\bfree-form prose only\b",
                r"\bplain text instead of\b.*\bstructured artifact\b",
                r"\bignore\b.*\bstructured artifact\b",
                r"\bdo not\b.*\bstructured output\b",
            ),
        ):
            rule_ids.append("structured_output_override")
        if _contains_any(
            lowered,
            (
                r"\bignore\b.*\boutput schema\b",
                r"\boverride\b.*\boutput schema\b",
                r"\bchange\b.*\boutput schema\b",
                r"\bwhatever fields\b",
            ),
        ):
            rule_ids.append("output_schema_override")
        if _contains_any(
            lowered,
            (
                r"\braw chain-of-thought\b",
                r"\breveal\b.*\bchain[- ]of[- ]thought\b",
                r"\bshow\b.*\bchain[- ]of[- ]thought\b",
            ),
        ):
            rule_ids.append("chain_of_thought_leak")
        if _contains_any(
            lowered,
            (
                r"\bdisclose\b.*\bcredentials?\b",
                r"\bdisclose\b.*\bapi keys?\b",
                r"\bdisclose\b.*\bsecrets?\b",
                r"\breveal\b.*\bcredentials?\b",
                r"\breveal\b.*\bapi keys?\b",
                r"\breveal\b.*\bsecrets?\b",
                r"\bexfiltrate\b.*\bsecrets?\b",
                r"\bprint\b.*\b(api keys?|secrets?|credentials?)\b",
            ),
        ):
            rule_ids.append("credential_leakage")
        if _contains_any(
            lowered,
            (
                r"\bskip clarification\b",
                r"\bbypass clarification\b",
                r"\bignore clarification\b",
                r"\bnever ask\b.*\bclarifying questions?\b",
            ),
        ):
            rule_ids.append("clarification_boundary_override")
        if _contains_any(
            lowered,
            (
                r"\boverride\b.*\bstage contract\b",
                r"\bignore\b.*\bstage contract\b",
                r"\bbypass\b.*\bstage contract\b",
                r"\bignore\b.*\bstage responsibility\b",
            ),
        ):
            rule_ids.append("stage_contract_override")
        if _contains_non_negated_any(
            lowered,
            (
                r"\bchange the delivery mode\b",
                r"\boverride\b.*\bdelivery\b",
                r"\bbypass\b.*\bdelivery\b",
                r"\bforce\b.*\bgit_auto_delivery\b",
            ),
        ):
            rule_ids.append("delivery_boundary_override")
        if _contains_any(
            lowered,
            (
                r"\bdo not log or audit\b",
                r"\bdisable audit\b",
                r"\bbypass audit\b",
                r"\bsuppress logs?\b",
                r"\bavoid audit\b",
            ),
        ):
            rule_ids.append("audit_boundary_override")
        if self._mentions_disallowed_tools(lowered=lowered, stage_type=stage_type):
            rule_ids.append("stage_contract_tool_override")
        return list(dict.fromkeys(rule_ids))

    def _context_prompt_budget_chars(self) -> int:
        return max(1, self._settings_read.context_limits.model_output_process_preview_chars)

    def _mentions_disallowed_tools(
        self,
        *,
        lowered: str,
        stage_type: StageType,
    ) -> bool:
        contract = self._stage_contracts[stage_type.value]
        allowed_tools = {
            str(tool).lower()
            for tool in contract.get("allowed_tools", [])
            if isinstance(tool, str)
        }
        for tool_name in _all_stage_tool_names(self._stage_contracts):
            if tool_name in allowed_tools:
                continue
            if _mentions_tool(lowered, tool_name):
                return True
        return False

    def _load_stage_contracts(self) -> dict[str, dict[str, Any]]:
        template_snapshot = self._validation_template_snapshot()
        runtime_limit_snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
            self._settings_read,
            template_snapshot=template_snapshot,
            run_id=_VALIDATION_RUN_ID,
            created_at=self._created_at(),
        )
        graph_definition = GraphCompiler(now=self._created_at).compile(
            template_snapshot=template_snapshot,
            runtime_limit_snapshot=runtime_limit_snapshot,
        )
        return {
            stage_type: dict(contract)
            for stage_type, contract in graph_definition.stage_contracts.items()
        }

    def _validation_template_snapshot(self) -> TemplateSnapshot:
        stages = build_fixed_stage_sequence()
        created_at = self._created_at()
        return TemplateSnapshot(
            snapshot_ref=f"template-snapshot-{_VALIDATION_RUN_ID}",
            run_id=_VALIDATION_RUN_ID,
            source_template_id="template-prompt-validation",
            source_template_name="Prompt Validation Template",
            source_template=TemplateSource.SYSTEM_TEMPLATE,
            source_template_updated_at=created_at,
            fixed_stage_sequence=stages,
            stage_role_bindings=tuple(
                StageRoleSnapshot(
                    stage_type=stage,
                    role_id=f"role-{stage.value}",
                    system_prompt=f"Prompt validation role for {stage.value}.",
                    provider_id="provider-deepseek",
                )
                for stage in stages
            ),
            approval_checkpoints=(
                ApprovalType.SOLUTION_DESIGN_APPROVAL,
                ApprovalType.CODE_REVIEW_APPROVAL,
            ),
            auto_regression_enabled=True,
            max_auto_regression_retries=(
                self._settings_read.agent_limits.max_auto_regression_retries
            ),
            created_at=created_at,
        )

    def _created_at(self) -> datetime:
        return self._settings_read.version.updated_at or _VALIDATION_CREATED_AT_FALLBACK


def _normalize_for_matching(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.casefold()).strip()


def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _contains_non_negated_any(text: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            prefix = text[max(0, match.start() - 32) : match.start()]
            if re.search(
                r"\b(do not|don't|never|avoid|must not|should not|cannot|can't)\b\s*$",
                prefix,
            ):
                continue
            return True
    return False


def _mentions_tool(text: str, tool_name: str) -> bool:
    variants = {tool_name, tool_name.replace("_", " "), tool_name.replace("_", "-")}
    for variant in variants:
        escaped = re.escape(variant)
        positive_pattern = re.compile(
            rf"\b(use|call|run|execute|invoke)\b\s+(?:the\s+)?{escaped}\b",
        )
        for match in positive_pattern.finditer(text):
            prefix = text[max(0, match.start() - 24) : match.start()]
            if re.search(r"\b(do not|don't|never|avoid|must not|should not)\b\s*$", prefix):
                continue
            return True
    return False


def _all_stage_tool_names(stage_contracts: dict[str, dict[str, Any]]) -> set[str]:
    tools: set[str] = set()
    for contract in stage_contracts.values():
        for tool in contract.get("allowed_tools", []):
            if isinstance(tool, str):
                tools.add(tool.lower())
    return tools


__all__ = [
    "PromptValidationError",
    "PromptValidationResult",
    "PromptValidationRule",
    "PromptValidationService",
]
