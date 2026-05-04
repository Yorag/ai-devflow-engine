from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.runtime import DeliveryChannelSnapshotModel, PipelineRunModel
from backend.app.domain.enums import (
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.observability import AuditResult
from backend.app.tools.protocol import (
    ToolBindableDescription,
    ToolError,
    ToolInput,
    ToolPermissionBoundary,
    ToolReconciliationStatus,
    ToolResult,
    ToolResultStatus,
    ToolSideEffectLevel,
)


READ_DELIVERY_SNAPSHOT_TOOL_NAME = "read_delivery_snapshot"
PREPARE_BRANCH_TOOL_NAME = "prepare_branch"
CREATE_COMMIT_TOOL_NAME = "create_commit"
DELIVERY_TOOL_CATEGORY = "delivery"
_SCHEMA_VERSION = "tool-schema-v1"

_READ_DELIVERY_SNAPSHOT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"run_id": {"type": "string", "minLength": 1}},
    "required": ["run_id"],
    "additionalProperties": False,
}
_DELIVERY_SNAPSHOT_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "delivery_channel_snapshot_ref": {"type": "string"},
        "delivery_mode": {"type": "string", "enum": ["demo_delivery", "git_auto_delivery"]},
        "scm_provider_type": {"type": ["string", "null"]},
        "repository_identifier": {"type": ["string", "null"]},
        "default_branch": {"type": ["string", "null"]},
        "code_review_request_type": {"type": ["string", "null"]},
        "credential_ref": {"type": ["string", "null"]},
        "credential_status": {"type": "string"},
        "readiness_status": {"type": "string"},
        "readiness_message": {"type": ["string", "null"]},
        "last_validated_at": {"type": ["string", "null"]},
    },
    "required": [
        "delivery_channel_snapshot_ref",
        "delivery_mode",
        "scm_provider_type",
        "repository_identifier",
        "default_branch",
        "code_review_request_type",
        "credential_ref",
        "credential_status",
        "readiness_status",
        "readiness_message",
        "last_validated_at",
    ],
    "additionalProperties": False,
}
_READ_DELIVERY_SNAPSHOT_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "delivery_channel_snapshot_ref": {"type": "string"},
        "delivery_channel_snapshot": _DELIVERY_SNAPSHOT_OBJECT_SCHEMA,
    },
    "required": [
        "run_id",
        "delivery_channel_snapshot_ref",
        "delivery_channel_snapshot",
    ],
    "additionalProperties": False,
}
_PREPARE_BRANCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_path": {"type": "string", "minLength": 1},
        "branch_name": {"type": "string", "minLength": 1},
        "base_branch": {"type": "string", "minLength": 1},
        "delivery_record_id": {"type": "string", "minLength": 1},
    },
    "required": ["repository_path", "branch_name", "base_branch", "delivery_record_id"],
    "additionalProperties": False,
}
_PREPARE_BRANCH_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "branch_name": {"type": "string"},
        "base_branch": {"type": "string"},
        "head_sha": {"type": "string"},
        "delivery_record_id": {"type": "string"},
    },
    "required": ["branch_name", "base_branch", "head_sha", "delivery_record_id"],
    "additionalProperties": False,
}
_CREATE_COMMIT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_path": {"type": "string", "minLength": 1},
        "commit_message": {"type": "string", "minLength": 1},
        "delivery_record_id": {"type": "string", "minLength": 1},
    },
    "required": ["repository_path", "commit_message", "delivery_record_id"],
    "additionalProperties": False,
}
_CREATE_COMMIT_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "commit_sha": {"type": "string"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "delivery_record_id": {"type": "string"},
    },
    "required": ["commit_sha", "changed_files", "delivery_record_id"],
    "additionalProperties": False,
}
_GIT_AUTO_REQUIRED_FIELDS = (
    "scm_provider_type",
    "repository_identifier",
    "default_branch",
    "code_review_request_type",
    "credential_ref",
)
_PREVIEW_REDACTION = RedactionPolicy(max_text_length=240, excerpt_length=240)
_FAILURE_AUDIT_REQUIRED_CODES = frozenset(
    {
        ErrorCode.DELIVERY_SNAPSHOT_MISSING,
        ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
    }
)


