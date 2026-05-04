from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.runtime_refs import GraphInterruptType
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogRecordInput
from backend.app.schemas.events import SessionEvent
from backend.app.schemas.observability import LogLevel
from backend.app.services.events import DomainEventType, resolve_sse_event_type


NOW = datetime(2026, 5, 4, 11, 30, 0, tzinfo=UTC)


class CapturingEventStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def append(self, domain_event_type: DomainEventType | str, **kwargs: Any) -> object:
        self.calls.append({"domain_event_type": domain_event_type, **kwargs})
        return SimpleNamespace(event_id=f"event-{len(self.calls)}")


class ValidatingEventStore(CapturingEventStore):
    def append(self, domain_event_type: DomainEventType | str, **kwargs: Any) -> object:
        SessionEvent(
            event_id=f"event-{len(self.calls) + 1}",
            session_id=kwargs["session_id"],
            run_id=kwargs["run_id"],
            event_type=resolve_sse_event_type(domain_event_type),
            occurred_at=NOW,
            payload=kwargs["payload"],
        )
        return super().append(domain_event_type, **kwargs)


class CapturingArtifactStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def append_process_record(self, **kwargs: Any) -> object:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(artifact_id=kwargs["artifact_id"])


class CapturingRunLogWriter:
    def __init__(self) -> None:
        self.records: list[LogRecordInput] = []

    def write_run_log(self, record: LogRecordInput) -> object:
        self.records.append(record)
        return SimpleNamespace(log_id=f"log-{len(self.records)}")


class FailingRunLogWriter:
    def write_run_log(self, record: LogRecordInput) -> object:
        raise RuntimeError("log sink unavailable")


def build_trace(**overrides: Any) -> TraceContext:
    values = {
        "request_id": "request-a47",
        "trace_id": "trace-a47",
        "correlation_id": "correlation-a47",
        "span_id": "span-root",
        "parent_span_id": None,
        "session_id": "session-1",
        "run_id": "run-1",
        "stage_run_id": "stage-run-1",
        "graph_thread_id": "graph-thread-1",
        "created_at": NOW,
    }
    values.update(overrides)
    return TraceContext(**values)


def test_node_started_translation_writes_domain_event_artifact_record_and_sanitized_log() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphNodeStartedFacts,
    )

    events = CapturingEventStore()
    artifacts = CapturingArtifactStore()
    logs = CapturingRunLogWriter()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=logs,
        now=lambda: NOW,
    )

    result = translator.translate_node_started(
        LangGraphNodeStartedFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            stage_status=StageStatus.RUNNING,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            attempt_index=1,
            stage_summary="Solution design started.",
            trace_context=build_trace(),
            raw_event={
                "event": "on_chain_start",
                "state": {"private": "blocked"},
                "sequence": 7,
            },
        )
    )

    assert result.domain_event_refs == ["event-1"]
    assert result.artifact_refs == ["artifact-stage-1"]
    assert result.log_summary_refs == ["log-1"]
    assert events.calls[0]["domain_event_type"] is DomainEventType.STAGE_STARTED
    assert events.calls[0]["payload"]["stage_node"]["stage_run_id"] == "stage-run-1"
    assert "raw_event" not in str(events.calls[0]["payload"]).lower()
    assert "private" not in str(events.calls[0]["payload"])
    assert artifacts.calls[0]["process_key"] == "langgraph_node_started"
    assert artifacts.calls[0]["process_value"]["graph_node_key"] == "solution_design"
    assert "raw_event_ref" not in artifacts.calls[0]["process_value"]
    assert "langgraph-event://" not in str(artifacts.calls[0]["process_value"])
    assert "raw_event_excerpt" not in artifacts.calls[0]["process_value"]
    assert "on_chain_start" not in str(artifacts.calls[0]["process_value"])
    assert "sequence" not in str(artifacts.calls[0]["process_value"])
    assert artifacts.calls[0]["process_value"]["dropped_raw_key_count"] == 1
    assert artifacts.calls[0]["process_value"]["retained_raw_scalar_key_count"] == 2
    assert "state" not in str(artifacts.calls[0]["process_value"])
    assert "private" not in str(artifacts.calls[0]["process_value"])
    assert logs.records[0].payload.summary["action"] == "translate_node_started"
    assert logs.records[0].payload.summary["dropped_raw_key_count"] == 1
    assert "state" not in str(logs.records[0].payload.summary)
    assert "raw_event" not in str(logs.records[0].payload.summary).lower()
    assert "on_chain_start" not in str(logs.records[0].payload.summary)
    assert "sequence" not in str(logs.records[0].payload.summary)
    assert "private" not in str(logs.records[0].payload.summary)


