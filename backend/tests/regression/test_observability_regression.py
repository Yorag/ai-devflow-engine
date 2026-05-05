from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import PlatformRuntimeSettingsModel
from backend.app.db.models.log import (
    AuditLogEntryModel,
    LogBase,
    LogPayloadModel,
    RunLogEntryModel,
)
from backend.app.db.models.runtime import StageRunModel
from backend.app.domain.changes import ChangeOperation, ChangeSet, ChangeSetFile
from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.retention import EXPIRED_LOG_FILE_REF, EXPIRED_LOG_MESSAGE
from backend.app.repositories.runtime_settings import RUNTIME_SETTINGS_ID
from backend.app.api.error_codes import ErrorCode
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
    RedactionStatus,
)
from backend.app.tools.protocol import ToolInput, ToolResultStatus
from backend.app.workspace.bash import run_bash_command
from backend.tests.projections.test_workspace_projection import (
    NOW,
    _default_internal_model_bindings,
    _manager,
    _seed_workspace,
)
from backend.tests.workspace.test_workspace_bash import (
    _build_workspace as _build_bash_workspace,
)
from backend.tests.workspace.test_workspace_bash import (
    _RecordingAudit,
    _RecordingRunner,
    _trace,
)


class _NoopAuditWriter:
    def write_audit_copy(self, _record):
        raise OSError("audit jsonl unavailable")

    def write(self, _record):
        return None


def _trace_context() -> TraceContext:
    return TraceContext(
        request_id="request-l62",
        trace_id="trace-l62",
        correlation_id="correlation-l62",
        span_id="span-l62",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-active",
        stage_run_id="stage-active",
        created_at=NOW,
    )


def test_audit_metadata_blocks_command_output_secrets_without_losing_ledger(
    tmp_path,
) -> None:
    from backend.app.observability.audit import AuditService

    manager = _manager(tmp_path)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    with manager.session(DatabaseRole.LOG) as log_session:
        service = AuditService(log_session, audit_writer=_NoopAuditWriter())
        result = service.record_command_result(
            actor_type=AuditActorType.TOOL,
            actor_id="bash",
            action="tool.bash.failed",
            target_type="tool_action",
            target_id="bash:run-active:span-l62",
            result=AuditResult.FAILED,
            reason="Command failed.",
            metadata={
                "stdout_excerpt": "TOKEN=raw-token-value",
                "stderr_excerpt": "password=raw-password-value",
            },
            trace_context=_trace_context(),
            created_at=NOW,
        )

    with manager.session(DatabaseRole.LOG) as log_session:
        saved_entry = log_session.get(AuditLogEntryModel, result.audit_id)
        saved_payload = log_session.get(
            type(result.metadata_payload),
            result.metadata_payload.payload_id,
        )

    assert saved_entry is not None
    assert saved_entry.audit_file_write_failed is True
    assert saved_payload is not None
    assert saved_payload.redaction_status is RedactionStatus.BLOCKED
    assert saved_entry.metadata_excerpt == "[blocked:sensitive_text_pattern]"
    dumped = str(saved_payload.summary) + str(saved_entry.metadata_excerpt)
    assert "raw-token-value" not in dumped
    assert "raw-password-value" not in dumped


