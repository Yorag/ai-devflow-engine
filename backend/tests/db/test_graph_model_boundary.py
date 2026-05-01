from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect

from backend.app.core.config import EnvironmentSettings
from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import StageType


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
GRAPH_TABLES = {
    "graph_definitions",
    "graph_threads",
    "graph_checkpoints",
    "graph_interrupts",
}
FORBIDDEN_GRAPH_TABLES = {
    "projects",
    "sessions",
    "pipeline_templates",
    "providers",
    "delivery_channels",
    "platform_runtime_settings",
    "pipeline_runs",
    "stage_runs",
    "stage_artifacts",
    "approval_requests",
    "approval_decisions",
    "tool_confirmation_requests",
    "delivery_records",
    "domain_events",
    "run_log_entries",
    "audit_log_entries",
    "log_payloads",
    "feed_entries",
    "inspector_projections",
}
GRAPH_THREAD_STATUSES = [
    "pending",
    "running",
    "interrupted",
    "paused",
    "completed",
    "failed",
    "terminated",
]
GRAPH_INTERRUPT_TYPES = [
    "clarification_request",
    "solution_design_approval",
    "code_review_approval",
    "tool_confirmation",
]
GRAPH_INTERRUPT_STATUSES = ["pending", "responded", "cancelled"]
GRAPH_RUNTIME_OBJECT_TYPES = [
    "clarification_record",
    "approval_request",
    "tool_confirmation_request",
]


def enum_values(enum_type: type) -> list[str]:
    return [item.value for item in enum_type]


def test_graph_models_register_only_graph_role_metadata() -> None:
    from backend.app.db.models.graph import (
        GraphBase,
        GraphCheckpointModel,
        GraphDefinitionModel,
        GraphInterruptModel,
        GraphThreadModel,
    )

    assert GraphBase.metadata is ROLE_METADATA[DatabaseRole.GRAPH]
    assert {table.name for table in GraphBase.metadata.sorted_tables} == GRAPH_TABLES
    assert FORBIDDEN_GRAPH_TABLES.isdisjoint(GraphBase.metadata.tables)

    for model in (
        GraphDefinitionModel,
        GraphThreadModel,
        GraphCheckpointModel,
        GraphInterruptModel,
    ):
        assert model.metadata is ROLE_METADATA[DatabaseRole.GRAPH]

    for role in (
        DatabaseRole.CONTROL,
        DatabaseRole.RUNTIME,
        DatabaseRole.EVENT,
        DatabaseRole.LOG,
    ):
        assert GRAPH_TABLES.isdisjoint(ROLE_METADATA[role].tables)


def test_graph_tables_create_only_in_graph_database(tmp_path) -> None:
    from backend.app.db.models.graph import GraphBase

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    GraphBase.metadata.create_all(manager.engine(DatabaseRole.GRAPH))

    with manager.session(DatabaseRole.GRAPH) as session:
        graph_tables = set(inspect(session.bind).get_table_names())

    assert GRAPH_TABLES.issubset(graph_tables)
    assert FORBIDDEN_GRAPH_TABLES.isdisjoint(graph_tables)

    for role in (
        DatabaseRole.CONTROL,
        DatabaseRole.RUNTIME,
        DatabaseRole.EVENT,
        DatabaseRole.LOG,
    ):
        with manager.session(role) as session:
            assert GRAPH_TABLES.isdisjoint(inspect(session.bind).get_table_names())


def test_alembic_env_imports_graph_models_for_metadata_loading() -> None:
    alembic_env = Path("backend/alembic/env.py").read_text(encoding="utf-8")

    assert "import backend.app.db.models.graph  # noqa: F401" in alembic_env


