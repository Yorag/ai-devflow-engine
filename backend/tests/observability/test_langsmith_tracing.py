from __future__ import annotations

from contextlib import contextmanager
from typing import Any


class FakeRun:
    def __init__(self) -> None:
        self.outputs: dict[str, Any] = {}
        self.metadata: dict[str, Any] = {}

    def add_outputs(self, outputs: dict[str, Any]) -> None:
        self.outputs.update(outputs)

    def add_metadata(self, metadata: dict[str, Any]) -> None:
        self.metadata.update(metadata)


def test_langsmith_runtime_tracer_is_noop_when_tracing_disabled() -> None:
    from backend.app.observability.langsmith_tracing import LangSmithRuntimeTracer

    calls: list[str] = []

    @contextmanager
    def fake_trace(**kwargs: Any) -> Any:
        calls.append(kwargs["name"])
        yield FakeRun()

    tracer = LangSmithRuntimeTracer(
        trace_factory=fake_trace,
        tracing_enabled=lambda: False,
    )

    with tracer.trace_stage(
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type="code_generation",
        graph_node_key="code_generation",
    ):
        pass

    assert calls == []


def test_langsmith_runtime_tracer_emits_safe_hierarchical_spans() -> None:
    from backend.app.observability.langsmith_tracing import LangSmithRuntimeTracer

    calls: list[dict[str, Any]] = []
    runs: list[FakeRun] = []

    @contextmanager
    def fake_trace(**kwargs: Any) -> Any:
        calls.append(kwargs)
        run = FakeRun()
        runs.append(run)
        yield run

    tracer = LangSmithRuntimeTracer(
        trace_factory=fake_trace,
        tracing_enabled=lambda: True,
    )

    with tracer.trace_stage(
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type="code_generation",
        graph_node_key="code_generation",
    ):
        with tracer.trace_iteration(
            iteration_index=1,
            model_call_type="stage_execution",
            tool_result_count=0,
        ):
            tracer.record_model_decision(
                decision_type="request_tool_call",
                status="accepted",
                trace_ref="decision-1",
                model_call_ref="model-call-1",
            )
            with tracer.trace_tool_call(
                tool_name="read_file",
                call_id="call-1",
                input_payload={
                    "path": "frontend/src/pages/HomePage.tsx",
                    "content": "secret body must not be copied",
                },
            ):
                tracer.record_tool_result(
                    tool_name="read_file",
                    call_id="call-1",
                    status="succeeded",
                    artifact_refs=("tool-result://call-1",),
                    side_effect_refs=(),
                    error_code=None,
                    safe_details={},
                )

    assert [call["name"] for call in calls] == [
        "stage_agent.code_generation",
        "stage_agent.iteration.1",
        "stage_agent.tool.read_file",
    ]
    assert calls[0]["metadata"]["run_id"] == "run-1"
    assert calls[1]["parent"] is runs[0]
    assert calls[2]["parent"] is runs[1]
    assert calls[2]["inputs"] == {
        "tool_name": "read_file",
        "call_id": "call-1",
        "input_payload_summary": {
            "path": "frontend/src/pages/HomePage.tsx",
            "input_keys": ["content", "path"],
            "payload_size_bytes": 85,
            "redaction_status": "summary_only",
        },
    }
    assert runs[1].outputs["decision_type"] == "request_tool_call"
    assert runs[2].outputs["status"] == "succeeded"
    assert "secret body" not in str(calls)


def test_langsmith_runtime_tracer_swallows_trace_errors() -> None:
    from backend.app.observability.langsmith_tracing import LangSmithRuntimeTracer

    @contextmanager
    def failing_trace(**kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("langsmith unavailable")
        yield FakeRun()

    tracer = LangSmithRuntimeTracer(
        trace_factory=failing_trace,
        tracing_enabled=lambda: True,
    )

    with tracer.trace_stage(
        run_id="run-1",
        stage_run_id="stage-run-1",
        stage_type="code_generation",
        graph_node_key="code_generation",
    ):
        tracer.record_model_decision(
            decision_type="submit_stage_artifact",
            status="accepted",
            trace_ref="decision-1",
            model_call_ref="model-call-1",
        )


def test_langsmith_runtime_tracer_does_not_swallow_business_errors() -> None:
    from backend.app.observability.langsmith_tracing import LangSmithRuntimeTracer

    exits: list[tuple[type[BaseException] | None, BaseException | None]] = []

    class FakeManager:
        def __enter__(self) -> FakeRun:
            return FakeRun()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: Any,
        ) -> None:
            del tb
            exits.append((exc_type, exc))

    def fake_trace(**kwargs: Any) -> FakeManager:
        del kwargs
        return FakeManager()

    tracer = LangSmithRuntimeTracer(
        trace_factory=fake_trace,
        tracing_enabled=lambda: True,
    )

    try:
        with tracer.trace_stage(
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type="code_generation",
            graph_node_key="code_generation",
        ):
            raise ValueError("business failure")
    except ValueError:
        pass

    assert exits[0][0] is ValueError
    assert isinstance(exits[0][1], ValueError)
