from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.models.runtime import DeliveryChannelSnapshotModel
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ScmProviderType,
    StageType,
)
from backend.app.providers.base import ProviderConfig
from backend.app.providers.provider_registry import ProviderRegistry
from backend.app.schemas.runtime_settings import (
    ModelBindingSnapshotRead,
    PlatformRuntimeSettingsRead,
    ProviderSnapshotRead,
)
from backend.app.tools.execution_gate import (
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolWorkspaceBoundaryError,
)
from backend.app.tools.protocol import (
    ToolPermissionBoundary,
    ToolResultStatus,
    ToolSideEffectLevel,
)
from backend.app.tools.registry import ToolRegistry


NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)


def test_settings_override_fixture_only_changes_test_local_runtime_paths(
    tmp_path: Path,
) -> None:
    from backend.tests.fixtures import settings_override_fixture

    settings = settings_override_fixture(tmp_path)

    assert isinstance(settings, EnvironmentSettings)
    assert settings.resolve_platform_runtime_root() == (tmp_path / ".runtime").resolve()
    assert settings.resolve_workspace_root() == (
        tmp_path / ".runtime" / "workspaces"
    ).resolve()
    assert settings.frontend_api_base_url == EnvironmentSettings().frontend_api_base_url

    with pytest.raises(ValueError, match="frontend_api_base_url"):
        settings_override_fixture(
            tmp_path,
            frontend_api_base_url="http://localhost:9000/api",
        )


def test_settings_override_fixture_allows_workspace_and_credential_overrides(
    tmp_path: Path,
) -> None:
    from backend.tests.fixtures import settings_override_fixture

    settings = settings_override_fixture(
        tmp_path,
        workspace_root=tmp_path / "custom-workspaces",
        credential_env_prefixes=("TEAM_", "OPENAI_"),
    )

    assert settings.resolve_workspace_root() == (tmp_path / "custom-workspaces").resolve()
    assert settings.is_allowed_credential_env_name("TEAM_TOKEN")
    assert not settings.is_allowed_credential_env_name("OTHER_TOKEN")


def test_runtime_settings_snapshot_fixture_returns_formal_schema() -> None:
    from backend.tests.fixtures import runtime_settings_snapshot_fixture

    snapshot = runtime_settings_snapshot_fixture(updated_at=NOW)

    assert isinstance(snapshot, PlatformRuntimeSettingsRead)
    assert snapshot.settings_id == "platform-runtime-settings"
    assert snapshot.version.config_version == "platform-runtime-settings-config-v1"
    assert snapshot.version.schema_version == "platform-runtime-settings-v1"
    assert snapshot.version.hard_limits_version == "platform-hard-limits-v1"
    assert snapshot.version.updated_at == NOW


def test_fake_provider_fixture_uses_formal_provider_snapshots() -> None:
    from backend.tests.fixtures import FakeChatModel, FakeProvider, fake_provider_fixture

    fake = fake_provider_fixture()

    assert isinstance(fake, FakeProvider)
    assert isinstance(fake.chat_model, FakeChatModel)
    assert isinstance(fake.config, ProviderConfig)
    assert fake.provider_snapshot.snapshot_id == fake.config.provider_snapshot_id
    assert (
        fake.model_binding_snapshot.snapshot_id
        == fake.config.model_binding_snapshot_id
    )
    assert (
        fake.model_binding_snapshot.provider_snapshot_id
        == fake.provider_snapshot.snapshot_id
    )


def test_fake_provider_supports_scripted_success_tool_call_and_failures() -> None:
    from backend.tests.fixtures import fake_provider_fixture
    from backend.tests.fixtures.providers import FakeProviderError

    fake = fake_provider_fixture()
    fake.enqueue_structured_success({"decision_type": "submit_stage_artifact"})
    fake.enqueue_tool_call_request("read_file", {"path": "src/app.py"})
    fake.enqueue_timeout()
    fake.enqueue_rate_limit()
    fake.enqueue_network_error()

    assert fake.chat_model.invoke_structured() == {
        "decision_type": "submit_stage_artifact"
    }
    assert fake.chat_model.invoke_structured() == {
        "decision_type": "request_tool_call",
        "tool_name": "read_file",
        "input_payload": {"path": "src/app.py"},
    }

    with pytest.raises(FakeProviderError) as timeout_error:
        fake.chat_model.invoke_structured()
    assert timeout_error.value.failure_kind == "timeout"

    with pytest.raises(FakeProviderError) as rate_limit_error:
        fake.chat_model.invoke_structured()
    assert rate_limit_error.value.failure_kind == "rate_limit"

    with pytest.raises(FakeProviderError) as network_error:
        fake.chat_model.invoke_structured()
    assert network_error.value.failure_kind == "network_error"


