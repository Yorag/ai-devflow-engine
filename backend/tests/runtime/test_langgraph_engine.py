from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.graph_definition import GraphDefinition
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphThreadRef,
    GraphThreadStatus,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.runtime.base import RuntimeExecutionContext, RuntimeStepResult
from backend.app.services.graph_compiler import GraphCompiler


NOW = datetime(2026, 5, 4, 9, 40, 0, tzinfo=UTC)
EXPECTED_STAGE_SEQUENCE = [
    StageType.REQUIREMENT_ANALYSIS,
    StageType.SOLUTION_DESIGN,
    StageType.CODE_GENERATION,
    StageType.TEST_GENERATION_EXECUTION,
    StageType.CODE_REVIEW,
    StageType.DELIVERY_INTEGRATION,
]


class CapturingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return SimpleNamespace(log_id=f"log-{len(self.records)}")


class FailingRunLogWriter:
    def write_run_log(self, record: LogRecordInput) -> object:
        raise RuntimeError("log sink unavailable")


class CapturingCheckpointPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def save_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        purpose: CheckpointPurpose,
        trace_context: TraceContext,
        stage_run_id: str | None = None,
        stage_type: StageType | None = None,
        workspace_snapshot_ref: str | None = None,
        payload_ref: str | None = None,
    ) -> CheckpointRef:
        self.calls.append(
            {
                "thread": thread,
                "purpose": purpose,
                "trace_context": trace_context,
                "stage_run_id": stage_run_id,
                "stage_type": stage_type,
                "workspace_snapshot_ref": workspace_snapshot_ref,
                "payload_ref": payload_ref,
            }
        )
        return CheckpointRef(
            checkpoint_id=f"checkpoint-{len(self.calls)}",
            thread_id=thread.thread_id,
            run_id=thread.run_id,
            stage_run_id=stage_run_id,
            stage_type=stage_type,
            purpose=purpose,
            workspace_snapshot_ref=workspace_snapshot_ref,
            payload_ref=payload_ref,
        )

    def load_checkpoint(
        self,
        *,
        thread: GraphThreadRef,
        checkpoint: CheckpointRef,
        trace_context: TraceContext,
    ) -> CheckpointRef:
        return checkpoint


class CapturingRuntimeCommandPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., object]:
        def _capture(**kwargs: Any) -> object:
            self.calls.append((name, kwargs))
            raise AssertionError(f"A4.5 LangGraph runtime must not call {name}")

        return _capture


class FakeStageRunner:
    def __init__(self, *, route_once: str | None = None) -> None:
        self.invocations: list[Any] = []
        self._route_once = route_once

    def run_stage(self, invocation: Any) -> Any:
        from backend.app.runtime.stage_runner_port import StageNodeResult

        self.invocations.append(invocation)
        route_key = None
        if invocation.stage_type is StageType.CODE_REVIEW and self._route_once:
            route_key = self._route_once
            self._route_once = None
        return StageNodeResult(
            run_id=invocation.run_id,
            stage_run_id=invocation.stage_run_id,
            stage_type=invocation.stage_type,
            status=StageStatus.COMPLETED,
            artifact_refs=[
                f"artifact-{invocation.stage_type.value}-{len(self.invocations)}"
            ],
            domain_event_refs=[
                f"event-{invocation.stage_type.value}-{len(self.invocations)}"
            ],
            log_summary_refs=[
                f"log-{invocation.stage_type.value}-{len(self.invocations)}"
            ],
            audit_refs=[],
            route_key=route_key,
        )


class WaitingStageRunner:
    def __init__(self) -> None:
        self.invocations: list[Any] = []

    def run_stage(self, invocation: Any) -> Any:
        from backend.app.runtime.stage_runner_port import StageNodeResult

        self.invocations.append(invocation)
        return StageNodeResult(
            run_id=invocation.run_id,
            stage_run_id=invocation.stage_run_id,
            stage_type=invocation.stage_type,
            status=StageStatus.WAITING_TOOL_CONFIRMATION,
            artifact_refs=[],
            domain_event_refs=[],
            log_summary_refs=[],
            audit_refs=[],
            route_key="waiting_tool_confirmation",
        )


