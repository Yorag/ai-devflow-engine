from collections.abc import Awaitable, Callable
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from backend.app.api.error_codes import ErrorCode


REQUEST_ID_HEADER = "X-Request-ID"


class ErrorResponse(BaseModel):
    error_code: ErrorCode = Field(..., description="Stable machine-readable error code.")
    message: str = Field(..., description="Human-readable error summary.")
    request_id: str = Field(..., description="Request correlation identifier.")


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
    return str(uuid4())


def build_error_response(
    status_code: int,
    error_code: ErrorCode,
    message: str,
    request: Request,
) -> JSONResponse:
    request_id = get_request_id(request)
    payload = ErrorResponse(error_code=error_code, message=message, request_id=request_id)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={REQUEST_ID_HEADER: request_id},
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
    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

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
