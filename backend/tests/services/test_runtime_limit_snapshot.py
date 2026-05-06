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
    ApprovalType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    StageType,
    TemplateSource,
)
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.runtime_settings import (
    AgentRuntimeLimits,
    ContextLimits,
    PlatformRuntimeSettingsRead,
    PlatformRuntimeSettingsUpdate,
)


NOW = datetime(2026, 5, 3, 10, 0, 0, tzinfo=UTC)
SNAPSHOT_AT = datetime(2026, 5, 3, 10, 5, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 3, 10, 10, 0, tzinfo=UTC)
FIXED_STAGES = (
    StageType.REQUIREMENT_ANALYSIS,
    StageType.SOLUTION_DESIGN,
    StageType.CODE_GENERATION,
    StageType.TEST_GENERATION_EXECUTION,
    StageType.CODE_REVIEW,
    StageType.DELIVERY_INTEGRATION,
)


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
        request_id="request-runtime-limit-snapshot",
        trace_id="trace-runtime-limit-snapshot",
        correlation_id="correlation-runtime-limit-snapshot",
        span_id="span-runtime-limit-snapshot",
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


def template_snapshot(
    *,
    run_id: str = "run-runtime-limits",
    max_auto_regression_retries: int = 1,
    max_react_iterations_per_stage: int = 30,
    max_tool_calls_per_stage: int = 80,
    skip_high_risk_tool_confirmations: bool = False,
) -> TemplateSnapshot:
    return TemplateSnapshot(
        snapshot_ref=f"template-snapshot-{run_id}",
        run_id=run_id,
        source_template_id="template-feature-one",
        source_template_name="Feature One",
        source_template=TemplateSource.SYSTEM_TEMPLATE,
        source_template_updated_at=NOW,
        fixed_stage_sequence=FIXED_STAGES,
        stage_role_bindings=tuple(
            StageRoleSnapshot(
                stage_type=stage_type,
                role_id=f"role-{stage_type.value}",
                system_prompt=f"# Prompt for {stage_type.value}",
                provider_id="provider-alpha",
            )
            for stage_type in FIXED_STAGES
        ),
        approval_checkpoints=(
            ApprovalType.SOLUTION_DESIGN_APPROVAL,
            ApprovalType.CODE_REVIEW_APPROVAL,
        ),
        auto_regression_enabled=True,
        max_auto_regression_retries=max_auto_regression_retries,
        max_react_iterations_per_stage=max_react_iterations_per_stage,
        max_tool_calls_per_stage=max_tool_calls_per_stage,
        skip_high_risk_tool_confirmations=skip_high_risk_tool_confirmations,
        created_at=NOW,
    )


def build_runtime_run(
    run_id: str = "run-runtime-limits",
    *,
    runtime_limit_snapshot_ref: str = "runtime-limit-existing",
    provider_call_policy_snapshot_ref: str = "provider-policy-existing",
    delivery_channel_snapshot_ref: str | None = None,
    current_stage_run_id: str | None = None,
    status: RunStatus = RunStatus.RUNNING,
) -> PipelineRunModel:
    return PipelineRunModel(
        run_id=run_id,
        session_id="session-runtime-limits",
        project_id="project-default",
        attempt_index=1,
        status=status,
        trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
        template_snapshot_ref=f"template-snapshot-{run_id}",
        graph_definition_ref="graph-definition-pending",
        graph_thread_ref="graph-thread-pending",
        workspace_ref="workspace-runtime-limits",
        runtime_limit_snapshot_ref=runtime_limit_snapshot_ref,
        provider_call_policy_snapshot_ref=provider_call_policy_snapshot_ref,
        delivery_channel_snapshot_ref=delivery_channel_snapshot_ref,
        current_stage_run_id=current_stage_run_id,
        trace_id="trace-runtime-limits",
        started_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def current_settings(tmp_path: Path):
    from backend.app.services.providers import ProviderService
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        ProviderService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).seed_builtin_providers(trace_context=build_trace())
        return PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        ).get_current_settings(trace_context=build_trace())


