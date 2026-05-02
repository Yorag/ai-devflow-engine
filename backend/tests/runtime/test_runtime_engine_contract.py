from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError

from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.runtime_refs import (
    CheckpointPurpose,
    CheckpointRef,
    GraphInterruptRef,
    GraphInterruptStatus,
    GraphInterruptType,
    GraphThreadRef,
    GraphThreadStatus,
    RuntimeResumePayload,
)
from backend.app.domain.trace_context import TraceContext
from backend.app.runtime.base import (
    RuntimeEngine,
    RuntimeEngineResult,
    RuntimeExecutionContext,
    RuntimeInterrupt,
    RuntimeStepResult,
    RuntimeTerminalResult,
)
from backend.app.services.runtime_orchestration import CheckpointPort, RuntimeCommandPort


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-runtime-engine",
        trace_id="trace-runtime-engine",
        correlation_id="correlation-runtime-engine",
        span_id="span-runtime-engine",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        graph_thread_id="graph-thread-1",
        created_at=NOW,
    )


def build_thread() -> GraphThreadRef:
    return GraphThreadRef(
        thread_id="graph-thread-1",
        run_id="run-1",
        status=GraphThreadStatus.RUNNING,
        current_stage_run_id="stage-run-1",
        current_stage_type=StageType.REQUIREMENT_ANALYSIS,
    )


def build_checkpoint() -> CheckpointRef:
    return CheckpointRef(
        checkpoint_id="checkpoint-1",
        thread_id="graph-thread-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.REQUIREMENT_ANALYSIS,
        purpose=CheckpointPurpose.RUNNING_SAFE_POINT,
        workspace_snapshot_ref="workspace-snapshot-1",
    )


def build_context_kwargs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "run_id": "run-1",
        "session_id": "session-1",
        "thread": build_thread(),
        "trace_context": build_trace(),
        "template_snapshot_ref": "template-snapshot-1",
        "provider_snapshot_refs": ["provider-snapshot-1"],
        "model_binding_snapshot_refs": ["model-binding-snapshot-1"],
        "runtime_limit_snapshot_ref": "runtime-limit-snapshot-1",
        "provider_call_policy_snapshot_ref": "provider-call-policy-snapshot-1",
        "graph_definition_ref": "graph-definition-1",
        "delivery_channel_snapshot_ref": "delivery-channel-snapshot-1",
        "workspace_snapshot_ref": "workspace-snapshot-1",
    }
    values.update(overrides)
    return values


def build_context() -> RuntimeExecutionContext:
    return RuntimeExecutionContext(**build_context_kwargs())


def build_step_result_kwargs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "run_id": "run-1",
        "stage_run_id": "stage-run-1",
        "stage_type": StageType.REQUIREMENT_ANALYSIS,
        "status": StageStatus.COMPLETED,
        "trace_context": build_trace(),
        "artifact_refs": ["artifact-1"],
        "domain_event_refs": ["event-1"],
        "log_summary_refs": ["runtime-log-summary-1"],
        "audit_refs": ["audit-entry-1"],
        "checkpoint_ref": build_checkpoint(),
    }
    values.update(overrides)
    return values


def build_interrupt() -> RuntimeInterrupt:
    interrupt_ref = GraphInterruptRef(
        interrupt_id="interrupt-approval-1",
        thread=build_thread(),
        interrupt_type=GraphInterruptType.APPROVAL,
        status=GraphInterruptStatus.PENDING,
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        payload_ref="approval-request-1",
        approval_id="approval-1",
        checkpoint_ref=build_checkpoint(),
    )
    return RuntimeInterrupt(
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type=StageType.SOLUTION_DESIGN,
        interrupt_ref=interrupt_ref,
        payload_ref="approval-request-1",
        trace_context=build_trace(),
        artifact_refs=["solution-artifact-1"],
        domain_event_refs=["approval-requested-event-1"],
        log_summary_refs=["runtime-log-summary-1"],
        audit_refs=["audit-entry-1"],
    )


