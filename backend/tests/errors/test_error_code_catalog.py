from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.error_codes import (
    ErrorCode,
    assert_error_code_registered,
    lookup_error_code,
)
from backend.app.api.errors import ApiError
from backend.app.domain.trace_context import TraceContext
from backend.app.main import create_app
from backend.app.schemas.errors import ApiErrorResponse, ErrorCategory
from backend.app.tools.protocol import ToolError


REQUIRED_W5_0A_CODES = {
    "tool_unknown",
    "tool_not_allowed",
    "tool_input_schema_invalid",
    "tool_workspace_boundary_violation",
    "tool_timeout",
    "tool_audit_required_failed",
    "tool_confirmation_required",
    "tool_confirmation_denied",
    "tool_confirmation_not_actionable",
    "tool_risk_blocked",
    "bash_command_not_allowed",
    "provider_retry_exhausted",
    "provider_circuit_open",
    "delivery_snapshot_missing",
    "delivery_snapshot_not_ready",
    "delivery_git_cli_failed",
    "delivery_remote_request_failed",
    "runtime_data_dir_unavailable",
    "audit_write_failed",
    "log_query_invalid",
    "log_payload_blocked",
    "config_snapshot_mutation_blocked",
}


def test_error_catalog_registers_w5_0a_codes_with_safe_metadata() -> None:
    registered_values = {code.value for code in ErrorCode}

    assert REQUIRED_W5_0A_CODES <= registered_values
    for code_value in REQUIRED_W5_0A_CODES:
        entry = lookup_error_code(code_value)
        assert entry.error_code.value == code_value
        assert entry.category in set(ErrorCategory)
        assert 400 <= entry.default_http_status <= 599
        assert entry.default_safe_title
        assert entry.default_safe_message
        assert "Traceback" not in entry.default_safe_message
        assert "API Key" not in entry.default_safe_message
        assert assert_error_code_registered(code_value) is entry.error_code

    assert lookup_error_code(ErrorCode.TOOL_UNKNOWN).category is ErrorCategory.TOOL
    assert lookup_error_code(ErrorCode.PROVIDER_RETRY_EXHAUSTED).retryable is True
    assert lookup_error_code(ErrorCode.TOOL_RISK_BLOCKED).user_visible is True


def test_error_catalog_registers_every_error_code_member() -> None:
    for code in ErrorCode:
        entry = lookup_error_code(code)
        assert entry.error_code is code


def test_api_error_response_rejects_unregistered_or_sensitive_error_contract() -> None:
    with pytest.raises(ValueError, match="Unknown error_code"):
        assert_error_code_registered("not_registered")

    with pytest.raises(ValidationError, match="sensitive"):
        ApiErrorResponse(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Traceback leaked",
            request_id="request-1",
            correlation_id="correlation-1",
        )

    with pytest.raises(ValidationError, match="sensitive"):
        ApiErrorResponse(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="api_key leaked",
            request_id="request-1",
            correlation_id="correlation-1",
        )


def test_api_error_response_allows_safe_public_field_names() -> None:
    response = ApiErrorResponse(
        error_code=ErrorCode.CONFIG_INVALID_VALUE,
        message="Provider api_key_ref is preserved as a configured secret.",
        request_id="request-1",
        correlation_id="correlation-1",
    )

    assert response.message == "Provider api_key_ref is preserved as a configured secret."


def test_api_errors_use_registered_code_and_optional_detail_ref() -> None:
    app = create_app()

    @app.get("/api/test-registered-error", include_in_schema=False)
    async def raise_registered_error() -> None:
        raise ApiError(
            error_code="tool_timeout",
            message="Tool execution timed out.",
            status_code=408,
            detail_ref="detail-tool-timeout-1",
        )

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/test-registered-error",
        headers={
            "X-Request-ID": "request-timeout-1",
            "X-Correlation-ID": "correlation-timeout-1",
            "X-Trace-ID": "trace-timeout-1",
        },
    )

    assert response.status_code == 408
    assert response.headers["x-trace-id"] == "trace-timeout-1"
    assert response.json() == {
        "error_code": "tool_timeout",
        "message": "Tool execution timed out.",
        "request_id": "request-timeout-1",
        "correlation_id": "correlation-timeout-1",
        "detail_ref": "detail-tool-timeout-1",
    }


