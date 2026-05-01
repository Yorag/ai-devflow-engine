from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import __version__
from backend.app.api.errors import register_error_handlers
from backend.app.api.router import build_api_router
from backend.app.core.config import APP_TITLE, DOCS_URL, OPENAPI_URL, EnvironmentSettings
from backend.app.observability.context import RequestCorrelationMiddleware
from backend.app.observability.runtime_data import RuntimeDataPreflight


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    RuntimeDataPreflight.from_environment_settings(
        app.state.environment_settings
    ).ensure_runtime_data_ready()
    yield


def create_app(settings: EnvironmentSettings | None = None) -> FastAPI:
    environment_settings = settings or EnvironmentSettings()
    app = FastAPI(
        title=APP_TITLE,
        version=__version__,
        openapi_url=OPENAPI_URL,
        docs_url=DOCS_URL,
        lifespan=lifespan,
    )
    app.state.environment_settings = environment_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(environment_settings.backend_cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestCorrelationMiddleware)
    register_error_handlers(app)
    app.include_router(build_api_router())
    return app


app = create_app()
