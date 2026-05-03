from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING


_EXPORTS = {
    "FakeChatModel": ("backend.tests.fixtures.providers", "FakeChatModel"),
    "FakeProvider": ("backend.tests.fixtures.providers", "FakeProvider"),
    "FakeProviderError": ("backend.tests.fixtures.providers", "FakeProviderError"),
    "FakeProviderFailure": ("backend.tests.fixtures.providers", "FakeProviderError"),
    "FakeTool": ("backend.tests.fixtures.tools", "FakeTool"),
    "FixtureGitRepository": ("backend.tests.fixtures.workspace", "FixtureGitRepository"),
    "FixtureWorkspaceRepo": ("backend.tests.fixtures.workspace", "FixtureWorkspaceRepo"),
    "MockRemoteDeliveryClient": (
        "backend.tests.fixtures.delivery",
        "MockRemoteDeliveryClient",
    ),
    "WorkspaceBoundary": ("backend.tests.fixtures.tools", "WorkspaceBoundary"),
    "delivery_channel_snapshot_fixture": (
        "backend.tests.fixtures.delivery",
        "delivery_channel_snapshot_fixture",
    ),
    "fake_chat_model_fixture": (
        "backend.tests.fixtures.providers",
        "fake_chat_model_fixture",
    ),
    "fake_provider_fixture": ("backend.tests.fixtures.providers", "fake_provider_fixture"),
    "fake_tool_fixture": ("backend.tests.fixtures.tools", "fake_tool_fixture"),
    "fixture_git_repository": ("backend.tests.fixtures.workspace", "fixture_git_repository"),
    "fixture_workspace_repo": ("backend.tests.fixtures.workspace", "fixture_workspace_repo"),
    "model_binding_snapshot_fixture": (
        "backend.tests.fixtures.providers",
        "model_binding_snapshot_fixture",
    ),
    "mock_remote_delivery_client": (
        "backend.tests.fixtures.delivery",
        "mock_remote_delivery_client",
    ),
    "provider_capabilities_fixture": (
        "backend.tests.fixtures.providers",
        "provider_capabilities_fixture",
    ),
    "provider_snapshot_fixture": (
        "backend.tests.fixtures.providers",
        "provider_snapshot_fixture",
    ),
    "runtime_settings_snapshot_fixture": (
        "backend.tests.fixtures.settings",
        "runtime_settings_snapshot_fixture",
    ),
    "settings_override_fixture": (
        "backend.tests.fixtures.settings",
        "settings_override_fixture",
    ),
    "snapshot_model_capabilities_fixture": (
        "backend.tests.fixtures.providers",
        "provider_capabilities_fixture",
    ),
    "tool_trace_fixture": ("backend.tests.fixtures.tools", "tool_trace_fixture"),
    "workspace_boundary_fixture": (
        "backend.tests.fixtures.tools",
        "workspace_boundary_fixture",
    ),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from backend.tests.fixtures.delivery import (
        MockRemoteDeliveryClient,
        delivery_channel_snapshot_fixture,
        mock_remote_delivery_client,
    )
    from backend.tests.fixtures.providers import (
        FakeChatModel,
        FakeProvider,
        FakeProviderError,
        fake_chat_model_fixture,
        fake_provider_fixture,
        model_binding_snapshot_fixture,
        provider_capabilities_fixture,
        provider_snapshot_fixture,
    )
    from backend.tests.fixtures.settings import (
        runtime_settings_snapshot_fixture,
        settings_override_fixture,
    )
    from backend.tests.fixtures.tools import (
        FakeTool,
        WorkspaceBoundary,
        fake_tool_fixture,
        tool_trace_fixture,
        workspace_boundary_fixture,
    )
    from backend.tests.fixtures.workspace import (
        FixtureGitRepository,
        FixtureWorkspaceRepo,
        fixture_git_repository,
        fixture_workspace_repo,
    )