class BadIdentityStageRunner:
    def __init__(self, *, field_name: str, value: object) -> None:
        self.field_name = field_name
        self.value = value

    def run_stage(self, invocation: Any) -> Any:
        from backend.app.runtime.stage_runner_port import StageNodeResult

        values = {
            "run_id": invocation.run_id,
            "stage_run_id": invocation.stage_run_id,
            "stage_type": invocation.stage_type,
            "status": StageStatus.COMPLETED,
            "artifact_refs": ["artifact-1"],
            "domain_event_refs": ["event-1"],
            "log_summary_refs": ["log-1"],
            "audit_refs": [],
            "route_key": None,
        }
        values[self.field_name] = self.value
        return StageNodeResult(**values)


def _clock() -> Callable[[], datetime]:
    ticks = iter(NOW + timedelta(milliseconds=index) for index in range(1000))
    return lambda: next(ticks)


def build_definition() -> GraphDefinition:
    from backend.tests.services.test_graph_compiler import (
        build_runtime_limit_snapshot,
        build_template_snapshot,
    )

    return GraphCompiler(now=lambda: NOW).compile(
        template_snapshot=build_template_snapshot(run_id="run-1"),
        runtime_limit_snapshot=build_runtime_limit_snapshot(run_id="run-1"),
    )


def build_trace(**overrides: Any) -> TraceContext:
    values = {
        "request_id": "request-1",
        "trace_id": "trace-1",
        "correlation_id": "correlation-1",
        "span_id": "span-root",
        "parent_span_id": None,
        "session_id": "session-1",
        "run_id": "run-1",
        "stage_run_id": None,
        "graph_thread_id": "graph-thread-1",
        "created_at": NOW,
    }
    values.update(overrides)
    return TraceContext(**values)


def build_context(**overrides: Any) -> RuntimeExecutionContext:
    values = {
        "run_id": "run-1",
        "session_id": "session-1",
        "thread": GraphThreadRef(
            thread_id="graph-thread-1",
            run_id="run-1",
            status=GraphThreadStatus.RUNNING,
            current_stage_run_id=None,
            current_stage_type=None,
        ),
        "trace_context": build_trace(),
        "template_snapshot_ref": "template-snapshot-run-1",
        "provider_snapshot_refs": ["provider-snapshot-1"],
        "model_binding_snapshot_refs": ["model-binding-1"],
        "runtime_limit_snapshot_ref": "runtime-limit-snapshot-run-1",
        "provider_call_policy_snapshot_ref": "policy-1",
        "graph_definition_ref": "graph-definition-run-1",
        "delivery_channel_snapshot_ref": None,
        "workspace_snapshot_ref": "workspace-1",
    }
    values.update(overrides)
    return RuntimeExecutionContext(**values)


def build_engine(
    *,
    runner: FakeStageRunner | None = None,
    log_writer: CapturingRunLogWriter | FailingRunLogWriter | None = None,
) -> tuple[
    Any,
    FakeStageRunner,
    CapturingCheckpointPort,
    CapturingRuntimeCommandPort,
]:
    from backend.app.runtime.langgraph_engine import LangGraphRuntimeEngine

    resolved_runner = runner or FakeStageRunner()
    engine = LangGraphRuntimeEngine(
        graph_definition=build_definition(),
        stage_runner=resolved_runner,
        checkpointer=InMemorySaver(),
        log_writer=log_writer,
        now=_clock(),
    )
    return (
        engine,
        resolved_runner,
        CapturingCheckpointPort(),
        CapturingRuntimeCommandPort(),
    )


def test_langgraph_runtime_advances_one_business_stage_per_run_next_call() -> None:
    engine, runner, checkpoint_port, runtime_port = build_engine(
        log_writer=CapturingRunLogWriter()
    )
    context = build_context()

    results = [
        engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
        for _ in range(6)
    ]

    assert all(isinstance(result, RuntimeStepResult) for result in results)
    assert [result.stage_type for result in results] == EXPECTED_STAGE_SEQUENCE
    assert [call.run_id for call in runner.invocations] == ["run-1"] * 6
    assert [call.stage_type for call in runner.invocations] == EXPECTED_STAGE_SEQUENCE
    assert [call.graph_node_key for call in runner.invocations] == [
        stage.value for stage in EXPECTED_STAGE_SEQUENCE
    ]
    assert [call.stage_run_id for call in runner.invocations] == [
        f"stage-run-run-1-{stage.value}" for stage in EXPECTED_STAGE_SEQUENCE
    ]
    assert [call.stage_contract_ref for call in runner.invocations] == [
        f"graph-definition-run-1/stage-contracts/{stage.value}"
        for stage in EXPECTED_STAGE_SEQUENCE
    ]
    assert all(call.runtime_context is context for call in runner.invocations)
    assert all(
        call.trace_context.graph_thread_id == "graph-thread-1"
        for call in runner.invocations
    )
    assert runtime_port.calls == []