def test_node_completed_translation_writes_stage_updated_and_process_record() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphNodeCompletedFacts,
    )

    events = CapturingEventStore()
    artifacts = CapturingArtifactStore()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=CapturingRunLogWriter(),
        now=lambda: NOW,
    )

    result = translator.translate_node_completed(
        LangGraphNodeCompletedFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            stage_status=StageStatus.COMPLETED,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            attempt_index=1,
            stage_summary="Solution design completed.",
            route_key="approved",
            output_artifact_refs=["artifact-stage-1"],
            prior_domain_event_refs=["event-upstream-1"],
            trace_context=build_trace(),
            raw_event={"event": "on_chain_end", "checkpoint_payload": {"secret": "blocked"}},
        )
    )

    assert result.domain_event_refs == ["event-1"]
    assert events.calls[0]["domain_event_type"] is DomainEventType.STAGE_UPDATED
    assert events.calls[0]["payload"]["stage_node"]["status"] == StageStatus.COMPLETED.value
    assert events.calls[0]["payload"]["stage_node"]["ended_at"] == NOW.isoformat()
    assert artifacts.calls[0]["process_key"] == "langgraph_node_completed"
    assert artifacts.calls[0]["process_value"]["route_key"] == "approved"
    assert artifacts.calls[0]["process_value"]["output_artifact_refs"] == ["artifact-stage-1"]
    assert artifacts.calls[0]["process_value"]["prior_domain_event_refs"] == [
        "event-upstream-1"
    ]
    assert "checkpoint_payload" not in str(artifacts.calls[0]["process_value"])
    assert "secret" not in str(artifacts.calls[0]["process_value"])


@pytest.mark.parametrize(
    ("interrupt_type", "expected_event_type", "required_ref_field", "required_ref_value"),
    [
        (
            GraphInterruptType.CLARIFICATION_REQUEST,
            DomainEventType.CLARIFICATION_REQUESTED,
            "clarification_id",
            "clarification-1",
        ),
        (
            GraphInterruptType.APPROVAL,
            DomainEventType.APPROVAL_REQUESTED,
            "approval_id",
            "approval-1",
        ),
    ],
)
def test_interrupt_translation_maps_to_domain_event_and_stable_process_record(
    interrupt_type: GraphInterruptType,
    expected_event_type: DomainEventType,
    required_ref_field: str,
    required_ref_value: str,
) -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
    )

    events = CapturingEventStore()
    artifacts = CapturingArtifactStore()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=CapturingRunLogWriter(),
        now=lambda: NOW,
    )
    values = {
        "session_id": "session-1",
        "run_id": "run-1",
        "stage_run_id": "stage-run-1",
        "stage_type": StageType.SOLUTION_DESIGN,
        "graph_thread_id": "graph-thread-1",
        "graph_node_key": "solution_design",
        "stage_artifact_id": "artifact-stage-1",
        "interrupt_id": f"interrupt-{required_ref_value}",
        "interrupt_type": interrupt_type,
        "payload_ref": f"payload-{required_ref_value}",
        required_ref_field: required_ref_value,
        "trace_context": build_trace(),
        "raw_event": {"event": "__interrupt__", "compiled_graph": {"private": "blocked"}},
    }

    result = translator.translate_interrupt(LangGraphInterruptFacts(**values))

    assert result.domain_event_refs == ["event-1"]
    assert events.calls[0]["domain_event_type"] is expected_event_type
    assert artifacts.calls[0]["process_key"] == f"langgraph_interrupt:interrupt-{required_ref_value}"
    assert artifacts.calls[0]["process_value"][required_ref_field] == required_ref_value
    assert artifacts.calls[0]["process_value"]["payload_ref"] == f"payload-{required_ref_value}"
    assert "compiled_graph" not in str(events.calls[0]["payload"])
    assert "private" not in str(events.calls[0]["payload"])
    assert "compiled_graph" not in str(artifacts.calls[0]["process_value"])
    assert "private" not in str(artifacts.calls[0]["process_value"])


