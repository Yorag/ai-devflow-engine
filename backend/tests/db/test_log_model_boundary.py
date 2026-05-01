from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.schemas.observability import (
    AuditActorType,
    AuditLogEntryProjection,
    AuditResult,
    LogCategory,
    LogLevel,
    RedactionStatus,
    RunLogEntryProjection,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
LOG_TABLES = {"run_log_entries", "audit_log_entries", "log_payloads"}
FORBIDDEN_LOG_TABLES = {
    "projects",
    "sessions",
    "pipeline_templates",
    "providers",
    "delivery_channels",
    "platform_runtime_settings",
    "pipeline_runs",
    "stage_runs",
    "stage_artifacts",
    "approval_requests",
    "approval_decisions",
    "tool_confirmation_requests",
    "delivery_records",
    "graph_definitions",
    "graph_threads",
    "graph_checkpoints",
    "graph_interrupts",
    "domain_events",
    "feed_entries",
    "inspector_projections",
}


def enum_values(enum_type: type) -> list[str]:
    return [item.value for item in enum_type]


def test_log_models_register_only_log_role_metadata() -> None:
    from backend.app.db.models.log import (
        AuditLogEntryModel,
        LogBase,
        LogPayloadModel,
        RunLogEntryModel,
    )

    assert LogBase.metadata is ROLE_METADATA[DatabaseRole.LOG]
    assert {table.name for table in LogBase.metadata.sorted_tables} == LOG_TABLES
    assert FORBIDDEN_LOG_TABLES.isdisjoint(LogBase.metadata.tables)

    for model in (RunLogEntryModel, AuditLogEntryModel, LogPayloadModel):
        assert model.metadata is ROLE_METADATA[DatabaseRole.LOG]

    for role in (
        DatabaseRole.CONTROL,
        DatabaseRole.RUNTIME,
        DatabaseRole.GRAPH,
        DatabaseRole.EVENT,
    ):
        assert LOG_TABLES.isdisjoint(ROLE_METADATA[role].tables)


def test_log_tables_create_only_in_log_database(tmp_path) -> None:
    from backend.app.db.models.log import LogBase

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    with manager.session(DatabaseRole.LOG) as session:
        log_tables = set(inspect(session.bind).get_table_names())

    assert LOG_TABLES.issubset(log_tables)
    assert FORBIDDEN_LOG_TABLES.isdisjoint(log_tables)

    for role in (
        DatabaseRole.CONTROL,
        DatabaseRole.RUNTIME,
        DatabaseRole.GRAPH,
        DatabaseRole.EVENT,
    ):
        with manager.session(role) as session:
            assert LOG_TABLES.isdisjoint(inspect(session.bind).get_table_names())


def test_alembic_env_imports_log_models_for_metadata_loading() -> None:
    alembic_env = Path("backend/alembic/env.py").read_text(encoding="utf-8")

    assert "import backend.app.db.models.log  # noqa: F401" in alembic_env


def test_run_log_model_indexes_file_location_trace_and_product_refs(tmp_path) -> None:
    from backend.app.db.models.log import LogBase, LogPayloadModel, RunLogEntryModel

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    with manager.session(DatabaseRole.LOG) as session:
        payload = LogPayloadModel(
            payload_id="payload-run-log-1",
            payload_type="tool_output_summary",
            summary={"tool_name": "bash", "stdout_excerpt": "pytest passed"},
            storage_ref="logs/payloads/payload-run-log-1.json",
            content_hash="sha256:runlogpayload",
            redaction_status=RedactionStatus.REDACTED,
            payload_size_bytes=512,
            schema_version="log-payload-v1",
            created_at=NOW,
        )
        entry = RunLogEntryModel(
            log_id="log-1",
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-1",
            approval_id=None,
            tool_confirmation_id="tool-confirmation-1",
            delivery_record_id=None,
            graph_thread_id="graph-thread-1",
            request_id="request-1",
            source="tool.registry",
            category=LogCategory.TOOL,
            level=LogLevel.WARNING,
            message="Tool call requires confirmation.",
            log_file_ref="logs/runs/run-1.jsonl",
            line_offset=128,
            line_number=3,
            log_file_generation="run-1",
            payload_ref=payload.payload_id,
            payload_excerpt="tool_name=bash risk=high_risk",
            payload_size_bytes=payload.payload_size_bytes,
            redaction_status=RedactionStatus.REDACTED,
            correlation_id="correlation-1",
            trace_id="trace-1",
            span_id="span-tool-1",
            parent_span_id="span-stage-1",
            duration_ms=42,
            error_code=None,
            created_at=NOW,
        )
        session.add_all([payload, entry])
        session.commit()

        saved_entry = session.get(RunLogEntryModel, "log-1")

    assert saved_entry is not None
    assert saved_entry.log_file_ref == "logs/runs/run-1.jsonl"
    assert saved_entry.line_offset == 128
    assert saved_entry.line_number == 3
    assert saved_entry.trace_id == "trace-1"
    assert saved_entry.correlation_id == "correlation-1"
    assert saved_entry.span_id == "span-tool-1"
    assert saved_entry.parent_span_id == "span-stage-1"
    assert saved_entry.tool_confirmation_id == "tool-confirmation-1"

    projection = RunLogEntryProjection(
        log_id=saved_entry.log_id,
        session_id=saved_entry.session_id,
        run_id=saved_entry.run_id,
        stage_run_id=saved_entry.stage_run_id,
        approval_id=saved_entry.approval_id,
        tool_confirmation_id=saved_entry.tool_confirmation_id,
        delivery_record_id=saved_entry.delivery_record_id,
        graph_thread_id=saved_entry.graph_thread_id,
        request_id=saved_entry.request_id,
        source=saved_entry.source,
        category=saved_entry.category,
        level=saved_entry.level,
        message=saved_entry.message,
        log_file_ref=saved_entry.log_file_ref,
        line_offset=saved_entry.line_offset,
        line_number=saved_entry.line_number,
        log_file_generation=saved_entry.log_file_generation,
        payload_ref=saved_entry.payload_ref,
        payload_excerpt=saved_entry.payload_excerpt,
        payload_size_bytes=saved_entry.payload_size_bytes,
        redaction_status=saved_entry.redaction_status,
        correlation_id=saved_entry.correlation_id,
        trace_id=saved_entry.trace_id,
        span_id=saved_entry.span_id,
        parent_span_id=saved_entry.parent_span_id,
        created_at=saved_entry.created_at,
    )
    assert projection.model_dump(mode="json")["category"] == "tool"

    columns = set(RunLogEntryModel.__table__.columns.keys())
    assert {
        "log_file_ref",
        "line_offset",
        "line_number",
        "log_file_generation",
        "request_id",
        "trace_id",
        "correlation_id",
        "span_id",
        "parent_span_id",
        "session_id",
        "run_id",
        "stage_run_id",
        "approval_id",
        "tool_confirmation_id",
        "delivery_record_id",
        "graph_thread_id",
    }.issubset(columns)
    assert {
        "domain_event_id",
        "feed_entry_id",
        "inspector_projection_id",
        "raw_payload",
        "payload",
        "full_payload",
        "raw_graph_state",
    }.isdisjoint(columns)


def test_audit_log_model_records_actor_target_result_and_failure_policy(tmp_path) -> None:
    from backend.app.db.models.log import (
        AUDIT_WRITE_FAILURE_BEHAVIOR,
        AuditLogEntryModel,
        LogBase,
        LogPayloadModel,
    )

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    with manager.session(DatabaseRole.LOG) as session:
        metadata = LogPayloadModel(
            payload_id="payload-audit-1",
            payload_type="audit_metadata_summary",
            summary={"decision": "allowed", "tool_name": "bash"},
            storage_ref="logs/payloads/payload-audit-1.json",
            content_hash="sha256:auditpayload",
            redaction_status=RedactionStatus.REDACTED,
            payload_size_bytes=256,
            schema_version="log-payload-v1",
            created_at=NOW,
        )
        audit = AuditLogEntryModel(
            audit_id="audit-1",
            actor_type=AuditActorType.USER,
            actor_id="user-local",
            action="tool_confirmation.allow",
            target_type="tool_confirmation",
            target_id="tool-confirmation-1",
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-1",
            approval_id=None,
            tool_confirmation_id="tool-confirmation-1",
            delivery_record_id=None,
            request_id="request-1",
            result=AuditResult.ACCEPTED,
            reason="User allowed this high-risk command.",
            metadata_ref=metadata.payload_id,
            metadata_excerpt="Allowed bash command after confirmation.",
            correlation_id="correlation-1",
            trace_id="trace-1",
            span_id="span-audit-1",
            audit_file_ref="logs/audit.jsonl",
            audit_file_generation="audit-2026-01-02",
            audit_file_write_failed=False,
            created_at=NOW,
        )
        session.add(metadata)
        session.flush()
        session.add(audit)
        session.commit()

        saved_audit = session.get(AuditLogEntryModel, "audit-1")

    assert saved_audit is not None
    assert saved_audit.actor_type is AuditActorType.USER
    assert saved_audit.action == "tool_confirmation.allow"
    assert saved_audit.target_id == "tool-confirmation-1"
    assert saved_audit.result is AuditResult.ACCEPTED
    assert saved_audit.request_id == "request-1"
    assert saved_audit.correlation_id == "correlation-1"
    assert saved_audit.audit_file_ref == "logs/audit.jsonl"
    assert saved_audit.audit_file_write_failed is False
    assert AUDIT_WRITE_FAILURE_BEHAVIOR == "reject_or_rollback_high_impact_action"

    projection = AuditLogEntryProjection(
        audit_id=saved_audit.audit_id,
        actor_type=saved_audit.actor_type,
        actor_id=saved_audit.actor_id,
        action=saved_audit.action,
        target_type=saved_audit.target_type,
        target_id=saved_audit.target_id,
        session_id=saved_audit.session_id,
        run_id=saved_audit.run_id,
        stage_run_id=saved_audit.stage_run_id,
        approval_id=saved_audit.approval_id,
        tool_confirmation_id=saved_audit.tool_confirmation_id,
        delivery_record_id=saved_audit.delivery_record_id,
        request_id=saved_audit.request_id,
        result=saved_audit.result,
        reason=saved_audit.reason,
        metadata_ref=saved_audit.metadata_ref,
        metadata_excerpt=saved_audit.metadata_excerpt,
        correlation_id=saved_audit.correlation_id,
        trace_id=saved_audit.trace_id,
        span_id=saved_audit.span_id,
        created_at=saved_audit.created_at,
    )
    assert projection.model_dump(mode="json")["result"] == "accepted"

    columns = set(AuditLogEntryModel.__table__.columns.keys())
    assert {
        "actor_type",
        "actor_id",
        "action",
        "target_type",
        "target_id",
        "result",
        "reason",
        "request_id",
        "correlation_id",
        "audit_file_write_failed",
    }.issubset(columns)
    assert {
        "downgraded_to_run_log",
        "fallback_run_log_id",
        "domain_event_id",
        "feed_entry_id",
        "inspector_projection_id",
        "raw_metadata",
        "metadata",
    }.isdisjoint(columns)


def test_log_payload_model_keeps_bounded_summary_not_raw_payload(tmp_path) -> None:
    from backend.app.db.models.log import LogBase, LogPayloadModel

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    LogBase.metadata.create_all(manager.engine(DatabaseRole.LOG))

    with manager.session(DatabaseRole.LOG) as session:
        payload = LogPayloadModel(
            payload_id="payload-model-1",
            payload_type="model_response_summary",
            summary={"excerpt": "structured output parsed", "field_count": 4},
            storage_ref="logs/payloads/payload-model-1.json",
            content_hash="sha256:modelpayload",
            redaction_status=RedactionStatus.NOT_REQUIRED,
            payload_size_bytes=1024,
            schema_version="log-payload-v1",
            created_at=NOW,
        )
        session.add(payload)
        session.commit()

        saved_payload = session.get(LogPayloadModel, "payload-model-1")

    assert saved_payload is not None
    assert saved_payload.summary["field_count"] == 4
    assert saved_payload.storage_ref == "logs/payloads/payload-model-1.json"
    assert saved_payload.content_hash == "sha256:modelpayload"
    assert saved_payload.redaction_status is RedactionStatus.NOT_REQUIRED
    assert saved_payload.payload_size_bytes == 1024

    columns = set(LogPayloadModel.__table__.columns.keys())
    assert {
        "payload_type",
        "summary",
        "storage_ref",
        "content_hash",
        "redaction_status",
        "payload_size_bytes",
    }.issubset(columns)
    assert {
        "raw_payload",
        "full_payload",
        "payload",
        "content",
        "body",
        "unredacted_text",
    }.isdisjoint(columns)


def test_log_model_enums_reuse_l1_1_observability_contract_values() -> None:
    from backend.app.db.models.log import (
        AuditLogEntryModel,
        LogPayloadModel,
        RunLogEntryModel,
    )

    assert RunLogEntryModel.__table__.columns["category"].type.enums == enum_values(
        LogCategory
    )
    assert RunLogEntryModel.__table__.columns["level"].type.enums == enum_values(LogLevel)
    assert RunLogEntryModel.__table__.columns[
        "redaction_status"
    ].type.enums == enum_values(RedactionStatus)
    assert AuditLogEntryModel.__table__.columns["actor_type"].type.enums == enum_values(
        AuditActorType
    )
    assert AuditLogEntryModel.__table__.columns["result"].type.enums == enum_values(
        AuditResult
    )
    assert LogPayloadModel.__table__.columns[
        "redaction_status"
    ].type.enums == enum_values(RedactionStatus)
