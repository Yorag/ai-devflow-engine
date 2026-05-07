from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

import httpx
import pytest


SMOKE_REQUIREMENT = (
    "请只修改 frontend/src/pages/HomePage.tsx，把 "
    "<h1>Make delivery work traceable.</h1> 改成 "
    "<h1>Make delivery work.</h1>。不要修改其他文件。"
)
TARGET_FILE = "frontend/src/pages/HomePage.tsx"
TERMINAL_OR_CONTROL_STATUSES = {
    "completed",
    "failed",
    "terminated",
    "waiting_approval",
    "waiting_tool_confirmation",
    "waiting_clarification",
}


@dataclass(frozen=True, slots=True)
class RuntimeState:
    run_status: str
    current_stage_run_id: str | None
    stages: dict[str, dict[str, Any]]
    outputs: dict[str, dict[str, Any]]
    pending_approval_ids: tuple[str, ...]
    pending_tool_confirmation_ids: tuple[str, ...]


def test_real_model_stage_handoff_smoke() -> None:
    if os.environ.get("AI_DEVFLOW_LIVE_MODEL_SMOKE") != "1":
        pytest.skip("set AI_DEVFLOW_LIVE_MODEL_SMOKE=1 to run live model smoke")

    base_url = os.environ.get(
        "AI_DEVFLOW_SMOKE_BASE_URL",
        "http://127.0.0.1:8000/api",
    ).rstrip("/")
    runtime_db = Path(
        os.environ.get("AI_DEVFLOW_RUNTIME_DB", ".runtime/runtime.db")
    )
    deadline = time.monotonic() + int(
        os.environ.get("AI_DEVFLOW_SMOKE_TIMEOUT_SECONDS", "900")
    )
    http_timeout_seconds = float(
        os.environ.get(
            "AI_DEVFLOW_SMOKE_HTTP_TIMEOUT_SECONDS",
            os.environ.get("AI_DEVFLOW_SMOKE_TIMEOUT_SECONDS", "900"),
        )
    )

    with httpx.Client(base_url=base_url, timeout=http_timeout_seconds) as client:
        created = client.post("/projects/project-default/sessions")
        created.raise_for_status()
        session_id = created.json()["session_id"]
        appended = client.post(
            f"/sessions/{session_id}/messages",
            json={"message_type": "new_requirement", "content": SMOKE_REQUIREMENT},
        )
        appended.raise_for_status()
        run_id = appended.json()["session"]["current_run_id"]
        assert run_id, "new_requirement did not start a PipelineRun"

        state = _wait_for_codegen_or_control(
            client=client,
            runtime_db=runtime_db,
            run_id=run_id,
            deadline=deadline,
        )

    _assert_no_downstream_clarification(state, run_id=run_id, session_id=session_id)

    if state.run_status == "waiting_tool_confirmation":
        pytest.fail(
            _diagnostic(
                "run stopped at tool confirmation before code generation evidence",
                run_id=run_id,
                session_id=session_id,
                state=state,
            )
        )
    if state.run_status == "waiting_approval" and "code_generation" not in state.outputs:
        pytest.fail(
            _diagnostic(
                "run stopped at approval before code generation evidence",
                run_id=run_id,
                session_id=session_id,
                state=state,
            )
        )

    requirement_output = state.outputs.get("requirement_analysis")
    solution_output = state.outputs.get("solution_design")
    code_output = state.outputs.get("code_generation")
    assert requirement_output is not None, _diagnostic(
        "Requirement Analysis did not complete",
        run_id=run_id,
        session_id=session_id,
        state=state,
    )
    assert solution_output is not None, _diagnostic(
        "Solution Design did not complete",
        run_id=run_id,
        session_id=session_id,
        state=state,
    )
    assert code_output is not None, _diagnostic(
        "Code Generation did not complete",
        run_id=run_id,
        session_id=session_id,
        state=state,
    )

    solution_payload = _artifact_payload(solution_output)
    plan = solution_payload.get("implementation_plan")
    assert isinstance(plan, dict), "SolutionDesignArtifact missing implementation_plan"
    tasks = plan.get("tasks")
    assert isinstance(tasks, list) and tasks, "implementation_plan.tasks is empty"
    assert any(TARGET_FILE in json.dumps(task, ensure_ascii=False) for task in tasks), (
        f"implementation_plan does not target {TARGET_FILE}"
    )

    code_payload = _artifact_payload(code_output)
    file_edit_refs = _string_list(code_payload.get("file_edit_trace_refs"))
    assert any(ref.startswith("file_edit_trace:") for ref in file_edit_refs), (
        "CodeGenerationArtifact missing successful file_edit_trace_refs"
    )
    assert TARGET_FILE in json.dumps(code_payload, ensure_ascii=False), (
        f"CodeGenerationArtifact does not cite {TARGET_FILE}"
    )

    test_output = state.outputs.get("test_generation_execution")
    if test_output is not None:
        test_payload = _artifact_payload(test_output)
        command_refs = _string_list(test_payload.get("command_trace_refs"))
        assert any(ref.startswith("command_trace:") for ref in command_refs), (
            "TestGenerationExecutionArtifact completed without command_trace_refs"
        )