def _trace_context() -> TraceContext:
    return TraceContext(
        request_id="request-tool-error-1",
        trace_id="trace-tool-error-1",
        correlation_id="correlation-tool-error-1",
        span_id="span-tool-error-1",
        parent_span_id=None,
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )


def test_tool_error_from_code_uses_catalog_defaults_and_trace_context() -> None:
    trace = _trace_context()

    error = ToolError.from_code(
        "tool_workspace_boundary_violation",
        trace_context=trace,
        safe_details={"path": "../outside.py"},
    )

    assert error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert error.safe_message == "Tool target is outside the run workspace."
    assert error.safe_details == {"path": "../outside.py"}
    assert error.trace_id == "trace-tool-error-1"
    assert error.correlation_id == "correlation-tool-error-1"
    assert error.span_id == "span-tool-error-1"
    assert "Traceback" not in str(error.model_dump(mode="json"))


def test_tool_error_rejects_unregistered_code_and_sensitive_details() -> None:
    trace = _trace_context()

    with pytest.raises(ValidationError):
        ToolError(
            error_code="not_registered",
            safe_message="Invalid tool error.",
            trace_context=trace,
        )

    with pytest.raises(ValueError, match="Unknown error_code"):
        ToolError.from_code("not_registered", trace_context=trace)

    with pytest.raises(ValidationError, match="sensitive"):
        ToolError.from_code(
            ErrorCode.TOOL_TIMEOUT,
            trace_context=trace,
            safe_details={"Authorization": "Bearer secret"},
        )


def test_tool_error_rejects_sensitive_message_and_nested_detail_terms() -> None:
    trace = _trace_context()

    with pytest.raises(ValidationError, match="sensitive"):
        ToolError.from_code(
            ErrorCode.TOOL_TIMEOUT,
            trace_context=trace,
            safe_message="Retry failed with password=abc123.",
        )

    with pytest.raises(ValidationError, match="sensitive"):
        ToolError.from_code(
            ErrorCode.TOOL_TIMEOUT,
            trace_context=trace,
            safe_details={"context": {"token": "redacted"}},
        )

    with pytest.raises(ValidationError, match="sensitive"):
        ToolError.from_code(
            ErrorCode.TOOL_TIMEOUT,
            trace_context=trace,
            safe_details={"context": "Authorization: Bearer secret"},
        )


def test_tool_error_allows_safe_public_field_names_in_message_and_details() -> None:
    trace = _trace_context()

    message_error = ToolError.from_code(
        ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
        trace_context=trace,
        safe_message=(
            "Provider api_key_ref is missing. max_output_tokens exceeds limit. "
            "token_count is above threshold."
        ),
    )
    details_error = ToolError.from_code(
        ErrorCode.TOOL_INPUT_SCHEMA_INVALID,
        trace_context=trace,
        safe_details={
            "field": "api_key_ref",
            "limit": "max_output_tokens exceeds limit.",
            "usage": {"summary": "token_count is above threshold."},
        },
    )

    assert message_error.safe_message == (
        "Provider api_key_ref is missing. max_output_tokens exceeds limit. "
        "token_count is above threshold."
    )
    assert details_error.safe_details["field"] == "api_key_ref"


def test_tool_error_rejects_credential_shaped_values_under_safe_keys() -> None:
    trace = _trace_context()

    with pytest.raises(ValidationError, match="sensitive"):
        ToolError.from_code(
            ErrorCode.TOOL_TIMEOUT,
            trace_context=trace,
            safe_details={"context": "Bearer abc123"},
        )


def test_tool_error_from_code_rejects_explicit_empty_safe_message() -> None:
    trace = _trace_context()

    with pytest.raises(ValidationError):
        ToolError.from_code(
            ErrorCode.TOOL_TIMEOUT,
            trace_context=trace,
            safe_message="",
        )
