from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from backend.app.domain.enums import ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import ToolExecutionRequest
from backend.app.tools.protocol import ToolPermissionBoundary, ToolSideEffectLevel
from backend.app.tools.risk import (
    ToolConfirmationGrant,
    ToolConfirmationRequestRecord,
    ToolRiskAssessment,
    ToolRiskClassifier,
)
from backend.tests.fixtures.tools import fake_tool_fixture


NOW = datetime(2026, 5, 3, 13, 30, 0, tzinfo=UTC)


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-risk-1",
        trace_id="trace-risk-1",
        correlation_id="correlation-risk-1",
        span_id="span-risk-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


def build_request(tool_name: str, payload: dict[str, object]) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_name=tool_name,
        call_id=f"call-{tool_name}",
        input_payload=payload,
        trace_context=build_trace(),
        coordination_key=f"coord-{tool_name}",
    )


@pytest.mark.parametrize("tool_name", ["read_file", "glob", "grep"])
def test_classify_read_only_workspace_reads_and_searches(tool_name: str) -> None:
    classifier = ToolRiskClassifier()
    read_tool = fake_tool_fixture(
        name=tool_name,
        side_effect_level=ToolSideEffectLevel.WORKSPACE_READ,
    )

    assessment = classifier.classify(
        tool=read_tool,
        request=build_request(tool_name, {"path": "src/app.py"}),
    )

    assert assessment.risk_level is ToolRiskLevel.READ_ONLY
    assert assessment.risk_categories == []
    assert assessment.requires_confirmation is False


def test_classify_precise_single_file_edit_as_low_risk_write() -> None:
    classifier = ToolRiskClassifier()
    edit_tool = fake_tool_fixture(
        name="edit_file",
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
        permission_boundary=ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("path",),
        ),
    )

    assessment = classifier.classify(
        tool=edit_tool,
        request=build_request(
            "edit_file",
            {
                "path": "src/app.py",
                "old_text": "value = 1",
                "new_text": "value = 2",
            },
        ),
    )

    assert assessment.risk_level is ToolRiskLevel.LOW_RISK_WRITE
    assert assessment.risk_categories == []
    assert assessment.requires_confirmation is False


@pytest.mark.parametrize(
    ("command", "expected_category"),
    [
        ("npm install vite", ToolRiskCategory.DEPENDENCY_CHANGE),
        ("uv pip install pytest", ToolRiskCategory.DEPENDENCY_CHANGE),
        ("pip install --upgrade pytest", ToolRiskCategory.DEPENDENCY_CHANGE),
    ],
)
def test_classify_dependency_install_or_upgrade_as_high_risk(
    command: str,
    expected_category: ToolRiskCategory,
) -> None:
    classifier = ToolRiskClassifier()
    bash_tool = fake_tool_fixture(
        name="bash",
        side_effect_level=ToolSideEffectLevel.PROCESS_EXECUTION,
    )

    assessment = classifier.classify(
        tool=bash_tool,
        request=build_request("bash", {"command": command}),
    )

    assert assessment.risk_level is ToolRiskLevel.HIGH_RISK
    assert expected_category in assessment.risk_categories
    assert assessment.requires_confirmation is True
    assert assessment.command_preview == command


def test_classify_env_and_runtime_mutation_as_blocked() -> None:
    classifier = ToolRiskClassifier()
    write_tool = fake_tool_fixture(
        name="write_file",
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
    )

    env_assessment = classifier.classify(
        tool=write_tool,
        request=build_request(
            "write_file",
            {"path": ".env", "content": "API_KEY=secret"},
        ),
    )
    runtime_assessment = classifier.classify(
        tool=write_tool,
        request=build_request(
            "write_file",
            {"path": ".runtime/logs/run.jsonl", "content": "tamper"},
        ),
    )

    assert env_assessment.risk_level is ToolRiskLevel.HIGH_RISK
    assert env_assessment.risk_categories == [
        ToolRiskCategory.ENVIRONMENT_CONFIG_CHANGE
    ]
    assert runtime_assessment.risk_level is ToolRiskLevel.BLOCKED
    assert runtime_assessment.risk_categories == [
        ToolRiskCategory.PLATFORM_RUNTIME_MUTATION
    ]


@pytest.mark.parametrize("path", [".env", ".env.production", ".npmrc", "secrets/id_rsa"])
def test_classify_credential_file_reads_as_blocked(path: str) -> None:
    classifier = ToolRiskClassifier()
    read_tool = fake_tool_fixture(
        name="read_file",
        side_effect_level=ToolSideEffectLevel.WORKSPACE_READ,
    )

    assessment = classifier.classify(
        tool=read_tool,
        request=build_request("read_file", {"path": path}),
    )

    assert assessment.risk_level is ToolRiskLevel.BLOCKED
    assert assessment.risk_categories == [ToolRiskCategory.CREDENTIAL_ACCESS]
    assert assessment.requires_confirmation is False