def test_fake_provider_structured_failure_can_carry_catalog_error_code() -> None:
    from backend.tests.fixtures import fake_provider_fixture
    from backend.tests.fixtures.providers import FakeProviderError

    fake = fake_provider_fixture()
    fake.enqueue_structured_failure(
        error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
        message="Provider retry attempts were exhausted.",
    )

    with pytest.raises(FakeProviderError) as error:
        fake.chat_model.invoke_structured()

    assert error.value.error_code is ErrorCode.PROVIDER_RETRY_EXHAUSTED
    assert error.value.failure_kind == "structured_failure"


def test_fake_tool_executes_through_tool_registry_and_workspace_gate() -> None:
    from backend.tests.fixtures import fake_tool_fixture, tool_trace_fixture

    tool = fake_tool_fixture()
    registry = ToolRegistry([tool])
    trace = tool_trace_fixture()
    context = ToolExecutionContext(
        stage_type=StageType.CODE_GENERATION,
        stage_contracts={StageType.CODE_GENERATION.value: {"allowed_tools": [tool.name]}},
        trace_context=trace,
        workspace_boundary=tool.workspace_boundary,
        runtime_tool_timeout_seconds=5,
        platform_tool_timeout_hard_limit_seconds=30,
    )

    result = registry.execute(tool.build_request(trace_context=trace), context)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert tool.calls[0].tool_name == tool.name
    assert tool.calls[0].timeout_seconds == 5.0


def test_fake_tool_contract_exercises_input_schema_and_audit_gate() -> None:
    from backend.tests.fixtures import fake_tool_fixture, tool_trace_fixture

    trace = tool_trace_fixture()
    tool = fake_tool_fixture(
        name="write_file",
        description="Write one file.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string", "minLength": 1},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        permission_boundary=ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("path",),
        ),
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
        audit_required=True,
    )
    registry = ToolRegistry([tool])
    context = ToolExecutionContext(
        stage_type=StageType.CODE_GENERATION,
        stage_contracts={StageType.CODE_GENERATION.value: {"allowed_tools": [tool.name]}},
        trace_context=trace,
        workspace_boundary=tool.workspace_boundary,
    )

    invalid = registry.execute(
        ToolExecutionRequest(
            tool_name=tool.name,
            call_id="invalid-write",
            input_payload={"path": "src/app.py"},
            trace_context=trace,
            coordination_key="fixture-invalid-write",
        ),
        context,
    )
    blocked = registry.execute(
        ToolExecutionRequest(
            tool_name=tool.name,
            call_id="audit-blocked-write",
            input_payload={"path": "src/app.py", "content": "print('ok')"},
            trace_context=trace,
            coordination_key="fixture-audit-blocked-write",
        ),
        context,
    )

    assert invalid.status is ToolResultStatus.FAILED
    assert invalid.error is not None
    assert invalid.error.error_code is ErrorCode.TOOL_INPUT_SCHEMA_INVALID
    assert blocked.status is ToolResultStatus.FAILED
    assert blocked.error is not None
    assert blocked.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert tool.calls == []


