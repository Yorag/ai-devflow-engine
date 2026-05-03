from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.runtime import (
    ClarificationRecordModel,
    RunControlRecordModel,
    StageArtifactModel,
)
from backend.app.domain.enums import RunControlRecordType, StageType
from backend.app.schemas import common
from backend.app.schemas.feed import ControlItemFeedEntry, ExecutionNodeProjection
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.projections.inspector import (
    InspectorProjectionService,
    InspectorProjectionServiceError,
)
from backend.tests.projections.test_workspace_projection import NOW, _manager, _seed_workspace, _trace


def test_control_item_detail_projection_builds_clarification_sections_from_runtime_artifacts_and_events(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_control_clarification_projection(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_control_item_detail("control-clarification-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["control_record_id"] == "control-clarification-1"
    assert dumped["run_id"] == "run-active"
    assert dumped["control_type"] == "clarification_wait"
    assert set(dumped) >= {
        "identity",
        "input",
        "process",
        "output",
        "artifacts",
        "metrics",
    }
    assert dumped["input"]["records"]["trigger_reason"] == "Need the user to clarify file scope."
    assert (
        dumped["input"]["records"]["clarification_question"]
        == "Should the change affect backend only?"
    )
    assert dumped["process"]["records"]["control_event"]["control_record_id"] == (
        "control-clarification-1"
    )
    assert dumped["process"]["records"]["history_attempt_refs"] == ["run-active:attempt-2"]
    assert dumped["output"]["records"]["result_status"] == "waiting_clarification"
    assert dumped["artifacts"]["log_refs"] == ["log-control-clarification-1"]
    assert dumped["metrics"] == {"retry_index": 0, "source_attempt_index": 1}
    assert dumped["artifacts"]["records"]["artifact_refs"] == [
        "artifact-control-clarification-1"
    ]
    assert dumped["artifacts"]["records"]["payload_refs"] == [
        "payload-control-clarification-1"
    ]
    assert dumped["artifacts"]["records"]["artifact_types"] == ["control_item_trace"]
    assert dumped["output"]["records"]["result_snapshot"] == {
        "result_status": "waiting_clarification"
    }
    assert "artifact-unrelated-later-1" not in str(dumped)
    assert "payload-unrelated-later-1" not in str(dumped)
    assert "Should not override control item detail." not in str(dumped)
    assert "graph_thread_ref" not in str(dumped)
    assert "graph_thread_id" not in str(dumped)


def test_control_item_detail_projection_builds_retry_sections_without_clarification_record(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_retry_control_projection(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_control_item_detail("control-retry-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["control_type"] == "retry"
    assert dumped["input"]["records"]["clarification_question"] is None
    assert dumped["output"]["records"]["target_stage_type"] == "code_generation"
    assert dumped["metrics"] == {"retry_index": 2, "source_attempt_index": 1}
    assert dumped["artifacts"]["records"]["artifact_refs"] == ["artifact-control-retry-1"]
    assert dumped["artifacts"]["records"]["payload_refs"] == ["payload-control-retry-1"]
    assert dumped["artifacts"]["records"]["artifact_types"] == ["control_item_trace"]
    assert dumped["output"]["records"]["result_snapshot"] == {
        "result_status": "accepted",
        "next_stage_type": "code_generation",
    }
    assert "artifact-control-other-1" not in str(dumped)
    assert "payload-control-other-1" not in str(dumped)
    assert "Different control item on same stage." not in str(dumped)


def test_control_item_detail_projection_excludes_unmatched_control_trace_artifacts(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_retry_control_projection(manager)
    _seed_control_without_related_artifact(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_control_item_detail("control-no-artifact-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["control_record_id"] == "control-no-artifact-1"
    assert dumped["input"]["records"]["trigger_reason"] == (
        "No related control artifact exists for this control item."
    )
    assert dumped["process"]["log_refs"] == []
    assert dumped["artifacts"]["records"]["artifact_refs"] == []
    assert dumped["artifacts"]["records"]["payload_refs"] == []
    assert dumped["artifacts"]["records"]["artifact_types"] == []
    assert dumped["metrics"] == {}
    assert dumped["output"]["records"]["result_snapshot"] is None
    assert "artifact-control-retry-1" not in str(dumped)
    assert "artifact-control-other-1" not in str(dumped)


def test_control_item_detail_projection_ignores_malformed_stage_node_payloads(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_control_clarification_projection(manager)

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
        original_list_for_session = service._event_store.list_for_session

        def _list_with_malformed_stage_node(session_id: str):
            return [
                *original_list_for_session(session_id),
                SimpleNamespace(
                    run_id="run-active",
                    stage_run_id="stage-active",
                    payload={
                        "stage_node": {
                            "entry_id": "entry-stage-malformed-1",
                            "run_id": "run-active",
                            "occurred_at": (NOW + timedelta(minutes=8)).isoformat(),
                            "stage_run_id": "stage-active",
                            "type": "stage_node",
                        }
                    },
                ),
            ]

        monkeypatch.setattr(
            service._event_store,
            "list_for_session",
            _list_with_malformed_stage_node,
        )
        projection = service.get_control_item_detail("control-clarification-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["control_record_id"] == "control-clarification-1"
    assert dumped["process"]["records"]["stage_node_refs"] == [
        "entry-stage-active",
        "entry-stage-for-control-clarification-1",
    ]
    assert "entry-stage-malformed-1" not in dumped["process"]["records"]["stage_node_refs"]
    assert dumped["input"]["records"]["trigger_reason"] == "Need the user to clarify file scope."


def test_control_item_detail_projection_does_not_expose_clarification_for_retry_payload_ref_collision(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_retry_control_projection(manager)
    _seed_retry_payload_ref_collision_with_clarification(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_control_item_detail("control-retry-collision-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["control_type"] == "retry"
    assert dumped["input"]["records"]["clarification_question"] is None
    assert dumped["input"]["records"]["clarification_answer"] is None
    assert dumped["artifacts"]["records"]["clarification_id"] is None


def test_control_item_detail_projection_rejects_missing_tool_confirmation_hidden_session_and_hidden_project(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_retry_control_projection(manager)

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
            service.get_control_item_detail("missing-control-item")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Control item inspector was not found."

    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RunControlRecordModel(
                control_record_id="control-tool-1",
                run_id="run-active",
                stage_run_id="stage-active",
                control_type=RunControlRecordType.TOOL_CONFIRMATION,
                source_stage_type=StageType.CODE_GENERATION,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="tool-confirmation-1",
                graph_interrupt_ref="interrupt-tool-1",
                occurred_at=NOW + timedelta(minutes=8),
                created_at=NOW + timedelta(minutes=8),
            )
        )
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
            service.get_control_item_detail("control-tool-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Control item inspector was not found."

    with manager.session(DatabaseRole.CONTROL) as session:
        hidden_session = session.get(SessionModel, "session-1")
        assert hidden_session is not None
        hidden_session.is_visible = False
        hidden_session.visibility_removed_at = NOW + timedelta(minutes=9)
        session.add(hidden_session)
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
            service.get_control_item_detail("control-retry-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Control item inspector was not found."

    project_manager = _manager(tmp_path / "hidden-project")
    _seed_workspace(project_manager)
    _seed_retry_control_projection(project_manager)
    with project_manager.session(DatabaseRole.CONTROL) as session:
        hidden_project = session.get(ProjectModel, "project-1")
        assert hidden_project is not None
        hidden_project.is_visible = False
        hidden_project.visibility_removed_at = NOW + timedelta(minutes=9)
        session.add(hidden_project)
        session.commit()

    with (
        project_manager.session(DatabaseRole.CONTROL) as control_session,
        project_manager.session(DatabaseRole.RUNTIME) as runtime_session,
        project_manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        )
        with pytest.raises(InspectorProjectionServiceError) as exc_info:
            service.get_control_item_detail("control-retry-1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Control item inspector was not found."


def _seed_control_clarification_projection(manager) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            ClarificationRecordModel(
                clarification_id="clarification-1",
                run_id="run-active",
                stage_run_id="stage-active",
                question="Should the change affect backend only?",
                answer=None,
                payload_ref="clarification-payload-1",
                graph_interrupt_ref="interrupt-clarification-1",
                requested_at=NOW + timedelta(minutes=7),
                answered_at=None,
                created_at=NOW + timedelta(minutes=7),
                updated_at=NOW + timedelta(minutes=7),
            )
        )
        session.add(
            RunControlRecordModel(
                control_record_id="control-clarification-1",
                run_id="run-active",
                stage_run_id="stage-active",
                control_type=RunControlRecordType.CLARIFICATION_WAIT,
                source_stage_type=StageType.CODE_GENERATION,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="clarification-1",
                graph_interrupt_ref="interrupt-clarification-1",
                occurred_at=NOW + timedelta(minutes=7),
                created_at=NOW + timedelta(minutes=7),
            )
        )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-control-clarification-1",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="control_item_trace",
                payload_ref="payload-control-clarification-1",
                process={
                    "control_record_id": "control-clarification-1",
                    "context_refs": ["context-scope-1", "context-file-2"],
                    "trigger_reason": "Need the user to clarify file scope.",
                    "control_process_trace_ref": "trace-control-clarification-1",
                    "history_attempt_refs": ["run-active:attempt-2"],
                    "output_snapshot": {
                        "result_status": "waiting_clarification",
                        "graph_thread_ref": "graph-thread-hidden",
                    },
                    "artifact_refs": ["artifact-control-clarification-1", "artifact-plan-1"],
                    "log_refs": ["log-control-clarification-1"],
                    "tool_confirmation_trace_ref": "trace-tool-existing-1",
                },
                metrics={"retry_index": 0, "source_attempt_index": 1},
                created_at=NOW + timedelta(minutes=7),
            )
        )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-unrelated-later-1",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="code_generation_process",
                payload_ref="payload-unrelated-later-1",
                process={
                    "trigger_reason": "Should not override control item detail.",
                    "output_snapshot": {
                        "result_status": "succeeded",
                        "next_stage_type": "delivery",
                    },
                    "log_refs": ["log-unrelated-later-1"],
                },
                metrics={"retry_index": 99, "source_attempt_index": 99},
                created_at=NOW + timedelta(minutes=8),
            )
        )
        session.commit()

    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(
                [
                    "event-control-clarification-1",
                    "event-stage-control-clarification-1",
                ]
            ).__next__,
        )
        store.append(
            DomainEventType.CLARIFICATION_REQUESTED,
            payload={
                "run_id": "run-active",
                "stage_run_id": "stage-active",
                "control_item": ControlItemFeedEntry(
                    entry_id="entry-control-clarification-1",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7),
                    control_record_id="control-clarification-1",
                    control_type=common.ControlItemType.CLARIFICATION_WAIT,
                    source_stage_type=common.StageType.CODE_GENERATION,
                    target_stage_type=common.StageType.CODE_GENERATION,
                    title="Clarification required",
                    summary="Clarify whether backend-only scope is intended.",
                    payload_ref="clarification-1",
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        store.append(
            DomainEventType.STAGE_UPDATED,
            payload={
                "stage_node": ExecutionNodeProjection(
                    entry_id="entry-stage-for-control-clarification-1",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7),
                    stage_run_id="stage-active",
                    stage_type=common.StageType.CODE_GENERATION,
                    status=common.StageStatus.WAITING_CLARIFICATION,
                    attempt_index=1,
                    started_at=NOW + timedelta(minutes=2),
                    ended_at=None,
                    summary="Waiting for the user to clarify file scope.",
                    items=[],
                    metrics={},
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()


def _seed_retry_control_projection(manager) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RunControlRecordModel(
                control_record_id="control-retry-1",
                run_id="run-active",
                stage_run_id="stage-active",
                control_type=RunControlRecordType.RETRY,
                source_stage_type=StageType.CODE_REVIEW,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="retry-payload-1",
                graph_interrupt_ref=None,
                occurred_at=NOW + timedelta(minutes=7),
                created_at=NOW + timedelta(minutes=7),
            )
        )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-control-retry-1",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="control_item_trace",
                payload_ref="payload-control-retry-1",
                process={
                    "control_record_id": "control-retry-1",
                    "trigger_reason": "Regression test failed after review.",
                    "history_attempt_refs": [
                        "run-active:attempt-1",
                        "run-active:attempt-2",
                    ],
                    "output_snapshot": {
                        "result_status": "accepted",
                        "next_stage_type": "code_generation",
                        "graph_thread_id": "hidden-thread-id",
                    },
                    "artifact_refs": ["artifact-retry-plan-1"],
                    "metrics": {"retry_index": 2, "source_attempt_index": 1},
                },
                metrics={"retry_index": 2, "source_attempt_index": 1},
                created_at=NOW + timedelta(minutes=7),
            )
        )
        session.add(
            RunControlRecordModel(
                control_record_id="control-other-1",
                run_id="run-active",
                stage_run_id="stage-active",
                control_type=RunControlRecordType.RETRY,
                source_stage_type=StageType.CODE_REVIEW,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="retry-payload-other-1",
                graph_interrupt_ref=None,
                occurred_at=NOW + timedelta(minutes=8),
                created_at=NOW + timedelta(minutes=8),
            )
        )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-control-other-1",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="control_item_trace",
                payload_ref="payload-control-other-1",
                process={
                    "control_record_id": "control-other-1",
                    "trigger_reason": "Different control item on same stage.",
                    "history_attempt_refs": ["run-active:attempt-9"],
                    "output_snapshot": {
                        "result_status": "rejected",
                        "next_stage_type": "rollback",
                    },
                    "log_refs": ["log-control-other-1"],
                    "metrics": {"retry_index": 9, "source_attempt_index": 9},
                },
                metrics={"retry_index": 9, "source_attempt_index": 9},
                created_at=NOW + timedelta(minutes=8),
            )
        )
        session.commit()

    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(["event-control-retry-1"]).__next__,
        )
        store.append(
            DomainEventType.RETRY_TRIGGERED,
            payload={
                "control_item": ControlItemFeedEntry(
                    entry_id="entry-control-retry-1",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=7),
                    control_record_id="control-retry-1",
                    control_type=common.ControlItemType.RETRY,
                    source_stage_type=common.StageType.CODE_REVIEW,
                    target_stage_type=common.StageType.CODE_GENERATION,
                    title="Retry code generation",
                    summary="Code review found a regression that requires regeneration.",
                    payload_ref="retry-payload-1",
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()


def _seed_control_without_related_artifact(manager) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            RunControlRecordModel(
                control_record_id="control-no-artifact-1",
                run_id="run-active",
                stage_run_id="stage-active",
                control_type=RunControlRecordType.RETRY,
                source_stage_type=StageType.CODE_REVIEW,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="retry-payload-no-artifact-1",
                graph_interrupt_ref=None,
                occurred_at=NOW + timedelta(minutes=9),
                created_at=NOW + timedelta(minutes=9),
            )
        )
        session.commit()

    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(["event-control-no-artifact-1"]).__next__,
        )
        store.append(
            DomainEventType.RETRY_TRIGGERED,
            payload={
                "control_item": ControlItemFeedEntry(
                    entry_id="entry-control-no-artifact-1",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=9),
                    control_record_id="control-no-artifact-1",
                    control_type=common.ControlItemType.RETRY,
                    source_stage_type=common.StageType.CODE_REVIEW,
                    target_stage_type=common.StageType.CODE_GENERATION,
                    title="Retry without artifact",
                    summary="No related control artifact exists for this control item.",
                    payload_ref="retry-payload-no-artifact-1",
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()


def _seed_retry_payload_ref_collision_with_clarification(manager) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            ClarificationRecordModel(
                clarification_id="clarification-collision-1",
                run_id="run-active",
                stage_run_id="stage-active",
                question="This clarification must not leak into retry detail.",
                answer="No clarification data should appear.",
                payload_ref="clarification-collision-payload-1",
                graph_interrupt_ref="interrupt-clarification-collision-1",
                requested_at=NOW + timedelta(minutes=9),
                answered_at=NOW + timedelta(minutes=10),
                created_at=NOW + timedelta(minutes=9),
                updated_at=NOW + timedelta(minutes=10),
            )
        )
        session.add(
            RunControlRecordModel(
                control_record_id="control-retry-collision-1",
                run_id="run-active",
                stage_run_id="stage-active",
                control_type=RunControlRecordType.RETRY,
                source_stage_type=StageType.CODE_REVIEW,
                target_stage_type=StageType.CODE_GENERATION,
                payload_ref="clarification-collision-1",
                graph_interrupt_ref=None,
                occurred_at=NOW + timedelta(minutes=10),
                created_at=NOW + timedelta(minutes=10),
            )
        )
        session.add(
            StageArtifactModel(
                artifact_id="artifact-control-retry-collision-1",
                run_id="run-active",
                stage_run_id="stage-active",
                artifact_type="control_item_trace",
                payload_ref="payload-control-retry-collision-1",
                process={
                    "control_record_id": "control-retry-collision-1",
                    "trigger_reason": "Payload ref collides with clarification id.",
                    "output_snapshot": {
                        "result_status": "accepted",
                        "next_stage_type": "code_generation",
                    },
                },
                metrics={"retry_index": 1, "source_attempt_index": 1},
                created_at=NOW + timedelta(minutes=10),
            )
        )
        session.commit()

    with manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(["event-control-retry-collision-1"]).__next__,
        )
        store.append(
            DomainEventType.RETRY_TRIGGERED,
            payload={
                "control_item": ControlItemFeedEntry(
                    entry_id="entry-control-retry-collision-1",
                    run_id="run-active",
                    occurred_at=NOW + timedelta(minutes=10),
                    control_record_id="control-retry-collision-1",
                    control_type=common.ControlItemType.RETRY,
                    source_stage_type=common.StageType.CODE_REVIEW,
                    target_stage_type=common.StageType.CODE_GENERATION,
                    title="Retry with colliding payload_ref",
                    summary="Retry detail must not expose clarification data.",
                    payload_ref="clarification-collision-1",
                ).model_dump(mode="json")
            },
            trace_context=_trace(run_id="run-active", stage_run_id="stage-active"),
        )
        session.commit()