def valid_tool_confirmation_payload(
    *,
    tool_confirmation_id: str = "tool-confirmation-1",
    stage_run_id: str = "stage-run-1",
) -> dict[str, Any]:
    return {
        "entry_id": f"tool-confirmation-entry-{tool_confirmation_id}",
        "run_id": "run-1",
        "type": "tool_confirmation",
        "occurred_at": NOW.isoformat(),
        "stage_run_id": stage_run_id,
        "tool_confirmation_id": tool_confirmation_id,
        "status": "pending",
        "title": "Review workspace command",
        "tool_name": "workspace.apply_patch",
        "command_preview": "Apply patch to backend/app/runtime/event_translator.py",
        "target_summary": "backend/app/runtime/event_translator.py",
        "risk_level": "high_risk",
        "risk_categories": ["broad_write"],
        "reason": "The patch modifies runtime translation behavior.",
        "expected_side_effects": ["Update event translation source code."],
        "allow_action": f"allow:{tool_confirmation_id}",
        "deny_action": f"deny:{tool_confirmation_id}",
        "is_actionable": True,
        "requested_at": NOW.isoformat(),
        "responded_at": None,
        "decision": None,
        "deny_followup_action": None,
        "deny_followup_summary": None,
        "disabled_reason": None,
    }


def test_tool_confirmation_interrupt_without_product_payload_writes_process_and_log_only() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
    )

    events = CapturingEventStore()
    artifacts = CapturingArtifactStore()
    logs = CapturingRunLogWriter()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=logs,
        now=lambda: NOW,
    )

    result = translator.translate_interrupt(
        LangGraphInterruptFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            interrupt_id="interrupt-tool-confirmation-1",
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            payload_ref="payload-tool-confirmation-1",
            tool_confirmation_id="tool-confirmation-1",
            tool_action_ref="tool-action-1",
            trace_context=build_trace(),
            raw_event={"event": "__interrupt__", "safe_key": "safe-value"},
        )
    )

    assert result.domain_event_refs == []
    assert result.artifact_refs == ["artifact-stage-1"]
    assert result.log_summary_refs == ["log-1"]
    assert events.calls == []
    assert artifacts.calls[0]["process_key"] == (
        "langgraph_interrupt:interrupt-tool-confirmation-1"
    )
    assert artifacts.calls[0]["process_value"]["tool_confirmation_id"] == (
        "tool-confirmation-1"
    )
    assert artifacts.calls[0]["process_value"]["tool_action_ref"] == "tool-action-1"
    assert artifacts.calls[0]["process_value"]["domain_event_ref"] is None
    assert logs.records[0].payload.summary["action"] == "translate_interrupt"
    assert logs.records[0].payload.summary["domain_event_id"] is None


def test_tool_confirmation_interrupt_with_explicit_product_payload_emits_valid_event() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
    )

    events = ValidatingEventStore()
    artifacts = CapturingArtifactStore()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=CapturingRunLogWriter(),
        now=lambda: NOW,
    )

    result = translator.translate_interrupt(
        LangGraphInterruptFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            interrupt_id="interrupt-tool-confirmation-1",
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            payload_ref="payload-tool-confirmation-1",
            tool_confirmation_id="tool-confirmation-1",
            tool_action_ref="tool-action-1",
            tool_confirmation_payload=valid_tool_confirmation_payload(),
            trace_context=build_trace(),
            raw_event={"event": "__interrupt__", "safe_key": "safe-value"},
        )
    )

    assert result.domain_event_refs == ["event-1"]
    assert events.calls[0]["domain_event_type"] is DomainEventType.TOOL_CONFIRMATION_REQUESTED
    assert events.calls[0]["payload"]["tool_confirmation"]["tool_name"] == (
        "workspace.apply_patch"
    )
    assert events.calls[0]["payload"]["tool_confirmation"]["risk_categories"] == [
        "broad_write"
    ]
    assert artifacts.calls[0]["process_value"]["domain_event_ref"] == "event-1"


