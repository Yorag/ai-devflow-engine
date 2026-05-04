from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.error_codes import ErrorCode
from backend.app.schemas import common
from backend.app.schemas.runtime_settings import ProviderCallPolicySnapshotRead


ProviderFailureKind = Literal[
    "timeout",
    "network_error",
    "rate_limited",
    "auth_failed",
    "model_not_found",
    "capability_unsupported",
    "snapshot_unavailable",
    "empty_response",
    "structured_output_unparseable",
    "provider_error",
]

RetryDecisionStatus = Literal["scheduled", "exhausted", "not_retryable"]
CircuitBreakerAction = Literal["closed", "opened", "blocked", "half_open"]


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderFailure(_StrictBaseModel):
    failure_kind: ProviderFailureKind
    safe_message: str = Field(min_length=1)
    error_code: ErrorCode
    retryable: bool


class ProviderRetryDecision(_StrictBaseModel):
    failure_kind: ProviderFailureKind
    retry_attempt: int = Field(ge=1)
    max_retry_attempts: int = Field(ge=0)
    should_retry: bool
    backoff_wait_seconds: float | None
    status: RetryDecisionStatus
    error_code: ErrorCode
    safe_message: str = Field(min_length=1)


class ProviderRetryTraceRecord(_StrictBaseModel):
    trace_ref: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str | None = None
    provider_snapshot_id: str = Field(min_length=1)
    model_binding_snapshot_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    failure_kind: ProviderFailureKind
    retry_attempt: int = Field(ge=0)
    max_retry_attempts: int = Field(ge=0)
    backoff_wait_seconds: float | None = None
    status: Literal["scheduled", "exhausted", "not_retryable", "succeeded"]
    error_code: ErrorCode | None = None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderCircuitBreakerBindingKey:
    provider_snapshot_id: str
    model_binding_snapshot_id: str


class ProviderCircuitBreakerState(_StrictBaseModel):
    provider_snapshot_id: str = Field(min_length=1)
    model_binding_snapshot_id: str = Field(min_length=1)
    status: common.ProviderCircuitBreakerStatus
    consecutive_failures: int = Field(ge=0)
    opened_at: datetime | None = None
    last_failure_kind: ProviderFailureKind | None = None
    next_retry_at: datetime | None = None
    half_open_trial_in_progress: bool = False


class ProviderCircuitBreakerDecision(_StrictBaseModel):
    allowed: bool
    state: ProviderCircuitBreakerState
    action: CircuitBreakerAction


class ProviderCircuitBreakerTraceRecord(_StrictBaseModel):
    trace_ref: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str | None = None
    provider_snapshot_id: str = Field(min_length=1)
    model_binding_snapshot_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    status: common.ProviderCircuitBreakerStatus
    consecutive_failures: int = Field(ge=0)
    opened_at: datetime | None = None
    next_retry_at: datetime | None = None
    failure_kind: ProviderFailureKind | None = None
    action: Literal["opened", "blocked", "half_open", "closed"]
    occurred_at: datetime


def classify_provider_failure(
    failure_kind: ProviderFailureKind,
    safe_message: str,
) -> ProviderFailure:
    retryable = failure_kind in {"timeout", "network_error", "rate_limited"}
    return ProviderFailure(
        failure_kind=failure_kind,
        safe_message=safe_message,
        error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
        retryable=retryable,
    )


class ProviderNonRetryableFailure(RuntimeError):
    def __init__(self, failure: ProviderFailure) -> None:
        super().__init__(failure.safe_message)
        self.failure = failure


