from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.app.domain.trace_context import TraceContext


REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"
TRACE_ID_HEADER = "X-Trace-ID"

_current_trace_context: ContextVar[TraceContext | None] = ContextVar(
    "current_trace_context",
    default=None,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def build_request_trace_context(request: Request) -> TraceContext:
    request_id = request.headers.get(REQUEST_ID_HEADER) or _new_id("request")
    correlation_id = request.headers.get(CORRELATION_ID_HEADER) or _new_id("correlation")
    trace_id = request.headers.get(TRACE_ID_HEADER) or _new_id("trace")
    return TraceContext(
        request_id=request_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        span_id=_new_id("span"),
        parent_span_id=None,
        created_at=datetime.now(UTC),
    )


def get_trace_context() -> TraceContext:
    trace_context = _current_trace_context.get()
    if trace_context is None:
        raise RuntimeError("TraceContext is not available outside an API request context.")
    return trace_context


def set_trace_context(trace_context: TraceContext) -> Token[TraceContext | None]:
    return _current_trace_context.set(trace_context)


def reset_trace_context(token: Token[TraceContext | None]) -> None:
    _current_trace_context.reset(token)


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        trace_context = build_request_trace_context(request)
        request.state.trace_context = trace_context
        request.state.request_id = trace_context.request_id
        request.state.correlation_id = trace_context.correlation_id
        token = set_trace_context(trace_context)
        try:
            response = await call_next(request)
        finally:
            reset_trace_context(token)

        response.headers[REQUEST_ID_HEADER] = trace_context.request_id
        response.headers[CORRELATION_ID_HEADER] = trace_context.correlation_id
        response.headers[TRACE_ID_HEADER] = trace_context.trace_id
        return response


__all__ = [
    "CORRELATION_ID_HEADER",
    "REQUEST_ID_HEADER",
    "TRACE_ID_HEADER",
    "RequestCorrelationMiddleware",
    "build_request_trace_context",
    "get_trace_context",
    "reset_trace_context",
    "set_trace_context",
]