def test_graph_definition_thread_and_checkpoint_models_keep_execution_state_boundary(
    tmp_path,
) -> None:
    from backend.app.db.models.graph import (
        GraphBase,
        GraphCheckpointModel,
        GraphDefinitionModel,
        GraphThreadModel,
    )

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    GraphBase.metadata.create_all(manager.engine(DatabaseRole.GRAPH))

    with manager.session(DatabaseRole.GRAPH) as session:
        definition = GraphDefinitionModel(
            graph_definition_id="graph-definition-1",
            run_id="run-1",
            template_snapshot_ref="template-snapshot-1",
            graph_version="graph-v1",
            stage_nodes=[
                {
                    "node_key": "requirement_analysis",
                    "stage_type": StageType.REQUIREMENT_ANALYSIS.value,
                },
                {
                    "node_key": "solution_design",
                    "stage_type": StageType.SOLUTION_DESIGN.value,
                },
            ],
            stage_contracts={
                StageType.REQUIREMENT_ANALYSIS.value: {
                    "input_contract": "requirement_input",
                    "output_contract": "requirement_analysis_artifact",
                    "allowed_tools": ["read_file", "glob", "grep"],
                    "runtime_limits": {"max_react_iterations": 6},
                }
            },
            interrupt_policy={
                "approval_interrupts": [
                    "solution_design_approval",
                    "code_review_approval",
                ]
            },
            retry_policy={"max_auto_regression_retries": 2},
            delivery_routing_policy={"demo_delivery": "demo_delivery_adapter"},
            schema_version="graph-definition-v1",
            created_at=NOW,
        )
        thread = GraphThreadModel(
            graph_thread_id="graph-thread-1",
            run_id="run-1",
            graph_definition_id=definition.graph_definition_id,
            checkpoint_namespace="run-1-main",
            current_node_key="requirement_analysis",
            current_interrupt_id=None,
            status="running",
            last_checkpoint_ref="checkpoint-ref-1",
            created_at=NOW,
            updated_at=NOW,
        )
        checkpoint = GraphCheckpointModel(
            checkpoint_id="checkpoint-1",
            graph_thread_id=thread.graph_thread_id,
            checkpoint_ref="checkpoint-ref-1",
            node_key="requirement_analysis",
            state_ref="graph-state/run-1/checkpoint-1.json",
            sequence_index=1,
            created_at=NOW,
        )
        session.add_all([definition, thread, checkpoint])
        session.commit()

        saved_definition = session.get(GraphDefinitionModel, "graph-definition-1")
        saved_thread = session.get(GraphThreadModel, "graph-thread-1")
        saved_checkpoint = session.get(GraphCheckpointModel, "checkpoint-1")

    assert saved_definition is not None
    assert saved_definition.stage_contracts[StageType.REQUIREMENT_ANALYSIS.value][
        "allowed_tools"
    ] == ["read_file", "glob", "grep"]
    assert saved_thread is not None
    assert saved_thread.status == "running"
    assert saved_thread.last_checkpoint_ref == "checkpoint-ref-1"
    assert saved_checkpoint is not None
    assert saved_checkpoint.state_ref == "graph-state/run-1/checkpoint-1.json"

    definition_columns = set(GraphDefinitionModel.__table__.columns.keys())
    thread_columns = set(GraphThreadModel.__table__.columns.keys())
    checkpoint_columns = set(GraphCheckpointModel.__table__.columns.keys())
    assert {
        "graph_definition_id",
        "template_snapshot_ref",
        "graph_version",
        "stage_nodes",
        "stage_contracts",
        "interrupt_policy",
        "retry_policy",
        "delivery_routing_policy",
    }.issubset(definition_columns)
    assert {
        "graph_thread_id",
        "run_id",
        "graph_definition_id",
        "checkpoint_namespace",
        "current_node_key",
        "current_interrupt_id",
        "status",
        "last_checkpoint_ref",
    }.issubset(thread_columns)
    assert {"checkpoint_ref", "node_key", "state_ref", "sequence_index"}.issubset(
        checkpoint_columns
    )
    assert {
        "pipeline_run_status",
        "stage_status",
        "approval_status",
        "delivery_record_id",
        "domain_event_payload",
        "narrative_feed_payload",
        "inspector_payload",
        "audit_payload",
        "log_payload",
    }.isdisjoint(definition_columns | thread_columns | checkpoint_columns)


