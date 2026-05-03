from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from backend.app.domain.enums import StageType


GRAPH_DEFINITION_SCHEMA_VERSION = "graph-definition-v1"
GRAPH_DEFINITION_VERSION = "function-one-mainline-v1"
JsonObject = dict[str, Any]


class FrozenDict(dict[str, Any]):
    def __delitem__(self, key: object) -> None:
        raise TypeError("graph definition mappings are immutable")

    def __setitem__(self, key: object, value: object) -> None:
        raise TypeError("graph definition mappings are immutable")

    def clear(self) -> None:
        raise TypeError("graph definition mappings are immutable")

    def pop(self, key: object, default: object | None = None) -> None:
        raise TypeError("graph definition mappings are immutable")

    def popitem(self) -> None:
        raise TypeError("graph definition mappings are immutable")

    def setdefault(self, key: object, default: object | None = None) -> None:
        raise TypeError("graph definition mappings are immutable")

    def update(self, *args: object, **kwargs: object) -> None:
        raise TypeError("graph definition mappings are immutable")

    def __ior__(self, value: object) -> "FrozenDict":
        raise TypeError("graph definition mappings are immutable")


class FrozenList(list[Any]):
    def __delitem__(self, key: object) -> None:
        raise TypeError("graph definition lists are immutable")

    def __setitem__(self, key: object, value: object) -> None:
        raise TypeError("graph definition lists are immutable")

    def append(self, value: object) -> None:
        raise TypeError("graph definition lists are immutable")

    def clear(self) -> None:
        raise TypeError("graph definition lists are immutable")

    def extend(self, values: object) -> None:
        raise TypeError("graph definition lists are immutable")

    def insert(self, index: int, value: object) -> None:
        raise TypeError("graph definition lists are immutable")

    def pop(self, index: int = -1) -> None:
        raise TypeError("graph definition lists are immutable")

    def remove(self, value: object) -> None:
        raise TypeError("graph definition lists are immutable")

    def reverse(self) -> None:
        raise TypeError("graph definition lists are immutable")

    def sort(self, *, key: Any = None, reverse: bool = False) -> None:
        raise TypeError("graph definition lists are immutable")

    def __iadd__(self, values: object) -> "FrozenList":
        raise TypeError("graph definition lists are immutable")

    def __imul__(self, value: object) -> "FrozenList":
        raise TypeError("graph definition lists are immutable")


class GraphDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_definition_id: StrictStr = Field(min_length=1, max_length=80)
    run_id: StrictStr = Field(min_length=1)
    template_snapshot_ref: StrictStr = Field(min_length=1)
    runtime_limit_snapshot_ref: StrictStr = Field(min_length=1)
    runtime_limit_source_config_version: StrictStr = Field(min_length=1)
    graph_version: Literal["function-one-mainline-v1"] = GRAPH_DEFINITION_VERSION
    stage_nodes: tuple[JsonObject, ...]
    stage_contracts: dict[str, JsonObject]
    interrupt_policy: JsonObject
    retry_policy: JsonObject
    delivery_routing_policy: JsonObject
    source_node_group_map: dict[str, str]
    schema_version: Literal["graph-definition-v1"] = GRAPH_DEFINITION_SCHEMA_VERSION
    created_at: datetime

    @field_validator("stage_nodes")
    @classmethod
    def _require_six_stage_nodes(
        cls,
        value: tuple[JsonObject, ...],
    ) -> tuple[JsonObject, ...]:
        if len(value) != 6:
            raise ValueError("stage_nodes must contain the six formal business stages")
        return tuple(_freeze_json_value(node) for node in value)

    @field_validator("stage_contracts")
    @classmethod
    def _require_stage_contract_keys(
        cls,
        value: dict[str, JsonObject],
    ) -> dict[str, JsonObject]:
        expected = {stage.value for stage in StageType}
        if set(value) != expected:
            raise ValueError("stage_contracts must cover all formal stage types")
        return FrozenDict(
            {
                stage_type: _freeze_json_value(contract)
                for stage_type, contract in value.items()
            }
        )

    @field_validator(
        "interrupt_policy",
        "retry_policy",
        "delivery_routing_policy",
    )
    @classmethod
    def _freeze_json_object(
        cls,
        value: JsonObject,
    ) -> JsonObject:
        frozen = _freeze_json_value(value)
        if not isinstance(frozen, dict):
            raise TypeError("graph definition payload must remain a mapping")
        return frozen

    @field_validator("source_node_group_map")
    @classmethod
    def _require_stage_type_targets(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        valid_targets = {stage.value for stage in StageType}
        invalid = sorted(target for target in value.values() if target not in valid_targets)
        if invalid:
            raise ValueError("source_node_group_map must target formal stage types only")
        return FrozenDict(value)


def _freeze_json_value(value: object) -> object:
    if isinstance(value, FrozenDict | FrozenList):
        return value
    if isinstance(value, dict):
        return FrozenDict(
            {key: _freeze_json_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return FrozenList(_freeze_json_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_json_value(item) for item in value)
    return value


def build_fixed_stage_sequence() -> tuple[StageType, ...]:
    return (
        StageType.REQUIREMENT_ANALYSIS,
        StageType.SOLUTION_DESIGN,
        StageType.CODE_GENERATION,
        StageType.TEST_GENERATION_EXECUTION,
        StageType.CODE_REVIEW,
        StageType.DELIVERY_INTEGRATION,
    )


def build_solution_design_node_group() -> dict[str, object]:
    return {
        "node_key": "solution_design",
        "stage_type": "solution_design",
        "node_groups": [
            "solution_design_authoring",
            "solution_validation",
        ],
        "entry_node_key": "solution_design.authoring",
        "success_node_key": "solution_design.approval_gate",
        "failure_route": {
            "from": "solution_validation",
            "to": "solution_design_authoring",
        },
    }


def build_interrupt_policy() -> dict[str, object]:
    return {
        "approval_interrupts": [
            "solution_design_approval",
            "code_review_approval",
        ],
        "clarification_interrupt": "clarification_request",
        "tool_confirmation_interrupt": "tool_confirmation",
    }


def stage_allowed_tools() -> dict[StageType, list[str]]:
    return {
        StageType.REQUIREMENT_ANALYSIS: [],
        StageType.SOLUTION_DESIGN: ["read_file", "glob", "grep"],
        StageType.CODE_GENERATION: [
            "read_file",
            "glob",
            "grep",
            "write_file",
            "edit_file",
        ],
        StageType.TEST_GENERATION_EXECUTION: [
            "read_file",
            "glob",
            "grep",
            "write_file",
            "edit_file",
            "bash",
        ],
        StageType.CODE_REVIEW: ["read_file", "glob", "grep"],
        StageType.DELIVERY_INTEGRATION: [
            "read_delivery_snapshot",
            "prepare_branch",
            "create_commit",
            "push_branch",
            "create_code_review_request",
        ],
    }


__all__ = [
    "FrozenDict",
    "FrozenList",
    "GRAPH_DEFINITION_SCHEMA_VERSION",
    "GRAPH_DEFINITION_VERSION",
    "GraphDefinition",
    "build_fixed_stage_sequence",
    "build_interrupt_policy",
    "build_solution_design_node_group",
    "stage_allowed_tools",
]
