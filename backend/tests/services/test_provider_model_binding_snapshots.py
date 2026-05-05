from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProviderModel
from backend.app.db.models.runtime import (
    ModelBindingSnapshotModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    ProviderSnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import (
    ApprovalType,
    ProviderProtocolType,
    ProviderSource,
    RunStatus,
    RunTriggerSource,
    StageType,
    TemplateSource,
)
from backend.app.domain.provider_snapshot import (
    INTERNAL_MODEL_BINDING_TYPES,
    InternalModelBindingSelection,
    ModelBindingSnapshotBuilder,
    ModelBindingSnapshotBuilderError,
    ProviderSnapshotBuilder,
    ProviderSnapshotBuilderError,
)
from backend.app.domain.template_snapshot import StageRoleSnapshot, TemplateSnapshot


NOW = datetime(2026, 5, 3, 9, 0, 0, tzinfo=UTC)
SNAPSHOT_AT = datetime(2026, 5, 3, 9, 2, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 3, 9, 5, 0, tzinfo=UTC)
FIXED_STAGES = (
    StageType.REQUIREMENT_ANALYSIS,
    StageType.SOLUTION_DESIGN,
    StageType.CODE_GENERATION,
    StageType.TEST_GENERATION_EXECUTION,
    StageType.CODE_REVIEW,
    StageType.DELIVERY_INTEGRATION,
)


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    return manager


def capability(
    model_id: str,
    *,
    max_output_tokens: int = 8192,
    context_window_tokens: int = 128000,
    supports_tool_calling: bool = True,
    supports_structured_output: bool = True,
    supports_native_reasoning: bool = False,
) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "context_window_tokens": context_window_tokens,
        "max_output_tokens": max_output_tokens,
        "supports_tool_calling": supports_tool_calling,
        "supports_structured_output": supports_structured_output,
        "supports_native_reasoning": supports_native_reasoning,
    }


def provider_model(
    provider_id: str = "provider-alpha",
    *,
    display_name: str = "Alpha Provider",
    api_key_ref: str | None = "env:AI_DEVFLOW_CREDENTIAL_ALPHA",
    default_model_id: str = "alpha-chat",
    runtime_capabilities: list[dict[str, Any]] | None = None,
    base_url: str = "https://alpha.example.test/v1",
    provider_source: ProviderSource = ProviderSource.CUSTOM,
    protocol_type: ProviderProtocolType = (
        ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
    ),
    updated_at: datetime = NOW,
) -> ProviderModel:
    return ProviderModel(
        provider_id=provider_id,
        display_name=display_name,
        provider_source=provider_source,
        protocol_type=protocol_type,
        base_url=base_url,
        api_key_ref=api_key_ref,
        default_model_id=default_model_id,
        supported_model_ids=[default_model_id],
        runtime_capabilities=runtime_capabilities or [capability(default_model_id)],
        created_at=NOW,
        updated_at=updated_at,
    )


def template_snapshot(
    *,
    run_id: str = "run-provider-snapshot",
    provider_ids: tuple[str, ...] = (
        "provider-alpha",
        "provider-beta",
        "provider-alpha",
        "provider-alpha",
        "provider-beta",
        "provider-alpha",
    ),
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
                provider_id=provider_ids[index],
            )
            for index, stage_type in enumerate(FIXED_STAGES)
        ),
        approval_checkpoints=(
            ApprovalType.SOLUTION_DESIGN_APPROVAL,
            ApprovalType.CODE_REVIEW_APPROVAL,
        ),
        auto_regression_enabled=True,
        max_auto_regression_retries=1,
        created_at=NOW,
    )


def internal_selection(
    binding_type: str,
    *,
    provider_id: str = "provider-beta",
    model_id: str = "beta-chat",
    model_parameters: dict[str, object] | None = None,
) -> InternalModelBindingSelection:
    return InternalModelBindingSelection(
        binding_type=binding_type,
        provider_id=provider_id,
        model_id=model_id,
        model_parameters=model_parameters or {"temperature": 0.0},
    )


def all_internal_selections(
    *,
    provider_id: str = "provider-beta",
    model_id: str = "beta-chat",
) -> tuple[InternalModelBindingSelection, ...]:
    return tuple(
        internal_selection(
            binding_type,
            provider_id=provider_id,
            model_id=model_id,
        )
        for binding_type in INTERNAL_MODEL_BINDING_TYPES
    )


