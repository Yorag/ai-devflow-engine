from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import SessionModel, StartupPublicationModel
from backend.app.db.models.event import DomainEventModel
from backend.app.db.models.graph import GraphDefinitionModel, GraphThreadModel
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeLimitSnapshotModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    RunStatus,
    RunTriggerSource,
    SessionStatus,
    StageStatus,
    StageType,
)
from backend.app.schemas import common
from backend.app.schemas.feed import MessageFeedEntry
from backend.app.schemas.run import RunSummaryProjection
from backend.app.services.events import DomainEventType, EventStore
from backend.app.services.publication_boundary import (
    PublicationBoundaryService,
    PublicationBoundaryServiceError,
)
from backend.app.services.sessions import DEFAULT_SESSION_DISPLAY_NAME, SessionService
from backend.tests.projections.test_workspace_projection import _trace
from backend.tests.services.test_start_first_run import (
    NOW,
    RecordingAuditService,
    RecordingLogWriter,
    build_manager,
    build_settings,
    build_trace,
    seed_control_plane,
)


@dataclass(frozen=True)
class PendingStartupSeed:
    session_id: str
    run_id: str
    stage_run_id: str
    publication_id: str


def _build_seeded_manager_with_draft_session(
    tmp_path: Path,
) -> tuple[object, str]:
    settings = build_settings(tmp_path)
    manager = build_manager(settings)
    audit = RecordingAuditService()
    log_writer = RecordingLogWriter()

    with manager.session(DatabaseRole.CONTROL) as control_session:
        seed_control_plane(
            control_session,
            settings=settings,
            audit=audit,
            log_writer=log_writer,
        )
        draft = SessionService(
            control_session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_session(
            project_id="project-default",
            trace_context=build_trace(),
        )

    return manager, draft.session_id


def _seed_pending_startup_product_set(
    manager,
    *,
    session_id: str,
    run_id: str = "run-startup-1",
    stage_run_id: str = "stage-run-startup-1",
) -> PendingStartupSeed:
    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.GRAPH) as graph_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        boundary = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        publication = boundary.begin_startup_publication(
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            trace_context=build_trace(),
        )

        runtime_session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id=f"runtime-limit-{run_id}",
                    run_id=run_id,
                    agent_limits={"max_react_iterations_per_stage": 3},
                    context_limits={"grep_max_results": 10},
                    source_config_version="runtime-config-startup",
                    hard_limits_version="platform-hard-limits-v1",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id=f"policy-{run_id}",
                    run_id=run_id,
                    provider_call_policy={"network_error_max_retries": 1},
                    source_config_version="runtime-config-startup",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        runtime_session.commit()
        runtime_session.add(
            PipelineRunModel(
                run_id=run_id,
                session_id=session_id,
                project_id="project-default",
                attempt_index=1,
                status=RunStatus.RUNNING,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-startup",
                graph_definition_ref=f"graph-definition-{run_id}",
                graph_thread_ref=f"graph-thread-{run_id}",
                workspace_ref=f"workspace-{run_id}",
                runtime_limit_snapshot_ref=f"runtime-limit-{run_id}",
                provider_call_policy_snapshot_ref=f"policy-{run_id}",
                delivery_channel_snapshot_ref=None,
                current_stage_run_id=None,
                trace_id=f"trace-{run_id}",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        runtime_session.commit()
        runtime_session.add(
            StageRunModel(
                stage_run_id=stage_run_id,
                run_id=run_id,
                stage_type=StageType.REQUIREMENT_ANALYSIS,
                status=StageStatus.RUNNING,
                attempt_index=1,
                graph_node_key="requirement_analysis",
                stage_contract_ref="requirement_analysis",
                input_ref=None,
                output_ref=None,
                summary="Requirement Analysis started from the first user requirement.",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        runtime_session.commit()
        seeded_run = runtime_session.get(PipelineRunModel, run_id)
        assert seeded_run is not None
        seeded_run.current_stage_run_id = stage_run_id
        seeded_run.updated_at = NOW
        runtime_session.add(seeded_run)
        runtime_session.commit()

        graph_session.add_all(
            [
                GraphDefinitionModel(
                    graph_definition_id=f"graph-definition-{run_id}",
                    run_id=run_id,
                    template_snapshot_ref="template-snapshot-startup",
                    graph_version="graph-v1",
                    stage_nodes=[],
                    stage_contracts={},
                    interrupt_policy={},
                    retry_policy={},
                    delivery_routing_policy={},
                    schema_version="graph-definition-v1",
                    created_at=NOW,
                ),
                GraphThreadModel(
                    graph_thread_id=f"graph-thread-{run_id}",
                    run_id=run_id,
                    graph_definition_id=f"graph-definition-{run_id}",
                    checkpoint_namespace=f"{run_id}-main",
                    current_node_key="requirement_analysis",
                    current_interrupt_id=None,
                    status="running",
                    last_checkpoint_ref=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        graph_session.commit()

        store = EventStore(
            event_session,
            now=lambda: NOW,
            id_factory=iter(
                [
                    f"event-run-created-{run_id}",
                    f"event-message-{run_id}",
                ]
            ).__next__,
        )
        store.append(
            DomainEventType.PIPELINE_RUN_CREATED,
            payload={
                "run": RunSummaryProjection(
                    run_id=run_id,
                    attempt_index=1,
                    status=RunStatus.RUNNING,
                    trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                    started_at=NOW,
                    ended_at=None,
                    current_stage_type=StageType.REQUIREMENT_ANALYSIS,
                    is_active=True,
                ).model_dump(mode="json")
            },
            trace_context=_trace(
                session_id=session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
            ),
        )
        store.append(
            DomainEventType.SESSION_MESSAGE_APPENDED,
            payload={
                "message_item": MessageFeedEntry(
                    entry_id=f"entry-message-{run_id}",
                    run_id=run_id,
                    type=common.FeedEntryType.USER_MESSAGE,
                    occurred_at=NOW,
                    message_id=f"message-{run_id}",
                    author="user",
                    content="Pending startup requirement.",
                    stage_run_id=stage_run_id,
                ).model_dump(mode="json")
            },
            trace_context=_trace(
                session_id=session_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
            ),
        )
        event_session.commit()

        return PendingStartupSeed(
            session_id=session_id,
            run_id=run_id,
            stage_run_id=stage_run_id,
            publication_id=publication.publication_id,
        )


def test_visible_run_ids_for_session_excludes_pending_publication(
    tmp_path: Path,
) -> None:
    manager, session_id = _build_seeded_manager_with_draft_session(tmp_path)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.GRAPH) as graph_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        service.begin_startup_publication(
            session_id=session_id,
            run_id="run-startup-pending",
            stage_run_id="stage-run-startup-pending",
            trace_context=build_trace(),
        )

        assert service.visible_run_ids_for_session(session_id=session_id) == set()


def test_begin_startup_publication_fails_if_session_hidden_between_check_and_insert(
    tmp_path: Path,
) -> None:
    manager, session_id = _build_seeded_manager_with_draft_session(tmp_path)

    class RaceControlSession:
        injected = False

        def __init__(self, wrapped_session) -> None:  # noqa: ANN001
            self._wrapped_session = wrapped_session

        def _hide_session_once(self) -> None:
            if not self.injected:
                self.injected = True
                with manager.session(DatabaseRole.CONTROL) as concurrent_session:
                    row = concurrent_session.get(SessionModel, session_id)
                    assert row is not None
                    row.is_visible = False
                    row.visibility_removed_at = NOW
                    row.updated_at = NOW
                    concurrent_session.add(row)
                    concurrent_session.commit()

        def get(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            return self._wrapped_session.get(*args, **kwargs)

        def add(self, value) -> None:  # noqa: ANN001
            if isinstance(value, StartupPublicationModel):
                self._hide_session_once()
            self._wrapped_session.add(value)

        def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            self._hide_session_once()
            return self._wrapped_session.execute(*args, **kwargs)

        def commit(self) -> None:
            self._wrapped_session.commit()

        def rollback(self) -> None:
            self._wrapped_session.rollback()

        def query(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            return self._wrapped_session.query(*args, **kwargs)

        def __getattr__(self, name: str):  # noqa: ANN204
            return getattr(self._wrapped_session, name)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.GRAPH) as graph_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = PublicationBoundaryService(
            control_session=RaceControlSession(control_session),
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        with pytest.raises(PublicationBoundaryServiceError) as exc_info:
            service.begin_startup_publication(
                session_id=session_id,
                run_id="run-startup-raced-delete",
                stage_run_id="stage-run-startup-raced-delete",
                trace_context=build_trace(),
            )
        publications = (
            control_session.query(StartupPublicationModel)
            .filter_by(session_id=session_id)
            .all()
        )
        saved_session = control_session.get(SessionModel, session_id)

    assert exc_info.value.error_code is ErrorCode.NOT_FOUND
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Session was not found."
    assert publications == []
    assert saved_session is not None
    assert saved_session.is_visible is False


def test_publish_startup_visibility_marks_session_running_and_exposes_run(
    tmp_path: Path,
) -> None:
    manager, session_id = _build_seeded_manager_with_draft_session(tmp_path)
    seeded = _seed_pending_startup_product_set(manager, session_id=session_id)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.GRAPH) as graph_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        published = service.publish_startup_visibility(
            publication_id=seeded.publication_id,
            session_id=seeded.session_id,
            run_id=seeded.run_id,
            stage_run_id=seeded.stage_run_id,
            trace_context=build_trace(),
            published_at=NOW,
        )

        assert published.run_id == seeded.run_id
        assert service.visible_run_ids_for_session(session_id=seeded.session_id) == {
            seeded.run_id
        }

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, seeded.session_id)
        publication = session.get(StartupPublicationModel, seeded.publication_id)

    assert saved_session is not None
    assert saved_session.status is SessionStatus.RUNNING
    assert saved_session.current_run_id == seeded.run_id
    assert saved_session.latest_stage_type is StageType.REQUIREMENT_ANALYSIS
    assert publication is not None
    assert publication.publication_state == "published"
    assert publication.pending_session_id is None


def test_publish_startup_visibility_does_not_auto_title_over_concurrent_rename(
    tmp_path: Path,
) -> None:
    manager, session_id = _build_seeded_manager_with_draft_session(tmp_path)
    seeded = _seed_pending_startup_product_set(manager, session_id=session_id)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.GRAPH) as graph_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        stale_session = control_session.get(SessionModel, session_id)
        assert stale_session is not None
        assert stale_session.display_name == DEFAULT_SESSION_DISPLAY_NAME

        with manager.session(DatabaseRole.CONTROL) as concurrent_session:
            renamed = concurrent_session.get(SessionModel, session_id)
            assert renamed is not None
            renamed.display_name = "Manual planning session"
            concurrent_session.add(renamed)
            concurrent_session.commit()

        service = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        service.publish_startup_visibility(
            publication_id=seeded.publication_id,
            session_id=seeded.session_id,
            run_id=seeded.run_id,
            stage_run_id=seeded.stage_run_id,
            trace_context=build_trace(),
            published_at=NOW,
            session_display_name="Auto generated session name",
            session_display_name_expected_current=DEFAULT_SESSION_DISPLAY_NAME,
        )

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, seeded.session_id)

    assert saved_session is not None
    assert saved_session.display_name == "Manual planning session"
    assert saved_session.status is SessionStatus.RUNNING
    assert saved_session.current_run_id == seeded.run_id


def test_abort_startup_publication_deletes_staged_rows_and_marks_aborted(
    tmp_path: Path,
) -> None:
    manager, session_id = _build_seeded_manager_with_draft_session(tmp_path)
    seeded = _seed_pending_startup_product_set(manager, session_id=session_id)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.GRAPH) as graph_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        service.abort_startup_publication(
            publication_id=seeded.publication_id,
            session_id=seeded.session_id,
            run_id=seeded.run_id,
            reason="runtime snapshot failure",
            trace_context=build_trace(),
            aborted_at=NOW,
        )

    with manager.session(DatabaseRole.CONTROL) as session:
        saved_session = session.get(SessionModel, seeded.session_id)
        publication = session.get(StartupPublicationModel, seeded.publication_id)
        assert saved_session is not None
        assert saved_session.status is SessionStatus.DRAFT
        assert saved_session.current_run_id is None
        assert saved_session.latest_stage_type is None
        assert publication is not None
        assert publication.publication_state == "aborted"
        assert publication.pending_session_id is None

    with manager.session(DatabaseRole.RUNTIME) as session:
        assert session.get(PipelineRunModel, seeded.run_id) is None
        assert session.get(StageRunModel, seeded.stage_run_id) is None
        assert (
            session.query(RuntimeLimitSnapshotModel)
            .filter_by(run_id=seeded.run_id)
            .count()
            == 0
        )
        assert (
            session.query(ProviderCallPolicySnapshotModel)
            .filter_by(run_id=seeded.run_id)
            .count()
            == 0
        )

    with manager.session(DatabaseRole.GRAPH) as session:
        assert (
            session.query(GraphDefinitionModel)
            .filter_by(run_id=seeded.run_id)
            .count()
            == 0
        )
        assert (
            session.query(GraphThreadModel)
            .filter_by(run_id=seeded.run_id)
            .count()
            == 0
        )

    with manager.session(DatabaseRole.EVENT) as session:
        assert (
            session.query(DomainEventModel)
            .filter_by(run_id=seeded.run_id)
            .count()
            == 0
        )


def test_begin_startup_publication_requires_cleanup_before_retry(
    tmp_path: Path,
) -> None:
    manager, session_id = _build_seeded_manager_with_draft_session(tmp_path)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.GRAPH) as graph_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        service = PublicationBoundaryService(
            control_session=control_session,
            runtime_session=runtime_session,
            graph_session=graph_session,
            event_session=event_session,
            now=lambda: NOW,
        )
        pending = service.begin_startup_publication(
            session_id=session_id,
            run_id="run-startup-first",
            stage_run_id="stage-run-startup-first",
            trace_context=build_trace(),
        )

        with pytest.raises(PublicationBoundaryServiceError) as exc_info:
            service.begin_startup_publication(
                session_id=session_id,
                run_id="run-startup-second",
                stage_run_id="stage-run-startup-second",
                trace_context=build_trace(),
            )

        assert exc_info.value.error_code is ErrorCode.VALIDATION_ERROR
        assert exc_info.value.status_code == 409

        service.abort_startup_publication(
            publication_id=pending.publication_id,
            session_id=session_id,
            run_id="run-startup-first",
            reason="manual cleanup before retry",
            trace_context=build_trace(),
            aborted_at=NOW,
        )

        replacement = service.begin_startup_publication(
            session_id=session_id,
            run_id="run-startup-second",
            stage_run_id="stage-run-startup-second",
            trace_context=build_trace(),
        )

        assert replacement.run_id == "run-startup-second"
        assert service.visible_run_ids_for_session(session_id=session_id) == set()