class ProviderRetryPolicy:
    def __init__(self, snapshot: ProviderCallPolicySnapshotRead) -> None:
        self.snapshot = snapshot
        self.provider_call_policy = snapshot.provider_call_policy

    def failure_from_exception(self, error: BaseException) -> ProviderFailure:
        message = str(error)
        normalized = message.lower()
        if (
            isinstance(error, TimeoutError)
            or "timeout" in normalized
            or "timed out" in normalized
        ):
            return classify_provider_failure("timeout", "Provider request timed out.")
        if "429" in normalized or "rate limit" in normalized or "rate_limited" in normalized:
            return classify_provider_failure("rate_limited", "Provider rate limit was reached.")
        if isinstance(error, ConnectionError) or "network" in normalized or "connection" in normalized:
            return classify_provider_failure("network_error", "Provider network request failed.")
        if (
            "401" in normalized
            or "403" in normalized
            or "unauthorized" in normalized
            or "api key" in normalized
            or "credential" in normalized
        ):
            return classify_provider_failure("auth_failed", "Provider authentication failed.")
        if "404" in normalized or "model not found" in normalized:
            return classify_provider_failure("model_not_found", "Provider model was not found.")
        if (
            ("capability" in normalized and "unsupported" in normalized)
            or ("does not support" in normalized and "tool" in normalized)
        ):
            return classify_provider_failure(
                "capability_unsupported",
                "Provider capability is unsupported.",
            )
        if "snapshot unavailable" in normalized or "binding unavailable" in normalized:
            return classify_provider_failure(
                "snapshot_unavailable",
                "Provider snapshot is unavailable.",
            )
        if "empty response" in normalized:
            return classify_provider_failure(
                "empty_response",
                "Provider response was empty.",
            )
        if (
            "invalid json" in normalized
            or "jsondecode" in normalized
            or "unparseable" in normalized
            or "parse" in normalized
        ):
            return classify_provider_failure(
                "structured_output_unparseable",
                "Provider structured output could not be parsed.",
            )
        return classify_provider_failure("provider_error", "Provider call failed.")

    def decision_for_failure(
        self,
        failure: ProviderFailure,
        *,
        retry_attempt: int,
    ) -> ProviderRetryDecision:
        max_retry_attempts = self._max_retry_attempts(failure.failure_kind)
        if not failure.retryable:
            return ProviderRetryDecision(
                failure_kind=failure.failure_kind,
                retry_attempt=retry_attempt,
                max_retry_attempts=max_retry_attempts,
                should_retry=False,
                backoff_wait_seconds=None,
                status="not_retryable",
                error_code=failure.error_code,
                safe_message=failure.safe_message,
            )
        if retry_attempt > max_retry_attempts:
            return ProviderRetryDecision(
                failure_kind=failure.failure_kind,
                retry_attempt=retry_attempt,
                max_retry_attempts=max_retry_attempts,
                should_retry=False,
                backoff_wait_seconds=None,
                status="exhausted",
                error_code=failure.error_code,
                safe_message=failure.safe_message,
            )
        return ProviderRetryDecision(
            failure_kind=failure.failure_kind,
            retry_attempt=retry_attempt,
            max_retry_attempts=max_retry_attempts,
            should_retry=True,
            backoff_wait_seconds=self.backoff_wait_seconds(retry_attempt),
            status="scheduled",
            error_code=failure.error_code,
            safe_message=failure.safe_message,
        )

    def backoff_wait_seconds(self, retry_attempt: int) -> float:
        policy = self.provider_call_policy
        return min(
            float(policy.backoff_max_seconds),
            float(policy.backoff_base_seconds) * 2 ** (retry_attempt - 1),
        )

    def _max_retry_attempts(self, failure_kind: ProviderFailureKind) -> int:
        if failure_kind == "rate_limited":
            return self.provider_call_policy.rate_limit_max_retries
        if failure_kind in {"timeout", "network_error"}:
            return self.provider_call_policy.network_error_max_retries
        return 0


