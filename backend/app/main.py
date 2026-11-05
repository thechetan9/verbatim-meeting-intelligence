"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, meetings, tracker
from app.config import Settings, get_settings
from app.container import Container, build_container
from app.observability import configure_logging, log_event, new_request_id, request_id_var

logger = logging.getLogger("app.http")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    configure_logging(settings.log_level, settings.log_json)
    container = container or build_container(settings)

    app = FastAPI(
        title="Verbatim — Meeting Intelligence API",
        version="0.1.0",
        description="Ask questions about meeting transcripts; answers are cited to the exact moment.",
    )
    app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = (request.headers.get("X-Request-ID") or new_request_id())[:64]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            if request.url.path != "/api/health":
                log_event(
                    logger,
                    "http.request",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    ms=round((time.perf_counter() - started) * 1000, 1),
                )
            return response
        finally:
            request_id_var.reset(token)

    app.include_router(meetings.router)
    app.include_router(chat.router)
    app.include_router(tracker.router)
    log_event(
        logging.getLogger("app"),
        "app.started",
        llm_enabled=container.llm is not None,
        model=container.llm.model if container.llm else None,
        database=settings.database_path,
    )
    return app


def app_factory() -> FastAPI:  # used by `uvicorn app.main:app_factory --factory`
    return create_app()
