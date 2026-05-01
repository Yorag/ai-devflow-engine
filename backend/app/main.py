from fastapi import FastAPI

from backend.app import __version__
from backend.app.api.errors import register_error_handlers
from backend.app.api.router import build_api_router
from backend.app.core.config import APP_TITLE, DOCS_URL, OPENAPI_URL


def create_app() -> FastAPI:
    app = FastAPI(title=APP_TITLE, version=__version__, openapi_url=OPENAPI_URL, docs_url=DOCS_URL)
    register_error_handlers(app)
    app.include_router(build_api_router())
    return app


app = create_app()
