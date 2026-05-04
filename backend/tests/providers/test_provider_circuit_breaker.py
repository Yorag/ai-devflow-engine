from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.providers.retry_policy import (
    ProviderCircuitBreaker,
    ProviderRetryPolicy,
)
from backend.app.schemas import common

from backend.tests.providers.test_provider_retry_policy import policy_snapshot


NOW = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


def test_circuit_breaker_opens_at_frozen_threshold_and_blocks_same_binding() -> None:
    retry_policy = ProviderRetryPolicy(
        policy_snapshot(circuit_breaker_failure_threshold=2)
    )
    breaker = ProviderCircuitBreaker(retry_policy)

    key = breaker.binding_key(
        provider_snapshot_id="provider-snapshot-1",
        model_binding_snapshot_id="model-binding-1",
    )
    first = breaker.record_failure(
        key,
        failure_kind="network_error",
        occurred_at=NOW,
    )
    second = breaker.record_failure(
        key,
        failure_kind="network_error",
        occurred_at=NOW + timedelta(seconds=1),
    )
    before_call = breaker.before_call(key, occurred_at=NOW + timedelta(seconds=2))

    assert first.status is common.ProviderCircuitBreakerStatus.CLOSED
    assert second.status is common.ProviderCircuitBreakerStatus.OPEN
    assert before_call.allowed is False
    assert before_call.state.status is common.ProviderCircuitBreakerStatus.OPEN


def test_circuit_breaker_half_opens_after_snapshot_recovery_window_and_closes_on_success() -> None:
    retry_policy = ProviderRetryPolicy(
        policy_snapshot(
            circuit_breaker_failure_threshold=1,
            circuit_breaker_recovery_seconds=30,
        )
    )
    breaker = ProviderCircuitBreaker(retry_policy)
    key = breaker.binding_key(
        provider_snapshot_id="provider-snapshot-1",
        model_binding_snapshot_id="model-binding-1",
    )

    breaker.record_failure(key, failure_kind="timeout", occurred_at=NOW)
    early = breaker.before_call(key, occurred_at=NOW + timedelta(seconds=29))
    recovered = breaker.before_call(key, occurred_at=NOW + timedelta(seconds=30))
    closed = breaker.record_success(key, occurred_at=NOW + timedelta(seconds=31))

    assert early.allowed is False
    assert recovered.allowed is True
    assert recovered.state.status is common.ProviderCircuitBreakerStatus.HALF_OPEN
    assert closed.status is common.ProviderCircuitBreakerStatus.CLOSED
    assert closed.consecutive_failures == 0


def test_circuit_breaker_allows_only_one_half_open_trial_until_result() -> None:
    retry_policy = ProviderRetryPolicy(
        policy_snapshot(
            circuit_breaker_failure_threshold=1,
            circuit_breaker_recovery_seconds=30,
        )
    )
    breaker = ProviderCircuitBreaker(retry_policy)
    key = breaker.binding_key(
        provider_snapshot_id="provider-snapshot-1",
        model_binding_snapshot_id="model-binding-1",
    )

    breaker.record_failure(key, failure_kind="timeout", occurred_at=NOW)
    first_trial = breaker.before_call(key, occurred_at=NOW + timedelta(seconds=30))
    second_trial = breaker.before_call(key, occurred_at=NOW + timedelta(seconds=31))

    assert first_trial.allowed is True
    assert first_trial.action == "half_open"
    assert second_trial.allowed is False
    assert second_trial.action == "blocked"
    assert second_trial.state.status is common.ProviderCircuitBreakerStatus.HALF_OPEN
