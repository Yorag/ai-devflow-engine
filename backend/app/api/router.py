from fastapi import APIRouter

from backend.app.api.routes import (
    health,
    projects,
    providers,
    runtime_settings,
    sessions,
    templates,
)
from backend.app.core.config import API_PREFIX


def build_api_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(health.router)
    router.include_router(projects.router)
    router.include_router(sessions.router)
    router.include_router(templates.router)
    router.include_router(providers.router)
    router.include_router(runtime_settings.router)
    return router
