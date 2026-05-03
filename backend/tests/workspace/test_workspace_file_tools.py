from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.domain.enums import StageType, ToolRiskCategory, ToolRiskLevel
from backend.app.domain.trace_context import TraceContext
from backend.app.tools.execution_gate import ToolExecutionContext, ToolExecutionRequest
from backend.app.tools.protocol import ToolAuditRef, ToolInput, ToolResultStatus
from backend.app.tools.registry import ToolRegistry
from backend.app.tools.risk import ToolConfirmationGrant, ToolConfirmationRequestRecord
from backend.app.workspace.manager import EnvironmentSettings, RunWorkspace, WorkspaceManager
from backend.app.workspace.tools import FileEditTool, FileReadTool, FileWriteTool, GlobTool


NOW = datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC)


def _trace() -> TraceContext:
    return TraceContext(
        request_id="request-workspace-tools-1",
        trace_id="trace-workspace-tools-1",
        correlation_id="correlation-workspace-tools-1",
        span_id="span-workspace-tools-1",
        parent_span_id=None,
        session_id="session-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        created_at=NOW,
    )


@dataclass(frozen=True)
class _WorkspaceBoundary:
    manager: WorkspaceManager
    workspace: RunWorkspace

    def assert_inside_workspace(
        self,
        target: str,
        *,
        trace_context: TraceContext,
    ) -> None:
        self.manager.assert_inside_workspace(
            target,
            workspace=self.workspace,
            trace_context=trace_context,
        )


class _RecordingAudit:
    def __init__(self) -> None:
        self.intents: list[str] = []
        self.rejections: list[str] = []

    def record_tool_intent(
        self,
        *,
        request: ToolExecutionRequest,
        tool_name: str,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.intents.append(tool_name)
        return ToolAuditRef(
            audit_id=f"audit-{request.call_id}",
            action="tool.intent",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-{request.call_id}",
        )

    def record_tool_rejection(
        self,
        *,
        request: ToolExecutionRequest,
        error_code: object,
        trace_context: TraceContext,
    ) -> ToolAuditRef:
        self.rejections.append(str(error_code))
        return ToolAuditRef(
            audit_id=f"audit-reject-{request.call_id}",
            action="tool.rejected",
            trace_id=trace_context.trace_id,
            correlation_id=trace_context.correlation_id,
            metadata_ref=f"payload-reject-{request.call_id}",
        )


class _RecordingConfirmationPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_request(self, **kwargs: object) -> ToolConfirmationRequestRecord:
        self.calls.append(dict(kwargs))
        return ToolConfirmationRequestRecord(
            tool_confirmation_id="tool-confirmation-1",
            confirmation_object_ref=str(kwargs["confirmation_object_ref"]),
        )


class _RecordingRunLog:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record_tool_result(
        self,
        *,
        request: ToolExecutionRequest,
        result,
        duration_ms: int,
    ) -> None:
        self.records.append(
            {
                "tool_name": request.tool_name,
                "status": result.status,
                "audit_ref": result.audit_ref,
                "error_code": result.error.error_code if result.error else None,
                "duration_ms": duration_ms,
            }
        )


@dataclass(frozen=True)
class _ToolHarness:
    workspace: RunWorkspace
    registry: ToolRegistry
    context: ToolExecutionContext
    trace_context: TraceContext
    audit: _RecordingAudit
    confirmations: _RecordingConfirmationPort
    run_log: _RecordingRunLog


def _build_harness(tmp_path: Path) -> _ToolHarness:
    return _build_harness_with_runtime_root(tmp_path, platform_runtime_root=None)


def _build_harness_with_runtime_root(
    tmp_path: Path,
    *,
    platform_runtime_root: Path | None,
) -> _ToolHarness:
    project_root = tmp_path / "project"
    project_root.mkdir()
    settings_kwargs = {
        "default_project_root": project_root,
        "workspace_root": project_root,
    }
    if platform_runtime_root is not None:
        settings_kwargs["platform_runtime_root"] = platform_runtime_root
    manager = WorkspaceManager(
        settings=EnvironmentSettings(**settings_kwargs)
    )
    trace_context = _trace()
    workspace = manager.create_for_run(
        run_id=trace_context.run_id or "run-1",
        workspace_ref="workspace-1",
        trace_context=trace_context,
    )
    registry = ToolRegistry(
        [
            FileReadTool(manager=manager, workspace=workspace),
            GlobTool(manager=manager, workspace=workspace),
            FileWriteTool(manager=manager, workspace=workspace),
            FileEditTool(manager=manager, workspace=workspace),
        ]
    )
    audit = _RecordingAudit()
    confirmations = _RecordingConfirmationPort()
    run_log = _RecordingRunLog()
    context = ToolExecutionContext(
        stage_type=StageType.CODE_GENERATION,
        stage_contracts={
            StageType.CODE_GENERATION.value: {
                "allowed_tools": ["read_file", "glob", "write_file", "edit_file"]
            }
        },
        trace_context=trace_context,
        workspace_boundary=_WorkspaceBoundary(manager=manager, workspace=workspace),
        audit_recorder=audit,
        confirmation_port=confirmations,
        run_log_recorder=run_log,
    )
    return _ToolHarness(
        workspace=workspace,
        registry=registry,
        context=context,
        trace_context=trace_context,
        audit=audit,
        confirmations=confirmations,
        run_log=run_log,
    )


def _request(
    tool_name: str,
    payload: dict[str, object],
    *,
    trace_context: TraceContext,
) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_name=tool_name,
        call_id=f"call-{tool_name.replace('_', '-')}",
        input_payload=payload,
        trace_context=trace_context,
        coordination_key=f"coordination-{tool_name.replace('_', '-')}",
    )


