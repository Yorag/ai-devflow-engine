from __future__ import annotations

from datetime import UTC, datetime

from backend.app.api.error_codes import ErrorCode
from backend.app.providers.retry_policy import (
    ProviderRetryPolicy,
    classify_provider_failure,
)
from backend.app.schemas.runtime_settings import (
    ProviderCallPolicy,
    ProviderCallPolicySnapshotRead,
)


NOW = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


def policy_snapshot(**overrides: object) -> ProviderCallPolicySnapshotRead:
    policy_values = {
        "request_timeout_seconds": 45,
        "network_error_max_retries": 3,
        "rate_limit_max_retries": 1,
        "backoff_base_seconds": 1.5,
        "backoff_max_seconds": 5.0,
        "circuit_breaker_failure_threshold": 2,
        "circuit_breaker_recovery_seconds": 30,
        **overrides,
    }
    policy = ProviderCallPolicy(**policy_values)
    return ProviderCallPolicySnapshotRead(
        snapshot_id="policy-run-1",
        run_id="run-1",
        provider_call_policy=policy,
        source_config_version="runtime-settings-v1",
        schema_version="provider-call-policy-snapshot-v1",
        created_at=NOW,
    )


def test_retry_policy_schedules_exponential_backoff_from_frozen_snapshot() -> None:
    policy = ProviderRetryPolicy(policy_snapshot())

    first = policy.decision_for_failure(
        policy.failure_from_exception(TimeoutError("request timed out")),
        retry_attempt=1,
    )
    third = policy.decision_for_failure(
        policy.failure_from_exception(ConnectionError("network down")),
        retry_attempt=3,
    )

    assert first.should_retry is True
    assert first.backoff_wait_seconds == 1.5
    assert third.should_retry is True
    assert third.backoff_wait_seconds == 5.0
    assert third.max_retry_attempts == 3


def test_rate_limit_uses_rate_limit_retry_count() -> None:
    policy = ProviderRetryPolicy(policy_snapshot())
    failure = policy.failure_from_exception(RuntimeError("HTTP 429 rate limit"))

    first = policy.decision_for_failure(failure, retry_attempt=1)
    second = policy.decision_for_failure(failure, retry_attempt=2)

    assert first.should_retry is True
    assert first.max_retry_attempts == 1
    assert second.should_retry is False
    assert second.status == "exhausted"


def test_non_retryable_failures_do_not_enter_recovery_loop() -> None:
    policy = ProviderRetryPolicy(policy_snapshot())

    auth = policy.decision_for_failure(
        policy.failure_from_exception(RuntimeError("401 unauthorized api key")),
        retry_attempt=1,
    )
    parse = policy.decision_for_failure(
        classify_provider_failure("structured_output_unparseable", "Invalid JSON."),
        retry_attempt=1,
    )

    assert auth.should_retry is False
    assert auth.status == "not_retryable"
    assert parse.should_retry is False
    assert parse.error_code is ErrorCode.PROVIDER_RETRY_EXHAUSTED
