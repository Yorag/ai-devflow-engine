from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.error_codes import ErrorCode
from backend.app.observability.context import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    TRACE_ID_HEADER,
)


class ErrorResponse(BaseModel):
    error_code: ErrorCode = Field(..., description="Stable machine-readable error code.")
    message: str = Field(..., description="Human-readable error summary.")
    request_id: str = Field(..., description="Request correlation identifier.")
    correlation_id: str = Field(..., description="User action or command correlation identifier.")


class ApiError(Exception):
    def __init__(self, error_code: ErrorCode, message: str, status_code: int = 400) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return request.headers.get(REQUEST_ID_HEADER) or str(uuid4())


def get_correlation_id(request: Request) -> str:
    correlation_id = getattr(request.state, "correlation_id", None)
    if isinstance(correlation_id, str) and correlation_id:
        return correlation_id
    return request.headers.get(CORRELATION_ID_HEADER) or get_request_id(request)


def get_trace_id(request: Request) -> str | None:
    trace_context = getattr(request.state, "trace_context", None)
    trace_id = getattr(trace_context, "trace_id", None)
    if isinstance(trace_id, str) and trace_id:
        return trace_id
    return request.headers.get(TRACE_ID_HEADER)


def build_error_response(
    status_code: int,
    error_code: ErrorCode,
    message: str,
    request: Request,
) -> JSONResponse:
    request_id = get_request_id(request)
    correlation_id = get_correlation_id(request)
    payload = ErrorResponse(
        error_code=error_code,
        message=message,
        request_id=request_id,
        correlation_id=correlation_id,
    )
    headers = {
        REQUEST_ID_HEADER: request_id,
        CORRELATION_ID_HEADER: correlation_id,
    }
    if trace_id := get_trace_id(request):
        headers[TRACE_ID_HEADER] = trace_id
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=headers,
    )


def _http_error_code(status_code: int) -> ErrorCode:
    if status_code == status.HTTP_404_NOT_FOUND:
        return ErrorCode.NOT_FOUND
    return ErrorCode.INTERNAL_ERROR if status_code >= 500 else ErrorCode.VALIDATION_ERROR


def _http_error_message(status_code: int, detail: object) -> str:
    if isinstance(detail, str) and detail:
        return detail
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP error"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return build_error_response(exc.status_code, exc.error_code, exc.message, request)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return build_error_response(
            422,
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed.",
            request,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return build_error_response(
            exc.status_code,
            _http_error_code(exc.status_code),
            _http_error_message(exc.status_code, exc.detail),
            request,
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        return build_error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorCode.INTERNAL_ERROR,
            "Internal server error.",
            request,
        )
