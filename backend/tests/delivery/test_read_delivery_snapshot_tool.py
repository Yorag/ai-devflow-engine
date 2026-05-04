from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.api.error_codes import ErrorCode
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
    ToolRiskLevel,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditResult
from backend.app.tools.execution_gate import ToolExecutionContext, ToolExecutionRequest
from backend.app.tools.protocol import ToolAuditRef, ToolResult, ToolResultStatus
from backend.app.tools.registry import ToolRegistry

from backend.app.delivery.scm import ScmDeliveryAdapter, ReadDeliverySnapshotTool


NOW = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


class RecordingAudit:
    def __init__(self) -> None:
        self.intents: list[dict[str, object]] = []
        self.rejections: list[dict[str, object]] = []

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
                "run_id": trace_context.run_id,
                "stage_run_id": trace_context.stage_run_id,
            }
        )
        return ToolAuditRef(
            audit_id=f"audit-{request.call_id}",
            action="tool.intent",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-{request.call_id}",
        )

    def record_tool_rejection(
        self,
        *,
        request: ToolExecutionRequest,
        error_code: ErrorCode,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.rejections.append(
            {
                "tool_name": request.tool_name,
                "error_code": error_code.value,
            }
        )
        return ToolAuditRef(
            audit_id=f"audit-reject-{request.call_id}",
            action="tool.rejected",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-reject-{request.call_id}",
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


class RecordingDeliveryAudit:
    def __init__(self) -> None:
        self.errors: list[dict[str, object]] = []

    def record_tool_error(self, **kwargs: object) -> object:
        self.errors.append(dict(kwargs))
        return object()


class FailingDeliveryAudit(RecordingDeliveryAudit):
    def record_tool_error(self, **kwargs: object) -> object:
        self.errors.append(dict(kwargs))
        raise RuntimeError("delivery audit unavailable")


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


def build_trace(**overrides: Any) -> TraceContext:
    values: dict[str, Any] = {
        "request_id": "request-read-delivery-snapshot",
        "trace_id": "trace-read-delivery-snapshot",
        "correlation_id": "correlation-read-delivery-snapshot",
        "span_id": "span-read-delivery-snapshot",
        "parent_span_id": None,
        "session_id": "session-1",
        "run_id": "run-1",
        "stage_run_id": "stage-run-delivery",
        "created_at": NOW,
    }
    values.update(overrides)
    return TraceContext(**values)


def seed_run(
    manager: DatabaseManager,
    *,
    delivery_mode: DeliveryMode = DeliveryMode.GIT_AUTO_DELIVERY,
    credential_status: CredentialStatus = CredentialStatus.READY,
    readiness_status: DeliveryReadinessStatus = DeliveryReadinessStatus.READY,
    repository_identifier: str | None = "acme/frozen-repo",
    default_branch: str | None = "main",
    credential_ref: str | None = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
    snapshot_ref: str | None = "delivery-snapshot-1",
    snapshot_run_id: str = "run-1",
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
                    run_id=snapshot_run_id,
                    source_delivery_channel_id="delivery-default",
                    delivery_mode=delivery_mode,
                    scm_provider_type=(
                        ScmProviderType.GITHUB
                        if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
                        else None
                    ),
                    repository_identifier=repository_identifier,
                    default_branch=default_branch,
                    code_review_request_type=(
                        CodeReviewRequestType.PULL_REQUEST
                        if delivery_mode is DeliveryMode.GIT_AUTO_DELIVERY
                        else None
                    ),
                    credential_ref=credential_ref,
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
                trace_id="trace-read-delivery-snapshot",
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


def build_request(run_id: str = "run-1") -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_name="read_delivery_snapshot",
        call_id="call-read-delivery-snapshot",
        input_payload={"run_id": run_id},
        trace_context=build_trace(run_id=run_id),
        coordination_key="coordination-read-delivery-snapshot",
    )


def build_context(
    *,
    allowed_tools: list[str] | None = None,
    audit: RecordingAudit | None = None,
    run_log: RecordingRunLog | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        stage_type=StageType.DELIVERY_INTEGRATION,
        stage_contracts={
            StageType.DELIVERY_INTEGRATION.value: {
                "allowed_tools": (
                    ["read_delivery_snapshot"]
                    if allowed_tools is None
                    else allowed_tools
                )
            }
        },
        trace_context=build_trace(),
        audit_recorder=audit,
        run_log_recorder=run_log,
        runtime_tool_timeout_seconds=5,
        platform_tool_timeout_hard_limit_seconds=30,
    )


def test_read_delivery_snapshot_registers_and_reads_frozen_snapshot_through_registry(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    audit = RecordingAudit()
    run_log = RecordingRunLog()

    with manager.session(DatabaseRole.RUNTIME) as session:
        tool = ReadDeliverySnapshotTool(
            adapter=ScmDeliveryAdapter(runtime_session=session)
        )
        registry = ToolRegistry([tool])

        assert tool.default_risk_level is ToolRiskLevel.READ_ONLY
        assert tool.audit_required is True
        assert tool.side_effect_level.value == "none"
        assert tool.permission_boundary.requires_workspace is False
        assert [item.name for item in registry.list_bindable_tools(category="delivery")] == [
            "read_delivery_snapshot"
        ]

        result = registry.execute(
            build_request(),
            build_context(audit=audit, run_log=run_log),
        )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.audit_ref is not None
    assert result.artifact_refs == ["delivery-snapshot-1"]
    snapshot = result.output_payload["delivery_channel_snapshot"]
    assert snapshot == {
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "delivery_mode": "git_auto_delivery",
        "scm_provider_type": "github",
        "repository_identifier": "acme/frozen-repo",
        "default_branch": "main",
        "code_review_request_type": "pull_request",
        "credential_ref": "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
        "credential_status": "ready",
        "readiness_status": "ready",
        "readiness_message": "delivery is ready.",
        "last_validated_at": NOW.replace(tzinfo=None).isoformat(),
    }
    assert "AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN" not in (result.output_preview or "")
    assert audit.intents == [
        {
            "tool_name": "read_delivery_snapshot",
            "run_id": "run-1",
            "stage_run_id": "stage-run-delivery",
        }
    ]
    assert run_log.records[-1]["tool_name"] == "read_delivery_snapshot"
    assert run_log.records[-1]["status"] == "succeeded"


def test_read_delivery_snapshot_preview_redacts_sensitive_repository_text(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(
        manager,
        repository_identifier="acme/raw-secret-token",
        default_branch="release/password=secret123",
    )

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [ReadDeliverySnapshotTool(adapter=ScmDeliveryAdapter(runtime_session=session))]
        )
        result = registry.execute(
            build_request(),
            build_context(audit=RecordingAudit(), run_log=RecordingRunLog()),
        )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload["delivery_channel_snapshot"]["repository_identifier"] == (
        "acme/raw-secret-token"
    )
    assert result.output_payload["delivery_channel_snapshot"]["default_branch"] == (
        "release/password=secret123"
    )
    assert "raw-secret-token" not in (result.output_preview or "")
    assert "password=secret123" not in (result.output_preview or "")
    assert result.output_preview == (
        "delivery_snapshot git_auto_delivery "
        "repository_configured=true default_branch_configured=true ready"
    )


def test_read_delivery_snapshot_is_rejected_by_allowed_tools_gate(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    audit = RecordingAudit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [ReadDeliverySnapshotTool(adapter=ScmDeliveryAdapter(runtime_session=session))]
        )
        result = registry.execute(
            build_request(),
            build_context(allowed_tools=[], audit=audit, run_log=RecordingRunLog()),
        )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_NOT_ALLOWED
    assert audit.intents == []


def test_read_delivery_snapshot_rejects_trace_run_mismatch(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)
    audit = RecordingAudit()
    run_log = RecordingRunLog()

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [ReadDeliverySnapshotTool(adapter=ScmDeliveryAdapter(runtime_session=session))]
        )
        result = registry.execute(
            ToolExecutionRequest(
                tool_name="read_delivery_snapshot",
                call_id="call-read-delivery-snapshot",
                input_payload={"run_id": "run-1"},
                trace_context=build_trace(run_id="run-other"),
                coordination_key="coordination-read-delivery-snapshot",
            ),
            build_context(audit=audit, run_log=run_log),
        )

    assert result.status is ToolResultStatus.FAILED
    assert result.audit_ref is not None
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_INPUT_SCHEMA_INVALID
    assert result.error.safe_details == {
        "run_id": "run-1",
        "trace_run_id": "run-other",
        "reason": "trace_run_mismatch",
    }
    assert audit.intents[0]["tool_name"] == "read_delivery_snapshot"
    assert run_log.records[-1]["error_code"] == "tool_input_schema_invalid"


def test_read_delivery_snapshot_requires_domain_failure_audit(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager, snapshot_ref=None)
    audit = RecordingAudit()
    run_log = RecordingRunLog()

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [ReadDeliverySnapshotTool(adapter=ScmDeliveryAdapter(runtime_session=session))]
        )
        missing_audit = registry.execute(
            build_request(),
            build_context(audit=audit, run_log=run_log),
        )

    assert missing_audit.status is ToolResultStatus.FAILED
    assert missing_audit.error is not None
    assert missing_audit.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert missing_audit.error.safe_details == {
        "reason": "delivery_failure_audit_unavailable",
        "requested_error_code": "delivery_snapshot_missing",
    }
    assert audit.intents[0]["tool_name"] == "read_delivery_snapshot"

    failing_delivery_audit = FailingDeliveryAudit()
    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [
                ReadDeliverySnapshotTool(
                    adapter=ScmDeliveryAdapter(
                        runtime_session=session,
                        audit_service=failing_delivery_audit,
                    )
                )
            ]
        )
        failing_audit = registry.execute(
            build_request(),
            build_context(audit=RecordingAudit(), run_log=run_log),
        )

    assert failing_audit.status is ToolResultStatus.FAILED
    assert failing_audit.error is not None
    assert failing_audit.error.error_code is ErrorCode.TOOL_AUDIT_REQUIRED_FAILED
    assert failing_delivery_audit.errors[0]["error_code"] is ErrorCode.DELIVERY_SNAPSHOT_MISSING
    assert run_log.records[-1]["error_code"] == "tool_audit_required_failed"