def build_terminal() -> RuntimeTerminalResult:
    return RuntimeTerminalResult(
        run_id="run-1",
        status=GraphThreadStatus.COMPLETED,
        thread=build_thread().model_copy(
            update={"status": GraphThreadStatus.COMPLETED}
        ),
        trace_context=build_trace(),
        result_ref="delivery-result-1",
        domain_event_refs=["run-completed-event-1"],
        artifact_refs=["delivery-artifact-1"],
        log_summary_refs=["runtime-log-summary-2"],
        audit_refs=["audit-entry-2"],
    )


def model_kwargs(model: Any, **overrides: Any) -> dict[str, Any]:
    values = model.model_dump()
    values.update(overrides)
    return values


def test_runtime_execution_context_requires_frozen_run_snapshot_refs() -> None:
    context = build_context()

    assert context.run_id == "run-1"
    assert context.thread.thread_id == "graph-thread-1"
    assert context.trace_context.trace_id == "trace-runtime-engine"
    assert context.template_snapshot_ref == "template-snapshot-1"
    assert context.provider_snapshot_refs == ["provider-snapshot-1"]
    assert context.model_binding_snapshot_refs == ["model-binding-snapshot-1"]
    assert context.runtime_limit_snapshot_ref == "runtime-limit-snapshot-1"
    assert (
        context.provider_call_policy_snapshot_ref
        == "provider-call-policy-snapshot-1"
    )
    assert context.graph_definition_ref == "graph-definition-1"
    assert context.delivery_channel_snapshot_ref == "delivery-channel-snapshot-1"
    assert context.workspace_snapshot_ref == "workspace-snapshot-1"

    with pytest.raises(ValidationError, match="provider_snapshot_refs"):
        RuntimeExecutionContext(
            run_id="run-1",
            session_id="session-1",
            thread=build_thread(),
            trace_context=build_trace(),
            template_snapshot_ref="template-snapshot-1",
            provider_snapshot_refs=[],
            model_binding_snapshot_refs=["model-binding-snapshot-1"],
            runtime_limit_snapshot_ref="runtime-limit-snapshot-1",
            provider_call_policy_snapshot_ref="provider-call-policy-snapshot-1",
            graph_definition_ref="graph-definition-1",
        )

    with pytest.raises(ValidationError, match="model_binding_snapshot_refs"):
        RuntimeExecutionContext(
            run_id="run-1",
            session_id="session-1",
            thread=build_thread(),
            trace_context=build_trace(),
            template_snapshot_ref="template-snapshot-1",
            provider_snapshot_refs=["provider-snapshot-1"],
            model_binding_snapshot_refs=[],
            runtime_limit_snapshot_ref="runtime-limit-snapshot-1",
            provider_call_policy_snapshot_ref="provider-call-policy-snapshot-1",
            graph_definition_ref="graph-definition-1",
        )


def test_runtime_execution_context_rejects_identity_mismatches_and_empty_refs() -> None:
    with pytest.raises(ValidationError):
        RuntimeExecutionContext(
            **build_context_kwargs(
                thread=build_thread().model_copy(update={"run_id": "other-run"})
            )
        )

    with pytest.raises(ValidationError):
        RuntimeExecutionContext(
            **build_context_kwargs(
                trace_context=build_trace().model_copy(update={"run_id": "other-run"})
            )
        )

    with pytest.raises(ValidationError):
        RuntimeExecutionContext(
            **build_context_kwargs(
                trace_context=build_trace().model_copy(
                    update={"session_id": "other-session"}
                )
            )
        )

    with pytest.raises(ValidationError):
        RuntimeExecutionContext(
            **build_context_kwargs(
                trace_context=build_trace().model_copy(
                    update={"graph_thread_id": "other-thread"}
                )
            )
        )

    with pytest.raises(ValidationError):
        RuntimeExecutionContext(
            **build_context_kwargs(provider_snapshot_refs=[""])
        )

    with pytest.raises(ValidationError):
        RuntimeExecutionContext(
            **build_context_kwargs(model_binding_snapshot_refs=[""])
        )


