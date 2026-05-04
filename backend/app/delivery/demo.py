from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.app.delivery.base import DeliveryAdapterInput, DeliveryAdapterResult
from backend.app.domain.enums import DeliveryMode
from backend.app.observability.log_writer import LogPayloadSummary, LogRecordInput
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.observability import (
    AuditActorType,
    AuditResult,
    LogCategory,
    LogLevel,
)


DEMO_DELIVERY_LOG_SOURCE = "delivery.demo"
DEMO_DELIVERY_ACTOR_ID = "demo-delivery-adapter"
DEMO_DELIVERY_SUMMARY = "Demo delivery completed without Git writes."
DEMO_DELIVERY_REASON = (
    "Demo delivery records display output only and performs no Git write actions."
)


class DemoDeliveryAdapter:
    name = "demo_delivery"
    delivery_mode = DeliveryMode.DEMO_DELIVERY

    def __init__(
        self,
        *,
        audit_service: Any | None = None,
        log_writer: Any | None = None,
        redaction_policy: RedactionPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._audit_service = audit_service
        self._log_writer = log_writer
        self._redaction_policy = redaction_policy or RedactionPolicy()
        self._now = now or (lambda: datetime.now(UTC))

    def deliver(self, delivery_input: DeliveryAdapterInput) -> DeliveryAdapterResult:
        if delivery_input.delivery_mode is not DeliveryMode.DEMO_DELIVERY:
            raise ValueError("DemoDeliveryAdapter only supports demo_delivery")

        metadata = self._metadata(delivery_input)
        audit_ref = self._record_audit(delivery_input, metadata)
        log_ref = self._write_log(delivery_input, metadata)
        return DeliveryAdapterResult(
            run_id=delivery_input.run_id,
            stage_run_id=delivery_input.stage_run_id,
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            status="succeeded",
            result_ref=self._result_ref(delivery_input.run_id),
            process_ref=self._process_ref(delivery_input.run_id),
            branch_name=f"demo/{delivery_input.run_id}",
            commit_sha=None,
            code_review_url=None,
            audit_refs=[audit_ref] if audit_ref is not None else [],
            log_summary_refs=[log_ref] if log_ref is not None else [],
            trace_context=delivery_input.trace_context,
        )

    def _metadata(self, delivery_input: DeliveryAdapterInput) -> dict[str, Any]:
        trace = delivery_input.trace_context
        return {
            "run_id": delivery_input.run_id,
            "stage_run_id": delivery_input.stage_run_id,
            "delivery_channel_snapshot_ref": (
                delivery_input.delivery_channel_snapshot_ref
            ),
            "delivery_mode": DeliveryMode.DEMO_DELIVERY.value,
            "result_ref": self._result_ref(delivery_input.run_id),
            "process_ref": self._process_ref(delivery_input.run_id),
            "branch_name": f"demo/{delivery_input.run_id}",
            "git_write_actions": [],
            "no_git_actions": True,
            "requirement_refs": list(delivery_input.requirement_refs),
            "solution_refs": list(delivery_input.solution_refs),
            "changeset_refs": list(delivery_input.changeset_refs),
            "test_result_refs": list(delivery_input.test_result_refs),
            "review_refs": list(delivery_input.review_refs),
            "approval_result_refs": list(delivery_input.approval_result_refs),
            "artifact_refs": list(delivery_input.artifact_refs),
            "request_id": trace.request_id,
            "trace_id": trace.trace_id,
            "correlation_id": trace.correlation_id,
            "span_id": trace.span_id,
        }

    def _record_audit(
        self,
        delivery_input: DeliveryAdapterInput,
        metadata: dict[str, Any],
    ) -> str | None:
        if self._audit_service is None:
            return None
        result = self._audit_service.require_audit_record(
            actor_type=AuditActorType.SYSTEM,
            actor_id=DEMO_DELIVERY_ACTOR_ID,
            action="delivery.demo.succeeded",
            target_type="delivery_adapter",
            target_id=f"demo_delivery:{delivery_input.run_id}",
            result=AuditResult.SUCCEEDED,
            reason=DEMO_DELIVERY_REASON,
            metadata=metadata,
            trace_context=delivery_input.trace_context,
            rollback=None,
            created_at=self._now(),
        )
        audit_id = getattr(result, "audit_id", None)
        return audit_id if isinstance(audit_id, str) and audit_id else None

    def _write_log(
        self,
        delivery_input: DeliveryAdapterInput,
        metadata: dict[str, Any],
    ) -> str | None:
        if self._log_writer is None:
            return None
        redacted = self._redaction_policy.summarize_payload(
            metadata,
            payload_type="demo_delivery",
        )
        summary = LogPayloadSummary.from_redacted_payload(
            "demo_delivery",
            redacted,
        )
        if isinstance(redacted.redacted_payload, dict):
            summary.summary.update(redacted.redacted_payload)
        result = self._log_writer.write_run_log(
            LogRecordInput(
                source=DEMO_DELIVERY_LOG_SOURCE,
                category=LogCategory.DELIVERY,
                level=LogLevel.INFO,
                message=DEMO_DELIVERY_SUMMARY,
                trace_context=delivery_input.trace_context,
                payload=summary,
                created_at=self._now(),
            )
        )
        log_id = getattr(result, "log_id", None)
        return log_id if isinstance(log_id, str) and log_id else None

    @staticmethod
    def _result_ref(run_id: str) -> str:
        return f"demo-delivery-result:{run_id}"

    @staticmethod
    def _process_ref(run_id: str) -> str:
        return f"demo-delivery-process:{run_id}"


__all__ = [
    "DEMO_DELIVERY_ACTOR_ID",
    "DEMO_DELIVERY_LOG_SOURCE",
    "DEMO_DELIVERY_REASON",
    "DEMO_DELIVERY_SUMMARY",
    "DemoDeliveryAdapter",
]
