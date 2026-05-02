from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.main import create_app


def test_health_returns_service_status_and_request_id() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/api/health",
        headers={
            "X-Request-ID": "req-health-1",
            "X-Correlation-ID": "corr-health-1",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-health-1"
    assert response.headers["x-correlation-id"] == "corr-health-1"
    assert response.headers["x-trace-id"]
    assert response.json() == {
        "status": "ok",
        "service": "ai-devflow-engine",
        "version": "0.1.0",
    }


def test_api_docs_and_openapi_are_served_under_api_prefix() -> None:
    client = TestClient(create_app())

    openapi_response = client.get("/api/openapi.json")
    docs_response = client.get("/api/docs")

    assert openapi_response.status_code == 200
    assert docs_response.status_code == 200


def test_allowed_frontend_origin_can_access_api_with_cors_headers(tmp_path) -> None:
    app = create_app(
        settings=EnvironmentSettings(
            platform_runtime_root=tmp_path / "runtime",
            backend_cors_origins=("http://localhost:5173",),
        )
    )
    client = TestClient(app)

    preflight_response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Request-ID",
        },
    )
    get_response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})

    assert preflight_response.status_code == 200
    assert preflight_response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert get_response.status_code == 200
    assert get_response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_openapi_documents_health_route_and_error_response() -> None:
    client = TestClient(create_app())

    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    health_operation = document["paths"]["/api/health"]["get"]

    assert "200" in health_operation["responses"]
    assert "500" in health_operation["responses"]
    assert (
        health_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/HealthResponse"
    )
    assert (
        health_operation["responses"]["500"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )

    schemas = document["components"]["schemas"]
    assert set(schemas["HealthResponse"]["required"]) == {"status", "service", "version"}
    assert set(schemas["ErrorResponse"]["required"]) == {
        "error_code",
        "message",
        "request_id",
        "correlation_id",
    }