def _seed_runtime_settings(manager) -> None:
    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            PlatformRuntimeSettingsModel(
                settings_id=RUNTIME_SETTINGS_ID,
                config_version="platform-runtime-settings-config-v1",
                schema_version="platform-runtime-settings-v1",
                hard_limits_version="platform-hard-limits-v1",
                agent_limits={"max_react_iterations_per_stage": 30},
                provider_call_policy={"network_error_max_retries": 3},
                internal_model_bindings=_default_internal_model_bindings(
                    "platform-runtime-settings-config-v1"
                ),
                context_limits={"grep_max_results": 100},
                log_policy={
                    "run_log_retention_days": 30,
                    "audit_log_retention_days": 180,
                    "log_rotation_max_bytes": 10485760,
                    "log_query_default_limit": 10,
                    "log_query_max_limit": 20,
                },
                created_by_actor_id=None,
                updated_by_actor_id=None,
                last_audit_log_id=None,
                last_trace_id=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def _run_log_row(
    *,
    log_id: str,
    stage_run_id: str,
    message: str,
    payload_excerpt: str | None,
    redaction_status: RedactionStatus,
    created_at: datetime,
) -> RunLogEntryModel:
    return RunLogEntryModel(
        log_id=log_id,
        session_id="session-1",
        run_id="run-active",
        stage_run_id=stage_run_id,
        approval_id=None,
        tool_confirmation_id=None,
        delivery_record_id=None,
        graph_thread_id="graph-thread-run-active",
        request_id=f"request-{log_id}",
        source="observability.regression",
        category=LogCategory.RUNTIME,
        level=LogLevel.WARNING,
        message=message,
        log_file_ref=(
            EXPIRED_LOG_FILE_REF
            if message == EXPIRED_LOG_MESSAGE
            else "logs/runs/run-active.jsonl"
        ),
        line_offset=0,
        line_number=1,
        log_file_generation="expired" if message == EXPIRED_LOG_MESSAGE else "run-active",
        payload_ref=None,
        payload_excerpt=payload_excerpt,
        payload_size_bytes=128 if payload_excerpt else 0,
        redaction_status=redaction_status,
        correlation_id=f"correlation-{log_id}",
        trace_id="trace-run-active",
        span_id=f"span-{log_id}",
        parent_span_id=None,
        duration_ms=None,
        error_code=None,
        created_at=created_at,
    )


def test_log_queries_return_stable_degraded_projection_for_expired_and_blocked_payloads(
    tmp_path,
) -> None:
    from backend.app.observability.log_query import LogQueryService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_runtime_settings(manager)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            StageRunModel(
                stage_run_id="stage-secondary",
                run_id="run-active",
                stage_type=StageType.CODE_REVIEW,
                status=StageStatus.RUNNING,
                attempt_index=2,
                graph_node_key="code_review.main",
                stage_contract_ref="stage-contract-code-review",
                input_ref=None,
                output_ref=None,
                summary="Secondary stage.",
                started_at=NOW + timedelta(minutes=2),
                ended_at=None,
                created_at=NOW + timedelta(minutes=2),
                updated_at=NOW + timedelta(minutes=2),
            )
        )
        session.commit()
    with manager.session(DatabaseRole.LOG) as session:
        session.add_all(
            [
                _run_log_row(
                    log_id="log-expired",
                    stage_run_id="stage-active",
                    message=EXPIRED_LOG_MESSAGE,
                    payload_excerpt=None,
                    redaction_status=RedactionStatus.NOT_REQUIRED,
                    created_at=NOW,
                ),
                _run_log_row(
                    log_id="log-blocked",
                    stage_run_id="stage-active",
                    message="Payload blocked by redaction policy.",
                    payload_excerpt="[blocked:sensitive_text_pattern]",
                    redaction_status=RedactionStatus.BLOCKED,
                    created_at=NOW + timedelta(seconds=1),
                ),
                _run_log_row(
                    log_id="log-secondary",
                    stage_run_id="stage-secondary",
                    message="Secondary stage log.",
                    payload_excerpt="secondary",
                    redaction_status=RedactionStatus.NOT_REQUIRED,
                    created_at=NOW + timedelta(seconds=2),
                ),
            ]
        )
        session.commit()

    service = LogQueryService(
        manager.session(DatabaseRole.CONTROL),
        manager.session(DatabaseRole.RUNTIME),
        manager.session(DatabaseRole.LOG),
    )

    run_response = service.list_run_logs("run-active", limit=10)
    stage_response = service.list_stage_logs("stage-active", limit=10)

    assert [entry.log_id for entry in run_response.entries] == [
        "log-expired",
        "log-blocked",
        "log-secondary",
    ]
    assert [entry.log_id for entry in stage_response.entries] == [
        "log-expired",
        "log-blocked",
    ]
    expired = run_response.entries[0]
    blocked = run_response.entries[1]
    assert expired.message == EXPIRED_LOG_MESSAGE
    assert expired.log_file_ref == EXPIRED_LOG_FILE_REF
    assert blocked.redaction_status is RedactionStatus.BLOCKED
    assert blocked.payload_excerpt == "[blocked:sensitive_text_pattern]"
    dumped = run_response.model_dump(mode="json")
    assert "raw-token-value" not in str(dumped)
    assert "narrative_feed" not in dumped