@pytest.mark.parametrize(
    ("path", "expected_category"),
    [
        ("package.json", ToolRiskCategory.DEPENDENCY_CHANGE),
        ("pyproject.toml", ToolRiskCategory.DEPENDENCY_CHANGE),
        ("uv.lock", ToolRiskCategory.LOCKFILE_CHANGE),
        ("migrations/0001_create_table.py", ToolRiskCategory.DATABASE_MIGRATION),
    ],
)
def test_classify_manifest_lockfile_and_migration_writes_as_high_risk(
    path: str,
    expected_category: ToolRiskCategory,
) -> None:
    classifier = ToolRiskClassifier()
    write_tool = fake_tool_fixture(
        name="write_file",
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
    )

    assessment = classifier.classify(
        tool=write_tool,
        request=build_request("write_file", {"path": path, "content": "changed"}),
    )

    assert assessment.risk_level is ToolRiskLevel.HIGH_RISK
    assert assessment.risk_categories == [expected_category]
    assert assessment.requires_confirmation is True


def test_classify_broad_write_as_high_risk() -> None:
    classifier = ToolRiskClassifier()
    write_tool = fake_tool_fixture(
        name="write_file",
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
    )

    assessment = classifier.classify(
        tool=write_tool,
        request=build_request(
            "write_file",
            {
                "paths": ["src/a.py", "src/b.py"],
                "content": "changed",
            },
        ),
    )

    assert assessment.risk_level is ToolRiskLevel.HIGH_RISK
    assert assessment.risk_categories == [ToolRiskCategory.BROAD_WRITE]


@pytest.mark.parametrize(
    "command",
    [
        "rm ../outside.txt",
        "python scripts/build.py --output ..\\outside.txt",
    ],
)
def test_classify_bash_command_path_escape_as_blocked(command: str) -> None:
    classifier = ToolRiskClassifier()
    bash_tool = fake_tool_fixture(
        name="bash",
        side_effect_level=ToolSideEffectLevel.PROCESS_EXECUTION,
    )

    assessment = classifier.classify(
        tool=bash_tool,
        request=build_request("bash", {"command": command}),
    )

    assert assessment.risk_level is ToolRiskLevel.BLOCKED
    assert assessment.risk_categories == [ToolRiskCategory.PATH_ESCAPE]
    assert assessment.requires_confirmation is False


@pytest.mark.parametrize(
    "command",
    [
        "rm ./../outside.txt",
        "rm /tmp/outside.txt",
    ],
)
def test_classify_bash_command_relative_or_absolute_escape_as_blocked(
    command: str,
) -> None:
    classifier = ToolRiskClassifier()
    bash_tool = fake_tool_fixture(
        name="bash",
        side_effect_level=ToolSideEffectLevel.PROCESS_EXECUTION,
    )

    assessment = classifier.classify(
        tool=bash_tool,
        request=build_request("bash", {"command": command}),
    )

    assert assessment.risk_level is ToolRiskLevel.BLOCKED
    assert assessment.risk_categories == [ToolRiskCategory.PATH_ESCAPE]
    assert assessment.requires_confirmation is False


@pytest.mark.parametrize(
    "command",
    [
        "cat .npmrc",
        "printenv API_KEY",
        "printenv api-key",
        "printenv apikey",
    ],
)
def test_classify_credential_command_read_as_blocked(command: str) -> None:
    classifier = ToolRiskClassifier()
    bash_tool = fake_tool_fixture(
        name="bash",
        side_effect_level=ToolSideEffectLevel.PROCESS_EXECUTION,
    )

    assessment = classifier.classify(
        tool=bash_tool,
        request=build_request("bash", {"command": command}),
    )

    assert assessment.risk_level is ToolRiskLevel.BLOCKED
    assert assessment.risk_categories == [ToolRiskCategory.CREDENTIAL_ACCESS]
    assert assessment.requires_confirmation is False


