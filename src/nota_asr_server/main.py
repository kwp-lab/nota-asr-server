from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from nota_asr_server import __version__
from nota_asr_server.api.batch_routes import router as batch_router
from nota_asr_server.api.routes import router
from nota_asr_server.config import Settings
from nota_asr_server.errors import APIError
from nota_asr_server.schemas import ErrorDetail, ErrorEnvelope
from nota_asr_server.services.model_manager import ModelManager
from nota_asr_server.services.batch_jobs import BatchJobService


logger = logging.getLogger("nota_asr_server")


def _error_response(
    request: Request,
    *,
    status_code: int,
    error_type: str,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    payload = ErrorEnvelope(
        error=ErrorDetail(
            type=error_type,
            code=code,
            message=message,
            request_id=request_id,
        )
    )
    response_headers = {"X-Request-ID": request_id}
    response_headers.update(headers or {})
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers=response_headers,
    )


def create_app(
    settings: Settings | None = None,
    model_manager: ModelManager | None = None,
    batch_jobs: BatchJobService | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_settings.validate()
    manager = model_manager or ModelManager(resolved_settings)
    jobs = batch_jobs or BatchJobService(resolved_settings, manager)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await run_in_threadpool(manager.preload)
        except Exception:
            logger.exception("Default model preload failed")
        jobs.start()
        try:
            yield
        finally:
            await run_in_threadpool(jobs.stop)

    app = FastAPI(
        title="Nota ASR Server",
        version=__version__,
        description="OpenAI-compatible meeting transcription with stable diarization output.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.model_manager = manager
    app.state.batch_jobs = jobs

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            error_type=exc.error_type,
            code=exc.code,
            message=exc.message,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first_error = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(item) for item in first_error.get("loc", ()))
        message = first_error.get("msg", "Request validation failed")
        if location:
            message = f"{location}: {message}"
        return _error_response(
            request,
            status_code=422,
            error_type="invalid_request_error",
            code="validation_error",
            message=message,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request failure", exc_info=exc)
        return _error_response(
            request,
            status_code=500,
            error_type="server_error",
            code="internal_error",
            message="The server could not process the request",
        )

    app.include_router(router)
    app.include_router(batch_router)
    return app


app = create_app()
