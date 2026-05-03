from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.control import PlatformRuntimeSettingsModel, ProjectModel
from backend.app.db.models.control import SessionModel as ControlSessionModel
from backend.app.db.models.log import RunLogEntryModel
from backend.app.db.models.runtime import PipelineRunModel, StageRunModel
from backend.app.repositories.runtime_settings import RUNTIME_SETTINGS_ID
from backend.app.schemas.observability import (
    LogCategory,
    LogLevel,
    RunLogEntryProjection,
    RunLogQuery,
    RunLogQueryResponse,
)
from backend.app.schemas.runtime_settings import LogPolicy, PlatformHardLimits
from backend.app.services.publication_boundary import (
    PublicationBoundaryService,
    PublicationBoundaryServiceError,
)


RUN_LOGS_NOT_FOUND_MESSAGE = "Run logs were not found."
STAGE_LOGS_NOT_FOUND_MESSAGE = "Stage logs were not found."
INVALID_LOG_QUERY_MESSAGE = "Log query is invalid."
CONFIG_SNAPSHOT_UNAVAILABLE_MESSAGE = "Configuration snapshot is unavailable."


class LogQueryServiceError(RuntimeError):
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


def encode_cursor(created_at: datetime, log_id: str) -> str:
    payload = {"created_at": created_at.isoformat(), "log_id": log_id}
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    return encoded.decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        log_id = payload["log_id"]
    except (
        UnicodeEncodeError,
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise LogQueryService._invalid_query() from exc
    if not isinstance(log_id, str) or not log_id:
        raise LogQueryService._invalid_query()
    return created_at, log_id


class LogQueryService:
    def __init__(
        self,
        control_session: Session,
        runtime_session: Session,
        log_session: Session,
    ) -> None:
        self._control_session = control_session
        self._runtime_session = runtime_session
        self._log_session = log_session
        self._publication_boundary = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
        )

    def list_run_logs(
        self,
        run_id: str,
        *,
        level: LogLevel | None = None,
        category: LogCategory | None = None,
        source: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> RunLogQueryResponse:
        run = self._get_visible_run(run_id, message=RUN_LOGS_NOT_FOUND_MESSAGE)
        effective_limit = self._effective_limit(limit)
        decoded_cursor = self.decode_cursor(cursor) if cursor is not None else None
        query_echo = self._query_echo(
            run_id=run.run_id,
            stage_run_id=None,
            level=level,
            category=category,
            source=source,
            since=since,
            until=until,
            cursor=cursor,
            limit=effective_limit,
        )
        return self._list_logs(
            run_id=run.run_id,
            stage_run_id=None,
            level=level,
            category=category,
            source=source,
            since=since,
            until=until,
            cursor=decoded_cursor,
            limit=effective_limit,
            query_echo=query_echo,
        )

    def list_stage_logs(
        self,
        stage_run_id: str,
        *,
        level: LogLevel | None = None,
        category: LogCategory | None = None,
        source: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> RunLogQueryResponse:
        stage = self._get_visible_stage(stage_run_id)
        effective_limit = self._effective_limit(limit)
        decoded_cursor = self.decode_cursor(cursor) if cursor is not None else None
        query_echo = self._query_echo(
            run_id=stage.run_id,
            stage_run_id=stage.stage_run_id,
            level=level,
            category=category,
            source=source,
            since=since,
            until=until,
            cursor=cursor,
            limit=effective_limit,
        )
        return self._list_logs(
            run_id=stage.run_id,
            stage_run_id=stage.stage_run_id,
            level=level,
            category=category,
            source=source,
            since=since,
            until=until,
            cursor=decoded_cursor,
            limit=effective_limit,
            query_echo=query_echo,
        )

    def encode_cursor(self, created_at: datetime, log_id: str) -> str:
        return encode_cursor(created_at, log_id)

    def decode_cursor(self, cursor: str) -> tuple[datetime, str]:
        return decode_cursor(cursor)

    def _list_logs(
        self,
        *,
        run_id: str,
        stage_run_id: str | None,
        level: LogLevel | None,
        category: LogCategory | None,
        source: str | None,
        since: datetime | None,
        until: datetime | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
        query_echo: RunLogQuery,
    ) -> RunLogQueryResponse:
        statement = select(RunLogEntryModel).where(RunLogEntryModel.run_id == run_id)
        if stage_run_id is not None:
            statement = statement.where(RunLogEntryModel.stage_run_id == stage_run_id)
        if level is not None:
            statement = statement.where(RunLogEntryModel.level == level)
        if category is not None:
            statement = statement.where(RunLogEntryModel.category == category)
        if source is not None:
            statement = statement.where(RunLogEntryModel.source == source)
        if since is not None:
            statement = statement.where(RunLogEntryModel.created_at >= since)
        if until is not None:
            statement = statement.where(RunLogEntryModel.created_at <= until)
        if cursor is not None:
            cursor_created_at, cursor_log_id = cursor
            statement = statement.where(
                or_(
                    RunLogEntryModel.created_at > cursor_created_at,
                    and_(
                        RunLogEntryModel.created_at == cursor_created_at,
                        RunLogEntryModel.log_id > cursor_log_id,
                    ),
                )
            )
        statement = statement.order_by(
            RunLogEntryModel.created_at.asc(),
            RunLogEntryModel.log_id.asc(),
        ).limit(limit + 1)

        rows = list(self._log_session.scalars(statement))
        page_rows = rows[:limit]
        has_more = len(rows) > limit
        next_cursor = (
            self.encode_cursor(page_rows[-1].created_at, page_rows[-1].log_id)
            if has_more and page_rows
            else None
        )
        return RunLogQueryResponse(
            entries=[self._to_projection(row) for row in page_rows],
            next_cursor=next_cursor,
            has_more=has_more,
            query=query_echo,
        )

    def _effective_limit(self, requested_limit: int | None) -> int:
        log_policy = self._current_log_policy()
        effective_limit = (
            log_policy.log_query_default_limit
            if requested_limit is None
            else requested_limit
        )
        if effective_limit <= 0 or effective_limit > log_policy.log_query_max_limit:
            raise self._invalid_query()
        return effective_limit

    def _query_echo(
        self,
        *,
        run_id: str,
        stage_run_id: str | None,
        level: LogLevel | None,
        category: LogCategory | None,
        source: str | None,
        since: datetime | None,
        until: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> RunLogQuery:
        try:
            return RunLogQuery(
                run_id=run_id,
                stage_run_id=stage_run_id,
                level=level,
                category=category,
                source=source,
                since=since,
                until=until,
                cursor=cursor,
                limit=limit,
            )
        except ValidationError as exc:
            raise self._invalid_query() from exc

    def _current_log_policy(self) -> LogPolicy:
        try:
            model = self._control_session.get(
                PlatformRuntimeSettingsModel,
                RUNTIME_SETTINGS_ID,
            )
        except SQLAlchemyError as exc:
            raise self._config_unavailable() from exc
        if model is None:
            raise self._config_unavailable()
        if not self._has_required_log_query_limit_fields(model.log_policy):
            raise self._config_unavailable()
        try:
            log_policy = LogPolicy.model_validate(model.log_policy)
        except ValidationError as exc:
            raise self._config_unavailable() from exc
        hard_limit = PlatformHardLimits().log_policy.log_query_max_limit
        if (
            log_policy.log_query_max_limit > hard_limit
            or log_policy.log_query_default_limit > log_policy.log_query_max_limit
        ):
            raise self._config_unavailable()
        return log_policy

    @staticmethod
    def _has_required_log_query_limit_fields(log_policy: Any) -> bool:
        if not isinstance(log_policy, dict):
            return False
        return {
            "log_query_default_limit",
            "log_query_max_limit",
        } <= log_policy.keys()

    def _get_visible_stage(self, stage_run_id: str) -> StageRunModel:
        try:
            stage, _run = self._publication_boundary.assert_stage_visible(
                stage_run_id=stage_run_id,
                not_found_message=STAGE_LOGS_NOT_FOUND_MESSAGE,
            )
        except PublicationBoundaryServiceError:
            raise self._not_found(STAGE_LOGS_NOT_FOUND_MESSAGE)
        return stage

    def _get_visible_run(self, run_id: str, *, message: str) -> PipelineRunModel:
        try:
            self._publication_boundary.assert_run_visible(
                run_id=run_id,
                not_found_message=message,
            )
        except PublicationBoundaryServiceError:
            raise self._not_found(message)
        run = self._runtime_session.get(PipelineRunModel, run_id)
        if run is None:
            raise self._not_found(message)
        control_session = self._control_session.get(
            ControlSessionModel,
            run.session_id,
        )
        if (
            control_session is None
            or not control_session.is_visible
            or control_session.project_id != run.project_id
        ):
            raise self._not_found(message)
        project = self._control_session.get(ProjectModel, run.project_id)
        if project is None or not project.is_visible:
            raise self._not_found(message)
        return run

    @staticmethod
    def _to_projection(row: RunLogEntryModel) -> RunLogEntryProjection:
        return RunLogEntryProjection(
            log_id=row.log_id,
            session_id=row.session_id,
            run_id=row.run_id,
            stage_run_id=row.stage_run_id,
            approval_id=row.approval_id,
            tool_confirmation_id=row.tool_confirmation_id,
            delivery_record_id=row.delivery_record_id,
            graph_thread_id=row.graph_thread_id,
            request_id=row.request_id,
            source=row.source,
            category=row.category,
            level=row.level,
            message=row.message,
            log_file_ref=row.log_file_ref,
            line_offset=row.line_offset,
            line_number=row.line_number,
            log_file_generation=row.log_file_generation,
            payload_ref=row.payload_ref,
            payload_excerpt=row.payload_excerpt,
            payload_size_bytes=row.payload_size_bytes,
            redaction_status=row.redaction_status,
            correlation_id=row.correlation_id,
            trace_id=row.trace_id,
            span_id=row.span_id,
            parent_span_id=row.parent_span_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _invalid_query() -> LogQueryServiceError:
        return LogQueryServiceError(
            ErrorCode.LOG_QUERY_INVALID,
            INVALID_LOG_QUERY_MESSAGE,
            422,
        )

    @staticmethod
    def _not_found(message: str) -> LogQueryServiceError:
        return LogQueryServiceError(ErrorCode.NOT_FOUND, message, 404)

    @staticmethod
    def _config_unavailable() -> LogQueryServiceError:
        return LogQueryServiceError(
            ErrorCode.CONFIG_SNAPSHOT_UNAVAILABLE,
            CONFIG_SNAPSHOT_UNAVAILABLE_MESSAGE,
            503,
        )


__all__ = [
    "LogQueryService",
    "LogQueryServiceError",
    "decode_cursor",
    "encode_cursor",
]
