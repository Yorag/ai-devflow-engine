from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from backend.app.api.error_codes import ErrorCode
from backend.app.delivery.scm import (
    CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
    PUSH_BRANCH_TOOL_NAME,
    CreateCodeReviewRequestTool,
    GitCliResult,
    PushBranchTool,
    ScmDeliveryAdapter,
)
from backend.app.domain.enums import StageType, ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import (
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolWorkspaceBoundaryError,
)
from backend.app.tools.protocol import ToolAuditRef, ToolResult, ToolResultStatus
from backend.app.tools.registry import ToolRegistry
from backend.app.tools.risk import ToolConfirmationGrant, ToolConfirmationRequestRecord
from backend.tests.fixtures import FixtureGitRepository, fixture_git_repository


NOW = datetime(2026, 5, 4, 23, 30, 0, tzinfo=UTC)


class RecordingAudit:
    def __init__(self) -> None:
        self.intents: list[dict[str, object]] = []
        self.rejections: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []
        self.errors: list[dict[str, object]] = []

    def record_tool_intent(self, **kwargs: object) -> ToolAuditRef:
        self.intents.append(dict(kwargs))
        trace_context = kwargs["trace_context"]
        request = kwargs["request"]
        return ToolAuditRef(
            audit_id=f"audit-intent-{request.call_id}",
            action="tool.intent",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-intent-{request.call_id}",
        )

    def record_tool_rejection(self, **kwargs: object) -> ToolAuditRef:
        self.rejections.append(dict(kwargs))
        trace_context = kwargs["trace_context"]
        request = kwargs["request"]
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


class SecretFailingRemoteClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def create_pull_request(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(dict(kwargs))
        raise RuntimeError("Authorization: Bearer secret-token")


class RecordingPushAdapter(ScmDeliveryAdapter):
    def __init__(self, audit: RecordingAudit) -> None:
        super().__init__(audit_service=audit)
        object.__setattr__(self, "git_calls", [])

    def run_git_cli(
        self,
        repository_path: str | Path,
        args: list[str],
        timeout_seconds: float | None = None,
    ) -> GitCliResult:
        del repository_path, timeout_seconds
        self.git_calls.append(list(args))
        if args[:2] == ["check-ref-format", "--branch"]:
            return GitCliResult(returncode=0, stdout="", stderr="", duration_ms=1)
        if args[:2] == ["remote", "get-url"]:
            return GitCliResult(
                returncode=0,
                stdout="https://user:secret-token@example.test/acme/app.git\n",
                stderr="",
                duration_ms=1,
            )
        if args[:1] == ["rev-parse"]:
            return GitCliResult(
                returncode=0,
                stdout="0123456789abcdef0123456789abcdef01234567\n",
                stderr="",
                duration_ms=1,
            )
        if args[:1] == ["push"]:
            return GitCliResult(
                returncode=0,
                stdout="Pushed to https://user:secret-token@example.test/acme/app.git\n",
                stderr="To https://user:secret-token@example.test/acme/app.git\n",
                duration_ms=1,
            )
        return GitCliResult(
            returncode=128,
            stdout="",
            stderr="unexpected git call",
            duration_ms=1,
        )


def build_trace(*, tool_confirmation_id: str | None = None) -> TraceContext:
    return TraceContext(
        request_id="request-d5-3",
        trace_id="trace-d5-3",
        correlation_id="correlation-d5-3",
        span_id="span-d5-3",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-delivery",
        tool_confirmation_id=tool_confirmation_id,
        created_at=NOW,
    )


def build_registry(
    audit: RecordingAudit | None,
    *,
    remote_clients: dict[str, object] | None = None,
) -> ToolRegistry:
    adapter = ScmDeliveryAdapter(
        audit_service=audit,
        remote_clients=remote_clients or {},
    )
    return ToolRegistry(
        [
            PushBranchTool(adapter=adapter),
            CreateCodeReviewRequestTool(adapter=adapter),
        ]
    )


def build_context(
    *,
    allowed_tools: list[str] | None = None,
    audit: RecordingAudit | None = None,
    run_log: RecordingRunLog | None = None,
    confirmations: RecordingConfirmationPort | None = None,
    workspace_boundary: RecordingWorkspaceBoundary | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        stage_type=StageType.DELIVERY_INTEGRATION,
        stage_contracts={
            StageType.DELIVERY_INTEGRATION.value: {
                "allowed_tools": (
                    [PUSH_BRANCH_TOOL_NAME, CREATE_CODE_REVIEW_REQUEST_TOOL_NAME]
                    if allowed_tools is None
                    else allowed_tools
                )
            }
        },
        trace_context=build_trace(),
        workspace_boundary=workspace_boundary,
        audit_recorder=audit,
        run_log_recorder=run_log,
        confirmation_port=confirmations,
        runtime_tool_timeout_seconds=10,
        platform_tool_timeout_hard_limit_seconds=30,
    )


def request(tool_name: str, payload: dict[str, object]) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_name=tool_name,
        call_id=f"call-{tool_name}",
        input_payload=payload,
        trace_context=build_trace(),
        coordination_key=f"coordination-{tool_name}",
    )


