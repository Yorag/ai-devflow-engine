from __future__ import annotations

from datetime import UTC, datetime

from backend.app.providers.langchain_adapter import ModelCallTraceSummary, ModelCallUsage
from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import ProviderCircuitBreakerStatus, StageStatus
from backend.app.providers.retry_policy import (
    ProviderCircuitBreakerTraceRecord,
    ProviderRetryTraceRecord,
)
from backend.app.schemas.prompts import ModelCallType
from backend.tests.runtime.test_stage_agent_runtime import (
    code_generation_payload,
    build_runtime,
    invocation,
    model_result,
    read_file_call,
    succeeded_tool_result,
    trace_context,
)


NOW = datetime(2026, 5, 4, 18, 30, tzinfo=UTC)


def retry_trace() -> ProviderRetryTraceRecord:
    return ProviderRetryTraceRecord(
        trace_ref="provider-retry-trace-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        provider_snapshot_id="provider-snapshot-run-1",
        model_binding_snapshot_id="model-binding-snapshot-run-1",
        provider_id="provider-openai",
        model_id="gpt-5",
        failure_kind="timeout",
        retry_attempt=1,
        max_retry_attempts=2,
        backoff_wait_seconds=1.0,
        status="scheduled",
        error_code=ErrorCode.PROVIDER_RETRY_EXHAUSTED,
        occurred_at=NOW,
    )


def circuit_trace() -> ProviderCircuitBreakerTraceRecord:
    return ProviderCircuitBreakerTraceRecord(
        trace_ref="provider-circuit-breaker-trace-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        provider_snapshot_id="provider-snapshot-run-1",
        model_binding_snapshot_id="model-binding-snapshot-run-1",
        provider_id="provider-openai",
        model_id="gpt-5",
        status=ProviderCircuitBreakerStatus.OPEN,
        consecutive_failures=3,
        opened_at=NOW,
        next_retry_at=NOW,
        failure_kind="timeout",
        action="opened",
        occurred_at=NOW,
    )


def fail_stage_payload() -> dict[str, object]:
    return {
        "decision_type": "fail_stage",
        "failure_reason": "cannot continue",
        "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
        "incomplete_items": ["artifact"],
        "user_visible_summary": "Cannot continue.",
    }


def test_stage_agent_records_provider_retry_and_circuit_breaker_traces() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output=fail_stage_payload(),
                provider_retry_trace=(retry_trace(),),
                provider_circuit_breaker_trace=(circuit_trace(),),
            )
        ]
    )

    runtime.run_stage(invocation())

    assert "provider_retry_trace" in runtime.artifact_store.append_keys()
    assert "provider_circuit_breaker_trace" in runtime.artifact_store.append_keys()


def test_stage_agent_notifies_progress_after_each_process_record() -> None:
    progress_records: list[tuple[str, str]] = []
    runtime = build_runtime(
        provider_results=[model_result(structured_output=fail_stage_payload())],
        progress_callback=lambda request, process_key, process_ref: progress_records.append(
            (process_key, process_ref)
        ),
    )

    runtime.run_stage(invocation())

    assert progress_records[0] == (
        "stage_agent_started",
        "stage-artifact://artifact-stage-run-1#process/stage_agent_started",
    )
    assert (
        "model_call_trace",
        "stage-artifact://artifact-stage-run-1#process/model_call_trace",
    ) in progress_records
    assert (
        "decision_trace",
        "stage-artifact://artifact-stage-run-1#process/decision_trace",
    ) in progress_records


def test_stage_agent_repair_decision_records_repair_trace_and_uses_repair_prompt_next() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "repair_structured_output",
                    "parse_error": "missing field",
                    "repair_instruction": "return valid artifact",
                    "invalid_output_ref": "sha256:bad",
                }
            ),
            model_result(structured_output=fail_stage_payload()),
        ]
    )

    runtime.run_stage(invocation())

    assert "structured_output_repair_trace" in runtime.artifact_store.append_keys()
    assert runtime.context_builder.requests[1].model_call_type is (
        ModelCallType.STRUCTURED_OUTPUT_REPAIR
    )
    assert runtime.context_builder.requests[1].parse_error == "missing field"
    assert runtime.context_builder.requests[1].trace_context == trace_context()


