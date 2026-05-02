from __future__ import annotations

from enum import StrEnum

from backend.app.domain.enums import RunStatus, RunTriggerSource, SessionStatus


class InvalidRunStateTransition(ValueError):
    """Raised when a run or session lifecycle rule rejects a transition."""


class RunTransitionEvent(StrEnum):
    REQUEST_CLARIFICATION = "request_clarification"
    CLARIFICATION_REPLY = "clarification_reply"
    REQUEST_APPROVAL = "request_approval"
    APPROVAL_RESULT = "approval_result"
    REQUEST_TOOL_CONFIRMATION = "request_tool_confirmation"
    TOOL_CONFIRMATION_RESULT = "tool_confirmation_result"
    PAUSE = "pause"
    RESUME = "resume"
    COMPLETE = "complete"
    FAIL = "fail"
    TERMINATE = "terminate"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.TERMINATED,
    }
)
ACTIVE_RUN_STATUSES = frozenset(
    status for status in RunStatus if status not in TERMINAL_RUN_STATUSES
)

_RUN_TO_SESSION_STATUS = {
    RunStatus.RUNNING: SessionStatus.RUNNING,
    RunStatus.PAUSED: SessionStatus.PAUSED,
    RunStatus.WAITING_CLARIFICATION: SessionStatus.WAITING_CLARIFICATION,
    RunStatus.WAITING_APPROVAL: SessionStatus.WAITING_APPROVAL,
    RunStatus.WAITING_TOOL_CONFIRMATION: SessionStatus.WAITING_TOOL_CONFIRMATION,
    RunStatus.COMPLETED: SessionStatus.COMPLETED,
    RunStatus.FAILED: SessionStatus.FAILED,
    RunStatus.TERMINATED: SessionStatus.TERMINATED,
}

_TRANSITIONS = {
    RunStatus.RUNNING: {
        RunTransitionEvent.REQUEST_CLARIFICATION: RunStatus.WAITING_CLARIFICATION,
        RunTransitionEvent.REQUEST_APPROVAL: RunStatus.WAITING_APPROVAL,
        RunTransitionEvent.REQUEST_TOOL_CONFIRMATION: RunStatus.WAITING_TOOL_CONFIRMATION,
        RunTransitionEvent.PAUSE: RunStatus.PAUSED,
        RunTransitionEvent.COMPLETE: RunStatus.COMPLETED,
        RunTransitionEvent.FAIL: RunStatus.FAILED,
        RunTransitionEvent.TERMINATE: RunStatus.TERMINATED,
    },
    RunStatus.WAITING_CLARIFICATION: {
        RunTransitionEvent.CLARIFICATION_REPLY: RunStatus.RUNNING,
        RunTransitionEvent.PAUSE: RunStatus.PAUSED,
        RunTransitionEvent.FAIL: RunStatus.FAILED,
        RunTransitionEvent.TERMINATE: RunStatus.TERMINATED,
    },
    RunStatus.WAITING_APPROVAL: {
        RunTransitionEvent.APPROVAL_RESULT: RunStatus.RUNNING,
        RunTransitionEvent.PAUSE: RunStatus.PAUSED,
        RunTransitionEvent.FAIL: RunStatus.FAILED,
        RunTransitionEvent.TERMINATE: RunStatus.TERMINATED,
    },
    RunStatus.WAITING_TOOL_CONFIRMATION: {
        RunTransitionEvent.TOOL_CONFIRMATION_RESULT: RunStatus.RUNNING,
        RunTransitionEvent.PAUSE: RunStatus.PAUSED,
        RunTransitionEvent.FAIL: RunStatus.FAILED,
        RunTransitionEvent.TERMINATE: RunStatus.TERMINATED,
    },
    RunStatus.PAUSED: {
        RunTransitionEvent.RESUME: RunStatus.RUNNING,
        RunTransitionEvent.TERMINATE: RunStatus.TERMINATED,
    },
    RunStatus.COMPLETED: {},
    RunStatus.FAILED: {},
    RunStatus.TERMINATED: {},
}

