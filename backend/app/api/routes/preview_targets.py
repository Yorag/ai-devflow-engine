from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.api.routes.query import get_control_session, get_runtime_session
from backend.app.db.models.runtime import PipelineRunModel, StageArtifactModel
from backend.app.schemas.preview import PreviewTarget, PreviewTargetReference
from backend.app.services.publication_boundary import (
    PublicationBoundaryService,
    PublicationBoundaryServiceError,
)


class PreviewTargetServiceError(RuntimeError):
    def __init__(self, error_code: ErrorCode, message: str, status_code: int) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PreviewTargetService:
    def __init__(
        self,
        *,
        control_session: Session,
        runtime_session: Session,
    ) -> None:
        self._runtime_session = runtime_session
        self._publication_boundary = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
        )

    def get_preview_target(self, preview_target_id: str) -> PreviewTarget:
        artifact = self._runtime_session.get(StageArtifactModel, preview_target_id)
        if artifact is None or artifact.artifact_type != "preview_target":
            raise PreviewTargetServiceError(
                ErrorCode.NOT_FOUND,
                "Preview target was not found.",
                404,
            )

        try:
            self._publication_boundary.assert_run_visible(
                run_id=artifact.run_id,
                not_found_message="Preview target was not found.",
            )
        except PublicationBoundaryServiceError as exc:
            raise PreviewTargetServiceError(
                exc.error_code,
                exc.message,
                exc.status_code,
            ) from exc

        run = self._runtime_session.get(PipelineRunModel, artifact.run_id)
        if run is None:
            raise PreviewTargetServiceError(
                ErrorCode.NOT_FOUND,
                "Preview target was not found.",
                404,
            )

        process = artifact.process
        if not isinstance(process, dict):
            raise PreviewTargetServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Preview target is unavailable.",
                500,
            )
        target_type = process.get("target_type")
        reference_payload = process.get("reference")
        if not isinstance(target_type, str) or not target_type.strip():
            raise PreviewTargetServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Preview target is unavailable.",
                500,
            )
        if not isinstance(reference_payload, dict):
            raise PreviewTargetServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Preview target is unavailable.",
                500,
            )

        try:
            reference = PreviewTargetReference.model_validate(reference_payload)
        except ValidationError as exc:
            raise PreviewTargetServiceError(
                ErrorCode.INTERNAL_ERROR,
                "Preview target is unavailable.",
                500,
            ) from exc

        return PreviewTarget(
            preview_target_id=artifact.artifact_id,
            project_id=run.project_id,
            run_id=artifact.run_id,
            stage_run_id=artifact.stage_run_id,
            target_type=target_type.strip(),
            reference=reference,
            created_at=artifact.created_at,
        )


router = APIRouter(tags=["query"])


def get_preview_target_service(
    control_session: Session = Depends(get_control_session),
    runtime_session: Session = Depends(get_runtime_session),
) -> Iterator[PreviewTargetService]:
    yield PreviewTargetService(
        control_session=control_session,
        runtime_session=runtime_session,
    )


@router.get(
    "/preview-targets/{previewTargetId}",
    response_model=PreviewTarget,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_preview_target(
    previewTargetId: str,
    service: PreviewTargetService = Depends(get_preview_target_service),
) -> PreviewTarget:
    try:
        return service.get_preview_target(previewTargetId)
    except PreviewTargetServiceError as exc:
        raise ApiError(
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
        ) from exc
