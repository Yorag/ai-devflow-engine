from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.runtime import DeliveryChannelSnapshotModel, PipelineRunModel
from backend.app.domain.enums import (
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ToolRiskCategory,
    ToolRiskLevel,
)
from backend.app.observability.redaction import RedactionPolicy
from backend.app.schemas.observability import AuditResult
from backend.app.tools.protocol import (
    ToolBindableDescription,
    ToolError,
    ToolInput,
    ToolPermissionBoundary,
    ToolResult,
    ToolResultStatus,
    ToolSideEffectLevel,
)


READ_DELIVERY_SNAPSHOT_TOOL_NAME = "read_delivery_snapshot"
DELIVERY_TOOL_CATEGORY = "delivery"
_SCHEMA_VERSION = "tool-schema-v1"

_READ_DELIVERY_SNAPSHOT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"run_id": {"type": "string", "minLength": 1}},
    "required": ["run_id"],
    "additionalProperties": False,
}
_DELIVERY_SNAPSHOT_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "delivery_channel_snapshot_ref": {"type": "string"},
        "delivery_mode": {"type": "string", "enum": ["demo_delivery", "git_auto_delivery"]},
        "scm_provider_type": {"type": ["string", "null"]},
        "repository_identifier": {"type": ["string", "null"]},
        "default_branch": {"type": ["string", "null"]},
        "code_review_request_type": {"type": ["string", "null"]},
        "credential_ref": {"type": ["string", "null"]},
        "credential_status": {"type": "string"},
        "readiness_status": {"type": "string"},
        "readiness_message": {"type": ["string", "null"]},
        "last_validated_at": {"type": ["string", "null"]},
    },
    "required": [
        "delivery_channel_snapshot_ref",
        "delivery_mode",
        "scm_provider_type",
        "repository_identifier",
        "default_branch",
        "code_review_request_type",
        "credential_ref",
        "credential_status",
        "readiness_status",
        "readiness_message",
        "last_validated_at",
    ],
    "additionalProperties": False,
}
_READ_DELIVERY_SNAPSHOT_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "delivery_channel_snapshot_ref": {"type": "string"},
        "delivery_channel_snapshot": _DELIVERY_SNAPSHOT_OBJECT_SCHEMA,
    },
    "required": [
        "run_id",
        "delivery_channel_snapshot_ref",
        "delivery_channel_snapshot",
    ],
    "additionalProperties": False,
}
_GIT_AUTO_REQUIRED_FIELDS = (
    "scm_provider_type",
    "repository_identifier",
    "default_branch",
    "code_review_request_type",
    "credential_ref",
)
_PREVIEW_REDACTION = RedactionPolicy(max_text_length=240, excerpt_length=240)
_FAILURE_AUDIT_REQUIRED_CODES = frozenset(
    {
        ErrorCode.DELIVERY_SNAPSHOT_MISSING,
        ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
    }
)


