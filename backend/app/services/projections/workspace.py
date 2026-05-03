from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import (
    DeliveryChannelModel,
    ProjectModel,
    SessionModel,
)
from backend.app.db.models.runtime import (
    PipelineRunModel,
    StageRunModel,
    ToolConfirmationRequestModel,
)
from backend.app.domain.enums import RunStatus, SessionStatus
from backend.app.schemas.delivery_channel import ProjectDeliveryChannelDetailProjection
from backend.app.schemas.feed import (
    ApprovalResultFeedEntry,
    TopLevelFeedEntry,
)
from backend.app.schemas.project import ProjectRead
from backend.app.schemas.run import ComposerStateProjection, RunSummaryProjection
from backend.app.schemas.session import SessionRead
from backend.app.schemas.workspace import SessionWorkspaceProjection
from backend.app.services.delivery_channels import DeliveryChannelService
from backend.app.services.events import DomainEvent, EventStore
from backend.app.services.publication_boundary import PublicationBoundaryService


TOP_LEVEL_FEED_ENTRY_ADAPTER = TypeAdapter(TopLevelFeedEntry)
WORKSPACE_NOT_FOUND_MESSAGE = "Session workspace was not found."


class WorkspaceProjectionServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class WorkspaceProjectionService:
    def __init__(
        self,
        control_session: Session,
        runtime_session: Session,
        event_session: Session,
        *,
        credential_env_prefixes: tuple[str, ...] | None = None,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._event_store = EventStore(event_session)
        self._publication_boundary = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
            event_session=event_session,
        )
        self._delivery_channel_service = DeliveryChannelService(
            control_session,
            credential_env_prefixes=credential_env_prefixes,
        )

    def get_session_workspace(self, session_id: str) -> SessionWorkspaceProjection:
        session = self._get_visible_session(session_id)
        project = self._get_visible_project(session.project_id)
        return SessionWorkspaceProjection(
            session=self._session_read(session),
            project=self._project_read(project),
            delivery_channel=self._delivery_channel_read(project),
            runs=self.build_run_summaries(session),
            narrative_feed=self._build_narrative_feed(session.session_id),
            current_run_id=session.current_run_id,
            current_stage_type=self._current_stage_type(session),
            composer_state=self.build_composer_state(session),
        )

    def build_composer_state(
        self,
        session: SessionModel,
    ) -> ComposerStateProjection:
        status = session.status
        terminal_statuses = {
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.TERMINATED,
        }
        if status is SessionStatus.DRAFT:
            return ComposerStateProjection(
                mode="draft",
                is_input_enabled=True,
                primary_action="send",
                secondary_actions=[],
                bound_run_id=None,
            )
        if status in terminal_statuses:
            return ComposerStateProjection(
                mode="readonly",
                is_input_enabled=False,
                primary_action="disabled",
                secondary_actions=[],
                bound_run_id=session.current_run_id,
            )
        if status is SessionStatus.WAITING_CLARIFICATION:
            return ComposerStateProjection(
                mode="waiting_clarification",
                is_input_enabled=True,
                primary_action="send",
                secondary_actions=["pause", "terminate"],
                bound_run_id=session.current_run_id,
            )
        if status is SessionStatus.PAUSED:
            return ComposerStateProjection(
                mode="paused",
                is_input_enabled=False,
                primary_action="resume",
                secondary_actions=["terminate"],
                bound_run_id=session.current_run_id,
            )
        return ComposerStateProjection(
            mode=status.value,
            is_input_enabled=False,
            primary_action="pause",
            secondary_actions=["terminate"],
            bound_run_id=session.current_run_id,
        )

    def build_run_summaries(
        self,
        session: SessionModel,
    ) -> list[RunSummaryProjection]:
        statement = (
            select(PipelineRunModel)
            .where(PipelineRunModel.session_id == session.session_id)
            .order_by(
                PipelineRunModel.started_at.asc(),
                PipelineRunModel.attempt_index.asc(),
                PipelineRunModel.run_id.asc(),
            )
        )
        hidden_run_ids = self._publication_boundary.hidden_run_ids_for_session(
            session_id=session.session_id
        )
        return [
            self._run_summary(run, session=session)
            for run in self._runtime_session.execute(statement).scalars().all()
            if run.run_id not in hidden_run_ids
        ]

    def _get_visible_session(self, session_id: str) -> SessionModel:
        session = self._control_session.get(SessionModel, session_id)
        if session is None or not session.is_visible:
            raise WorkspaceProjectionServiceError(
                ErrorCode.NOT_FOUND,
                WORKSPACE_NOT_FOUND_MESSAGE,
                404,
            )
        return session

    def _get_visible_project(self, project_id: str) -> ProjectModel:
        project = self._control_session.get(ProjectModel, project_id)
        if project is None or not project.is_visible:
            raise WorkspaceProjectionServiceError(
                ErrorCode.NOT_FOUND,
                WORKSPACE_NOT_FOUND_MESSAGE,
                404,
            )
        return project

    def _delivery_channel_read(
        self,
        project: ProjectModel,
    ) -> ProjectDeliveryChannelDetailProjection | None:
        if not project.default_delivery_channel_id:
            return None
        channel = self._control_session.get(
            DeliveryChannelModel,
            project.default_delivery_channel_id,
        )
        if channel is None or channel.project_id != project.project_id:
            return None
        return ProjectDeliveryChannelDetailProjection.model_validate(
            {
                "project_id": channel.project_id,
                "delivery_channel_id": channel.delivery_channel_id,
                "delivery_mode": channel.delivery_mode,
                "scm_provider_type": channel.scm_provider_type,
                "repository_identifier": channel.repository_identifier,
                "default_branch": channel.default_branch,
                "code_review_request_type": channel.code_review_request_type,
                "credential_ref": (
                    self._delivery_channel_service.credential_ref_for_projection(
                        channel.credential_ref
                    )
                ),
                "credential_status": channel.credential_status,
                "readiness_status": channel.readiness_status,
                "readiness_message": channel.readiness_message,
                "last_validated_at": self._projection_datetime(
                    channel.last_validated_at
                ),
                "updated_at": self._projection_datetime(channel.updated_at),
            }
        )

    def _build_narrative_feed(self, session_id: str) -> list[TopLevelFeedEntry]:
        entries: list[TopLevelFeedEntry] = []
        hidden_run_ids = self._publication_boundary.hidden_run_ids_for_session(
            session_id=session_id
        )
        for event in self._event_store.list_for_session(session_id):
            if event.run_id is not None and event.run_id in hidden_run_ids:
                continue
            entry = self._entry_from_event(event)
            if entry is not None:
                entries = self._upsert_feed_entry(entries, entry)
        return entries

    def _entry_from_event(self, event: DomainEvent) -> TopLevelFeedEntry | None:
        for key in (
            "message_item",
            "stage_node",
            "control_item",
            "approval_request",
            "approval_result",
            "tool_confirmation",
            "delivery_result",
            "system_status",
        ):
            value: Any = event.payload.get(key)
            if value is not None:
                if key == "tool_confirmation" and isinstance(value, dict):
                    value = self._hydrate_tool_confirmation(value)
                return TOP_LEVEL_FEED_ENTRY_ADAPTER.validate_python(value)
        return None

    def _upsert_feed_entry(
        self,
        entries: list[TopLevelFeedEntry],
        incoming: TopLevelFeedEntry,
    ) -> list[TopLevelFeedEntry]:
        if isinstance(incoming, ApprovalResultFeedEntry):
            entries = self._apply_approval_result(entries, incoming)
        incoming_identity = self._feed_identity(incoming)
        for index, entry in enumerate(entries):
            if self._feed_identity(entry) == incoming_identity:
                return entries[:index] + [incoming] + entries[index + 1 :]
        return [*entries, incoming]

    def _apply_approval_result(
        self,
        entries: list[TopLevelFeedEntry],
        approval_result: ApprovalResultFeedEntry,
    ) -> list[TopLevelFeedEntry]:
        return [
            entry.model_copy(
                update={
                    "status": approval_result.decision,
                    "is_actionable": False,
                },
            )
            if (
                entry.type == "approval_request"
                and entry.approval_id == approval_result.approval_id
            )
            else entry
            for entry in entries
        ]

    def _hydrate_tool_confirmation(
        self,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        tool_confirmation_id = value.get("tool_confirmation_id")
        if not isinstance(tool_confirmation_id, str):
            return value
        decision = value.get("decision")
        if decision != "denied":
            return {
                **value,
                "deny_followup_action": None,
                "deny_followup_summary": None,
            }
        request = self._runtime_session.get(
            ToolConfirmationRequestModel,
            tool_confirmation_id,
        )
        return {
            **value,
            "deny_followup_action": (
                request.deny_followup_action if request is not None else None
            ),
            "deny_followup_summary": (
                request.deny_followup_summary if request is not None else None
            ),
        }

    @staticmethod
    def _feed_identity(entry: TopLevelFeedEntry) -> str:
        if entry.type == "user_message":
            return f"{entry.type}:{entry.message_id}"
        if entry.type == "stage_node":
            return f"{entry.type}:{entry.stage_run_id}"
        if entry.type == "approval_request":
            return f"{entry.type}:{entry.approval_id}"
        if entry.type == "tool_confirmation":
            return f"{entry.type}:{entry.tool_confirmation_id}"
        if entry.type == "control_item":
            return f"{entry.type}:{entry.control_record_id}"
        if entry.type == "approval_result":
            return f"{entry.type}:{entry.approval_id}"
        if entry.type == "delivery_result":
            return f"{entry.type}:{entry.delivery_record_id}"
        return f"{entry.type}:{entry.run_id}:{entry.status}"

    def _run_summary(
        self,
        run: PipelineRunModel,
        *,
        session: SessionModel,
    ) -> RunSummaryProjection:
        terminal = run.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.TERMINATED,
        }
        return RunSummaryProjection(
            run_id=run.run_id,
            attempt_index=run.attempt_index,
            status=run.status,
            trigger_source=run.trigger_source,
            started_at=self._projection_datetime(run.started_at),
            ended_at=self._projection_datetime(run.ended_at),
            current_stage_type=self._stage_type_for_run_summary(
                run,
                session=session,
            ),
            is_active=run.run_id == session.current_run_id and not terminal,
        )

    def _current_stage_type(self, session: SessionModel):
        if session.current_run_id is None:
            return session.latest_stage_type
        run = self._runtime_session.get(PipelineRunModel, session.current_run_id)
        if run is None:
            return session.latest_stage_type
        return self._stage_type_for_run(run) or session.latest_stage_type

    def _stage_type_for_run(self, run: PipelineRunModel):
        if run.current_stage_run_id is None:
            return None
        stage = self._runtime_session.get(StageRunModel, run.current_stage_run_id)
        if stage is None:
            return None
        return stage.stage_type

    def _stage_type_for_run_summary(
        self,
        run: PipelineRunModel,
        *,
        session: SessionModel,
    ):
        stage_type = self._stage_type_for_run(run)
        if stage_type is not None:
            return stage_type
        terminal = run.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.TERMINATED,
        }
        if (
            run.run_id == session.current_run_id
            and run.current_stage_run_id is None
            and not terminal
        ):
            return session.latest_stage_type
        return None

    @staticmethod
    def _session_read(session: SessionModel) -> SessionRead:
        return SessionRead.model_validate(
            {
                "session_id": session.session_id,
                "project_id": session.project_id,
                "display_name": session.display_name,
                "status": session.status,
                "selected_template_id": session.selected_template_id,
                "current_run_id": session.current_run_id,
                "latest_stage_type": session.latest_stage_type,
                "created_at": WorkspaceProjectionService._projection_datetime(
                    session.created_at
                ),
                "updated_at": WorkspaceProjectionService._projection_datetime(
                    session.updated_at
                ),
            }
        )

    @staticmethod
    def _project_read(project: ProjectModel) -> ProjectRead:
        return ProjectRead.model_validate(
            {
                "project_id": project.project_id,
                "name": project.name,
                "root_path": project.root_path,
                "default_delivery_channel_id": project.default_delivery_channel_id,
                "is_default": project.is_default,
                "created_at": WorkspaceProjectionService._projection_datetime(
                    project.created_at
                ),
                "updated_at": WorkspaceProjectionService._projection_datetime(
                    project.updated_at
                ),
            }
        )

    @staticmethod
    def _projection_datetime(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)


__all__ = [
    "WorkspaceProjectionService",
    "WorkspaceProjectionServiceError",
]
