from __future__ import annotations

import re
from collections.abc import Mapping

from fastapi.testclient import TestClient

from backend.app.api.error_codes import ErrorCode, lookup_error_code
from backend.app.domain.enums import (
    ApprovalType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    SessionStatus,
    StageStatus,
    StageType,
)
from backend.tests.api.test_approval_api import build_app as build_approval_app
from backend.tests.api.test_approval_api import seed_approval
from backend.tests.api.test_pause_resume_api import build_app as build_run_app
from backend.tests.api.test_pause_resume_api import seed_active_run_for_api
from backend.tests.api.test_rerun_command_api import (
    build_rerun_app,
    seed_rerunnable_run_for_api,
)


SENSITIVE_PATTERNS = (
    re.compile(r"Traceback"),
    re.compile(r"Authorization:", re.IGNORECASE),
    re.compile(r"Cookie:", re.IGNORECASE),
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"password\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"private key", re.IGNORECASE),
)

REQUIRED_RUNTIME_AND_TOOL_ERROR_CODES = {
    "approval_not_actionable",
    "run_command_not_actionable",
    "delivery_snapshot_not_ready",
    "runtime_data_dir_unavailable",
    "audit_write_failed",
    "log_query_invalid",
    "log_payload_blocked",
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
    "delivery_git_cli_failed",
    "delivery_remote_request_failed",
}


def assert_error_code_catalog_covers_runtime_and_tool_errors() -> None:
    registered = {code.value for code in ErrorCode}
    assert REQUIRED_RUNTIME_AND_TOOL_ERROR_CODES <= registered
    for code_value in REQUIRED_RUNTIME_AND_TOOL_ERROR_CODES:
        entry = lookup_error_code(code_value)
        assert entry.default_http_status in range(400, 600)
        assert entry.default_safe_title
        assert entry.default_safe_message
        assert not _contains_sensitive_text(entry.default_safe_message)


def assert_api_error_contract_stable(
    response,
    *,
    expected_error_code: str,
    expected_status: int,
) -> Mapping[str, object]:
    body = response.json()
    assert response.status_code == expected_status
    assert body["error_code"] == expected_error_code
    catalog = lookup_error_code(expected_error_code)
    assert response.status_code == catalog.default_http_status
    assert isinstance(body["message"], str) and body["message"]
    assert not _contains_sensitive_text(body["message"])
    assert body["request_id"] == "request-v66"
    assert body["correlation_id"] == "correlation-v66"
    assert response.headers["x-request-id"] == "request-v66"
    assert response.headers["x-correlation-id"] == "correlation-v66"
    assert response.headers["x-trace-id"] == "trace-v66"
    return body


def test_error_code_catalog_covers_v6_6_runtime_tool_provider_delivery_and_log_codes() -> None:
    assert_error_code_catalog_covers_runtime_and_tool_errors()


def test_paused_approval_submit_uses_stable_not_actionable_code(tmp_path) -> None:
    app = build_approval_app(tmp_path)
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
        stage_type=StageType.SOLUTION_DESIGN,
        run_status=RunStatus.PAUSED,
        session_status=SessionStatus.PAUSED,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/approvals/{approval_id}/approve",
            json={},
            headers=_trace_headers(),
        )

    body = assert_api_error_contract_stable(
        response,
        expected_error_code="approval_not_actionable",
        expected_status=409,
    )
    assert "paused" in str(body["message"])


def test_delivery_channel_not_ready_uses_stable_contract_code(tmp_path) -> None:
    app = build_approval_app(tmp_path)
    approval_id = seed_approval(
        app,
        approval_type=ApprovalType.CODE_REVIEW_APPROVAL,
        stage_type=StageType.CODE_REVIEW,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        readiness_status=DeliveryReadinessStatus.UNCONFIGURED,
        credential_status=CredentialStatus.UNBOUND,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/approvals/{approval_id}/approve",
            json={},
            headers=_trace_headers(),
        )

    body = assert_api_error_contract_stable(
        response,
        expected_error_code="delivery_snapshot_not_ready",
        expected_status=409,
    )
    assert body["detail_ref"] == approval_id


def test_illegal_rerun_uses_stable_run_command_not_actionable_code(tmp_path) -> None:
    app = build_rerun_app(tmp_path)
    seed_rerunnable_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/session-1/runs",
            json={},
            headers=_trace_headers(),
        )

    assert_api_error_contract_stable(
        response,
        expected_error_code="run_command_not_actionable",
        expected_status=409,
    )


def test_non_paused_resume_uses_stable_run_command_not_actionable_code(tmp_path) -> None:
    app = build_run_app(tmp_path)
    seed_active_run_for_api(
        app,
        run_status=RunStatus.RUNNING,
        session_status=SessionStatus.RUNNING,
        stage_status=StageStatus.RUNNING,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/runs/run-1/resume",
            json={},
            headers=_trace_headers(),
        )

    assert_api_error_contract_stable(
        response,
        expected_error_code="run_command_not_actionable",
        expected_status=409,
    )


def _trace_headers() -> dict[str, str]:
    return {
        "X-Request-ID": "request-v66",
        "X-Correlation-ID": "correlation-v66",
        "X-Trace-ID": "trace-v66",
    }


def _contains_sensitive_text(value: str) -> bool:
    return any(pattern.search(value) for pattern in SENSITIVE_PATTERNS)
