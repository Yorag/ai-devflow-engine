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
    RuntimeBase,
    RuntimeLimitSnapshotModel,
    ProviderCallPolicySnapshotModel,
    StageRunModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import RunStatus, RunTriggerSource, StageStatus, StageType
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.observability.redaction import SENSITIVE_FIELD_PLACEHOLDER
from backend.app.repositories.runtime import StageRunRepository, StageRunRepositoryError
from backend.app.schemas.observability import LogCategory
from backend.app.services.stages import StageRunService


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


class FailingFlushSession:
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


def test_repository_persists_stage_run_with_graph_contract_refs(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        repository = StageRunRepository(runtime_session)

        repository.create_stage_run(
            stage_run_id="stage-run-1",
            run_id="run-1",
            stage_type=StageType.CODE_GENERATION,
            status=StageStatus.RUNNING,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            output_ref=None,
            summary="Starting code generation.",
            started_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        runtime_session.commit()

        saved = runtime_session.get(StageRunModel, "stage-run-1")

    assert saved is not None
    assert saved.graph_node_key == "code_generation.main"
    assert saved.stage_contract_ref == "stage-contract-code-generation"


def test_repository_maps_sqlalchemy_errors() -> None:
    repository = StageRunRepository(FailingFlushSession())  # type: ignore[arg-type]

    with pytest.raises(StageRunRepositoryError, match="Stage run storage is unavailable"):
        repository.create_stage_run(
            stage_run_id="stage-run-1",
            run_id="run-1",
            stage_type=StageType.CODE_GENERATION,
            status=StageStatus.RUNNING,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            output_ref=None,
            summary="Starting code generation.",
            started_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )


def test_start_stage_creates_running_stage_and_updates_run_pointer(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=lambda: NOW,
        )

        stage = service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="Starting code generation.",
            trace_context=build_trace(),
        )
        runtime_session.commit()

        saved_run = runtime_session.get(PipelineRunModel, "run-1")

    assert stage.status is StageStatus.RUNNING
    assert stage.started_at == NOW
    assert stage.ended_at is None
    assert saved_run is not None
    assert saved_run.current_stage_run_id == "stage-run-1"
    assert log_writer.records[0].source == "services.stages"


def test_mark_stage_waiting_keeps_current_stage_type_and_sets_waiting_status(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(runtime_session=runtime_session, now=lambda: NOW)
        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            attempt_index=1,
            graph_node_key="solution_design.main",
            stage_contract_ref="stage-contract-solution-design",
            input_ref="input-1",
            summary="Designing solution.",
            trace_context=build_trace(),
        )

        stage = service.mark_stage_waiting(
            stage_run_id="stage-run-1",
            status=StageStatus.WAITING_APPROVAL,
            summary="Waiting for solution design approval.",
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        saved_run = runtime_session.get(PipelineRunModel, "run-1")

    assert stage.stage_type is StageType.SOLUTION_DESIGN
    assert stage.status is StageStatus.WAITING_APPROVAL
    assert saved_run is not None
    assert saved_run.current_stage_run_id == "stage-run-1"


def test_complete_stage_marks_stage_completed_and_sets_output_ref_and_ended_at(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(runtime_session=runtime_session, now=lambda: NOW)
        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="Generating code.",
            trace_context=build_trace(),
        )
        service._now = lambda: LATER  # type: ignore[method-assign]

        stage = service.complete_stage(
            stage_run_id="stage-run-1",
            status=StageStatus.COMPLETED,
            output_ref="output-1",
            summary="Code generation completed.",
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    assert stage.status is StageStatus.COMPLETED
    assert stage.output_ref == "output-1"
    assert stage.ended_at == LATER


def test_complete_stage_allows_failed_status_without_new_public_method(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(runtime_session=runtime_session, now=lambda: NOW)
        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.TEST_GENERATION_EXECUTION,
            attempt_index=1,
            graph_node_key="test_generation_execution.main",
            stage_contract_ref="stage-contract-test-generation-execution",
            input_ref="input-1",
            summary="Running tests.",
            trace_context=build_trace(),
        )

        stage = service.complete_stage(
            stage_run_id="stage-run-1",
            status=StageStatus.FAILED,
            output_ref=None,
            summary="Tests failed.",
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

    assert stage.status is StageStatus.FAILED
    assert not hasattr(service, "fail_stage")


def test_service_rejects_invalid_waiting_status(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(runtime_session=runtime_session, now=lambda: NOW)
        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="Generating code.",
            trace_context=build_trace(),
        )

        with pytest.raises(ValueError, match="waiting status"):
            service.mark_stage_waiting(
                stage_run_id="stage-run-1",
                status=StageStatus.COMPLETED,
                summary="Invalid waiting transition.",
                trace_context=build_trace(stage_run_id="stage-run-1"),
            )


def test_service_rejects_waiting_transition_for_non_current_stage(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(runtime_session=runtime_session, now=lambda: NOW)
        first = service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="First code generation attempt.",
            trace_context=build_trace(),
        )
        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-2",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=2,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-2",
            summary="Second code generation attempt.",
            trace_context=build_trace(),
        )

        with pytest.raises(ValueError, match="current active stage"):
            service.mark_stage_waiting(
                stage_run_id=first.stage_run_id,
                status=StageStatus.WAITING_TOOL_CONFIRMATION,
                summary="Historical stage must not be rewritten.",
                trace_context=build_trace(stage_run_id=first.stage_run_id),
            )

        saved_first = runtime_session.get(StageRunModel, first.stage_run_id)

    assert saved_first is not None
    assert saved_first.status is StageStatus.RUNNING


def test_service_rejects_terminal_stage_rewrites(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(runtime_session=runtime_session, now=lambda: NOW)
        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="Generating code.",
            trace_context=build_trace(),
        )
        service.complete_stage(
            stage_run_id="stage-run-1",
            status=StageStatus.COMPLETED,
            output_ref="output-1",
            summary="Completed once.",
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )

        with pytest.raises(ValueError, match="terminal"):
            service.complete_stage(
                stage_run_id="stage-run-1",
                status=StageStatus.FAILED,
                output_ref=None,
                summary="Terminal row must not be rewritten.",
                trace_context=build_trace(stage_run_id="stage-run-1"),
            )

        with pytest.raises(ValueError, match="terminal"):
            service.mark_stage_waiting(
                stage_run_id="stage-run-1",
                status=StageStatus.WAITING_APPROVAL,
                summary="Terminal row must not become waiting.",
                trace_context=build_trace(stage_run_id="stage-run-1"),
            )

        saved = runtime_session.get(StageRunModel, "stage-run-1")

    assert saved is not None
    assert saved.status is StageStatus.COMPLETED
    assert saved.output_ref == "output-1"


def test_service_does_not_create_approval_pseudo_stage(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(runtime_session=runtime_session, now=lambda: NOW)
        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            attempt_index=1,
            graph_node_key="solution_design.main",
            stage_contract_ref="stage-contract-solution-design",
            input_ref="input-1",
            summary="Designing solution.",
            trace_context=build_trace(),
        )

        service.mark_stage_waiting(
            stage_run_id="stage-run-1",
            status=StageStatus.WAITING_APPROVAL,
            summary="Waiting for solution design approval.",
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        stages = runtime_session.query(StageRunModel).all()

    assert len(stages) == 1
    assert stages[0].stage_type is StageType.SOLUTION_DESIGN


def test_restarting_business_stage_creates_new_attempt_row(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(runtime_session=runtime_session, now=lambda: NOW)

        first = service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="First code generation attempt.",
            trace_context=build_trace(),
        )
        service.complete_stage(
            stage_run_id=first.stage_run_id,
            status=StageStatus.SUPERSEDED,
            output_ref=None,
            summary="Superseded by retry.",
            trace_context=build_trace(stage_run_id=first.stage_run_id),
        )
        second = service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-2",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=2,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-2",
            summary="Second code generation attempt.",
            trace_context=build_trace(),
        )

        stages = runtime_session.query(StageRunModel).order_by(StageRunModel.attempt_index).all()

    assert [stage.stage_run_id for stage in stages] == ["stage-run-1", "stage-run-2"]
    assert stages[0].status is StageStatus.SUPERSEDED
    assert second.attempt_index == 2


def test_stage_service_writes_runtime_log_with_inherited_trace_context(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=lambda: NOW,
        )

        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="Starting code generation.",
            trace_context=build_trace(),
        )

    record = log_writer.records[0]
    assert record.category is LogCategory.RUNTIME
    assert record.trace_context.trace_id == "trace-1"
    assert record.trace_context.stage_run_id == "stage-run-1"
    assert record.payload.summary["graph_node_key"] == SENSITIVE_FIELD_PLACEHOLDER
    assert record.payload.summary["stage_contract_ref"] == "stage-contract-code-generation"


def test_stage_service_log_summary_uses_redacted_truncated_payload(
    tmp_path: Path,
) -> None:
    manager = build_manager(tmp_path)
    log_writer = CapturingLogWriter()
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(
            runtime_session=runtime_session,
            log_writer=log_writer,
            now=lambda: NOW,
        )

        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-" + ("x" * 5000),
            summary="Starting code generation.",
            trace_context=build_trace(),
        )

    summary = log_writer.records[0].payload.summary
    assert summary["graph_node_key"] == SENSITIVE_FIELD_PLACEHOLDER
    assert summary["input_ref"] != "input-" + ("x" * 5000)
    assert str(summary["input_ref"]).endswith("...[truncated]")
    assert "graph_node_key" in summary["blocked_fields"]
    assert "input_ref" in summary["truncated_fields"]


def test_stage_service_keeps_domain_state_when_log_writer_fails(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(
            runtime_session=runtime_session,
            log_writer=FailingLogWriter(),
            now=lambda: NOW,
        )

        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="Generating code.",
            trace_context=build_trace(),
        )
        service.complete_stage(
            stage_run_id="stage-run-1",
            status=StageStatus.COMPLETED,
            output_ref="output-1",
            summary="Code generation completed.",
            trace_context=build_trace(stage_run_id="stage-run-1"),
        )
        runtime_session.commit()

        saved = runtime_session.get(StageRunModel, "stage-run-1")

    assert saved is not None
    assert saved.status is StageStatus.COMPLETED


def test_stage_service_keeps_domain_state_when_redaction_fails(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        seed_run(runtime_session)
        service = StageRunService(
            runtime_session=runtime_session,
            log_writer=CapturingLogWriter(),
            redaction_policy=FailingRedactionPolicy(),  # type: ignore[arg-type]
            now=lambda: NOW,
        )

        service.start_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            attempt_index=1,
            graph_node_key="code_generation.main",
            stage_contract_ref="stage-contract-code-generation",
            input_ref="input-1",
            summary="Generating code.",
            trace_context=build_trace(),
        )
        runtime_session.commit()

        saved = runtime_session.get(StageRunModel, "stage-run-1")

    assert saved is not None
    assert saved.status is StageStatus.RUNNING
