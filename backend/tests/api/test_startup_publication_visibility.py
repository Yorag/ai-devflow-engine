from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import SessionModel, StartupPublicationModel
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
from backend.tests.api.test_query_api import build_query_api_app
from backend.tests.projections.test_workspace_projection import NOW, _trace


@dataclass(frozen=True)
class PendingStartupSeed:
    session_id: str
    run_id: str
    stage_run_id: str
    publication_id: str


def _seed_pending_startup(app) -> PendingStartupSeed:
    seeded = PendingStartupSeed(
        session_id="session-startup-pending",
        run_id="run-startup-pending",
        stage_run_id="stage-run-startup-pending",
        publication_id="startup-publication-pending",
    )

    with app.state.database_manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            SessionModel(
                session_id=seeded.session_id,
                project_id="project-1",
                display_name="Pending startup session",
                status=SessionStatus.DRAFT,
                selected_template_id="template-feature",
                current_run_id=None,
                latest_stage_type=None,
                is_visible=True,
                visibility_removed_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            StartupPublicationModel(
                publication_id=seeded.publication_id,
                session_id=seeded.session_id,
                run_id=seeded.run_id,
                stage_run_id=seeded.stage_run_id,
                publication_state="pending",
                pending_session_id=seeded.session_id,
                published_at=None,
                aborted_at=None,
                abort_reason=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-startup-pending",
                    run_id=seeded.run_id,
                    agent_limits={"max_react_iterations_per_stage": 3},
                    context_limits={"grep_max_results": 10},
                    source_config_version="runtime-config-startup-pending",
                    hard_limits_version="platform-hard-limits-v1",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="policy-startup-pending",
                    run_id=seeded.run_id,
                    provider_call_policy={"network_error_max_retries": 1},
                    source_config_version="runtime-config-startup-pending",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
        session.add(
            PipelineRunModel(
                run_id=seeded.run_id,
                session_id=seeded.session_id,
                project_id="project-1",
                attempt_index=1,
                status=RunStatus.RUNNING,
                trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
                template_snapshot_ref="template-snapshot-startup-pending",
                graph_definition_ref="graph-definition-startup-pending",
                graph_thread_ref="graph-thread-startup-pending",
                workspace_ref="workspace-startup-pending",
                runtime_limit_snapshot_ref="runtime-limit-startup-pending",
                provider_call_policy_snapshot_ref="policy-startup-pending",
                delivery_channel_snapshot_ref=None,
                current_stage_run_id=None,
                trace_id="trace-startup-pending",
                started_at=NOW,
                ended_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
        session.add(
            StageRunModel(
                stage_run_id=seeded.stage_run_id,
                run_id=seeded.run_id,
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
        session.commit()
        seeded_run = session.get(PipelineRunModel, seeded.run_id)
        assert seeded_run is not None
        seeded_run.current_stage_run_id = seeded.stage_run_id
        seeded_run.updated_at = NOW
        session.add(seeded_run)
        session.commit()

    with app.state.database_manager.session(DatabaseRole.EVENT) as session:
        store = EventStore(
            session,
            now=lambda: NOW,
            id_factory=iter(
                [
                    "event-run-created-startup-pending",
                    "event-message-startup-pending",
                ]
            ).__next__,
        )
        store.append(
            DomainEventType.PIPELINE_RUN_CREATED,
            payload={
                "run": RunSummaryProjection(
                    run_id=seeded.run_id,
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
                session_id=seeded.session_id,
                run_id=seeded.run_id,
                stage_run_id=seeded.stage_run_id,
            ),
        )
        store.append(
            DomainEventType.SESSION_MESSAGE_APPENDED,
            payload={
                "message_item": MessageFeedEntry(
                    entry_id="entry-message-startup-pending",
                    run_id=seeded.run_id,
                    type=common.FeedEntryType.USER_MESSAGE,
                    occurred_at=NOW,
                    message_id="message-startup-pending",
                    author="user",
                    content="Pending startup requirement.",
                    stage_run_id=seeded.stage_run_id,
                ).model_dump(mode="json")
            },
            trace_context=_trace(
                session_id=seeded.session_id,
                run_id=seeded.run_id,
                stage_run_id=seeded.stage_run_id,
            ),
        )
        session.commit()

    return seeded


def test_workspace_projection_hides_pending_startup_run_and_feed_until_publication(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    seeded = _seed_pending_startup(app)

    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{seeded.session_id}/workspace")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "draft"
    assert body["session"]["current_run_id"] is None
    assert body["runs"] == []
    assert body["narrative_feed"] == []


def test_timeline_route_rejects_unpublished_run_id(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)
    seeded = _seed_pending_startup(app)

    with TestClient(app) as client:
        response = client.get(f"/api/runs/{seeded.run_id}/timeline")

    assert response.status_code == 404
    assert response.json()["message"] == "Run timeline was not found."


def test_sse_stream_does_not_emit_pending_startup_events(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)
    seeded = _seed_pending_startup(app)

    with TestClient(app) as client:
        response = client.get(
            f"/api/sessions/{seeded.session_id}/events/stream",
            params={"after": 0, "limit": 50},
        )

    assert response.status_code == 200
    assert seeded.run_id not in response.text
    assert "Pending startup requirement." not in response.text
