from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mandate_core.domain.errors import MandateCoreError

from apps.api.config import Settings
from apps.api.dependencies import AppContainer, build_container
from apps.api.routers import (
    auth,
    cases,
    catalog,
    commands,
    demo_lab,
    email_pack,
    integrations,
    ledger,
    mandates,
    webhooks,
)
from apps.api.routers.integrations import integration_flags
from apps.api.schemas import HealthResponse, ReadyResponse


async def _recheck_worker_loop(container: AppContainer, stop_event: asyncio.Event) -> None:
    interval = max(1, container.settings.recheck_poll_interval_seconds)
    while not stop_event.is_set():
        try:
            await container.orchestrator.process_due_recheck_jobs(limit=10)
            await container.orchestrator.sweep_open_cases()
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue


def create_app(
    settings: Settings | None = None,
    *,
    container_override: AppContainer | None = None,
) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = container_override or build_container(cfg)
        await container.store.init_schema()
        app.state.container = container

        stop_event = asyncio.Event()
        worker_task = asyncio.create_task(_recheck_worker_loop(container, stop_event))
        try:
            yield
        finally:
            stop_event.set()
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            await container.store.dispose()

    app = FastAPI(
        title="Mandate Core & Mandate Shop API",
        version="1.0.0",
        description=(
            "Deterministic spending firewall, state machine, snapshot merger, "
            "PayPal Orders v2 enforcement, and tamper-evident SHA-256 audit ledger."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(MandateCoreError)
    async def core_error_handler(_request: Request, exc: MandateCoreError) -> JSONResponse:
        body: dict[str, Any] = {
            "error": {
                "code": exc.code,
                "message": str(exc),
            }
        }
        if exc.details is not None:
            body["error"]["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.get("/health", tags=["Health"], response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="mandate-api")

    @app.get("/ready", tags=["Health"], response_model=ReadyResponse)
    async def ready(request: Request) -> ReadyResponse:
        c: AppContainer = request.app.state.container
        return ReadyResponse(
            status="ready",
            paypal_mode=c.settings.paypal_mode,
            catalog_provider=c.settings.catalog_provider,
            llm_provider=c.settings.llm_provider if c.llm else "deterministic",
            notifier_provider=c.settings.notifier_provider,
            integrations_configured=integration_flags(c),
        )

    app.include_router(auth.router)
    app.include_router(commands.router)
    app.include_router(mandates.router)
    app.include_router(cases.router)
    app.include_router(catalog.router)
    app.include_router(ledger.router)
    app.include_router(webhooks.router)
    app.include_router(integrations.router)
    app.include_router(demo_lab.router)
    app.include_router(email_pack.router)

    return app


app = create_app()
