from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase
from backend.app.db.models.runtime import (
    PipelineRunModel,
    ProviderCallPolicySnapshotModel,
    RuntimeBase,
    RuntimeLimitSnapshotModel,
)
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import RunStatus, RunTriggerSource
from backend.app.domain.trace_context import TraceContext


NOW = datetime(2026, 5, 2, 14, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 2, 14, 5, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-template-snapshot",
        trace_id="trace-template-snapshot",
        correlation_id="correlation-template-snapshot",
        span_id="span-template-snapshot",
        parent_span_id=None,
        created_at=NOW,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    RuntimeBase.metadata.create_all(manager.engine(DatabaseRole.RUNTIME))
    return manager


def test_build_for_run_freezes_template_fields_before_later_template_mutation(
    tmp_path: Path,
) -> None:
    from backend.app.domain.template_snapshot import TemplateSnapshotBuilder
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        template = TemplateService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())
        source_bindings = [
            {
                "stage_type": binding["stage_type"],
                "role_id": binding["role_id"],
                "system_prompt": binding["system_prompt"],
                "provider_id": binding["provider_id"],
            }
            for binding in template.stage_role_bindings
        ]
        snapshot = TemplateSnapshotBuilder.build_for_run(
            template,
            run_id="run-template-freeze",
            created_at=NOW,
        )

        for index, binding in enumerate(template.stage_role_bindings):
            binding["system_prompt"] = f"# Mutated prompt {index}"
            binding["provider_id"] = f"provider-mutated-{index}"
        template.auto_regression_enabled = False
        template.max_auto_regression_retries = 99
        template.updated_at = LATER
        session.add(template)
        session.commit()

    assert snapshot.snapshot_ref == "template-snapshot-run-template-freeze"
    assert snapshot.run_id == "run-template-freeze"
    assert snapshot.source_template_id == "template-feature"
    assert [stage.value for stage in snapshot.fixed_stage_sequence] == [
        "requirement_analysis",
        "solution_design",
        "code_generation",
        "test_generation_execution",
        "code_review",
        "delivery_integration",
    ]
    first_binding = snapshot.stage_role_bindings[0]
    assert first_binding.stage_type.value == "requirement_analysis"
    assert first_binding.role_id == "role-requirement-analyst"
    assert first_binding.system_prompt != "# Mutated prompt"
    assert first_binding.provider_id == "provider-deepseek"
    assert [
        {
            "stage_type": binding.stage_type.value,
            "role_id": binding.role_id,
            "system_prompt": binding.system_prompt,
            "provider_id": binding.provider_id,
        }
        for binding in snapshot.stage_role_bindings
    ] == source_bindings
    assert snapshot.auto_regression_enabled is True
    assert snapshot.max_auto_regression_retries == 1
    dumped = snapshot.model_dump(mode="json")
    assert set(dumped) == {
        "snapshot_ref",
        "run_id",
        "source_template_id",
        "source_template_name",
        "source_template",
        "source_template_updated_at",
        "fixed_stage_sequence",
        "stage_role_bindings",
        "approval_checkpoints",
        "auto_regression_enabled",
        "max_auto_regression_retries",
        "schema_version",
        "created_at",
    }
    assert set(dumped["stage_role_bindings"][0]) == {
        "stage_type",
        "role_id",
        "system_prompt",
        "provider_id",
    }


def test_builder_rejects_templates_with_incomplete_stage_bindings(
    tmp_path: Path,
) -> None:
    from backend.app.domain.template_snapshot import TemplateSnapshotBuilder
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        template = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())
        template.stage_role_bindings = template.stage_role_bindings[:-1]

        with pytest.raises(ValueError, match="stage_role_bindings"):
            TemplateSnapshotBuilder.build_for_run(
                template,
                run_id="run-invalid-template",
                created_at=NOW,
            )


@pytest.mark.parametrize(
    ("bad_binding", "expected_match"),
    [
        (None, "stage_role_bindings"),
        (
            {
                "role_id": "role-solution-designer",
                "system_prompt": "# Solution prompt",
                "provider_id": "provider-deepseek",
            },
            "stage_type",
        ),
    ],
)
def test_builder_rejects_malformed_stage_binding_rows(
    tmp_path: Path,
    bad_binding: Any,
    expected_match: str,
) -> None:
    from backend.app.domain.template_snapshot import TemplateSnapshotBuilder
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        template = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())
        stage_role_bindings = list(template.stage_role_bindings)
        stage_role_bindings[1] = bad_binding
        template.stage_role_bindings = stage_role_bindings

        with pytest.raises(ValueError, match=expected_match):
            TemplateSnapshotBuilder.build_for_run(
                template,
                run_id="run-malformed-stage-binding",
                created_at=NOW,
            )


def test_builder_rejects_binding_with_null_provider_id(
    tmp_path: Path,
) -> None:
    from backend.app.domain.template_snapshot import TemplateSnapshotBuilder
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        template = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())
        template.stage_role_bindings = [
            {**binding, "provider_id": None} if index == 1 else binding
            for index, binding in enumerate(template.stage_role_bindings)
        ]

        with pytest.raises(ValueError, match="provider_id"):
            TemplateSnapshotBuilder.build_for_run(
                template,
                run_id="run-null-provider",
                created_at=NOW,
            )


