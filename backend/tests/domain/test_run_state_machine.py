import pytest

from backend.app.domain.enums import RunStatus, RunTriggerSource, SessionStatus
from backend.app.domain.state_machine import (
    InvalidRunStateTransition,
    RunStateMachine,
    RunTransitionEvent,
)


def test_first_new_requirement_requires_draft_session_without_current_run() -> None:
    assert (
        RunStateMachine.assert_can_start_first_run(
            session_status=SessionStatus.DRAFT,
            current_run_id=None,
        )
        is RunTriggerSource.INITIAL_REQUIREMENT
    )

    with pytest.raises(InvalidRunStateTransition, match="draft Session"):
        RunStateMachine.assert_can_start_first_run(
            session_status=SessionStatus.DRAFT,
            current_run_id="run-1",
        )

    with pytest.raises(InvalidRunStateTransition, match="draft Session"):
        RunStateMachine.assert_can_start_first_run(
            session_status=SessionStatus.RUNNING,
            current_run_id=None,
        )


def test_clarification_reply_only_resumes_waiting_clarification_run() -> None:
    assert (
        RunStateMachine.transition(
            RunStatus.WAITING_CLARIFICATION,
            RunTransitionEvent.CLARIFICATION_REPLY,
        )
        is RunStatus.RUNNING
    )

    for status in (
        RunStatus.RUNNING,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_TOOL_CONFIRMATION,
        RunStatus.PAUSED,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.TERMINATED,
    ):
        with pytest.raises(
            InvalidRunStateTransition,
            match="clarification_reply",
        ):
            RunStateMachine.transition(
                status,
                RunTransitionEvent.CLARIFICATION_REPLY,
            )


def test_completed_session_never_creates_new_run() -> None:
    with pytest.raises(InvalidRunStateTransition, match="completed Session"):
        RunStateMachine.assert_can_create_rerun(
            session_status=SessionStatus.COMPLETED,
            current_run_id="run-1",
            current_run_status=RunStatus.COMPLETED,
        )

    with pytest.raises(InvalidRunStateTransition, match="completed Session"):
        RunStateMachine.assert_can_create_run_from_source(
            session_status=SessionStatus.COMPLETED,
            current_run_id="run-1",
            current_run_status=RunStatus.COMPLETED,
            trigger_source=RunTriggerSource.RETRY,
        )


def test_failed_or_terminated_current_run_tail_allows_new_run() -> None:
    for status in (RunStatus.FAILED, RunStatus.TERMINATED):
        assert (
            RunStateMachine.assert_can_create_rerun(
                session_status=RunStateMachine.project_session_status(status),
                current_run_id="run-1",
                current_run_status=status,
            )
            is RunTriggerSource.RETRY
        )


def test_non_terminal_or_completed_current_run_blocks_new_run() -> None:
    for status in (
        RunStatus.RUNNING,
        RunStatus.PAUSED,
        RunStatus.WAITING_CLARIFICATION,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_TOOL_CONFIRMATION,
        RunStatus.COMPLETED,
    ):
        with pytest.raises(
            InvalidRunStateTransition,
            match="failed or terminated",
        ):
            RunStateMachine.assert_can_create_rerun(
                session_status=RunStateMachine.project_session_status(status),
                current_run_id="run-1",
                current_run_status=status,
            )


def test_trigger_source_rules_cover_v1_sources_and_external_retry_mapping() -> None:
    assert (
        RunStateMachine.assert_can_create_run_from_source(
            session_status=SessionStatus.DRAFT,
            current_run_id=None,
            current_run_status=None,
            trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
        )
        is RunTriggerSource.INITIAL_REQUIREMENT
    )
    assert (
        RunStateMachine.assert_can_create_run_from_source(
            session_status=SessionStatus.FAILED,
            current_run_id="run-1",
            current_run_status=RunStatus.FAILED,
            trigger_source="external_user_retry",
        )
        is RunTriggerSource.RETRY
    )
    assert (
        RunStateMachine.assert_can_create_run_from_source(
            session_status=SessionStatus.TERMINATED,
            current_run_id="run-1",
            current_run_status=RunStatus.TERMINATED,
            trigger_source=RunTriggerSource.OPS_RESTART,
        )
        is RunTriggerSource.OPS_RESTART
    )


def test_pause_and_resume_continue_same_run_and_do_not_enable_run_creation() -> None:
    assert (
        RunStateMachine.transition(RunStatus.RUNNING, RunTransitionEvent.PAUSE)
        is RunStatus.PAUSED
    )
    assert (
        RunStateMachine.transition(RunStatus.PAUSED, RunTransitionEvent.RESUME)
        is RunStatus.RUNNING
    )

    with pytest.raises(InvalidRunStateTransition, match="failed or terminated"):
        RunStateMachine.assert_can_create_run_from_source(
            session_status=SessionStatus.PAUSED,
            current_run_id="run-1",
            current_run_status=RunStatus.PAUSED,
            trigger_source=RunTriggerSource.RETRY,
        )


def test_project_session_status_maps_run_status_and_draft_without_run() -> None:
    assert RunStateMachine.project_session_status(None) is SessionStatus.DRAFT

    for run_status in RunStatus:
        projected = RunStateMachine.project_session_status(run_status)
        assert projected.value == run_status.value


def test_unknown_transition_inputs_raise_state_machine_error() -> None:
    with pytest.raises(InvalidRunStateTransition, match="unsupported transition event"):
        RunStateMachine.transition(RunStatus.RUNNING, "unknown_event")

    with pytest.raises(InvalidRunStateTransition, match="unsupported trigger source"):
        RunStateMachine.assert_can_create_run_from_source(
            session_status=SessionStatus.FAILED,
            current_run_id="run-1",
            current_run_status=RunStatus.FAILED,
            trigger_source="new_requirement",
        )
