from __future__ import annotations

from enum import StrEnum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.schemas.errors import ErrorCatalogEntry


class ErrorCode(StrEnum):
    INTERNAL_ERROR = "internal_error"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    CONFIG_INVALID_VALUE = "config_invalid_value"
    CONFIG_HARD_LIMIT_EXCEEDED = "config_hard_limit_exceeded"
    CONFIG_VERSION_CONFLICT = "config_version_conflict"
    CONFIG_STORAGE_UNAVAILABLE = "config_storage_unavailable"
    CONFIG_SNAPSHOT_UNAVAILABLE = "config_snapshot_unavailable"
    CONFIG_CREDENTIAL_ENV_NOT_ALLOWED = "config_credential_env_not_allowed"
    CONFIG_SNAPSHOT_MUTATION_BLOCKED = "config_snapshot_mutation_blocked"
    TOOL_UNKNOWN = "tool_unknown"
    TOOL_NOT_ALLOWED = "tool_not_allowed"
    TOOL_INPUT_SCHEMA_INVALID = "tool_input_schema_invalid"
    TOOL_WORKSPACE_BOUNDARY_VIOLATION = "tool_workspace_boundary_violation"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_AUDIT_REQUIRED_FAILED = "tool_audit_required_failed"
    TOOL_CONFIRMATION_REQUIRED = "tool_confirmation_required"
    TOOL_CONFIRMATION_DENIED = "tool_confirmation_denied"
    TOOL_CONFIRMATION_NOT_ACTIONABLE = "tool_confirmation_not_actionable"
    TOOL_RISK_BLOCKED = "tool_risk_blocked"
    BASH_COMMAND_NOT_ALLOWED = "bash_command_not_allowed"
    PROVIDER_RETRY_EXHAUSTED = "provider_retry_exhausted"
    PROVIDER_CIRCUIT_OPEN = "provider_circuit_open"
    DELIVERY_SNAPSHOT_MISSING = "delivery_snapshot_missing"
    DELIVERY_SNAPSHOT_NOT_READY = "delivery_snapshot_not_ready"
    DELIVERY_GIT_CLI_FAILED = "delivery_git_cli_failed"
    DELIVERY_REMOTE_REQUEST_FAILED = "delivery_remote_request_failed"
    RUNTIME_DATA_DIR_UNAVAILABLE = "runtime_data_dir_unavailable"
    AUDIT_WRITE_FAILED = "audit_write_failed"
    LOG_QUERY_INVALID = "log_query_invalid"
    LOG_PAYLOAD_BLOCKED = "log_payload_blocked"


class RuntimeSettingsErrorCode(StrEnum):
    CONFIG_INVALID_VALUE = ErrorCode.CONFIG_INVALID_VALUE.value
    CONFIG_HARD_LIMIT_EXCEEDED = ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED.value
    CONFIG_VERSION_CONFLICT = ErrorCode.CONFIG_VERSION_CONFLICT.value
    CONFIG_STORAGE_UNAVAILABLE = ErrorCode.CONFIG_STORAGE_UNAVAILABLE.value
    CONFIG_SNAPSHOT_UNAVAILABLE = ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE.value