def test_read_delivery_snapshot_redacts_unsafe_failure_details(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager)

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [ReadDeliverySnapshotTool(adapter=ScmDeliveryAdapter(runtime_session=session))]
        )
        result = registry.execute(
            ToolExecutionRequest(
                tool_name="read_delivery_snapshot",
                call_id="call-read-delivery-snapshot",
                input_payload={"run_id": "Bearer secret-run-token"},
                trace_context=build_trace(run_id="run-other"),
                coordination_key="coordination-read-delivery-snapshot",
            ),
            build_context(audit=RecordingAudit(), run_log=RecordingRunLog()),
        )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_INPUT_SCHEMA_INVALID
    assert result.error.safe_details == {"detail_redacted": True}


def test_read_delivery_snapshot_returns_missing_without_project_config_fallback(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager, snapshot_ref=None)
    audit = RecordingAudit()
    delivery_audit = RecordingDeliveryAudit()
    run_log = RecordingRunLog()

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [
                ReadDeliverySnapshotTool(
                    adapter=ScmDeliveryAdapter(
                        runtime_session=session,
                        audit_service=delivery_audit,
                    )
                )
            ]
        )
        result = registry.execute(
            build_request(),
            build_context(audit=audit, run_log=run_log),
        )

    assert result.status is ToolResultStatus.FAILED
    assert result.audit_ref is not None
    assert result.error is not None
    assert result.error.error_code is ErrorCode.DELIVERY_SNAPSHOT_MISSING
    assert result.error.safe_details == {
        "run_id": "run-1",
        "reason": "delivery_snapshot_missing",
    }
    assert audit.intents[0]["tool_name"] == "read_delivery_snapshot"
    assert delivery_audit.errors[0]["tool_name"] == "read_delivery_snapshot"
    assert delivery_audit.errors[0]["error_code"] is ErrorCode.DELIVERY_SNAPSHOT_MISSING
    assert delivery_audit.errors[0]["result"] is AuditResult.FAILED
    assert run_log.records[-1]["error_code"] == "delivery_snapshot_missing"


