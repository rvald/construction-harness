"""Single, consistent error envelope for every endpoint.

Shape: ``{"error": {"code", "message", "request_id"}}``. Messy documents are NOT errors —
they come back as job status + flagged records; only genuine faults reach here.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """Raise for a controlled, client-facing failure with a stable code."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def _envelope(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": _request_id(request)}},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _envelope(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return _envelope(request, 422, "validation_error", str(exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return _envelope(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak internals or document contents into the response body.
        return _envelope(request, 500, "internal_error", "An unexpected error occurred.")
