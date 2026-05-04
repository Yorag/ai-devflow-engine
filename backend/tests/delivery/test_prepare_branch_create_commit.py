from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.log import AuditLogEntryModel, LogBase, LogPayloadModel
from backend.app.db.session import DatabaseManager
from backend.app.delivery.scm import (
    CREATE_COMMIT_TOOL_NAME,
    PREPARE_BRANCH_TOOL_NAME,
    CreateCommitTool,
    PrepareBranchTool,
    ScmDeliveryAdapter,
)
from backend.app.domain.enums import StageType, ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.audit import AuditService
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.observability import AuditResult
from backend.app.tools.execution_gate import (
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolWorkspaceBoundaryError,
)
from backend.app.tools.protocol import ToolAuditRef, ToolResult, ToolResultStatus
from backend.app.tools.registry import ToolRegistry
from backend.app.tools.risk import ToolConfirmationGrant, ToolConfirmationRequestRecord
from backend.tests.fixtures import FixtureGitRepository, fixture_git_repository


NOW = datetime(2026, 5, 4, 21, 0, 0, tzinfo=UTC)


def build_audit_manager(tmp_path: Path) -> tuple[DatabaseManager, RuntimeDataSettings]:
    settings = EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    manager = DatabaseManager.from_environment_settings(settings)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    return manager, RuntimeDataSettings.from_environment_settings(settings)


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
            tool_confirmation_id="tool-confirmation-1",
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
        self.checked_targets.append(target)
        if target == self.blocked_target:
            raise ToolWorkspaceBoundaryError(
                "Tool target is outside the run workspace.",
                target=target,
            )


def build_trace(*, tool_confirmation_id: str | None = None) -> TraceContext:
    return TraceContext(
        request_id="request-d5-2",
        trace_id="trace-d5-2",
        correlation_id="correlation-d5-2",
        span_id="span-d5-2",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-delivery",
        tool_confirmation_id=tool_confirmation_id,
        created_at=NOW,
    )


