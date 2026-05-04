from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.api.error_codes import ErrorCode
from backend.app.delivery.base import (
    DeliveryAdapterError,
    DeliveryAdapterInput,
    DeliveryAdapterResult,
)
from backend.app.delivery.scm import (
    CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
    CREATE_COMMIT_TOOL_NAME,
    PREPARE_BRANCH_TOOL_NAME,
    PUSH_BRANCH_TOOL_NAME,
    READ_DELIVERY_SNAPSHOT_TOOL_NAME,
)
from backend.app.domain.enums import DeliveryMode
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import ToolExecutionContext, ToolExecutionRequest
from backend.app.tools.protocol import ToolAuditRef, ToolError, ToolResult, ToolResultStatus


GIT_AUTO_DELIVERY_RESULT_PREFIX = "git-auto-delivery-result"
GIT_AUTO_DELIVERY_PROCESS_PREFIX = "git-auto-delivery-process"
_GIT_AUTO_DELIVERY_TOOL_SEQUENCE = (
    READ_DELIVERY_SNAPSHOT_TOOL_NAME,
    PREPARE_BRANCH_TOOL_NAME,
    CREATE_COMMIT_TOOL_NAME,
    PUSH_BRANCH_TOOL_NAME,
    CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
)
_READY_SNAPSHOT_REQUIRED_STRINGS = (
    "scm_provider_type",
    "repository_identifier",
    "default_branch",
    "code_review_request_type",
    "credential_ref",
)


class GitAutoDeliveryError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        safe_message: str,
        safe_details: dict[str, object] | None = None,
    ) -> None:
        self.error_code = error_code
        self.safe_message = safe_message
        self.safe_details = safe_details or {}
        super().__init__(safe_message)


