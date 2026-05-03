from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase
from backend.app.db.models.runtime import (
    DeliveryChannelSnapshotModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.runtime_settings import (
    PlatformRuntimeSettingsRead,
    PlatformRuntimeSettingsUpdate,
    ProviderCallPolicy,
)


NOW = datetime(2026, 5, 3, 11, 0, 0, tzinfo=UTC)
SNAPSHOT_AT = datetime(2026, 5, 3, 11, 5, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 3, 11, 10, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_rejected_command", **kwargs})
        return object()


class RecordingLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-provider-call-policy-snapshot",
        trace_id="trace-provider-call-policy-snapshot",
        correlation_id="correlation-provider-call-policy-snapshot",
        span_id="span-provider-call-policy-snapshot",
        parent_span_id=None,
        created_at=NOW,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    from backend.app.services.providers import ProviderService

    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    with manager.session(DatabaseRole.CONTROL) as session:
        ProviderService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).seed_builtin_providers(trace_context=build_trace())
    return manager


def build_runtime_run(
    run_id: str = "run-provider-call-policy",
    *,
    runtime_limit_snapshot_ref: str = "runtime-limit-existing",
    provider_call_policy_snapshot_ref: str = "provider-policy-existing",
    delivery_channel_snapshot_ref: str | None = None,
    current_stage_run_id: str | None = None,
    status: RunStatus = RunStatus.RUNNING,
) -> PipelineRunModel:
    return PipelineRunModel(
        run_id=run_id,
        session_id="session-provider-call-policy",
        project_id="project-default",
        attempt_index=1,
        status=status,
        trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
        template_snapshot_ref=f"template-snapshot-{run_id}",
        graph_definition_ref="graph-definition-pending",
        graph_thread_ref="graph-thread-pending",
        workspace_ref="workspace-provider-call-policy",
        runtime_limit_snapshot_ref=runtime_limit_snapshot_ref,
        provider_call_policy_snapshot_ref=provider_call_policy_snapshot_ref,
        delivery_channel_snapshot_ref=delivery_channel_snapshot_ref,
        current_stage_run_id=current_stage_run_id,
        trace_id="trace-provider-call-policy",
        started_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def current_settings(tmp_path: Path):
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        return PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        ).get_current_settings(trace_context=build_trace())


def test_provider_call_policy_snapshot_freezes_current_settings_version(
    tmp_path: Path,
) -> None:
    from backend.app.domain.provider_call_policy_snapshot import (
        ProviderCallPolicySnapshotBuilder,
    )
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        service = PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        )
        current = service.get_current_settings(trace_context=build_trace())
        updated = service.update_settings(
            PlatformRuntimeSettingsUpdate(
                expected_config_version=current.version.config_version,
                provider_call_policy=ProviderCallPolicy(
                    request_timeout_seconds=45,
                    network_error_max_retries=4,
                    rate_limit_max_retries=5,
                    backoff_base_seconds=1.5,
                    backoff_max_seconds=12.5,
                    circuit_breaker_failure_threshold=7,
                    circuit_breaker_recovery_seconds=90,
                ),
            ),
            trace_context=build_trace(),
        )

    snapshot = ProviderCallPolicySnapshotBuilder.build_for_run(
        updated,
        run_id="run-provider-call-policy",
        created_at=SNAPSHOT_AT,
    )

    with manager.session(DatabaseRole.CONTROL) as session:
        PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: LATER,
        ).update_settings(
            PlatformRuntimeSettingsUpdate(
                expected_config_version=updated.version.config_version,
                provider_call_policy=ProviderCallPolicy(
                    request_timeout_seconds=30,
                    network_error_max_retries=1,
                ),
            ),
            trace_context=build_trace(),
        )

    assert snapshot.snapshot_id == (
        "provider-call-policy-snapshot-run-provider-call-policy"
    )
    assert snapshot.run_id == "run-provider-call-policy"
    assert snapshot.provider_call_policy.request_timeout_seconds == 45
    assert snapshot.provider_call_policy.network_error_max_retries == 4
    assert snapshot.provider_call_policy.rate_limit_max_retries == 5
    assert snapshot.provider_call_policy.backoff_base_seconds == 1.5
    assert snapshot.provider_call_policy.backoff_max_seconds == 12.5
    assert snapshot.provider_call_policy.circuit_breaker_failure_threshold == 7
    assert snapshot.provider_call_policy.circuit_breaker_recovery_seconds == 90
    assert snapshot.source_config_version == "runtime-settings-v2"
    assert snapshot.schema_version == "provider-call-policy-snapshot-v1"
    assert snapshot.created_at == SNAPSHOT_AT
    dumped = snapshot.model_dump(mode="python")
    assert dumped["provider_call_policy"]["request_timeout_seconds"] == 45
    assert dumped["provider_call_policy"]["network_error_max_retries"] == 4


