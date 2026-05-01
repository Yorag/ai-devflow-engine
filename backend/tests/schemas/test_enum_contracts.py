from enum import StrEnum

from pydantic import BaseModel

from backend.app.domain import enums
from backend.app.schemas import common


def values(enum_type: type[StrEnum]) -> set[str]:
    return {member.value for member in enum_type}


def test_stage_type_contains_only_six_business_stages() -> None:
    assert values(enums.StageType) == {
        "requirement_analysis",
        "solution_design",
        "code_generation",
        "test_generation_execution",
        "code_review",
        "delivery_integration",
    }


def test_feed_entry_type_contains_only_top_level_narrative_entries() -> None:
    assert values(enums.FeedEntryType) == {
        "user_message",
        "stage_node",
        "approval_request",
        "tool_confirmation",
        "control_item",
        "approval_result",
        "delivery_result",
        "system_status",
    }


def test_status_contracts_separate_session_run_stage_and_object_statuses() -> None:
    assert values(enums.SessionStatus) == {
        "draft",
        "running",
        "paused",
        "waiting_clarification",
        "waiting_approval",
        "waiting_tool_confirmation",
        "completed",
        "failed",
        "terminated",
    }
    assert values(enums.RunStatus) == {
        "running",
        "paused",
        "waiting_clarification",
        "waiting_approval",
        "waiting_tool_confirmation",
        "completed",
        "failed",
        "terminated",
    }
    assert values(enums.StageStatus) == {
        "running",
        "waiting_clarification",
        "waiting_approval",
        "waiting_tool_confirmation",
        "completed",
        "failed",
        "terminated",
        "superseded",
    }
    assert values(enums.ApprovalStatus) >= {
        "pending",
        "approved",
        "rejected",
        "cancelled",
    }
    assert values(enums.ToolConfirmationStatus) == {
        "pending",
        "allowed",
        "denied",
        "cancelled",
    }
    assert "draft" not in values(enums.RunStatus)
    assert "pending" not in values(enums.RunStatus)
    assert "pending" not in values(enums.StageStatus)
    assert "approved" not in values(enums.ToolConfirmationStatus)
    assert "rejected" not in values(enums.ToolConfirmationStatus)


def test_control_item_and_run_control_record_contracts_are_distinct() -> None:
    assert values(enums.ControlItemType) >= {
        "clarification_wait",
        "rollback",
        "retry",
    }
    assert "tool_confirmation" not in values(enums.ControlItemType)
    assert "system_status" not in values(enums.ControlItemType)
    assert values(enums.RunControlRecordType) >= {
        "clarification_wait",
        "rollback",
        "retry",
        "tool_confirmation",
    }


def test_configuration_and_delivery_enums_match_contracts() -> None:
    assert values(enums.DeliveryMode) == {"demo_delivery", "git_auto_delivery"}
    assert values(enums.DeliveryReadinessStatus) == {
        "unconfigured",
        "invalid",
        "ready",
    }
    assert values(enums.CredentialStatus) == {"unbound", "invalid", "ready"}
    assert values(enums.TemplateSource) == {"system_template", "user_template"}
    assert values(enums.ProviderSource) == {"builtin", "custom"}
    assert values(enums.ProviderProtocolType) >= {
        "volcengine_native",
        "openai_completions_compatible",
    }
    assert values(enums.ScmProviderType) >= {"github", "gitlab"}
    assert values(enums.CodeReviewRequestType) == {
        "pull_request",
        "merge_request",
    }
    assert values(enums.RunTriggerSource) == {
        "initial_requirement",
        "retry",
        "ops_restart",
    }


def test_tool_and_stage_item_enums_cover_runtime_contract_values() -> None:
    assert values(enums.ApprovalType) == {
        "solution_design_approval",
        "code_review_approval",
    }
    assert values(enums.ToolRiskLevel) == {
        "read_only",
        "low_risk_write",
        "high_risk",
        "blocked",
    }
    assert values(enums.ToolRiskCategory) >= {
        "dependency_change",
        "network_download",
        "file_delete_or_move",
        "broad_write",
        "database_migration",
        "lockfile_change",
        "environment_config_change",
        "unknown_command",
        "credential_access",
        "path_escape",
        "platform_runtime_mutation",
        "registry_or_audit_bypass",
    }
    assert values(enums.ProviderCircuitBreakerStatus) >= {
        "closed",
        "open",
        "half_open",
    }
    assert values(enums.StageItemType) >= {
        "dialogue",
        "context",
        "reasoning",
        "decision",
        "model_call",
        "provider_call",
        "tool_call",
        "tool_confirmation",
        "diff_preview",
        "result",
    }


def test_sse_event_type_covers_backend_session_event_stream_contract() -> None:
    assert values(enums.SseEventType) == {
        "session_created",
        "session_message_appended",
        "pipeline_run_created",
        "stage_started",
        "stage_updated",
        "clarification_requested",
        "clarification_answered",
        "approval_requested",
        "approval_result",
        "tool_confirmation_requested",
        "tool_confirmation_result",
        "control_item_created",
        "delivery_result",
        "system_status",
        "session_status_changed",
    }


def test_schema_common_reexports_enums_and_serializes_machine_values() -> None:
    assert common.StageType is enums.StageType
    assert common.FeedEntryType is enums.FeedEntryType
    assert common.SseEventType is enums.SseEventType

    class StageEnvelope(BaseModel):
        stage_type: common.StageType
        entry_type: common.FeedEntryType

    envelope = StageEnvelope(
        stage_type="solution_design",
        entry_type=common.FeedEntryType.STAGE_NODE,
    )

    assert envelope.stage_type is common.StageType.SOLUTION_DESIGN
    assert envelope.model_dump(mode="json") == {
        "stage_type": "solution_design",
        "entry_type": "stage_node",
    }
