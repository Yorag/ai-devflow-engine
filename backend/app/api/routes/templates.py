from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.db.base import DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.observability.audit import AuditService
from backend.app.observability.context import get_trace_context
from backend.app.observability.log_writer import JsonlLogWriter
from backend.app.observability.runtime_data import RuntimeDataSettings
from backend.app.schemas.template import PipelineTemplateRead
from backend.app.services.templates import TemplateService


router = APIRouter(tags=["pipeline-templates"])


def _pipeline_template_read(template: Any) -> PipelineTemplateRead:
    return PipelineTemplateRead.model_validate(
        {
            "template_id": template.template_id,
            "name": template.name,
            "description": template.description,
            "template_source": template.template_source,
            "base_template_id": template.base_template_id,
            "fixed_stage_sequence": template.fixed_stage_sequence,
            "stage_role_bindings": template.stage_role_bindings,
            "approval_checkpoints": template.approval_checkpoints,
            "auto_regression_enabled": template.auto_regression_enabled,
            "max_auto_regression_retries": template.max_auto_regression_retries,
            "created_at": template.created_at,
            "updated_at": template.updated_at,
        }
    )


def get_control_session(request: Request) -> Iterator[Session]:
    manager: DatabaseManager = request.app.state.database_manager
    session = manager.session(DatabaseRole.CONTROL)
    try:
        yield session
    finally:
        session.close()


def get_template_service(
    request: Request,
    session: Session = Depends(get_control_session),
) -> Iterator[TemplateService]:
    manager: DatabaseManager = request.app.state.database_manager
    settings = request.app.state.environment_settings
    log_session = manager.session(DatabaseRole.LOG)
    audit_writer = JsonlLogWriter(RuntimeDataSettings.from_environment_settings(settings))
    audit_service = AuditService(log_session, audit_writer=audit_writer)
    try:
        yield TemplateService(
            session,
            audit_service=audit_service,
        )
    finally:
        log_session.close()


@router.get(
    "/pipeline-templates",
    response_model=list[PipelineTemplateRead],
    responses={500: {"model": ErrorResponse}},
)
def list_pipeline_templates(
    service: TemplateService = Depends(get_template_service),
) -> list[PipelineTemplateRead]:
    templates = service.list_templates(trace_context=get_trace_context())
    return [_pipeline_template_read(template) for template in templates]


@router.get(
    "/pipeline-templates/{templateId}",
    response_model=PipelineTemplateRead,
    responses={
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_pipeline_template(
    templateId: str,
    service: TemplateService = Depends(get_template_service),
) -> PipelineTemplateRead:
    template = service.get_template(
        templateId,
        trace_context=get_trace_context(),
    )
    if template is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Pipeline template was not found.",
            404,
        )
    return _pipeline_template_read(template)
