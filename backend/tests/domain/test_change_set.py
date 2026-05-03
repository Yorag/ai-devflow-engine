from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.domain.changes import (
    ChangeOperation,
    ChangeSet,
    ChangeSetFile,
    ContextReference,
    ContextReferenceKind,
)


NOW = datetime(2026, 5, 4, 15, 0, 0, tzinfo=UTC)


def _requirement_ref() -> ContextReference:
    return ContextReference(
        reference_id="ctx-requirement-1",
        kind=ContextReferenceKind.REQUIREMENT_MESSAGE,
        source_ref="message://session-1/1",
        source_label="Initial requirement",
    )


def test_context_reference_supports_current_and_future_reference_kinds() -> None:
    current = ContextReference(
        reference_id="ctx-diff-1",
        kind=ContextReferenceKind.DIFF,
        source_ref="diff://run-1/src/app.py",
        source_label="src/app.py diff",
        path="src/app.py",
        metadata={"line_count": 12},
    )
    future = ContextReference(
        reference_id="ctx-preview-1",
        kind=ContextReferenceKind.PREVIEW_SNAPSHOT,
        source_ref="preview://run-1/snapshot-1",
        source_label="Future preview snapshot",
        metadata={"viewport": "desktop"},
    )

    assert current.ref == "context-reference://ctx-diff-1"
    assert current.path == "src/app.py"
    assert future.kind is ContextReferenceKind.PREVIEW_SNAPSHOT


def test_change_set_from_workspace_delta_filters_runtime_private_and_excluded_paths() -> None:
    change_set = ChangeSet.from_workspace_delta(
        change_set_id="changeset-1",
        workspace_ref="workspace-run-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        files=[
            ChangeSetFile(
                path="src/app.py",
                operation=ChangeOperation.MODIFY,
                diff_ref="diff://run-1/src/app.py",
            ),
            ChangeSetFile(
                path=".runtime/logs/run.jsonl",
                operation=ChangeOperation.MODIFY,
                diff_ref="diff://run-1/.runtime/logs/run.jsonl",
            ),
            ChangeSetFile(
                path="dist/app.js",
                operation=ChangeOperation.CREATE,
                diff_ref="diff://run-1/dist/app.js",
            ),
        ],
        context_references=[_requirement_ref()],
        file_edit_trace_refs=[
            "file_edit_trace:run-1:call-1:src/app.py",
            "file_edit_trace:run-1:call-1:.runtime/logs/run.jsonl",
            "file_edit_trace:run-1:call-1:dist/app.js",
        ],
        workspace_excluded_relative_paths=("dist",),
        created_at=NOW,
    )

    assert change_set.ref == "changeset://changeset-1"
    assert change_set.changed_files == ("src/app.py",)
    assert change_set.diff_refs == ("diff://run-1/src/app.py",)
    assert change_set.file_edit_trace_refs == (
        "file_edit_trace:run-1:call-1:src/app.py",
    )
    assert change_set.context_references[0].kind is ContextReferenceKind.REQUIREMENT_MESSAGE


def test_change_set_rejects_outside_paths_duplicate_paths_and_non_json_metadata() -> None:
    with pytest.raises(ValidationError, match="safe relative path"):
        ChangeSetFile(
            path="../outside.py",
            operation=ChangeOperation.MODIFY,
            diff_ref="diff://outside",
        )

    with pytest.raises(ValidationError, match="duplicate retained change path"):
        ChangeSet.from_workspace_delta(
            change_set_id="changeset-dup",
            workspace_ref="workspace-run-1",
            run_id="run-1",
            stage_run_id="stage-run-1",
            files=[
                ChangeSetFile(path="src/app.py", operation=ChangeOperation.MODIFY),
                ChangeSetFile(path="src//app.py", operation=ChangeOperation.DELETE),
            ],
            context_references=[_requirement_ref()],
            created_at=NOW,
        )

    with pytest.raises(ValidationError, match="JSON-serializable"):
        ContextReference(
            reference_id="ctx-bad",
            kind=ContextReferenceKind.TOOL_OBSERVATION,
            source_ref="tool://run-1/read-file",
            source_label="Bad metadata",
            metadata={"bad": {1, 2, 3}},
        )


