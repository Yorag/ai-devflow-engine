from fastapi import APIRouter

from backend.app.api.routes import (
    approvals,
    audit_logs,
    health,
    projects,
    providers,
    query,
    runtime_settings,
    runs,
    sessions,
    templates,
    tool_confirmations,
)
from backend.app.core.config import API_PREFIX


def build_api_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(health.router)
    router.include_router(projects.router)
    router.include_router(sessions.router)
    router.include_router(runs.router)
    router.include_router(approvals.router)
    router.include_router(tool_confirmations.router)
    router.include_router(templates.router)
    router.include_router(providers.router)
    router.include_router(runtime_settings.router)
    router.include_router(query.router)
    router.include_router(audit_logs.router)
    return router
