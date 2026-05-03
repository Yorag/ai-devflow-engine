from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.runtime import (
    ApprovalDecisionModel,
    ApprovalRequestModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    StageStatus,
    StageType,
)
from backend.app.schemas import common
from backend.app.schemas.feed import ExecutionNodeProjection, ProviderCallStageItem
from backend.app.schemas.run import (
    ImplementationPlanTaskRead,
    SolutionDesignArtifactRead,
    SolutionImplementationPlanRead,
)
from backend.app.services.events import DomainEventType, EventStore
from backend.tests.projections.test_workspace_projection import (
    NOW,
    _manager,
    _seed_workspace,
    _trace,
)


def test_stage_inspector_projection_builds_sections_from_stage_artifacts_events_and_runtime(
    tmp_path,
) -> None:
    from backend.app.services.projections.inspector import InspectorProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with manager.session(DatabaseRole.RUNTIME) as session:
        stage = session.get(StageRunModel, "stage-active")
        assert stage is not None
        stage.input_ref = "input-snapshot-active"
        stage.output_ref = "output-snapshot-active"
        session.add(
            StageArtifactModel(
                artifact_id="artifact-code-output-1",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="code_patch",
                payload_ref="payload-code-output-1",
                process={
                    "graph_thread_ref": "graph-thread-artifact",
                    "graph_thread_id": "graph-thread-id-artifact",
                    "input_snapshot": {
                        "requirement_ref": "requirement-artifact-1",
                        "prompt_ref": "prompt-code-generation-1",
                        "graph_thread_ref": "graph-thread-artifact",
                        "graph_thread_id": "graph-thread-id-artifact",
                    },
                    "context_refs": ["context-file-1", "context-symbol-1"],
                    "output_snapshot": {
                        "changed_file_refs": ["workspace-file-1"],
                        "patch_ref": "patch-code-generation-1",
                        "graph_thread_ref": "graph-thread-artifact",
                        "graph_thread_id": "graph-thread-id-artifact",
                    },
                    "provider_retry_trace_ref": "artifact-provider-retry-trace-1",
                    "provider_circuit_breaker_trace_ref": (
                        "artifact-provider-circuit-trace-1"
                    ),
                    "tool_confirmation_trace_ref": (
                        "artifact-tool-confirmation-trace-1"
                    ),
                    "log_refs": ["log-code-generation-1"],
                },
                metrics={
                    "duration_ms": 4200,
                    "input_tokens": 1000,
                    "output_tokens": 600,
                    "total_tokens": 1600,
                    "tool_call_count": 1,
                },
                created_at=NOW + timedelta(minutes=7, seconds=30),
            )
        )
        session.commit()

    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(["event-provider-retry"]).__next__,
        )
        store.append(
            DomainEventType.PROVIDER_CALL_RETRIED,
            payload={
                "stage_node": ExecutionNodeProjection(
                    entry_id="entry-stage-active-provider-retry",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7, seconds=45),
                    stage_run_id="stage-active",
                    stage_type=common.StageType.CODE_GENERATION,
                    status=common.StageStatus.WAITING_TOOL_CONFIRMATION,
                    attempt_index=1,
                    started_at=NOW + timedelta(minutes=2),
                    ended_at=None,
                    summary="Code Generation is retrying a provider call.",
                    items=[
                        ProviderCallStageItem(
                            item_id="provider-call-model-1",
                            type=common.StageItemType.PROVIDER_CALL,
                            occurred_at=NOW + timedelta(minutes=7, seconds=40),
                            title="Provider success",
                            summary="Model call completed without retry.",
                            content=None,
                            artifact_refs=[
                                "model-call-artifact-1",
                                "model-retry-policy-snapshot",
                            ],
                            metrics={},
                            provider_id="provider-deepseek",
                            model_id="deepseek-chat",
                            status="succeeded",
                            retry_attempt=0,
                            max_retry_attempts=2,
                            backoff_wait_seconds=None,
                            circuit_breaker_status=(
                                common.ProviderCircuitBreakerStatus.CLOSED
                            ),
                            failure_reason=None,
                            process_ref="model-call-trace-1",
                        ),
                        ProviderCallStageItem(
                            item_id="provider-call-1",
                            type=common.StageItemType.PROVIDER_CALL,
                            occurred_at=NOW + timedelta(minutes=7, seconds=45),
                            title="Provider retry",
                            summary="Network retry scheduled.",
                            content=None,
                            artifact_refs=[
                                "provider-retry-trace-1",
                                "provider-circuit-breaker-trace-1",
                            ],
                            metrics={},
                            provider_id="provider-deepseek",
                            model_id="deepseek-chat",
                            status="retrying",
                            retry_attempt=1,
                            max_retry_attempts=2,
                            backoff_wait_seconds=5,
                            circuit_breaker_status=(
                                common.ProviderCircuitBreakerStatus.CLOSED
                            ),
                            failure_reason="network_error",
                            process_ref="provider-retry-trace-1",
                        )
                    ],
                    metrics={},
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        inspector = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_stage_inspector("stage-active")

    dumped = inspector.model_dump(mode="json")
    assert dumped["stage_run_id"] == "stage-active"
    assert dumped["run_id"] == "run-active"
    assert dumped["stage_type"] == "code_generation"
    assert dumped["status"] == "waiting_tool_confirmation"
    assert {
        "identity",
        "input",
        "process",
        "output",
        "artifacts",
        "metrics",
    }.issubset(dumped)
    assert dumped["identity"]["records"]["input_ref"] == "input-snapshot-active"
    assert dumped["identity"]["records"]["output_ref"] == "output-snapshot-active"
    assert dumped["input"]["records"]["input_snapshot"]["requirement_ref"] == (
        "requirement-artifact-1"
    )
    assert dumped["input"]["stable_refs"] == [
        "input-snapshot-active",
        "context-file-1",
        "context-symbol-1",
    ]
    assert dumped["output"]["records"]["output_snapshot"]["patch_ref"] == (
        "patch-code-generation-1"
    )
    assert dumped["artifacts"]["records"]["artifact_refs"] == ["artifact-code-output-1"]
    assert dumped["artifacts"]["records"]["payload_refs"] == [
        "payload-code-output-1"
    ]

    provider_call = next(
        call
        for call in dumped["process"]["records"]["provider_calls"]
        if call["item_id"] == "provider-call-1"
    )
    assert provider_call["provider_id"] == "provider-deepseek"
    assert provider_call["model_id"] == "deepseek-chat"
    assert provider_call["status"] == "retrying"
    assert provider_call["retry_attempt"] == 1
    assert provider_call["max_retry_attempts"] == 2
    assert provider_call["backoff_wait_seconds"] == 5
    assert provider_call["circuit_breaker_status"] == "closed"
    assert provider_call["failure_reason"] == "network_error"
    assert provider_call["process_ref"] == "provider-retry-trace-1"
    assert dumped["tool_confirmation_trace_refs"] == [
        "process-tool-confirmation-1",
        "artifact-tool-confirmation-trace-1",
    ]
    assert dumped["provider_retry_trace_refs"] == [
        "artifact-provider-retry-trace-1",
        "provider-retry-trace-1",
    ]
    assert "model-call-trace-1" not in dumped["provider_retry_trace_refs"]
    assert "model-retry-policy-snapshot" not in dumped["provider_retry_trace_refs"]
    assert dumped["provider_circuit_breaker_trace_refs"] == [
        "artifact-provider-circuit-trace-1",
        "provider-circuit-breaker-trace-1",
    ]
    assert dumped["process"]["log_refs"] == ["log-code-generation-1"]
    assert dumped["metrics"] == {
        "duration_ms": 4200,
        "input_tokens": 1000,
        "output_tokens": 600,
        "total_tokens": 1600,
        "attempt_index": 1,
        "tool_call_count": 1,
    }
    assert "graph_thread_ref" not in str(dumped)
    assert "graph_thread_id" not in str(dumped)
    assert "graph-thread-active" not in str(dumped)
    assert "graph-thread-artifact" not in str(dumped)
    assert "graph-thread-id-artifact" not in str(dumped)


def test_solution_design_inspector_returns_implementation_plan_and_approval_result_refs(
    tmp_path,
) -> None:
    from backend.app.services.projections.inspector import InspectorProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    implementation_plan = SolutionImplementationPlanRead(
        plan_id="plan-solution-design-1",
        source_stage_run_id="stage-solution-design-1",
        tasks=[
            ImplementationPlanTaskRead(
                task_id="task-codegen-1",
                order_index=1,
                title="Generate code from the approved design",
                depends_on_task_ids=[],
                target_files=["backend/app/services/projections/inspector.py"],
                target_modules=["backend.app.services.projections.inspector"],
                acceptance_refs=["Q3.3"],
                verification_commands=[
                    "uv run python -m pytest "
                    "backend/tests/projections/test_stage_inspector_projection.py -v"
                ],
                risk_handling="Stop if projection contracts are unclear.",
            )
        ],
        downstream_refs=[
            "code_generation",
            "test_generation_execution",
            "code_review",
        ],
        created_at=NOW + timedelta(minutes=4),
    )
    solution_artifact = SolutionDesignArtifactRead(
        artifact_id="artifact-solution-design-1",
        stage_run_id="stage-solution-design-1",
        technical_plan="Use the projection service to expose grouped stage facts.",
        implementation_plan=implementation_plan,
        impacted_files=["backend/app/services/projections/inspector.py"],
        api_design="GET /api/stages/{stageRunId}/inspector",
        data_flow_design="Read runtime artifacts and stage events.",
        risks=["Do not expose graph_thread_ref."],
        test_strategy="Use projection and API tests.",
        validation_report="Plan validated for Q3.3.",
        requirement_refs=["requirement-1"],
        evidence_refs=["evidence-1"],
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            StageRunModel(
                stage_run_id="stage-solution-design-1",
                run_id="run-active",
                stage_type=StageType.SOLUTION_DESIGN,
                status=StageStatus.COMPLETED,
                attempt_index=1,
                input_ref="input-solution-design-1",
                output_ref="artifact-solution-design-1",
                summary="Solution design completed.",
                started_at=NOW + timedelta(minutes=3),
                ended_at=NOW + timedelta(minutes=5),
                created_at=NOW + timedelta(minutes=3),
                updated_at=NOW + timedelta(minutes=5),
            )
        )
        session.flush()
        session.add_all(
            [
                StageArtifactModel(
                    artifact_id="artifact-solution-design-1",
                    run_id="run-active",
                    stage_run_id="stage-solution-design-1",
                    artifact_type="solution_design",
                    payload_ref="payload-solution-design-1",
                    process={
                        "solution_design_artifact": solution_artifact.model_dump(
                            mode="json"
                        )
                    },
                    metrics={},
                    created_at=NOW + timedelta(minutes=5),
                ),
                ApprovalRequestModel(
                    approval_id="approval-solution-design-1",
                    run_id="run-active",
                    stage_run_id="stage-solution-design-1",
                    approval_type=ApprovalType.SOLUTION_DESIGN_APPROVAL,
                    status=ApprovalStatus.APPROVED,
                    payload_ref="payload-solution-design-1",
                    graph_interrupt_ref="graph-interrupt-approval-1",
                    requested_at=NOW + timedelta(minutes=5),
                    resolved_at=NOW + timedelta(minutes=6),
                    created_at=NOW + timedelta(minutes=5),
                    updated_at=NOW + timedelta(minutes=6),
                ),
            ]
        )
        session.flush()
        session.add(
            ApprovalDecisionModel(
                decision_id="approval-result-solution-design-1",
                approval_id="approval-solution-design-1",
                run_id="run-active",
                decision=ApprovalStatus.APPROVED,
                reason=None,
                decided_by_actor_id="user-1",
                decided_at=NOW + timedelta(minutes=6),
                created_at=NOW + timedelta(minutes=6),
            )
        )
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        inspector = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_stage_inspector("stage-solution-design-1")

    dumped = inspector.model_dump(mode="json")
    assert dumped["implementation_plan"]["tasks"][0]["task_id"] == "task-codegen-1"
    assert dumped["implementation_plan"]["downstream_refs"] == [
        "code_generation",
        "test_generation_execution",
        "code_review",
    ]
    assert dumped["output"]["records"]["implementation_plan_id"] == (
        "plan-solution-design-1"
    )
    assert dumped["artifacts"]["records"]["solution_design_artifact"][
        "implementation_plan"
    ]["plan_id"] == "plan-solution-design-1"
    assert dumped["approval_result_refs"] == ["approval-result-solution-design-1"]
    assert dumped["artifacts"]["records"]["approval_requests"] == [
        {
            "approval_id": "approval-solution-design-1",
            "approval_type": "solution_design_approval",
            "status": "approved",
            "payload_ref": "payload-solution-design-1",
        }
    ]


def test_non_solution_stage_does_not_expose_artifact_implementation_plan(
    tmp_path,
) -> None:
    from backend.app.services.projections.inspector import InspectorProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    implementation_plan = SolutionImplementationPlanRead(
        plan_id="plan-code-generation-should-not-expose",
        source_stage_run_id="stage-active",
        tasks=[
            ImplementationPlanTaskRead(
                task_id="task-from-codegen-process",
                order_index=1,
                title="Internal code generation process task",
                depends_on_task_ids=[],
                target_files=["backend/app/services/projections/inspector.py"],
                target_modules=["backend.app.services.projections.inspector"],
                acceptance_refs=["Q3.3"],
                verification_commands=[
                    "uv run python -m pytest "
                    "backend/tests/projections/test_stage_inspector_projection.py -v"
                ],
                risk_handling=None,
            )
        ],
        downstream_refs=["code_generation"],
        created_at=NOW + timedelta(minutes=7),
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            StageArtifactModel(
                artifact_id="artifact-codegen-process-plan",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="code_generation_process",
                payload_ref="payload-codegen-process-plan",
                process={
                    "implementation_plan": implementation_plan.model_dump(mode="json")
                },
                metrics={},
                created_at=NOW + timedelta(minutes=7),
            )
        )
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        inspector = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_stage_inspector("stage-active")

    dumped = inspector.model_dump(mode="json")
    assert dumped["stage_type"] == "code_generation"
    assert dumped["implementation_plan"] is None
    assert dumped["output"]["records"]["implementation_plan_id"] is None


def test_non_solution_stage_does_not_emit_solution_design_artifact_record(
    tmp_path,
) -> None:
    from backend.app.services.projections.inspector import InspectorProjectionService

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    implementation_plan = SolutionImplementationPlanRead(
        plan_id="plan-nested-codegen-should-not-expose",
        source_stage_run_id="stage-active",
        tasks=[
            ImplementationPlanTaskRead(
                task_id="task-nested-codegen-process",
                order_index=1,
                title="Nested process plan from non-solution stage",
                depends_on_task_ids=[],
                target_files=["backend/app/services/projections/inspector.py"],
                target_modules=["backend.app.services.projections.inspector"],
                acceptance_refs=["Q3.3"],
                verification_commands=[
                    "uv run python -m pytest "
                    "backend/tests/projections/test_stage_inspector_projection.py -v"
                ],
                risk_handling=None,
            )
        ],
        downstream_refs=["code_generation"],
        created_at=NOW + timedelta(minutes=7),
    )
    solution_artifact = SolutionDesignArtifactRead(
        artifact_id="artifact-nested-solution-design-should-not-expose",
        stage_run_id="stage-active",
        technical_plan="This malformed non-solution payload must stay hidden.",
        implementation_plan=implementation_plan,
        impacted_files=["backend/app/services/projections/inspector.py"],
        api_design=None,
        data_flow_design=None,
        risks=[],
        test_strategy="Use projection tests.",
        validation_report="Valid schema, invalid stage boundary.",
        requirement_refs=[],
        evidence_refs=[],
    )
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            StageArtifactModel(
                artifact_id="artifact-codegen-nested-solution-design",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="code_generation_process",
                payload_ref="payload-codegen-nested-solution-design",
                process={
                    "solution_design_artifact": solution_artifact.model_dump(
                        mode="json"
                    )
                },
                metrics={},
                created_at=NOW + timedelta(minutes=7),
            )
        )
        session.commit()

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        inspector = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_stage_inspector("stage-active")

    dumped = inspector.model_dump(mode="json")
    assert dumped["stage_type"] == "code_generation"
    assert dumped["implementation_plan"] is None
    assert "solution_design_artifact" not in dumped["artifacts"]["records"]


def test_stage_inspector_projection_rejects_missing_stage_hidden_session_and_hidden_project(
    tmp_path,
) -> None:
    from backend.app.services.projections.inspector import (
        InspectorProjectionService,
        InspectorProjectionServiceError,
    )

    manager = _manager(tmp_path)
    _seed_workspace(manager)
    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_stage_inspector("stage-missing")
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Stage inspector was not found."

    manager = _manager(tmp_path / "hidden-session")
    _seed_workspace(manager)
    with manager.session(DatabaseRole.CONTROL) as session:
        removed = session.get(SessionModel, "session-1")
        assert removed is not None
        removed.is_visible = False
        removed.visibility_removed_at = NOW
        session.add(removed)
        session.commit()
    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_stage_inspector("stage-active")
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Stage inspector was not found."

    manager = _manager(tmp_path / "hidden-project")
    _seed_workspace(manager)
    with manager.session(DatabaseRole.CONTROL) as session:
        removed = session.get(ProjectModel, "project-1")
        assert removed is not None
        removed.is_visible = False
        removed.visibility_removed_at = NOW
        session.add(removed)
        session.commit()
    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_stage_inspector("stage-active")
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Stage inspector was not found."
