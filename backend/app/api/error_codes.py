from enum import StrEnum


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


class RuntimeSettingsErrorCode(StrEnum):
    CONFIG_INVALID_VALUE = ErrorCode.CONFIG_INVALID_VALUE.value
    CONFIG_HARD_LIMIT_EXCEEDED = ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED.value
    CONFIG_VERSION_CONFLICT = ErrorCode.CONFIG_VERSION_CONFLICT.value
    CONFIG_STORAGE_UNAVAILABLE = ErrorCode.CONFIG_STORAGE_UNAVAILABLE.value
    CONFIG_SNAPSHOT_UNAVAILABLE = ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE.value