def execute_confirmed(
    registry: ToolRegistry,
    request: ToolExecutionRequest,
    context: ToolExecutionContext,
    confirmations: RecordingConfirmationPort,
) -> ToolResult:
    pending = registry.execute(request, context)
    assert pending.status is ToolResultStatus.WAITING_CONFIRMATION
    assert pending.error is not None
    confirmed = ToolExecutionRequest(
        tool_name=request.tool_name,
        call_id=request.call_id,
        input_payload=request.input_payload,
        trace_context=build_trace(tool_confirmation_id=pending.tool_confirmation_ref),
        coordination_key=request.coordination_key,
        confirmation_grant=ToolConfirmationGrant(
            tool_confirmation_id=str(pending.tool_confirmation_ref),
            confirmation_object_ref=str(
                confirmations.calls[-1]["confirmation_object_ref"]
            ),
            tool_name=request.tool_name,
            input_digest=str(pending.error.safe_details["input_digest"]),
            target_summary=str(pending.error.safe_details["target_summary"]),
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
        ),
    )
    return registry.execute(confirmed, context)


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


def commit_fixture_change(repo: FixtureGitRepository) -> str:
    git(repo, "switch", "-c", "delivery/run-1")
    git(repo, "add", "src/workspace_change.txt")
    git(repo, "commit", "-m", "Implement delivery changes")
    return git(repo, "rev-parse", "HEAD")


def review_request_payload(
    request_type: str = "pull_request",
) -> dict[str, object]:
    return {
        "repository_identifier": "acme/app",
        "source_branch": "delivery/run-1",
        "target_branch": "main",
        "title": "Implement delivery changes",
        "body": "Delivery branch is ready for review.",
        "code_review_request_type": request_type,
        "delivery_record_id": "delivery-record-1",
    }


def push_branch_payload(repo: FixtureGitRepository) -> dict[str, object]:
    return {
        "repository_path": str(repo.root),
        "remote_name": "origin",
        "branch_name": "delivery/run-1",
        "delivery_record_id": "delivery-record-1",
    }


def test_push_branch_requires_confirmation_before_git_push(tmp_path: Path) -> None:
    repo = fixture_git_repository(tmp_path)
    pushed_sha = commit_fixture_change(repo)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = build_registry(audit)

    pending = registry.execute(
        request(PUSH_BRANCH_TOOL_NAME, push_branch_payload(repo)),
        build_context(
            audit=audit,
            run_log=run_log,
            confirmations=confirmations,
            workspace_boundary=workspace_boundary,
        ),
    )

    assert pending.status is ToolResultStatus.WAITING_CONFIRMATION
    assert workspace_boundary.checked_targets == [str(repo.root)]
    assert confirmations.calls[0]["tool_name"] == PUSH_BRANCH_TOOL_NAME
    assert run_log.records[-1]["error_code"] == "tool_confirmation_required"
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/run-1",
        check=False,
    ) == ""
    assert pushed_sha == git(repo, "rev-parse", "HEAD")