class ProviderCircuitBreaker:
    def __init__(self, retry_policy: ProviderRetryPolicy) -> None:
        self.retry_policy = retry_policy
        self._states: dict[
            ProviderCircuitBreakerBindingKey,
            ProviderCircuitBreakerState,
        ] = {}

    @staticmethod
    def binding_key(
        *,
        provider_snapshot_id: str,
        model_binding_snapshot_id: str,
    ) -> ProviderCircuitBreakerBindingKey:
        return ProviderCircuitBreakerBindingKey(
            provider_snapshot_id=provider_snapshot_id,
            model_binding_snapshot_id=model_binding_snapshot_id,
        )

    def before_call(
        self,
        key: ProviderCircuitBreakerBindingKey,
        *,
        occurred_at: datetime,
    ) -> ProviderCircuitBreakerDecision:
        state = self._state_for_key(key)
        if state.status is common.ProviderCircuitBreakerStatus.OPEN:
            if state.next_retry_at is not None and occurred_at >= state.next_retry_at:
                half_open = state.model_copy(
                    update={
                        "status": common.ProviderCircuitBreakerStatus.HALF_OPEN,
                        "half_open_trial_in_progress": True,
                    }
                )
                self._states[key] = half_open
                return ProviderCircuitBreakerDecision(
                    allowed=True,
                    state=half_open,
                    action="half_open",
                )
            return ProviderCircuitBreakerDecision(
                allowed=False,
                state=state,
                action="blocked",
            )
        if (
            state.status is common.ProviderCircuitBreakerStatus.HALF_OPEN
            and state.half_open_trial_in_progress
        ):
            return ProviderCircuitBreakerDecision(
                allowed=False,
                state=state,
                action="blocked",
            )
        return ProviderCircuitBreakerDecision(
            allowed=True,
            state=state,
            action=(
                "half_open"
                if state.status is common.ProviderCircuitBreakerStatus.HALF_OPEN
                else "closed"
            ),
        )

    def record_success(
        self,
        key: ProviderCircuitBreakerBindingKey,
        *,
        occurred_at: datetime,
    ) -> ProviderCircuitBreakerState:
        del occurred_at
        state = ProviderCircuitBreakerState(
            provider_snapshot_id=key.provider_snapshot_id,
            model_binding_snapshot_id=key.model_binding_snapshot_id,
            status=common.ProviderCircuitBreakerStatus.CLOSED,
            consecutive_failures=0,
        )
        self._states[key] = state
        return state

    def record_failure(
        self,
        key: ProviderCircuitBreakerBindingKey,
        *,
        failure_kind: ProviderFailureKind,
        occurred_at: datetime,
    ) -> ProviderCircuitBreakerState:
        current = self._state_for_key(key)
        consecutive_failures = current.consecutive_failures + 1
        threshold = (
            self.retry_policy.provider_call_policy.circuit_breaker_failure_threshold
        )
        if (
            consecutive_failures >= threshold
            or current.status is common.ProviderCircuitBreakerStatus.HALF_OPEN
        ):
            next_retry_at = occurred_at + timedelta(
                seconds=(
                    self.retry_policy.provider_call_policy
                    .circuit_breaker_recovery_seconds
                )
            )
            state = ProviderCircuitBreakerState(
                provider_snapshot_id=key.provider_snapshot_id,
                model_binding_snapshot_id=key.model_binding_snapshot_id,
                status=common.ProviderCircuitBreakerStatus.OPEN,
                consecutive_failures=consecutive_failures,
                opened_at=occurred_at,
                last_failure_kind=failure_kind,
                next_retry_at=next_retry_at,
                half_open_trial_in_progress=False,
            )
        else:
            state = ProviderCircuitBreakerState(
                provider_snapshot_id=key.provider_snapshot_id,
                model_binding_snapshot_id=key.model_binding_snapshot_id,
                status=common.ProviderCircuitBreakerStatus.CLOSED,
                consecutive_failures=consecutive_failures,
                last_failure_kind=failure_kind,
            )
        self._states[key] = state
        return state

    def _state_for_key(
        self,
        key: ProviderCircuitBreakerBindingKey,
    ) -> ProviderCircuitBreakerState:
        state = self._states.get(key)
        if state is not None:
            return state
        return ProviderCircuitBreakerState(
            provider_snapshot_id=key.provider_snapshot_id,
            model_binding_snapshot_id=key.model_binding_snapshot_id,
            status=common.ProviderCircuitBreakerStatus.CLOSED,
            consecutive_failures=0,
        )


__all__ = [
    "CircuitBreakerAction",
    "ProviderCircuitBreaker",
    "ProviderCircuitBreakerBindingKey",
    "ProviderCircuitBreakerDecision",
    "ProviderCircuitBreakerState",
    "ProviderCircuitBreakerTraceRecord",
    "ProviderFailure",
    "ProviderFailureKind",
    "ProviderNonRetryableFailure",
    "ProviderRetryDecision",
    "ProviderRetryPolicy",
    "ProviderRetryTraceRecord",
    "RetryDecisionStatus",
    "classify_provider_failure",
]