@pytest.mark.parametrize("settings", [None, {"settings_id": ""}])
def test_provider_call_policy_snapshot_rejects_invalid_or_missing_settings_source(
    settings: object,
) -> None:
    from backend.app.domain.provider_call_policy_snapshot import (
        ProviderCallPolicySnapshotBuilder,
        ProviderCallPolicySnapshotBuilderError,
    )

    with pytest.raises(ProviderCallPolicySnapshotBuilderError) as error:
        ProviderCallPolicySnapshotBuilder.build_for_run(
            settings,
            run_id="run-provider-call-policy",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE


@pytest.mark.parametrize(
    "mutate_payload",
    [
        lambda payload: payload.update({"provider_call_policy": {}}),
        lambda payload: payload["provider_call_policy"].pop(
            "network_error_max_retries"
        ),
        lambda payload: payload.pop("provider_call_policy"),
    ],
)
def test_provider_call_policy_snapshot_rejects_partial_settings_payload_defaults(
    tmp_path: Path,
    mutate_payload: Any,
) -> None:
    from backend.app.domain.provider_call_policy_snapshot import (
        ProviderCallPolicySnapshotBuilder,
        ProviderCallPolicySnapshotBuilderError,
    )

    payload = current_settings(tmp_path).model_dump(mode="python")
    mutate_payload(payload)

    with pytest.raises(ProviderCallPolicySnapshotBuilderError) as error:
        ProviderCallPolicySnapshotBuilder.build_for_run(
            payload,
            run_id="run-provider-call-policy",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE


@pytest.mark.parametrize(
    "mutate_payload",
    [
        lambda payload: payload.update({"provider_call_policy": {}}),
        lambda payload: payload["provider_call_policy"].pop(
            "network_error_max_retries"
        ),
    ],
)
def test_provider_call_policy_snapshot_rejects_coerced_partial_settings_read_defaults(
    tmp_path: Path,
    mutate_payload: Any,
) -> None:
    from backend.app.domain.provider_call_policy_snapshot import (
        ProviderCallPolicySnapshotBuilder,
        ProviderCallPolicySnapshotBuilderError,
    )

    payload = current_settings(tmp_path).model_dump(mode="python")
    mutate_payload(payload)
    settings = PlatformRuntimeSettingsRead.model_validate(payload)

    with pytest.raises(ProviderCallPolicySnapshotBuilderError) as error:
        ProviderCallPolicySnapshotBuilder.build_for_run(
            settings,
            run_id="run-provider-call-policy",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE


def test_provider_call_policy_snapshot_payload_is_immutable(
    tmp_path: Path,
) -> None:
    from backend.app.domain.provider_call_policy_snapshot import (
        ProviderCallPolicySnapshotBuilder,
    )

    snapshot = ProviderCallPolicySnapshotBuilder.build_for_run(
        current_settings(tmp_path),
        run_id="run-provider-call-policy",
        created_at=SNAPSHOT_AT,
    )

    with pytest.raises(ValidationError):
        snapshot.provider_call_policy.request_timeout_seconds = 1
    with pytest.raises(ValidationError):
        snapshot.source_config_version = "runtime-settings-mutated"

    assert snapshot.provider_call_policy.request_timeout_seconds == 60
    assert snapshot.source_config_version == "runtime-settings-v1"


def test_provider_call_policy_snapshot_id_uses_bounded_sha_fallback(
    tmp_path: Path,
) -> None:
    from backend.app.domain.provider_call_policy_snapshot import (
        ProviderCallPolicySnapshotBuilder,
    )

    run_id = "run-" + ("y" * 120)
    snapshot = ProviderCallPolicySnapshotBuilder.build_for_run(
        current_settings(tmp_path),
        run_id=run_id,
        created_at=SNAPSHOT_AT,
    )

    assert snapshot.snapshot_id.startswith("provider-call-policy-snapshot-")
    assert len(snapshot.snapshot_id) <= 80
    assert run_id not in snapshot.snapshot_id


def test_provider_call_policy_snapshot_repository_error_exposes_storage_error_code(
    tmp_path: Path,
) -> None:
    from backend.app.domain.provider_call_policy_snapshot import (
        ProviderCallPolicySnapshotBuilder,
    )
    from backend.app.repositories.runtime import (
        RuntimeSnapshotRepository,
        RuntimeSnapshotRepositoryError,
    )

    snapshot = ProviderCallPolicySnapshotBuilder.build_for_run(
        current_settings(tmp_path),
        run_id="run-provider-call-policy",
        created_at=SNAPSHOT_AT,
    )
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        repository = RuntimeSnapshotRepository(runtime_session)
        repository.save_provider_call_policy_snapshot(snapshot)
        with pytest.raises(RuntimeSnapshotRepositoryError) as error:
            repository.save_provider_call_policy_snapshot(snapshot)

    assert error.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert error.value.message == "Runtime snapshot storage is unavailable."


def test_run_lifecycle_attach_provider_call_policy_snapshot_persists_row_and_updates_only_policy_ref(
    tmp_path: Path,
) -> None:
    from backend.app.domain.provider_call_policy_snapshot import (
        ProviderCallPolicySnapshotBuilder,
    )
    from backend.app.services.runs import RunLifecycleService

    run_id = "run-attach-provider-call-policy"
    snapshot = ProviderCallPolicySnapshotBuilder.build_for_run(
        current_settings(tmp_path),
        run_id=run_id,
        created_at=SNAPSHOT_AT,
    )
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        runtime_session.add_all(
            [
                DeliveryChannelSnapshotModel(
                    delivery_channel_snapshot_id="delivery-channel-existing",
                    run_id=run_id,
                    source_delivery_channel_id="delivery-channel-1",
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
                    schema_version="delivery-channel-snapshot-v1",
                    created_at=NOW,
                ),
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-existing",
                    run_id=run_id,
                    agent_limits={"max_react_iterations_per_stage": 30},
                    context_limits={"compression_threshold_ratio": 0.8},
                    source_config_version="runtime-settings-v1",
                    hard_limits_version="platform-hard-limits-v1",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-policy-existing",
                    run_id=run_id,
                    provider_call_policy={"request_timeout_seconds": 60},
                    source_config_version="runtime-settings-v1",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        runtime_session.flush()
        run = build_runtime_run(
            run_id,
            delivery_channel_snapshot_ref="delivery-channel-existing",
            current_stage_run_id="stage-run-existing",
            status=RunStatus.WAITING_APPROVAL,
        )
        runtime_session.add(run)
        runtime_session.commit()

        existing = runtime_session.get(PipelineRunModel, run_id)
        assert existing is not None
        attached = RunLifecycleService(
            runtime_session,
            now=lambda: LATER,
        ).attach_provider_call_policy_snapshot(existing, snapshot)
        runtime_session.commit()
        attached_is_existing = attached is existing

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        saved_run = runtime_session.get(PipelineRunModel, run_id)
        saved_snapshot = runtime_session.get(
            ProviderCallPolicySnapshotModel,
            snapshot.snapshot_id,
        )

    assert attached_is_existing
    assert saved_run is not None
    assert saved_snapshot is not None
    assert saved_snapshot.provider_call_policy["request_timeout_seconds"] == 60
    assert saved_snapshot.source_config_version == "runtime-settings-v1"
    assert saved_run.status is RunStatus.WAITING_APPROVAL
    assert saved_run.provider_call_policy_snapshot_ref == snapshot.snapshot_id
    assert saved_run.runtime_limit_snapshot_ref == "runtime-limit-existing"
    assert saved_run.delivery_channel_snapshot_ref == "delivery-channel-existing"
    assert saved_run.current_stage_run_id == "stage-run-existing"
    assert saved_run.template_snapshot_ref == f"template-snapshot-{run_id}"
    assert saved_run.graph_definition_ref == "graph-definition-pending"
    assert saved_run.graph_thread_ref == "graph-thread-pending"
    assert saved_run.updated_at.replace(tzinfo=UTC) == LATER
