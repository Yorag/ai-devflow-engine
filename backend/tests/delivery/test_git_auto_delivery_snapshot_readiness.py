from __future__ import annotations

from pathlib import Path

from backend.app.db.base import DatabaseRole
from backend.app.delivery.git_auto import GitAutoDeliveryAdapter
from backend.app.domain.enums import (
    CredentialStatus,
    DeliveryReadinessStatus,
)
from backend.tests.delivery.test_git_auto_delivery import (
    NOW,
    RecordingAudit,
    RecordingConfirmationPort,
    RecordingRunLog,
    RecordingWorkspaceBoundary,
    build_context_factory,
    build_input,
    build_manager,
    build_registry,
    confirmation_resolver,
    git,
    remote_git,
    seed_git_auto_run,
)
from backend.tests.fixtures import fixture_git_repository


def test_git_auto_delivery_fails_without_frozen_snapshot_before_git_side_effects(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager, snapshot_ref=None)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()

    with manager.session(DatabaseRole.RUNTIME) as session:
        adapter = GitAutoDeliveryAdapter(
            tool_registry=build_registry(
                runtime_session=session,
                audit=audit,
                remote_clients={"acme/app": repo.remote_client},
            ),
            execution_context_factory=build_context_factory(
                audit=audit,
                run_log=RecordingRunLog(),
                confirmations=confirmations,
                workspace_boundary=RecordingWorkspaceBoundary(),
            ),
            repository_path=repo.root,
            confirmation_resolver=confirmation_resolver(confirmations),
            now=lambda: NOW,
        )
        result = adapter.deliver(build_input())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.error_code == "delivery_snapshot_missing"
    assert confirmations.calls == []
    assert git(repo, "branch", "--show-current") == "main"
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/run-1",
        check=False,
    ) == ""


def test_git_auto_delivery_fails_when_frozen_snapshot_is_not_ready(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(
        manager,
        credential_status=CredentialStatus.UNBOUND,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
    )
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()

    with manager.session(DatabaseRole.RUNTIME) as session:
        adapter = GitAutoDeliveryAdapter(
            tool_registry=build_registry(
                runtime_session=session,
                audit=audit,
                remote_clients={"acme/app": repo.remote_client},
            ),
            execution_context_factory=build_context_factory(
                audit=audit,
                run_log=RecordingRunLog(),
                confirmations=confirmations,
                workspace_boundary=RecordingWorkspaceBoundary(),
            ),
            repository_path=repo.root,
            confirmation_resolver=confirmation_resolver(confirmations),
            now=lambda: NOW,
        )
        result = adapter.deliver(build_input())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.error_code == "delivery_snapshot_not_ready"
    assert result.error.safe_details["failed_step"] == "read_delivery_snapshot"
    assert result.audit_refs == ["audit-intent-call-read_delivery_snapshot"]
    assert confirmations.calls == []
    assert git(repo, "branch", "--show-current") == "main"
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/run-1",
        check=False,
    ) == ""
    assert repo.remote_client.requests == []


def test_git_auto_delivery_asserts_current_snapshot_ref_without_project_fallback(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager, snapshot_ref="delivery-snapshot-frozen")
    audit = RecordingAudit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        adapter = GitAutoDeliveryAdapter(
            tool_registry=build_registry(
                runtime_session=session,
                audit=audit,
                remote_clients={"acme/app": repo.remote_client},
            ),
            execution_context_factory=build_context_factory(
                audit=audit,
                run_log=RecordingRunLog(),
                confirmations=RecordingConfirmationPort(),
                workspace_boundary=RecordingWorkspaceBoundary(),
            ),
            repository_path=repo.root,
            now=lambda: NOW,
        )
        result = adapter.deliver(
            build_input(delivery_channel_snapshot_ref="delivery-snapshot-other")
        )

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.safe_details["reason"] == "delivery_snapshot_ref_mismatch"
    assert result.audit_refs == ["audit-intent-call-read_delivery_snapshot"]
    assert git(repo, "branch", "--show-current") == "main"
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/run-1",
        check=False,
    ) == ""
    assert repo.remote_client.requests == []


def test_git_auto_delivery_uses_frozen_snapshot_repository_identifier(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager, repository_identifier="acme/frozen-app")
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()

    with manager.session(DatabaseRole.RUNTIME) as session:
        adapter = GitAutoDeliveryAdapter(
            tool_registry=build_registry(
                runtime_session=session,
                audit=audit,
                remote_clients={"acme/frozen-app": repo.remote_client},
            ),
            execution_context_factory=build_context_factory(
                audit=audit,
                run_log=RecordingRunLog(),
                confirmations=confirmations,
                workspace_boundary=RecordingWorkspaceBoundary(),
            ),
            repository_path=repo.root,
            confirmation_resolver=confirmation_resolver(confirmations),
            now=lambda: NOW,
        )
        result = adapter.deliver(build_input())

    assert result.status == "succeeded"
    assert repo.remote_client.requests[-1]["repository_identifier"] == "acme/frozen-app"