_EXTERNAL_RETRY_ALIASES = {"external_user_retry", "user_retry", "rerun"}


class RunStateMachine:
    @staticmethod
    def transition(
        current_status: RunStatus,
        event: RunTransitionEvent | str,
    ) -> RunStatus:
        try:
            transition_event = RunTransitionEvent(event)
        except ValueError as exc:
            raise InvalidRunStateTransition(
                f"unsupported transition event: {event}"
            ) from exc
        next_status = _TRANSITIONS[current_status].get(transition_event)
        if next_status is None:
            raise InvalidRunStateTransition(
                f"Cannot apply {transition_event.value} from {current_status.value}."
            )
        return next_status

    @staticmethod
    def assert_can_start_first_run(
        *,
        session_status: SessionStatus,
        current_run_id: str | None,
    ) -> RunTriggerSource:
        if session_status is not SessionStatus.DRAFT or current_run_id is not None:
            raise InvalidRunStateTransition(
                "The first new_requirement can start a run only from a draft Session "
                "with current_run_id = null."
            )
        return RunTriggerSource.INITIAL_REQUIREMENT

    @staticmethod
    def assert_can_create_rerun(
        *,
        session_status: SessionStatus,
        current_run_id: str | None,
        current_run_status: RunStatus | None,
        trigger_source: RunTriggerSource = RunTriggerSource.RETRY,
    ) -> RunTriggerSource:
        if session_status is SessionStatus.COMPLETED:
            raise InvalidRunStateTransition(
                "A completed Session cannot create a new PipelineRun; a new "
                "PipelineRun can be created only after the current run is failed "
                "or terminated."
            )
        if current_run_id is None or current_run_status is None:
            raise InvalidRunStateTransition(
                "A rerun requires an existing current run tail."
            )
        if current_run_status not in {RunStatus.FAILED, RunStatus.TERMINATED}:
            raise InvalidRunStateTransition(
                "A new PipelineRun can be created only after the current run "
                "is failed or terminated."
            )
        if session_status is not RunStateMachine.project_session_status(
            current_run_status
        ):
            raise InvalidRunStateTransition(
                "Session status must project from the current run status before "
                "creating a new PipelineRun."
            )
        return trigger_source

    @staticmethod
    def assert_can_create_run_from_source(
        *,
        session_status: SessionStatus,
        current_run_id: str | None,
        current_run_status: RunStatus | None,
        trigger_source: RunTriggerSource | str,
    ) -> RunTriggerSource:
        normalized_source = _normalize_trigger_source(trigger_source)
        if normalized_source is RunTriggerSource.INITIAL_REQUIREMENT:
            return RunStateMachine.assert_can_start_first_run(
                session_status=session_status,
                current_run_id=current_run_id,
            )
        return RunStateMachine.assert_can_create_rerun(
            session_status=session_status,
            current_run_id=current_run_id,
            current_run_status=current_run_status,
            trigger_source=normalized_source,
        )

    @staticmethod
    def project_session_status(run_status: RunStatus | None) -> SessionStatus:
        if run_status is None:
            return SessionStatus.DRAFT
        return _RUN_TO_SESSION_STATUS[run_status]

    @staticmethod
    def is_terminal_run_status(status: RunStatus) -> bool:
        return status in TERMINAL_RUN_STATUSES

    @staticmethod
    def is_active_run_status(status: RunStatus) -> bool:
        return status in ACTIVE_RUN_STATUSES


def _normalize_trigger_source(source: RunTriggerSource | str) -> RunTriggerSource:
    if isinstance(source, RunTriggerSource):
        return source
    if source in _EXTERNAL_RETRY_ALIASES:
        return RunTriggerSource.RETRY
    try:
        return RunTriggerSource(source)
    except ValueError as exc:
        raise InvalidRunStateTransition(
            f"unsupported trigger source: {source}"
        ) from exc


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "InvalidRunStateTransition",
    "RunStateMachine",
    "RunTransitionEvent",
    "TERMINAL_RUN_STATUSES",
]
