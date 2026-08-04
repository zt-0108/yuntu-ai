from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.observability import get_request_id


logger = logging.getLogger(__name__)


def _response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": get_request_id(),
    }
    if details:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    return [
        {
            "location": list(item.get("loc", ())),
            "message": item.get("msg", "Invalid value"),
            "type": item.get("type", "validation_error"),
        }
        for item in exc.errors()
    ]


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _response(
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=_safe_validation_errors(exc),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = str(exc.detail)
        if exc.status_code >= 500:
            code = "upstream_service_error" if exc.status_code == 502 else "service_error"
            message = "The requested service is temporarily unavailable."
        return _response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_request_error error_type=%s", type(exc).__name__)
        return _response(
            status_code=500,
            code="internal_error",
            message="An unexpected server error occurred.",
        )