@pytest.mark.parametrize("path", [".", "./", ""])
def test_classify_ambiguous_root_edit_as_high_risk_broad_write(path: str) -> None:
    classifier = ToolRiskClassifier()
    edit_tool = fake_tool_fixture(
        name="edit_file",
        side_effect_level=ToolSideEffectLevel.WORKSPACE_WRITE,
        permission_boundary=ToolPermissionBoundary(
            boundary_type="workspace",
            requires_workspace=True,
            resource_scopes=("current_run_workspace",),
            workspace_target_paths=("path",),
        ),
    )

    assessment = classifier.classify(
        tool=edit_tool,
        request=build_request(
            "edit_file",
            {
                "path": path,
                "old_text": "value = 1",
                "new_text": "value = 2",
            },
        ),
    )

    assert assessment.risk_level is ToolRiskLevel.HIGH_RISK
    assert assessment.risk_categories == [ToolRiskCategory.BROAD_WRITE]
    assert assessment.requires_confirmation is True


def test_classify_exact_runtime_root_mutation_in_command_as_blocked() -> None:
    classifier = ToolRiskClassifier()
    bash_tool = fake_tool_fixture(
        name="bash",
        side_effect_level=ToolSideEffectLevel.PROCESS_EXECUTION,
    )

    assessment = classifier.classify(
        tool=bash_tool,
        request=build_request("bash", {"command": "rm -rf .runtime"}),
    )

    assert assessment.risk_level is ToolRiskLevel.BLOCKED
    assert assessment.risk_categories == [
        ToolRiskCategory.PLATFORM_RUNTIME_MUTATION
    ]
    assert assessment.requires_confirmation is False


def test_classify_dot_runtime_root_command_mutation_as_blocked() -> None:
    classifier = ToolRiskClassifier()
    bash_tool = fake_tool_fixture(
        name="bash",
        side_effect_level=ToolSideEffectLevel.PROCESS_EXECUTION,
    )

    assessment = classifier.classify(
        tool=bash_tool,
        request=build_request("bash", {"command": "rm -rf ./.runtime"}),
    )

    assert assessment.risk_level is ToolRiskLevel.BLOCKED
    assert assessment.risk_categories == [
        ToolRiskCategory.PLATFORM_RUNTIME_MUTATION
    ]
    assert assessment.requires_confirmation is False


def test_classifier_builds_stable_confirmation_object_ref_and_input_digest() -> None:
    classifier = ToolRiskClassifier()
    bash_tool = fake_tool_fixture(
        name="bash",
        side_effect_level=ToolSideEffectLevel.PROCESS_EXECUTION,
    )
    payload = {"env": {"B": "2", "A": "1"}, "command": "pip install pytest"}
    expected_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assessment = classifier.classify(
        tool=bash_tool,
        request=build_request("bash", payload),
    )

    assert assessment.risk_level is ToolRiskLevel.HIGH_RISK
    assert assessment.input_digest == expected_digest
    assert (
        assessment.confirmation_object_ref
        == f"tool-call:bash:call-bash:{expected_digest[:12]}"
    )


def test_public_contract_models_are_stable_strict_value_objects() -> None:
    grant = ToolConfirmationGrant(
        tool_confirmation_id="tool-confirmation-1",
        confirmation_object_ref="tool-call:bash:call-bash:abc123",
        tool_name="bash",
        input_digest="abc123",
        target_summary="command: npm install vite",
        risk_level=ToolRiskLevel.HIGH_RISK,
        risk_categories=[ToolRiskCategory.DEPENDENCY_CHANGE],
    )
    assessment = ToolRiskAssessment(
        risk_level=ToolRiskLevel.HIGH_RISK,
        risk_categories=[ToolRiskCategory.DEPENDENCY_CHANGE],
        reason="Dependency change requires confirmation.",
        command_preview="npm install vite",
        target_summary="command: npm install vite",
        expected_side_effects=["May modify dependencies."],
        alternative_path_summary=None,
        input_digest="abc123",
        confirmation_object_ref="tool-call:bash:call-bash:abc123",
    )
    record = ToolConfirmationRequestRecord(
        tool_confirmation_id="tool-confirmation-1",
        confirmation_object_ref="tool-call:bash:call-bash:abc123",
    )

    assert grant.tool_name == "bash"
    assert assessment.requires_confirmation is True
    assert record.tool_confirmation_id == "tool-confirmation-1"


def test_high_risk_dependency_change_does_not_imply_continue_current_stage_followup() -> None:
    classifier = ToolRiskClassifier()
    bash_tool = fake_tool_fixture(
        name="bash",
        side_effect_level=ToolSideEffectLevel.PROCESS_EXECUTION,
    )

    assessment = classifier.classify(
        tool=bash_tool,
        request=build_request("bash", {"command": "npm install vite"}),
    )

    assert assessment.risk_level is ToolRiskLevel.HIGH_RISK
    assert assessment.risk_categories == [ToolRiskCategory.DEPENDENCY_CHANGE]
    assert assessment.alternative_path_summary is None