@dataclass(frozen=True, slots=True)
class ScmDeliveryAdapter:
    runtime_session: Session
    audit_service: Any | None = None

    def read_delivery_snapshot(self, tool_input: ToolInput) -> ToolResult:
        run_id = str(tool_input.input_payload["run_id"])
        if (
            tool_input.trace_context.run_id is not None
            and tool_input.trace_context.run_id != run_id
        ):
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
                safe_details={
                    "run_id": run_id,
                    "trace_run_id": tool_input.trace_context.run_id,
                    "reason": "trace_run_mismatch",
                },
            )

        run = self.runtime_session.get(PipelineRunModel, run_id, populate_existing=True)
        if run is None or not run.delivery_channel_snapshot_ref:
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_MISSING,
                safe_details={"run_id": run_id, "reason": "delivery_snapshot_missing"},
            )

        snapshot = self.runtime_session.get(
            DeliveryChannelSnapshotModel,
            run.delivery_channel_snapshot_ref,
            populate_existing=True,
        )
        if snapshot is None or snapshot.run_id != run.run_id:
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_MISSING,
                safe_details={
                    "run_id": run_id,
                    "delivery_channel_snapshot_ref": run.delivery_channel_snapshot_ref,
                    "reason": "delivery_snapshot_missing",
                },
            )

        missing_fields = _missing_required_snapshot_fields(snapshot)
        if missing_fields:
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
                safe_details={
                    "run_id": run_id,
                    "delivery_channel_snapshot_ref": snapshot.delivery_channel_snapshot_id,
                    "reason": "delivery_snapshot_incomplete",
                    "missing_fields": missing_fields,
                },
            )

        if (
            snapshot.credential_status is not CredentialStatus.READY
            or snapshot.readiness_status is not DeliveryReadinessStatus.READY
        ):
            return self._failed_result(
                tool_input,
                error_code=ErrorCode.DELIVERY_SNAPSHOT_NOT_READY,
                safe_details={
                    "run_id": run_id,
                    "delivery_channel_snapshot_ref": snapshot.delivery_channel_snapshot_id,
                    "reason": "delivery_snapshot_not_ready",
                    "credential_status": snapshot.credential_status.value,
                    "readiness_status": snapshot.readiness_status.value,
                },
            )

        payload = _snapshot_payload(snapshot)
        return ToolResult(
            tool_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
            call_id=tool_input.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output_payload={
                "run_id": run.run_id,
                "delivery_channel_snapshot_ref": snapshot.delivery_channel_snapshot_id,
                "delivery_channel_snapshot": payload,
            },
            output_preview=_snapshot_preview(payload),
            artifact_refs=[snapshot.delivery_channel_snapshot_id],
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )

    def _failed_result(
        self,
        tool_input: ToolInput,
        *,
        error_code: ErrorCode,
        safe_details: dict[str, object],
    ) -> ToolResult:
        if error_code in _FAILURE_AUDIT_REQUIRED_CODES and not self._record_failure_audit(
            tool_input=tool_input,
            error_code=error_code,
            safe_details=safe_details,
        ):
            return ToolResult(
                tool_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
                call_id=tool_input.call_id,
                status=ToolResultStatus.FAILED,
                error=_safe_tool_error(
                    error_code=ErrorCode.TOOL_AUDIT_REQUIRED_FAILED,
                    tool_input=tool_input,
                    safe_details={
                        "reason": "delivery_failure_audit_unavailable",
                        "requested_error_code": error_code.value,
                    },
                ),
                trace_context=tool_input.trace_context,
                coordination_key=tool_input.coordination_key,
            )
        return ToolResult(
            tool_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
            call_id=tool_input.call_id,
            status=ToolResultStatus.FAILED,
            error=_safe_tool_error(
                error_code=error_code,
                tool_input=tool_input,
                safe_details=safe_details,
            ),
            trace_context=tool_input.trace_context,
            coordination_key=tool_input.coordination_key,
        )

    def _record_failure_audit(
        self,
        *,
        tool_input: ToolInput,
        error_code: ErrorCode,
        safe_details: dict[str, object],
    ) -> bool:
        if self.audit_service is None:
            return False
        try:
            self.audit_service.record_tool_error(
                tool_name=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
                command=READ_DELIVERY_SNAPSHOT_TOOL_NAME,
                error_code=error_code,
                result=AuditResult.FAILED,
                reason=str(safe_details.get("reason", error_code.value)),
                metadata=safe_details,
                trace_context=tool_input.trace_context,
            )
        except Exception:
            return False
        return True


