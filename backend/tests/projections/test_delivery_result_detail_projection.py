from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ProjectModel, SessionModel
from backend.app.db.models.runtime import (
    DeliveryChannelSnapshotModel,
    DeliveryRecordModel,
    PipelineRunModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    RunStatus,
    RunTriggerSource,
    ScmProviderType,
    SessionStatus,
    StageStatus,
    StageType,
)
from backend.app.services.projections.inspector import (
    InspectorProjectionService,
    InspectorProjectionServiceError,
)
from backend.tests.projections.test_workspace_projection import NOW, _manager, _seed_workspace


def test_delivery_result_detail_projection_builds_sections_from_delivery_record_snapshot_and_artifacts(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_delivery_result_detail(manager)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_delivery_record_detail("delivery-record-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["delivery_record_id"] == "delivery-record-1"
    assert dumped["run_id"] == "run-delivery"
    assert dumped["delivery_mode"] == "demo_delivery"
    assert dumped["status"] == "succeeded"
    assert dumped["created_at"] == (
        NOW + timedelta(minutes=30)
    ).isoformat().replace("+00:00", "Z")
    assert set(dumped) >= {"identity", "input", "process", "output", "artifacts", "metrics"}

    assert dumped["identity"]["records"] == {
        "delivery_record_id": "delivery-record-1",
        "run_id": "run-delivery",
        "stage_run_id": "stage-delivery",
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "delivery_mode": "demo_delivery",
        "status": "succeeded",
        "created_at": (NOW + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "completed_at": (NOW + timedelta(minutes=30)).isoformat().replace(
            "+00:00",
            "Z",
        ),
    }
    assert dumped["input"]["records"]["delivery_channel_snapshot"] == {
        "delivery_channel_snapshot_ref": "delivery-snapshot-1",
        "delivery_mode": "demo_delivery",
        "scm_provider_type": None,
        "repository_identifier": None,
        "default_branch": None,
        "code_review_request_type": None,
        "credential_ref": None,
        "credential_status": "unbound",
        "readiness_status": "ready",
        "readiness_message": "demo delivery ready",
        "last_validated_at": (
            NOW + timedelta(minutes=29)
        ).isoformat().replace("+00:00", "Z"),
        "schema_version": "delivery-channel-snapshot-v1",
    }
    assert dumped["input"]["records"]["upstream_refs"] == [
        "artifact-requirement-output",
        "artifact-solution-output",
        "artifact-code-output",
        "artifact-test-output",
        "artifact-review-output",
        "approval-result-code-review-1",
    ]
    assert dumped["process"]["records"]["delivery_process"] == {
        "delivery_record_id": "delivery-record-1",
        "delivery_mode": "demo_delivery",
        "status": "succeeded",
        "result_ref": "demo-delivery-result:run-delivery",
        "process_ref": "demo-delivery-process:run-delivery",
        "branch_name": "demo/run-delivery",
        "commit_sha": None,
        "code_review_url": None,
        "audit_refs": ["audit-demo-1"],
        "log_summary_refs": ["log-demo-1"],
        "delivery_result_event_ref": "event-delivery-result-1",
        "no_git_actions": True,
        "git_write_actions": [],
    }
    assert dumped["process"]["records"]["delivery_process_refs"] == [
        "demo-delivery-process:run-delivery"
    ]
    assert dumped["process"]["log_refs"] == ["log-delivery-stage-1", "log-demo-1"]
    assert dumped["output"]["records"] == {
        "summary": "Delivery integration completed for demo_delivery path.",
        "delivery_status": "succeeded",
        "result_ref": "demo-delivery-result:run-delivery",
        "branch_name": "demo/run-delivery",
        "commit_sha": None,
        "code_review_url": None,
        "failure_reason": None,
        "test_summary": "Resolved upstream test summary.",
        "review_summary": "Resolved upstream review summary from stage.",
    }
    assert dumped["artifacts"]["records"]["artifact_refs"] == [
        "artifact-delivery-stage-1"
    ]
    assert dumped["artifacts"]["records"]["payload_refs"] == [
        "payload-delivery-stage-1"
    ]
    assert dumped["artifacts"]["records"]["delivery_artifacts"] == [
        "artifact-delivery-stage-1",
        "demo-delivery-result:run-delivery",
        "demo-delivery-process:run-delivery",
        "demo/run-delivery",
    ]
    assert dumped["artifacts"]["records"]["audit_refs"] == ["audit-demo-1"]
    assert dumped["artifacts"]["records"]["log_summary_refs"] == ["log-demo-1"]
    assert dumped["metrics"] == {
        "duration_ms": 1250,
        "attempt_index": 1,
        "delivery_artifact_count": 1,
        "changed_file_count": 0,
        "executed_test_count": 1,
        "passed_test_count": 1,
    }
    assert "delivery-record-other" not in str(dumped)
    assert "artifact-delivery-other" not in str(dumped)
    assert "artifact-delivery-same-ref-unmatched" not in str(dumped)
    assert "feed-summary-should-not-be-source" not in str(dumped)
    assert "temporary-feed-summary-should-not-be-source" not in str(dumped)
    assert "graph_thread_ref" not in str(dumped)
    assert "graph_thread_id" not in str(dumped)


def test_delivery_result_detail_projection_supports_git_delivery_record_fields_without_git_auto_delivery_tools(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_delivery_result_detail(
        manager,
        delivery_mode=DeliveryMode.GIT_AUTO_DELIVERY,
        scm_provider_type=ScmProviderType.GITHUB,
        repository_identifier="example/workspace-project",
        default_branch="main",
        code_review_request_type=CodeReviewRequestType.PULL_REQUEST,
        credential_ref="env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
        credential_status=CredentialStatus.READY,
        branch_name="feature/run-delivery",
        commit_sha="abc123def456",
        code_review_url="https://github.example/pulls/1",
        process_ref="git-delivery-process:run-delivery",
        result_ref="git-delivery-result:run-delivery",
    )

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_delivery_record_detail("delivery-record-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["delivery_mode"] == "git_auto_delivery"
    assert dumped["process"]["records"]["delivery_process"] == {
        "delivery_record_id": "delivery-record-1",
        "delivery_mode": "git_auto_delivery",
        "status": "succeeded",
        "result_ref": "git-delivery-result:run-delivery",
        "process_ref": "git-delivery-process:run-delivery",
        "branch_name": "feature/run-delivery",
        "commit_sha": "abc123def456",
        "code_review_url": "https://github.example/pulls/1",
        "audit_refs": ["audit-demo-1"],
        "log_summary_refs": ["log-demo-1"],
        "delivery_result_event_ref": "event-delivery-result-1",
        "no_git_actions": False,
        "git_write_actions": [],
    }
    assert dumped["process"]["log_refs"] == ["log-delivery-stage-1", "log-demo-1"]
    assert (
        dumped["input"]["records"]["delivery_channel_snapshot"][
            "repository_identifier"
        ]
        == "example/workspace-project"
    )
    assert dumped["output"]["records"]["branch_name"] == "feature/run-delivery"
    assert dumped["output"]["records"]["commit_sha"] == "abc123def456"
    assert dumped["output"]["records"]["code_review_url"] == (
        "https://github.example/pulls/1"
    )
    assert dumped["artifacts"]["records"]["delivery_artifacts"] == [
        "artifact-delivery-stage-1",
        "git-delivery-result:run-delivery",
        "git-delivery-process:run-delivery",
        "feature/run-delivery",
        "abc123def456",
        "https://github.example/pulls/1",
    ]
    assert dumped["metrics"] == {
        "duration_ms": 1250,
        "attempt_index": 1,
        "delivery_artifact_count": 1,
        "changed_file_count": 0,
        "executed_test_count": 1,
        "passed_test_count": 1,
    }


def test_delivery_result_detail_projection_resolves_runtime_input_refs(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_delivery_result_detail(manager, use_runtime_input_refs=True)

    with (
        manager.session(DatabaseRole.CONTROL) as control_session,
        manager.session(DatabaseRole.RUNTIME) as runtime_session,
        manager.session(DatabaseRole.EVENT) as event_session,
    ):
        projection = InspectorProjectionService(
            control_session,
            runtime_session,
            event_session,
        ).get_delivery_record_detail("delivery-record-1")

    dumped = projection.model_dump(mode="json")
    assert dumped["input"]["records"]["upstream_refs"] == [
        "artifact-requirement-output",
        "artifact-solution-output",
        "artifact-code-output",
        "artifact-test-output",
        "artifact-review-output",
        "approval-result-code-review-1",
    ]
    assert dumped["input"]["stable_refs"] == [
        "delivery-snapshot-1",
        "delivery-input-ref-1",
        "artifact-requirement-output",
        "artifact-solution-output",
        "artifact-code-output",
        "artifact-test-output",
        "artifact-review-output",
        "approval-result-code-review-1",
    ]
    assert dumped["output"]["records"]["test_summary"] == (
        "Resolved upstream test summary."
    )
    assert dumped["output"]["records"]["review_summary"] == (
        "Resolved upstream review summary from stage."
    )


def test_delivery_result_detail_projection_rejects_missing_non_succeeded_hidden_or_cross_run_records(
    tmp_path,
) -> None:
    manager = _manager(tmp_path)
    _seed_workspace(manager)
    _seed_delivery_result_detail(manager)
    _seed_non_succeeded_and_cross_run_delivery_records(manager)

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
        for delivery_record_id in [
            "delivery-record-missing",
            "delivery-record-failed",
            "delivery-record-cross-run",
            "delivery-record-stale-snapshot",
        ]:
            with pytest.raises(InspectorProjectionServiceError) as exc_info:
                service.get_delivery_record_detail(delivery_record_id)
            assert exc_info.value.status_code == 404
            assert exc_info.value.message == "Delivery result detail was not found."

    with manager.session(DatabaseRole.CONTROL) as session:
        project = session.get(ProjectModel, "project-1")
        assert project is not None
        project.is_visible = False
        project.visibility_removed_at = NOW + timedelta(minutes=40)
        session.add(project)
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
            service.get_delivery_record_detail("delivery-record-1")
        assert exc_info.value.status_code == 404
        assert exc_info.value.message == "Delivery result detail was not found."


def _seed_delivery_result_detail(
    manager,
    *,
    delivery_mode: DeliveryMode = DeliveryMode.DEMO_DELIVERY,
    scm_provider_type: ScmProviderType | None = None,
    repository_identifier: str | None = None,
    default_branch: str | None = None,
    code_review_request_type: CodeReviewRequestType | None = None,
    credential_ref: str | None = None,
    credential_status: CredentialStatus = CredentialStatus.UNBOUND,
    branch_name: str = "demo/run-delivery",
    commit_sha: str | None = None,
    code_review_url: str | None = None,
    result_ref: str = "demo-delivery-result:run-delivery",
    process_ref: str = "demo-delivery-process:run-delivery",
    use_runtime_input_refs: bool = False,
) -> None:
    upstream_refs = [
        "artifact-requirement-output",
        "artifact-solution-output",
        "artifact-code-output",
        "artifact-test-output",
        "artifact-review-output",
        "approval-result-code-review-1",
    ]
    delivery_input_snapshot = {"delivery_channel_snapshot_ref": "delivery-snapshot-1"}
    if not use_runtime_input_refs:
        delivery_input_snapshot["upstream_refs"] = upstream_refs

    with manager.session(DatabaseRole.CONTROL) as session:
        control_session = session.get(SessionModel, "session-1")
        assert control_session is not None
        control_session.status = SessionStatus.COMPLETED
        control_session.current_run_id = "run-delivery"
        control_session.latest_stage_type = StageType.DELIVERY_INTEGRATION
        control_session.updated_at = NOW + timedelta(minutes=31)
        session.add(control_session)
        session.commit()

    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            DeliveryChannelSnapshotModel(
                delivery_channel_snapshot_id="delivery-snapshot-1",
                run_id="run-delivery",
                source_delivery_channel_id="delivery-1",
                delivery_mode=delivery_mode,
                scm_provider_type=scm_provider_type,
                repository_identifier=repository_identifier,
                default_branch=default_branch,
                code_review_request_type=code_review_request_type,
                credential_ref=credential_ref,
                credential_status=credential_status,
                readiness_status=DeliveryReadinessStatus.READY,
                readiness_message="demo delivery ready",
                last_validated_at=NOW + timedelta(minutes=29),
                schema_version="delivery-channel-snapshot-v1",
                created_at=NOW + timedelta(minutes=29),
            )
        )
        session.add(
            PipelineRunModel(
                run_id="run-delivery",
                session_id="session-1",
                project_id="project-1",
                attempt_index=3,
                status=RunStatus.COMPLETED,
                trigger_source=RunTriggerSource.RETRY,
                template_snapshot_ref="template-snapshot-delivery",
                graph_definition_ref="graph-definition-delivery",
                graph_thread_ref="graph-thread-delivery-hidden",
                workspace_ref="workspace-delivery",
                runtime_limit_snapshot_ref="runtime-limit-active",
                provider_call_policy_snapshot_ref="policy-active",
                delivery_channel_snapshot_ref="delivery-snapshot-1",
                current_stage_run_id="stage-delivery",
                trace_id="trace-run-delivery",
                started_at=NOW + timedelta(minutes=20),
                ended_at=NOW + timedelta(minutes=31),
                created_at=NOW + timedelta(minutes=20),
                updated_at=NOW + timedelta(minutes=31),
            )
        )
        session.add_all(
            [
                StageRunModel(
                    stage_run_id="stage-test-upstream",
                    run_id="run-delivery",
                    stage_type=StageType.TEST_GENERATION_EXECUTION,
                    status=StageStatus.COMPLETED,
                    attempt_index=1,
                    graph_node_key="test_generation_execution.main",
                    stage_contract_ref="stage-contract-test-generation-execution",
                    input_ref="test-input-ref-1",
                    output_ref="test-output-ref-1",
                    summary="Fallback test summary from stage.",
                    started_at=NOW + timedelta(minutes=26),
                    ended_at=NOW + timedelta(minutes=27),
                    created_at=NOW + timedelta(minutes=26),
                    updated_at=NOW + timedelta(minutes=27),
                ),
                StageRunModel(
                    stage_run_id="stage-review-upstream",
                    run_id="run-delivery",
                    stage_type=StageType.CODE_REVIEW,
                    status=StageStatus.COMPLETED,
                    attempt_index=1,
                    graph_node_key="code_review.main",
                    stage_contract_ref="stage-contract-code-review",
                    input_ref="review-input-ref-1",
                    output_ref="review-output-ref-1",
                    summary="Resolved upstream review summary from stage.",
                    started_at=NOW + timedelta(minutes=27),
                    ended_at=NOW + timedelta(minutes=28),
                    created_at=NOW + timedelta(minutes=27),
                    updated_at=NOW + timedelta(minutes=28),
                ),
                StageRunModel(
                    stage_run_id="stage-delivery",
                    run_id="run-delivery",
                    stage_type=StageType.DELIVERY_INTEGRATION,
                    status=StageStatus.COMPLETED,
                    attempt_index=1,
                    graph_node_key="delivery_integration.main",
                    stage_contract_ref="stage-contract-delivery-integration",
                    input_ref="delivery-input-ref-1",
                    output_ref="delivery-output-ref-1",
                    summary="Delivery integration completed for demo_delivery path.",
                    started_at=NOW + timedelta(
                        minutes=29,
                        seconds=58,
                        milliseconds=750,
                    ),
                    ended_at=NOW + timedelta(minutes=30),
                    created_at=NOW + timedelta(minutes=29),
                    updated_at=NOW + timedelta(minutes=30),
                ),
            ]
        )
        session.commit()
        session.add(
            DeliveryRecordModel(
                delivery_record_id="delivery-record-1",
                run_id="run-delivery",
                stage_run_id="stage-delivery",
                delivery_channel_snapshot_ref="delivery-snapshot-1",
                delivery_mode=delivery_mode,
                status="succeeded",
                branch_name=branch_name,
                commit_sha=commit_sha,
                code_review_url=code_review_url,
                result_ref=result_ref,
                process_ref=process_ref,
                failure_reason=None,
                created_at=NOW + timedelta(minutes=30),
                completed_at=NOW + timedelta(minutes=30),
            )
        )
        session.add_all(
            [
                StageArtifactModel(
                    artifact_id="artifact-test-output",
                    run_id="run-delivery",
                    stage_run_id="stage-test-upstream",
                    artifact_type="stage_output",
                    payload_ref="payload-test-output",
                    process={
                        "output_snapshot": {
                            "summary": "Resolved upstream test summary.",
                        },
                    },
                    metrics={"executed_test_count": 1, "passed_test_count": 1},
                    created_at=NOW + timedelta(minutes=27),
                ),
                StageArtifactModel(
                    artifact_id="artifact-review-output",
                    run_id="run-delivery",
                    stage_run_id="stage-review-upstream",
                    artifact_type="stage_output",
                    payload_ref="payload-review-output",
                    process={},
                    metrics={},
                    created_at=NOW + timedelta(minutes=28),
                ),
                StageArtifactModel(
                    artifact_id="artifact-delivery-stage-1",
                    run_id="run-delivery",
                    stage_run_id="stage-delivery",
                    artifact_type="delivery_result_trace",
                    payload_ref="payload-delivery-stage-1",
                    process={
                        "input_snapshot": delivery_input_snapshot,
                        "input_refs": upstream_refs if use_runtime_input_refs else [],
                        "output_snapshot": {
                            "summary": (
                                "Delivery integration completed for demo_delivery path."
                            ),
                            "graph_thread_ref": "graph-thread-hidden",
                        },
                        delivery_mode.value: {
                            "delivery_record_id": "delivery-record-1",
                            "delivery_mode": delivery_mode.value,
                            "status": "succeeded",
                            "result_ref": result_ref,
                            "process_ref": process_ref,
                            "branch_name": branch_name,
                            "commit_sha": commit_sha,
                            "code_review_url": code_review_url,
                            "audit_refs": ["audit-demo-1"],
                            "log_summary_refs": ["log-demo-1"],
                            "delivery_result_event_ref": "event-delivery-result-1",
                            "no_git_actions": delivery_mode is DeliveryMode.DEMO_DELIVERY,
                            "git_write_actions": [],
                        },
                        "log_refs": ["log-delivery-stage-1"],
                    },
                    metrics={
                        "duration_ms": 1250,
                        "attempt_index": 1,
                        "delivery_artifact_count": 1,
                        "changed_file_count": 0,
                        "executed_test_count": 1,
                        "passed_test_count": 1,
                    },
                    created_at=NOW + timedelta(minutes=30),
                ),
                StageArtifactModel(
                    artifact_id="artifact-delivery-other",
                    run_id="run-delivery",
                    stage_run_id="stage-delivery",
                    artifact_type="delivery_result_trace",
                    payload_ref="payload-delivery-other",
                    process={
                        "demo_delivery": {
                            "delivery_record_id": "delivery-record-other",
                            "summary": "feed-summary-should-not-be-source",
                        },
                        "log_refs": ["log-delivery-other"],
                    },
                    metrics={"delivery_artifact_count": 99},
                    created_at=NOW + timedelta(minutes=30, seconds=1),
                ),
                StageArtifactModel(
                    artifact_id="artifact-delivery-same-ref-unmatched",
                    run_id="run-delivery",
                    stage_run_id="stage-delivery",
                    artifact_type="delivery_result_trace",
                    payload_ref="payload-delivery-same-ref-unmatched",
                    process={
                        "process_ref": process_ref,
                        "result_ref": result_ref,
                        "output_snapshot": {
                            "summary": "temporary-feed-summary-should-not-be-source",
                            "test_summary": "temporary-test-summary",
                            "review_summary": "temporary-review-summary",
                        },
                        "log_refs": ["log-delivery-same-ref-unmatched"],
                    },
                    metrics={
                        "duration_ms": 9999,
                        "delivery_artifact_count": 99,
                        "changed_file_count": 99,
                    },
                    created_at=NOW + timedelta(minutes=30, seconds=2),
                ),
            ]
        )
        session.commit()


def _seed_non_succeeded_and_cross_run_delivery_records(manager) -> None:
    with manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            DeliveryChannelSnapshotModel(
                delivery_channel_snapshot_id="delivery-snapshot-stale",
                run_id="run-delivery",
                source_delivery_channel_id="delivery-stale",
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
                scm_provider_type=None,
                repository_identifier=None,
                default_branch=None,
                code_review_request_type=None,
                credential_ref=None,
                credential_status=CredentialStatus.UNBOUND,
                readiness_status=DeliveryReadinessStatus.READY,
                readiness_message="stale delivery snapshot",
                last_validated_at=NOW + timedelta(minutes=29),
                schema_version="delivery-channel-snapshot-v1",
                created_at=NOW + timedelta(minutes=29),
            )
        )
        session.add(
            DeliveryRecordModel(
                delivery_record_id="delivery-record-failed",
                run_id="run-delivery",
                stage_run_id="stage-delivery",
                delivery_channel_snapshot_ref="delivery-snapshot-1",
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
                status="failed",
                branch_name=None,
                commit_sha=None,
                code_review_url=None,
                result_ref=None,
                process_ref="demo-delivery-process:failed",
                failure_reason="Demo delivery failed.",
                created_at=NOW + timedelta(minutes=30),
                completed_at=NOW + timedelta(minutes=30),
            )
        )
        session.add(
            DeliveryRecordModel(
                delivery_record_id="delivery-record-cross-run",
                run_id="run-delivery",
                stage_run_id="stage-active",
                delivery_channel_snapshot_ref="delivery-snapshot-1",
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
                status="succeeded",
                branch_name=None,
                commit_sha=None,
                code_review_url=None,
                result_ref="demo-delivery-result:cross",
                process_ref="demo-delivery-process:cross",
                failure_reason=None,
                created_at=NOW + timedelta(minutes=30),
                completed_at=NOW + timedelta(minutes=30),
            )
        )
        session.add(
            DeliveryRecordModel(
                delivery_record_id="delivery-record-stale-snapshot",
                run_id="run-delivery",
                stage_run_id="stage-delivery",
                delivery_channel_snapshot_ref="delivery-snapshot-stale",
                delivery_mode=DeliveryMode.DEMO_DELIVERY,
                status="succeeded",
                branch_name=None,
                commit_sha=None,
                code_review_url=None,
                result_ref="demo-delivery-result:stale-snapshot",
                process_ref="demo-delivery-process:stale-snapshot",
                failure_reason=None,
                created_at=NOW + timedelta(minutes=30),
                completed_at=NOW + timedelta(minutes=30),
            )
        )
        session.commit()