def test_runtime_models_are_strict_and_do_not_expose_raw_engine_state() -> None:
    with pytest.raises(ValidationError, match="raw_graph_state"):
        RuntimeStepResult(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_GENERATION,
            status=StageStatus.COMPLETED,
            trace_context=build_trace(),
            artifact_refs=["artifact-1"],
            domain_event_refs=["event-1"],
            raw_graph_state={"forbidden": True},
        )

    result = RuntimeStepResult(**build_step_result_kwargs())

    assert result.artifact_refs == ["artifact-1"]
    assert result.domain_event_refs == ["event-1"]
    assert result.log_summary_refs == ["runtime-log-summary-1"]
    assert result.audit_refs == ["audit-entry-1"]
    assert result.checkpoint_ref is not None


def test_runtime_step_result_rejects_checkpoint_trace_and_empty_ref_mismatches() -> None:
    with pytest.raises(ValidationError):
        RuntimeStepResult(
            **build_step_result_kwargs(
                trace_context=build_trace().model_copy(update={"run_id": "other-run"})
            )
        )

    with pytest.raises(ValidationError):
        RuntimeStepResult(
            **build_step_result_kwargs(
                trace_context=build_trace().model_copy(
                    update={"stage_run_id": "other-stage-run"}
                )
            )
        )

    with pytest.raises(ValidationError):
        RuntimeStepResult(
            **build_step_result_kwargs(
                checkpoint_ref=build_checkpoint().model_copy(
                    update={"run_id": "other-run"}
                )
            )
        )

    with pytest.raises(ValidationError):
        RuntimeStepResult(
            **build_step_result_kwargs(
                checkpoint_ref=build_checkpoint().model_copy(
                    update={"stage_run_id": "other-stage-run"}
                )
            )
        )

    with pytest.raises(ValidationError):
        RuntimeStepResult(
            **build_step_result_kwargs(
                checkpoint_ref=build_checkpoint().model_copy(
                    update={"stage_type": StageType.CODE_GENERATION}
                )
            )
        )

    for field_name in (
        "artifact_refs",
        "domain_event_refs",
        "log_summary_refs",
        "audit_refs",
    ):
        with pytest.raises(ValidationError):
            RuntimeStepResult(**build_step_result_kwargs(**{field_name: [""]}))


def test_runtime_interrupt_and_terminal_result_keep_domain_refs() -> None:
    interrupt = build_interrupt()
    terminal = build_terminal()

    assert interrupt.interrupt_ref.approval_id == "approval-1"
    assert interrupt.payload_ref == "approval-request-1"
    assert interrupt.trace_context.trace_id == "trace-runtime-engine"
    assert interrupt.artifact_refs == ["solution-artifact-1"]
    assert interrupt.domain_event_refs == ["approval-requested-event-1"]
    assert interrupt.log_summary_refs == ["runtime-log-summary-1"]
    assert interrupt.audit_refs == ["audit-entry-1"]
    assert terminal.result_ref == "delivery-result-1"
    assert terminal.thread.status is GraphThreadStatus.COMPLETED
    assert terminal.trace_context.trace_id == "trace-runtime-engine"

    with pytest.raises(ValidationError, match="raw_graph_state"):
        RuntimeInterrupt(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            interrupt_ref=interrupt.interrupt_ref,
            payload_ref="approval-request-1",
            trace_context=build_trace(),
            raw_graph_state={"forbidden": True},
        )

    with pytest.raises(ValidationError, match="raw_graph_state"):
        RuntimeTerminalResult(
            run_id="run-1",
            status=GraphThreadStatus.COMPLETED,
            thread=build_thread(),
            trace_context=build_trace(),
            raw_graph_state={"forbidden": True},
        )