def test_langgraph_runtime_requires_explicit_checkpointer() -> None:
    from backend.app.runtime.langgraph_engine import LangGraphRuntimeEngine

    with pytest.raises(ValueError, match="explicit checkpointer"):
        LangGraphRuntimeEngine(
            graph_definition=build_definition(),
            stage_runner=FakeStageRunner(),
            now=_clock(),
        )


def test_langgraph_runtime_uses_graph_thread_id_for_checkpointer_and_syncs_checkpoint_refs() -> None:
    engine, _runner, checkpoint_port, runtime_port = build_engine()
    context = build_context()

    first = engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    second = engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert first.checkpoint_ref is not None
    assert second.checkpoint_ref is not None
    assert first.checkpoint_ref.thread_id == "graph-thread-1"
    assert second.checkpoint_ref.thread_id == "graph-thread-1"
    assert [call["purpose"] for call in checkpoint_port.calls] == [
        CheckpointPurpose.RUNNING_SAFE_POINT,
        CheckpointPurpose.RUNNING_SAFE_POINT,
    ]
    assert [call["thread"].thread_id for call in checkpoint_port.calls] == [
        "graph-thread-1",
        "graph-thread-1",
    ]
    assert checkpoint_port.calls[0]["payload_ref"].startswith(
        "langgraph://graph-thread-1/checkpoints/default/"
    )
    assert checkpoint_port.calls[1]["payload_ref"].startswith(
        "langgraph://graph-thread-1/checkpoints/default/"
    )
    assert checkpoint_port.calls[0]["payload_ref"] != checkpoint_port.calls[1][
        "payload_ref"
    ]


def test_langgraph_runtime_wires_code_review_conditional_regression_route() -> None:
    runner = FakeStageRunner(route_once="review_regression_retry")
    engine, _runner, checkpoint_port, runtime_port = build_engine(runner=runner)
    context = build_context()

    for _ in range(6):
        engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    assert [call.stage_type for call in runner.invocations] == [
        StageType.REQUIREMENT_ANALYSIS,
        StageType.SOLUTION_DESIGN,
        StageType.CODE_GENERATION,
        StageType.TEST_GENERATION_EXECUTION,
        StageType.CODE_REVIEW,
        StageType.CODE_GENERATION,
    ]


def test_langgraph_runtime_returns_domain_refs_without_raw_graph_state() -> None:
    engine, _runner, checkpoint_port, runtime_port = build_engine()
    context = build_context()

    result = engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )
    dumped = result.model_dump(mode="json")

    assert dumped["artifact_refs"] == ["artifact-requirement_analysis-1"]
    assert dumped["domain_event_refs"] == ["event-requirement_analysis-1"]
    assert dumped["log_summary_refs"] == ["log-requirement_analysis-1"]
    assert "graph_state" not in dumped
    assert "compiled_graph" not in dumped
    assert "checkpoint_payload" not in dumped
    assert all("raw" not in key.lower() for key in dumped)


def test_langgraph_runtime_does_not_mark_waiting_stage_as_completed() -> None:
    runner = WaitingStageRunner()
    engine, _runner, checkpoint_port, runtime_port = build_engine(runner=runner)
    context = build_context()

    engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    snapshot = engine._checkpointer.get_tuple(  # noqa: SLF001
        {"configurable": {"thread_id": "graph-thread-1"}}
    )
    values = snapshot.checkpoint["channel_values"]
    assert values["last_result"]["status"] == (
        StageStatus.WAITING_TOOL_CONFIRMATION.value
    )
    assert values["completed_stage_run_ids"] == []


def test_langgraph_runtime_does_not_advance_after_waiting_stage_result() -> None:
    runner = WaitingStageRunner()
    engine, _runner, checkpoint_port, runtime_port = build_engine(runner=runner)
    context = build_context()

    engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    with pytest.raises(ValueError, match="non-completed stage result"):
        engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    assert [call.stage_type for call in runner.invocations] == [
        StageType.REQUIREMENT_ANALYSIS
    ]