def _tool_input(
    tool_name: str,
    payload: dict[str, object],
    *,
    trace_context: TraceContext,
) -> ToolInput:
    return ToolInput(
        tool_name=tool_name,
        call_id=f"direct-{tool_name.replace('_', '-')}",
        input_payload=payload,
        trace_context=trace_context,
        coordination_key=f"direct-coordination-{tool_name.replace('_', '-')}",
    )


def test_write_file_overwrites_content_and_emits_side_effect_ref(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('old')\n", encoding="utf-8")
    initial_request = _request(
        "write_file",
        {"path": "src/app.py", "content": "print('new')\n"},
        trace_context=harness.trace_context,
    )

    pending = harness.registry.execute(initial_request, harness.context)
    assert pending.status is ToolResultStatus.WAITING_CONFIRMATION
    assert target.read_text(encoding="utf-8") == "print('old')\n"
    assert pending.error is not None
    confirmed_trace = harness.trace_context.model_copy(
        update={"tool_confirmation_id": pending.tool_confirmation_ref}
    )
    confirmed_request = ToolExecutionRequest(
        tool_name=initial_request.tool_name,
        call_id=initial_request.call_id,
        input_payload=initial_request.input_payload,
        trace_context=confirmed_trace,
        coordination_key=initial_request.coordination_key,
        confirmation_grant=ToolConfirmationGrant(
            tool_confirmation_id=str(pending.tool_confirmation_ref),
            confirmation_object_ref=str(
                harness.confirmations.calls[0]["confirmation_object_ref"]
            ),
            tool_name="write_file",
            input_digest=str(pending.error.safe_details["input_digest"]),
            target_summary=str(pending.error.safe_details["target_summary"]),
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
        ),
    )

    result = harness.registry.execute(confirmed_request, harness.context)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {"path": "src/app.py", "bytes_written": 13}
    assert result.output_preview == "Wrote src/app.py (13 bytes)"
    assert result.side_effect_refs == [
        "file_edit_trace:run-1:call-write-file:src/app.py"
    ]
    assert result.audit_ref is not None
    assert result.audit_ref.audit_id == "audit-call-write-file"
    assert harness.audit.intents == ["write_file", "write_file"]
    assert target.read_text(encoding="utf-8") == "print('new')\n"


def test_runtime_logs_are_blocked_by_real_workspace_boundary_through_registry(
    tmp_path: Path,
) -> None:
    harness = _build_harness_with_runtime_root(
        tmp_path,
        platform_runtime_root=tmp_path / "project" / ".runtime",
    )

    result = harness.registry.execute(
        _request(
            "read_file",
            {"path": ".runtime/logs/run.jsonl"},
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.BLOCKED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert result.error.error_code.value == "tool_workspace_boundary_violation"
    assert result.error.safe_details == {
        "target": ".runtime/logs/run.jsonl",
        "requested_tool_name": "read_file",
    }
    assert harness.audit.rejections == ["tool_workspace_boundary_violation"]
    assert harness.run_log.records[-1]["status"] is ToolResultStatus.BLOCKED
    assert (
        harness.run_log.records[-1]["error_code"]
        is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    )


def test_write_file_preserves_audit_ref_and_records_run_log_result(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    initial_request = _request(
        "write_file",
        {"path": "src/audit.py", "content": "print('audit')\n"},
        trace_context=harness.trace_context,
    )
    pending = harness.registry.execute(initial_request, harness.context)
    confirmed_trace = harness.trace_context.model_copy(
        update={"tool_confirmation_id": pending.tool_confirmation_ref}
    )
    confirmed_request = ToolExecutionRequest(
        tool_name=initial_request.tool_name,
        call_id=initial_request.call_id,
        input_payload=initial_request.input_payload,
        trace_context=confirmed_trace,
        coordination_key=initial_request.coordination_key,
        confirmation_grant=ToolConfirmationGrant(
            tool_confirmation_id=str(pending.tool_confirmation_ref),
            confirmation_object_ref=str(
                harness.confirmations.calls[0]["confirmation_object_ref"]
            ),
            tool_name="write_file",
            input_digest=str(pending.error.safe_details["input_digest"]),
            target_summary=str(pending.error.safe_details["target_summary"]),
            risk_level=ToolRiskLevel.HIGH_RISK,
            risk_categories=[ToolRiskCategory.UNKNOWN_COMMAND],
        ),
    )

    result = harness.registry.execute(confirmed_request, harness.context)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.audit_ref is not None
    assert result.audit_ref.audit_id == "audit-call-write-file"
    assert harness.run_log.records[-1] == {
        "tool_name": "write_file",
        "status": ToolResultStatus.SUCCEEDED,
        "audit_ref": result.audit_ref,
        "error_code": None,
        "duration_ms": harness.run_log.records[-1]["duration_ms"],
    }


def test_edit_file_preserves_audit_ref_and_records_run_log_result(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "src" / "audit.py"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")

    result = harness.registry.execute(
        _request(
            "edit_file",
            {"path": "src/audit.py", "old_text": "before", "new_text": "after"},
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.audit_ref is not None
    assert result.audit_ref.audit_id == "audit-call-edit-file"
    assert harness.run_log.records[-1] == {
        "tool_name": "edit_file",
        "status": ToolResultStatus.SUCCEEDED,
        "audit_ref": result.audit_ref,
        "error_code": None,
        "duration_ms": harness.run_log.records[-1]["duration_ms"],
    }


def test_large_read_and_write_previews_are_truncated_with_redaction_suffix(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    large_content = "x" * 5000
    read_target = harness.workspace.root / "src" / "large.txt"
    read_target.parent.mkdir(parents=True)
    read_target.write_text(large_content, encoding="utf-8")

    read_result = harness.registry.execute(
        _request(
            "read_file",
            {"path": "src/large.txt"},
            trace_context=harness.trace_context,
        ),
        harness.context,
    )
    write_result = harness.registry.resolve("write_file").execute(
        _tool_input(
            "write_file",
            {"path": "src/write-preview.txt", "content": large_content},
            trace_context=harness.trace_context,
        )
    )

    assert read_result.status is ToolResultStatus.SUCCEEDED
    assert read_result.output_preview is not None
    assert len(read_result.output_preview) == 4096
    assert read_result.output_preview.endswith("...[truncated]")
    assert write_result.status is ToolResultStatus.SUCCEEDED
    assert write_result.output_preview is not None
    assert len(write_result.output_preview) == 4096
    assert write_result.output_preview.endswith("...[truncated]")


def test_large_edit_preview_is_truncated_with_redaction_suffix(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "src" / "edit-preview.txt"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")

    result = harness.registry.resolve("edit_file").execute(
        _tool_input(
            "edit_file",
            {
                "path": "src/edit-preview.txt",
                "old_text": "old",
                "new_text": "x" * 5000,
            },
            trace_context=harness.trace_context,
        )
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_preview is not None
    assert len(result.output_preview) == 4096
    assert result.output_preview.endswith("...[truncated]")


def test_read_file_directly_maps_workspace_boundary_to_existing_error_contract(
    tmp_path: Path,
) -> None:
    harness = _build_harness_with_runtime_root(
        tmp_path,
        platform_runtime_root=tmp_path / "project" / ".runtime",
    )
    tool = harness.registry.resolve("read_file")

    result = tool.execute(
        _tool_input(
            "read_file",
            {"path": ".runtime/logs/run.jsonl"},
            trace_context=harness.trace_context,
        )
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert result.error.error_code.value == "tool_workspace_boundary_violation"
    assert result.error.safe_details == {"target": ".runtime/logs/run.jsonl"}


def test_write_file_creates_missing_parents_and_preserves_exact_utf8_bytes(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "new" / "nested" / "crlf.txt"
    content = "alpha\nbeta\r\ngamma\n"
    expected_bytes = content.encode("utf-8")
    tool = harness.registry.resolve("write_file")

    result = tool.execute(
        _tool_input(
            "write_file",
            {"path": "new/nested/crlf.txt", "content": content},
            trace_context=harness.trace_context,
        )
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "path": "new/nested/crlf.txt",
        "bytes_written": len(expected_bytes),
    }
    assert target.parent.is_dir()
    assert target.read_bytes() == expected_bytes


def test_edit_file_replaces_exact_match_once_and_emits_side_effect_ref(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"value = 1\nprint(value)\n")

    result = harness.registry.execute(
        _request(
            "edit_file",
            {
                "path": "src/app.py",
                "old_text": "value = 1",
                "new_text": "value = 2",
            },
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "path": "src/app.py",
        "replacements": 1,
        "bytes_written": 23,
    }
    assert result.output_preview == "Edited src/app.py (1 replacement, 23 bytes)"
    assert result.side_effect_refs == [
        "file_edit_trace:run-1:call-edit-file:src/app.py"
    ]
    assert result.audit_ref is not None
    assert result.audit_ref.audit_id == "audit-call-edit-file"
    assert harness.audit.intents == ["edit_file"]
    assert target.read_bytes() == b"value = 2\nprint(value)\n"


def test_edit_file_replaces_crlf_text_and_preserves_crlf_bytes(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "src" / "crlf.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"first\r\nold line\r\nlast\r\n")
    expected_bytes = b"first\r\nnew line\r\nlast\r\n"
    tool = harness.registry.resolve("edit_file")

    result = tool.execute(
        _tool_input(
            "edit_file",
            {
                "path": "src/crlf.txt",
                "old_text": "old line\r\nlast",
                "new_text": "new line\r\nlast",
            },
            trace_context=harness.trace_context,
        )
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "path": "src/crlf.txt",
        "replacements": 1,
        "bytes_written": len(expected_bytes),
    }
    assert target.read_bytes() == expected_bytes


@pytest.mark.parametrize(
    ("initial_content", "old_text", "reason"),
    [
        ("value = 1\n", "missing", "edit_target_missing"),
        ("value = 1\nvalue = 1\n", "value = 1", "edit_target_not_unique"),
    ],
)
def test_edit_file_rejects_missing_or_non_unique_target_without_mutation(
    tmp_path: Path,
    initial_content: str,
    old_text: str,
    reason: str,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text(initial_content, encoding="utf-8")

    result = harness.registry.execute(
        _request(
            "edit_file",
            {
                "path": "src/app.py",
                "old_text": old_text,
                "new_text": "value = 2",
            },
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.output_payload == {}
    assert result.output_preview is None
    assert result.error is not None
    assert result.error.safe_details == {"path": "src/app.py", "reason": reason}
    assert result.side_effect_refs == []
    assert target.read_text(encoding="utf-8") == initial_content


def test_edit_file_rejects_overlapping_non_unique_target_without_mutation(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("aaa", encoding="utf-8")

    result = harness.registry.execute(
        _request(
            "edit_file",
            {
                "path": "src/app.py",
                "old_text": "aa",
                "new_text": "b",
            },
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.output_payload == {}
    assert result.output_preview is None
    assert result.error is not None
    assert result.error.safe_details == {
        "path": "src/app.py",
        "reason": "edit_target_not_unique",
    }
    assert result.side_effect_refs == []
    assert target.read_text(encoding="utf-8") == "aaa"


def test_read_file_registers_and_reads_utf8_text_through_tool_registry(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_bytes("print('hello')\n".encode("utf-8"))

    result = harness.registry.execute(
        _request(
            "read_file",
            {"path": "src/app.py"},
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "path": "src/app.py",
        "content": "print('hello')\n",
    }
    assert result.output_preview == "src/app.py\nprint('hello')\n"
    assert result.error is None


def test_read_file_rejects_binary_content_without_returning_raw_bytes(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "assets" / "image.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x00\xffraw-bytes")

    result = harness.registry.execute(
        _request(
            "read_file",
            {"path": "assets/image.bin"},
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.output_payload == {}
    assert result.output_preview is None
    assert result.error is not None
    assert result.error.safe_details == {
        "path": "assets/image.bin",
        "reason": "not_utf8_text",
    }
    assert "raw-bytes" not in result.error.safe_message
    assert "raw-bytes" not in str(result.error.safe_details)


def test_read_file_rejects_utf8_decodable_rich_media_by_file_type(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / "assets" / "icon.svg"
    target.parent.mkdir(parents=True)
    target.write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4" /></svg>'
    )

    result = harness.registry.execute(
        _request(
            "read_file",
            {"path": "assets/icon.svg"},
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.output_payload == {}
    assert result.output_preview is None
    assert result.error is not None
    assert result.error.safe_details == {
        "path": "assets/icon.svg",
        "reason": "unsupported_file_type",
    }
    assert "<svg" not in str(result.output_payload)
    assert "<svg" not in result.error.safe_message


def test_read_file_directly_rejects_private_runtime_log_path(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    target = harness.workspace.root / ".runtime" / "logs" / "run.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text('{"event":"private"}\n', encoding="utf-8")
    tool = harness.registry.resolve("read_file")

    result = tool.execute(
        _tool_input(
            "read_file",
            {"path": ".runtime/logs/run.jsonl"},
            trace_context=harness.trace_context,
        )
    )

    assert result.status is not ToolResultStatus.SUCCEEDED
    assert result.output_payload == {}
    assert result.output_preview is None
    assert result.error is not None
    assert result.error.safe_details == {
        "path": ".runtime/logs/run.jsonl",
        "reason": "workspace_path_excluded",
    }
    assert "private" not in str(result.output_payload)
    assert "private" not in result.error.safe_message


def test_glob_registers_and_returns_sorted_relative_matches_without_file_content(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    files = {
        "src/zeta.py": "print('zeta')\n",
        "src/alpha.py": "print('alpha')\n",
        "src/nested/beta.py": "print('beta')\n",
        "src/nested/readme.md": "# nested\n",
        ".runtime/logs/run.jsonl": '{"event":"private"}\n',
    }
    for relative_path, content in files.items():
        target = harness.workspace.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    result = harness.registry.execute(
        _request(
            "glob",
            {"pattern": "**/*.py"},
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "matches": [
            {"path": "src/alpha.py", "path_type": "file"},
            {"path": "src/nested/beta.py", "path_type": "file"},
            {"path": "src/zeta.py", "path_type": "file"},
        ]
    }
    assert result.output_preview == "\n".join(
        ["src/alpha.py", "src/nested/beta.py", "src/zeta.py"]
    )
    assert "print(" not in str(result.output_payload)
    assert ".runtime/logs" not in str(result.output_payload)


def test_glob_excludes_runtime_logs_when_broad_pattern_would_match_them(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    files = {
        "README.md": "# Fixture\n",
        "src/app.py": "print('visible')\n",
        ".runtime/logs/run.jsonl": '{"event":"private"}\n',
    }
    for relative_path, content in files.items():
        target = harness.workspace.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    result = harness.registry.execute(
        _request(
            "glob",
            {"pattern": "**/*"},
            trace_context=harness.trace_context,
        ),
        harness.context,
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output_payload == {
        "matches": [
            {"path": "README.md", "path_type": "file"},
            {"path": "src/app.py", "path_type": "file"},
        ]
    }
    assert ".runtime/logs/run.jsonl" not in str(result.output_payload)


def test_glob_directly_rejects_escape_pattern_with_structured_result(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    tool = harness.registry.resolve("glob")

    result = tool.execute(
        _tool_input(
            "glob",
            {"pattern": "../**/*"},
            trace_context=harness.trace_context,
        )
    )

    assert result.status is not ToolResultStatus.SUCCEEDED
    assert result.output_payload == {}
    assert result.output_preview is None
    assert result.error is not None
    assert result.error.safe_details == {
        "pattern": "../**/*",
        "reason": "invalid_glob_pattern",
    }


def test_glob_directly_rejects_expanded_candidate_outside_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = _build_harness(tmp_path)
    outside_file = tmp_path / "outside" / "escape.py"
    outside_file.parent.mkdir()
    outside_file.write_text("print('outside')\n", encoding="utf-8")
    original_glob = Path.glob

    def fake_glob(path: Path, pattern: str):
        if path == harness.workspace.root and pattern == "**/*.py":
            return iter([outside_file])
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", fake_glob)
    tool = harness.registry.resolve("glob")

    result = tool.execute(
        _tool_input(
            "glob",
            {"pattern": "**/*.py"},
            trace_context=harness.trace_context,
        )
    )

    assert result.status is not ToolResultStatus.SUCCEEDED
    assert result.output_payload == {}
    assert result.output_preview is None
    assert result.error is not None
    assert result.error.safe_details == {
        "path": str(outside_file),
        "reason": "workspace_candidate_outside",
    }
    assert "outside" not in str(result.output_payload)


def test_glob_directly_maps_runtime_log_candidate_boundary_to_existing_error_contract(
    tmp_path: Path,
) -> None:
    harness = _build_harness_with_runtime_root(
        tmp_path,
        platform_runtime_root=tmp_path / "project" / ".runtime",
    )
    logs_dir = harness.workspace.root / ".runtime" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "run.jsonl").write_text('{"event":"private"}\n', encoding="utf-8")
    tool = harness.registry.resolve("glob")

    result = tool.execute(
        _tool_input(
            "glob",
            {"pattern": "**/*"},
            trace_context=harness.trace_context,
        )
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.output_payload == {}
    assert result.output_preview is None
    assert result.error is not None
    assert result.error.error_code is ErrorCode.TOOL_WORKSPACE_BOUNDARY_VIOLATION
    assert result.error.error_code.value == "tool_workspace_boundary_violation"
    assert result.error.safe_details == {"target": ".runtime/logs/run.jsonl"}
