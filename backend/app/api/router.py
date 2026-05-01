from fastapi import APIRouter

from backend.app.api.routes import health
from backend.app.core.config import API_PREFIX


def build_api_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(health.router)
    return router