@dataclass(frozen=True, slots=True)
class ReadDeliverySnapshotTool:
    adapter: ScmDeliveryAdapter

    @property
    def name(self) -> str:
        return READ_DELIVERY_SNAPSHOT_TOOL_NAME

    @property
    def category(self) -> str:
        return DELIVERY_TOOL_CATEGORY

    @property
    def description(self) -> str:
        return "Read the frozen delivery channel snapshot for the current run."

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _READ_DELIVERY_SNAPSHOT_INPUT_SCHEMA

    @property
    def result_schema(self) -> Mapping[str, object]:
        return _READ_DELIVERY_SNAPSHOT_RESULT_SCHEMA

    @property
    def default_risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.READ_ONLY

    @property
    def risk_categories(self) -> Sequence[ToolRiskCategory]:
        return ()

    @property
    def permission_boundary(self) -> ToolPermissionBoundary:
        return ToolPermissionBoundary(
            boundary_type=DELIVERY_TOOL_CATEGORY,
            requires_workspace=False,
            resource_scopes=("delivery_channel_snapshot",),
        )

    @property
    def side_effect_level(self) -> ToolSideEffectLevel:
        return ToolSideEffectLevel.NONE

    @property
    def audit_required(self) -> bool:
        return True

    @property
    def schema_version(self) -> str:
        return _SCHEMA_VERSION

    @property
    def default_timeout_seconds(self) -> float | None:
        return 5.0

    def bindable_description(self) -> ToolBindableDescription:
        return ToolBindableDescription(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
            result_schema=dict(self.result_schema),
            risk_level=self.default_risk_level,
            risk_categories=list(self.risk_categories),
            schema_version=self.schema_version,
            default_timeout_seconds=self.default_timeout_seconds,
        )

    def execute(self, tool_input: ToolInput) -> ToolResult:
        return self.adapter.read_delivery_snapshot(tool_input)


def _missing_required_snapshot_fields(
    snapshot: DeliveryChannelSnapshotModel,
) -> list[str]:
    if snapshot.delivery_mode is not DeliveryMode.GIT_AUTO_DELIVERY:
        return []
    missing: list[str] = []
    for field_name in _GIT_AUTO_REQUIRED_FIELDS:
        if getattr(snapshot, field_name) in (None, ""):
            missing.append(field_name)
    return missing


def _snapshot_payload(snapshot: DeliveryChannelSnapshotModel) -> dict[str, object]:
    return {
        "delivery_channel_snapshot_ref": snapshot.delivery_channel_snapshot_id,
        "delivery_mode": snapshot.delivery_mode.value,
        "scm_provider_type": _enum_value(snapshot.scm_provider_type),
        "repository_identifier": snapshot.repository_identifier,
        "default_branch": snapshot.default_branch,
        "code_review_request_type": _enum_value(snapshot.code_review_request_type),
        "credential_ref": snapshot.credential_ref,
        "credential_status": snapshot.credential_status.value,
        "readiness_status": snapshot.readiness_status.value,
        "readiness_message": snapshot.readiness_message,
        "last_validated_at": (
            snapshot.last_validated_at.isoformat()
            if snapshot.last_validated_at is not None
            else None
        ),
    }


def _snapshot_preview(snapshot_payload: Mapping[str, object]) -> str:
    delivery_mode = snapshot_payload["delivery_mode"]
    readiness_status = snapshot_payload["readiness_status"]
    repository_configured = snapshot_payload.get("repository_identifier") is not None
    default_branch_configured = snapshot_payload.get("default_branch") is not None
    redacted = _PREVIEW_REDACTION.summarize_text(
        f"delivery_snapshot {delivery_mode} "
        f"repository_configured={str(repository_configured).lower()} "
        f"default_branch_configured={str(default_branch_configured).lower()} "
        f"{readiness_status}",
        payload_type="delivery_snapshot_tool_preview",
    )
    if isinstance(redacted.redacted_payload, str) and redacted.redacted_payload:
        return redacted.redacted_payload
    return redacted.excerpt or "[redacted]"


def _safe_tool_error(
    *,
    error_code: ErrorCode,
    tool_input: ToolInput,
    safe_details: dict[str, object],
) -> ToolError:
    try:
        return ToolError.from_code(
            error_code,
            trace_context=tool_input.trace_context,
            safe_details=safe_details,
        )
    except ValueError:
        return ToolError.from_code(
            error_code,
            trace_context=tool_input.trace_context,
            safe_details={"detail_redacted": True},
        )


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return value.value


__all__ = [
    "READ_DELIVERY_SNAPSHOT_TOOL_NAME",
    "ScmDeliveryAdapter",
    "ReadDeliverySnapshotTool",
]
