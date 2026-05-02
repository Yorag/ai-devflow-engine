from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import __version__
from backend.app.api.errors import register_error_handlers
from backend.app.api.router import build_api_router
from backend.app.core.config import APP_TITLE, DOCS_URL, OPENAPI_URL, EnvironmentSettings
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.domain.trace_context import TraceContext
from backend.app.observability.audit import AuditService
from backend.app.observability.context import RequestCorrelationMiddleware
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataPreflight, RuntimeDataSettings
from backend.app.services.providers import ProviderService
from backend.app.services.projects import ProjectService
from backend.app.services.templates import TemplateService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    RuntimeDataPreflight.from_environment_settings(
        app.state.environment_settings
    ).ensure_runtime_data_ready()
    app.state.database_manager.initialize_schema()
    ensure_startup_default_project(app)
    ensure_startup_control_plane_seed(app)
    yield


def _startup_trace_context() -> TraceContext:
    return TraceContext(
        request_id=f"startup-request-{uuid4().hex}",
        trace_id=f"startup-trace-{uuid4().hex}",
        correlation_id=f"startup-correlation-{uuid4().hex}",
        span_id=f"startup-span-{uuid4().hex}",
        parent_span_id=None,
        created_at=datetime.now(UTC),
    )


def ensure_startup_default_project(app: FastAPI) -> None:
    settings = app.state.environment_settings
    manager: DatabaseManager = app.state.database_manager
    control_session = manager.session(DatabaseRole.CONTROL)
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    try:
        ProjectService(
            control_session,
            settings=settings,
            audit_service=AuditService(log_session, audit_writer=audit_writer),
        ).ensure_default_project(trace_context=_startup_trace_context())
    finally:
        control_session.close()
        log_session.close()


def ensure_startup_control_plane_seed(app: FastAPI) -> None:
    settings = app.state.environment_settings
    manager: DatabaseManager = app.state.database_manager
    control_session = manager.session(DatabaseRole.CONTROL)
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    trace_context = _startup_trace_context()
    try:
        ProviderService(
            control_session,
            audit_service=audit_service,
        ).seed_builtin_providers(trace_context=trace_context)
        TemplateService(
            control_session,
            audit_service=audit_service,
        ).seed_system_templates(trace_context=trace_context)
    finally:
        control_session.close()
        log_session.close()


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
    app.state.database_manager = DatabaseManager.from_environment_settings(
        environment_settings
    )
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