def build_registry(audit: RecordingAudit | None) -> ToolRegistry:
    adapter = ScmDeliveryAdapter(audit_service=audit)
    return ToolRegistry(
        [
            PrepareBranchTool(adapter=adapter),
            CreateCommitTool(adapter=adapter),
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
                    [PREPARE_BRANCH_TOOL_NAME, CREATE_COMMIT_TOOL_NAME]
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


def git(repo: FixtureGitRepository, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo.root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_prepare_branch_requires_confirmation_before_git_write(tmp_path: Path) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = build_registry(audit)
    context = build_context(
        audit=audit,
        run_log=run_log,
        confirmations=confirmations,
        workspace_boundary=workspace_boundary,
    )

    pending = registry.execute(
        request(
            PREPARE_BRANCH_TOOL_NAME,
            {
                "repository_path": str(repo.root),
                "branch_name": "delivery/run-1",
                "base_branch": "main",
                "delivery_record_id": "delivery-record-1",
            },
        ),
        context,
    )

    assert pending.status is ToolResultStatus.WAITING_CONFIRMATION
    assert workspace_boundary.checked_targets == [str(repo.root)]
    assert git(repo, "branch", "--show-current") == "main"
    assert confirmations.calls[0]["tool_name"] == PREPARE_BRANCH_TOOL_NAME
    assert run_log.records[-1]["error_code"] == "tool_confirmation_required"


def test_prepare_branch_checks_repository_workspace_boundary_before_git_write(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary(blocked_target=str(repo.root))
    registry = build_registry(audit)

    result = registry.execute(
        request(
            PREPARE_BRANCH_TOOL_NAME,
            {
                "repository_path": str(repo.root),
                "branch_name": "delivery/run-1",
                "base_branch": "main",
                "delivery_record_id": "delivery-record-1",
            },
        ),
        build_context(
            audit=audit,
            run_log=run_log,
            confirmations=confirmations,
            workspace_boundary=workspace_boundary,
        ),
    )

    assert result.status is ToolResultStatus.BLOCKED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert git(repo, "branch", "--show-current") == "main"
    assert audit.intents == []
    assert confirmations.calls == []
    assert workspace_boundary.checked_targets == [str(repo.root)]


def test_prepare_branch_creates_branch_through_registry_and_audits(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = build_registry(audit)
    context = build_context(
        audit=audit,
        run_log=run_log,
        confirmations=confirmations,
        workspace_boundary=workspace_boundary,
    )

    result = execute_confirmed(
        registry,
        request(
            PREPARE_BRANCH_TOOL_NAME,
            {
                "repository_path": str(repo.root),
                "branch_name": "delivery/run-1",
                "base_branch": "main",
                "delivery_record_id": "delivery-record-1",
            },
        ),
        context,
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["branch_name"] == "delivery/run-1"
    assert result.output_payload["base_branch"] == "main"
    assert result.output_payload["head_sha"] == repo.head
    assert result.side_effect_refs == [
        "git_branch:delivery/run-1",
        "delivery_record:delivery-record-1",
    ]
    assert workspace_boundary.checked_targets == [str(repo.root), str(repo.root)]
    assert git(repo, "branch", "--show-current") == "delivery/run-1"
    assert "fixture-git-repo" not in (result.output_preview or "")
    assert audit.calls[0]["tool_name"] == PREPARE_BRANCH_TOOL_NAME
    assert audit.calls[0]["branch_name"] == "delivery/run-1"
    assert audit.calls[0]["delivery_record_id"] == "delivery-record-1"
    assert run_log.records[-1]["tool_name"] == PREPARE_BRANCH_TOOL_NAME
    assert run_log.records[-1]["status"] == "succeeded"


def test_create_commit_commits_workspace_changes_and_excludes_runtime_logs(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = build_registry(audit)
    context = build_context(
        audit=audit,
        run_log=run_log,
        confirmations=confirmations,
        workspace_boundary=workspace_boundary,
    )
    git(repo, "switch", "-c", "delivery/run-1")

    result = execute_confirmed(
        registry,
        request(
            CREATE_COMMIT_TOOL_NAME,
            {
                "repository_path": str(repo.root),
                "commit_message": "Implement delivery changes",
                "delivery_record_id": "delivery-record-1",
            },
        ),
        context,
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    commit_sha = result.output_payload["commit_sha"]
    assert isinstance(commit_sha, str) and len(commit_sha) == 40
    assert result.output_payload["changed_files"] == ["src/workspace_change.txt"]
    assert workspace_boundary.checked_targets == [str(repo.root), str(repo.root)]
    assert result.side_effect_refs == [
        f"git_commit:{commit_sha}",
        "delivery_record:delivery-record-1",
    ]
    assert "src/workspace_change.txt" in git(
        repo,
        "show",
        "--name-only",
        "--format=",
        "HEAD",
    )
    assert ".runtime/logs/run-1.jsonl" not in git(
        repo,
        "show",
        "--name-only",
        "--format=",
        "HEAD",
    )
    assert audit.calls[-1]["tool_name"] == CREATE_COMMIT_TOOL_NAME
    assert audit.calls[-1]["commit_sha"] == commit_sha
    assert audit.calls[-1]["changed_files"] == ["src/workspace_change.txt"]
    assert audit.calls[-1]["delivery_record_id"] == "delivery-record-1"
    assert run_log.records[-1]["status"] == "succeeded"


def test_create_commit_excludes_tracked_runtime_log_deletions(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = build_registry(audit)
    context = build_context(
        audit=audit,
        run_log=run_log,
        confirmations=confirmations,
        workspace_boundary=workspace_boundary,
    )
    git(repo, "switch", "-c", "delivery/run-1")
    git(repo, "add", "-f", ".runtime/logs/run-1.jsonl")
    git(repo, "commit", "-m", "Track runtime log fixture")
    repo.runtime_log_sample.unlink()

    result = execute_confirmed(
        registry,
        request(
            CREATE_COMMIT_TOOL_NAME,
            {
                "repository_path": str(repo.root),
                "commit_message": "Implement delivery changes",
                "delivery_record_id": "delivery-record-1",
            },
        ),
        context,
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["changed_files"] == ["src/workspace_change.txt"]
    commit_diff = git(repo, "show", "--name-status", "--format=", "HEAD")
    assert "A\tsrc/workspace_change.txt" in commit_diff
    assert ".runtime/logs/run-1.jsonl" not in commit_diff
    assert ".runtime/logs/run-1.jsonl" in git(
        repo,
        "ls-tree",
        "-r",
        "--name-only",
        "HEAD",
    )
    assert audit.calls[-1]["changed_files"] == ["src/workspace_change.txt"]


def test_create_commit_succeeds_with_concrete_audit_service_contract(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    gate_audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    manager, runtime_settings = build_audit_manager(tmp_path)
    git(repo, "switch", "-c", "delivery/run-1")

    with manager.session(DatabaseRole.LOG) as log_session:
        concrete_audit = AuditService(
            log_session,
            audit_writer=JsonlLogWriter(runtime_settings),
        )
        registry = ToolRegistry(
            [
                CreateCommitTool(
                    adapter=ScmDeliveryAdapter(audit_service=concrete_audit)
                ),
            ]
        )
        context = build_context(
            audit=gate_audit,
            run_log=run_log,
            confirmations=confirmations,
            workspace_boundary=workspace_boundary,
        )

        result = execute_confirmed(
            registry,
            request(
                CREATE_COMMIT_TOOL_NAME,
                {
                    "repository_path": str(repo.root),
                    "commit_message": "Implement delivery changes",
                    "delivery_record_id": "delivery-record-1",
                },
            ),
            context,
            confirmations,
        )

    assert result.status is ToolResultStatus.SUCCEEDED

    with manager.session(DatabaseRole.LOG) as log_session:
        saved_audit = (
            log_session.query(AuditLogEntryModel)
            .filter_by(action=f"tool.{CREATE_COMMIT_TOOL_NAME}.succeeded")
            .one()
        )
        saved_payload = log_session.get(LogPayloadModel, saved_audit.metadata_ref)

    assert saved_audit.result is AuditResult.SUCCEEDED
    assert saved_payload is not None
    assert saved_payload.summary["payload_type"] == "audit_metadata_summary"
    assert saved_audit.metadata_excerpt is not None
    assert "git commit -m" in saved_audit.metadata_excerpt
    assert "exit_code" in saved_audit.metadata_excerpt
    assert "duration_ms" in saved_audit.metadata_excerpt
    assert "stdout_excerpt" in saved_audit.metadata_excerpt
    assert "stderr_excerpt" in saved_audit.metadata_excerpt
    assert str(result.output_payload["commit_sha"]) in saved_audit.metadata_excerpt
    assert "delivery-record-1" in saved_audit.metadata_excerpt


def test_git_cli_ignores_hostile_repository_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = fixture_git_repository(tmp_path, repo_name="target-repo")
    hostile_repo = fixture_git_repository(tmp_path, repo_name="hostile-repo")
    monkeypatch.setenv("GIT_DIR", str(hostile_repo.git_dir))
    monkeypatch.setenv("GIT_WORK_TREE", str(hostile_repo.root))
    monkeypatch.setenv("GIT_INDEX_FILE", str(hostile_repo.git_dir / "index"))

    result = ScmDeliveryAdapter().run_git_cli(
        repo.root,
        ["rev-parse", "--show-toplevel"],
    )

    assert result.returncode == 0
    assert Path(result.stdout.strip()).resolve() == repo.root.resolve()


def test_create_commit_fails_without_commit_changes_and_records_audit(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    repo.workspace_change_file.unlink()
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = build_registry(audit)
    context = build_context(
        audit=audit,
        run_log=run_log,
        confirmations=confirmations,
        workspace_boundary=workspace_boundary,
    )

    result = execute_confirmed(
        registry,
        request(
            CREATE_COMMIT_TOOL_NAME,
            {
                "repository_path": str(repo.root),
                "commit_message": "No changes",
                "delivery_record_id": "delivery-record-1",
            },
        ),
        context,
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.DELIVERY_GIT_CLI_FAILED
    assert result.error.safe_details["reason"] == "no_changes_to_commit"
    assert workspace_boundary.checked_targets == [str(repo.root), str(repo.root)]
    assert audit.errors[-1]["tool_name"] == CREATE_COMMIT_TOOL_NAME
    assert audit.errors[-1]["error_code"] is ErrorCode.DELIVERY_GIT_CLI_FAILED
    assert run_log.records[-1]["error_code"] == "delivery_git_cli_failed"


def test_git_tools_reject_allowed_tools_drift_before_git_state_changes(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    registry = build_registry(audit)

    result = registry.execute(
        request(
            PREPARE_BRANCH_TOOL_NAME,
            {
                "repository_path": str(repo.root),
                "branch_name": "delivery/run-1",
                "base_branch": "main",
                "delivery_record_id": "delivery-record-1",
            },
        ),
        build_context(allowed_tools=[], audit=audit, run_log=RecordingRunLog()),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_NOT_ALLOWED
    assert git(repo, "branch", "--show-current") == "main"
    assert audit.intents == []


def test_git_tools_fail_closed_when_concrete_audit_service_is_missing(
    tmp_path: Path,
) -> None:
    repo = fixture_git_repository(tmp_path)
    gate_audit = RecordingAudit()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = ToolRegistry(
        [
            PrepareBranchTool(adapter=ScmDeliveryAdapter(audit_service=None)),
        ]
    )
    context = build_context(
        audit=gate_audit,
        confirmations=confirmations,
        workspace_boundary=workspace_boundary,
    )

    result = execute_confirmed(
        registry,
        request(
            PREPARE_BRANCH_TOOL_NAME,
            {
                "repository_path": str(repo.root),
                "branch_name": "delivery/run-1",
                "base_branch": "main",
                "delivery_record_id": "delivery-record-1",
            },
        ),
        context,
        confirmations,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert workspace_boundary.checked_targets == [str(repo.root), str(repo.root)]
    assert git(repo, "branch", "--show-current") == "main"
