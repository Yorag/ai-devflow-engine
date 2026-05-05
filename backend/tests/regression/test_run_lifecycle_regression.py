from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.db.base import DatabaseRole
from backend.app.db.models.runtime import PipelineRunModel
from backend.app.domain.enums import DeliveryMode, RunStatus, StageType
from backend.app.runtime.base import RuntimeInterrupt, RuntimeStepResult
from backend.tests.e2e.test_full_api_flow import (
    _advance_until_interrupt_or_stage_result,
    _api_get,
    _approve_pending_approval,
    _attach_demo_delivery_snapshot,
    _close_fixture,
    _configure_full_path,
    _latest_delivery_record,
    _seed_tool_confirmation_trace,
    startDeterministicRunFixture,
)


def runRegressionScenario(tmp_path: Path) -> dict[str, Any]:
    fixture = startDeterministicRunFixture(tmp_path)
    try:
        requirement_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(requirement_result, RuntimeStepResult)
        assert requirement_result.stage_type is StageType.REQUIREMENT_ANALYSIS

        solution_interrupt = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(solution_interrupt, RuntimeInterrupt)
        assert solution_interrupt.stage_type is StageType.SOLUTION_DESIGN

        solution_approval = _approve_pending_approval(
            fixture.client,
            fixture.app,
            fixture.run_id,
        )
        assert solution_approval["approval_result"]["decision"] == "approved"

        solution_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(solution_result, RuntimeStepResult)
        assert solution_result.stage_type is StageType.SOLUTION_DESIGN

        tool_interrupt = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(tool_interrupt, RuntimeInterrupt)
        assert tool_interrupt.stage_type is StageType.CODE_GENERATION
        tool_confirmation_id = tool_interrupt.interrupt_ref.tool_confirmation_id
        assert tool_confirmation_id is not None

        allow_response = fixture.client.post(
            f"/api/tool-confirmations/{tool_confirmation_id}/allow",
            json={},
        )
        assert allow_response.status_code == 200
        allowed = allow_response.json()["tool_confirmation"]
        assert allowed["status"] == "allowed"
        assert allowed["decision"] == "allowed"
        _seed_tool_confirmation_trace(
            fixture.app,
            tool_confirmation_id,
            result_status="allowed",
        )

        code_generation_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(code_generation_result, RuntimeStepResult)
        assert code_generation_result.stage_type is StageType.CODE_GENERATION

        test_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(test_result, RuntimeStepResult)
        assert test_result.stage_type is StageType.TEST_GENERATION_EXECUTION

        review_interrupt = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(review_interrupt, RuntimeInterrupt)
        assert review_interrupt.stage_type is StageType.CODE_REVIEW

        review_approval = _approve_pending_approval(
            fixture.client,
            fixture.app,
            fixture.run_id,
        )
        assert review_approval["approval_result"]["decision"] == "approved"
        _attach_demo_delivery_snapshot(fixture.app, fixture.run_id)

        review_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(review_result, RuntimeStepResult)
        assert review_result.stage_type is StageType.CODE_REVIEW

        delivery_result = _advance_until_interrupt_or_stage_result(
            fixture,
            configure=_configure_full_path,
        )
        assert isinstance(delivery_result, RuntimeStepResult)
        assert delivery_result.stage_type is StageType.DELIVERY_INTEGRATION

        delivery_record = _latest_delivery_record(fixture.app, fixture.run_id)
        assert delivery_record.status == "succeeded"
        assert delivery_record.delivery_mode is DeliveryMode.DEMO_DELIVERY

        with fixture.app.state.database_manager.session(
            DatabaseRole.RUNTIME
        ) as session:
            run = session.get(PipelineRunModel, fixture.run_id)
            assert run is not None
            assert run.status is RunStatus.COMPLETED

        return {
            "app": fixture.app,
            "client": fixture.client,
            "delivery_record": delivery_record,
            "fixture": fixture,
            "run_id": fixture.run_id,
            "session_id": fixture.session_id,
        }
    except Exception:
        _close_fixture(fixture)
        raise


