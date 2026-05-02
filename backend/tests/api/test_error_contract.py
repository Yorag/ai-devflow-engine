from fastapi import Query
from fastapi.testclient import TestClient

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError
from backend.app.main import create_app


def test_api_error_uses_stable_code_message_and_request_id() -> None:
    app = create_app()

    @app.get("/api/test-error", include_in_schema=False)
    async def raise_test_error() -> None:
        raise ApiError(
            error_code=ErrorCode.CONFIG_INVALID_VALUE,
            message="Configuration value is invalid.",
            status_code=422,
        )

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/test-error",
        headers={
            "X-Request-ID": "req-error-1",
            "X-Correlation-ID": "corr-error-1",
        },
    )

    assert response.status_code == 422
    assert response.headers["x-request-id"] == "req-error-1"
    assert response.json() == {
        "error_code": "config_invalid_value",
        "message": "Configuration value is invalid.",
        "request_id": "req-error-1",
        "correlation_id": "corr-error-1",
    }


def test_http_errors_use_unified_response_contract() -> None:
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.get(
        "/api/missing",
        headers={
            "X-Request-ID": "req-missing-1",
            "X-Correlation-ID": "corr-missing-1",
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Not Found",
        "request_id": "req-missing-1",
        "correlation_id": "corr-missing-1",
    }


def test_validation_errors_use_unified_response_contract() -> None:
    app = create_app()

    @app.get("/api/test-validation", include_in_schema=False)
    async def read_test_validation(limit: int = Query(...)) -> dict[str, int]:
        return {"limit": limit}

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/test-validation",
        params={"limit": "not-a-number"},
        headers={
            "X-Request-ID": "req-validation-1",
            "X-Correlation-ID": "corr-validation-1",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "error_code": "validation_error",
        "message": "Request validation failed.",
        "request_id": "req-validation-1",
        "correlation_id": "corr-validation-1",
    }


def test_unhandled_errors_do_not_leak_stack_or_exception_text() -> None:
    app = create_app()

    @app.get("/api/test-unhandled", include_in_schema=False)
    async def raise_unhandled_error() -> None:
        raise RuntimeError("do not leak this runtime detail")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/test-unhandled",
        headers={
            "X-Request-ID": "req-500-1",
            "X-Correlation-ID": "corr-500-1",
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "internal_error",
        "message": "Internal server error.",
        "request_id": "req-500-1",
        "correlation_id": "corr-500-1",
    }
    assert "do not leak" not in response.text
    assert "Traceback" not in response.text


def test_error_code_dictionary_reserves_config_codes_for_later_slices() -> None:
    reserved_codes = {
        ErrorCode.CONFIG_INVALID_VALUE,
        ErrorCode.CONFIG_HARD_LIMIT_EXCEEDED,
        ErrorCode.CONFIG_VERSION_CONFLICT,
        ErrorCode.CONFIG_STORAGE_UNAVAILABLE,
        ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
        ErrorCode.CONFIG_CREDENTIAL_ENV_NOT_ALLOWED,
    }

    assert {code.value for code in reserved_codes} == {
        "config_invalid_value",
        "config_hard_limit_exceeded",
        "config_version_conflict",
        "config_storage_unavailable",
        "config_snapshot_unavailable",
        "config_credential_env_not_allowed",
    }