def test_fake_tool_contract_stays_under_tool_name_and_allowed_tools_gate() -> None:
    from backend.tests.fixtures import fake_tool_fixture, tool_trace_fixture

    trace = tool_trace_fixture()
    tool = fake_tool_fixture()
    registry = ToolRegistry([tool])
    denied_context = ToolExecutionContext(
        stage_type=StageType.CODE_GENERATION,
        stage_contracts={StageType.CODE_GENERATION.value: {"allowed_tools": ["write_file"]}},
        trace_context=trace,
        workspace_boundary=tool.workspace_boundary,
    )
    allowed_context = ToolExecutionContext(
        stage_type=StageType.CODE_GENERATION,
        stage_contracts={StageType.CODE_GENERATION.value: {"allowed_tools": [tool.name]}},
        trace_context=trace,
        workspace_boundary=tool.workspace_boundary,
    )

    unknown = registry.execute(
        ToolExecutionRequest(
            tool_name="grep",
            call_id="fixture-unknown-tool",
            input_payload={"path": "src/app.py"},
            trace_context=trace,
            coordination_key="fixture-unknown-tool",
        ),
        allowed_context,
    )
    denied = registry.execute(
        ToolExecutionRequest(
            tool_name=tool.name,
            call_id="fixture-not-allowed-tool",
            input_payload={"path": "src/app.py"},
            trace_context=trace,
            coordination_key="fixture-not-allowed-tool",
        ),
        denied_context,
    )

    assert unknown.status is ToolResultStatus.FAILED
    assert unknown.error is not None
    assert unknown.error.error_code is ErrorCode.TOOL_UNKNOWN
    assert denied.status is ToolResultStatus.FAILED
    assert denied.error is not None
    assert denied.error.error_code is ErrorCode.TOOL_NOT_ALLOWED
    assert tool.calls == []


def test_workspace_boundary_fixture_normalizes_equivalent_relative_paths() -> None:
    from backend.tests.fixtures import tool_trace_fixture, workspace_boundary_fixture

    boundary = workspace_boundary_fixture(blocked_target="../outside.py")

    with pytest.raises(ToolWorkspaceBoundaryError) as blocked:
        boundary.assert_inside_workspace(
            "src/../../outside.py",
            trace_context=tool_trace_fixture(),
        )

    assert blocked.value.target == "src/../../outside.py"
    assert boundary.checked_targets == ["../outside.py"]


def test_fixture_workspace_repo_stays_under_tmp_and_contains_runtime_log_exclusion_sample(
    tmp_path: Path,
) -> None:
    from backend.tests.fixtures import FixtureWorkspaceRepo, fixture_workspace_repo

    repo = fixture_workspace_repo(tmp_path)

    assert isinstance(repo, FixtureWorkspaceRepo)
    assert repo.root.is_relative_to(tmp_path.resolve())
    assert repo.baseline_file.exists()
    assert repo.workspace_change_file.exists()
    assert repo.runtime_log_sample.exists()
    assert (repo.root / "src" / "app.py").exists()


def test_fixture_workspace_helpers_reject_paths_outside_tmp_path(tmp_path: Path) -> None:
    from backend.tests.fixtures import fixture_git_repository, fixture_workspace_repo

    with pytest.raises(ValueError, match="tmp_path"):
        fixture_workspace_repo(tmp_path, repo_name="../escape")

    with pytest.raises(ValueError, match="tmp_path"):
        fixture_git_repository(tmp_path, repo_name="../escape")


def test_fixture_git_repository_creates_committed_baseline_and_mock_remote(
    tmp_path: Path,
) -> None:
    from backend.tests.fixtures import FixtureGitRepository, fixture_git_repository

    repo = fixture_git_repository(tmp_path)

    assert isinstance(repo, FixtureGitRepository)
    assert repo.root.is_relative_to(tmp_path.resolve())
    assert repo.remote_path.is_relative_to(tmp_path.resolve())
    assert repo.git_dir.exists()
    assert repo.branch == "main"
    assert repo.head
    assert repo.remote_path.exists()
    assert repo.workspace_change_file.exists()
    assert repo.runtime_log_sample.exists()
    assert repo.remote_client.requests == []


def test_mock_remote_delivery_client_records_success_and_failure_without_network() -> None:
    from backend.tests.fixtures import mock_remote_delivery_client

    client = mock_remote_delivery_client()
    success = client.create_pull_request(
        repository_identifier="acme/app",
        source_branch="feature/test",
        target_branch="main",
        title="Test PR",
        body="Fixture delivery request",
    )
    merge = client.create_merge_request(
        repository_identifier="acme/app",
        source_branch="feature/test",
        target_branch="main",
        title="Test MR",
        body="Fixture delivery request",
    )

    assert success["url"].startswith("https://example.test/")
    assert success["request_type"] == "pull_request"
    assert merge["request_type"] == "merge_request"
    assert client.requests[0]["repository_identifier"] == "acme/app"

    failing = mock_remote_delivery_client(fail_next=True)
    with pytest.raises(RuntimeError, match="mock remote request failed"):
        failing.create_pull_request(
            repository_identifier="acme/app",
            source_branch="feature/test",
            target_branch="main",
            title="Test PR",
            body="Fixture delivery request",
        )