def assertSessionHistoryReplayStable(
    client: TestClient,
    session_id: str,
    run_id: str,
) -> None:
    workspace = _api_get(client, f"/api/sessions/{session_id}/workspace")
    timeline = _api_get(client, f"/api/runs/{run_id}/timeline")
    replayed_workspace = _api_get(client, f"/api/sessions/{session_id}/workspace")
    replayed_timeline = _api_get(client, f"/api/runs/{run_id}/timeline")

    assert workspace == replayed_workspace
    assert timeline == replayed_timeline

    assert workspace["session"]["status"] == RunStatus.COMPLETED.value
    assert workspace["session"]["current_run_id"] == run_id
    assert workspace["current_run_id"] == run_id
    matching_runs = [item for item in workspace["runs"] if item["run_id"] == run_id]
    assert len(matching_runs) == 1
    assert matching_runs[0]["status"] == RunStatus.COMPLETED.value
    assert matching_runs[0]["is_active"] is False

    assert timeline["run_id"] == run_id
    assert timeline["session_id"] == session_id
    assert timeline["status"] == RunStatus.COMPLETED.value

    workspace_identities = _feed_identities(workspace["narrative_feed"])
    timeline_identities = _feed_identities(timeline["entries"])
    assert workspace_identities == _feed_identities(
        replayed_workspace["narrative_feed"]
    )
    assert timeline_identities == _feed_identities(replayed_timeline["entries"])
    assert len(workspace_identities) == len(set(workspace_identities))
    assert len(timeline_identities) == len(set(timeline_identities))

    _assert_no_graph_thread_ref(workspace)
    _assert_no_graph_thread_ref(timeline)


def _feed_identities(entries: list[dict[str, Any]]) -> list[tuple[str, str]]:
    identities: list[tuple[str, str]] = []
    for entry in entries:
        entry_type = entry["type"]
        if entry_type == "delivery_result":
            entry_key = entry["delivery_record_id"]
        elif entry_type in {"approval_request", "approval_result"}:
            entry_key = entry["approval_id"]
        elif entry_type == "tool_confirmation":
            entry_key = entry["tool_confirmation_id"]
        elif entry_type == "stage_node":
            entry_key = entry["stage_run_id"]
        else:
            entry_key = entry["entry_id"]
        identities.append((entry_type, entry_key))
    return identities


def _assert_no_graph_thread_ref(value: Any) -> None:
    if isinstance(value, dict):
        assert "graph_thread_ref" not in value
        for nested in value.values():
            _assert_no_graph_thread_ref(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_graph_thread_ref(nested)


def test_run_lifecycle_regression_reaches_completed_delivery_and_rejects_second_requirement(
    tmp_path: Path,
) -> None:
    scenario = runRegressionScenario(tmp_path)
    try:
        client = scenario["client"]
        session_id = scenario["session_id"]
        run_id = scenario["run_id"]
        delivery_record = scenario["delivery_record"]
        delivery_record_id = delivery_record.delivery_record_id

        workspace = _api_get(client, f"/api/sessions/{session_id}/workspace")
        timeline = _api_get(client, f"/api/runs/{run_id}/timeline")
        workspace_delivery_results = [
            entry
            for entry in workspace["narrative_feed"]
            if entry["type"] == "delivery_result"
        ]
        timeline_delivery_results = [
            entry for entry in timeline["entries"] if entry["type"] == "delivery_result"
        ]

        assert [
            entry["delivery_record_id"] for entry in workspace_delivery_results
        ] == [delivery_record_id]
        assert [
            entry["delivery_record_id"] for entry in timeline_delivery_results
        ] == [delivery_record_id]

        delivery_detail = _api_get(
            client,
            f"/api/delivery-records/{delivery_record_id}",
        )
        assert delivery_detail["delivery_record_id"] == delivery_record_id
        assert delivery_detail["run_id"] == run_id
        assert delivery_detail["status"] == "succeeded"
        assert delivery_detail["delivery_mode"] == DeliveryMode.DEMO_DELIVERY.value

        second = client.post(
            f"/api/sessions/{session_id}/messages",
            json={
                "message_type": "new_requirement",
                "content": "Start another requirement after completion.",
            },
            headers={
                "X-Request-ID": "req-run-lifecycle-second-requirement",
                "X-Correlation-ID": "corr-run-lifecycle-regression",
            },
        )
        assert second.status_code == 409
        assert second.json()["error_code"] == "validation_error"
    finally:
        _close_fixture(scenario["fixture"])


def test_session_history_replay_stays_stable_after_completed_run_queries(
    tmp_path: Path,
) -> None:
    scenario = runRegressionScenario(tmp_path)
    try:
        assertSessionHistoryReplayStable(
            scenario["client"],
            scenario["session_id"],
            scenario["run_id"],
        )
    finally:
        _close_fixture(scenario["fixture"])