def test_multiple_interrupts_on_same_artifact_use_distinct_process_keys_and_refs() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
    )

    artifacts = CapturingArtifactStore()
    translator = LangGraphEventTranslator(
        event_store=CapturingEventStore(),
        artifact_store=artifacts,
        log_writer=CapturingRunLogWriter(),
        now=lambda: NOW,
    )

    first = translator.translate_interrupt(
        LangGraphInterruptFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            interrupt_id="interrupt-clarification-1",
            interrupt_type=GraphInterruptType.CLARIFICATION_REQUEST,
            payload_ref="payload-clarification-1",
            clarification_id="clarification-1",
            trace_context=build_trace(),
        )
    )
    second = translator.translate_interrupt(
        LangGraphInterruptFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            interrupt_id="interrupt-approval-1",
            interrupt_type=GraphInterruptType.APPROVAL,
            payload_ref="payload-approval-1",
            approval_id="approval-1",
            trace_context=build_trace(),
        )
    )

    assert [call["process_key"] for call in artifacts.calls] == [
        "langgraph_interrupt:interrupt-clarification-1",
        "langgraph_interrupt:interrupt-approval-1",
    ]
    assert first.process_refs == [
        "stage-artifact://artifact-stage-1#process/langgraph_interrupt:interrupt-clarification-1"
    ]
    assert second.process_refs == [
        "stage-artifact://artifact-stage-1#process/langgraph_interrupt:interrupt-approval-1"
    ]
    assert artifacts.calls[0]["process_value"]["interrupt_id"] == "interrupt-clarification-1"
    assert artifacts.calls[1]["process_value"]["interrupt_id"] == "interrupt-approval-1"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("run_id", "other-run"),
        ("tool_confirmation_id", "other-tool-confirmation"),
        ("stage_run_id", "other-stage-run"),
    ],
)
def test_tool_confirmation_payload_identity_mismatch_writes_process_and_log_before_error(
    field: str,
    bad_value: str,
) -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslationError,
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
    )

    events = CapturingEventStore()
    artifacts = CapturingArtifactStore()
    logs = CapturingRunLogWriter()
    payload = valid_tool_confirmation_payload()
    payload[field] = bad_value
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=logs,
        now=lambda: NOW,
    )

    with pytest.raises(LangGraphEventTranslationError, match="identity"):
        translator.translate_interrupt(
            LangGraphInterruptFacts(
                session_id="session-1",
                run_id="run-1",
                stage_run_id="stage-run-1",
                stage_type=StageType.SOLUTION_DESIGN,
                graph_thread_id="graph-thread-1",
                graph_node_key="solution_design",
                stage_artifact_id="artifact-stage-1",
                interrupt_id="interrupt-tool-confirmation-1",
                interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
                payload_ref="payload-tool-confirmation-1",
                tool_confirmation_id="tool-confirmation-1",
                tool_action_ref="tool-action-1",
                tool_confirmation_payload=payload,
                trace_context=build_trace(),
            )
        )

    assert events.calls == []
    assert len(artifacts.calls) == 1
    assert artifacts.calls[0]["process_key"] == (
        "langgraph_interrupt:interrupt-tool-confirmation-1"
    )
    assert artifacts.calls[0]["process_value"]["domain_event_ref"] is None
    assert len(logs.records) == 1
    assert logs.records[0].payload.summary["domain_event_id"] is None
    assert bad_value not in str(artifacts.calls[0]["process_value"])
    assert bad_value not in str(logs.records[0].payload.summary)


