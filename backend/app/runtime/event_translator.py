from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ControlItemType,
    FeedEntryType,
    StageItemType,
    StageStatus,
    StageType,
)
from backend.app.domain.runtime_refs import GraphInterruptType
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.schemas.feed import ToolConfirmationFeedEntry
from backend.app.schemas.observability import LogCategory, LogLevel, RedactionStatus
from backend.app.services.events import DomainEventType, RAW_GRAPH_EVENT_TYPES


_LOGGER = logging.getLogger(__name__)

_BLOCKED_RAW_KEYS = frozenset(
    {
        "state",
        "values",
        "tasks",
        "checkpoint",
        "checkpoint_payload",
        "compiled_graph",
        "graph_state",
        "raw_state",
        "raw_event",
        "thread",
    }
)


class EventStoreProtocol(Protocol):
    def append(
        self,
        domain_event_type: DomainEventType | str,
        *,
        payload: dict[str, Any],
        trace_context: TraceContext,
        session_id: str | None = None,
        run_id: str | None = None,
        stage_run_id: str | None = None,
    ) -> object: ...


class ArtifactStoreProtocol(Protocol):
    def append_process_record(
        self,
        *,
        artifact_id: str,
        process_key: str,
        process_value: Any,
        trace_context: TraceContext,
    ) -> object: ...


class RunLogWriterProtocol(Protocol):
    def write_run_log(self, record: LogRecordInput) -> object: ...


class _FactsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LangGraphEventTranslationError(RuntimeError):
    """Raised when LangGraph runtime facts cannot be safely translated."""


@dataclass(frozen=True)
class LangGraphEventTranslationResult:
    domain_event_refs: list[str]
    artifact_refs: list[str]
    process_refs: list[str]
    log_summary_refs: list[str]


class LangGraphNodeStartedFacts(_FactsModel):
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    stage_status: StageStatus
    graph_thread_id: str = Field(min_length=1)
    graph_node_key: str = Field(min_length=1)
    stage_artifact_id: str = Field(min_length=1)
    attempt_index: int = Field(ge=1)
    stage_summary: str = Field(min_length=1)
    trace_context: TraceContext
    raw_event: Mapping[str, Any] | None = None


class LangGraphNodeCompletedFacts(_FactsModel):
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    stage_status: StageStatus
    graph_thread_id: str = Field(min_length=1)
    graph_node_key: str = Field(min_length=1)
    stage_artifact_id: str = Field(min_length=1)
    attempt_index: int = Field(ge=1)
    stage_summary: str = Field(min_length=1)
    route_key: str | None = Field(default=None, min_length=1)
    output_artifact_refs: list[str] = Field(default_factory=list)
    prior_domain_event_refs: list[str] = Field(default_factory=list)
    trace_context: TraceContext
    raw_event: Mapping[str, Any] | None = None


class LangGraphInterruptFacts(_FactsModel):
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str = Field(min_length=1)
    stage_type: StageType
    graph_thread_id: str = Field(min_length=1)
    graph_node_key: str = Field(min_length=1)
    stage_artifact_id: str = Field(min_length=1)
    interrupt_id: str = Field(min_length=1)
    interrupt_type: GraphInterruptType
    payload_ref: str = Field(min_length=1)
    trace_context: TraceContext
    raw_event: Mapping[str, Any] | None = None
    clarification_id: str | None = Field(default=None, min_length=1)
    approval_id: str | None = Field(default=None, min_length=1)
    approval_type: ApprovalType | str | None = None
    tool_confirmation_id: str | None = Field(default=None, min_length=1)
    tool_action_ref: str | None = Field(default=None, min_length=1)
    tool_confirmation_payload: Mapping[str, Any] | None = None