def test_langgraph_runtime_logs_sanitized_internal_graph_events() -> None:
    log_writer = CapturingRunLogWriter()
    engine, _runner, checkpoint_port, runtime_port = build_engine(log_writer=log_writer)
    context = build_context()

    engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    messages = [record.message for record in log_writer.records]
    assert "LangGraph graph built." in messages
    assert "LangGraph thread started." in messages
    assert "LangGraph node started." in messages
    assert "LangGraph node completed." in messages
    assert "LangGraph checkpoint synchronized." in messages
    assert all(record.category.value == "runtime" for record in log_writer.records)
    assert all(record.source == "runtime.langgraph" for record in log_writer.records)
    assert all(
        record.trace_context.graph_thread_id == "graph-thread-1"
        for record in log_writer.records
    )
    assert {
        record.payload.summary["action"]
        for record in log_writer.records
    } >= {
        "graph_build",
        "thread_start",
        "node_started",
        "node_completed",
        "checkpoint_saved",
    }
    for record in log_writer.records:
        summary = record.payload.summary
        assert "raw" not in " ".join(summary)
        assert "graph_state" not in summary
        assert "compiled_graph" not in summary
        assert "checkpoint_payload" not in summary


def test_langgraph_runtime_reuses_existing_active_stage_run_id() -> None:
    engine, runner, checkpoint_port, runtime_port = build_engine()
    context = build_context(
        thread=GraphThreadRef(
            thread_id="graph-thread-1",
            run_id="run-1",
            status=GraphThreadStatus.RUNNING,
            current_stage_run_id="existing-stage-run-1",
            current_stage_type=StageType.REQUIREMENT_ANALYSIS,
        ),
    )

    result = engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert runner.invocations[0].stage_run_id == "existing-stage-run-1"
    assert result.stage_run_id == "existing-stage-run-1"
    assert checkpoint_port.calls[0]["stage_run_id"] == "existing-stage-run-1"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("run_id", "other-run"),
        ("stage_run_id", "other-stage-run"),
        ("stage_type", StageType.CODE_GENERATION),
    ],
)
def test_langgraph_runtime_rejects_mismatched_stage_node_result_identity(
    field_name: str,
    value: object,
) -> None:
    runner = BadIdentityStageRunner(field_name=field_name, value=value)
    engine, _runner, checkpoint_port, runtime_port = build_engine(runner=runner)
    context = build_context()

    with pytest.raises(ValueError, match="StageNodeResult"):
        engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    assert checkpoint_port.calls == []


def test_langgraph_runtime_logs_graph_failed_before_reraising() -> None:
    log_writer = CapturingRunLogWriter()
    runner = BadIdentityStageRunner(field_name="run_id", value="other-run")
    engine, _runner, checkpoint_port, runtime_port = build_engine(
        runner=runner,
        log_writer=log_writer,
    )
    context = build_context()

    with pytest.raises(ValueError, match="StageNodeResult.run_id"):
        engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )

    failed_records = [
        record
        for record in log_writer.records
        if record.payload.summary["action"] == "graph_failed"
    ]
    assert len(failed_records) == 1
    failed = failed_records[0]
    assert failed.message == "LangGraph execution failed."
    assert failed.level.value == "error"
    assert failed.trace_context.graph_thread_id == "graph-thread-1"
    assert failed.payload.summary["error_type"] == "ValueError"
    assert "StageNodeResult.run_id" in str(failed.payload.summary["error_message"])
    assert "graph_state" not in failed.payload.summary
    assert "compiled_graph" not in failed.payload.summary
    assert "checkpoint_payload" not in failed.payload.summary
    assert checkpoint_port.calls == []


def test_langgraph_runtime_log_writer_failure_does_not_mask_result() -> None:
    engine, _runner, checkpoint_port, runtime_port = build_engine(
        log_writer=FailingRunLogWriter()
    )
    context = build_context()

    result = engine.run_next(
        context=context,
        runtime_port=runtime_port,
        checkpoint_port=checkpoint_port,
    )

    assert isinstance(result, RuntimeStepResult)
    assert result.stage_type is StageType.REQUIREMENT_ANALYSIS
    assert result.checkpoint_ref is not None


def test_langgraph_runtime_rejects_mismatched_graph_definition_ref() -> None:
    engine, _runner, checkpoint_port, runtime_port = build_engine()
    context = build_context(graph_definition_ref="other-graph-definition")

    with pytest.raises(ValueError, match="graph_definition_ref"):
        engine.run_next(
            context=context,
            runtime_port=runtime_port,
            checkpoint_port=checkpoint_port,
        )