def test_invalid_tool_confirmation_payload_writes_process_and_log_before_error() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslationError,
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
    )

    events = CapturingEventStore()
    artifacts = CapturingArtifactStore()
    logs = CapturingRunLogWriter()
    invalid_payload = valid_tool_confirmation_payload()
    invalid_payload.pop("tool_name")
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=logs,
        now=lambda: NOW,
    )

    with pytest.raises(LangGraphEventTranslationError, match="tool confirmation payload"):
        translator.translate_interrupt(
            LangGraphInterruptFacts(
                session_id="session-1",
                run_id="run-1",
                stage_run_id="stage-run-1",
                stage_type=StageType.SOLUTION_DESIGN,
                graph_thread_id="graph-thread-1",
                graph_node_key="solution_design",
                stage_artifact_id="artifact-stage-1",
                interrupt_id="interrupt-tool-confirmation-1",
                interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
                payload_ref="payload-tool-confirmation-1",
                tool_confirmation_id="tool-confirmation-1",
                tool_action_ref="tool-action-1",
                tool_confirmation_payload=invalid_payload,
                trace_context=build_trace(),
                raw_event={"event": "__interrupt__", "safe_key": "safe-value"},
            )
        )

    assert events.calls == []
    assert len(artifacts.calls) == 1
    assert artifacts.calls[0]["process_key"] == (
        "langgraph_interrupt:interrupt-tool-confirmation-1"
    )
    assert artifacts.calls[0]["process_value"]["domain_event_ref"] is None
    assert artifacts.calls[0]["process_value"]["tool_confirmation_id"] == (
        "tool-confirmation-1"
    )
    assert len(logs.records) == 1
    assert logs.records[0].payload.summary["action"] == "translate_interrupt"
    assert logs.records[0].payload.summary["domain_event_id"] is None
    assert "workspace.apply_patch" not in str(artifacts.calls[0]["process_value"])
    assert "workspace.apply_patch" not in str(logs.records[0].payload.summary)


def test_approval_interrupt_derives_solution_and_code_review_approval_types() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
    )

    events = CapturingEventStore()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=CapturingArtifactStore(),
        log_writer=CapturingRunLogWriter(),
        now=lambda: NOW,
    )

    translator.translate_interrupt(
        LangGraphInterruptFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            interrupt_id="interrupt-approval-1",
            interrupt_type=GraphInterruptType.APPROVAL,
            payload_ref="payload-approval-1",
            approval_id="approval-1",
            trace_context=build_trace(),
        )
    )
    translator.translate_interrupt(
        LangGraphInterruptFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-2",
            stage_type=StageType.CODE_REVIEW,
            graph_thread_id="graph-thread-1",
            graph_node_key="code_review",
            stage_artifact_id="artifact-stage-2",
            interrupt_id="interrupt-approval-2",
            interrupt_type=GraphInterruptType.APPROVAL,
            payload_ref="payload-approval-2",
            approval_id="approval-2",
            trace_context=build_trace(stage_run_id="stage-run-2"),
        )
    )

    assert (
        events.calls[0]["payload"]["approval_request"]["approval_type"]
        == "solution_design_approval"
    )
    assert (
        events.calls[1]["payload"]["approval_request"]["approval_type"]
        == "code_review_approval"
    )


def test_approval_interrupt_uses_explicit_approval_type() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
    )

    events = CapturingEventStore()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=CapturingArtifactStore(),
        log_writer=CapturingRunLogWriter(),
        now=lambda: NOW,
    )

    translator.translate_interrupt(
        LangGraphInterruptFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.CODE_REVIEW,
            graph_thread_id="graph-thread-1",
            graph_node_key="code_review",
            stage_artifact_id="artifact-stage-1",
            interrupt_id="interrupt-approval-1",
            interrupt_type=GraphInterruptType.APPROVAL,
            payload_ref="payload-approval-1",
            approval_id="approval-1",
            approval_type="solution_design_approval",
            trace_context=build_trace(),
        )
    )

    assert (
        events.calls[0]["payload"]["approval_request"]["approval_type"]
        == "solution_design_approval"
    )


