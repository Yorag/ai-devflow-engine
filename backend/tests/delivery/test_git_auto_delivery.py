from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.runtime import (
    DeliveryChannelSnapshotModel,
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.delivery.base import DeliveryAdapterInput
from backend.app.delivery.git_auto import GitAutoDeliveryAdapter
from backend.app.delivery.scm import (
    CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
    CREATE_COMMIT_TOOL_NAME,
    PREPARE_BRANCH_TOOL_NAME,
    PUSH_BRANCH_TOOL_NAME,
    READ_DELIVERY_SNAPSHOT_TOOL_NAME,
    CreateCodeReviewRequestTool,
    CreateCommitTool,
    PrepareBranchTool,
    PushBranchTool,
    ReadDeliverySnapshotTool,
    ScmDeliveryAdapter,
)
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    StageStatus,
    StageType,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import (
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolWorkspaceBoundaryError,
)
from backend.app.tools.protocol import ToolAuditRef, ToolResult
from backend.app.tools.registry import ToolRegistry
from backend.app.tools.risk import ToolConfirmationGrant, ToolConfirmationRequestRecord
from backend.tests.fixtures import FixtureGitRepository, fixture_git_repository


NOW = datetime(2026, 5, 5, 10, 0, 0, tzinfo=UTC)
ALL_DELIVERY_TOOLS = [
    READ_DELIVERY_SNAPSHOT_TOOL_NAME,
    PREPARE_BRANCH_TOOL_NAME,
    CREATE_COMMIT_TOOL_NAME,
    PUSH_BRANCH_TOOL_NAME,
    CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
]


class RecordingAudit:
    def __init__(self) -> None:
        self.intents: list[dict[str, object]] = []
        self.rejections: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []
        self.errors: list[dict[str, object]] = []

    def record_tool_intent(
        self,
        *,
        request: ToolExecutionRequest,
        tool_name: str,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.intents.append(
            {
                "tool_name": tool_name,
                "request_id": trace_context.request_id,
                "trace_id": trace_context.trace_id,
                "correlation_id": trace_context.correlation_id,
                "span_id": trace_context.span_id,
                "parent_span_id": trace_context.parent_span_id,
                "run_id": trace_context.run_id,
                "stage_run_id": trace_context.stage_run_id,
            }
        )
        return ToolAuditRef(
            audit_id=f"audit-intent-{request.call_id}",
            action="tool.intent",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-intent-{request.call_id}",
        )

    def record_tool_rejection(
        self,
        *,
        request: ToolExecutionRequest,
        error_code: object,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.rejections.append(
            {
                "tool_name": request.tool_name,
                "error_code": getattr(error_code, "value", error_code),
            }
        )
        return ToolAuditRef(
            audit_id=f"audit-reject-{request.call_id}",
            action="tool.rejected",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-reject-{request.call_id}",
        )

    def record_tool_call(self, **kwargs: object) -> ToolAuditRef:
        self.calls.append(dict(kwargs))
        trace_context = kwargs["trace_context"]
        return ToolAuditRef(
            audit_id=f"audit-call-{len(self.calls)}",
            action=f"tool.{kwargs['tool_name']}.succeeded",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-call-{len(self.calls)}",
        )

    def record_tool_error(self, **kwargs: object) -> ToolAuditRef:
        self.errors.append(dict(kwargs))
        trace_context = kwargs["trace_context"]
        return ToolAuditRef(
            audit_id=f"audit-error-{len(self.errors)}",
            action=f"tool.{kwargs['tool_name']}.failed",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-error-{len(self.errors)}",
        )


class RecordingRunLog:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record_tool_result(
        self,
        *,
        request: ToolExecutionRequest,
        result: ToolResult,
        duration_ms: int,
    ) -> None:
        self.records.append(
            {
                "tool_name": request.tool_name,
                "status": result.status.value,
                "error_code": result.error.error_code.value if result.error else None,
                "duration_ms": duration_ms,
            }
        )


class RecordingConfirmationPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_request(self, **kwargs: object) -> ToolConfirmationRequestRecord:
        self.calls.append(dict(kwargs))
        return ToolConfirmationRequestRecord(
            tool_confirmation_id=f"tool-confirmation-{len(self.calls)}",
            confirmation_object_ref=str(kwargs["confirmation_object_ref"]),
        )


class RecordingWorkspaceBoundary:
    def __init__(self, *, blocked_target: str | None = None) -> None:
        self.blocked_target = blocked_target
        self.checked_targets: list[str] = []

    def assert_inside_workspace(
        self,
        target: str,
        *,
        trace_context: TraceContext,
    ) -> None:
        del trace_context
        self.checked_targets.append(target)
        if target == self.blocked_target:
            raise ToolWorkspaceBoundaryError(
                "Tool target is outside the run workspace.",
                target=target,
            )


def build_trace(*, tool_confirmation_id: str | None = None) -> TraceContext:
    return TraceContext(
        request_id="request-git-auto-delivery",
        trace_id="trace-git-auto-delivery",
        correlation_id="correlation-git-auto-delivery",
        span_id="span-git-auto-delivery",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-delivery",
        tool_confirmation_id=tool_confirmation_id,
        created_at=NOW,
    )


def build_context_factory(
    *,
    allowed_tools: list[str] | None = None,
    audit: RecordingAudit | None = None,
    run_log: RecordingRunLog | None = None,
    confirmations: RecordingConfirmationPort | None = None,
    workspace_boundary: RecordingWorkspaceBoundary | None = None,
) -> Callable[[TraceContext], ToolExecutionContext]:
    def factory(trace_context: TraceContext) -> ToolExecutionContext:
        return ToolExecutionContext(
            stage_type=StageType.DELIVERY_INTEGRATION,
            stage_contracts={
                StageType.DELIVERY_INTEGRATION.value: {
                    "allowed_tools": ALL_DELIVERY_TOOLS
                    if allowed_tools is None
                    else allowed_tools
                }
            },
            trace_context=trace_context,
            workspace_boundary=workspace_boundary,
            audit_recorder=audit,
            run_log_recorder=run_log,
            confirmation_port=confirmations,
            runtime_tool_timeout_seconds=10,
            platform_tool_timeout_hard_limit_seconds=30,
        )

    return factory


def confirmation_resolver(
    confirmations: RecordingConfirmationPort,
) -> Callable[
    [ToolExecutionRequest, ToolResult, ToolExecutionContext],
    ToolExecutionRequest | None,
]:
    def resolve(
        request: ToolExecutionRequest,
        result: ToolResult,
        context: ToolExecutionContext,
    ) -> ToolExecutionRequest | None:
        del context
        if result.error is None or result.tool_confirmation_ref is None:
            return None
        return ToolExecutionRequest(
            tool_name=request.tool_name,
            call_id=request.call_id,
            input_payload=request.input_payload,
            trace_context=request.trace_context.model_copy(
                update={"tool_confirmation_id": result.tool_confirmation_ref}
            ),
            coordination_key=request.coordination_key,
            confirmation_grant=ToolConfirmationGrant(
                tool_confirmation_id=result.tool_confirmation_ref,
                confirmation_object_ref=str(
                    confirmations.calls[-1]["confirmation_object_ref"]
                ),
                tool_name=request.tool_name,
                input_digest=str(result.error.safe_details["input_digest"]),
                target_summary=str(result.error.safe_details["target_summary"]),
                risk_level=ToolRiskLevel.HIGH_RISK,
                risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
            ),
        )

    return resolve


def mismatched_confirmation_resolver(
    confirmations: RecordingConfirmationPort,
) -> Callable[
    [ToolExecutionRequest, ToolResult, ToolExecutionContext],
    ToolExecutionRequest | None,
]:
    def resolve(
        request: ToolExecutionRequest,
        result: ToolResult,
        context: ToolExecutionContext,
    ) -> ToolExecutionRequest | None:
        confirmed = confirmation_resolver(confirmations)(request, result, context)
        if confirmed is None:
            return None
        return confirmed.model_copy(
            update={
                "input_payload": {
                    **confirmed.input_payload,
                    "branch_name": "delivery/hostile-run-1",
                }
            }
        )

    return resolve


def in_place_mismatched_confirmation_resolver(
    confirmations: RecordingConfirmationPort,
) -> Callable[
    [ToolExecutionRequest, ToolResult, ToolExecutionContext],
    ToolExecutionRequest | None,
]:
    def resolve(
        request: ToolExecutionRequest,
        result: ToolResult,
        context: ToolExecutionContext,
    ) -> ToolExecutionRequest | None:
        del context
        if result.error is None or result.tool_confirmation_ref is None:
            return None
        request.input_payload["branch_name"] = "delivery/hostile-run-1"
        request.trace_context = request.trace_context.model_copy(
            update={"tool_confirmation_id": result.tool_confirmation_ref}
        )
        request.confirmation_grant = ToolConfirmationGrant(
            tool_confirmation_id=result.tool_confirmation_ref,
            confirmation_object_ref=str(
                confirmations.calls[-1]["confirmation_object_ref"]
            ),
            tool_name=request.tool_name,
            input_digest=str(result.error.safe_details["input_digest"]),
            target_summary=str(result.error.safe_details["target_summary"]),
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
        )
        return request

    return resolve


def in_place_tainted_identity_confirmation_resolver(
    confirmations: RecordingConfirmationPort,
) -> Callable[
    [ToolExecutionRequest, ToolResult, ToolExecutionContext],
    ToolExecutionRequest | None,
]:
    def resolve(
        request: ToolExecutionRequest,
        result: ToolResult,
        context: ToolExecutionContext,
    ) -> ToolExecutionRequest | None:
        del context
        if result.error is None or result.tool_confirmation_ref is None:
            return None
        request.call_id = "call-hostile-prepare_branch"
        request.coordination_key = "hostile-coordination-key"
        request.trace_context = request.trace_context.model_copy(
            update={"tool_confirmation_id": result.tool_confirmation_ref}
        )
        request.confirmation_grant = ToolConfirmationGrant(
            tool_confirmation_id=result.tool_confirmation_ref,
            confirmation_object_ref=str(
                confirmations.calls[-1]["confirmation_object_ref"]
            ),
            tool_name=request.tool_name,
            input_digest=str(result.error.safe_details["input_digest"]),
            target_summary=str(result.error.safe_details["target_summary"]),
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
        )
        return request

    return resolve


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    return manager


def seed_git_auto_run(
    manager: DatabaseManager,
    *,
    snapshot_ref: str | None = "delivery-snapshot-1",
    credential_status: CredentialStatus = CredentialStatus.READY,
    readiness_status: DeliveryReadinessStatus = DeliveryReadinessStatus.READY,
    repository_identifier: str | None = "acme/app",
) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limits-1",
                    run_id="run-1",
                    agent_limits={},
                    context_limits={},
                    source_config_version="test",
                    hard_limits_version="test",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-policy-1",
                    run_id="run-1",
                    provider_call_policy={},
                    source_config_version="test",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        if snapshot_ref is not None:
            session.add(
                DeliveryChannelSnapshotModel(
                    delivery_channel_snapshot_id=snapshot_ref,
                    run_id="run-1",
                    source_delivery_channel_id="delivery-default",
                    delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
                    scm_provider_type=ScmProviderType.GITHUB,
                    repository_identifier=repository_identifier,
                    default_branch="main",
                    code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
                    credential_ref="env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
                    credential_status=credential_status,
                    readiness_status=readiness_status,
                    readiness_message="delivery is ready.",
                    last_validated_at=NOW,
                    schema_version="delivery-channel-snapshot-v1",
                    created_at=NOW,
                )
            )
        session.commit()
        session.add(
            PipelineRunModel(
                run_id="run-1",
                session_id="session-1",
                project_id="project-default",
                attempt_index=1,
                status=RunStatus.RUNNING,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-1",
                graph_definition_ref="graph-definition-1",
                graph_thread_ref="thread-1",
                workspace_ref="workspace-1",
                runtime_limit_snapshot_ref="runtime-limits-1",
                provider_call_policy_snapshot_ref="provider-policy-1",
                delivery_channel_snapshot_ref=snapshot_ref,
                current_stage_run_id="stage-run-delivery",
                trace_id="trace-git-auto-delivery",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            StageRunModel(
                stage_run_id="stage-run-delivery",
                run_id="run-1",
                stage_type=StageType.DELIVERY_INTEGRATION,
                status=StageStatus.RUNNING,
                attempt_index=1,
                graph_node_key="delivery_integration",
                stage_contract_ref="stage-contract-delivery-integration",
                input_ref=None,
                output_ref=None,
                summary="Delivering.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def build_input(**overrides: Any) -> DeliveryAdapterInput:
    values: dict[str, Any] = {
        "run_id": "run-1",
        "stage_run_id": "stage-run-delivery",
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "delivery_mode": DeliveryMode.GIT_AUTO_DELIVERY,
        "trace_context": build_trace(),
    }
    values.update(overrides)
    return DeliveryAdapterInput(**values)


def build_registry(
    *,
    runtime_session: Any,
    audit: RecordingAudit | None,
    remote_clients: dict[str, object] | None = None,
) -> ToolRegistry:
    return ToolRegistry(
        [
            ReadDeliverySnapshotTool(
                adapter=ScmDeliveryAdapter(
                    runtime_session=runtime_session,
                    audit_service=audit,
                    remote_clients=remote_clients or {},
                )
            ),
            PrepareBranchTool(adapter=ScmDeliveryAdapter(audit_service=audit)),
            CreateCommitTool(adapter=ScmDeliveryAdapter(audit_service=audit)),
            PushBranchTool(adapter=ScmDeliveryAdapter(audit_service=audit)),
            CreateCodeReviewRequestTool(
                adapter=ScmDeliveryAdapter(
                    audit_service=audit,
                    remote_clients=remote_clients or {},
                )
            ),
        ]
    )


def git(repo: FixtureGitRepository, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo.root,
        check=check,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def remote_git(repo: FixtureGitRepository, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo.remote_path,
        check=check,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_git_auto_delivery_executes_frozen_snapshot_tool_chain_through_registry(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [
                ReadDeliverySnapshotTool(
                    adapter=ScmDeliveryAdapter(
                        runtime_session=session,
                        audit_service=audit,
                        remote_clients={"acme/app": repo.remote_client},
                    )
                ),
                PrepareBranchTool(adapter=ScmDeliveryAdapter(audit_service=audit)),
                CreateCommitTool(adapter=ScmDeliveryAdapter(audit_service=audit)),
                PushBranchTool(adapter=ScmDeliveryAdapter(audit_service=audit)),
                CreateCodeReviewRequestTool(
                    adapter=ScmDeliveryAdapter(
                        audit_service=audit,
                        remote_clients={"acme/app": repo.remote_client},
                    )
                ),
            ]
        )
        adapter = GitAutoDeliveryAdapter(
            tool_registry=registry,
            execution_context_factory=build_context_factory(
                audit=audit,
                run_log=run_log,
                confirmations=confirmations,
                workspace_boundary=workspace_boundary,
            ),
            repository_path=repo.root,
            remote_name="origin",
            confirmation_resolver=confirmation_resolver(confirmations),
            now=lambda: NOW,
        )
        result = adapter.deliver(build_input())

    assert result.status == "succeeded"
    assert result.delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
    assert result.result_ref == "git-auto-delivery-result:run-1"
    assert result.process_ref == "git-auto-delivery-process:run-1"
    assert result.branch_name == "delivery/run-1"
    assert isinstance(result.commit_sha, str) and len(result.commit_sha) == 40
    assert result.code_review_url == "https://example.test/acme/app/pull/1"
    assert result.audit_refs == [
        "audit-intent-call-read_delivery_snapshot",
        "audit-intent-call-prepare_branch",
        "audit-intent-call-create_commit",
        "audit-intent-call-push_branch",
        "audit-intent-call-create_code_review_request",
    ]
    assert [record["tool_name"] for record in audit.intents] == [
        "read_delivery_snapshot",
        "prepare_branch",
        "create_commit",
        "push_branch",
        "create_code_review_request",
    ]
    assert [record["tool_name"] for record in run_log.records] == [
        "read_delivery_snapshot",
        "prepare_branch",
        "prepare_branch",
        "create_commit",
        "create_commit",
        "push_branch",
        "push_branch",
        "create_code_review_request",
        "create_code_review_request",
    ]
    assert [record["status"] for record in run_log.records] == [
        "succeeded",
        "waiting_confirmation",
        "succeeded",
        "waiting_confirmation",
        "succeeded",
        "waiting_confirmation",
        "succeeded",
        "waiting_confirmation",
        "succeeded",
    ]
    assert [call["tool_name"] for call in confirmations.calls] == [
        "prepare_branch",
        "create_commit",
        "push_branch",
        "create_code_review_request",
    ]
    assert repo.remote_client.requests == [
        {
            "request_type": "pull_request",
            "repository_identifier": "acme/app",
            "source_branch": "delivery/run-1",
            "target_branch": "main",
            "title": "Deliver run run-1",
            "body": "Delivery branch is ready for review.",
        }
    ]
    assert remote_git(repo, "rev-parse", "delivery/run-1") == result.commit_sha


def test_git_auto_delivery_uses_child_spans_for_each_tool(tmp_path: Path) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = build_registry(
            runtime_session=session,
            audit=audit,
            remote_clients={"acme/app": repo.remote_client},
        )
        adapter = GitAutoDeliveryAdapter(
            tool_registry=registry,
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
    assert [record["request_id"] for record in audit.intents] == [
        "request-git-auto-delivery",
        "request-git-auto-delivery",
        "request-git-auto-delivery",
        "request-git-auto-delivery",
        "request-git-auto-delivery",
    ]
    assert [record["trace_id"] for record in audit.intents] == [
        "trace-git-auto-delivery",
        "trace-git-auto-delivery",
        "trace-git-auto-delivery",
        "trace-git-auto-delivery",
        "trace-git-auto-delivery",
    ]
    assert [record["correlation_id"] for record in audit.intents] == [
        "correlation-git-auto-delivery",
        "correlation-git-auto-delivery",
        "correlation-git-auto-delivery",
        "correlation-git-auto-delivery",
        "correlation-git-auto-delivery",
    ]
    assert [record["span_id"] for record in audit.intents] == [
        "git-auto-delivery-read_delivery_snapshot",
        "git-auto-delivery-prepare_branch",
        "git-auto-delivery-create_commit",
        "git-auto-delivery-push_branch",
        "git-auto-delivery-create_code_review_request",
    ]
    assert [record["parent_span_id"] for record in audit.intents] == [
        "span-git-auto-delivery",
        "span-git-auto-delivery",
        "span-git-auto-delivery",
        "span-git-auto-delivery",
        "span-git-auto-delivery",
    ]


def test_git_auto_delivery_blocks_when_confirmation_is_required_without_resolver(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager)
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
            now=lambda: NOW,
        )
        result = adapter.deliver(build_input())

    assert result.status == "blocked"
    assert result.error is not None
    assert result.error.error_code == "tool_confirmation_required"
    assert result.error.safe_details["failed_step"] == "prepare_branch"
    assert git(repo, "branch", "--show-current") == "main"
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/run-1",
        check=False,
    ) == ""


def test_git_auto_delivery_rejects_confirmation_request_mismatch(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager)
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
            confirmation_resolver=mismatched_confirmation_resolver(confirmations),
            now=lambda: NOW,
        )
        result = adapter.deliver(build_input())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.error_code == "internal_error"
    assert result.error.safe_details["failed_step"] == "prepare_branch"
    assert result.error.safe_details["reason"] == "confirmation_request_mismatch"
    assert result.error.safe_details["mismatched_fields"] == ["input_payload"]
    assert git(repo, "branch", "--show-current") == "main"
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/hostile-run-1",
        check=False,
    ) == ""
    assert repo.remote_client.requests == []


def test_git_auto_delivery_rejects_in_place_confirmation_request_mutation(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager)
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
            confirmation_resolver=in_place_mismatched_confirmation_resolver(
                confirmations
            ),
            now=lambda: NOW,
        )
        result = adapter.deliver(build_input())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.error_code == "internal_error"
    assert result.error.safe_details["failed_step"] == "prepare_branch"
    assert result.error.safe_details["reason"] == "confirmation_request_mismatch"
    assert result.error.safe_details["mismatched_fields"] == ["input_payload"]
    assert len(confirmations.calls) == 1
    assert git(repo, "branch", "--show-current") == "main"
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/hostile-run-1",
        check=False,
    ) == ""
    assert repo.remote_client.requests == []


def test_git_auto_delivery_uses_original_call_id_for_mismatch_diagnostics(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    manager = build_manager(tmp_path)
    seed_git_auto_run(manager)
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
            confirmation_resolver=in_place_tainted_identity_confirmation_resolver(
                confirmations
            ),
            now=lambda: NOW,
        )
        result = adapter.deliver(build_input())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.safe_details["reason"] == "confirmation_request_mismatch"
    assert result.error.safe_details["mismatched_fields"] == [
        "call_id",
        "coordination_key",
    ]
    assert result.error.safe_details["tool_call_id"] == "call-prepare_branch"
    assert git(repo, "branch", "--show-current") == "main"
    assert repo.remote_client.requests == []


def test_git_auto_delivery_rejects_non_git_auto_mode(tmp_path: Path) -> None:
    repo = fixture_git_repository(tmp_path)
    adapter = GitAutoDeliveryAdapter(
        tool_registry=ToolRegistry([]),
        execution_context_factory=build_context_factory(),
        repository_path=repo.root,
        now=lambda: NOW,
    )

    with pytest.raises(ValueError, match="git_auto_delivery"):
        adapter.deliver(build_input(delivery_mode=DeliveryMode.DEMO_DELIVERY))
