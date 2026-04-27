from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import api_router
from core.config import Settings, load_settings
from core.logging import configure_logging
from db.session import create_database_manager
from services import AppServices, build_services


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    database = create_database_manager(settings.resolved_database_url)
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    app.state.db = database
    app.state.http_client = http_client
    app.state.services = app.state.services_factory(settings, http_client)

    try:
        yield
    finally:
        await http_client.aclose()
        await database.engine.dispose()


def create_app(
    settings: Settings | None = None,
    services_factory: Callable[[Settings, httpx.AsyncClient], AppServices] = build_services,
) -> FastAPI:
    active_settings = settings or load_settings()
    app = FastAPI(title=active_settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = active_settings
    app.state.services_factory = services_factory

    if active_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=active_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": active_settings.app_env}

    app.include_router(api_router)
    return app


app = create_app()