@dataclass(frozen=True, slots=True)
class GitCliResult:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ScmDeliveryAdapter:
    runtime_session: Session | None = None
    audit_service: Any | None = None

    def run_git_cli(
        self,
        repository_path: str | Path,
        args: Sequence[str],
        timeout_seconds: float | None = None,
    ) -> GitCliResult:
        started = time.monotonic()
        path = Path(repository_path).expanduser().resolve()
        if not path.is_dir():
            return GitCliResult(
                returncode=128,
                stdout="",
                stderr="repository_path is not an existing directory",
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        try:
            completed = subprocess.run(
                ["git", "-C", str(path), *args],
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
                env=_sanitized_git_env(),
            )
        except subprocess.TimeoutExpired as exc:
            return GitCliResult(
                returncode=124,
                stdout=str(exc.stdout or ""),
                stderr="git command timed out",
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        except OSError:
            return GitCliResult(
                returncode=127,
                stdout="",
                stderr="git command failed to start",
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        return GitCliResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    def read_delivery_snapshot(self, tool_input: ToolInput) -> ToolResult:
        run_id = str(tool_input.input_payload["run_id"])
        if self.runtime_session is None:
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.INTERNAL_ERROR,
                safe_details={"reason": "runtime_session_unavailable"},
            )
        if (
            tool_input.trace_context.run_id is not None
            and tool_input.trace_context.run_id != run_id
        ):
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
                safe_details={
                    "run_id": run_id,
                    "trace_run_id": tool_input.trace_context.run_id,
                    "reason": "trace_run_mismatch",
                },
            )

        run = self.runtime_session.get(PipelineRunModel, run_id, populate_existing=True)
        if run is None or not run.delivery_channel_snapshot_ref:
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_MISSING,
                safe_details={"run_id": run_id, "reason": "delivery_snapshot_missing"},
            )

        snapshot = self.runtime_session.get(
            DeliveryChannelSnapshotModel,
            run.delivery_channel_snapshot_ref,
            populate_existing=True,
        )
        if snapshot is None or snapshot.run_id != run.run_id:
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_MISSING,
                safe_details={
                    "run_id": run_id,
                    "delivery_channel_snapshot_ref": run.delivery_channel_snapshot_ref,
                    "reason": "delivery_snapshot_missing",
                },
            )

        missing_fields = _missing_required_snapshot_fields(snapshot)
        if missing_fields:
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
                safe_details={
                    "run_id": run_id,
                    "delivery_channel_snapshot_ref": snapshot.delivery_channel_snapshot_id,
                    "reason": "delivery_snapshot_incomplete",
                    "missing_fields": missing_fields,
                },
            )

        if (
            snapshot.credential_status is not CredentialStatus.READY
            or snapshot.readiness_status is not DeliveryReadinessStatus.READY
        ):
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
                safe_details={
                    "run_id": run_id,
                    "delivery_channel_snapshot_ref": snapshot.delivery_channel_snapshot_id,
                    "reason": "delivery_snapshot_not_ready",
                    "credential_status": snapshot.credential_status.value,
                    "readiness_status": snapshot.readiness_status.value,
                },
            )

        payload = _snapshot_payload(snapshot)
        return ToolResult(
            tool_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
            call_id=tool_input.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output_payload={
                "run_id": run.run_id,
                "delivery_channel_snapshot_ref": snapshot.delivery_channel_snapshot_id,
                "delivery_channel_snapshot": payload,
            },
            output_preview=_snapshot_preview(payload),
            artifact_refs=[snapshot.delivery_channel_snapshot_id],
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )

    def prepare_branch(self, tool_input: ToolInput) -> ToolResult:
        payload = tool_input.input_payload
        repository_path = str(payload["repository_path"])
        branch_name = str(payload["branch_name"])
        base_branch = str(payload["base_branch"])
        delivery_record_id = str(payload["delivery_record_id"])
        timeout_seconds = tool_input.timeout_seconds

        audit_failure = self._git_audit_required_result(
            tool_input,
            tool_name=PREPARE_BRANCH_TOOL_NAME,
            command="git switch -c",
        )
        if audit_failure is not None:
            return audit_failure

        for ref_name, reason in (
            (branch_name, "invalid_branch_name"),
            (base_branch, "invalid_base_branch"),
        ):
            checked = self.run_git_cli(
                repository_path,
                ["check-ref-format", "--branch", ref_name],
                timeout_seconds,
            )
            if checked.returncode != 0:
                return self._git_failed_result(
                    tool_input,
                    tool_name=PREPARE_BRANCH_TOOL_NAME,
                    command="git check-ref-format --branch",
                    exit_code=checked.returncode,
                    reason=reason,
                    delivery_record_id=delivery_record_id,
                    branch_name=branch_name,
                )

        switched = self.run_git_cli(
            repository_path,
            ["switch", "-c", branch_name, base_branch],
            timeout_seconds,
        )
        if switched.returncode != 0:
            return self._git_failed_result(
                tool_input,
                tool_name=PREPARE_BRANCH_TOOL_NAME,
                command="git switch -c",
                exit_code=switched.returncode,
                reason="switch_failed",
                delivery_record_id=delivery_record_id,
                branch_name=branch_name,
            )

        parsed = self.run_git_cli(repository_path, ["rev-parse", "HEAD"], timeout_seconds)
        if parsed.returncode != 0:
            return self._git_failed_result(
                tool_input,
                tool_name=PREPARE_BRANCH_TOOL_NAME,
                command="git rev-parse HEAD",
                exit_code=parsed.returncode,
                reason="rev_parse_failed",
                delivery_record_id=delivery_record_id,
                branch_name=branch_name,
            )
        head_sha = parsed.stdout.strip()

        audit_failure = self._record_git_call(
            tool_input=tool_input,
            tool_name=PREPARE_BRANCH_TOOL_NAME,
            command="git switch -c",
            execution=switched,
            delivery_record_id=delivery_record_id,
            branch_name=branch_name,
            base_branch=base_branch,
            head_sha=head_sha,
        )
        if audit_failure is not None:
            return audit_failure

        return ToolResult(
            tool_name=PREPARE_BRANCH_TOOL_NAME,
            call_id=tool_input.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output_payload={
                "branch_name": branch_name,
                "base_branch": base_branch,
                "head_sha": head_sha,
                "delivery_record_id": delivery_record_id,
            },
            output_preview=_safe_preview(f"prepared git branch at {head_sha[:12]}"),
            side_effect_refs=[
                f"git_branch:{branch_name}",
                f"delivery_record:{delivery_record_id}",
            ],
            reconciliation_status=ToolReconciliationStatus.PENDING,
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )

    def create_commit(self, tool_input: ToolInput) -> ToolResult:
        payload = tool_input.input_payload
        repository_path = str(payload["repository_path"])
        commit_message = str(payload["commit_message"])
        delivery_record_id = str(payload["delivery_record_id"])
        timeout_seconds = tool_input.timeout_seconds

        audit_failure = self._git_audit_required_result(
            tool_input,
            tool_name=CREATE_COMMIT_TOOL_NAME,
            command="git commit -m",
        )
        if audit_failure is not None:
            return audit_failure

        unstaged = self.run_git_cli(
            repository_path,
            ["diff", "--name-only", "-z", "--", "."],
            timeout_seconds,
        )
        if unstaged.returncode != 0:
            return self._git_failed_result(
                tool_input,
                tool_name=CREATE_COMMIT_TOOL_NAME,
                command="git diff --name-only",
                exit_code=unstaged.returncode,
                reason="workspace_changes_lookup_failed",
                delivery_record_id=delivery_record_id,
            )

        staged = self.run_git_cli(
            repository_path,
            ["diff", "--cached", "--name-only", "-z", "--", "."],
            timeout_seconds,
        )
        if staged.returncode != 0:
            return self._git_failed_result(
                tool_input,
                tool_name=CREATE_COMMIT_TOOL_NAME,
                command="git diff --cached --name-only",
                exit_code=staged.returncode,
                reason="staged_changes_lookup_failed",
                delivery_record_id=delivery_record_id,
            )

        untracked = self.run_git_cli(
            repository_path,
            ["ls-files", "--others", "--exclude-standard", "-z"],
            timeout_seconds,
        )
        if untracked.returncode != 0:
            return self._git_failed_result(
                tool_input,
                tool_name=CREATE_COMMIT_TOOL_NAME,
                command="git ls-files --others --exclude-standard",
                exit_code=untracked.returncode,
                reason="untracked_changes_lookup_failed",
                delivery_record_id=delivery_record_id,
            )

        staged_paths = _split_git_path_output(staged.stdout)
        staged_runtime_logs = sorted(
            path for path in staged_paths if _is_runtime_log_path(path)
        )
        if staged_runtime_logs:
            runtime_unstaged = self.run_git_cli(
                repository_path,
                ["restore", "--staged", "--", *staged_runtime_logs],
                timeout_seconds,
            )
            if runtime_unstaged.returncode != 0:
                return self._git_failed_result(
                    tool_input,
                    tool_name=CREATE_COMMIT_TOOL_NAME,
                    command="git restore --staged -- .runtime/logs",
                    exit_code=runtime_unstaged.returncode,
                    reason="runtime_log_unstage_failed",
                    delivery_record_id=delivery_record_id,
                )

        candidate_paths = sorted(
            {
                *_split_git_path_output(unstaged.stdout),
                *staged_paths,
                *_split_git_path_output(untracked.stdout),
            }
        )
        stage_paths = [
            path for path in candidate_paths if not _is_runtime_log_path(path)
        ]
        if stage_paths:
            added = self.run_git_cli(
                repository_path,
                ["add", "-A", "--", *stage_paths],
                timeout_seconds,
            )
            if added.returncode != 0:
                return self._git_failed_result(
                    tool_input,
                    tool_name=CREATE_COMMIT_TOOL_NAME,
                    command="git add -A",
                    exit_code=added.returncode,
                    reason="stage_failed",
                    delivery_record_id=delivery_record_id,
                )

        diff_args = ["diff", "--cached", "--name-only", "-z", "--", "."]
        diffed = self.run_git_cli(repository_path, diff_args, timeout_seconds)
        if diffed.returncode != 0:
            return self._git_failed_result(
                tool_input,
                tool_name=CREATE_COMMIT_TOOL_NAME,
                command="git diff --cached --name-only",
                exit_code=diffed.returncode,
                reason="staged_files_failed",
                delivery_record_id=delivery_record_id,
            )
        changed_files = [
            path
            for path in _split_git_path_output(diffed.stdout)
            if not _is_runtime_log_path(path)
        ]
        if not changed_files:
            return self._git_failed_result(
                tool_input,
                tool_name=CREATE_COMMIT_TOOL_NAME,
                command="git diff --cached --name-only",
                exit_code=0,
                reason="no_changes_to_commit",
                delivery_record_id=delivery_record_id,
            )

        committed = self.run_git_cli(
            repository_path,
            ["commit", "-m", commit_message],
            timeout_seconds,
        )
        if committed.returncode != 0:
            return self._git_failed_result(
                tool_input,
                tool_name=CREATE_COMMIT_TOOL_NAME,
                command="git commit -m",
                exit_code=committed.returncode,
                reason="commit_failed",
                delivery_record_id=delivery_record_id,
            )

        parsed = self.run_git_cli(repository_path, ["rev-parse", "HEAD"], timeout_seconds)
        if parsed.returncode != 0:
            return self._git_failed_result(
                tool_input,
                tool_name=CREATE_COMMIT_TOOL_NAME,
                command="git rev-parse HEAD",
                exit_code=parsed.returncode,
                reason="rev_parse_failed",
                delivery_record_id=delivery_record_id,
            )
        commit_sha = parsed.stdout.strip()

        audit_failure = self._record_git_call(
            tool_input=tool_input,
            tool_name=CREATE_COMMIT_TOOL_NAME,
            command="git commit -m",
            execution=committed,
            delivery_record_id=delivery_record_id,
            commit_sha=commit_sha,
            changed_files=changed_files,
        )
        if audit_failure is not None:
            return audit_failure

        return ToolResult(
            tool_name=CREATE_COMMIT_TOOL_NAME,
            call_id=tool_input.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output_payload={
                "commit_sha": commit_sha,
                "changed_files": changed_files,
                "delivery_record_id": delivery_record_id,
            },
            output_preview=_safe_preview(
                f"created git commit {commit_sha[:12]} with {len(changed_files)} changed file(s)"
            ),
            side_effect_refs=[
                f"git_commit:{commit_sha}",
                f"delivery_record:{delivery_record_id}",
            ],
            reconciliation_status=ToolReconciliationStatus.PENDING,
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )

    def _failed_result(
        self,
        tool_input: ToolInput,
        *,
        error_code: ErrorCode,
        safe_details: dict[str, object],
    ) -> ToolResult:
        if error_code in _FAILURE_AUDIT_REQUIRED_CODES and not self._record_failure_audit(
            tool_input=tool_input,
            error_code=error_code,
            safe_details=safe_details,
        ):
            return ToolResult(
                tool_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
                call_id=tool_input.call_id,
                status=ToolResultStatus.FAILED,
                error=_safe_tool_error(
                    error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                    tool_input=tool_input,
                    safe_details={
                        "reason": "delivery_failure_audit_unavailable",
                        "requested_error_code": error_code.value,
                    },
                ),
                trace_context=tool_input.trace_context,
                coordination_key=tool_input.coordination_key,
            )
        return ToolResult(
            tool_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
            call_id=tool_input.call_id,
            status=ToolResultStatus.FAILED,
            error=_safe_tool_error(
                error_code=error_code,
                tool_input=tool_input,
                safe_details=safe_details,
            ),
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )

    def _record_failure_audit(
        self,
        *,
        tool_input: ToolInput,
        error_code: ErrorCode,
        safe_details: dict[str, object],
    ) -> bool:
        if self.audit_service is None:
            return False
        try:
            self.audit_service.record_tool_error(
                tool_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
                command=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
                error_code=error_code,
                result=AuditResult.FAILED,
                reason=str(safe_details.get("reason", error_code.value)),
                metadata=safe_details,
                trace_context=tool_input.trace_context,
            )
        except Exception:
            return False
        return True

    def _git_audit_required_result(
        self,
        tool_input: ToolInput,
        *,
        tool_name: str,
        command: str,
    ) -> ToolResult | None:
        if self.audit_service is not None:
            return None
        return _git_tool_error_result(
            tool_input,
            tool_name=tool_name,
            error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
            safe_details={
                "command": command,
                "reason": "delivery_git_write_audit_unavailable",
            },
        )

    def _git_failed_result(
        self,
        tool_input: ToolInput,
        *,
        tool_name: str,
        command: str,
        exit_code: int,
        reason: str,
        delivery_record_id: str,
        branch_name: str | None = None,
    ) -> ToolResult:
        safe_details: dict[str, object] = {
            "command": command,
            "exit_code": exit_code,
            "reason": reason,
        }
        result = _git_tool_error_result(
            tool_input,
            tool_name=tool_name,
            error_code=ErrorCode.DELIVERY_GIT_CLI_FAILED,
            safe_details=safe_details,
        )
        audit_failure = self._record_git_error(
            tool_input=tool_input,
            tool_name=tool_name,
            command=command,
            error_code=ErrorCode.DELIVERY_GIT_CLI_FAILED,
            reason=reason,
            metadata=safe_details,
            delivery_record_id=delivery_record_id,
            branch_name=branch_name,
        )
        return audit_failure or result

    def _record_git_call(
        self,
        *,
        tool_input: ToolInput,
        tool_name: str,
        command: str,
        execution: GitCliResult,
        delivery_record_id: str,
        branch_name: str | None = None,
        base_branch: str | None = None,
        head_sha: str | None = None,
        commit_sha: str | None = None,
        changed_files: Sequence[str] = (),
    ) -> ToolResult | None:
        if self.audit_service is None:
            return _git_tool_error_result(
                tool_input,
                tool_name=tool_name,
                error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                safe_details={
                    "command": command,
                    "reason": "delivery_git_write_audit_unavailable",
                },
            )
        try:
            self.audit_service.record_tool_call(
                tool_name=tool_name,
                command=command,
                exit_code=execution.returncode,
                duration_ms=execution.duration_ms,
                changed_files=list(changed_files),
                stdout_excerpt=execution.stdout,
                stderr_excerpt=execution.stderr,
                branch_name=branch_name,
                base_branch=base_branch,
                head_sha=head_sha,
                commit_sha=commit_sha,
                delivery_record_id=delivery_record_id,
                intent_audit_id=tool_input.side_effect_intent_ref,
                trace_context=tool_input.trace_context,
            )
        except Exception:
            return _git_tool_error_result(
                tool_input,
                tool_name=tool_name,
                error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                safe_details={
                    "command": command,
                    "reason": "delivery_git_write_audit_failed",
                },
            )
        return None

    def _record_git_error(
        self,
        *,
        tool_input: ToolInput,
        tool_name: str,
        command: str,
        error_code: ErrorCode,
        reason: str,
        metadata: dict[str, object],
        delivery_record_id: str,
        branch_name: str | None = None,
    ) -> ToolResult | None:
        if self.audit_service is None:
            return _git_tool_error_result(
                tool_input,
                tool_name=tool_name,
                error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                safe_details={
                    "command": command,
                    "reason": "delivery_git_write_audit_unavailable",
                },
            )
        try:
            self.audit_service.record_tool_error(
                tool_name=tool_name,
                command=command,
                error_code=error_code,
                result=AuditResult.FAILED,
                reason=reason,
                metadata=metadata,
                branch_name=branch_name,
                delivery_record_id=delivery_record_id,
                intent_audit_id=tool_input.side_effect_intent_ref,
                trace_context=tool_input.trace_context,
            )
        except Exception:
            return _git_tool_error_result(
                tool_input,
                tool_name=tool_name,
                error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                safe_details={
                    "command": command,
                    "reason": "delivery_git_write_audit_failed",
                },
            )
        return None