class GitAutoDeliveryAdapter:
    def __init__(
        self,
        *,
        tool_registry: Any,
        execution_context_factory: Callable[[TraceContext], ToolExecutionContext],
        repository_path: str | Path,
        remote_name: str = "origin",
        branch_name_factory: Callable[[DeliveryAdapterInput], str] | None = None,
        commit_message_factory: Callable[[DeliveryAdapterInput], str] | None = None,
        review_title_factory: Callable[[DeliveryAdapterInput], str] | None = None,
        review_body_factory: Callable[[DeliveryAdapterInput], str] | None = None,
        pending_delivery_record_id_factory: (
            Callable[[DeliveryAdapterInput], str] | None
        ) = None,
        confirmation_resolver: Callable[
            [ToolExecutionRequest, ToolResult, ToolExecutionContext],
            ToolExecutionRequest | None,
        ]
        | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._execution_context_factory = execution_context_factory
        self._repository_path = Path(repository_path)
        self._remote_name = remote_name
        self._branch_name_factory = branch_name_factory or (
            lambda delivery_input: f"delivery/{delivery_input.run_id}"
        )
        self._commit_message_factory = commit_message_factory or (
            lambda delivery_input: f"Deliver run {delivery_input.run_id}"
        )
        self._review_title_factory = review_title_factory or (
            lambda delivery_input: f"Deliver run {delivery_input.run_id}"
        )
        self._review_body_factory = review_body_factory or (
            lambda delivery_input: "Delivery branch is ready for review."
        )
        self._pending_delivery_record_id_factory = (
            pending_delivery_record_id_factory
            or (lambda delivery_input: f"delivery-record-{delivery_input.run_id}")
        )
        self._confirmation_resolver = confirmation_resolver
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def delivery_mode(self) -> DeliveryMode:
        return DeliveryMode.GIT_AUTO_DELIVERY

    @property
    def name(self) -> str:
        return "git_auto_delivery"

    def deliver(self, delivery_input: DeliveryAdapterInput) -> DeliveryAdapterResult:
        if delivery_input.delivery_mode is not DeliveryMode.GIT_AUTO_DELIVERY:
            raise ValueError("GitAutoDeliveryAdapter only supports git_auto_delivery")

        step_results: dict[str, ToolResult] = {}

        read_result = self._execute_step(
            step_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
            payload={"run_id": delivery_input.run_id},
            parent_trace=delivery_input.trace_context,
        )
        step_results[READ_DELIVERY_SNAPSHOT_TOOL_NAME] = read_result
        if read_result.status is not ToolResultStatus.SUCCEEDED:
            return self._adapter_result_from_tool_failure(
                delivery_input=delivery_input,
                failed_step=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
                tool_result=read_result,
            )

        try:
            snapshot = self.assert_snapshot_ready(
                delivery_input=delivery_input,
                snapshot=self._snapshot_from_read_result(read_result),
            )
        except GitAutoDeliveryError as exc:
            return self._adapter_result_from_delivery_error(
                delivery_input=delivery_input,
                error=exc,
                failed_step=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
                audit_refs=(
                    [read_result.audit_ref.audit_id]
                    if read_result.audit_ref is not None
                    else []
                ),
            )

        branch_name = self._branch_name_factory(delivery_input)
        commit_message = self._commit_message_factory(delivery_input)
        review_title = self._review_title_factory(delivery_input)
        review_body = self._review_body_factory(delivery_input)
        pending_delivery_record_id = self._pending_delivery_record_id_factory(
            delivery_input
        )

        for step_name, payload in (
            (
                PREPARE_BRANCH_TOOL_NAME,
                {
                    "repository_path": str(self._repository_path),
                    "branch_name": branch_name,
                    "base_branch": str(snapshot["default_branch"]),
                    "delivery_record_id": pending_delivery_record_id,
                },
            ),
            (
                CREATE_COMMIT_TOOL_NAME,
                {
                    "repository_path": str(self._repository_path),
                    "commit_message": commit_message,
                    "delivery_record_id": pending_delivery_record_id,
                },
            ),
            (
                PUSH_BRANCH_TOOL_NAME,
                {
                    "repository_path": str(self._repository_path),
                    "remote_name": self._remote_name,
                    "branch_name": branch_name,
                    "delivery_record_id": pending_delivery_record_id,
                },
            ),
            (
                CREATE_CODE_REVIEW_REQUEST_TOOL_NAME,
                {
                    "repository_identifier": str(snapshot["repository_identifier"]),
                    "source_branch": branch_name,
                    "target_branch": str(snapshot["default_branch"]),
                    "title": review_title,
                    "body": review_body,
                    "code_review_request_type": str(
                        snapshot["code_review_request_type"]
                    ),
                    "delivery_record_id": pending_delivery_record_id,
                },
            ),
        ):
            result = self._execute_step(
                step_name=step_name,
                payload=payload,
                parent_trace=delivery_input.trace_context,
            )
            step_results[step_name] = result
            if result.status is not ToolResultStatus.SUCCEEDED:
                return self._adapter_result_from_tool_failure(
                    delivery_input=delivery_input,
                    failed_step=step_name,
                    tool_result=result,
                )

        return self.build_delivery_record(
            delivery_input=delivery_input,
            snapshot=snapshot,
            step_results=step_results,
        )

    def assert_snapshot_ready(
        self,
        *,
        delivery_input: DeliveryAdapterInput,
        snapshot: Mapping[str, object],
    ) -> Mapping[str, object]:
        if not snapshot:
            raise GitAutoDeliveryError(
                error_code=ErrorCode.DELIVERY_SNAPSHOT_MISSING.value,
                safe_message="Delivery snapshot is missing.",
                safe_details={"reason": "delivery_snapshot_missing"},
            )

        snapshot_ref = snapshot.get("delivery_channel_snapshot_ref")
        if snapshot_ref != delivery_input.delivery_channel_snapshot_ref:
            raise GitAutoDeliveryError(
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY.value,
                safe_message="Delivery snapshot is not ready.",
                safe_details={
                    "reason": "delivery_snapshot_ref_mismatch",
                    "delivery_channel_snapshot_ref": snapshot_ref
                    if isinstance(snapshot_ref, str)
                    else None,
                    "expected_delivery_channel_snapshot_ref": (
                        delivery_input.delivery_channel_snapshot_ref
                    ),
                },
            )

        if snapshot.get("delivery_mode") != DeliveryMode.GIT_AUTO_DELIVERY.value:
            raise GitAutoDeliveryError(
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY.value,
                safe_message="Delivery snapshot is not ready.",
                safe_details={
                    "reason": "delivery_mode_not_git_auto_delivery",
                    "delivery_mode": str(snapshot.get("delivery_mode")),
                },
            )

        missing_fields = [
            field_name
            for field_name in _READY_SNAPSHOT_REQUIRED_STRINGS
            if not _is_non_empty_string(snapshot.get(field_name))
        ]
        if missing_fields:
            raise GitAutoDeliveryError(
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY.value,
                safe_message="Delivery snapshot is not ready.",
                safe_details={
                    "reason": "delivery_snapshot_incomplete",
                    "missing_fields": missing_fields,
                    "delivery_channel_snapshot_ref": snapshot_ref,
                },
            )

        credential_status = snapshot.get("credential_status")
        readiness_status = snapshot.get("readiness_status")
        if credential_status != "ready" or readiness_status != "ready":
            raise GitAutoDeliveryError(
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY.value,
                safe_message="Delivery snapshot is not ready.",
                safe_details={
                    "reason": "delivery_snapshot_not_ready",
                    "credential_status": str(credential_status),
                    "readiness_status": str(readiness_status),
                    "delivery_channel_snapshot_ref": snapshot_ref,
                },
            )

        return snapshot

    def build_delivery_record(
        self,
        *,
        delivery_input: DeliveryAdapterInput,
        snapshot: Mapping[str, object],
        step_results: Mapping[str, ToolResult],
    ) -> DeliveryAdapterResult:
        del snapshot
        prepare_result = step_results[PREPARE_BRANCH_TOOL_NAME]
        commit_result = step_results[CREATE_COMMIT_TOOL_NAME]
        review_result = step_results[CREATE_CODE_REVIEW_REQUEST_TOOL_NAME]
        return DeliveryAdapterResult(
            run_id=delivery_input.run_id,
            stage_run_id=delivery_input.stage_run_id,
            delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
            status="succeeded",
            result_ref=self._result_ref(delivery_input),
            process_ref=self._process_ref(delivery_input),
            branch_name=str(prepare_result.output_payload["branch_name"]),
            commit_sha=str(commit_result.output_payload["commit_sha"]),
            code_review_url=str(review_result.output_payload["code_review_url"]),
            audit_refs=[
                result.audit_ref.audit_id
                for step_name in _GIT_AUTO_DELIVERY_TOOL_SEQUENCE
                if (result := step_results[step_name]).audit_ref is not None
            ],
            log_summary_refs=[],
            trace_context=delivery_input.trace_context,
        )

    def _execute_step(
        self,
        *,
        step_name: str,
        payload: dict[str, object],
        parent_trace: TraceContext,
    ) -> ToolResult:
        step_trace = parent_trace.child_span(
            span_id=f"git-auto-delivery-{step_name}",
            created_at=self._now(),
        )
        request = ToolExecutionRequest(
            tool_name=step_name,
            call_id=f"call-{step_name}",
            input_payload=payload,
            trace_context=step_trace,
            coordination_key=(
                f"{step_trace.run_id}:{step_trace.stage_run_id}:{step_name}"
            ),
        )
        context = self._execution_context_factory(step_trace)
        result = self._tool_registry.execute(request, context)
        if (
            result.status is not ToolResultStatus.WAITING_CONFIRMATION
            or self._confirmation_resolver is None
        ):
            return result

        expected_confirmed_request = request.model_copy(deep=True)
        confirmed_request = self._confirmation_resolver(request, result, context)
        if confirmed_request is None:
            return result
        mismatch = _confirmation_request_mismatch(
            expected_confirmed_request,
            confirmed_request,
        )
        if mismatch:
            return ToolResult(
                tool_name=step_name,
                call_id=expected_confirmed_request.call_id,
                status=ToolResultStatus.FAILED,
                error=ToolError.from_code(
                    ErrorCode.INTERNAL_ERROR,
                    trace_context=expected_confirmed_request.trace_context,
                    safe_message="Delivery tool confirmation request is invalid.",
                    safe_details={
                        "reason": "confirmation_request_mismatch",
                        "mismatched_fields": mismatch,
                    },
                    audit_ref=result.audit_ref,
                ),
                audit_ref=result.audit_ref,
                tool_confirmation_ref=result.tool_confirmation_ref,
                trace_context=expected_confirmed_request.trace_context,
                coordination_key=expected_confirmed_request.coordination_key,
            )

        confirmed_context = self._confirmed_context(
            original_context=context,
            confirmed_trace=confirmed_request.trace_context,
            audit_ref=result.audit_ref,
        )
        return self._tool_registry.execute(confirmed_request, confirmed_context)

    def _adapter_result_from_tool_failure(
        self,
        *,
        delivery_input: DeliveryAdapterInput,
        failed_step: str,
        tool_result: ToolResult,
    ) -> DeliveryAdapterResult:
        tool_error = tool_result.error
        if tool_error is None:
            error = DeliveryAdapterError(
                error_code=ErrorCode.INTERNAL_ERROR.value,
                safe_message="Delivery tool returned an invalid failure result.",
                safe_details={
                    "failed_step": failed_step,
                    "tool_name": tool_result.tool_name,
                    "tool_call_id": tool_result.call_id,
                    "tool_confirmation_ref": tool_result.tool_confirmation_ref,
                    "tool_audit_id": (
                        tool_result.audit_ref.audit_id
                        if tool_result.audit_ref is not None
                        else None
                    ),
                },
            )
        else:
            safe_details = {
                "failed_step": failed_step,
                "tool_name": tool_result.tool_name,
                "tool_call_id": tool_result.call_id,
                "tool_confirmation_ref": tool_result.tool_confirmation_ref,
                "tool_audit_id": (
                    tool_result.audit_ref.audit_id
                    if tool_result.audit_ref is not None
                    else None
                ),
                **tool_error.safe_details,
            }
            error = DeliveryAdapterError(
                error_code=tool_error.error_code.value,
                safe_message=tool_error.safe_message,
                safe_details=safe_details,
            )

        return DeliveryAdapterResult(
            run_id=delivery_input.run_id,
            stage_run_id=delivery_input.stage_run_id,
            delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
            status=(
                "blocked"
                if tool_result.status
                in (ToolResultStatus.WAITING_CONFIRMATION, ToolResultStatus.BLOCKED)
                else "failed"
            ),
            process_ref=self._process_ref(delivery_input),
            audit_refs=(
                [tool_result.audit_ref.audit_id]
                if tool_result.audit_ref is not None
                else []
            ),
            log_summary_refs=[],
            error=error,
            trace_context=delivery_input.trace_context,
        )

    def _adapter_result_from_delivery_error(
        self,
        *,
        delivery_input: DeliveryAdapterInput,
        error: GitAutoDeliveryError,
        failed_step: str,
        audit_refs: list[str] | None = None,
    ) -> DeliveryAdapterResult:
        return DeliveryAdapterResult(
            run_id=delivery_input.run_id,
            stage_run_id=delivery_input.stage_run_id,
            delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
            status="failed",
            process_ref=self._process_ref(delivery_input),
            audit_refs=audit_refs or [],
            log_summary_refs=[],
            error=DeliveryAdapterError(
                error_code=error.error_code,
                safe_message=error.safe_message,
                safe_details={"failed_step": failed_step, **error.safe_details},
            ),
            trace_context=delivery_input.trace_context,
        )

    def _snapshot_from_read_result(
        self,
        read_result: ToolResult,
    ) -> Mapping[str, object]:
        snapshot = read_result.output_payload.get("delivery_channel_snapshot")
        if not isinstance(snapshot, Mapping):
            raise GitAutoDeliveryError(
                error_code=ErrorCode.DELIVERY_SNAPSHOT_MISSING.value,
                safe_message="Delivery snapshot is missing.",
                safe_details={"reason": "delivery_snapshot_payload_missing"},
            )
        return snapshot

    def _confirmed_context(
        self,
        *,
        original_context: ToolExecutionContext,
        confirmed_trace: TraceContext,
        audit_ref: ToolAuditRef | None,
    ) -> ToolExecutionContext:
        if audit_ref is None or original_context.audit_recorder is None:
            return self._execution_context_factory(confirmed_trace)
        return replace(
            original_context,
            trace_context=confirmed_trace,
            audit_recorder=_ReusedToolIntentAuditRecorder(
                audit_ref=audit_ref,
                delegate=original_context.audit_recorder,
            ),
        )

    def _result_ref(self, delivery_input: DeliveryAdapterInput) -> str:
        return f"{GIT_AUTO_DELIVERY_RESULT_PREFIX}:{delivery_input.run_id}"

    def _process_ref(self, delivery_input: DeliveryAdapterInput) -> str:
        return f"{GIT_AUTO_DELIVERY_PROCESS_PREFIX}:{delivery_input.run_id}"


class _ReusedToolIntentAuditRecorder:
    def __init__(self, *, audit_ref: ToolAuditRef, delegate: Any) -> None:
        self._audit_ref = audit_ref
        self._delegate = delegate

    def record_tool_intent(self, **kwargs: object) -> ToolAuditRef:
        del kwargs
        return self._audit_ref

    def record_tool_rejection(self, **kwargs: object) -> ToolAuditRef:
        if hasattr(self._delegate, "record_tool_rejection"):
            return self._delegate.record_tool_rejection(**kwargs)
        return self._audit_ref


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _confirmation_request_mismatch(
    original: ToolExecutionRequest,
    confirmed: ToolExecutionRequest,
) -> list[str]:
    mismatched_fields: list[str] = []
    for field_name in (
        "tool_name",
        "call_id",
        "input_payload",
        "coordination_key",
        "timeout_seconds",
    ):
        if getattr(original, field_name) != getattr(confirmed, field_name):
            mismatched_fields.append(field_name)
    original_trace = original.trace_context.model_dump(
        exclude={"tool_confirmation_id"}
    )
    confirmed_trace = confirmed.trace_context.model_dump(
        exclude={"tool_confirmation_id"}
    )
    if original_trace != confirmed_trace:
        mismatched_fields.append("trace_context")
    return mismatched_fields


__all__ = [
    "GIT_AUTO_DELIVERY_PROCESS_PREFIX",
    "GIT_AUTO_DELIVERY_RESULT_PREFIX",
    "GitAutoDeliveryAdapter",
    "GitAutoDeliveryError",
]