@pytest.mark.parametrize(
    "unsafe_path",
    ["src/../app.py", "/absolute.py", "C:/absolute.py", " C:/outside.py "],
)
def test_change_set_file_rejects_unsafe_retained_paths(unsafe_path: str) -> None:
    with pytest.raises(ValidationError, match="safe relative path"):
        ChangeSetFile(path=unsafe_path, operation=ChangeOperation.MODIFY)


def test_change_set_rejects_malformed_file_edit_trace_refs() -> None:
    with pytest.raises(ValueError, match="malformed file_edit_trace ref"):
        ChangeSet.from_workspace_delta(
            change_set_id="changeset-bad-trace",
            workspace_ref="workspace-run-1",
            run_id="run-1",
            files=[
                ChangeSetFile(path="src/app.py", operation=ChangeOperation.MODIFY),
            ],
            file_edit_trace_refs=["file_edit_trace:missing-parts"],
            created_at=NOW,
        )


def test_change_set_rejects_unsafe_file_edit_trace_paths() -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        ChangeSet.from_workspace_delta(
            change_set_id="changeset-unsafe-trace",
            workspace_ref="workspace-run-1",
            run_id="run-1",
            files=[
                ChangeSetFile(path="src/app.py", operation=ChangeOperation.MODIFY),
            ],
            file_edit_trace_refs=[
                "file_edit_trace:run-1:call-1:src/../outside.py",
            ],
            created_at=NOW,
        )


def test_context_reference_metadata_is_immutable_after_construction() -> None:
    source_metadata = {"nested": {"items": ["a"], "count": 1}}
    reference = ContextReference(
        reference_id="ctx-metadata",
        kind=ContextReferenceKind.TOOL_OBSERVATION,
        source_ref="tool://run-1/read-file",
        source_label="Read file",
        metadata=source_metadata,
    )

    source_metadata["nested"]["items"].append("external")

    assert reference.metadata["nested"]["items"] == ("a",)
    with pytest.raises(TypeError):
        reference.metadata["added"] = True
    with pytest.raises(TypeError):
        reference.metadata["nested"]["count"] = 2
    with pytest.raises(TypeError):
        reference.metadata["nested"]["items"][0] = "changed"


def test_change_set_keeps_matching_trace_refs_and_enforces_rename_previous_path() -> None:
    change_set = ChangeSet.from_workspace_delta(
        change_set_id="changeset-rename-1",
        workspace_ref="workspace-run-1",
        run_id="run-1",
        stage_run_id="stage-run-1",
        files=[
            ChangeSetFile(
                path="src/new_name.py",
                previous_path="src/old_name.py",
                operation=ChangeOperation.RENAME,
                diff_ref="diff://run-1/src/new_name.py",
            )
        ],
        context_references=[
            ContextReference(
                reference_id="ctx-review-1",
                kind=ContextReferenceKind.REVIEW_FEEDBACK,
                source_ref="review://run-1/issue-1",
                source_label="Reviewer note",
            )
        ],
        file_edit_trace_refs=[
            "file_edit_trace:run-1:call-2:src/new_name.py",
            "file_edit_trace:run-1:call-2:.runtime/logs/run.jsonl",
            "command_trace:run-1:call-2",
        ],
        created_at=NOW,
    )

    assert change_set.files[0].previous_path == "src/old_name.py"
    assert change_set.file_edit_trace_refs == (
        "file_edit_trace:run-1:call-2:src/new_name.py",
        "command_trace:run-1:call-2",
    )

    with pytest.raises(ValidationError, match="require previous_path"):
        ChangeSetFile(path="src/new_name.py", operation=ChangeOperation.RENAME)

    with pytest.raises(ValidationError, match="only allowed for rename"):
        ChangeSetFile(
            path="src/app.py",
            previous_path="src/old_app.py",
            operation=ChangeOperation.MODIFY,
        )

    with pytest.raises(ValidationError, match="different previous_path"):
        ChangeSetFile(
            path="src/app.py",
            previous_path="src/app.py",
            operation=ChangeOperation.RENAME,
        )
