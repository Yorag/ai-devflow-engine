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