def test_stage_agent_does_not_bind_tools_during_structured_output_repair() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "repair_structured_output",
                    "parse_error": "missing field",
                    "repair_instruction": "return valid artifact",
                    "invalid_output_ref": "sha256:bad",
                }
            ),
            model_result(structured_output=fail_stage_payload()),
        ],
    )

    runtime.run_stage(invocation())

    assert runtime.context_builder.requests[1].model_call_type is (
        ModelCallType.STRUCTURED_OUTPUT_REPAIR
    )
    assert runtime.provider_adapter.calls[1]["tool_descriptions"] == ()


def test_stage_agent_includes_tool_result_observations_in_next_model_call() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(tool_call_requests=(read_file_call("call-1"),)),
            model_result(structured_output=fail_stage_payload()),
        ],
        tool_results=[succeeded_tool_result("call-1")],
    )

    runtime.run_stage(invocation())

    second_call_messages = runtime.provider_adapter.calls[1]["messages"]
    rendered_text = "\n\n".join(str(message.content) for message in second_call_messages)
    assert "Recent Tool Results" in rendered_text
    assert "call-1" in rendered_text
    assert "read_file" in rendered_text
    assert "tool-result://call-1/content" in rendered_text


def test_stage_agent_retry_with_revised_plan_continues_to_next_iteration() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "retry_with_revised_plan",
                    "reason": "Need a narrower read.",
                    "revised_plan_steps": ["Read the focused file."],
                    "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
                }
            ),
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "CodeGenerationArtifact",
                    "artifact_payload": code_generation_payload(),
                    "evidence_refs": ["stage-process://stage-run-1/model-call/2"],
                }
            ),
        ]
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.COMPLETED
    assert len(runtime.context_builder.requests) == 2


def test_stage_agent_parser_error_fails_without_structured_repair_iteration() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(structured_output={"decision_type": "not-a-decision"}),
        ]
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.FAILED
    assert "structured_output_repair_trace" not in runtime.artifact_store.append_keys()
    assert len(runtime.context_builder.requests) == 1
    assert runtime.artifact_store.process["stage_agent_failed"]["reason"] == (
        "invalid_structured_output"
    )


def test_stage_agent_model_call_trace_omits_prompt_and_response_summaries() -> None:
    result_with_summaries = model_result(
        structured_output=fail_stage_payload(),
        raw_output_text="I cannot continue because the required file is missing.",
    ).model_copy(
        update={
            "usage": ModelCallUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            "trace_summary": ModelCallTraceSummary(
                request_id="request-1",
                trace_id="trace-1",
                correlation_id="correlation-1",
                span_id="span-provider-1",
                parent_span_id="span-iteration-1",
                run_id="run-1",
                stage_run_id="stage-run-1",
                provider_snapshot_id="provider-snapshot-run-1",
                model_binding_snapshot_id="model-binding-snapshot-run-1",
                model_call_type=ModelCallType.STAGE_EXECUTION,
                input_summary={
                    "excerpt": "raw prompt body",
                    "redacted_payload": [{"content": "rendered user task"}],
                    "content_hash": "sha256:input",
                },
                output_summary={
                    "excerpt": "raw response body",
                    "redacted_payload": {"decision": "fail"},
                    "content_hash": "sha256:output",
                },
            ),
        }
    )
    runtime = build_runtime(provider_results=[result_with_summaries])

    runtime.run_stage(invocation())

    model_trace = runtime.artifact_store.process["model_call_trace"]
    assert "trace_summary" not in model_trace
    assert model_trace["trace"] == {
        "request_id": "request-1",
        "trace_id": "trace-1",
        "correlation_id": "correlation-1",
        "span_id": "span-provider-1",
        "parent_span_id": "span-iteration-1",
        "run_id": "run-1",
        "stage_run_id": "stage-run-1",
    }
    assert "raw prompt body" not in str(model_trace)
    assert "raw response body" not in str(model_trace)
    assert "rendered user task" not in str(model_trace)
    assert model_trace["display_summary"] == "Model decided to fail the stage: Cannot continue."
    assert model_trace["raw_output_text"] == (
        "I cannot continue because the required file is missing."
    )