def test_push_branch_pushes_fixture_branch_through_registry_and_audits(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    pushed_sha = commit_fixture_change(repo)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = build_registry(audit)

    result = execute_confirmed(
        registry,
        request(PUSH_BRANCH_TOOL_NAME, push_branch_payload(repo)),
        build_context(
            audit=audit,
            run_log=run_log,
            confirmations=confirmations,
            workspace_boundary=workspace_boundary,
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "remote_name": "origin",
        "branch_name": "delivery/run-1",
        "remote_ref": "origin/delivery/run-1",
        "pushed_sha": pushed_sha,
        "delivery_record_id": "delivery-record-1",
    }
    assert result.side_effect_refs == [
        "git_push:origin/delivery/run-1",
        f"git_commit:{pushed_sha}",
        "delivery_record:delivery-record-1",
    ]
    assert remote_git(repo, "rev-parse", "delivery/run-1") == pushed_sha
    assert str(repo.remote_path) not in (result.output_preview or "")
    assert audit.calls[-1]["tool_name"] == PUSH_BRANCH_TOOL_NAME
    assert audit.calls[-1]["remote_name"] == "origin"
    assert audit.calls[-1]["remote_ref"] == "origin/delivery/run-1"
    assert audit.calls[-1]["delivery_record_id"] == "delivery-record-1"
    assert run_log.records[-1]["status"] == "succeeded"


def test_push_branch_uses_local_branch_ref_for_commit_verification_and_push(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    adapter = RecordingPushAdapter(audit)
    registry = ToolRegistry([PushBranchTool(adapter=adapter)])

    result = execute_confirmed(
        registry,
        request(PUSH_BRANCH_TOOL_NAME, push_branch_payload(repo)),
        build_context(
            allowed_tools=[PUSH_BRANCH_TOOL_NAME],
            audit=audit,
            confirmations=confirmations,
            workspace_boundary=RecordingWorkspaceBoundary(),
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert ["rev-parse", "refs/heads/delivery/run-1^{commit}"] in adapter.git_calls
    assert [
        "push",
        "origin",
        "refs/heads/delivery/run-1:refs/heads/delivery/run-1",
    ] in adapter.git_calls
    assert ["rev-parse", "delivery/run-1"] not in adapter.git_calls
    assert ["push", "origin", "delivery/run-1:delivery/run-1"] not in adapter.git_calls


def test_push_branch_redacts_git_push_output_from_success_audit(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    adapter = RecordingPushAdapter(audit)
    registry = ToolRegistry([PushBranchTool(adapter=adapter)])

    result = execute_confirmed(
        registry,
        request(PUSH_BRANCH_TOOL_NAME, push_branch_payload(repo)),
        build_context(
            allowed_tools=[PUSH_BRANCH_TOOL_NAME],
            audit=audit,
            confirmations=confirmations,
            workspace_boundary=RecordingWorkspaceBoundary(),
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    serialized_audit = str(audit.calls[-1])
    assert "secret-token" not in serialized_audit
    assert audit.calls[-1]["stdout_excerpt"] == "[redacted]"
    assert audit.calls[-1]["stderr_excerpt"] == "[redacted]"


def test_push_branch_checks_workspace_boundary_before_confirmation_or_git_push(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    commit_fixture_change(repo)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary(blocked_target=str(repo.root))
    registry = build_registry(audit)

    result = registry.execute(
        request(PUSH_BRANCH_TOOL_NAME, push_branch_payload(repo)),
        build_context(
            audit=audit,
            run_log=RecordingRunLog(),
            confirmations=confirmations,
            workspace_boundary=workspace_boundary,
        ),
    )

    assert result.status is ToolResultStatus.BLOCKED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert audit.intents == []
    assert confirmations.calls == []
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/run-1",
        check=False,
    ) == ""


def test_create_review_request_requires_confirmation_before_remote_call(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    registry = build_registry(audit, remote_clients={"acme/app": repo.remote_client})

    pending = registry.execute(
        request(
            CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
            review_request_payload("pull_request"),
        ),
        build_context(
            audit=audit,
            run_log=run_log,
            confirmations=confirmations,
        ),
    )

    assert pending.status is ToolResultStatus.WAITING_CONFIRMATION
    assert repo.remote_client.requests == []
    assert confirmations.calls[0]["tool_name"] == CREATE_CODE_REVIEW_REQUEST_TOOL_NAME
    assert run_log.records[-1]["error_code"] == "tool_confirmation_required"


def test_create_review_request_supports_pull_request_with_mock_client(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    registry = build_registry(audit, remote_clients={"acme/app": repo.remote_client})

    result = execute_confirmed(
        registry,
        request(
            CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
            review_request_payload("pull_request"),
        ),
        build_context(
            audit=audit,
            run_log=run_log,
            confirmations=confirmations,
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "repository_identifier": "acme/app",
        "source_branch": "delivery/run-1",
        "target_branch": "main",
        "code_review_request_type": "pull_request",
        "code_review_url": "https://example.test/acme/app/pull/1",
        "code_review_number": 1,
        "delivery_record_id": "delivery-record-1",
    }
    assert result.side_effect_refs == [
        "code_review_request:pull_request:acme/app:1",
        "delivery_record:delivery-record-1",
    ]
    assert repo.remote_client.requests == [
        {
            "request_type": "pull_request",
            "repository_identifier": "acme/app",
            "source_branch": "delivery/run-1",
            "target_branch": "main",
            "title": "Implement delivery changes",
            "body": "Delivery branch is ready for review.",
        }
    ]
    assert audit.calls[-1]["tool_name"] == CREATE_CODE_REVIEW_REQUEST_TOOL_NAME
    assert audit.calls[-1]["repository_identifier"] == "acme/app"
    assert audit.calls[-1]["code_review_url"] == "https://example.test/acme/app/pull/1"
    assert audit.calls[-1]["code_review_number"] == 1
    assert run_log.records[-1]["status"] == "succeeded"


def test_create_review_request_supports_merge_request_with_mock_client(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    registry = build_registry(audit, remote_clients={"acme/app": repo.remote_client})

    result = execute_confirmed(
        registry,
        request(
            CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
            review_request_payload("merge_request"),
        ),
        build_context(
            audit=audit,
            run_log=RecordingRunLog(),
            confirmations=confirmations,
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["code_review_request_type"] == "merge_request"
    assert result.output_payload["code_review_url"] == (
        "https://example.test/acme/app/merge_requests/1"
    )
    assert result.side_effect_refs == [
        "code_review_request:merge_request:acme/app:1",
        "delivery_record:delivery-record-1",
    ]
    assert repo.remote_client.requests[-1]["request_type"] == "merge_request"


def test_create_review_request_remote_failure_redacts_secret_error_summary(
    tmp_path: Path,
) -> None:
    fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    remote_client = SecretFailingRemoteClient()
    registry = build_registry(audit, remote_clients={"acme/app": remote_client})

    result = execute_confirmed(
        registry,
        request(
            CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
            review_request_payload("pull_request"),
        ),
        build_context(
            audit=audit,
            run_log=RecordingRunLog(),
            confirmations=confirmations,
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.DELIVERY_REMOTE_REQUEST_FAILED
    serialized_error = str(result.error.safe_details)
    serialized_audit = str(audit.errors[-1])
    assert "secret-token" not in serialized_error
    assert "secret-token" not in serialized_audit
    assert result.error.safe_details["reason"] == "remote_request_failed"
    assert audit.errors[-1]["tool_name"] == CREATE_CODE_REVIEW_REQUEST_TOOL_NAME
    assert audit.errors[-1]["error_code"] is ErrorCode.DELIVERY_REMOTE_REQUEST_FAILED


def test_create_review_request_fails_for_missing_remote_client_without_calling_remote(
    tmp_path: Path,
) -> None:
    fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    registry = build_registry(audit, remote_clients={})

    result = execute_confirmed(
        registry,
        request(
            CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
            review_request_payload("pull_request"),
        ),
        build_context(audit=audit, confirmations=confirmations),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.DELIVERY_REMOTE_REQUEST_FAILED
    assert result.error.safe_details["reason"] == "remote_client_unavailable"
    assert audit.errors[-1]["reason"] == "remote_client_unavailable"


def test_create_review_request_fail_closed_without_concrete_audit_before_remote_call(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    gate_audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    registry = ToolRegistry(
        [
            CreateCodeReviewRequestTool(
                adapter=ScmDeliveryAdapter(
                    audit_service=None,
                    remote_clients={"acme/app": repo.remote_client},
                )
            )
        ]
    )

    result = execute_confirmed(
        registry,
        request(
            CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
            review_request_payload("pull_request"),
        ),
        build_context(
            allowed_tools=[CREATE_CODE_REVIEW_REQUEST_TOOL_NAME],
            audit=gate_audit,
            confirmations=confirmations,
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert repo.remote_client.requests == []


def test_d5_3_tools_reject_allowed_tools_drift_before_side_effects(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    commit_fixture_change(repo)
    audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    registry = build_registry(audit, remote_clients={"acme/app": repo.remote_client})

    result = registry.execute(
        request(PUSH_BRANCH_TOOL_NAME, push_branch_payload(repo)),
        build_context(
            allowed_tools=[],
            audit=audit,
            run_log=RecordingRunLog(),
            confirmations=confirmations,
            workspace_boundary=RecordingWorkspaceBoundary(),
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_NOT_ALLOWED
    assert audit.intents == []
    assert confirmations.calls == []
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/run-1",
        check=False,
    ) == ""


def test_d5_3_tools_fail_closed_when_concrete_audit_service_is_missing(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    commit_fixture_change(repo)
    gate_audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    registry = ToolRegistry(
        [PushBranchTool(adapter=ScmDeliveryAdapter(audit_service=None))]
    )

    result = execute_confirmed(
        registry,
        request(PUSH_BRANCH_TOOL_NAME, push_branch_payload(repo)),
        build_context(
            allowed_tools=[PUSH_BRANCH_TOOL_NAME],
            audit=gate_audit,
            confirmations=confirmations,
            workspace_boundary=RecordingWorkspaceBoundary(),
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert remote_git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/delivery/run-1",
        check=False,
    ) == ""
