from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isfinite
import posixpath
from pathlib import PureWindowsPath
from types import MappingProxyType
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.enums import ContractEnum


JsonObject = dict[str, Any]
FrozenJsonObject = Mapping[str, Any]
_PLATFORM_PRIVATE_RELATIVE_PATHS = frozenset({".runtime/logs"})


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if isfinite(value):
            return
        raise ValueError(f"{path} must be a finite JSON number")
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} must be JSON-serializable")


def _validate_json_object(value: JsonObject) -> JsonObject:
    _validate_json_value(value, path="$")
    return value


def _freeze_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json_value(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json_value(item) for item in value)
    return value


def _freeze_json_object(value: JsonObject) -> FrozenJsonObject:
    _validate_json_object(value)
    return _freeze_json_value(value)


def _normalize_relative_path(path: str) -> str:
    raw_path = path.replace("\\", "/").strip()
    if ".." in raw_path.split("/"):
        raise ValueError("path must be a safe relative path")
    normalized = posixpath.normpath(raw_path)
    if normalized in {"", "."}:
        raise ValueError("path must be a safe relative path")
    if normalized.startswith("../") or normalized == "..":
        raise ValueError("path must be a safe relative path")
    if normalized.startswith("/"):
        raise ValueError("path must be a safe relative path")
    if PureWindowsPath(raw_path).drive:
        raise ValueError("path must be a safe relative path")
    return normalized.rstrip("/")


def _is_excluded_path(path: str, *, excluded_relative_paths: Sequence[str]) -> bool:
    normalized = _normalize_relative_path(path)
    prefixes = (
        *(_normalize_relative_path(value) for value in excluded_relative_paths),
        *_PLATFORM_PRIVATE_RELATIVE_PATHS,
    )
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in prefixes
    )


def _retain_trace_ref(ref: str, *, retained_paths: set[str]) -> bool:
    if not ref.startswith("file_edit_trace:"):
        return True
    parts = ref.split(":", 3)
    if len(parts) != 4 or any(not part for part in parts):
        raise ValueError("malformed file_edit_trace ref")
    _, _, _, path = parts
    return _normalize_relative_path(path) in retained_paths


class ChangeOperation(ContractEnum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"


class ContextReferenceKind(ContractEnum):
    REQUIREMENT_MESSAGE = "requirement_message"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    CLARIFICATION = "clarification"
    SOLUTION_ARTIFACT = "solution_artifact"
    APPROVAL_FEEDBACK = "approval_feedback"
    TOOL_CONFIRMATION = "tool_confirmation"
    TOOL_OBSERVATION = "tool_observation"
    FILE_PATH = "file_path"
    DIRECTORY_PATH = "directory_path"
    FILE_EXCERPT = "file_excerpt"
    FILE_VERSION = "file_version"
    DIFF = "diff"
    TEST_RESULT = "test_result"
    REVIEW_FEEDBACK = "review_feedback"
    CHANGE_SET = "change_set"
    COMPRESSED_CONTEXT = "compressed_context"
    PAGE_SELECTION = "page_selection"
    DOM_ANCHOR = "dom_anchor"
    PREVIEW_SNAPSHOT = "preview_snapshot"


class ContextReference(_StrictFrozenModel):
    reference_id: str = Field(min_length=1)
    kind: ContextReferenceKind
    source_ref: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    path: str | None = Field(default=None, min_length=1)
    version_ref: str | None = Field(default=None, min_length=1)
    metadata: FrozenJsonObject = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: JsonObject) -> FrozenJsonObject:
        return _freeze_json_object(value)

    @property
    def ref(self) -> str:
        return f"context-reference://{self.reference_id}"


class ChangeSetFile(_StrictFrozenModel):
    path: str = Field(min_length=1)
    operation: ChangeOperation
    diff_ref: str | None = Field(default=None, min_length=1)
    previous_path: str | None = Field(default=None, min_length=1)

    @field_validator("path", "previous_path")
    @classmethod
    def validate_paths(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value)

    @model_validator(mode="after")
    def validate_rename_shape(self) -> ChangeSetFile:
        if self.operation is ChangeOperation.RENAME and self.previous_path is None:
            raise ValueError("rename change entries require previous_path")
        if self.operation is not ChangeOperation.RENAME and self.previous_path is not None:
            raise ValueError(
                "previous_path is only allowed for rename change entries"
            )
        if self.operation is ChangeOperation.RENAME and self.path == self.previous_path:
            raise ValueError("rename change entries require a different previous_path")
        return self


class ChangeSet(_StrictFrozenModel):
    change_set_id: str = Field(min_length=1)
    workspace_ref: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_run_id: str | None = Field(default=None, min_length=1)
    files: tuple[ChangeSetFile, ...] = Field(default_factory=tuple)
    context_references: tuple[ContextReference, ...] = Field(default_factory=tuple)
    file_edit_trace_refs: tuple[str, ...] = Field(default_factory=tuple)
    created_at: datetime

    @model_validator(mode="after")
    def validate_unique_paths(self) -> ChangeSet:
        retained_paths = [item.path for item in self.files]
        if len(retained_paths) != len(set(retained_paths)):
            raise ValueError("duplicate retained change path")
        return self

    @property
    def ref(self) -> str:
        return f"changeset://{self.change_set_id}"

    @property
    def changed_files(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)

    @property
    def diff_refs(self) -> tuple[str, ...]:
        return tuple(item.diff_ref for item in self.files if item.diff_ref is not None)

    @classmethod
    def from_workspace_delta(
        cls,
        *,
        change_set_id: str,
        workspace_ref: str,
        run_id: str,
        stage_run_id: str | None = None,
        files: Sequence[ChangeSetFile],
        context_references: Sequence[ContextReference] = (),
        file_edit_trace_refs: Sequence[str] = (),
        workspace_excluded_relative_paths: Sequence[str] = (),
        created_at: datetime,
    ) -> ChangeSet:
        retained_files = tuple(
            item
            for item in files
            if not _is_excluded_path(
                item.path,
                excluded_relative_paths=workspace_excluded_relative_paths,
            )
        )
        retained_paths = {item.path for item in retained_files}
        retained_trace_refs = tuple(
            ref
            for ref in file_edit_trace_refs
            if _retain_trace_ref(ref, retained_paths=retained_paths)
        )
        return cls(
            change_set_id=change_set_id,
            workspace_ref=workspace_ref,
            run_id=run_id,
            stage_run_id=stage_run_id,
            files=retained_files,
            context_references=tuple(context_references),
            file_edit_trace_refs=retained_trace_refs,
            created_at=created_at,
        )


__all__ = [
    "ChangeOperation",
    "ChangeSet",
    "ChangeSetFile",
    "ContextReference",
    "ContextReferenceKind",
]