class LangGraphEventTranslator:
    def __init__(
        self,
        *,
        event_store: EventStoreProtocol,
        artifact_store: ArtifactStoreProtocol,
        log_writer: RunLogWriterProtocol | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._event_store = event_store
        self._artifact_store = artifact_store
        self._log_writer = log_writer
        self._now = now or (lambda: datetime.now(UTC))

    def translate_node_started(
        self,
        facts: LangGraphNodeStartedFacts,
    ) -> LangGraphEventTranslationResult:
        raw_summary = self._sanitize_raw_event(
            facts.raw_event,
            trace_context=facts.trace_context,
        )
        event = self._event_store.append(
            DomainEventType.STAGE_STARTED,
            payload={"stage_node": self._stage_payload(facts, items=[])},
            trace_context=facts.trace_context,
            session_id=facts.session_id,
            run_id=facts.run_id,
            stage_run_id=facts.stage_run_id,
        )
        event_ref = self._event_id(event)
        process_ref = self.write_stage_artifact(
            artifact_id=facts.stage_artifact_id,
            process_key="langgraph_node_started",
            process_value={
                "event_kind": "node_started",
                "graph_thread_id": facts.graph_thread_id,
                "graph_node_key": facts.graph_node_key,
                "stage_run_id": facts.stage_run_id,
                "stage_type": facts.stage_type.value,
                "status": facts.stage_status.value,
                "attempt_index": facts.attempt_index,
                "domain_event_ref": event_ref,
                "dropped_raw_key_count": raw_summary["dropped_key_count"],
                "retained_raw_scalar_key_count": raw_summary[
                    "retained_scalar_key_count"
                ],
            },
            trace_context=facts.trace_context,
        )
        log_ref = self._record_log(
            "LangGraph node event translated.",
            trace_context=facts.trace_context,
            payload_type="langgraph_event_translation",
            summary={
                "action": "translate_node_started",
                "run_id": facts.run_id,
                "stage_run_id": facts.stage_run_id,
                "stage_type": facts.stage_type.value,
                "graph_thread_id": facts.graph_thread_id,
                "graph_node_key": facts.graph_node_key,
                "artifact_id": facts.stage_artifact_id,
                "process_key": "langgraph_node_started",
                "domain_event_id": event_ref,
                "dropped_raw_key_count": raw_summary["dropped_key_count"],
                "retained_raw_scalar_key_count": raw_summary[
                    "retained_scalar_key_count"
                ],
            },
        )
        return LangGraphEventTranslationResult(
            domain_event_refs=[event_ref],
            artifact_refs=[facts.stage_artifact_id],
            process_refs=[process_ref],
            log_summary_refs=[log_ref] if log_ref is not None else [],
        )

    def translate_node_completed(
        self,
        facts: LangGraphNodeCompletedFacts,
    ) -> LangGraphEventTranslationResult:
        raw_summary = self._sanitize_raw_event(
            facts.raw_event,
            trace_context=facts.trace_context,
        )
        item = {
            "item_id": f"langgraph-node-completed-{facts.stage_run_id}",
            "type": StageItemType.RESULT.value,
            "occurred_at": self._now().isoformat(),
            "title": "Stage node completed",
            "summary": facts.stage_summary,
            "artifact_refs": list(facts.output_artifact_refs),
            "metrics": {
                "prior_domain_event_ref_count": len(facts.prior_domain_event_refs),
            },
        }
        event = self._event_store.append(
            DomainEventType.STAGE_UPDATED,
            payload={"stage_node": self._stage_payload(facts, items=[item])},
            trace_context=facts.trace_context,
            session_id=facts.session_id,
            run_id=facts.run_id,
            stage_run_id=facts.stage_run_id,
        )
        event_ref = self._event_id(event)
        process_ref = self.write_stage_artifact(
            artifact_id=facts.stage_artifact_id,
            process_key="langgraph_node_completed",
            process_value={
                "event_kind": "node_completed",
                "graph_thread_id": facts.graph_thread_id,
                "graph_node_key": facts.graph_node_key,
                "stage_run_id": facts.stage_run_id,
                "stage_type": facts.stage_type.value,
                "status": facts.stage_status.value,
                "attempt_index": facts.attempt_index,
                "route_key": facts.route_key,
                "output_artifact_refs": list(facts.output_artifact_refs),
                "prior_domain_event_refs": list(facts.prior_domain_event_refs),
                "domain_event_ref": event_ref,
                "dropped_raw_key_count": raw_summary["dropped_key_count"],
                "retained_raw_scalar_key_count": raw_summary[
                    "retained_scalar_key_count"
                ],
            },
            trace_context=facts.trace_context,
        )
        log_ref = self._record_log(
            "LangGraph node event translated.",
            trace_context=facts.trace_context,
            payload_type="langgraph_event_translation",
            summary={
                "action": "translate_node_completed",
                "run_id": facts.run_id,
                "stage_run_id": facts.stage_run_id,
                "stage_type": facts.stage_type.value,
                "graph_thread_id": facts.graph_thread_id,
                "graph_node_key": facts.graph_node_key,
                "artifact_id": facts.stage_artifact_id,
                "process_key": "langgraph_node_completed",
                "domain_event_id": event_ref,
                "output_artifact_ref_count": len(facts.output_artifact_refs),
                "prior_domain_event_ref_count": len(facts.prior_domain_event_refs),
                "dropped_raw_key_count": raw_summary["dropped_key_count"],
                "retained_raw_scalar_key_count": raw_summary[
                    "retained_scalar_key_count"
                ],
            },
        )
        return LangGraphEventTranslationResult(
            domain_event_refs=[event_ref],
            artifact_refs=[facts.stage_artifact_id],
            process_refs=[process_ref],
            log_summary_refs=[log_ref] if log_ref is not None else [],
        )

    def translate_interrupt(
        self,
        facts: LangGraphInterruptFacts,
    ) -> LangGraphEventTranslationResult:
        raw_summary = self._sanitize_raw_event(
            facts.raw_event,
            trace_context=facts.trace_context,
        )
        process_key = self._interrupt_process_key(facts.interrupt_id)
        event_payload: dict[str, Any] | None = None
        payload_error: LangGraphEventTranslationError | None = None
        try:
            event_payload = self._interrupt_event_payload(facts)
        except LangGraphEventTranslationError as exc:
            if facts.interrupt_type is not GraphInterruptType.TOOL_CONFIRMATION:
                raise
            payload_error = exc
        event_ref: str | None = None
        if event_payload is not None and payload_error is None:
            event = self._event_store.append(
                self._event_type_for_interrupt(facts.interrupt_type),
                payload=event_payload,
                trace_context=facts.trace_context,
                session_id=facts.session_id,
                run_id=facts.run_id,
                stage_run_id=facts.stage_run_id,
            )
            event_ref = self._event_id(event)
        process_ref = self.write_stage_artifact(
            artifact_id=facts.stage_artifact_id,
            process_key=process_key,
            process_value={
                "event_kind": "interrupt",
                "graph_thread_id": facts.graph_thread_id,
                "graph_node_key": facts.graph_node_key,
                "stage_run_id": facts.stage_run_id,
                "stage_type": facts.stage_type.value,
                "interrupt_id": facts.interrupt_id,
                "interrupt_type": facts.interrupt_type.value,
                "payload_ref": facts.payload_ref,
                "clarification_id": facts.clarification_id,
                "approval_id": facts.approval_id,
                "approval_type": self._resolved_approval_type(facts),
                "tool_confirmation_id": facts.tool_confirmation_id,
                "tool_action_ref": facts.tool_action_ref,
                "domain_event_ref": event_ref,
                "dropped_raw_key_count": raw_summary["dropped_key_count"],
                "retained_raw_scalar_key_count": raw_summary[
                    "retained_scalar_key_count"
                ],
            },
            trace_context=facts.trace_context,
        )
        log_ref = self._record_log(
            "LangGraph interrupt event translated.",
            trace_context=facts.trace_context,
            payload_type="langgraph_event_translation",
            summary={
                "action": "translate_interrupt",
                "run_id": facts.run_id,
                "stage_run_id": facts.stage_run_id,
                "stage_type": facts.stage_type.value,
                "graph_thread_id": facts.graph_thread_id,
                "graph_node_key": facts.graph_node_key,
                "artifact_id": facts.stage_artifact_id,
                "process_key": process_key,
                "domain_event_id": event_ref,
                "interrupt_id": facts.interrupt_id,
                "interrupt_type": facts.interrupt_type.value,
                "payload_ref": facts.payload_ref,
                "dropped_raw_key_count": raw_summary["dropped_key_count"],
                "retained_raw_scalar_key_count": raw_summary[
                    "retained_scalar_key_count"
                ],
            },
        )
        result = LangGraphEventTranslationResult(
            domain_event_refs=[event_ref] if event_ref is not None else [],
            artifact_refs=[facts.stage_artifact_id],
            process_refs=[process_ref],
            log_summary_refs=[log_ref] if log_ref is not None else [],
        )
        if payload_error is not None:
            raise payload_error
        return result

    def write_stage_artifact(
        self,
        *,
        artifact_id: str,
        process_key: str,
        process_value: Mapping[str, Any],
        trace_context: TraceContext,
    ) -> str:
        self._artifact_store.append_process_record(
            artifact_id=artifact_id,
            process_key=process_key,
            process_value=dict(process_value),
            trace_context=trace_context,
        )
        return f"stage-artifact://{artifact_id}#process/{process_key}"

    def _stage_payload(
        self,
        facts: LangGraphNodeStartedFacts | LangGraphNodeCompletedFacts,
        *,
        items: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return {
            "entry_id": f"stage-node-{facts.stage_run_id}",
            "run_id": facts.run_id,
            "type": FeedEntryType.STAGE_NODE.value,
            "occurred_at": self._now().isoformat(),
            "stage_run_id": facts.stage_run_id,
            "stage_type": facts.stage_type.value,
            "status": facts.stage_status.value,
            "attempt_index": facts.attempt_index,
            "started_at": facts.trace_context.created_at.isoformat(),
            "ended_at": self._now().isoformat()
            if facts.stage_status
            in {StageStatus.COMPLETED, StageStatus.FAILED, StageStatus.TERMINATED}
            else None,
            "summary": facts.stage_summary,
            "items": [dict(item) for item in items],
            "metrics": {"graph_event_translated": True},
        }

    def _interrupt_event_payload(self, facts: LangGraphInterruptFacts) -> dict[str, Any] | None:
        if facts.interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
            if facts.clarification_id is None:
                raise LangGraphEventTranslationError(
                    "clarification interrupt requires clarification_id"
                )
            return {
                "run_id": facts.run_id,
                "stage_run_id": facts.stage_run_id,
                "control_item": {
                    "entry_id": f"control-{facts.clarification_id}",
                    "run_id": facts.run_id,
                    "type": FeedEntryType.CONTROL_ITEM.value,
                    "occurred_at": self._now().isoformat(),
                    "control_record_id": facts.clarification_id,
                    "control_type": ControlItemType.CLARIFICATION_WAIT.value,
                    "source_stage_type": facts.stage_type.value,
                    "target_stage_type": None,
                    "title": "Clarification requested",
                    "summary": "The stage is waiting for missing requirement information.",
                    "payload_ref": facts.payload_ref,
                },
            }
        if facts.interrupt_type is GraphInterruptType.APPROVAL:
            if facts.approval_id is None:
                raise LangGraphEventTranslationError(
                    "approval interrupt requires approval_id"
                )
            return {
                "approval_request": {
                    "entry_id": f"approval-{facts.approval_id}",
                    "run_id": facts.run_id,
                    "type": FeedEntryType.APPROVAL_REQUEST.value,
                    "occurred_at": self._now().isoformat(),
                    "approval_id": facts.approval_id,
                    "approval_type": self._resolved_approval_type(facts),
                    "status": ApprovalStatus.PENDING.value,
                    "title": "Approval requested",
                    "approval_object_excerpt": (
                        "Approval payload is available through the stable payload reference."
                    ),
                    "risk_excerpt": None,
                    "approval_object_preview": {"payload_ref": facts.payload_ref},
                    "approve_action": "approve",
                    "reject_action": "reject",
                    "is_actionable": True,
                    "requested_at": self._now().isoformat(),
                    "delivery_readiness_status": None,
                    "delivery_readiness_message": None,
                    "open_settings_action": None,
                    "disabled_reason": None,
                },
            }
        if facts.interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
            if facts.tool_confirmation_id is None:
                raise LangGraphEventTranslationError(
                    "tool confirmation interrupt requires tool_confirmation_id"
                )
            if facts.tool_confirmation_payload is None:
                return None
            try:
                payload = ToolConfirmationFeedEntry.model_validate(
                    facts.tool_confirmation_payload
                ).model_dump(mode="json")
            except Exception as exc:
                raise LangGraphEventTranslationError(
                    "tool confirmation payload failed validation"
                ) from exc
            self._validate_tool_confirmation_payload_identity(facts, payload)
            return {"tool_confirmation": payload}
        raise LangGraphEventTranslationError(
            f"unsupported interrupt type: {facts.interrupt_type}"
        )

    def _event_type_for_interrupt(
        self,
        interrupt_type: GraphInterruptType,
    ) -> DomainEventType:
        if interrupt_type is GraphInterruptType.CLARIFICATION_REQUEST:
            return DomainEventType.CLARIFICATION_REQUESTED
        if interrupt_type is GraphInterruptType.APPROVAL:
            return DomainEventType.APPROVAL_REQUESTED
        if interrupt_type is GraphInterruptType.TOOL_CONFIRMATION:
            return DomainEventType.TOOL_CONFIRMATION_REQUESTED
        raise LangGraphEventTranslationError(
            f"unsupported interrupt type: {interrupt_type}"
        )

    def _sanitize_raw_event(
        self,
        raw_event: Mapping[str, Any] | None,
        *,
        trace_context: TraceContext,
    ) -> dict[str, Any]:
        if raw_event is None:
            return {
                "dropped_key_count": 0,
                "retained_scalar_key_count": 0,
            }

        raw_type_fact = next(
            (
                (key, value)
                for key in ("event_type", "event")
                if isinstance(value := raw_event.get(key), str)
                and value in RAW_GRAPH_EVENT_TYPES
            ),
            None,
        )
        if raw_type_fact is not None:
            raw_field, raw_type = raw_type_fact
            self._record_log(
                "LangGraph raw event translation rejected.",
                trace_context=trace_context,
                payload_type="langgraph_event_translation",
                summary={
                    "action": "translation_rejected",
                    "blocked_event_field": raw_field,
                    "blocked_reason": "raw LangGraph event type",
                },
                level=LogLevel.ERROR,
            )
            raise LangGraphEventTranslationError(
                "raw LangGraph event cannot be externalized"
            )

        dropped_keys = sorted(key for key in raw_event if key.lower() in _BLOCKED_RAW_KEYS)
        retained_scalar_key_count = sum(
            1
            for key, value in raw_event.items()
            if key.lower() not in _BLOCKED_RAW_KEYS and _is_safe_scalar(value)
        )
        return {
            "dropped_key_count": len(dropped_keys),
            "retained_scalar_key_count": retained_scalar_key_count,
        }

    def _interrupt_process_key(self, interrupt_id: str) -> str:
        return f"langgraph_interrupt:{interrupt_id}"

    def _validate_tool_confirmation_payload_identity(
        self,
        facts: LangGraphInterruptFacts,
        payload: Mapping[str, Any],
    ) -> None:
        expected = {
            "run_id": facts.run_id,
            "stage_run_id": facts.stage_run_id,
            "tool_confirmation_id": facts.tool_confirmation_id,
        }
        for field_name, expected_value in expected.items():
            if payload.get(field_name) != expected_value:
                raise LangGraphEventTranslationError(
                    f"tool confirmation payload identity mismatch: {field_name}"
                )

    def _resolved_approval_type(self, facts: LangGraphInterruptFacts) -> str | None:
        if facts.interrupt_type is not GraphInterruptType.APPROVAL:
            return None
        if facts.approval_type is not None:
            return (
                facts.approval_type.value
                if isinstance(facts.approval_type, ApprovalType)
                else facts.approval_type
            )
        if facts.stage_type is StageType.CODE_REVIEW:
            return ApprovalType.CODE_REVIEW_APPROVAL.value
        return ApprovalType.SOLUTION_DESIGN_APPROVAL.value

    @staticmethod
    def _event_id(event: object) -> str:
        event_id = getattr(event, "event_id", None)
        if not isinstance(event_id, str) or not event_id:
            raise LangGraphEventTranslationError(
                "EventStore returned no stable event_id"
            )
        return event_id

    def _record_log(
        self,
        message: str,
        *,
        trace_context: TraceContext,
        payload_type: str,
        summary: Mapping[str, object],
        level: LogLevel = LogLevel.INFO,
    ) -> str | None:
        if self._log_writer is None:
            return None
        payload = LogPayloadSummary(
            payload_type=payload_type,
            summary=dict(summary),
            excerpt=None,
            payload_size_bytes=0,
            content_hash="",
            redaction_status=RedactionStatus.NOT_REQUIRED,
        )
        try:
            record = self._log_writer.write_run_log(
                LogRecordInput(
                    source="runtime.langgraph.event_translator",
                    category=LogCategory.RUNTIME,
                    level=level,
                    message=message,
                    trace_context=trace_context,
                    payload=payload,
                    created_at=self._now(),
                )
            )
        except Exception:
            _LOGGER.exception("LangGraph event translation log write failed")
            return None
        log_id = getattr(record, "log_id", None)
        return log_id if isinstance(log_id, str) and log_id else None


def _is_safe_scalar(value: object) -> bool:
    return isinstance(value, str | int | float | bool | type(None))


__all__ = [
    "LangGraphEventTranslationError",
    "LangGraphEventTranslationResult",
    "LangGraphEventTranslator",
    "LangGraphInterruptFacts",
    "LangGraphNodeCompletedFacts",
    "LangGraphNodeStartedFacts",
]
