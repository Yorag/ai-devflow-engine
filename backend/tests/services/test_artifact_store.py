from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import RunStatus, RunTriggerSource, StageStatus, StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.observability.redaction import RedactedPayload
from backend.app.schemas.observability import LogCategory, RedactionStatus
from backend.app.services.artifacts import ArtifactStore, ArtifactStoreError


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 3, 5, 5, tzinfo=UTC)


class CapturingLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return object()


class FailingLogWriter:
    def write_run_log(self, record: LogRecordInput) -> object:
        raise RuntimeError("log sink unavailable")


class FailingRedactionPolicy:
    def summarize_payload(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("redaction unavailable")


class BlockingRedactionPolicy:
    def summarize_payload(self, *args: object, **kwargs: object) -> RedactedPayload:
        return RedactedPayload(
            summary={
                "payload_type": "stage_artifact",
                "blocked_reason": "sensitive_text_pattern",
                "input_type": "dict",
            },
            excerpt="[blocked:sensitive_text_pattern]",
            redacted_payload=None,
            payload_size_bytes=100,
            content_hash="sha256:blocked",
            redaction_status=RedactionStatus.BLOCKED,
        )


class FailingGetSession:
    def get(self, *args: object, **kwargs: object) -> object:
        raise SQLAlchemyError("storage unavailable")


class FailingFlushSession:
    def __init__(self, stage: StageRunModel) -> None:
        self.stage = stage

    def get(self, model: object, ident: object) -> object | None:
        if model is StageRunModel:
            return self.stage
        return None

    def add(self, model: object) -> None:
        return None

    def flush(self) -> None:
        raise SQLAlchemyError("storage unavailable")


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    return manager


def build_trace(*, run_id: str = "run-1", stage_run_id: str | None = None) -> TraceContext:
    return TraceContext(
        request_id="request-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        span_id="span-1",
        parent_span_id=None,
        session_id="session-1",
        run_id=run_id,
        stage_run_id=stage_run_id,
        created_at=NOW,
    )


def seed_run(session: Session, *, run_id: str = "run-1") -> PipelineRunModel:
    runtime_limit_snapshot = RuntimeLimitSnapshotModel(
        snapshot_id=f"runtime-limit-{run_id}",
        run_id=run_id,
        agent_limits={"max_react_iterations_per_stage": 30},
        context_limits={"compression_threshold_ratio": 0.8},
        source_config_version="runtime-settings-v1",
        hard_limits_version="platform-hard-limits-v1",
        schema_version="runtime-limit-snapshot-v1",
        created_at=NOW,
    )
    provider_call_policy_snapshot = ProviderCallPolicySnapshotModel(
        snapshot_id=f"provider-policy-{run_id}",
        run_id=run_id,
        provider_call_policy={
            "request_timeout_seconds": 60,
            "network_error_max_retries": 3,
        },
        source_config_version="runtime-settings-v1",
        schema_version="provider-call-policy-snapshot-v1",
        created_at=NOW,
    )
    run = PipelineRunModel(
        run_id=run_id,
        session_id="session-1",
        project_id="project-default",
        attempt_index=1,
        status=RunStatus.RUNNING,
        trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
        template_snapshot_ref="template-snapshot-1",
        graph_definition_ref="graph-definition-1",
        graph_thread_ref="graph-thread-1",
        workspace_ref="workspace-1",
        runtime_limit_snapshot_ref=runtime_limit_snapshot.snapshot_id,
        provider_call_policy_snapshot_ref=provider_call_policy_snapshot.snapshot_id,
        delivery_channel_snapshot_ref=None,
        current_stage_run_id=None,
        trace_id="trace-1",
        started_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add_all([runtime_limit_snapshot, provider_call_policy_snapshot])
    session.flush()
    session.add(run)
    session.flush()
    return run


def seed_stage(
    session: Session,
    *,
    stage_run_id: str = "stage-run-1",
    run_id: str = "run-1",
) -> StageRunModel:
    stage = StageRunModel(
        stage_run_id=stage_run_id,
        run_id=run_id,
        stage_type=StageType.SOLUTION_DESIGN,
        status=StageStatus.RUNNING,
        attempt_index=1,
        graph_node_key="solution_design.main",
        stage_contract_ref="stage-contract-solution-design",
        input_ref=None,
        output_ref=None,
        summary="Designing solution.",
        started_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(stage)
    session.flush()
    return stage


def create_input_artifact(
    store: ArtifactStore,
    *,
    artifact_id: str = "artifact-stage-1",
) -> StageArtifactModel:
    return store.create_stage_input(
        run_id="run-1",
        stage_run_id="stage-run-1",
        artifact_id=artifact_id,
        artifact_type="stage_input",
        payload_ref="payload-stage-1",
        input_snapshot={"requirement_text": "Build the pipeline."},
        input_refs=["session-message-1"],
        trace_context=build_trace(stage_run_id="stage-run-1"),
    )


def test_create_stage_input_persists_stage_artifact_and_binds_stage_input_ref(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session, stage_run_id="stage-run-1")
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)

        artifact = store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-input-1",
            artifact_type="stage_input",
            payload_ref="payload-stage-input-1",
            input_snapshot={"requirement_text": "Build the pipeline."},
            input_refs=["session-message-1", "requirement-artifact-0"],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

        runtime_session.commit()
        saved_stage = runtime_session.get(StageRunModel, "stage-run-1")
        saved_artifact = runtime_session.get(
            StageArtifactModel,
            "artifact-stage-input-1",
        )

    assert artifact.artifact_id == "artifact-stage-input-1"
    assert saved_stage is not None
    assert saved_stage.input_ref == "artifact-stage-input-1"
    assert saved_stage.output_ref is None
    assert saved_artifact is not None
    assert saved_artifact.payload_ref == "payload-stage-input-1"
    assert saved_artifact.process["input_snapshot"]["requirement_text"] == (
        "Build the pipeline."
    )
    assert saved_artifact.process["input_refs"] == [
        "session-message-1",
        "requirement-artifact-0",
    ]
    assert saved_artifact.metrics == {}


def test_create_stage_input_updates_stage_updated_at_when_binding_input_ref(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session, stage_run_id="stage-run-1")
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: LATER)

        store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-input-1",
            artifact_type="stage_input",
            payload_ref="payload-stage-input-1",
            input_snapshot={"requirement_text": "Build the pipeline."},
            input_refs=[],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        saved_stage = runtime_session.get(StageRunModel, "stage-run-1")

    assert saved_stage is not None
    assert saved_stage.updated_at == LATER.replace(tzinfo=None)


def test_create_stage_input_rejects_unknown_stage(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)

        with pytest.raises(
            ArtifactStoreError,
            match="Stage artifact storage target was not found",
        ):
            store.create_stage_input(
                run_id="run-1",
                stage_run_id="missing-stage",
                artifact_id="artifact-stage-1",
                artifact_type="stage_input",
                payload_ref="payload-stage-1",
                input_snapshot={"requirement_text": "Build the pipeline."},
                input_refs=[],
                trace_context=build_trace(stage_run_id="missing-stage"),
            )


def test_create_stage_input_rejects_stage_from_different_run(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session, run_id="run-1")
        seed_run(runtime_session, run_id="run-2")
        seed_stage(runtime_session, stage_run_id="stage-run-1", run_id="run-2")
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)

        with pytest.raises(
            ArtifactStoreError,
            match="Stage artifact storage target was not found",
        ):
            store.create_stage_input(
                run_id="run-1",
                stage_run_id="stage-run-1",
                artifact_id="artifact-stage-1",
                artifact_type="stage_input",
                payload_ref="payload-stage-1",
                input_snapshot={"requirement_text": "Build the pipeline."},
                input_refs=[],
                trace_context=build_trace(stage_run_id="stage-run-1"),
            )