def test_audit_queries_return_stable_degraded_projection_for_blocked_payloads_and_errors(
    tmp_path,
) -> None:
    from backend.app.observability.audit import AuditQueryServiceError, AuditService

    manager = _manager(tmp_path)
    _seed_runtime_settings(manager)
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))
    with manager.session(DatabaseRole.LOG) as session:
        payload = LogPayloadModel(
            payload_id="payload-audit-blocked-l62",
            payload_type="audit_metadata_summary",
            summary={
                "payload_type": "audit_metadata_summary",
                "blocked_reason": "sensitive_text_pattern",
                "input_type": "dict",
            },
            storage_ref=None,
            content_hash="sha256:audit-blocked-l62",
            redaction_status=RedactionStatus.BLOCKED,
            payload_size_bytes=96,
            schema_version="log-payload-v1",
            created_at=NOW,
        )
        session.add(payload)
        session.flush()
        session.add(
            AuditLogEntryModel(
                audit_id="audit-blocked-l62",
                actor_type=AuditActorType.TOOL,
                actor_id="bash",
                action="tool.bash.failed",
                target_type="tool_action",
                target_id="bash:run-active:span-l62",
                session_id="session-1",
                run_id="run-active",
                stage_run_id="stage-active",
                approval_id=None,
                tool_confirmation_id=None,
                delivery_record_id=None,
                request_id="request-audit-blocked-l62",
                result=AuditResult.FAILED,
                reason="Command failed.",
                metadata_ref=payload.payload_id,
                metadata_excerpt="[blocked:sensitive_text_pattern]",
                correlation_id="correlation-audit-blocked-l62",
                trace_id="trace-audit-blocked-l62",
                span_id="span-audit-blocked-l62",
                audit_file_ref="logs/audit.jsonl",
                audit_file_generation="audit-20260501",
                audit_file_write_failed=False,
                created_at=NOW,
            )
        )
        session.commit()

    service = AuditService(
        manager.session(DatabaseRole.LOG),
        control_session=manager.session(DatabaseRole.CONTROL),
        audit_writer=_NoopAuditWriter(),
    )

    response = service.list_audit_logs(
        run_id="run-active",
        stage_run_id="stage-active",
        result=AuditResult.FAILED,
        limit=10,
    )

    assert [entry.audit_id for entry in response.entries] == ["audit-blocked-l62"]
    entry = response.entries[0]
    assert entry.metadata_ref == "payload-audit-blocked-l62"
    assert entry.metadata_excerpt == "[blocked:sensitive_text_pattern]"
    dumped = response.model_dump(mode="json")
    assert dumped["query"]["run_id"] == "run-active"
    assert dumped["query"]["stage_run_id"] == "stage-active"
    assert dumped["query"]["result"] == "failed"
    assert "raw-" not in str(dumped)
    assert "summary" not in str(dumped)
    assert "narrative_feed" not in dumped

    for kwargs in (
        {"limit": 0},
        {"limit": 21},
        {"cursor": "not-a-cursor"},
        {"since": NOW + timedelta(seconds=1), "until": NOW},
    ):
        with pytest.raises(AuditQueryServiceError) as exc_info:
            service.list_audit_logs(**kwargs)
        assert exc_info.value.error_code is ErrorCode.LOG_QUERY_INVALID
        assert exc_info.value.status_code == 422

    manager_without_settings = _manager(tmp_path / "missing-settings")
    LogBase.metadata.create_all(manager_without_settings.engine(DatabaseRole.LOG))
    service_without_settings = AuditService(
        manager_without_settings.session(DatabaseRole.LOG),
        control_session=manager_without_settings.session(DatabaseRole.CONTROL),
        audit_writer=_NoopAuditWriter(),
    )
    with pytest.raises(AuditQueryServiceError) as config_exc:
        service_without_settings.list_audit_logs()
    assert config_exc.value.error_code is ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE
    assert config_exc.value.status_code == 503