def test_delivery_channel_snapshot_fixture_matches_current_runtime_model_shape() -> None:
    from backend.tests.fixtures import delivery_channel_snapshot_fixture

    snapshot = delivery_channel_snapshot_fixture(created_at=NOW, last_validated_at=NOW)

    assert isinstance(snapshot, DeliveryChannelSnapshotModel)
    assert snapshot.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
    assert snapshot.scm_provider_type is ScmProviderType.GITHUB
    assert snapshot.code_review_request_type is CodeReviewRequestType.PULL_REQUEST
    assert snapshot.credential_status is CredentialStatus.READY
    assert snapshot.readiness_status is DeliveryReadinessStatus.READY
    assert snapshot.schema_version == "delivery-channel-snapshot-v1"


def test_delivery_channel_snapshot_fixture_can_model_not_ready_state() -> None:
    from backend.tests.fixtures import delivery_channel_snapshot_fixture

    snapshot = delivery_channel_snapshot_fixture(
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        credential_status=CredentialStatus.UNBOUND,
        readiness_message="DeliveryChannel readiness has not been validated.",
    )

    assert snapshot.readiness_status is DeliveryReadinessStatus.UNCONFIGURED
    assert snapshot.credential_status is CredentialStatus.UNBOUND
    assert snapshot.readiness_message == "DeliveryChannel readiness has not been validated."


def test_fake_tool_defaults_align_with_tool_execution_gate_suite() -> None:
    from backend.tests.fixtures import fake_tool_fixture

    tool = fake_tool_fixture()

    assert tool.bindable_description().name == "read_file"
    assert tool.name == "read_file"
    assert tool.category == "workspace"
    assert tool.default_timeout_seconds == 5.0
    assert tool.permission_boundary == ToolPermissionBoundary(
        boundary_type="workspace",
        requires_workspace=True,
        resource_scopes=("current_run_workspace",),
        workspace_target_paths=("path",),
    )


def test_provider_fixture_defaults_align_with_provider_registry_suite() -> None:
    from backend.tests.fixtures import (
        model_binding_snapshot_fixture,
        provider_snapshot_fixture,
    )

    provider_snapshot = provider_snapshot_fixture(created_at=NOW)
    model_binding_snapshot = model_binding_snapshot_fixture(
        created_at=NOW,
        provider_snapshot_id=provider_snapshot.snapshot_id,
        provider_id=provider_snapshot.provider_id,
        model_id=provider_snapshot.model_id,
    )
    expected_config = ProviderRegistry(
        provider_snapshots=[provider_snapshot],
        model_binding_snapshots=[model_binding_snapshot],
    ).resolve(
        model_binding_snapshot.snapshot_id,
        requires_tool_calling=True,
    )

    assert isinstance(provider_snapshot, ProviderSnapshotRead)
    assert isinstance(model_binding_snapshot, ModelBindingSnapshotRead)
    assert provider_snapshot.source_config_version == "provider-config-v1"
    assert provider_snapshot.schema_version == "provider-snapshot-v1"
    assert model_binding_snapshot.source_config_version == "template-binding-v1"
    assert model_binding_snapshot.schema_version == "model-binding-snapshot-v1"
    assert expected_config.provider_snapshot_id == provider_snapshot.snapshot_id


def test_delivery_fixture_defaults_align_with_delivery_snapshot_gate_suite() -> None:
    from backend.tests.fixtures import delivery_channel_snapshot_fixture

    snapshot = delivery_channel_snapshot_fixture(created_at=NOW, last_validated_at=NOW)

    assert snapshot.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
    assert snapshot.scm_provider_type is ScmProviderType.GITHUB
    assert snapshot.code_review_request_type is CodeReviewRequestType.PULL_REQUEST
    assert snapshot.credential_status is CredentialStatus.READY
    assert snapshot.readiness_status is DeliveryReadinessStatus.READY
    assert snapshot.schema_version == "delivery-channel-snapshot-v1"