def test_create_stage_input_logs_missing_stage_failure(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        store = ArtifactStore(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=lambda: NOW,
        )

        with pytest.raises(ArtifactStoreError):
            store.create_stage_input(
                run_id="run-1",
                stage_run_id="missing-stage",
                artifact_id="artifact-stage-1",
                artifact_type="stage_input",
                payload_ref="payload-stage-1",
                input_snapshot={"requirement_text": "Build the pipeline."},
                input_refs=[],
                trace_context=build_trace(stage_run_id="missing-stage"),
            )

    record = log_writer.records[0]
    assert record.category is LogCategory.RUNTIME
    assert record.payload.summary["action"] == "create_stage_input_failed"
    assert record.payload.summary["run_id"] == "run-1"
    assert record.payload.summary["stage_run_id"] == "missing-stage"
    assert record.payload.summary["artifact_id"] == "artifact-stage-1"
    assert record.payload.summary["error_message"] == (
        "Stage artifact storage target was not found."
    )


def test_append_process_record_merges_named_process_content_without_dropping_existing_keys(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)
        create_input_artifact(store)

        artifact = store.append_process_record(
            artifact_id="artifact-stage-1",
            process_key="context_manifest",
            process_value={"window_refs": ["ctx-1"], "compressed": False},
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        artifact = store.append_process_record(
            artifact_id="artifact-stage-1",
            process_key="tool_trace",
            process_value=[{"tool_name": "read_file", "status": "completed"}],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    assert artifact.process["input_snapshot"]["requirement_text"] == "Build the pipeline."
    assert artifact.process["input_refs"] == ["session-message-1"]
    assert artifact.process["context_manifest"]["window_refs"] == ["ctx-1"]
    assert artifact.process["tool_trace"][0]["tool_name"] == "read_file"


def test_append_process_record_rejects_unknown_artifact(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)

        with pytest.raises(ArtifactStoreError, match="Stage artifact was not found"):
            store.append_process_record(
                artifact_id="missing-artifact",
                process_key="tool_trace",
                process_value=[],
                trace_context=build_trace(stage_run_id="stage-run-1"),
            )


def test_append_process_record_logs_missing_artifact_failure(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=lambda: NOW,
        )

        with pytest.raises(ArtifactStoreError):
            store.append_process_record(
                artifact_id="missing-artifact",
                process_key="tool_trace",
                process_value=[],
                trace_context=build_trace(stage_run_id="stage-run-1"),
            )

    record = log_writer.records[0]
    assert record.payload.summary["action"] == "append_process_record_failed"
    assert record.payload.summary["artifact_id"] == "missing-artifact"
    assert record.payload.summary["changed_process_keys"] == ["tool_trace"]
    assert record.payload.summary["error_message"] == "Stage artifact was not found."


def test_complete_stage_output_updates_output_snapshot_and_stage_output_ref(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)
        store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-1",
            artifact_type="solution_design_artifact",
            payload_ref="payload-stage-1",
            input_snapshot={"requirement_text": "Build the pipeline."},
            input_refs=["session-message-1"],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

        artifact = store.complete_stage_output(
            artifact_id="artifact-stage-1",
            payload_ref="payload-solution-design-1",
            output_snapshot={
                "solution_summary": "Use AL lanes with checkpointed integration.",
                "evidence_refs": ["event-1", "artifact-input-0"],
            },
            output_refs=["solution-design-artifact-1"],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

        runtime_session.commit()
        saved_stage = runtime_session.get(StageRunModel, "stage-run-1")

    assert artifact.payload_ref == "payload-solution-design-1"
    assert artifact.process["input_snapshot"]["requirement_text"] == "Build the pipeline."
    assert artifact.process["output_snapshot"]["solution_summary"] == (
        "Use AL lanes with checkpointed integration."
    )
    assert artifact.process["output_refs"] == ["solution-design-artifact-1"]
    assert saved_stage is not None
    assert saved_stage.output_ref == "artifact-stage-1"


def test_complete_stage_output_updates_stage_updated_at_when_binding_output_ref(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)
        create_input_artifact(store)
        store._now = lambda: LATER  # type: ignore[method-assign]

        store.complete_stage_output(
            artifact_id="artifact-stage-1",
            payload_ref="payload-solution-design-1",
            output_snapshot={"solution_summary": "Use AL lanes."},
            output_refs=["solution-design-artifact-1"],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        saved_stage = runtime_session.get(StageRunModel, "stage-run-1")

    assert saved_stage is not None
    assert saved_stage.updated_at == LATER.replace(tzinfo=None)


def test_complete_stage_output_rejects_artifact_from_different_run_than_stage(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session, run_id="run-1")
        seed_run(runtime_session, run_id="run-2")
        seed_stage(runtime_session, stage_run_id="stage-run-1", run_id="run-1")
        runtime_session.add(
            StageArtifactModel(
                artifact_id="artifact-stage-1",
                run_id="run-2",
                stage_run_id="stage-run-1",
                artifact_type="solution_design_artifact",
                payload_ref="payload-stage-1",
                process={"input_snapshot": {"requirement_text": "Build."}},
                metrics={},
                created_at=NOW,
            )
        )
        runtime_session.flush()
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)

        with pytest.raises(
            ArtifactStoreError,
            match="Stage artifact storage target was not found",
        ):
            store.complete_stage_output(
                artifact_id="artifact-stage-1",
                payload_ref="payload-solution-design-1",
                output_snapshot={"solution_summary": "Use AL lanes."},
                output_refs=["solution-design-artifact-1"],
                trace_context=build_trace(
                    run_id="run-2",
                    stage_run_id="stage-run-1",
                ),
            )

        saved_stage = runtime_session.get(StageRunModel, "stage-run-1")

    assert saved_stage is not None
    assert saved_stage.output_ref is None


def test_attach_metric_set_merges_metrics_without_clearing_prior_values(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)
        create_input_artifact(store)

        store.attach_metric_set(
            artifact_id="artifact-stage-1",
            metric_set={"input_tokens": 120, "tool_call_count": 2},
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        artifact = store.attach_metric_set(
            artifact_id="artifact-stage-1",
            metric_set={"output_tokens": 48},
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    assert artifact.metrics["input_tokens"] == 120
    assert artifact.metrics["tool_call_count"] == 2
    assert artifact.metrics["output_tokens"] == 48


def test_attach_metric_set_writes_runtime_log_with_metric_keys(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=lambda: NOW,
        )
        create_input_artifact(store)
        log_writer.records.clear()

        store.attach_metric_set(
            artifact_id="artifact-stage-1",
            metric_set={"input_tokens": 120, "tool_call_count": 2},
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    record = log_writer.records[0]
    assert record.category is LogCategory.RUNTIME
    assert record.payload.summary["action"] == "attach_metric_set"
    assert record.payload.summary["artifact_id"] == "artifact-stage-1"
    assert record.payload.summary["changed_metric_keys"] == [
        "input_tokens",
        "tool_call_count",
    ]


def test_get_stage_artifact_returns_persisted_runtime_truth(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)
        create_input_artifact(store)
        runtime_session.commit()

        loaded = store.get_stage_artifact("artifact-stage-1")

    assert loaded.process["input_snapshot"]["requirement_text"] == "Build the pipeline."


def test_get_stage_artifact_rejects_unknown_artifact(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        store = ArtifactStore(runtime_session=runtime_session, now=lambda: NOW)

        with pytest.raises(ArtifactStoreError, match="Stage artifact was not found"):
            store.get_stage_artifact("missing-artifact")


def test_storage_get_failures_raise_artifact_store_error_and_write_failure_log() -> None:
    log_writer = CapturingLogWriter()
    store = ArtifactStore(
        runtime_session=FailingGetSession(),  # type: ignore[arg-type]
        log_writer=log_writer,
        now=lambda: NOW,
    )

    with pytest.raises(ArtifactStoreError, match="Stage artifact storage is unavailable"):
        store.get_stage_artifact("artifact-stage-1")

    record = log_writer.records[0]
    assert record.payload.summary["action"] == "get_stage_artifact_failed"
    assert record.payload.summary["artifact_id"] == "artifact-stage-1"
    assert record.payload.summary["error_message"] == (
        "Stage artifact storage is unavailable."
    )


def test_storage_flush_failures_raise_artifact_store_error_and_write_failure_log() -> None:
    stage = StageRunModel(
        stage_run_id="stage-run-1",
        run_id="run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        status=StageStatus.RUNNING,
        attempt_index=1,
        graph_node_key="solution_design.main",
        stage_contract_ref="stage-contract-solution-design",
        input_ref=None,
        output_ref=None,
        summary="Designing solution.",
        started_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    log_writer = CapturingLogWriter()
    store = ArtifactStore(
        runtime_session=FailingFlushSession(stage),  # type: ignore[arg-type]
        log_writer=log_writer,
        now=lambda: NOW,
    )

    with pytest.raises(ArtifactStoreError, match="Stage artifact storage is unavailable"):
        store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-1",
            artifact_type="stage_input",
            payload_ref="payload-stage-1",
            input_snapshot={"requirement_text": "Build the pipeline."},
            input_refs=[],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    record = log_writer.records[0]
    assert record.payload.summary["action"] == "create_stage_input_failed"
    assert record.payload.summary["artifact_id"] == "artifact-stage-1"
    assert record.payload.summary["error_message"] == (
        "Stage artifact storage is unavailable."
    )


def test_artifact_store_writes_runtime_logs_with_redacted_payload_summaries(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=lambda: NOW,
        )

        long_requirement = "Build the pipeline. " + ("x" * 5000)
        store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-1",
            artifact_type="stage_input",
            payload_ref="payload-stage-1",
            input_snapshot={"requirement_text": long_requirement},
            input_refs=["session-message-1"],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    record = log_writer.records[0]
    assert record.source == "services.artifacts"
    assert record.category is LogCategory.RUNTIME
    assert record.trace_context.stage_run_id == "stage-run-1"
    assert record.payload.payload_type == "stage_artifact"
    assert record.payload.summary["artifact_id"] == "artifact-stage-1"
    assert record.payload.summary["action"] == "create_stage_input"
    assert "input_snapshot.requirement_text" in record.payload.summary["truncated_fields"]


def test_artifact_store_success_logs_normalize_trace_to_artifact_identity(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session, run_id="run-1")
        seed_run(runtime_session, run_id="wrong-run")
        seed_stage(runtime_session, stage_run_id="stage-run-1", run_id="run-1")
        store = ArtifactStore(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=lambda: NOW,
        )

        store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-1",
            artifact_type="stage_input",
            payload_ref="payload-stage-1",
            input_snapshot={"requirement_text": "Build the pipeline."},
            input_refs=["session-message-1"],
            trace_context=build_trace(
                run_id="wrong-run",
                stage_run_id="wrong-stage",
            ),
        )

    record = log_writer.records[0]
    assert record.trace_context.run_id == "run-1"
    assert record.trace_context.stage_run_id == "stage-run-1"
    assert record.trace_context.parent_span_id == "span-1"


def test_artifact_store_preserves_stable_log_metadata_when_redaction_blocks_payload(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(
            runtime_session=runtime_session,
            log_writer=log_writer,
            redaction_policy=BlockingRedactionPolicy(),  # type: ignore[arg-type]
            now=lambda: NOW,
        )

        store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-1",
            artifact_type="stage_input",
            payload_ref="payload-stage-1",
            input_snapshot={"requirement_text": "Bearer sensitive-token"},
            input_refs=["session-message-1"],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    summary = log_writer.records[0].payload.summary
    assert summary["blocked_reason"] == "sensitive_text_pattern"
    assert summary["action"] == "create_stage_input"
    assert summary["run_id"] == "run-1"
    assert summary["stage_run_id"] == "stage-run-1"
    assert summary["artifact_id"] == "artifact-stage-1"
    assert summary["artifact_type"] == "stage_input"
    assert summary["payload_ref"] == "payload-stage-1"
    assert summary["changed_process_keys"] == ["input_snapshot", "input_refs"]


def test_artifact_store_keeps_persisted_artifact_when_log_writer_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(
            runtime_session=runtime_session,
            log_writer=FailingLogWriter(),
            now=lambda: NOW,
        )

        store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-1",
            artifact_type="stage_input",
            payload_ref="payload-stage-1",
            input_snapshot={"requirement_text": "Build the pipeline."},
            input_refs=["session-message-1"],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        runtime_session.commit()
        saved = runtime_session.get(StageArtifactModel, "artifact-stage-1")

    assert saved is not None


def test_artifact_store_keeps_persisted_artifact_when_redaction_fails(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        seed_stage(runtime_session)
        store = ArtifactStore(
            runtime_session=runtime_session,
            log_writer=CapturingLogWriter(),
            redaction_policy=FailingRedactionPolicy(),  # type: ignore[arg-type]
            now=lambda: NOW,
        )

        store.create_stage_input(
            run_id="run-1",
            stage_run_id="stage-run-1",
            artifact_id="artifact-stage-1",
            artifact_type="stage_input",
            payload_ref="payload-stage-1",
            input_snapshot={"requirement_text": "Build the pipeline."},
            input_refs=["session-message-1"],
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        runtime_session.commit()
        saved = runtime_session.get(StageArtifactModel, "artifact-stage-1")

    assert saved is not None