@pytest.mark.parametrize(
    "raw_event",
    [
        {"event_type": "GraphNodeStarted", "state": {"secret": "blocked"}},
        {"event": "GraphFailed", "values": {"secret": "blocked"}},
    ],
)
def test_translation_rejects_raw_graph_domain_event_names_before_product_writes(
    raw_event: dict[str, Any],
) -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslationError,
        LangGraphEventTranslator,
        LangGraphNodeStartedFacts,
    )

    events = CapturingEventStore()
    artifacts = CapturingArtifactStore()
    logs = CapturingRunLogWriter()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=logs,
        now=lambda: NOW,
    )

    with pytest.raises(LangGraphEventTranslationError, match="raw LangGraph event"):
        translator.translate_node_started(
            LangGraphNodeStartedFacts(
                session_id="session-1",
                run_id="run-1",
                stage_run_id="stage-run-1",
                stage_type=StageType.SOLUTION_DESIGN,
                stage_status=StageStatus.RUNNING,
                graph_thread_id="graph-thread-1",
                graph_node_key="solution_design",
                stage_artifact_id="artifact-stage-1",
                attempt_index=1,
                stage_summary="Solution design started.",
                trace_context=build_trace(),
                raw_event=raw_event,
            )
        )

    assert events.calls == []
    assert artifacts.calls == []
    assert logs.records[0].payload.summary["action"] == "translation_rejected"
    assert "blocked_event_type" not in logs.records[0].payload.summary
    assert logs.records[0].payload.summary["blocked_event_field"] in {"event", "event_type"}
    assert logs.records[0].level is LogLevel.ERROR
    assert "GraphNodeStarted" not in str(logs.records[0].payload.summary)
    assert "GraphFailed" not in str(logs.records[0].payload.summary)
    assert "state" not in str(logs.records[0].payload.summary)
    assert "values" not in str(logs.records[0].payload.summary)
    assert "secret" not in str(logs.records[0].payload.summary)


def test_translation_drops_all_blocked_raw_payload_keys_from_product_records_and_logs() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphNodeCompletedFacts,
    )

    artifacts = CapturingArtifactStore()
    logs = CapturingRunLogWriter()
    translator = LangGraphEventTranslator(
        event_store=CapturingEventStore(),
        artifact_store=artifacts,
        log_writer=logs,
        now=lambda: NOW,
    )

    translator.translate_node_completed(
        LangGraphNodeCompletedFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            stage_status=StageStatus.COMPLETED,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            attempt_index=1,
            stage_summary="Solution design completed.",
            route_key="approved",
            output_artifact_refs=["artifact-stage-1"],
            prior_domain_event_refs=[],
            trace_context=build_trace(),
            raw_event={
                "state": {"secret": "blocked"},
                "values": {"secret": "blocked"},
                "tasks": ["blocked"],
                "checkpoint": {"secret": "blocked"},
                "checkpoint_payload": {"secret": "blocked"},
                "compiled_graph": {"secret": "blocked"},
                "graph_state": {"secret": "blocked"},
                "raw_state": {"secret": "blocked"},
                "raw_event": {"secret": "blocked"},
                "thread": {"secret": "blocked"},
                "safe_key": "safe-value",
            },
        )
    )

    process_value = artifacts.calls[0]["process_value"]
    assert "raw_event_excerpt" not in process_value
    assert "raw_event_ref" not in process_value
    assert "langgraph-event://" not in str(process_value)
    assert "safe_key" not in str(process_value)
    assert "safe-value" not in str(process_value)
    assert process_value["dropped_raw_key_count"] == 10
    assert process_value["retained_raw_scalar_key_count"] == 1
    assert not {
        "checkpoint",
        "checkpoint_payload",
        "compiled_graph",
        "graph_state",
        "raw_event",
        "raw_state",
        "state",
        "tasks",
        "thread",
        "values",
    }.intersection(process_value)
    assert "checkpoint_payload" not in str(process_value)
    assert "compiled_graph" not in str(process_value)
    assert "raw_state" not in str(process_value)
    assert "checkpoint_payload" not in str(logs.records[0].payload.summary)
    assert "compiled_graph" not in str(logs.records[0].payload.summary)
    assert "raw_state" not in str(logs.records[0].payload.summary)
    assert "safe_key" not in str(logs.records[0].payload.summary)
    assert "safe-value" not in str(logs.records[0].payload.summary)
    assert "secret" not in str(process_value)
    assert "secret" not in str(logs.records[0].payload.summary)