_ERROR_CATALOG_ROWS: dict[ErrorCode, dict[str, Any]] = {
    ErrorCode.INTERNAL_ERROR: {
        "category": "api",
        "default_http_status": HTTPStatus.INTERNAL_SERVER_ERROR,
        "retryable": False,
        "user_visible": False,
        "default_safe_title": "Internal error",
        "default_safe_message": "Internal server error.",
    },
    ErrorCode.NOT_FOUND: {
        "category": "api",
        "default_http_status": HTTPStatus.NOT_FOUND,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Resource not found",
        "default_safe_message": "The requested resource was not found.",
    },
    ErrorCode.VALIDATION_ERROR: {
        "category": "api",
        "default_http_status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Validation error",
        "default_safe_message": "Request validation failed.",
    },
    ErrorCode.CONFIG_INVALID_VALUE: {
        "category": "configuration",
        "default_http_status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Invalid configuration value",
        "default_safe_message": "Configuration value is invalid.",
    },
    ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED: {
        "category": "configuration",
        "default_http_status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Configuration hard limit exceeded",
        "default_safe_message": "Configuration value exceeds the platform hard limit.",
    },
    ErrorCode.CONFIG_VERSION_CONFLICT: {
        "category": "configuration",
        "default_http_status": HTTPStatus.CONFLICT,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Configuration version conflict",
        "default_safe_message": "Configuration version conflict.",
    },
    ErrorCode.CONFIG_STORAGE_UNAVAILABLE: {
        "category": "configuration",
        "default_http_status": HTTPStatus.SERVICE_UNAVAILABLE,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Configuration storage unavailable",
        "default_safe_message": "Configuration storage is unavailable.",
    },
    ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE: {
        "category": "configuration",
        "default_http_status": HTTPStatus.SERVICE_UNAVAILABLE,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Configuration snapshot unavailable",
        "default_safe_message": "Configuration snapshot is unavailable.",
    },
    ErrorCode.CONFIG_CREDENTIAL_ENV_NOT_ALLOWED: {
        "category": "configuration",
        "default_http_status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Credential reference not allowed",
        "default_safe_message": "Credential environment reference is not allowed.",
    },
    ErrorCode.CONFIG_SNAPSHOT_MUTATION_BLOCKED: {
        "category": "configuration",
        "default_http_status": HTTPStatus.CONFLICT,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Configuration snapshot mutation blocked",
        "default_safe_message": "Configuration snapshot mutation is blocked for this run.",
    },
    ErrorCode.TOOL_UNKNOWN: {
        "category": "tool",
        "default_http_status": HTTPStatus.NOT_FOUND,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Tool not registered",
        "default_safe_message": "Tool is not registered.",
    },
    ErrorCode.TOOL_NOT_ALLOWED: {
        "category": "tool",
        "default_http_status": HTTPStatus.FORBIDDEN,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Tool not allowed",
        "default_safe_message": "Tool is not allowed for the current stage.",
    },
    ErrorCode.TOOL_INPUT_SCHEMA_INVALID: {
        "category": "tool",
        "default_http_status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Tool input schema invalid",
        "default_safe_message": "Tool input does not match the registered schema.",
    },
    ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION: {
        "category": "tool",
        "default_http_status": HTTPStatus.FORBIDDEN,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Workspace boundary violation",
        "default_safe_message": "Tool target is outside the run workspace.",
    },
    ErrorCode.TOOL_TIMEOUT: {
        "category": "tool",
        "default_http_status": HTTPStatus.REQUEST_TIMEOUT,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Tool timeout",
        "default_safe_message": "Tool execution timed out.",
    },
    ErrorCode.TOOL_AUDIT_REQUIRED_FAILED: {
        "category": "tool",
        "default_http_status": HTTPStatus.SERVICE_UNAVAILABLE,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Tool audit required failed",
        "default_safe_message": "Required tool audit record could not be written.",
    },
    ErrorCode.TOOL_CONFIRMATION_REQUIRED: {
        "category": "tool",
        "default_http_status": HTTPStatus.CONFLICT,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Tool confirmation required",
        "default_safe_message": "Tool execution is waiting for user confirmation.",
    },
    ErrorCode.TOOL_CONFIRMATION_DENIED: {
        "category": "tool",
        "default_http_status": HTTPStatus.FORBIDDEN,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Tool confirmation denied",
        "default_safe_message": "Tool confirmation was denied.",
    },
    ErrorCode.TOOL_CONFIRMATION_NOT_ACTIONABLE: {
        "category": "tool",
        "default_http_status": HTTPStatus.CONFLICT,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Tool confirmation not actionable",
        "default_safe_message": "Tool confirmation is not actionable.",
    },
    ErrorCode.TOOL_RISK_BLOCKED: {
        "category": "tool",
        "default_http_status": HTTPStatus.FORBIDDEN,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Tool risk blocked",
        "default_safe_message": "Tool action was blocked by risk policy.",
    },
    ErrorCode.BASH_COMMAND_NOT_ALLOWED: {
        "category": "tool",
        "default_http_status": HTTPStatus.FORBIDDEN,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Bash command not allowed",
        "default_safe_message": "Bash command is not allowed by policy.",
    },
    ErrorCode.PROVIDER_RETRY_EXHAUSTED: {
        "category": "provider",
        "default_http_status": HTTPStatus.SERVICE_UNAVAILABLE,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Provider retry exhausted",
        "default_safe_message": "Provider retry attempts were exhausted.",
    },
    ErrorCode.PROVIDER_CIRCUIT_OPEN: {
        "category": "provider",
        "default_http_status": HTTPStatus.SERVICE_UNAVAILABLE,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Provider circuit open",
        "default_safe_message": "Provider circuit breaker is open.",
    },
    ErrorCode.DELIVERY_SNAPSHOT_MISSING: {
        "category": "delivery",
        "default_http_status": HTTPStatus.CONFLICT,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Delivery snapshot missing",
        "default_safe_message": "Delivery snapshot is missing.",
    },
    ErrorCode.DELIVERY_SNAPSHOT_NOT_READY: {
        "category": "delivery",
        "default_http_status": HTTPStatus.CONFLICT,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Delivery snapshot not ready",
        "default_safe_message": "Delivery snapshot is not ready.",
    },
    ErrorCode.DELIVERY_GIT_CLI_FAILED: {
        "category": "delivery",
        "default_http_status": HTTPStatus.FAILED_DEPENDENCY,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Delivery Git CLI failed",
        "default_safe_message": "Git delivery command failed.",
    },
    ErrorCode.DELIVERY_REMOTE_REQUEST_FAILED: {
        "category": "delivery",
        "default_http_status": HTTPStatus.BAD_GATEWAY,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Delivery remote request failed",
        "default_safe_message": "Remote delivery request failed.",
    },
    ErrorCode.RUNTIME_DATA_DIR_UNAVAILABLE: {
        "category": "runtime",
        "default_http_status": HTTPStatus.SERVICE_UNAVAILABLE,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Runtime data directory unavailable",
        "default_safe_message": "Runtime data directory is unavailable.",
    },
    ErrorCode.AUDIT_WRITE_FAILED: {
        "category": "audit",
        "default_http_status": HTTPStatus.SERVICE_UNAVAILABLE,
        "retryable": True,
        "user_visible": True,
        "default_safe_title": "Audit write failed",
        "default_safe_message": "Audit record could not be written.",
    },
    ErrorCode.LOG_QUERY_INVALID: {
        "category": "log",
        "default_http_status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Log query invalid",
        "default_safe_message": "Log query is invalid.",
    },
    ErrorCode.LOG_PAYLOAD_BLOCKED: {
        "category": "log",
        "default_http_status": HTTPStatus.FORBIDDEN,
        "retryable": False,
        "user_visible": True,
        "default_safe_title": "Log payload blocked",
        "default_safe_message": "Log payload was blocked by redaction policy.",
    },
}


def _coerce_error_code(error_code: ErrorCode | str) -> ErrorCode:
    try:
        return error_code if isinstance(error_code, ErrorCode) else ErrorCode(error_code)
    except ValueError as exc:
        raise ValueError(f"Unknown error_code: {error_code!r}") from exc


def lookup_error_code(error_code: ErrorCode | str) -> ErrorCatalogEntry:
    resolved = _coerce_error_code(error_code)
    try:
        row = _ERROR_CATALOG_ROWS[resolved]
    except KeyError as exc:
        raise ValueError(f"Error code is not registered: {resolved.value}") from exc

    from backend.app.schemas.errors import ErrorCatalogEntry

    return ErrorCatalogEntry(error_code=resolved, **row)


def assert_error_code_registered(error_code: ErrorCode | str) -> ErrorCode:
    return lookup_error_code(error_code).error_code