def _wait_for_codegen_or_control(
    *,
    client: httpx.Client,
    runtime_db: Path,
    run_id: str,
    deadline: float,
) -> RuntimeState:
    latest_state: RuntimeState | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/runs/{run_id}")
        response.raise_for_status()
        latest_state = _load_runtime_state(runtime_db, run_id)
        if (
            latest_state.run_status == "waiting_approval"
            and "code_generation" not in latest_state.outputs
            and latest_state.pending_approval_ids
        ):
            for approval_id in latest_state.pending_approval_ids:
                approved = client.post(f"/approvals/{approval_id}/approve", json={})
                approved.raise_for_status()
            time.sleep(1.0)
            continue
        if "code_generation" in latest_state.outputs:
            return latest_state
        if latest_state.run_status in TERMINAL_OR_CONTROL_STATUSES:
            return latest_state
        time.sleep(2.0)

    if latest_state is not None:
        return latest_state
    raise AssertionError(f"run {run_id} did not appear in {runtime_db}")


def _load_runtime_state(runtime_db: Path, run_id: str) -> RuntimeState:
    if not runtime_db.is_file():
        raise AssertionError(f"runtime database not found: {runtime_db}")
    connection = sqlite3.connect(runtime_db)
    connection.row_factory = sqlite3.Row
    try:
        run = connection.execute(
            "select status, current_stage_run_id from pipeline_runs where run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise AssertionError(f"PipelineRun was not found in runtime db: {run_id}")
        stages = {
            row["stage_type"]: dict(row)
            for row in connection.execute(
                """
                select stage_run_id, stage_type, status, summary
                from stage_runs
                where run_id = ?
                order by started_at asc, stage_run_id asc
                """,
                (run_id,),
            ).fetchall()
        }
        outputs: dict[str, dict[str, Any]] = {}
        for row in connection.execute(
            """
            select sr.stage_type, sa.process
            from stage_artifacts sa
            join stage_runs sr on sr.stage_run_id = sa.stage_run_id
            where sa.run_id = ?
            order by sa.created_at asc, sa.artifact_id asc
            """,
            (run_id,),
        ).fetchall():
            process = _json_object(row["process"])
            snapshot = process.get("output_snapshot")
            if isinstance(snapshot, dict):
                outputs[row["stage_type"]] = snapshot
        approvals = tuple(
            row["approval_id"]
            for row in connection.execute(
                """
                select approval_id from approval_requests
                where run_id = ? and status = 'pending'
                order by requested_at asc
                """,
                (run_id,),
            ).fetchall()
        )
        confirmations = tuple(
            row["tool_confirmation_id"]
            for row in connection.execute(
                """
                select tool_confirmation_id from tool_confirmation_requests
                where run_id = ? and status = 'pending'
                order by requested_at asc
                """,
                (run_id,),
            ).fetchall()
        )
        return RuntimeState(
            run_status=str(run["status"]),
            current_stage_run_id=run["current_stage_run_id"],
            stages=stages,
            outputs=outputs,
            pending_approval_ids=approvals,
            pending_tool_confirmation_ids=confirmations,
        )
    finally:
        connection.close()


def _assert_no_downstream_clarification(
    state: RuntimeState,
    *,
    run_id: str,
    session_id: str,
) -> None:
    for stage_type in (
        "solution_design",
        "code_generation",
        "test_generation_execution",
        "code_review",
        "delivery_integration",
    ):
        stage = state.stages.get(stage_type)
        if stage and stage.get("status") == "waiting_clarification":
            pytest.fail(
                _diagnostic(
                    f"downstream stage requested clarification: {stage_type}",
                    run_id=run_id,
                    session_id=session_id,
                    state=state,
                )
            )


def _artifact_payload(output_snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = output_snapshot.get("artifact_payload")
    return payload if isinstance(payload, dict) else output_snapshot


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _diagnostic(
    message: str,
    *,
    run_id: str,
    session_id: str,
    state: RuntimeState,
) -> str:
    return (
        f"{message}; session_id={session_id}; run_id={run_id}; "
        f"run_status={state.run_status}; "
        f"current_stage_run_id={state.current_stage_run_id}; "
        f"stages={state.stages}; "
        f"outputs={list(state.outputs)}; "
        f"pending_approval_ids={list(state.pending_approval_ids)}; "
        f"pending_tool_confirmation_ids={list(state.pending_tool_confirmation_ids)}"
    )