def test_runtime_limit_snapshot_freezes_current_settings_version_and_template_limit(
    tmp_path: Path,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshotBuilder
    from backend.app.services.providers import ProviderService
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        ProviderService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).seed_builtin_providers(trace_context=build_trace())
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
                agent_limits=AgentRuntimeLimits(
                    max_react_iterations_per_stage=40,
                    max_tool_calls_per_stage=90,
                    max_auto_regression_retries=3,
                ),
                context_limits=ContextLimits(
                    tool_output_preview_chars=5000,
                    compression_threshold_ratio=0.75,
                ),
            ),
            trace_context=build_trace(),
        )

    snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
        updated,
        template_snapshot=template_snapshot(
            max_auto_regression_retries=2,
            max_react_iterations_per_stage=35,
            max_tool_calls_per_stage=70,
        ),
        run_id="run-runtime-limits",
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
                agent_limits=AgentRuntimeLimits(max_react_iterations_per_stage=30),
                context_limits=ContextLimits(compression_threshold_ratio=0.6),
            ),
            trace_context=build_trace(),
        )

    assert snapshot.snapshot_id == "runtime-limit-snapshot-run-runtime-limits"
    assert snapshot.run_id == "run-runtime-limits"
    assert snapshot.agent_limits.max_react_iterations_per_stage == 35
    assert snapshot.agent_limits.max_tool_calls_per_stage == 70
    assert snapshot.agent_limits.max_auto_regression_retries == 2
    assert snapshot.context_limits.tool_output_preview_chars == 5000
    assert snapshot.context_limits.compression_threshold_ratio == 0.75
    assert snapshot.source_config_version == "runtime-settings-v2"
    assert snapshot.hard_limits_version == "platform-hard-limits-v1"
    assert snapshot.schema_version == "runtime-limit-snapshot-v1"
    assert snapshot.created_at == SNAPSHOT_AT
    dumped = snapshot.model_dump(mode="python")
    assert dumped["agent_limits"]["max_auto_regression_retries"] == 2


