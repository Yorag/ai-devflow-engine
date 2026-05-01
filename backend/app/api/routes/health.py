from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app import __version__
from backend.app.api.errors import ErrorResponse
from backend.app.core.config import SERVICE_NAME


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={500: {"model": ErrorResponse, "description": "Internal server error"}},
)
async def get_health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME, version=__version__)
