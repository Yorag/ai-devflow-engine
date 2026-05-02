from fastapi import Request
from fastapi.testclient import TestClient

from backend.app.domain.trace_context import TraceContext
from backend.app.main import create_app


def test_request_correlation_middleware_inherits_headers_and_exposes_trace_context() -> None:
    app = create_app()

    @app.get("/api/test-trace-context", include_in_schema=False)
    async def read_trace_context(request: Request) -> dict[str, str | None]:
        from backend.app.observability.context import get_trace_context

        context = get_trace_context()
        state_context = request.state.trace_context
        child = context.child_span(span_id="span-service-1", created_at=context.created_at)

        assert isinstance(state_context, TraceContext)
        assert state_context == context
        assert child.request_id == context.request_id
        assert child.trace_id == context.trace_id
        assert child.correlation_id == context.correlation_id
        assert child.parent_span_id == context.span_id

        return {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "correlation_id": context.correlation_id,
            "span_id": context.span_id,
            "parent_span_id": context.parent_span_id,
            "child_parent_span_id": child.parent_span_id,
        }

    client = TestClient(app)

    response = client.get(
        "/api/test-trace-context",
        headers={
            "X-Request-ID": "request-from-client",
            "X-Correlation-ID": "correlation-from-client",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "request-from-client"
    assert body["correlation_id"] == "correlation-from-client"
    assert body["trace_id"]
    assert body["span_id"]
    assert body["parent_span_id"] is None
    assert body["child_parent_span_id"] == body["span_id"]
    assert response.headers["x-request-id"] == "request-from-client"
    assert response.headers["x-correlation-id"] == "correlation-from-client"
    assert response.headers["x-trace-id"] == body["trace_id"]


def test_request_correlation_middleware_generates_missing_identifiers() -> None:
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.headers["x-correlation-id"]
    assert response.headers["x-trace-id"]
    assert response.headers["x-request-id"] != response.headers["x-correlation-id"]


def test_get_trace_context_is_request_scoped_and_unavailable_after_response() -> None:
    app = create_app()
    seen_contexts: list[str] = []

    @app.get("/api/test-context-scope", include_in_schema=False)
    async def read_context_scope() -> dict[str, str]:
        from backend.app.observability.context import get_trace_context

        context = get_trace_context()
        seen_contexts.append(context.request_id)
        return {"request_id": context.request_id}

    client = TestClient(app)

    first = client.get("/api/test-context-scope", headers={"X-Request-ID": "request-1"})
    second = client.get("/api/test-context-scope", headers={"X-Request-ID": "request-2"})

    assert first.json() == {"request_id": "request-1"}
    assert second.json() == {"request_id": "request-2"}
    assert seen_contexts == ["request-1", "request-2"]

    from backend.app.observability.context import get_trace_context

    try:
        get_trace_context()
    except RuntimeError as exc:
        assert "TraceContext is not available" in str(exc)
    else:
        raise AssertionError("get_trace_context must fail outside a request")