def test_translator_generated_payloads_satisfy_real_session_event_contracts() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphInterruptFacts,
        LangGraphNodeCompletedFacts,
        LangGraphNodeStartedFacts,
    )

    events = ValidatingEventStore()
    artifacts = CapturingArtifactStore()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=CapturingRunLogWriter(),
        now=lambda: NOW,
    )

    translator.translate_node_started(
        LangGraphNodeStartedFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-started",
            stage_type=StageType.SOLUTION_DESIGN,
            stage_status=StageStatus.RUNNING,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-started",
            attempt_index=1,
            stage_summary="Solution design started.",
            trace_context=build_trace(stage_run_id="stage-run-started"),
            raw_event={"event": "on_chain_start", "safe_key": "safe-value"},
        )
    )
    translator.translate_node_completed(
        LangGraphNodeCompletedFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-completed",
            stage_type=StageType.SOLUTION_DESIGN,
            stage_status=StageStatus.COMPLETED,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-completed",
            attempt_index=1,
            stage_summary="Solution design completed.",
            route_key="approved",
            output_artifact_refs=["artifact-stage-completed"],
            prior_domain_event_refs=["event-upstream-1"],
            trace_context=build_trace(stage_run_id="stage-run-completed"),
            raw_event={"event": "on_chain_end", "safe_key": "safe-value"},
        )
    )

    for interrupt_type, ref_field, ref_value in (
        (GraphInterruptType.CLARIFICATION_REQUEST, "clarification_id", "clarification-1"),
        (GraphInterruptType.APPROVAL, "approval_id", "approval-1"),
    ):
        translator.translate_interrupt(
            LangGraphInterruptFacts(
                session_id="session-1",
                run_id="run-1",
                stage_run_id=f"stage-run-{ref_value}",
                stage_type=StageType.SOLUTION_DESIGN,
                graph_thread_id="graph-thread-1",
                graph_node_key="solution_design",
                stage_artifact_id=f"artifact-{ref_value}",
                interrupt_id=f"interrupt-{ref_value}",
                interrupt_type=interrupt_type,
                payload_ref=f"payload-{ref_value}",
                trace_context=build_trace(stage_run_id=f"stage-run-{ref_value}"),
                raw_event={"event": "__interrupt__", "safe_key": "safe-value"},
                **{ref_field: ref_value},
            )
        )
    translator.translate_interrupt(
        LangGraphInterruptFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-tool-confirmation-1",
            stage_type=StageType.SOLUTION_DESIGN,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-tool-confirmation-1",
            interrupt_id="interrupt-tool-confirmation-1",
            interrupt_type=GraphInterruptType.TOOL_CONFIRMATION,
            payload_ref="payload-tool-confirmation-1",
            tool_confirmation_id="tool-confirmation-1",
            tool_action_ref="tool-action-1",
            tool_confirmation_payload=valid_tool_confirmation_payload(
                stage_run_id="stage-run-tool-confirmation-1"
            ),
            trace_context=build_trace(stage_run_id="stage-run-tool-confirmation-1"),
            raw_event={"event": "__interrupt__", "safe_key": "safe-value"},
        )
    )

    assert [call["domain_event_type"] for call in events.calls] == [
        DomainEventType.STAGE_STARTED,
        DomainEventType.STAGE_UPDATED,
        DomainEventType.CLARIFICATION_REQUESTED,
        DomainEventType.APPROVAL_REQUESTED,
        DomainEventType.TOOL_CONFIRMATION_REQUESTED,
    ]
    for call in artifacts.calls:
        assert "raw_event_excerpt" not in call["process_value"]
        assert "raw_event_ref" not in call["process_value"]
        assert "langgraph-event://" not in str(call["process_value"])
        assert "safe_key" not in str(call["process_value"])
        assert "safe-value" not in str(call["process_value"])


def test_log_writer_failure_does_not_mask_product_writes() -> None:
    from backend.app.runtime.event_translator import (
        LangGraphEventTranslator,
        LangGraphNodeStartedFacts,
    )

    events = CapturingEventStore()
    artifacts = CapturingArtifactStore()
    translator = LangGraphEventTranslator(
        event_store=events,
        artifact_store=artifacts,
        log_writer=FailingRunLogWriter(),
        now=lambda: NOW,
    )

    result = translator.translate_node_started(
        LangGraphNodeStartedFacts(
            session_id="session-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            stage_type=StageType.SOLUTION_DESIGN,
            stage_status=StageStatus.RUNNING,
            graph_thread_id="graph-thread-1",
            graph_node_key="solution_design",
            stage_artifact_id="artifact-stage-1",
            attempt_index=1,
            stage_summary="Solution design started.",
            trace_context=build_trace(),
        )
    )

    assert result.domain_event_refs == ["event-1"]
    assert result.artifact_refs == ["artifact-stage-1"]
    assert result.log_summary_refs == []
    assert len(events.calls) == 1
    assert len(artifacts.calls) == 1
