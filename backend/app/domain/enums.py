from enum import StrEnum


class ContractEnum(StrEnum):
    """Base class for stable string-backed contract enums."""


class SessionStatus(ContractEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_TOOL_CONFIRMATION = "waiting_tool_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class RunStatus(ContractEnum):
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_TOOL_CONFIRMATION = "waiting_tool_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class StageStatus(ContractEnum):
    RUNNING = "running"
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_TOOL_CONFIRMATION = "waiting_tool_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"
    SUPERSEDED = "superseded"


class StageType(ContractEnum):
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    SOLUTION_DESIGN = "solution_design"
    CODE_GENERATION = "code_generation"
    TEST_GENERATION_EXECUTION = "test_generation_execution"
    CODE_REVIEW = "code_review"
    DELIVERY_INTEGRATION = "delivery_integration"


class FeedEntryType(ContractEnum):
    USER_MESSAGE = "user_message"
    STAGE_NODE = "stage_node"
    APPROVAL_REQUEST = "approval_request"
    TOOL_CONFIRMATION = "tool_confirmation"
    CONTROL_ITEM = "control_item"
    APPROVAL_RESULT = "approval_result"
    DELIVERY_RESULT = "delivery_result"
    SYSTEM_STATUS = "system_status"


class ControlItemType(ContractEnum):
    CLARIFICATION_WAIT = "clarification_wait"
    ROLLBACK = "rollback"
    RETRY = "retry"


class RunControlRecordType(ContractEnum):
    CLARIFICATION_WAIT = "clarification_wait"
    ROLLBACK = "rollback"
    RETRY = "retry"
    TOOL_CONFIRMATION = "tool_confirmation"


class ClarificationStatus(ContractEnum):
    PENDING = "pending"
    ANSWERED = "answered"


class ApprovalType(ContractEnum):
    SOLUTION_DESIGN_APPROVAL = "solution_design_approval"
    CODE_REVIEW_APPROVAL = "code_review_approval"


class DeliveryMode(ContractEnum):
    DEMO_DELIVERY = "demo_delivery"
    GIT_AUTO_DELIVERY = "git_auto_delivery"


class DeliveryReadinessStatus(ContractEnum):
    UNCONFIGURED = "unconfigured"
    INVALID = "invalid"
    READY = "ready"


class CredentialStatus(ContractEnum):
    UNBOUND = "unbound"
    INVALID = "invalid"
    READY = "ready"


class TemplateSource(ContractEnum):
    SYSTEM_TEMPLATE = "system_template"
    USER_TEMPLATE = "user_template"


class ProviderSource(ContractEnum):
    BUILTIN = "builtin"
    CUSTOM = "custom"


class ProviderProtocolType(ContractEnum):
    VOLCENGINE_NATIVE = "volcengine_native"
    OPENAI_COMPLETIONS_COMPATIBLE = "openai_completions_compatible"


class ScmProviderType(ContractEnum):
    GITHUB = "github"
    GITLAB = "gitlab"


class CodeReviewRequestType(ContractEnum):
    PULL_REQUEST = "pull_request"
    MERGE_REQUEST = "merge_request"


class RunTriggerSource(ContractEnum):
    INITIAL_REQUIREMENT = "initial_requirement"
    RETRY = "retry"
    OPS_RESTART = "ops_restart"


class ApprovalStatus(ContractEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ToolConfirmationStatus(ContractEnum):
    PENDING = "pending"
    ALLOWED = "allowed"
    DENIED = "denied"
    CANCELLED = "cancelled"


class ToolRiskLevel(ContractEnum):
    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    HIGH_RISK = "high_risk"
    BLOCKED = "blocked"


class ToolRiskCategory(ContractEnum):
    DEPENDENCY_CHANGE = "dependency_change"
    NETWORK_DOWNLOAD = "network_download"
    FILE_DELETE_OR_MOVE = "file_delete_or_move"
    BROAD_WRITE = "broad_write"
    DATABASE_MIGRATION = "database_migration"
    LOCKFILE_CHANGE = "lockfile_change"
    ENVIRONMENT_CONFIG_CHANGE = "environment_config_change"
    UNKNOWN_COMMAND = "unknown_command"
    CREDENTIAL_ACCESS = "credential_access"
    PATH_ESCAPE = "path_escape"
    PLATFORM_RUNTIME_MUTATION = "platform_runtime_mutation"
    REGISTRY_OR_AUDIT_BYPASS = "registry_or_audit_bypass"


class ProviderCircuitBreakerStatus(ContractEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class StageItemType(ContractEnum):
    DIALOGUE = "dialogue"
    CONTEXT = "context"
    REASONING = "reasoning"
    DECISION = "decision"
    MODEL_CALL = "model_call"
    PROVIDER_CALL = "provider_call"
    TOOL_CALL = "tool_call"
    TOOL_CONFIRMATION = "tool_confirmation"
    DIFF_PREVIEW = "diff_preview"
    RESULT = "result"


class SseEventType(ContractEnum):
    SESSION_CREATED = "session_created"
    SESSION_MESSAGE_APPENDED = "session_message_appended"
    PIPELINE_RUN_CREATED = "pipeline_run_created"
    STAGE_STARTED = "stage_started"
    STAGE_UPDATED = "stage_updated"
    CLARIFICATION_REQUESTED = "clarification_requested"
    CLARIFICATION_ANSWERED = "clarification_answered"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESULT = "approval_result"
    TOOL_CONFIRMATION_REQUESTED = "tool_confirmation_requested"
    TOOL_CONFIRMATION_RESULT = "tool_confirmation_result"
    CONTROL_ITEM_CREATED = "control_item_created"
    DELIVERY_RESULT = "delivery_result"
    SYSTEM_STATUS = "system_status"
    SESSION_STATUS_CHANGED = "session_status_changed"


__all__ = [
    "ApprovalStatus",
    "ApprovalType",
    "CodeReviewRequestType",
    "ClarificationStatus",
    "ContractEnum",
    "ControlItemType",
    "CredentialStatus",
    "DeliveryMode",
    "DeliveryReadinessStatus",
    "FeedEntryType",
    "ProviderCircuitBreakerStatus",
    "ProviderProtocolType",
    "ProviderSource",
    "RunControlRecordType",
    "RunStatus",
    "RunTriggerSource",
    "ScmProviderType",
    "SessionStatus",
    "StageItemType",
    "StageStatus",
    "StageType",
    "SseEventType",
    "TemplateSource",
    "ToolConfirmationStatus",
    "ToolRiskCategory",
    "ToolRiskLevel",
]