def test_read_delivery_snapshot_rejects_snapshot_owned_by_other_run(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager, snapshot_run_id="run-other")
    audit = RecordingAudit()
    delivery_audit = RecordingDeliveryAudit()
    run_log = RecordingRunLog()

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [
                ReadDeliverySnapshotTool(
                    adapter=ScmDeliveryAdapter(
                        runtime_session=session,
                        audit_service=delivery_audit,
                    )
                )
            ]
        )
        result = registry.execute(
            build_request(),
            build_context(audit=audit, run_log=run_log),
        )

    assert result.status is ToolResultStatus.FAILED
    assert result.audit_ref is not None
    assert result.error is not None
    assert result.error.error_code is ErrorCode.DELIVERY_SNAPSHOT_MISSING
    assert result.error.safe_details == {
        "run_id": "run-1",
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "reason": "delivery_snapshot_missing",
    }
    assert audit.intents[0]["tool_name"] == "read_delivery_snapshot"
    assert delivery_audit.errors[0]["error_code"] is ErrorCode.DELIVERY_SNAPSHOT_MISSING
    assert run_log.records[-1]["error_code"] == "delivery_snapshot_missing"


def test_read_delivery_snapshot_rejects_incomplete_git_snapshot(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(manager, repository_identifier=None)
    audit = RecordingAudit()
    run_log = RecordingRunLog()

    with manager.session(DatabaseRole.RUNTIME) as session:
        delivery_audit = RecordingDeliveryAudit()
        registry = ToolRegistry(
            [
                ReadDeliverySnapshotTool(
                    adapter=ScmDeliveryAdapter(
                        runtime_session=session,
                        audit_service=delivery_audit,
                    )
                )
            ]
        )
        result = registry.execute(
            build_request(),
            build_context(audit=audit, run_log=run_log),
        )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.DELIVERY_SNAPSHOT_NOT_READY
    assert result.error.safe_details == {
        "run_id": "run-1",
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "reason": "delivery_snapshot_incomplete",
        "missing_fields": ["repository_identifier"],
    }
    assert audit.intents[0]["tool_name"] == "read_delivery_snapshot"
    assert delivery_audit.errors[0]["error_code"] is ErrorCode.DELIVERY_SNAPSHOT_NOT_READY
    assert run_log.records[-1]["error_code"] == "delivery_snapshot_not_ready"


def test_read_delivery_snapshot_rejects_unavailable_credential_status(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    seed_run(
        manager,
        credential_status=CredentialStatus.UNBOUND,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
    )
    audit = RecordingAudit()
    delivery_audit = RecordingDeliveryAudit()
    run_log = RecordingRunLog()

    with manager.session(DatabaseRole.RUNTIME) as session:
        registry = ToolRegistry(
            [
                ReadDeliverySnapshotTool(
                    adapter=ScmDeliveryAdapter(
                        runtime_session=session,
                        audit_service=delivery_audit,
                    )
                )
            ]
        )
        result = registry.execute(
            build_request(),
            build_context(audit=audit, run_log=run_log),
        )

    assert result.status is ToolResultStatus.FAILED
    assert result.audit_ref is not None
    assert result.error is not None
    assert result.error.error_code is ErrorCode.DELIVERY_SNAPSHOT_NOT_READY
    assert result.error.safe_details == {
        "run_id": "run-1",
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "reason": "delivery_snapshot_not_ready",
        "credential_status": "unbound",
        "readiness_status": "unconfigured",
    }
    assert audit.intents[0]["tool_name"] == "read_delivery_snapshot"
    assert delivery_audit.errors[0]["error_code"] is ErrorCode.DELIVERY_SNAPSHOT_NOT_READY
    assert run_log.records[-1]["error_code"] == "delivery_snapshot_not_ready"