def test_runtime_logs_exclusion_regression_covers_workspace_tools_and_changeset(
    tmp_path,
) -> None:
    from backend.tests.workspace.test_workspace_file_tools import _build_harness
    from backend.tests.workspace.test_workspace_file_tools import _tool_input

    harness = _build_harness(tmp_path)
    runtime_log = harness.workspace.root / ".runtime" / "logs" / "run.jsonl"
    runtime_log.parent.mkdir(parents=True)
    runtime_log.write_text('{"event":"private"}\n', encoding="utf-8")
    app_file = harness.workspace.root / "src" / "app.py"
    app_file.parent.mkdir(parents=True)
    app_file.write_text("print('visible')\n", encoding="utf-8")

    read_result = harness.registry.resolve("read_file").execute(
        _tool_input(
            "read_file",
            {"path": ".runtime/logs/run.jsonl"},
            trace_context=harness.trace_context,
        )
    )
    change_set = ChangeSet.from_workspace_delta(
        change_set_id="changeset-l62",
        workspace_ref=harness.workspace.workspace_ref,
        run_id=harness.workspace.run_id,
        stage_run_id="stage-run-1",
        files=[
            ChangeSetFile(path="src/app.py", operation=ChangeOperation.MODIFY),
            ChangeSetFile(path=".runtime/logs/run.jsonl", operation=ChangeOperation.MODIFY),
        ],
        file_edit_trace_refs=[
            "file_edit_trace:run-1:call-l62:src/app.py",
            "file_edit_trace:run-1:call-l62:.runtime/logs/run.jsonl",
        ],
        created_at=NOW,
    )

    assert read_result.status is not ToolResultStatus.SUCCEEDED
    assert read_result.error is not None
    assert read_result.error.safe_details == {
        "path": ".runtime/logs/run.jsonl",
        "reason": "workspace_path_excluded",
    }
    assert change_set.changed_files == ("src/app.py",)
    assert change_set.file_edit_trace_refs == (
        "file_edit_trace:run-1:call-l62:src/app.py",
    )


def test_runtime_logs_exclusion_regression_covers_bash_changed_files(tmp_path) -> None:
    manager, workspace = _build_bash_workspace(tmp_path)
    audit = _RecordingAudit()
    runner = _RecordingRunner(workspace.root)

    result = run_bash_command(
        manager,
        workspace,
        "npm --prefix frontend run build",
        audit_service=audit,
        tool_input=ToolInput(
            tool_name="bash",
            call_id="call-bash-l62",
            input_payload={"command": "npm --prefix frontend run build"},
            trace_context=_trace(),
            coordination_key="coordination-bash-l62",
            side_effect_intent_ref="audit-intent-call-bash-l62",
            timeout_seconds=5,
        ),
        runner=lambda argv, cwd, timeout: (
            (workspace.root / ".runtime" / "logs").mkdir(parents=True, exist_ok=True),
            (workspace.root / ".runtime" / "logs" / "run.jsonl").write_text(
                '{"event":"private"}\n',
                encoding="utf-8",
            ),
            runner(argv, cwd=cwd, timeout=timeout),
        )[2],
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["changed_files"] == ["frontend/dist/app.js"]
    assert result.side_effect_refs == [
        "command_trace:run-1:call-bash-l62",
        "file_edit_trace:run-1:call-bash-l62:frontend/dist/app.js",
    ]
    assert ".runtime/logs" not in str(result.output_payload)
    assert ".runtime/logs" not in str(result.side_effect_refs)


def test_git_delivery_excludes_runtime_logs_from_delivery_commit_regression(
    tmp_path,
) -> None:
    from backend.app.delivery.scm import CREATE_COMMIT_TOOL_NAME
    from backend.tests.delivery.test_prepare_branch_create_commit import (
        RecordingAudit,
        RecordingConfirmationPort,
        RecordingRunLog,
        RecordingWorkspaceBoundary,
        build_context,
        build_registry,
        execute_confirmed,
        git,
        request,
    )
    from backend.tests.fixtures import fixture_git_repository

    repo = fixture_git_repository(tmp_path)
    audit = RecordingAudit()
    run_log = RecordingRunLog()
    confirmations = RecordingConfirmationPort()
    workspace_boundary = RecordingWorkspaceBoundary()
    registry = build_registry(audit)
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
        build_context(
            audit=audit,
            run_log=run_log,
            confirmations=confirmations,
            workspace_boundary=workspace_boundary,
        ),
        confirmations,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["changed_files"] == ["src/workspace_change.txt"]
    assert ".runtime/logs/run-1.jsonl" not in git(
        repo,
        "show",
        "--name-only",
        "--format=",
        "HEAD",
    )
    assert audit.calls[-1]["changed_files"] == ["src/workspace_change.txt"]