def build_runtime_run(run_id: str = "run-attach-provider") -> PipelineRunModel:
    return PipelineRunModel(
        run_id=run_id,
        session_id="session-provider-snapshot",
        project_id="project-default",
        attempt_index=1,
        status=RunStatus.RUNNING,
        trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
        template_snapshot_ref=f"template-snapshot-{run_id}",
        graph_definition_ref="graph-definition-pending",
        graph_thread_ref="graph-thread-pending",
        workspace_ref="workspace-provider-snapshot",
        runtime_limit_snapshot_ref="runtime-limit-snapshot-provider",
        provider_call_policy_snapshot_ref="provider-call-policy-snapshot-provider",
        delivery_channel_snapshot_ref=None,
        current_stage_run_id=None,
        trace_id="trace-provider-snapshot",
        started_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_builders_freeze_provider_and_model_binding_snapshots_before_later_provider_mutation() -> None:
    alpha = provider_model(
        "provider-alpha",
        default_model_id="alpha-chat",
        runtime_capabilities=[
            capability(
                "alpha-chat",
                max_output_tokens=4096,
                supports_tool_calling=False,
            )
        ],
    )
    beta = provider_model(
        "provider-beta",
        display_name="Beta Provider",
        api_key_ref="env:AI_DEVFLOW_CREDENTIAL_BETA",
        default_model_id="beta-chat",
        runtime_capabilities=[
            capability(
                "beta-chat",
                max_output_tokens=16384,
                supports_native_reasoning=True,
            )
        ],
        base_url="https://beta.example.test/v1",
    )
    template = template_snapshot()

    provider_snapshots = ProviderSnapshotBuilder.build_for_run(
        [beta, alpha],
        run_id=template.run_id,
        required_provider_ids=("provider-beta", "provider-alpha"),
        created_at=SNAPSHOT_AT,
        credential_env_prefixes=("AI_DEVFLOW_CREDENTIAL_",),
    )
    model_binding_snapshots = ModelBindingSnapshotBuilder.build_for_run(
        template,
        provider_snapshots=provider_snapshots,
        internal_bindings=all_internal_selections(),
        run_id=template.run_id,
        created_at=SNAPSHOT_AT,
    )

    alpha.base_url = "https://latest-alpha.example.test/v1"
    alpha.api_key_ref = "env:AI_DEVFLOW_CREDENTIAL_ALPHA_ROTATED"
    alpha.default_model_id = "alpha-mutated"
    alpha.runtime_capabilities = [capability("alpha-mutated", max_output_tokens=1)]
    beta.runtime_capabilities = [capability("beta-mutated", max_output_tokens=2)]
    beta.updated_at = LATER

    assert [snapshot.provider_id for snapshot in provider_snapshots] == [
        "provider-alpha",
        "provider-beta",
    ]
    alpha_snapshot = provider_snapshots[0]
    assert alpha_snapshot.base_url == "https://alpha.example.test/v1"
    assert alpha_snapshot.api_key_ref == "env:AI_DEVFLOW_CREDENTIAL_ALPHA"
    assert alpha_snapshot.model_id == "alpha-chat"
    assert alpha_snapshot.capabilities.model_id == "alpha-chat"
    assert alpha_snapshot.capabilities.max_output_tokens == 4096
    assert alpha_snapshot.source_config_version == NOW.isoformat()

    assert len(model_binding_snapshots) == 9
    assert len({snapshot.snapshot_id for snapshot in model_binding_snapshots}) == 9
    assert all(len(snapshot.snapshot_id) <= 80 for snapshot in provider_snapshots)
    assert all(len(snapshot.snapshot_id) <= 80 for snapshot in model_binding_snapshots)
    assert [binding.binding_type for binding in model_binding_snapshots[:6]] == [
        "agent_role",
        "agent_role",
        "agent_role",
        "agent_role",
        "agent_role",
        "agent_role",
    ]
    assert [
        binding.binding_type for binding in model_binding_snapshots[6:]
    ] == list(INTERNAL_MODEL_BINDING_TYPES)
    assert model_binding_snapshots[0].stage_type is StageType.REQUIREMENT_ANALYSIS
    assert model_binding_snapshots[0].role_id == "role-requirement_analysis"
    assert model_binding_snapshots[0].model_id == "alpha-chat"
    assert model_binding_snapshots[0].capabilities.max_output_tokens == 4096
    assert model_binding_snapshots[-1].provider_id == "provider-beta"
    assert model_binding_snapshots[-1].model_id == "beta-chat"
    assert model_binding_snapshots[-1].capabilities.max_output_tokens == 16384
    dumped = [snapshot.model_dump(mode="json") for snapshot in model_binding_snapshots]
    assert "latest-alpha" not in str(dumped)
    assert "mutated" not in str(dumped)


def test_provider_snapshot_builder_rejects_missing_required_provider_with_missing_id() -> None:
    with pytest.raises(ProviderSnapshotBuilderError) as error:
        ProviderSnapshotBuilder.build_for_run(
            [provider_model("provider-alpha")],
            run_id="run-missing-provider",
            required_provider_ids=("provider-alpha", "provider-missing"),
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert "provider-missing" in error.value.message


def test_provider_snapshot_builder_accepts_direct_api_key_for_runtime_use() -> None:
    raw_secret = "sk-raw-provider-runtime-key"

    snapshots = ProviderSnapshotBuilder.build_for_run(
        [
            provider_model(
                "provider-alpha",
                api_key_ref=raw_secret,
            )
        ],
        run_id="run-direct-provider-key",
        required_provider_ids=("provider-alpha",),
        created_at=SNAPSHOT_AT,
    )

    assert len(snapshots) == 1
    assert snapshots[0].api_key_ref == raw_secret


def test_builders_bind_internal_selection_to_non_default_model_on_same_provider() -> None:
    provider = provider_model(
        "provider-alpha",
        default_model_id="alpha-chat",
        runtime_capabilities=[
            capability(
                "alpha-chat",
                max_output_tokens=4096,
                supports_native_reasoning=False,
            ),
            capability(
                "alpha-reasoner",
                max_output_tokens=32768,
                supports_tool_calling=False,
                supports_structured_output=False,
                supports_native_reasoning=True,
            ),
        ],
    )
    provider.supported_model_ids = ["alpha-chat", "alpha-reasoner"]
    run_id = "run-non-default-internal-binding"
    provider_snapshots = ProviderSnapshotBuilder.build_for_run(
        [provider],
        run_id=run_id,
        required_provider_ids=("provider-alpha",),
        required_model_ids_by_provider={"provider-alpha": ("alpha-reasoner",)},
        created_at=SNAPSHOT_AT,
    )

    model_binding_snapshots = ModelBindingSnapshotBuilder.build_for_run(
        template_snapshot(run_id=run_id, provider_ids=("provider-alpha",) * 6),
        provider_snapshots=provider_snapshots,
        internal_bindings=(
            internal_selection(
                "context_compression",
                provider_id="provider-alpha",
                model_id="alpha-reasoner",
            ),
            internal_selection(
                "structured_output_repair",
                provider_id="provider-alpha",
                model_id="alpha-chat",
            ),
            internal_selection(
                "validation_pass",
                provider_id="provider-alpha",
                model_id="alpha-chat",
            ),
        ),
        run_id=run_id,
        created_at=SNAPSHOT_AT,
    )

    assert [
        (snapshot.provider_id, snapshot.model_id)
        for snapshot in provider_snapshots
    ] == [
        ("provider-alpha", "alpha-chat"),
        ("provider-alpha", "alpha-reasoner"),
    ]
    assert len({snapshot.snapshot_id for snapshot in provider_snapshots}) == 2
    assert all(len(snapshot.snapshot_id) <= 80 for snapshot in provider_snapshots)

    by_type = {
        snapshot.binding_type: snapshot for snapshot in model_binding_snapshots
    }
    alpha_chat_snapshot = provider_snapshots[0]
    alpha_reasoner_snapshot = provider_snapshots[1]
    assert all(
        snapshot.model_id == "alpha-chat"
        and snapshot.provider_snapshot_id == alpha_chat_snapshot.snapshot_id
        for snapshot in model_binding_snapshots[:6]
    )
    assert by_type["context_compression"].model_id == "alpha-reasoner"
    assert by_type["context_compression"].provider_snapshot_id == (
        alpha_reasoner_snapshot.snapshot_id
    )
    assert by_type["context_compression"].capabilities.max_output_tokens == 32768
    assert by_type["context_compression"].capabilities.supports_native_reasoning is True
    assert by_type["structured_output_repair"].model_id == "alpha-chat"
    assert by_type["validation_pass"].model_id == "alpha-chat"


def test_model_binding_builder_selects_default_model_independent_of_snapshot_order() -> None:
    provider = provider_model(
        "provider-alpha",
        default_model_id="alpha-chat",
        runtime_capabilities=[
            capability("alpha-chat", max_output_tokens=4096),
            capability(
                "alpha-reasoner",
                max_output_tokens=32768,
                supports_tool_calling=False,
                supports_structured_output=False,
                supports_native_reasoning=True,
            ),
        ],
    )
    run_id = "run-default-binding-order-independent"
    provider_snapshots = ProviderSnapshotBuilder.build_for_run(
        [provider],
        run_id=run_id,
        required_provider_ids=("provider-alpha",),
        required_model_ids_by_provider={"provider-alpha": ("alpha-reasoner",)},
        created_at=SNAPSHOT_AT,
    )

    model_binding_snapshots = ModelBindingSnapshotBuilder.build_for_run(
        template_snapshot(run_id=run_id, provider_ids=("provider-alpha",) * 6),
        provider_snapshots=tuple(reversed(provider_snapshots)),
        internal_bindings=(
            internal_selection(
                "context_compression",
                provider_id="provider-alpha",
                model_id="alpha-reasoner",
            ),
            internal_selection(
                "structured_output_repair",
                provider_id="provider-alpha",
                model_id="alpha-chat",
            ),
            internal_selection(
                "validation_pass",
                provider_id="provider-alpha",
                model_id="alpha-chat",
            ),
        ),
        run_id=run_id,
        created_at=SNAPSHOT_AT,
    )

    assert all(
        snapshot.binding_type == "agent_role" and snapshot.model_id == "alpha-chat"
        for snapshot in model_binding_snapshots[:6]
    )
    by_type = {
        snapshot.binding_type: snapshot for snapshot in model_binding_snapshots
    }
    assert by_type["context_compression"].model_id == "alpha-reasoner"


def test_snapshot_payloads_are_deeply_immutable_after_build() -> None:
    provider_snapshots = ProviderSnapshotBuilder.build_for_run(
        [provider_model("provider-alpha")],
        run_id="run-immutable-snapshots",
        required_provider_ids=("provider-alpha",),
        created_at=SNAPSHOT_AT,
    )
    model_binding_snapshots = ModelBindingSnapshotBuilder.build_for_run(
        template_snapshot(
            run_id="run-immutable-snapshots",
            provider_ids=("provider-alpha",) * 6,
        ),
        provider_snapshots=provider_snapshots,
        internal_bindings=all_internal_selections(
            provider_id="provider-alpha",
            model_id="alpha-chat",
        ),
        run_id="run-immutable-snapshots",
        created_at=SNAPSHOT_AT,
    )

    provider_snapshot = provider_snapshots[0]
    internal_binding = model_binding_snapshots[-1]

    with pytest.raises(ValidationError):
        provider_snapshot.capabilities.max_output_tokens = 1
    with pytest.raises(TypeError):
        internal_binding.model_parameters["temperature"] = 0.7
    with pytest.raises(TypeError):
        internal_binding.model_parameters |= {"temperature": 0.7}

    assert internal_binding.capabilities is not provider_snapshot.capabilities
    assert internal_binding.capabilities.max_output_tokens == (
        provider_snapshot.capabilities.max_output_tokens
    )
    assert internal_binding.model_dump(mode="json")["model_parameters"] == {
        "temperature": 0.0
    }


@pytest.mark.parametrize(
    "runtime_capabilities",
    [
        [capability("other-model")],
        [
            {
                **capability("alpha-chat"),
                "max_output_tokens": 0,
            }
        ],
    ],
)
def test_provider_snapshot_builder_rejects_missing_or_invalid_default_model_capabilities(
    runtime_capabilities: list[dict[str, Any]],
) -> None:
    with pytest.raises(ProviderSnapshotBuilderError) as error:
        ProviderSnapshotBuilder.build_for_run(
            [
                provider_model(
                    "provider-alpha",
                    default_model_id="alpha-chat",
                    runtime_capabilities=runtime_capabilities,
                )
            ],
            run_id="run-invalid-capabilities",
            required_provider_ids=("provider-alpha",),
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert "capabilities" in error.value.message


@pytest.mark.parametrize(
    "runtime_capabilities",
    [
        [
            {
                key: value
                for key, value in capability("alpha-chat").items()
                if key != "context_window_tokens"
            }
        ],
        [
            {
                **capability("alpha-chat"),
                "supports_tool_calling": "true",
            }
        ],
    ],
)
def test_provider_snapshot_builder_rejects_missing_or_coerced_capability_fields(
    runtime_capabilities: list[dict[str, Any]],
) -> None:
    with pytest.raises(ProviderSnapshotBuilderError) as error:
        ProviderSnapshotBuilder.build_for_run(
            [
                provider_model(
                    "provider-alpha",
                    default_model_id="alpha-chat",
                    runtime_capabilities=runtime_capabilities,
                )
            ],
            run_id="run-strict-capabilities",
            required_provider_ids=("provider-alpha",),
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert "capabilities" in error.value.message


def test_model_binding_snapshot_builder_requires_all_internal_bindings() -> None:
    provider_snapshots = ProviderSnapshotBuilder.build_for_run(
        [provider_model("provider-alpha")],
        run_id="run-missing-internal-binding",
        required_provider_ids=("provider-alpha",),
        created_at=SNAPSHOT_AT,
    )

    with pytest.raises(ModelBindingSnapshotBuilderError) as error:
        ModelBindingSnapshotBuilder.build_for_run(
            template_snapshot(
                run_id="run-missing-internal-binding",
                provider_ids=("provider-alpha",) * 6,
            ),
            provider_snapshots=provider_snapshots,
            internal_bindings=(
                internal_selection(
                    "context_compression",
                    provider_id="provider-alpha",
                    model_id="alpha-chat",
                ),
            ),
            run_id="run-missing-internal-binding",
            created_at=SNAPSHOT_AT,
        )

    assert error.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert "structured_output_repair" in error.value.message
    assert "validation_pass" in error.value.message


def test_run_lifecycle_attach_provider_snapshots_persists_rows_and_preserves_run_refs(
    tmp_path: Path,
) -> None:
    from backend.app.services.runs import RunLifecycleService

    manager = build_manager(tmp_path)
    run_id = "run-attach-provider"
    provider_snapshots = ProviderSnapshotBuilder.build_for_run(
        [provider_model("provider-alpha")],
        run_id=run_id,
        required_provider_ids=("provider-alpha",),
        created_at=SNAPSHOT_AT,
    )
    model_binding_snapshots = ModelBindingSnapshotBuilder.build_for_run(
        template_snapshot(run_id=run_id, provider_ids=("provider-alpha",) * 6),
        provider_snapshots=provider_snapshots,
        internal_bindings=all_internal_selections(
            provider_id="provider-alpha",
            model_id="alpha-chat",
        ),
        run_id=run_id,
        created_at=SNAPSHOT_AT,
    )

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        runtime_session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-snapshot-provider",
                    run_id=run_id,
                    agent_limits={"max_react_iterations_per_stage": 30},
                    context_limits={"compression_threshold_ratio": 0.8},
                    source_config_version="runtime-settings-v1",
                    hard_limits_version="platform-hard-limits-v1",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-call-policy-snapshot-provider",
                    run_id=run_id,
                    provider_call_policy={"request_timeout_seconds": 60},
                    source_config_version="runtime-settings-v1",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        runtime_session.flush()
        run = build_runtime_run(run_id)
        runtime_session.add(run)
        runtime_session.commit()

        existing = runtime_session.get(PipelineRunModel, run_id)
        assert existing is not None
        attached = RunLifecycleService(
            runtime_session,
            now=lambda: LATER,
        ).attach_provider_snapshots(
            existing,
            provider_snapshots=provider_snapshots,
            model_binding_snapshots=model_binding_snapshots,
        )
        runtime_session.commit()
        attached_is_existing = attached is existing

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        saved_run = runtime_session.get(PipelineRunModel, run_id)
        saved_provider_snapshots = (
            runtime_session.query(ProviderSnapshotModel)
            .filter(ProviderSnapshotModel.run_id == run_id)
            .all()
        )
        saved_model_bindings = (
            runtime_session.query(ModelBindingSnapshotModel)
            .filter(ModelBindingSnapshotModel.run_id == run_id)
            .all()
        )

    assert attached_is_existing
    assert saved_run is not None
    assert saved_run.updated_at.replace(tzinfo=UTC) == LATER
    assert saved_run.template_snapshot_ref == f"template-snapshot-{run_id}"
    assert saved_run.runtime_limit_snapshot_ref == "runtime-limit-snapshot-provider"
    assert saved_run.provider_call_policy_snapshot_ref == (
        "provider-call-policy-snapshot-provider"
    )
    assert saved_run.graph_definition_ref == "graph-definition-pending"
    assert saved_run.graph_thread_ref == "graph-thread-pending"
    assert len(saved_provider_snapshots) == 1
    assert saved_provider_snapshots[0].api_key_ref == "env:AI_DEVFLOW_CREDENTIAL_ALPHA"
    assert saved_provider_snapshots[0].capabilities["model_id"] == "alpha-chat"
    assert len(saved_model_bindings) == 9
    assert {
        binding.provider_snapshot_id for binding in saved_model_bindings
    } == {saved_provider_snapshots[0].snapshot_id}
    assert {
        binding.binding_type for binding in saved_model_bindings
    } == {"agent_role", *INTERNAL_MODEL_BINDING_TYPES}