def test_builder_rejects_non_boolean_auto_regression_flag(
    tmp_path: Path,
) -> None:
    from backend.app.domain.template_snapshot import TemplateSnapshotBuilder
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        template = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())
        template.auto_regression_enabled = "false"

        with pytest.raises(ValueError, match="auto_regression_enabled"):
            TemplateSnapshotBuilder.build_for_run(
                template,
                run_id="run-string-auto-regression",
                created_at=NOW,
            )


def test_builder_rejects_non_integer_auto_regression_retry_count(
    tmp_path: Path,
) -> None:
    from backend.app.domain.template_snapshot import TemplateSnapshotBuilder
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        template = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())
        template.max_auto_regression_retries = "1"

        with pytest.raises(ValueError, match="max_auto_regression_retries"):
            TemplateSnapshotBuilder.build_for_run(
                template,
                run_id="run-string-retry-count",
                created_at=NOW,
            )


def test_template_snapshot_schema_version_is_stable_literal(
    tmp_path: Path,
) -> None:
    from backend.app.domain.template_snapshot import (
        TemplateSnapshot,
        TemplateSnapshotBuilder,
    )
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        template = TemplateService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())
        snapshot = TemplateSnapshotBuilder.build_for_run(
            template,
            run_id="run-schema-version",
            created_at=NOW,
        )

    payload = snapshot.model_dump()
    payload["schema_version"] = "template-snapshot-v0"

    with pytest.raises(ValueError, match="schema_version"):
        TemplateSnapshot(**payload)


def test_run_lifecycle_attach_template_snapshot_updates_only_template_ref(
    tmp_path: Path,
) -> None:
    from backend.app.domain.template_snapshot import TemplateSnapshotBuilder
    from backend.app.services.runs import RunLifecycleService
    from backend.app.services.templates import TemplateService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as control_session:
        template = TemplateService(
            control_session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).get_default_template(trace_context=build_trace())
        snapshot = TemplateSnapshotBuilder.build_for_run(
            template,
            run_id="run-attach-template",
            created_at=NOW,
        )

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        runtime_session.add_all(
            [
                RuntimeLimitSnapshotModel(
                    snapshot_id="runtime-limit-snapshot-1",
                    run_id="run-attach-template",
                    agent_limits={"max_react_iterations_per_stage": 30},
                    context_limits={"compression_threshold_ratio": 0.8},
                    source_config_version="runtime-settings-v1",
                    hard_limits_version="platform-hard-limits-v1",
                    schema_version="runtime-limit-snapshot-v1",
                    created_at=NOW,
                ),
                ProviderCallPolicySnapshotModel(
                    snapshot_id="provider-call-policy-snapshot-1",
                    run_id="run-attach-template",
                    provider_call_policy={
                        "request_timeout_seconds": 60,
                        "network_error_max_retries": 3,
                    },
                    source_config_version="runtime-settings-v1",
                    schema_version="provider-call-policy-snapshot-v1",
                    created_at=NOW,
                ),
            ]
        )
        runtime_session.flush()
        run = PipelineRunModel(
            run_id="run-attach-template",
            session_id="session-1",
            project_id="project-default",
            attempt_index=1,
            status=RunStatus.RUNNING,
            trigger_source=RunTriggerSource.INITIAL_REQUIREMENT,
            template_snapshot_ref="template-snapshot-pending",
            graph_definition_ref="graph-definition-pending",
            graph_thread_ref="graph-thread-pending",
            workspace_ref="workspace-1",
            runtime_limit_snapshot_ref="runtime-limit-snapshot-1",
            provider_call_policy_snapshot_ref="provider-call-policy-snapshot-1",
            delivery_channel_snapshot_ref=None,
            current_stage_run_id=None,
            trace_id="trace-template-snapshot",
            started_at=NOW,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        runtime_session.add(run)
        runtime_session.commit()
        existing = runtime_session.get(PipelineRunModel, "run-attach-template")
        assert existing is not None

        attached = RunLifecycleService(
            runtime_session,
            now=lambda: LATER,
        ).attach_template_snapshot(existing, snapshot)
        runtime_session.commit()

        attached_is_existing = attached is existing

    with manager.session(DatabaseRole.RUNTIME) as runtime_session:
        saved = runtime_session.get(PipelineRunModel, "run-attach-template")

    assert saved is not None
    assert attached_is_existing
    assert saved.template_snapshot_ref == "template-snapshot-run-attach-template"
    assert saved.graph_definition_ref == "graph-definition-pending"
    assert saved.runtime_limit_snapshot_ref == "runtime-limit-snapshot-1"
    assert saved.provider_call_policy_snapshot_ref == (
        "provider-call-policy-snapshot-1"
    )
    assert saved.updated_at.replace(tzinfo=UTC) == LATER