def test_runtime_limit_snapshot_rejects_template_limit_above_current_settings(
    tmp_path: Path,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import (
        RuntimeLimitSnapshotBuilder,
        RuntimeLimitSnapshotBuilderError,
    )

    with pytest.raises(RuntimeLimitSnapshotBuilderError) as error:
        RuntimeLimitSnapshotBuilder.build_for_run(
            current_settings(tmp_path),
            template_snapshot=template_snapshot(max_auto_regression_retries=3),
            run_id="run-runtime-limits",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED
    assert "max_auto_regression_retries" in error.value.message


@pytest.mark.parametrize(
    ("field_name", "template_value"),
    [
        ("max_react_iterations_per_stage", 31),
        ("max_tool_calls_per_stage", 81),
    ],
)
def test_runtime_limit_snapshot_rejects_template_agent_limit_above_current_settings(
    tmp_path: Path,
    field_name: str,
    template_value: int,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import (
        RuntimeLimitSnapshotBuilder,
        RuntimeLimitSnapshotBuilderError,
    )

    template = template_snapshot()
    template = template.model_copy(update={field_name: template_value})

    with pytest.raises(RuntimeLimitSnapshotBuilderError) as error:
        RuntimeLimitSnapshotBuilder.build_for_run(
            current_settings(tmp_path),
            template_snapshot=template,
            run_id="run-runtime-limits",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED
    assert field_name in error.value.message


def test_runtime_limit_snapshot_rejects_template_limit_above_hard_limit(
    tmp_path: Path,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import (
        RuntimeLimitSnapshotBuilder,
        RuntimeLimitSnapshotBuilderError,
    )
    from backend.app.services.providers import ProviderService
    from backend.app.services.runtime_settings import PlatformRuntimeSettingsService

    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.CONTROL) as session:
        ProviderService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).seed_builtin_providers(trace_context=build_trace())
        service = PlatformRuntimeSettingsService(
            session,
            audit_service=RecordingAuditService(),
            log_writer=RecordingLogWriter(),
            now=lambda: NOW,
        )
        settings = service.get_current_settings(trace_context=build_trace())
        settings.agent_limits.max_auto_regression_retries = 4

    with pytest.raises(RuntimeLimitSnapshotBuilderError) as error:
        RuntimeLimitSnapshotBuilder.build_for_run(
            settings,
            template_snapshot=template_snapshot(max_auto_regression_retries=4),
            run_id="run-runtime-limits",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED
    assert "max_auto_regression_retries" in error.value.message


@pytest.mark.parametrize("settings", [None, {"settings_id": ""}])
def test_runtime_limit_snapshot_rejects_invalid_or_missing_settings_source(
    settings: object,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import (
        RuntimeLimitSnapshotBuilder,
        RuntimeLimitSnapshotBuilderError,
    )

    with pytest.raises(RuntimeLimitSnapshotBuilderError) as error:
        RuntimeLimitSnapshotBuilder.build_for_run(
            settings,
            template_snapshot=template_snapshot(),
            run_id="run-runtime-limits",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE


@pytest.mark.parametrize(
    "mutate_payload",
    [
        lambda payload: payload.update({"agent_limits": {}}),
        lambda payload: payload.update({"context_limits": {}}),
        lambda payload: payload["agent_limits"].pop("max_tool_calls_per_stage"),
        lambda payload: payload["context_limits"].pop("compression_threshold_ratio"),
        lambda payload: payload.pop("agent_limits"),
        lambda payload: payload.pop("context_limits"),
    ],
)
def test_runtime_limit_snapshot_rejects_partial_settings_payload_defaults(
    tmp_path: Path,
    mutate_payload: Any,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import (
        RuntimeLimitSnapshotBuilder,
        RuntimeLimitSnapshotBuilderError,
    )

    payload = current_settings(tmp_path).model_dump(mode="python")
    mutate_payload(payload)

    with pytest.raises(RuntimeLimitSnapshotBuilderError) as error:
        RuntimeLimitSnapshotBuilder.build_for_run(
            payload,
            template_snapshot=template_snapshot(),
            run_id="run-runtime-limits",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE


@pytest.mark.parametrize(
    "mutate_payload",
    [
        lambda payload: payload.update({"agent_limits": {}}),
        lambda payload: payload.update({"context_limits": {}}),
        lambda payload: payload["agent_limits"].pop("max_tool_calls_per_stage"),
        lambda payload: payload["context_limits"].pop("compression_threshold_ratio"),
    ],
)
def test_runtime_limit_snapshot_rejects_coerced_partial_settings_read_defaults(
    tmp_path: Path,
    mutate_payload: Any,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import (
        RuntimeLimitSnapshotBuilder,
        RuntimeLimitSnapshotBuilderError,
    )

    payload = current_settings(tmp_path).model_dump(mode="python")
    mutate_payload(payload)
    settings = PlatformRuntimeSettingsRead.model_validate(payload)

    with pytest.raises(RuntimeLimitSnapshotBuilderError) as error:
        RuntimeLimitSnapshotBuilder.build_for_run(
            settings,
            template_snapshot=template_snapshot(),
            run_id="run-runtime-limits",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE


def test_runtime_limit_snapshot_rejects_template_run_mismatch(
    tmp_path: Path,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import (
        RuntimeLimitSnapshotBuilder,
        RuntimeLimitSnapshotBuilderError,
    )

    with pytest.raises(RuntimeLimitSnapshotBuilderError) as error:
        RuntimeLimitSnapshotBuilder.build_for_run(
            current_settings(tmp_path),
            template_snapshot=template_snapshot(run_id="other-run"),
            run_id="run-runtime-limits",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert "run_id" in error.value.message


def test_runtime_limit_snapshot_payloads_are_immutable(tmp_path: Path) -> None:
    from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshotBuilder

    snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
        current_settings(tmp_path),
        template_snapshot=template_snapshot(),
        run_id="run-runtime-limits",
        created_at=SNAPSHOT_AT,
    )

    with pytest.raises(ValidationError):
        snapshot.agent_limits.max_react_iterations_per_stage = 1
    with pytest.raises(ValidationError):
        snapshot.context_limits.compression_threshold_ratio = 0.5
    with pytest.raises(ValidationError):
        snapshot.source_config_version = "runtime-settings-mutated"

    assert snapshot.agent_limits.max_react_iterations_per_stage == 30
    assert snapshot.context_limits.compression_threshold_ratio == 0.8


def test_runtime_limit_snapshot_id_uses_bounded_sha_fallback(
    tmp_path: Path,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshotBuilder

    run_id = "run-" + ("x" * 120)
    snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
        current_settings(tmp_path),
        template_snapshot=template_snapshot(run_id=run_id),
        run_id=run_id,
        created_at=SNAPSHOT_AT,
    )

    assert snapshot.snapshot_id.startswith("runtime-limit-snapshot-")
    assert len(snapshot.snapshot_id) <= 80
    assert run_id not in snapshot.snapshot_id


def test_runtime_limit_snapshot_repository_error_exposes_storage_error_code(
    tmp_path: Path,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshotBuilder
    from backend.app.repositories.runtime import (
        RuntimeSnapshotRepository,
        RuntimeSnapshotRepositoryError,
    )

    snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
        current_settings(tmp_path),
        template_snapshot=template_snapshot(),
        run_id="run-runtime-limits",
        created_at=SNAPSHOT_AT,
    )
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        repository = RuntimeSnapshotRepository(runtime_session)
        repository.save_runtime_limit_snapshot(snapshot)
        with pytest.raises(RuntimeSnapshotRepositoryError) as error:
            repository.save_runtime_limit_snapshot(snapshot)

    assert error.value.error_code is ErrorCode.CONFIG_STORAGE_UNAVAILABLE
    assert error.value.message == "Runtime snapshot storage is unavailable."


def test_run_lifecycle_attach_runtime_limit_snapshot_persists_row_and_updates_only_limit_ref(
    tmp_path: Path,
) -> None:
    from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshotBuilder
    from backend.app.services.runs import RunLifecycleService

    run_id = "run-attach-runtime-limits"
    snapshot = RuntimeLimitSnapshotBuilder.build_for_run(
        current_settings(tmp_path),
        template_snapshot=template_snapshot(run_id=run_id),
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
        ).attach_runtime_limit_snapshot(existing, snapshot)
        runtime_session.commit()
        attached_is_existing = attached is existing

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        saved_run = runtime_session.get(PipelineRunModel, run_id)
        saved_snapshot = runtime_session.get(
            RuntimeLimitSnapshotModel,
            snapshot.snapshot_id,
        )

    assert attached_is_existing
    assert saved_run is not None
    assert saved_snapshot is not None
    assert saved_snapshot.agent_limits["max_auto_regression_retries"] == 1
    assert saved_snapshot.context_limits["compression_threshold_ratio"] == 0.8
    assert saved_run.status is RunStatus.WAITING_APPROVAL
    assert saved_run.runtime_limit_snapshot_ref == snapshot.snapshot_id
    assert saved_run.provider_call_policy_snapshot_ref == "provider-policy-existing"
    assert saved_run.delivery_channel_snapshot_ref == "delivery-channel-existing"
    assert saved_run.current_stage_run_id == "stage-run-existing"
    assert saved_run.template_snapshot_ref == f"template-snapshot-{run_id}"
    assert saved_run.graph_definition_ref == "graph-definition-pending"
    assert saved_run.graph_thread_ref == "graph-thread-pending"
    assert saved_run.updated_at.replace(tzinfo=UTC) == LATER