def test_runtime_interrupt_rejects_mismatched_nested_refs() -> None:
    interrupt = build_interrupt()

    for field_name, value in (
        ("run_id", "other-run"),
        ("stage_run_id", "other-stage-run"),
        ("stage_type", StageType.CODE_GENERATION),
        ("payload_ref", "other-payload"),
    ):
        with pytest.raises(ValidationError):
            RuntimeInterrupt(
                **model_kwargs(
                    interrupt,
                    interrupt_ref=interrupt.interrupt_ref.model_copy(
                        update={field_name: value}
                    ),
                )
            )

    with pytest.raises(ValidationError):
        RuntimeInterrupt(
            **model_kwargs(
                interrupt,
                trace_context=build_trace().model_copy(update={"run_id": "other-run"}),
            )
        )

    with pytest.raises(ValidationError):
        RuntimeInterrupt(
            **model_kwargs(
                interrupt,
                trace_context=build_trace().model_copy(
                    update={"stage_run_id": "other-stage-run"}
                ),
            ),
        )

    for field_name in (
        "artifact_refs",
        "domain_event_refs",
        "log_summary_refs",
        "audit_refs",
    ):
        with pytest.raises(ValidationError):
            RuntimeInterrupt(**model_kwargs(interrupt, **{field_name: [""]}))


def test_runtime_terminal_result_requires_terminal_matching_thread() -> None:
    with pytest.raises(ValidationError):
        RuntimeTerminalResult(
            run_id="run-1",
            status=GraphThreadStatus.RUNNING,
            thread=build_thread(),
            trace_context=build_trace(),
        )

    with pytest.raises(ValidationError):
        RuntimeTerminalResult(
            run_id="run-1",
            status=GraphThreadStatus.COMPLETED,
            thread=build_thread().model_copy(
                update={"status": GraphThreadStatus.FAILED}
            ),
            trace_context=build_trace(),
        )

    with pytest.raises(ValidationError):
        RuntimeTerminalResult(
            run_id="run-1",
            status=GraphThreadStatus.COMPLETED,
            thread=build_thread().model_copy(
                update={"run_id": "other-run", "status": GraphThreadStatus.COMPLETED}
            ),
            trace_context=build_trace(),
        )

    with pytest.raises(ValidationError):
        RuntimeTerminalResult(
            run_id="run-1",
            status=GraphThreadStatus.COMPLETED,
            thread=build_thread().model_copy(
                update={"status": GraphThreadStatus.COMPLETED}
            ),
            trace_context=build_trace().model_copy(update={"run_id": "other-run"}),
        )

    terminal = build_terminal()
    for field_name in (
        "artifact_refs",
        "domain_event_refs",
        "log_summary_refs",
        "audit_refs",
    ):
        with pytest.raises(ValidationError):
            RuntimeTerminalResult(**model_kwargs(terminal, **{field_name: [""]}))