@dataclass(frozen=True, slots=True)
class ReadDeliverySnapshotTool:
    adapter: ScmDeliveryAdapter

    @property
    def name(self) -> str:
        return READ_DELIVERY_SNAPSHOT_TOOL_NAME

    @property
    def category(self) -> str:
        return DELIVERY_TOOL_CATEGORY

    @property
    def description(self) -> str:
        return "Read the frozen delivery channel snapshot for the current run."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _READ_DELIVERY_SNAPSHOT_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _READ_DELIVERY_SNAPSHOT_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.READ_ONLY

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return ()

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type=DELIVERY_TOOL_CATEGORY,
            requires_workspace=False,
            resource_scopes=("delivery_channel_snapshot",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.NONE

    @property
    def audit_required(self) -> bool:
        return True

    @property
    def schema_version(self) -> str:
        return _SCHEMA_VERSION

    @property
    def default_timeout_seconds(self) -> float | None:
        return 5.0

    def bindable_description(self) -> ToolBindableDescription:
        return ToolBindableDescription(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
            result_schema=dict(self.result_schema),
            risk_level=self.default_risk_level,
            risk_categories=list(self.risk_categories),
            schema_version=self.schema_version,
            default_timeout_seconds=self.default_timeout_seconds,
        )

    def execute(self, tool_input: ToolInput) -> ToolResult:
        return self.adapter.read_delivery_snapshot(tool_input)


@dataclass(frozen=True, slots=True)
class PrepareBranchTool:
    adapter: ScmDeliveryAdapter

    @property
    def name(self) -> str:
        return PREPARE_BRANCH_TOOL_NAME

    @property
    def category(self) -> str:
        return DELIVERY_TOOL_CATEGORY

    @property
    def description(self) -> str:
        return "Create a controlled delivery branch from a base branch."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _PREPARE_BRANCH_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _PREPARE_BRANCH_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.HIGH_RISK

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return (ToolRiskCategory.UNKNOWN_COMMAND,)

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type=DELIVERY_TOOL_CATEGORY,
            requires_workspace=True,
            resource_scopes=("git_repository", "delivery_record"),
            workspace_target_paths=("repository_path",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.GIT_WRITE

    @property
    def audit_required(self) -> bool:
        return True

    @property
    def schema_version(self) -> str:
        return _SCHEMA_VERSION

    @property
    def default_timeout_seconds(self) -> float | None:
        return 30.0

    def bindable_description(self) -> ToolBindableDescription:
        return ToolBindableDescription(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
            result_schema=dict(self.result_schema),
            risk_level=self.default_risk_level,
            risk_categories=list(self.risk_categories),
            schema_version=self.schema_version,
            default_timeout_seconds=self.default_timeout_seconds,
        )

    def execute(self, tool_input: ToolInput) -> ToolResult:
        return self.adapter.prepare_branch(tool_input)


@dataclass(frozen=True, slots=True)
class CreateCommitTool:
    adapter: ScmDeliveryAdapter

    @property
    def name(self) -> str:
        return CREATE_COMMIT_TOOL_NAME

    @property
    def category(self) -> str:
        return DELIVERY_TOOL_CATEGORY

    @property
    def description(self) -> str:
        return "Stage workspace changes and create a controlled delivery commit."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _CREATE_COMMIT_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _CREATE_COMMIT_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.HIGH_RISK

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return (ToolRiskCategory.UNKNOWN_COMMAND,)

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type=DELIVERY_TOOL_CATEGORY,
            requires_workspace=True,
            resource_scopes=("git_repository", "delivery_record"),
            workspace_target_paths=("repository_path",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.GIT_WRITE

    @property
    def audit_required(self) -> bool:
        return True

    @property
    def schema_version(self) -> str:
        return _SCHEMA_VERSION

    @property
    def default_timeout_seconds(self) -> float | None:
        return 30.0

    def bindable_description(self) -> ToolBindableDescription:
        return ToolBindableDescription(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
            result_schema=dict(self.result_schema),
            risk_level=self.default_risk_level,
            risk_categories=list(self.risk_categories),
            schema_version=self.schema_version,
            default_timeout_seconds=self.default_timeout_seconds,
        )

    def execute(self, tool_input: ToolInput) -> ToolResult:
        return self.adapter.create_commit(tool_input)


def _missing_required_snapshot_fields(
    snapshot: DeliveryChannelSnapshotModel,
) -> list[str]:
    if snapshot.delivery_mode is not DeliveryMode.GIT_AUTO_DELIVERY:
        return []
    missing: list[str] = []
    for field_name in _GIT_AUTO_REQUIRED_FIELDS:
        if getattr(snapshot, field_name) in (None, ""):
            missing.append(field_name)
    return missing


def _snapshot_payload(snapshot: DeliveryChannelSnapshotModel) -> dict[str, object]:
    return {
        "delivery_channel_snapshot_ref": snapshot.delivery_channel_snapshot_id,
        "delivery_mode": snapshot.delivery_mode.value,
        "scm_provider_type": _enum_value(snapshot.scm_provider_type),
        "repository_identifier": snapshot.repository_identifier,
        "default_branch": snapshot.default_branch,
        "code_review_request_type": _enum_value(snapshot.code_review_request_type),
        "credential_ref": snapshot.credential_ref,
        "credential_status": snapshot.credential_status.value,
        "readiness_status": snapshot.readiness_status.value,
        "readiness_message": snapshot.readiness_message,
        "last_validated_at": (
            snapshot.last_validated_at.isoformat()
            if snapshot.last_validated_at is not None
            else None
        ),
    }


def _snapshot_preview(snapshot_payload: Mapping[str, object]) -> str:
    delivery_mode = snapshot_payload["delivery_mode"]
    readiness_status = snapshot_payload["readiness_status"]
    repository_configured = snapshot_payload.get("repository_identifier") is not None
    default_branch_configured = snapshot_payload.get("default_branch") is not None
    redacted = _PREVIEW_REDACTION.summarize_text(
        f"delivery_snapshot {delivery_mode} "
        f"repository_configured={str(repository_configured).lower()} "
        f"default_branch_configured={str(default_branch_configured).lower()} "
        f"{readiness_status}",
        payload_type="delivery_snapshot_tool_preview",
    )
    if isinstance(redacted.redacted_payload, str) and redacted.redacted_payload:
        return redacted.redacted_payload
    return redacted.excerpt or "[redacted]"


def _safe_preview(text: str) -> str:
    redacted = _PREVIEW_REDACTION.summarize_text(
        text,
        payload_type="delivery_git_tool_preview",
    )
    if isinstance(redacted.redacted_payload, str) and redacted.redacted_payload:
        return redacted.redacted_payload
    return redacted.excerpt or "[redacted]"


def _git_tool_error_result(
    tool_input: ToolInput,
    *,
    tool_name: str,
    error_code: ErrorCode,
    safe_details: dict[str, object],
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        call_id=tool_input.call_id,
        status=ToolResultStatus.FAILED,
        error=_safe_tool_error(
            error_code=error_code,
            tool_input=tool_input,
            safe_details=safe_details,
        ),
        trace_context=tool_input.trace_context,
        coordination_key=tool_input.coordination_key,
    )


def _safe_tool_error(
    *,
    error_code: ErrorCode,
    tool_input: ToolInput,
    safe_details: dict[str, object],
) -> ToolError:
    try:
        return ToolError.from_code(
            error_code,
            trace_context=tool_input.trace_context,
            safe_details=safe_details,
        )
    except ValueError:
        return ToolError.from_code(
            error_code,
            trace_context=tool_input.trace_context,
            safe_details={"detail_redacted": True},
        )


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return value.value


def _sanitized_git_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.upper().startswith("GIT_"):
            env.pop(key, None)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_COUNT"] = "4"
    env["GIT_CONFIG_KEY_0"] = "core.hooksPath"
    env["GIT_CONFIG_VALUE_0"] = os.devnull
    env["GIT_CONFIG_KEY_1"] = "commit.gpgsign"
    env["GIT_CONFIG_VALUE_1"] = "false"
    env["GIT_CONFIG_KEY_2"] = "tag.gpgsign"
    env["GIT_CONFIG_VALUE_2"] = "false"
    env["GIT_CONFIG_KEY_3"] = "init.templateDir"
    env["GIT_CONFIG_VALUE_3"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _split_git_path_output(output: str) -> list[str]:
    return [path for path in output.split("\0") if path]


def _is_runtime_log_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized == ".runtime/logs" or normalized.startswith(".runtime/logs/")


__all__ = [
    "CREATE_COMMIT_TOOL_NAME",
    "PREPARE_BRANCH_TOOL_NAME",
    "READ_DELIVERY_SNAPSHOT_TOOL_NAME",
    "CreateCommitTool",
    "GitCliResult",
    "PrepareBranchTool",
    "ScmDeliveryAdapter",
    "ReadDeliverySnapshotTool",
]