def test_graph_interrupts_model_runtime_wait_points_without_approval_decisions(
    tmp_path,
) -> None:
    from backend.app.db.models.graph import (
        GraphBase,
        GraphDefinitionModel,
        GraphInterruptModel,
        GraphThreadModel,
    )

    manager = DatabaseManager.from_environment_settings(
        EnvironmentSettings(platform_runtime_root=tmp_path / "runtime")
    )
    GraphBase.metadata.create_all(manager.engine(DatabaseRole.GRAPH))

    with manager.session(DatabaseRole.GRAPH) as session:
        definition = GraphDefinitionModel(
            graph_definition_id="graph-definition-interrupts",
            run_id="run-interrupts",
            template_snapshot_ref="template-snapshot-interrupts",
            graph_version="graph-v1",
            stage_nodes=[
                {
                    "node_key": "requirement_analysis",
                    "stage_type": StageType.REQUIREMENT_ANALYSIS.value,
                },
                {
                    "node_key": "solution_design",
                    "stage_type": StageType.SOLUTION_DESIGN.value,
                },
                {
                    "node_key": "code_generation",
                    "stage_type": StageType.CODE_GENERATION.value,
                },
            ],
            stage_contracts={
                StageType.REQUIREMENT_ANALYSIS.value: {"allowed_tools": []},
                StageType.SOLUTION_DESIGN.value: {"allowed_tools": []},
                StageType.CODE_GENERATION.value: {"allowed_tools": ["bash"]},
            },
            interrupt_policy={
                "types": GRAPH_INTERRUPT_TYPES,
            },
            retry_policy={"max_auto_regression_retries": 2},
            delivery_routing_policy={"git_auto_delivery": "git_auto_delivery_adapter"},
            schema_version="graph-definition-v1",
            created_at=NOW,
        )
        thread = GraphThreadModel(
            graph_thread_id="graph-thread-interrupts",
            run_id="run-interrupts",
            graph_definition_id=definition.graph_definition_id,
            checkpoint_namespace="run-interrupts-main",
            current_node_key="code_generation",
            current_interrupt_id="interrupt-tool-1",
            status="interrupted",
            last_checkpoint_ref="checkpoint-before-tool",
            created_at=NOW,
            updated_at=NOW,
        )
        clarification_interrupt = GraphInterruptModel(
            interrupt_id="interrupt-clarification-1",
            graph_thread_id=thread.graph_thread_id,
            interrupt_type="clarification_request",
            source_stage_type=StageType.REQUIREMENT_ANALYSIS,
            source_node_key="requirement_analysis",
            payload_ref="artifact-clarification-question-1",
            runtime_object_ref="clarification-1",
            runtime_object_type="clarification_record",
            status="responded",
            requested_at=NOW,
            responded_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        approval_interrupt = GraphInterruptModel(
            interrupt_id="interrupt-approval-1",
            graph_thread_id=thread.graph_thread_id,
            interrupt_type="solution_design_approval",
            source_stage_type=StageType.SOLUTION_DESIGN,
            source_node_key="solution_design",
            payload_ref="solution-design-artifact-1",
            runtime_object_ref="approval-1",
            runtime_object_type="approval_request",
            status="pending",
            requested_at=NOW,
            responded_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        tool_interrupt = GraphInterruptModel(
            interrupt_id="interrupt-tool-1",
            graph_thread_id=thread.graph_thread_id,
            interrupt_type="tool_confirmation",
            source_stage_type=StageType.CODE_GENERATION,
            source_node_key="code_generation",
            payload_ref="tool-confirmation-1",
            runtime_object_ref="tool-confirmation-1",
            runtime_object_type="tool_confirmation_request",
            status="pending",
            requested_at=NOW,
            responded_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all(
            [
                definition,
                thread,
                clarification_interrupt,
                approval_interrupt,
                tool_interrupt,
            ]
        )
        session.commit()

        saved_tool_interrupt = session.get(GraphInterruptModel, "interrupt-tool-1")

    assert saved_tool_interrupt is not None
    assert saved_tool_interrupt.interrupt_type == "tool_confirmation"
    assert saved_tool_interrupt.runtime_object_type == "tool_confirmation_request"
    assert saved_tool_interrupt.runtime_object_ref == "tool-confirmation-1"

    thread_status = GraphThreadModel.__table__.columns["status"].type
    interrupt_type = GraphInterruptModel.__table__.columns["interrupt_type"].type
    interrupt_status = GraphInterruptModel.__table__.columns["status"].type
    runtime_object_type = GraphInterruptModel.__table__.columns["runtime_object_type"].type
    source_stage_type = GraphInterruptModel.__table__.columns["source_stage_type"].type

    assert thread_status.enums == GRAPH_THREAD_STATUSES
    assert interrupt_type.enums == GRAPH_INTERRUPT_TYPES
    assert interrupt_status.enums == GRAPH_INTERRUPT_STATUSES
    assert runtime_object_type.enums == GRAPH_RUNTIME_OBJECT_TYPES
    assert "approval_decision" not in runtime_object_type.enums
    assert "delivery_record" not in runtime_object_type.enums
    assert source_stage_type.enums == enum_values(StageType)

    interrupt_columns = set(GraphInterruptModel.__table__.columns.keys())
    assert {
        "interrupt_id",
        "graph_thread_id",
        "interrupt_type",
        "source_stage_type",
        "source_node_key",
        "payload_ref",
        "runtime_object_ref",
        "runtime_object_type",
        "status",
        "requested_at",
        "responded_at",
    }.issubset(interrupt_columns)
    assert {
        "approval_decision_id",
        "approval_decision_ref",
        "approval_status",
        "tool_confirmation_status",
        "pipeline_run_status",
        "stage_status",
    }.isdisjoint(interrupt_columns)