def test_runtime_engine_protocol_uses_a4_0_ports_and_trace_context() -> None:
    class FakeRuntimeEngine:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def start(
            self,
            *,
            context: RuntimeExecutionContext,
            runtime_port: RuntimeCommandPort,
            checkpoint_port: CheckpointPort,
        ) -> RuntimeEngineResult:
            self.calls.append(("start", context.trace_context))
            return RuntimeStepResult(
                run_id=context.run_id,
                stage_run_id="stage-run-1",
                stage_type=StageType.REQUIREMENT_ANALYSIS,
                status=StageStatus.RUNNING,
                trace_context=context.trace_context,
                domain_event_refs=["stage-started-event-1"],
            )

        def run_next(
            self,
            *,
            context: RuntimeExecutionContext,
            runtime_port: RuntimeCommandPort,
            checkpoint_port: CheckpointPort,
        ) -> RuntimeEngineResult:
            self.calls.append(("run_next", context.trace_context))
            return RuntimeStepResult(
                run_id=context.run_id,
                stage_run_id="stage-run-1",
                stage_type=StageType.REQUIREMENT_ANALYSIS,
                status=StageStatus.COMPLETED,
                trace_context=context.trace_context,
                artifact_refs=["requirement-artifact-1"],
                domain_event_refs=["stage-completed-event-1"],
            )

        def resume(
            self,
            *,
            context: RuntimeExecutionContext,
            interrupt: RuntimeInterrupt,
            resume_payload: RuntimeResumePayload,
            runtime_port: RuntimeCommandPort,
            checkpoint_port: CheckpointPort,
        ) -> RuntimeEngineResult:
            self.calls.append(("resume", resume_payload.payload_ref))
            return RuntimeStepResult(
                run_id=context.run_id,
                stage_run_id=interrupt.stage_run_id,
                stage_type=interrupt.stage_type,
                status=StageStatus.RUNNING,
                trace_context=context.trace_context,
                domain_event_refs=["interrupt-resumed-event-1"],
            )

        def terminate(
            self,
            *,
            context: RuntimeExecutionContext,
            runtime_port: RuntimeCommandPort,
            checkpoint_port: CheckpointPort,
        ) -> RuntimeTerminalResult:
            self.calls.append(("terminate", context.thread.thread_id))
            return RuntimeTerminalResult(
                run_id=context.run_id,
                status=GraphThreadStatus.TERMINATED,
                thread=context.thread.model_copy(
                    update={"status": GraphThreadStatus.TERMINATED}
                ),
                trace_context=context.trace_context,
                result_ref="terminated-result-1",
                domain_event_refs=["run-terminated-event-1"],
            )

    engine: RuntimeEngine = FakeRuntimeEngine()
    context = build_context()
    interrupt = build_interrupt()
    resume_payload = RuntimeResumePayload(
        resume_id="resume-approval-1",
        payload_ref="approval-result-1",
        values={"approved": True},
    )

    start_result = engine.start(
        context=context,
        runtime_port=object(),  # type: ignore[arg-type]
        checkpoint_port=object(),  # type: ignore[arg-type]
    )
    next_result = engine.run_next(
        context=context,
        runtime_port=object(),  # type: ignore[arg-type]
        checkpoint_port=object(),  # type: ignore[arg-type]
    )
    resume_result = engine.resume(
        context=context,
        interrupt=interrupt,
        resume_payload=resume_payload,
        runtime_port=object(),  # type: ignore[arg-type]
        checkpoint_port=object(),  # type: ignore[arg-type]
    )
    terminal_result = engine.terminate(
        context=context,
        runtime_port=object(),  # type: ignore[arg-type]
        checkpoint_port=object(),  # type: ignore[arg-type]
    )

    assert start_result.trace_context == context.trace_context
    assert next_result.artifact_refs == ["requirement-artifact-1"]
    assert resume_result.domain_event_refs == ["interrupt-resumed-event-1"]
    assert terminal_result.status is GraphThreadStatus.TERMINATED


def test_runtime_engine_protocol_signature_exposes_expected_boundary() -> None:
    start_hints = get_type_hints(RuntimeEngine.start)
    run_next_hints = get_type_hints(RuntimeEngine.run_next)
    resume_hints = get_type_hints(RuntimeEngine.resume)
    terminate_hints = get_type_hints(RuntimeEngine.terminate)

    assert start_hints["context"] is RuntimeExecutionContext
    assert start_hints["runtime_port"] is RuntimeCommandPort
    assert start_hints["checkpoint_port"] is CheckpointPort
    assert start_hints["return"] == RuntimeEngineResult

    assert run_next_hints["context"] is RuntimeExecutionContext
    assert run_next_hints["runtime_port"] is RuntimeCommandPort
    assert run_next_hints["checkpoint_port"] is CheckpointPort
    assert run_next_hints["return"] == RuntimeEngineResult

    assert resume_hints["context"] is RuntimeExecutionContext
    assert resume_hints["interrupt"] is RuntimeInterrupt
    assert resume_hints["resume_payload"] is RuntimeResumePayload
    assert resume_hints["runtime_port"] is RuntimeCommandPort
    assert resume_hints["checkpoint_port"] is CheckpointPort
    assert resume_hints["return"] == RuntimeEngineResult

    assert terminate_hints["context"] is RuntimeExecutionContext
    assert terminate_hints["runtime_port"] is RuntimeCommandPort
    assert terminate_hints["checkpoint_port"] is CheckpointPort
    assert terminate_hints["return"] is RuntimeTerminalResult
