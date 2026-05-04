from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.enums import StageType
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshot
from backend.app.domain.template_snapshot import TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus
from backend.app.schemas.runtime_settings import (
    PlatformHardLimits,
    RuntimeLimitSnapshotRead,
)


AUTO_REGRESSION_ROUTE_KEY = "review_regression_retry"
AUTO_REGRESSION_RETURN_STAGE = StageType.CODE_GENERATION
AUTO_REGRESSION_LOG_SOURCE = "runtime.auto_regression"
AUTO_REGRESSION_POLICY_PAYLOAD_TYPE = "auto_regression_policy_decision"
CHANGES_REQUESTED = "changes_requested"
STABLE_REVIEW_DECISIONS = frozenset({"approved", "no_changes_requested"})


class RunLogWriter(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class AutoRegressionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    should_retry: bool
    approval_allowed: bool
    status: Literal["retry_scheduled", "skipped", "exhausted"]
    reason: Literal[
        "changes_requested",
        "stable_review",
        "auto_regression_disabled",
        "not_code_review_stage",
        "missing_review_evidence",
        "retry_limit_exhausted",
    ]
    regression_decision: str | None = Field(default=None, min_length=1)
    retry_index: int | None = Field(default=None, ge=1)
    source_attempt_index: int = Field(ge=0)
    attempts_used: int = Field(ge=0)
    max_retries: int = Field(ge=0)
    route_key: str | None = Field(default=None, min_length=1)
    return_stage: StageType | None = None

    @model_validator(mode="after")
    def validate_retry_shape(self) -> AutoRegressionDecision:
        if self.should_retry:
            if self.status != "retry_scheduled":
                raise ValueError("retry decisions must use retry_scheduled status")
            if self.retry_index is None:
                raise ValueError("retry decisions require retry_index")
            if self.route_key != AUTO_REGRESSION_ROUTE_KEY:
                raise ValueError("retry decisions must use review regression route key")
            if self.return_stage is not AUTO_REGRESSION_RETURN_STAGE:
                raise ValueError("retry decisions must return to code_generation")
            if self.approval_allowed:
                raise ValueError("retry decisions cannot allow code review approval")
            if self.reason != "changes_requested":
                raise ValueError("retry decisions must use changes_requested reason")
            return self

        if self.retry_index is not None:
            raise ValueError("non-retry decisions cannot include retry_index")
        if self.route_key is not None:
            raise ValueError("non-retry decisions cannot include route_key")
        if self.return_stage is not None:
            raise ValueError("non-retry decisions cannot include return_stage")
        if self.status == "retry_scheduled":
            raise ValueError("retry_scheduled decisions must retry")
        if self.status == "exhausted":
            if self.reason != "retry_limit_exhausted":
                raise ValueError("exhausted decisions must use retry_limit_exhausted")
            if self.approval_allowed:
                raise ValueError("exhausted decisions cannot allow approval")
            return self
        if self.reason == "retry_limit_exhausted":
            raise ValueError("retry_limit_exhausted decisions must be exhausted")
        if self.status == "skipped":
            approval_allowed_by_reason = {
                "stable_review": True,
                "auto_regression_disabled": True,
                "missing_review_evidence": False,
                "not_code_review_stage": False,
            }
            expected = approval_allowed_by_reason.get(self.reason)
            if expected is None:
                raise ValueError("skipped decisions use skipped-only reasons")
            if self.approval_allowed is not expected:
                raise ValueError("skipped decision approval_allowed mismatches reason")
        return self


class AutoRegressionPolicy:
    def __init__(
        self,
        *,
        log_writer: RunLogWriter | None = None,
        now: Callable[[], datetime] | None = None,
        platform_hard_limits: PlatformHardLimits | None = None,
    ) -> None:
        self._log_writer = log_writer
        self._now = now or (lambda: datetime.now(UTC))
        self._platform_hard_limits = platform_hard_limits or PlatformHardLimits()

    def resolve_max_auto_regression_retries(
        self,
        *,
        template_snapshot: TemplateSnapshot,
        runtime_limit_snapshot: RuntimeLimitSnapshotRead | RuntimeLimitSnapshot,
        graph_definition: GraphDefinition,
    ) -> int:
        graph_enabled = _required_retry_policy_value(
            graph_definition,
            "auto_regression_enabled",
        )
        if not isinstance(graph_enabled, bool):
            raise ValueError(
                "GraphDefinition.retry_policy auto_regression_enabled must be a bool."
            )
        if graph_enabled != template_snapshot.auto_regression_enabled:
            raise ValueError(
                "GraphDefinition.retry_policy auto_regression_enabled must match "
                "TemplateSnapshot.auto_regression_enabled."
            )

        return_stage = _required_retry_policy_value(
            graph_definition,
            "return_stage_on_review_regression",
        )
        if return_stage != AUTO_REGRESSION_RETURN_STAGE.value:
            raise ValueError(
                "GraphDefinition.retry_policy return_stage_on_review_regression "
                "must be code_generation."
            )

        graph_retries = _non_negative_int(
            _required_retry_policy_value(
                graph_definition,
                "max_auto_regression_retries",
            ),
            "GraphDefinition.retry_policy.max_auto_regression_retries",
        )
        return min(
            template_snapshot.max_auto_regression_retries,
            runtime_limit_snapshot.agent_limits.max_auto_regression_retries,
            graph_retries,
            self._platform_hard_limits.agent_limits.max_auto_regression_retries,
        )

    def should_retry_review_issue(
        self,
        *,
        code_review_artifact: Mapping[str, object],
        template_snapshot: TemplateSnapshot,
        runtime_limit_snapshot: RuntimeLimitSnapshotRead | RuntimeLimitSnapshot,
        graph_definition: GraphDefinition,
        attempts_used: int,
        source_attempt_index: int,
        trace_context: TraceContext,
    ) -> AutoRegressionDecision:
        run_id = _required_trace_value(trace_context.run_id, "run_id")
        stage_run_id = _required_trace_value(
            trace_context.stage_run_id,
            "stage_run_id",
        )
        max_retries = self.resolve_max_auto_regression_retries(
            template_snapshot=template_snapshot,
            runtime_limit_snapshot=runtime_limit_snapshot,
            graph_definition=graph_definition,
        )
        regression_decision = _regression_decision(code_review_artifact)

        artifact_type = code_review_artifact.get("artifact_type")
        if artifact_type is not None and artifact_type != "CodeReviewArtifact":
            decision = self._skipped_decision(
                run_id=run_id,
                stage_run_id=stage_run_id,
                reason="not_code_review_stage",
                regression_decision=regression_decision,
                approval_allowed=False,
                source_attempt_index=source_attempt_index,
                attempts_used=attempts_used,
                max_retries=max_retries,
            )
            self._record_decision(decision, trace_context)
            return decision

        if regression_decision is None:
            decision = self._skipped_decision(
                run_id=run_id,
                stage_run_id=stage_run_id,
                reason="missing_review_evidence",
                regression_decision=None,
                approval_allowed=False,
                source_attempt_index=source_attempt_index,
                attempts_used=attempts_used,
                max_retries=max_retries,
            )
            self._record_decision(decision, trace_context)
            return decision

        if regression_decision in STABLE_REVIEW_DECISIONS:
            decision = self._skipped_decision(
                run_id=run_id,
                stage_run_id=stage_run_id,
                reason="stable_review",
                regression_decision=regression_decision,
                approval_allowed=True,
                source_attempt_index=source_attempt_index,
                attempts_used=attempts_used,
                max_retries=max_retries,
            )
            self._record_decision(decision, trace_context)
            return decision

        if not template_snapshot.auto_regression_enabled:
            decision = self._skipped_decision(
                run_id=run_id,
                stage_run_id=stage_run_id,
                reason="auto_regression_disabled",
                regression_decision=regression_decision,
                approval_allowed=True,
                source_attempt_index=source_attempt_index,
                attempts_used=attempts_used,
                max_retries=max_retries,
            )
            self._record_decision(decision, trace_context)
            return decision

        if not _has_review_evidence(code_review_artifact):
            decision = self._skipped_decision(
                run_id=run_id,
                stage_run_id=stage_run_id,
                reason="missing_review_evidence",
                regression_decision=regression_decision,
                approval_allowed=False,
                source_attempt_index=source_attempt_index,
                attempts_used=attempts_used,
                max_retries=max_retries,
            )
            self._record_decision(decision, trace_context)
            return decision

        if attempts_used >= max_retries:
            decision = AutoRegressionDecision(
                run_id=run_id,
                stage_run_id=stage_run_id,
                should_retry=False,
                approval_allowed=False,
                status="exhausted",
                reason="retry_limit_exhausted",
                regression_decision=regression_decision,
                source_attempt_index=source_attempt_index,
                attempts_used=attempts_used,
                max_retries=max_retries,
            )
            self._record_decision(decision, trace_context)
            return decision

        decision = AutoRegressionDecision(
            run_id=run_id,
            stage_run_id=stage_run_id,
            should_retry=True,
            approval_allowed=False,
            status="retry_scheduled",
            reason="changes_requested",
            regression_decision=regression_decision,
            retry_index=attempts_used + 1,
            source_attempt_index=source_attempt_index,
            attempts_used=attempts_used,
            max_retries=max_retries,
            route_key=AUTO_REGRESSION_ROUTE_KEY,
            return_stage=AUTO_REGRESSION_RETURN_STAGE,
        )
        self._record_decision(decision, trace_context)
        return decision

    def _skipped_decision(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        reason: Literal[
            "stable_review",
            "auto_regression_disabled",
            "not_code_review_stage",
            "missing_review_evidence",
        ],
        regression_decision: str | None,
        approval_allowed: bool,
        source_attempt_index: int,
        attempts_used: int,
        max_retries: int,
    ) -> AutoRegressionDecision:
        return AutoRegressionDecision(
            run_id=run_id,
            stage_run_id=stage_run_id,
            should_retry=False,
            approval_allowed=approval_allowed,
            status="skipped",
            reason=reason,
            regression_decision=regression_decision,
            source_attempt_index=source_attempt_index,
            attempts_used=attempts_used,
            max_retries=max_retries,
        )

    def _record_decision(
        self,
        decision: AutoRegressionDecision,
        trace_context: TraceContext,
    ) -> None:
        if self._log_writer is None:
            return
        summary = {
            "action": "auto_regression_policy",
            "status": decision.status,
            "reason": decision.reason,
            "run_id": decision.run_id,
            "stage_run_id": decision.stage_run_id,
            "regression_decision": decision.regression_decision,
            "retry_index": decision.retry_index,
            "source_attempt_index": decision.source_attempt_index,
            "attempts_used": decision.attempts_used,
            "max_retries": decision.max_retries,
            "route_key": decision.route_key,
            "return_stage": decision.return_stage.value
            if decision.return_stage
            else None,
            "approval_allowed": decision.approval_allowed,
        }
        try:
            self._log_writer.write_run_log(
                LogRecordInput(
                    source=AUTO_REGRESSION_LOG_SOURCE,
                    category=LogCategory.RUNTIME,
                    level=LogLevel.INFO,
                    message="Auto regression policy decision recorded.",
                    trace_context=trace_context,
                    payload=LogPayloadSummary(
                        payload_type=AUTO_REGRESSION_POLICY_PAYLOAD_TYPE,
                        summary=summary,
                        excerpt=None,
                        payload_size_bytes=0,
                        content_hash="",
                        redaction_status=RedactionStatus.NOT_REQUIRED,
                    ),
                    created_at=self._now(),
                )
            )
        except Exception:
            return


def resolve_max_auto_regression_retries(
    *,
    template_snapshot: TemplateSnapshot,
    runtime_limit_snapshot: RuntimeLimitSnapshotRead | RuntimeLimitSnapshot,
    graph_definition: GraphDefinition,
    platform_hard_limits: PlatformHardLimits | None = None,
) -> int:
    return AutoRegressionPolicy(
        platform_hard_limits=platform_hard_limits,
    ).resolve_max_auto_regression_retries(
        template_snapshot=template_snapshot,
        runtime_limit_snapshot=runtime_limit_snapshot,
        graph_definition=graph_definition,
    )


def should_retry_review_issue(
    *,
    code_review_artifact: Mapping[str, object],
    template_snapshot: TemplateSnapshot,
    runtime_limit_snapshot: RuntimeLimitSnapshotRead | RuntimeLimitSnapshot,
    graph_definition: GraphDefinition,
    attempts_used: int,
    source_attempt_index: int,
    trace_context: TraceContext,
    log_writer: RunLogWriter | None = None,
    now: Callable[[], datetime] | None = None,
    platform_hard_limits: PlatformHardLimits | None = None,
) -> AutoRegressionDecision:
    return AutoRegressionPolicy(
        log_writer=log_writer,
        now=now,
        platform_hard_limits=platform_hard_limits,
    ).should_retry_review_issue(
        code_review_artifact=code_review_artifact,
        template_snapshot=template_snapshot,
        runtime_limit_snapshot=runtime_limit_snapshot,
        graph_definition=graph_definition,
        attempts_used=attempts_used,
        source_attempt_index=source_attempt_index,
        trace_context=trace_context,
    )


def _required_retry_policy_value(
    graph_definition: GraphDefinition,
    key: str,
) -> object:
    value = graph_definition.retry_policy.get(key)
    if value is None:
        raise ValueError(f"GraphDefinition.retry_policy requires {key}")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _required_trace_value(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"TraceContext.{name} is required")
    return value


def _non_empty_sequence(value: object) -> bool:
    return isinstance(value, list | tuple) and any(bool(item) for item in value)


def _regression_decision(artifact: Mapping[str, object]) -> str | None:
    value = artifact.get("regression_decision")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == CHANGES_REQUESTED or normalized in STABLE_REVIEW_DECISIONS:
            return normalized
    return None


def _has_review_evidence(artifact: Mapping[str, object]) -> bool:
    return (
        _has_issue_evidence(artifact.get("issue_list"))
        and _has_fix_requirement_evidence(artifact.get("fix_requirements"))
        and _has_non_empty_string_sequence(artifact.get("evidence_refs"))
    )


def _has_issue_evidence(value: object) -> bool:
    if not isinstance(value, list | tuple):
        return False
    return any(_is_useful_issue(item) for item in value)


def _is_useful_issue(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    evidence_refs = value.get("evidence_refs")
    has_issue_label = any(
        _non_empty_string(value.get(key))
        for key in ("severity", "summary", "description", "requirement")
    )
    if has_issue_label and _has_non_empty_string_sequence(evidence_refs):
        return True
    return any(
        _non_empty_string(value.get(key))
        for key in ("body", "details", "message")
    )


def _has_fix_requirement_evidence(value: object) -> bool:
    if not isinstance(value, list | tuple):
        return False
    return any(_is_useful_fix_requirement(item) for item in value)


def _is_useful_fix_requirement(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    return any(
        _non_empty_string(value.get(key))
        for key in ("summary", "description", "requirement")
    )


def _has_non_empty_string_sequence(value: object) -> bool:
    return isinstance(value, list | tuple) and any(
        _stable_reference(item) for item in value
    )


def _non_empty_string(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return bool(normalized) and normalized not in {"placeholder", "todo", "tbd"}


def _stable_reference(value: object) -> bool:
    if not _non_empty_string(value):
        return False
    text = str(value).strip()
    return "://" in text or text.startswith(("sha256:", "stage-", "artifact-"))


__all__ = [
    "AUTO_REGRESSION_LOG_SOURCE",
    "AUTO_REGRESSION_POLICY_PAYLOAD_TYPE",
    "AUTO_REGRESSION_RETURN_STAGE",
    "AUTO_REGRESSION_ROUTE_KEY",
    "CHANGES_REQUESTED",
    "STABLE_REVIEW_DECISIONS",
    "AutoRegressionDecision",
    "AutoRegressionPolicy",
    "RunLogWriter",
    "resolve_max_auto_regression_retries",
    "should_retry_review_issue",
]
